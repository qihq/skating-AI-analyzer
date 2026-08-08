from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import cv2

from app.services.analysis_errors import AnalysisErrorCode, AnalysisPipelineError
from app.services.bio_context import (
    build_frame_bio_context,
    extract_key_frame_stems,
    summarize_jump_metrics,
)
from app.services.cross_validator import (
    CrossValidationReport,
    compute_blend_weights,
    cross_validate,
)
from app.services.frame_annotator import annotate_frames_batch, build_pose_by_stem
from app.services.llm_context import AnalysisPromptContext, render_prompt_context
from app.services.providers import ActiveProviderConfig
from app.services.pose import extract_pose
from app.services.video import FramePayload, encode_frames
from app.services.vision_path_a import analyze_path_a
from app.services.vision_path_b import PATH_B_MAX_FRAMES, PathBFrameSelection, analyze_path_b, select_stage_balanced_frames
from app.services.video_temporal import semantic_keyframes_are_reliable
from app.services.vision_video_context import build_video_context_by_frame
from app.analysis_v2.claim_fusion import ClaimSourceState, fuse_evidence_claims, source_state_from_payload
from app.analysis_v2.contracts import EvidenceClaim
from app.analysis_v2.fusion_inputs import (
    build_deterministic_claims,
    build_event_candidate_claims,
    build_event_window_claims,
    canonicalize_single_event_scope,
    claims_from_payload,
    derive_event_scopes_from_motion,
    scope_claims_to_events,
    v2_pipeline_fingerprint,
)


logger = logging.getLogger(__name__)

DUAL_PATH_TOTAL_TIMEOUT = 150.0
PATH_B_TIMEOUT = 120.0
PATH_B_IMAGE_MAX_WIDTH = 640
PATH_B_IMAGE_JPEG_QUALITY = 72
PATH_A_ERROR_EXCERPT_CHARS = 1200
SEMANTIC_MANUAL_LOCK_BLANK_POSE_FLAG = "semantic_pose_manual_lock_unaligned_blank_pose"

# Path A is deliberately stricter than the historical dual-path adapter.  A
# clip that is not explicitly produced by the target-crop adapter must never
# be sent to the V2 visual reviewer: an action-window clip can contain another
# skater and would make the model an accidental identity authority.
TARGET_CLIP_ARTIFACT_KIND = "target_focused_marked_crop"
TARGET_CLIP_ARTIFACT_UNVERIFIED = "target_focused_marked_crop_unverified"


def _sha256_file(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return "sha256:" + digest.hexdigest()
    except (OSError, ValueError):
        return None


def _normalized_bbox_for_frame(
    target_lock: dict[str, Any] | None,
    frame_index: int,
    *,
    frame_id: str | None = None,
) -> dict[str, float] | None:
    if not isinstance(target_lock, dict):
        return None
    values = target_lock.get("bbox_per_frame")
    bbox: Any = None
    # Semantic keyframes are materialized from source PTS and do not share the
    # sampled-frame array index.  Never apply another sampled frame's bbox to a
    # semantic frame; use the confirmed anchor bbox unless an explicit mapping
    # is persisted.
    if isinstance(frame_id, str) and frame_id.startswith("semantic_"):
        values = None
    if isinstance(values, list) and values:
        if 0 <= frame_index < len(values):
            bbox = values[frame_index]
        else:
            bbox = values[-1]
    if not isinstance(bbox, dict):
        bbox = target_lock.get("selected_bbox")
    if not isinstance(bbox, dict):
        return None
    try:
        x = float(bbox.get("x", 0.0) or 0.0)
        y = float(bbox.get("y", 0.0) or 0.0)
        width = float(bbox.get("width", bbox.get("w", 0.0)) or 0.0)
        height = float(bbox.get("height", bbox.get("h", 0.0)) or 0.0)
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    # Tracker payloads are normalized.  Clamp rather than allowing a malformed
    # diagnostic to make OpenCV index outside the image.
    x = max(0.0, min(1.0, x))
    y = max(0.0, min(1.0, y))
    width = max(0.0, min(1.0 - x, width))
    height = max(0.0, min(1.0 - y, height))
    return {"x": x, "y": y, "width": width, "height": height}


def _crop_and_mark_target_frame(
    image: Any,
    bbox: dict[str, float] | None,
    *,
    padding_ratio: float = 0.75,
    label: str = "TARGET",
) -> Any:
    """Crop around the confirmed target, retain context, and mark the target.

    The crop is intentionally generous (75% of the target extent on each side)
    so travel/ice-contact context remains visible while unrelated skaters are
    less likely to become the apparent subject.  Coordinates are normalized
    and clamped before indexing the image.
    """

    if bbox is None or image is None or getattr(image, "size", 0) == 0:
        return image
    try:
        height, width = image.shape[:2]
        x = float(bbox["x"])
        y = float(bbox["y"])
        w = float(bbox["width"])
        h = float(bbox["height"])
        left = int(round((x - w * padding_ratio) * width))
        top = int(round((y - h * padding_ratio) * height))
        right = int(round((x + w + w * padding_ratio) * width))
        bottom = int(round((y + h + h * padding_ratio) * height))
        left = max(0, min(width - 1, left))
        top = max(0, min(height - 1, top))
        right = max(left + 1, min(width, right))
        bottom = max(top + 1, min(height, bottom))
        crop = image[top:bottom, left:right].copy()
        crop_h, crop_w = crop.shape[:2]
        rel_left = int(round((x * width - left)))
        rel_top = int(round((y * height - top)))
        rel_right = int(round((x * width + w * width - left)))
        rel_bottom = int(round((y * height + h * height - top)))
        rel_left = max(0, min(crop_w - 1, rel_left))
        rel_top = max(0, min(crop_h - 1, rel_top))
        rel_right = max(rel_left + 1, min(crop_w - 1, rel_right))
        rel_bottom = max(rel_top + 1, min(crop_h - 1, rel_bottom))
        cv2.rectangle(crop, (rel_left, rel_top), (rel_right, rel_bottom), (0, 215, 255), 2)
        # Keep the marker compact; it is a visual cue, never a source-time
        # annotation.  OpenCV's fallback font is available in all runtimes.
        cv2.putText(crop, label, (rel_left + 3, max(16, rel_top - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 215, 255), 1, cv2.LINE_AA)
    except Exception:  # noqa: BLE001
        return image
    return crop


def _target_marked_frame_payloads(
    frame_paths: Sequence[Path],
    raw_payloads: Sequence[FramePayload],
    *,
    target_lock: dict[str, Any] | None,
    output_dir: Path,
) -> tuple[list[FramePayload], dict[str, Any]]:
    """Create marked frame evidence for the safe frames-only Path A retry.

    The original payload list is never mutated.  If a frame cannot be read or
    marked, it is omitted rather than silently exposing an unmarked frame.
    """

    if not raw_payloads:
        return [], {"artifact_kind": TARGET_CLIP_ARTIFACT_UNVERIFIED, "frame_count": 0, "source_frame_count": 0}
    output_dir.mkdir(parents=True, exist_ok=True)
    by_stem = {path.stem: path for path in frame_paths}
    frame_index_by_stem = {path.stem: index for index, path in enumerate(frame_paths)}
    marked_paths: list[Path] = []
    for index, payload in enumerate(raw_payloads):
        source = by_stem.get(payload.frame_id)
        if source is None:
            continue
        image = cv2.imread(str(source))
        if image is None:
            continue
        bbox = _normalized_bbox_for_frame(
            target_lock,
            frame_index_by_stem.get(source.stem, index),
            frame_id=payload.frame_id,
        )
        if bbox is None:
            continue
        marked = _crop_and_mark_target_frame(image, bbox)
        destination = output_dir / f"{source.stem}_target.jpg"
        if not cv2.imwrite(str(destination), marked):
            continue
        marked_paths.append(destination)

    if len(marked_paths) != len(raw_payloads):
        # A partial marked set is unsafe: frame alignment would be ambiguous.
        return [], {"artifact_kind": TARGET_CLIP_ARTIFACT_UNVERIFIED, "frame_count": len(marked_paths), "source_frame_count": len(raw_payloads)}
    timestamps = {payload.frame_id: payload.timestamp_sec for payload in raw_payloads}
    encoded = [
        FramePayload(
            frame_id=path.stem.removesuffix("_target"),
            data_url=f"data:image/jpeg;base64,{base64.b64encode(path.read_bytes()).decode('utf-8')}",
            timestamp_sec=float(timestamps.get(path.stem.removesuffix("_target"), 0.0)),
        )
        for path in marked_paths
    ]
    return encoded, {
        "artifact_kind": TARGET_CLIP_ARTIFACT_KIND,
        "frame_count": len(encoded),
        "source_frame_count": len(raw_payloads),
        "fingerprint": "sha256:" + hashlib.sha256("".join(_sha256_file(path) or "" for path in marked_paths).encode("utf-8")).hexdigest(),
        "crop_padding_ratio": 0.75,
    }


def _identity_conflicts_from_target_lock(
    target_lock: dict[str, Any] | None,
    *,
    frame_payloads: Sequence[FramePayload],
    window_start_sec: float = 0.0,
    effective_fps: float | None = None,
) -> list[dict[str, Any]]:
    """Convert tracker diagnostics into conservative source-PTS intervals."""

    if not isinstance(target_lock, dict):
        return []
    diagnostics = target_lock.get("person_tracker_diagnostics")
    if not isinstance(diagnostics, list) or not diagnostics:
        diagnostics = []
    # Older frame encoders/test adapters may omit timestamps.  Treat those
    # payloads as action-window-relative zero rather than failing the whole
    # vision stage; real FramePayload instances still provide source PTS.
    def _payload_timestamp(item: Any) -> float:
        value = getattr(item, "timestamp_sec", 0.0)
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _payload_frame_id(item: Any) -> str:
        return str(getattr(item, "frame_id", "") or "")

    payload_times = [_payload_timestamp(item) for item in frame_payloads]
    # Some resumed/legacy samplers persist all timestamps as zero/relative to
    # the action window while the claim timeline is source-PTS based.  Promote
    # only an all-zero payload; any positive timestamp is treated as an
    # absolute source PTS (the normal case) and remains unchanged.
    timestamp_offset = 0.0
    if payload_times and window_start_sec > 0 and max(payload_times) <= 0.0:
        timestamp_offset = float(window_start_sec)
    frame_timestamps = {_payload_frame_id(item): _payload_timestamp(item) + timestamp_offset for item in frame_payloads}
    observed_steps = [
        right - left
        for left, right in zip(
            (_payload_timestamp(item) for item in frame_payloads),
            (_payload_timestamp(item) for item in frame_payloads[1:]),
        )
        if right > left
    ]
    inferred_step = min(observed_steps) if observed_steps else 1.0 / 30.0
    inferred_fps = float(effective_fps or (1.0 / inferred_step if inferred_step > 0 else 30.0))
    conflict_states = {
        "lost", "lost_reused", "uncertain", "relock_pending", "relock_rejected",
        "continuity_rejected", "full_frame_yolo_relock_pending", "local_zoom_yolo_relock_pending",
        "false_relock", "identity_conflict", "wrong_person", "recovery",
    }
    intervals: list[dict[str, Any]] = []
    for index, item in enumerate(diagnostics):
        if not isinstance(item, dict):
            continue
        state = str(item.get("state") or item.get("tracking_state") or item.get("tracker_state") or "").strip().lower()
        reasons = {str(value).strip().lower() for value in (item.get("rejected_reasons") or ()) if str(value).strip()}
        flags = {str(value).strip().lower() for value in (item.get("quality_flags") or ()) if str(value).strip()}
        is_conflict = state in conflict_states or any(
            token in candidate
            for token in ("relock", "identity", "wrong_person", "crossing", "lost", "uncertain")
            for candidate in (state, *reasons, *flags)
        )
        if not is_conflict:
            is_conflict = any(token in state for token in ("relock", "lost", "uncertain", "conflict"))
        if not is_conflict:
            continue
        timestamp: float | None = None
        for key in ("pts_sec", "timestamp_sec", "timestamp", "time_sec"):
            value = item.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                timestamp = float(value)
                break
        if timestamp is None:
            frame_name = str(item.get("frame") or item.get("frame_id") or "").strip()
            timestamp = frame_timestamps.get(Path(frame_name).stem)
        if timestamp is None:
            raw_index = item.get("frame_index", index)
            try:
                timestamp = float(window_start_sec) + float(raw_index) / max(inferred_fps, 1.0)
            except (TypeError, ValueError):
                timestamp = float(window_start_sec)
        reason = "false_relock" if ("false" in state or "wrong" in state or "false_relock" in reasons) else (
            "recovery" if "relock" in state or "recovery" in state else "low_margin"
        )
        candidate_ids = tuple(str(value) for value in (item.get("candidate_ids") or item.get("rejected_candidate_ids") or ()) if str(value).strip())
        try:
            frame_index = int(item.get("frame_index", index))
        except (TypeError, ValueError):
            frame_index = index
        intervals.append({
            "start_pts_sec": max(0.0, timestamp),
            "end_pts_sec": max(0.0, timestamp),
            "reason": reason,
            "frame_indices": (frame_index,),
            "candidate_ids": candidate_ids,
        })

    # Any target-lock quality flag indicating multiperson or terminal loss is a
    # conflict even if the tracker did not emit per-frame diagnostics.
    quality_flags = {str(value).lower() for value in (target_lock.get("quality_flags") or ()) if str(value).strip()}
    if any("multiperson" in flag or "relock_instability" in flag or "final_unrecovered" in flag or "target_lost" in flag for flag in quality_flags) and not intervals:
        start = max(0.0, float(window_start_sec))
        last_timestamp = _payload_timestamp(frame_payloads[-1]) if frame_payloads else start
        end = max(start, last_timestamp if last_timestamp >= start else start + max(last_timestamp, 0.0))
        intervals.append({"start_pts_sec": start, "end_pts_sec": end, "reason": "crossing", "frame_indices": (), "candidate_ids": ()})

    # Merge nearby diagnostics into stable intervals.  This avoids making the
    # family UI show one warning for every sampled frame.
    intervals.sort(key=lambda item: (item["start_pts_sec"], item["end_pts_sec"]))
    merged: list[dict[str, Any]] = []
    frame_step = max(inferred_step, 1.0 / 120.0)
    for item in intervals:
        if merged and item["start_pts_sec"] <= merged[-1]["end_pts_sec"] + frame_step * 1.5:
            current = merged[-1]
            current["end_pts_sec"] = max(current["end_pts_sec"], item["end_pts_sec"])
            current["frame_indices"] = tuple(dict.fromkeys((*current.get("frame_indices", ()), *item.get("frame_indices", ()))))
            current["candidate_ids"] = tuple(dict.fromkeys((*current.get("candidate_ids", ()), *item.get("candidate_ids", ()))))
        else:
            merged.append(dict(item))
    return merged


def _dedupe_identity_conflicts(values: Sequence[Any]) -> list[Any]:
    """Keep stable conflict records when router and dual adapter both enrich identity."""

    output: list[Any] = []
    seen: set[tuple[float, float, str]] = set()
    for value in values:
        if isinstance(value, dict):
            try:
                key = (
                    round(float(value.get("start_pts_sec", value.get("start_pts", 0.0))), 6),
                    round(float(value.get("end_pts_sec", value.get("end_pts", 0.0))), 6),
                    str(value.get("reason") or "low_margin"),
                )
            except (TypeError, ValueError):
                output.append(value)
                continue
        else:
            key = (
                round(float(getattr(value, "start_pts_sec", 0.0)), 6),
                round(float(getattr(value, "end_pts_sec", 0.0)), 6),
                str(getattr(value, "reason", "low_margin")),
            )
        if key in seen:
            continue
        seen.add(key)
        output.append(value)
    return output


def _motion_features_for_prompt(frame_motion_scores: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(frame_motion_scores, dict):
        return {}
    summary: dict[str, Any] = {}
    for key in ("sample_count", "quality_flags", "analysis_profile_hint", "selected"):
        value = frame_motion_scores.get(key)
        if value is not None:
            summary[key] = value
    scores = frame_motion_scores.get("scores")
    if isinstance(scores, list):
        numeric_scores = [float(score) for score in scores if isinstance(score, (int, float))]
        summary["scores"] = numeric_scores[:20]
        if numeric_scores:
            summary["score_summary"] = {
                "count": len(numeric_scores),
                "max": round(max(numeric_scores), 4),
                "min": round(min(numeric_scores), 4),
                "avg": round(sum(numeric_scores) / len(numeric_scores), 4),
            }
    return summary


def _selected_semantic_frame_ids(resolved_keyframes: dict[str, Any] | None) -> set[str]:
    selected = resolved_keyframes.get("selected") if isinstance(resolved_keyframes, dict) else None
    if not isinstance(selected, list):
        return set()
    frame_ids: set[str] = set()
    for item in selected:
        if not isinstance(item, dict):
            continue
        frame_id = str(item.get("frame_id") or "").strip()
        if not frame_id.startswith("semantic_"):
            continue
        frame_ids.add(frame_id)
    return frame_ids


def _uses_semantic_keyframes(
    resolved_keyframes: dict[str, Any] | None,
    raw_frame_payloads: list[FramePayload] | None = None,
) -> bool:
    if semantic_keyframes_are_reliable(resolved_keyframes):
        return True
    source = str(resolved_keyframes.get("source") or "") if isinstance(resolved_keyframes, dict) else ""
    if source not in {"video_ai_refined", "blended"}:
        return False
    semantic_frame_ids = _selected_semantic_frame_ids(resolved_keyframes)
    if not semantic_frame_ids or not raw_frame_payloads:
        return False
    payload_ids = {payload.frame_id for payload in raw_frame_payloads}
    return semantic_frame_ids <= payload_ids


def _path_a_error_payload(error: str, detail: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "path": "A",
        "error": error,
        "frame_analysis": [],
        "action_phase_summary": {"detected_phases": [], "weakest_phase": "", "strongest_phase": ""},
        "pure_vision_subscores": {},
        "quality_flags": ["path_a_unavailable_fallback"],
    }
    if detail:
        payload["error_detail"] = detail[:PATH_A_ERROR_EXCERPT_CHARS]
    # Keep a claim-shaped refusal in V2 so fusion/reporting can surface the
    # unavailable state even when the provider was never called.
    payload["evidence_claims"] = [{
        "claim_type": "action_family_support",
        "value": None,
        "sources": ("path_a",),
        "confidence": 0.0,
        "observability": "unobservable",
        "status": "unobservable",
        "refusal_reason": str(error),
        "review_task": "confirm_target_clip",
        "provenance": ("target_clip_review", "refused"),
    }]
    return payload


def _semantic_pose_for_annotation(
    frame_paths: list[Path],
    work_dir: Path,
    *,
    target_lock: dict[str, Any] | None = None,
    effective_fps: float | None = None,
) -> dict[str, Any]:
    manual_lock_mode = bool(isinstance(target_lock, dict) and target_lock.get("manual_override"))
    if manual_lock_mode:
        return {
            "frames": [],
            "connections": [],
            "quality_flags": [SEMANTIC_MANUAL_LOCK_BLANK_POSE_FLAG],
            "pose_diagnostics": {
                "total_frames": len(frame_paths),
                "tracked_frames": 0,
                "lost_frames": len(frame_paths),
                "low_confidence_frames": len(frame_paths),
                "manual_lock_unaligned_semantic_frames": len(frame_paths),
            },
        }

    pose_input_dir = work_dir / "_semantic_pose_input"
    if pose_input_dir.exists():
        shutil.rmtree(pose_input_dir, ignore_errors=True)
    pose_input_dir.mkdir(parents=True, exist_ok=True)
    rename_map: dict[str, str] = {}
    for index, frame_path in enumerate(frame_paths, start=1):
        target = pose_input_dir / f"frame_{index:04d}.jpg"
        shutil.copy2(frame_path, target)
        rename_map[target.name] = frame_path.name

    pose_payload = extract_pose(str(pose_input_dir), effective_fps=effective_fps)
    frames = pose_payload.get("frames") if isinstance(pose_payload, dict) else None
    if isinstance(frames, list):
        remapped: list[dict[str, Any]] = []
        for frame in frames:
            if not isinstance(frame, dict):
                continue
            item = dict(frame)
            frame_name = item.get("frame")
            if isinstance(frame_name, str) and frame_name in rename_map:
                item["frame"] = rename_map[frame_name]
            remapped.append(item)
        pose_payload = {**pose_payload, "frames": remapped}
    return pose_payload if isinstance(pose_payload, dict) else {"frames": [], "connections": []}


def _compress_frame_payloads_for_path_b(
    frame_paths: list[Path],
    payloads: list[FramePayload],
    *,
    max_width: int = PATH_B_IMAGE_MAX_WIDTH,
    jpeg_quality: int = PATH_B_IMAGE_JPEG_QUALITY,
) -> list[FramePayload]:
    by_stem = {path.stem: path for path in frame_paths}
    compressed: list[FramePayload] = []
    for payload in payloads:
        frame_path = by_stem.get(payload.frame_id)
        if frame_path is None:
            compressed.append(payload)
            continue
        image = cv2.imread(str(frame_path))
        if image is None:
            compressed.append(payload)
            continue
        height, width = image.shape[:2]
        if width > max_width:
            scale = max_width / float(width)
            image = cv2.resize(image, (max_width, max(1, int(round(height * scale)))), interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)])
        if not ok:
            compressed.append(payload)
            continue
        compressed.append(
            FramePayload(
                frame_id=payload.frame_id,
                data_url=f"data:image/jpeg;base64,{base64.b64encode(encoded.tobytes()).decode('utf-8')}",
                timestamp_sec=payload.timestamp_sec,
            )
        )
    return compressed


@dataclass(slots=True)
class DualPathResult:
    path_a: dict[str, Any]
    path_b: dict[str, Any] | None
    validation: CrossValidationReport
    blend_weights: tuple[float, float]
    dual_path_meta: dict[str, Any]
    annotated_dir: Path | None
    used_key_frames: set[str]
    fused_claims: tuple[EvidenceClaim, ...] = ()
    fusion_result: Any | None = None


async def analyze_frames_dual(
    action_type: str,
    frame_paths: list[Path],
    raw_frame_payloads: list[FramePayload],
    pose_data: dict[str, Any] | None,
    bio_data: dict[str, Any] | None,
    provider_path_a: ActiveProviderConfig,
    provider_path_b: ActiveProviderConfig,
    *,
    frame_motion_scores: dict[str, Any] | None = None,
    action_subtype: str | None = None,
    analysis_profile: str | None = None,
    profile_evidence: dict[str, Any] | None = None,
    memory_context: str = "",
    annotated_dir: Path | None = None,
    timestamps: dict[str, float] | None = None,
    clip_path: Path | None = None,
    window_start_sec: float = 0.0,
    total_timeout: float = DUAL_PATH_TOTAL_TIMEOUT,
    path_b_timeout: float = PATH_B_TIMEOUT,
    skill_category: str | None = None,
    prompt_context: AnalysisPromptContext | None = None,
    video_temporal: dict[str, Any] | None = None,
    resolved_keyframes: dict[str, Any] | None = None,
    target_lock: dict[str, Any] | None = None,
    v2_mode: bool = False,
    analysis_id: str | None = None,
    target_clip_policy: dict[str, Any] | None = None,
    structured_measurements: list[dict[str, Any]] | dict[str, Any] | None = None,
    required_joints: Sequence[str] = (),
    identity_state: str = "unknown",
    identity: Any | None = None,
    source_fingerprints: dict[str, str] | None = None,
) -> DualPathResult:
    """
    Run dual-path analysis and cross validation.

    Path A keeps the hard-error contract from analyze_frames/analyze_path_a.
    Path B keeps a soft-error contract and returns {"error": "..."} on failure.
    """
    if annotated_dir is None:
        annotated_dir = (frame_paths[0].parent.parent / "annotated") if frame_paths else Path("/tmp/annotated")

    # V2 Path A is fail-closed unless the target is confirmed and every input
    # frame can be represented as a target-focused, marked crop.  Path B keeps
    # consuming the original source-linked/annotated frames below.
    path_a_frame_payloads = list(raw_frame_payloads)
    target_artifact: dict[str, Any] = {
        "artifact_kind": TARGET_CLIP_ARTIFACT_UNVERIFIED,
        "frame_count": 0,
        "source_frame_count": len(raw_frame_payloads),
    }
    target_policy_errors: tuple[str, ...] = ()
    if v2_mode:
        from app.analysis_v2.path_review import target_clip_policy_from

        target_policy = target_clip_policy_from(target_clip_policy)
        target_policy_errors = target_policy.validate()
        if not target_policy_errors and identity_state == "confirmed" and isinstance(target_lock, dict):
            path_a_frame_payloads, target_artifact = await asyncio.to_thread(
                _target_marked_frame_payloads,
                frame_paths,
                raw_frame_payloads,
                target_lock=target_lock,
                output_dir=annotated_dir.parent / "target_clip",
            )
            if target_artifact.get("artifact_kind") != TARGET_CLIP_ARTIFACT_KIND:
                target_policy_errors = ("target_marking_failed",)
        elif not target_policy_errors:
            target_policy_errors = ("identity_not_confirmed",)

    effective_target_clip_policy = dict(target_clip_policy or {})
    effective_source_fingerprints = dict(source_fingerprints or {})
    if target_artifact.get("fingerprint"):
        effective_target_clip_policy["artifact_kind"] = target_artifact.get("artifact_kind")
        effective_target_clip_policy["artifact_fingerprint"] = target_artifact.get("fingerprint")
        effective_source_fingerprints["target_clip_artifact"] = str(target_artifact["fingerprint"])

    uses_semantic_keyframes = _uses_semantic_keyframes(resolved_keyframes, raw_frame_payloads)
    annotation_pose_data = pose_data
    annotation_source = "main_pose"
    if uses_semantic_keyframes:
        try:
            effective_fps = None
            if isinstance(frame_motion_scores, dict):
                raw_fps = frame_motion_scores.get("effective_fps")
                effective_fps = float(raw_fps) if isinstance(raw_fps, (int, float)) else None
            annotation_pose_data = await asyncio.to_thread(
                _semantic_pose_for_annotation,
                frame_paths,
                annotated_dir.parent,
                target_lock=target_lock,
                effective_fps=effective_fps,
            )
            annotation_flags = (
                annotation_pose_data.get("quality_flags")
                if isinstance(annotation_pose_data, dict) and isinstance(annotation_pose_data.get("quality_flags"), list)
                else []
            )
            annotation_source = (
                "semantic_manual_lock_blank_pose"
                if SEMANTIC_MANUAL_LOCK_BLANK_POSE_FLAG in annotation_flags
                else "semantic_light_pose"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Semantic frame light pose failed; Path B will use original semantic frames: %s", exc)
            annotation_pose_data = {"frames": [], "connections": []}
            annotation_source = "semantic_pose_failed_original_frames"

    pose_by_stem = build_pose_by_stem(annotation_pose_data)
    connections = annotation_pose_data.get("connections") if isinstance(annotation_pose_data, dict) else None
    annotated_paths = annotate_frames_batch(
        frame_paths,
        pose_by_stem,
        annotated_dir,
        connections=connections if isinstance(connections, list) else None,
    )
    annotated_payloads = await encode_frames(annotated_paths, timestamps=timestamps)
    compressed_annotated_payloads = _compress_frame_payloads_for_path_b(annotated_paths, annotated_payloads)
    video_context_by_frame = build_video_context_by_frame(
        raw_frame_payloads,
        video_temporal=video_temporal,
        resolved_keyframes=resolved_keyframes,
    )

    frame_stems = [payload.frame_id for payload in raw_frame_payloads]
    key_stems = extract_key_frame_stems(bio_data)
    evidence_frames = frame_motion_scores.get("evidence_frames_v1") if isinstance(frame_motion_scores, dict) else None
    if uses_semantic_keyframes:
        path_b_selection = PathBFrameSelection(
            compressed_annotated_payloads,
            {},
            ["resolved_semantic"],
            0,
            "semantic_frames_preserved",
            {},
        )
    else:
        path_b_selection = select_stage_balanced_frames(
            compressed_annotated_payloads,
            evidence_frames if isinstance(evidence_frames, dict) else None,
            analysis_profile=analysis_profile,
            max_frames=PATH_B_MAX_FRAMES,
        )
    path_b_payloads = path_b_selection.frames
    bio_ctx = build_frame_bio_context(bio_data, frame_stems)
    jump_metrics_text = summarize_jump_metrics(bio_data)
    motion_features = _motion_features_for_prompt(frame_motion_scores)
    # V2 reviewers have separate, explicit input contracts.  The Path A
    # target-clip prompt owns its action-family hint and target policy, while
    # Path B receives only ``structured_measurements`` below.  Do not append
    # the historical prompt context here: it contains motion/bio payloads and
    # user-facing timing hints that would turn either model into an accidental
    # authority.  Legacy dual-path calls retain the historical context blocks.
    if v2_mode:
        path_a_context = ""
        path_b_context = ""
    else:
        path_a_context = (
            render_prompt_context(
                prompt_context,
                include_bio=False,
                include_profile_evidence=False,
            )
            if prompt_context is not None
            else memory_context
        )
        path_b_context = (
            render_prompt_context(prompt_context, include_bio=True)
            if prompt_context is not None
            else memory_context
        )

    provider_fingerprints = {
        "path_a": str(getattr(provider_path_a, "fingerprint", "")),
        "path_b": str(getattr(provider_path_b, "fingerprint", "")),
    }
    pipeline_fingerprint = v2_pipeline_fingerprint(
        analysis_id=str(analysis_id or "unknown"),
        provider_fingerprints=effective_source_fingerprints or provider_fingerprints,
        configuration={"analysis_profile": analysis_profile, "v2_mode": v2_mode},
    )

    async def _run_a() -> dict[str, Any]:
        if v2_mode and target_policy_errors:
            return _path_a_error_payload("target_clip_unavailable", ";".join(target_policy_errors))
        return await analyze_path_a(
            action_type=action_type,
            frame_payloads=path_a_frame_payloads,
            provider=provider_path_a,
            action_subtype=action_subtype,
            analysis_profile=analysis_profile,
            profile_evidence=None,
            bio_data=bio_data,
            motion_features=motion_features,
            memory_context=path_a_context,
            # The full action-window clip is a compatibility artifact.  V2
            # never gives it to a model that could choose the subject.
            mode="frames",
            clip_path=None,
            window_start_sec=window_start_sec,
            skill_category=skill_category,
            video_context_by_frame=video_context_by_frame,
            v2_mode=v2_mode,
            target_clip_policy=effective_target_clip_policy,
            source_fingerprints=effective_source_fingerprints or provider_fingerprints,
        )

    async def _run_b() -> dict[str, Any]:
        if not path_b_payloads:
            return {
                "path": "B",
                "error": "skipped_no_annotated_frames",
                "n_frames": 0,
                "frame_analysis": [],
            }
        return await analyze_path_b(
            action_type=action_type,
            annotated_frame_payloads=path_b_payloads,
            provider=provider_path_b,
            frame_bio_context=bio_ctx,
            key_frame_stems=key_stems,
            jump_metrics_text=jump_metrics_text,
            action_subtype=action_subtype,
            analysis_profile=analysis_profile,
            profile_evidence=profile_evidence,
            memory_context=path_b_context,
            skill_category=skill_category,
            video_context_by_frame=video_context_by_frame,
            evidence_context_by_frame=path_b_selection.evidence_context_by_frame,
            preserve_all_frames=uses_semantic_keyframes,
            v2_mode=v2_mode,
            structured_measurements=structured_measurements,
            required_joints=tuple(required_joints),
            identity_state=identity_state,
            source_fingerprints=effective_source_fingerprints or provider_fingerprints,
        )

    path_a_task = asyncio.create_task(_run_a())
    path_b_task = asyncio.create_task(_run_b())
    try:
        path_b_result = await asyncio.wait_for(path_b_task, timeout=path_b_timeout)
    except asyncio.TimeoutError:
        logger.warning("Path B timeout > %.0fs; continuing with Path A result", path_b_timeout)
        path_b_result = {
            "path": "B",
            "error": "path_b_timeout",
            "timeout_seconds": round(float(path_b_timeout), 3),
            "n_frames": len(path_b_payloads),
            "annotated_frame_count": len(path_b_payloads),
            "frame_analysis": [],
        }
    try:
        path_a_result = await asyncio.wait_for(path_a_task, timeout=total_timeout)
    except asyncio.TimeoutError:
        logger.warning("Path A timeout > %.0fs; using error result", total_timeout)
        path_a_result = {"path": "A", "error": "path_a_timeout"}
    except AnalysisPipelineError as exc:
        if exc.code != AnalysisErrorCode.AI_RESPONSE_PARSE_FAIL:
            raise
        logger.warning("Path A parse failed; continuing with Path B/fallback report: %s", exc.detail)
        path_a_result = _path_a_error_payload("path_a_parse_failed", exc.detail)

    validation = cross_validate(path_a_result, path_b_result)
    weights = compute_blend_weights(validation)
    fusion_diagnostics = validation.fusion_diagnostics

    dual_meta: dict[str, Any] = {
        "overall_agreement_rate": validation.overall_agreement_rate,
        "skeleton_reliability_signal": validation.skeleton_reliability_signal,
        "recommended_path": validation.recommended_path,
        "conflict_fields": validation.conflict_fields,
        "conflict_summary": validation.conflict_summary,
        "weight_a": weights[0],
        "weight_b": weights[1],
        "path_b_subscores": (path_b_result or {}).get("subscores"),
        "path_a_failed": bool(path_a_result and path_a_result.get("error")),
        "path_a_error": (path_a_result or {}).get("error") if isinstance(path_a_result, dict) else None,
        "path_b_failed": bool(path_b_result and path_b_result.get("error")),
        "path_b_error": (path_b_result or {}).get("error") if isinstance(path_b_result, dict) else None,
        "path_b_annotation_source": annotation_source,
        "path_b_preserve_all_frames": uses_semantic_keyframes,
        "raw_frame_count": len(raw_frame_payloads),
        "annotated_frame_count": len(path_b_payloads),
        "annotated_frame_count_raw": len(annotated_payloads),
        "path_b_stage_counts": path_b_selection.per_stage_count,
        "path_b_evidence_sources": path_b_selection.sources,
        "path_b_omitted_context_count": path_b_selection.omitted_context_count,
        "path_b_cap_reason": path_b_selection.cap_reason,
        "fusion_diagnostics": fusion_diagnostics,
        "conflict_level": fusion_diagnostics.get("conflict_level", "none"),
        "downgraded_reasons": fusion_diagnostics.get("downgraded_reasons", []),
        "needs_human_review": bool(fusion_diagnostics.get("needs_human_review", False)),
        "target_clip_artifact": target_artifact,
        "target_clip_policy_errors": list(target_policy_errors),
        "path_a_frame_count": len(path_a_frame_payloads),
    }

    fused_claims: tuple[EvidenceClaim, ...] = ()
    fusion_result = None
    if v2_mode:
        event_id = f"{analysis_id}:event:0" if analysis_id else None
        # Keep the legacy single-event compatibility path when no proposal
        # scopes are available.  Once multiple scopes exist, action/measurement
        # claims stay whole-analysis until a source-linked per-event extractor
        # can prove their interval; only proposal claims are event-scoped.
        derived_event_scopes = derive_event_scopes_from_motion(
            analysis_id=str(analysis_id or "unknown"),
            source_video_hash=str(((frame_motion_scores or {}).get("video_identity") or {}).get("sha256") or f"analysis:{analysis_id or 'unknown'}") if isinstance(frame_motion_scores, dict) else f"analysis:{analysis_id or 'unknown'}",
            motion_scores=frame_motion_scores,
            pipeline_fingerprint=pipeline_fingerprint,
        )
        multi_event = len(derived_event_scopes) > 1
        # Keep the ordinary one-event contract stable.  Proposal IDs are
        # content-derived (``evt-*``), whereas the historical V2 event uses
        # ``analysis:event:0``.  A sole proposal must not create a second
        # presenter event; retain its original ID only in source references.
        event_scopes = canonicalize_single_event_scope(
            derived_event_scopes,
            analysis_id=str(analysis_id or "unknown"),
            canonical_event_id=event_id,
        )
        deterministic_claims = build_deterministic_claims(
            analysis_id=str(analysis_id or "unknown"),
            action_profile=analysis_profile,
            bio_data=bio_data,
            pose_data=pose_data,
            target_lock=target_lock,
            pipeline_fingerprint=pipeline_fingerprint,
            event_id=None if multi_event else event_id,
            whole_analysis=multi_event,
        )
        claims_a = claims_from_payload(path_a_result, analysis_id=str(analysis_id or "unknown"), source="path_a", event_id=None if multi_event else event_id, fingerprint=provider_fingerprints["path_a"], whole_analysis=multi_event)
        claims_b = claims_from_payload(path_b_result, analysis_id=str(analysis_id or "unknown"), source="path_b", event_id=None if multi_event else event_id, fingerprint=provider_fingerprints["path_b"], whole_analysis=multi_event)
        if multi_event:
            # Only claims carrying an exact source-PTS point/interval are
            # localized.  Path A observations and aggregate Path B metrics
            # remain whole-analysis; no interval is guessed from frame order.
            deterministic_claims = scope_claims_to_events(
                deterministic_claims,
                scopes=event_scopes,
                analysis_id=str(analysis_id or "unknown"),
            )
            claims_a = scope_claims_to_events(
                claims_a,
                scopes=event_scopes,
                analysis_id=str(analysis_id or "unknown"),
            )
            claims_b = scope_claims_to_events(
                claims_b,
                scopes=event_scopes,
                analysis_id=str(analysis_id or "unknown"),
            )
        # Ordinary V2 analyses may contain more than one deterministic action
        # window.  Proposal scopes are evidence-only: they do not classify the
        # family or move Path A/B authority into event localization.  Persist
        # them as event-scoped claims so the presenter can render an ordered,
        # uncertainty-aware multi-event timeline.
        source_video_hash = str(((frame_motion_scores or {}).get("video_identity") or {}).get("sha256") or "") if isinstance(frame_motion_scores, dict) else ""
        event_window_claims = build_event_window_claims(
            analysis_id=str(analysis_id or "unknown"),
            scopes=event_scopes,
            pipeline_fingerprint=pipeline_fingerprint,
        )
        event_candidate_claims = build_event_candidate_claims(
            analysis_id=str(analysis_id or "unknown"),
            scopes=event_scopes,
            pipeline_fingerprint=pipeline_fingerprint,
        )
        if event_window_claims:
            dual_event_ids = [str(item["event_id"]) for item in event_scopes]
            dual_meta_event_ids = dual_event_ids
        else:
            dual_meta_event_ids = []
        states = (
            source_state_from_payload("path_a", path_a_result, fingerprint=provider_fingerprints["path_a"]),
            source_state_from_payload("path_b", path_b_result, fingerprint=provider_fingerprints["path_b"]),
            ClaimSourceState("deterministic", "complete", fingerprint=pipeline_fingerprint),
        )
        generated_identity_conflicts = _identity_conflicts_from_target_lock(
            target_lock,
            frame_payloads=raw_frame_payloads,
            window_start_sec=window_start_sec,
            effective_fps=(frame_motion_scores or {}).get("effective_fps") if isinstance(frame_motion_scores, dict) else None,
        )
        if identity_state != "confirmed" and not generated_identity_conflicts:
            # An unconfirmed target is unsafe for technical claims across the
            # analyzed window.  Preserve deterministic observability claims but
            # fail closed for identity-dependent evidence.
            start = max(0.0, float(window_start_sec))
            last_timestamp = float(raw_frame_payloads[-1].timestamp_sec) if raw_frame_payloads else start
            end = max(start, last_timestamp if last_timestamp >= start else start + max(last_timestamp, 0.0))
            generated_identity_conflicts = [{"start_pts_sec": start, "end_pts_sec": max(start, end), "reason": "low_margin"}]
        if isinstance(identity, dict):
            existing_conflicts = identity.get("conflicts") if isinstance(identity.get("conflicts"), list) else []
            identity_for_fusion: Any = {
                **identity,
                "conflicts": _dedupe_identity_conflicts([*existing_conflicts, *generated_identity_conflicts]),
            }
        elif generated_identity_conflicts and hasattr(identity, "conflicts"):
            # ``fuse_evidence_claims`` accepts a sequence of conflict records;
            # keep the original timeline object untouched and avoid injecting
            # raw dicts into its Pydantic tuple field.
            identity_for_fusion = _dedupe_identity_conflicts([*(getattr(identity, "conflicts", ()) or ()), *generated_identity_conflicts])
        elif identity is None:
            identity_for_fusion = generated_identity_conflicts
        else:
            identity_for_fusion = identity
        dual_meta["identity_conflict_intervals"] = generated_identity_conflicts
        fusion_result = fuse_evidence_claims(
            deterministic_claims,
            claims_a,
            claims_b,
            event_window_claims,
            event_candidate_claims,
            identity=identity_for_fusion,
            source_states=states,
            fusion_configuration={"pipeline_fingerprint": pipeline_fingerprint, "profile": analysis_profile},
        )
        fused_claims = fusion_result.claims
        dual_meta["claim_fusion"] = fusion_result.model_dump()
        dual_meta["v2_pipeline_fingerprint"] = pipeline_fingerprint
        dual_meta["event_ids"] = dual_meta_event_ids
        dual_meta["event_proposal_count"] = len(event_window_claims)

    return DualPathResult(
        path_a=path_a_result,
        path_b=path_b_result,
        validation=validation,
        blend_weights=weights,
        dual_path_meta=dual_meta,
        annotated_dir=annotated_dir,
        used_key_frames=key_stems,
        fused_claims=fused_claims,
        fusion_result=fusion_result,
    )


def dual_path_summary(result: DualPathResult) -> dict[str, Any]:
    """Return a compact JSON-serializable summary for frontend display."""
    validation = result.validation
    # Keep the summary adapter-compatible with historical test doubles and
    # persisted retry payloads that only expose ``to_dict``.  The concrete
    # CrossValidationReport still supplies the richer attributes in normal V2
    # execution; missing diagnostics are intentionally represented as unknown.
    validation_payload = validation.to_dict() if hasattr(validation, "to_dict") else {}
    blend_weights = getattr(result, "blend_weights", (0.0, 0.0)) or (0.0, 0.0)
    weight_a = float(blend_weights[0]) if len(blend_weights) > 0 else 0.0
    weight_b = float(blend_weights[1]) if len(blend_weights) > 1 else 0.0
    path_a = getattr(result, "path_a", {}) or {}
    path_b = getattr(result, "path_b", None) or {}
    dual_meta = getattr(result, "dual_path_meta", {}) or {}
    return {
        "agreement_rate": getattr(validation, "overall_agreement_rate", validation_payload.get("overall_agreement_rate")),
        "skeleton_signal": getattr(validation, "skeleton_reliability_signal", validation_payload.get("skeleton_reliability_signal")),
        "recommended": getattr(validation, "recommended_path", validation_payload.get("recommended_path", dual_meta.get("recommended_path", "unknown"))),
        "weight_a": weight_a,
        "weight_b": weight_b,
        "conflict_fields": getattr(validation, "conflict_fields", validation_payload.get("conflict_fields", [])),
        "summary_text": getattr(validation, "conflict_summary", validation_payload.get("conflict_summary")),
        "path_b_failed": dual_meta.get("path_b_failed", False),
        "fusion_diagnostics": dual_meta.get("fusion_diagnostics", {}),
        "conflict_level": dual_meta.get("conflict_level", "none"),
        "downgraded_reasons": dual_meta.get("downgraded_reasons", []),
        "needs_human_review": dual_meta.get("needs_human_review", False),
        "n_frames_a": len(path_a.get("frame_analysis") or []) if isinstance(path_a, dict) else 0,
        "n_frames_b": path_b.get("n_frames", 0) if isinstance(path_b, dict) else 0,
        "raw_frame_count": dual_meta.get("raw_frame_count", 0),
        "annotated_frame_count": dual_meta.get("annotated_frame_count", 0),
    }
