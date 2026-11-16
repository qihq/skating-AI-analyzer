from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import inspect
import json
import math
import os
import shutil
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any


VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
DEFAULT_VIDEO_DIR = Path(os.getenv("SKATING_DIAGNOSTIC_VIDEO_DIR", str(Path.cwd() / "private-videos")))
DEFAULT_OUTPUT_DIR = Path("tmp") / "skate-video-iteration"


def _repo_root(path: Path) -> Path:
    path = path.resolve()
    return path if (path / "backend" / "app").exists() else Path.cwd().resolve()


def _install_backend(repo: Path, model_root: Path) -> None:
    backend = repo / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))

    os.environ.setdefault("VIDEO_PROCESSING_ROOT", str(repo / "tmp" / "skating-diagnostics-processing"))
    if shutil.which("ffmpeg") is None:
        try:
            import imageio_ffmpeg

            source_ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())
            local_bin = repo / "tmp" / "skating-diagnostics-bin"
            local_ffmpeg = local_bin / "ffmpeg.exe"
            local_bin.mkdir(parents=True, exist_ok=True)
            if not local_ffmpeg.exists() or local_ffmpeg.stat().st_size != source_ffmpeg.stat().st_size:
                shutil.copy2(source_ffmpeg, local_ffmpeg)
            os.environ["PATH"] = f"{local_bin}{os.pathsep}{os.environ.get('PATH', '')}"
        except (ImportError, OSError):
            pass

    yolo = model_root / "models" / "yolov8n.pt"
    pose = model_root / "models" / "pose_landmarker_heavy.task"
    if yolo.exists():
        os.environ.setdefault("YOLO_PERSON_MODEL_PATH", str(yolo))
    if pose.exists():
        os.environ.setdefault("MEDIAPIPE_POSE_TASK_PATH", str(pose))
        os.environ.setdefault("POSE_NUM_POSES", "4")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(numeric) or math.isinf(numeric):
        return default
    return numeric


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_safe(value: Any) -> Any:
    """Convert inference diagnostics to values accepted by ``json.dumps``."""

    if dataclasses.is_dataclass(value):
        return _json_safe(dataclasses.asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    item_fn = getattr(value, "item", None)
    if callable(item_fn):
        try:
            return _json_safe(item_fn())
        except (TypeError, ValueError):
            pass
    tolist_fn = getattr(value, "tolist", None)
    if callable(tolist_fn):
        try:
            return _json_safe(tolist_fn())
        except (TypeError, ValueError):
            pass
    return value


def _bbox_area(bbox: dict[str, Any] | None) -> float:
    if not isinstance(bbox, dict):
        return 0.0
    return max(0.0, _safe_float(bbox.get("width"))) * max(0.0, _safe_float(bbox.get("height")))


def _frame_names(frame_paths: list[Path]) -> list[str]:
    return [path.name for path in frame_paths]


def _state_counts(items: Any, key: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                counts[str(item.get(key) or "unknown")] += 1
    return dict(counts)


def _quality_flags(*payloads: Any) -> list[str]:
    flags: list[str] = []
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        values = payload.get("quality_flags")
        if isinstance(values, list):
            for value in values:
                flag = str(value)
                if flag and flag not in flags:
                    flags.append(flag)
    return flags


def _candidate_id(candidate: dict[str, Any]) -> str:
    return str(candidate.get("id") or "").strip()


def _target_candidates(
    *,
    person_tracker: Any,
    target_lock: Any,
    frame_paths: list[Path],
    motion_scores: dict[str, Any],
    analysis_profile: str | None,
) -> list[dict[str, Any]]:
    detect_person_candidates = getattr(person_tracker, "detect_person_candidates", None)
    if detect_person_candidates is None:
        return []

    frame_names = _frame_names(frame_paths)
    anchor_indices_fn = getattr(target_lock, "target_preview_anchor_frame_indices", None)
    if anchor_indices_fn is not None:
        anchor_indices = anchor_indices_fn(frame_names, motion_scores)
    else:
        anchor_indices = []
        for fraction in (0.5, 0.25, 0.75):
            index = round((len(frame_paths) - 1) * fraction)
            if index not in anchor_indices:
                anchor_indices.append(index)

    candidates: list[dict[str, Any]] = []
    for anchor_index in anchor_indices:
        if anchor_index < 0 or anchor_index >= len(frame_paths):
            continue
        frame_path = frame_paths[anchor_index]
        try:
            detected = detect_person_candidates(frame_path, include_zoomed_small_targets=True)
        except TypeError:
            detected = detect_person_candidates(frame_path)
        except Exception:
            continue
        for candidate in detected:
            if not isinstance(candidate, dict):
                continue
            item = dict(candidate)
            item["id"] = f"anchor_{anchor_index}_{candidate.get('id') or len(candidates) + 1}"
            item["anchor_frame"] = frame_path.name
            item["anchor_index"] = anchor_index
            candidates.append(item)

    stable_fn = getattr(target_lock, "select_stable_target_candidate", None)
    if stable_fn is not None:
        selected = stable_fn(candidates)
        if isinstance(selected, dict):
            selected = dict(selected)
            selected["id"] = "candidate_auto_stable"
            selected["source"] = str(selected.get("source") or "yolo_preview_multi_anchor")
            return [selected, *candidates]
    return candidates


def _build_preview(target_lock: Any, *, video_name: str, frame_paths: list[Path], motion_scores: dict[str, Any], candidates: list[dict[str, Any]], analysis_profile: str | None) -> Any:
    kwargs: dict[str, Any] = {
        "existing_target_lock": None,
        "motion_scores": motion_scores,
    }
    signature = inspect.signature(target_lock.build_target_preview)
    if "detected_candidates" in signature.parameters:
        kwargs["detected_candidates"] = candidates
    if "analysis_profile" in signature.parameters:
        kwargs["analysis_profile"] = analysis_profile
    return target_lock.build_target_preview(video_name, _frame_names(frame_paths), **kwargs)


def _build_target_lock_payload(target_lock: Any, preview: Any) -> dict[str, Any]:
    return target_lock.build_target_lock_payload(preview)


def _track_bboxes(person_tracker: Any, frame_paths: list[Path], target_payload: dict[str, Any], effective_fps: float) -> tuple[list[dict[str, float]] | None, list[str], list[dict[str, Any]]]:
    selected_bbox = target_payload.get("selected_bbox")
    if not isinstance(selected_bbox, dict):
        return None, ["diagnostic_no_selected_bbox"], []
    anchor_index = int(target_payload.get("preview_frame_index") or 0)
    try:
        tracked, flags, diagnostics = person_tracker.track_person_bbox_detailed(
            frame_paths,
            selected_bbox,
            initial_frame_index=anchor_index,
            effective_fps=effective_fps,
            manual_lock_mode=bool(target_payload.get("manual_override")),
        )
        return tracked, list(flags), list(diagnostics)
    except Exception as exc:
        return [selected_bbox for _ in frame_paths], [f"diagnostic_tracker_failed:{type(exc).__name__}"], []


def _pose_summary(pose_data: dict[str, Any]) -> dict[str, Any]:
    diagnostics = pose_data.get("pose_diagnostics") if isinstance(pose_data, dict) else None
    if isinstance(diagnostics, dict):
        total = int(diagnostics.get("total_frames") or 0)
        tracked = int(diagnostics.get("tracked_frames") or 0)
        lost = int(diagnostics.get("lost_frames") or 0)
        low = int(diagnostics.get("low_confidence_frames") or 0)
        interpolated = int(diagnostics.get("interpolated_frames") or 0)
        return {
            "mode": diagnostics.get("mode"),
            "total_frames": total,
            "tracked_frames": tracked,
            "lost_frames": lost,
            "low_confidence_frames": low,
            "interpolated_frames": interpolated,
            "tracked_ratio": round(tracked / max(total, 1), 4),
            "lost_ratio": round(lost / max(total, 1), 4),
            "low_confidence_ratio": round(low / max(total, 1), 4),
            "state_counts": _state_counts(diagnostics.get("frames"), "tracking_state"),
        }
    frames = pose_data.get("frames") if isinstance(pose_data, dict) else []
    total = len(frames) if isinstance(frames, list) else 0
    tracked = sum(1 for frame in frames if isinstance(frame, dict) and frame.get("tracking_state") == "tracked")
    lost = total - tracked
    return {
        "mode": "legacy",
        "total_frames": total,
        "tracked_frames": tracked,
        "lost_frames": lost,
        "low_confidence_frames": lost,
        "interpolated_frames": 0,
        "tracked_ratio": round(tracked / max(total, 1), 4),
        "lost_ratio": round(lost / max(total, 1), 4),
        "low_confidence_ratio": round(lost / max(total, 1), 4),
        "state_counts": _state_counts(frames, "tracking_state"),
    }


def _keyframe_summary(candidates: dict[str, Any] | None) -> dict[str, Any]:
    result: dict[str, Any] = {"quality_flags": [], "complete": False, "coverage_score": 0.0, "average_confidence": 0.0}
    if not isinstance(candidates, dict):
        result["quality_flags"] = ["missing_keyframe_candidates"]
        return result
    confidences: list[float] = []
    timestamps: list[float] = []
    for key in ("T", "A", "L"):
        item = candidates.get(key) if isinstance(candidates.get(key), dict) else {}
        confidence = _safe_float(item.get("confidence"))
        timestamp = item.get("timestamp")
        result[key] = {
            "frame_id": item.get("frame_id"),
            "timestamp": timestamp,
            "confidence": round(confidence, 4),
            "warnings": item.get("warnings") if isinstance(item.get("warnings"), list) else [],
        }
        if item.get("frame_id") and confidence >= 0.35:
            confidences.append(confidence)
        if timestamp is not None:
            timestamps.append(_safe_float(timestamp))
    result["quality_flags"] = candidates.get("quality_flags") if isinstance(candidates.get("quality_flags"), list) else []
    result["complete"] = len(confidences) == 3
    result["coverage_score"] = round(len(confidences) / 3.0, 4)
    result["average_confidence"] = round(sum(confidences) / len(confidences), 4) if confidences else 0.0
    result["tal_order_valid"] = len(timestamps) == 3 and timestamps[0] < timestamps[1] < timestamps[2]
    return result


def _failure_notes(pose_data: dict[str, Any], tracker_diagnostics: list[dict[str, Any]], motion_scores: dict[str, Any]) -> list[dict[str, Any]]:
    selected_by_frame = {
        str(item.get("frame_id")): item
        for item in motion_scores.get("selected", [])
        if isinstance(item, dict) and item.get("frame_id")
    }
    notes: list[dict[str, Any]] = []
    pose_frames = ((pose_data.get("pose_diagnostics") or {}).get("frames") if isinstance(pose_data, dict) else []) or []
    for frame in pose_frames:
        if not isinstance(frame, dict):
            continue
        state = str(frame.get("tracking_state") or "")
        if state == "tracked":
            continue
        frame_id = str(frame.get("frame") or "").removesuffix(".jpg")
        motion = _safe_float((selected_by_frame.get(frame_id) or {}).get("motion_score"))
        reason = str(frame.get("reason") or state)
        scene = "pose_low_confidence_or_blur"
        if "lost" in state or "crop_retry" in reason:
            scene = "occlusion_or_detector_loss"
        if motion >= 0.45:
            scene = "fast_motion_or_rotation"
        notes.append(
            {
                "frame": frame.get("frame"),
                "frame_index": frame.get("frame_index"),
                "scene": scene,
                "state": state,
                "reason": reason,
                "motion_score": round(motion, 4),
            }
        )
        if len(notes) >= 8:
            break

    for item in tracker_diagnostics:
        if not isinstance(item, dict):
            continue
        state = str(item.get("state") or "")
        if state in {"tracked", "relocked"}:
            continue
        notes.append(
            {
                "frame": item.get("frame"),
                "frame_index": item.get("frame_index"),
                "scene": "target_bbox_relock_or_reuse",
                "state": state,
                "reason": ",".join(str(value) for value in item.get("rejected_reasons", []) if value),
            }
        )
        if len(notes) >= 12:
            break
    return notes


async def _analyze_one(
    video_path: Path,
    output_dir: Path,
    modules: dict[str, Any],
    identity_anchors: dict[str, Any] | None = None,
) -> dict[str, Any]:
    video_id = video_path.stem
    work_dir = output_dir / "work" / video_id
    frames_dir = work_dir / "frames"
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
    frames_dir.mkdir(parents=True, exist_ok=True)

    video = modules["video"]
    target_lock = modules["target_lock"]
    person_tracker = modules["person_tracker"]
    pose = modules["pose"]
    biomechanics = modules["biomechanics"]
    action_profiles = modules["action_profiles"]
    action_classification = modules["action_classification"]
    event_proposals = modules["event_proposals"]
    profile_moments = modules["profile_moments"]
    source_evidence_adapter = modules["source_evidence_adapter"]

    started = time.perf_counter()
    result: dict[str, Any] = {
        "video": video_path.name,
        "video_path": str(video_path),
        "status": "ok",
    }
    try:
        frame_paths, motion_scores, sampling = await video.extract_motion_sampled_frames(
            video_path,
            frames_dir,
            "自由滑",
            None,
            profile_agnostic_scan=True,
        )
        source_hash = _sha256_file(video_path)
        candidates = _target_candidates(
            person_tracker=person_tracker,
            target_lock=target_lock,
            frame_paths=frame_paths,
            motion_scores=motion_scores,
            analysis_profile=None,
        )
        preview = _build_preview(
            target_lock,
            video_name=video_id,
            frame_paths=frame_paths,
            motion_scores=motion_scores,
            candidates=candidates,
            analysis_profile=None,
        )
        anchor = (identity_anchors or {}).get(source_hash)
        if anchor is not None:
            target_payload = modules["identity_anchor"].target_lock_payload_from_parent_anchor(
                anchor,
                _frame_names(frame_paths),
                motion_scores.get("selected", []) if isinstance(motion_scores, dict) else [],
            )
        else:
            target_payload = _build_target_lock_payload(target_lock, preview)
        bbox_per_frame, tracker_flags, tracker_diagnostics = _track_bboxes(
            person_tracker,
            frame_paths,
            target_payload,
            sampling.effective_fps,
        )
        target_payload["bbox_per_frame"] = bbox_per_frame
        target_payload["person_tracker_diagnostics"] = tracker_diagnostics
        target_payload["quality_flags"] = list(
            dict.fromkeys([*(target_payload.get("quality_flags") if isinstance(target_payload.get("quality_flags"), list) else []), *tracker_flags])
        )
        pose_data = pose.extract_pose(
            str(frames_dir),
            target_payload,
            bbox_per_frame,
            sampling.effective_fps,
        )
        legacy_profile, profile_evidence = action_profiles.infer_analysis_profile(
            "自由滑",
            "节目片段",
            pose_data,
            motion_scores,
        )
        source_inputs = {
            "frame_paths": frame_paths,
            "sampling": sampling,
            "motion_scores": motion_scores,
            "bbox_per_frame": bbox_per_frame,
            "tracker_diagnostics": tracker_diagnostics,
            "pose_data": pose_data,
        }
        source_evidence = source_evidence_adapter.build_source_evidence(source_hash, _json_safe(source_inputs))
        proposal_collection = event_proposals.generate_event_proposals(
            source_video_hash=source_hash,
            source_duration_sec=source_evidence.source_duration_sec,
            samples=source_evidence.proposal_samples,
            pipeline_fingerprint="diagnostic-source-only-evidence.v2",
        )
        proposal_rows: list[dict[str, Any]] = []
        for proposal in proposal_collection.proposals:
            is_unlocalized_fallback = "unlocalized_observability_envelope" in proposal.evidence_sources
            if is_unlocalized_fallback:
                proposal_rows.append({
                    "proposal": proposal.model_dump(mode="json"),
                    "classification_evidence": None,
                    "classification": {
                        "profile": "unknown",
                        "state": "unknown",
                        "confidence": 0.0,
                        "margin": 0.0,
                        "semantic_labels_consumed": False,
                    },
                    "moments": {"moments": [], "semantic_labels_consumed": False},
                })
                continue
            classification_evidence = source_evidence_adapter.build_action_classification_evidence(source_evidence, proposal)
            classification = action_classification.classify_action(classification_evidence)
            moment_profile = classification.profile if classification.profile in {"jump", "spin", "step", "spiral"} else "step"
            moments = profile_moments.localize_profile_moments(
                event_id=proposal.event_id,
                profile=moment_profile,
                event_start_pts=proposal.start_pts,
                event_end_pts=proposal.end_pts,
                samples=source_evidence.moment_samples,
                source_timeline_fingerprint=source_evidence.source_timeline_fingerprint,
            )
            proposal_rows.append({
                "proposal": proposal.model_dump(mode="json"),
                "classification_evidence": classification_evidence.model_dump(mode="json"),
                "classification": classification.model_dump(mode="json"),
                "moments": moments.model_dump(mode="json"),
            })
        confirmed_rows = [row for row in proposal_rows if row["classification"]["state"] == "confirmed"]
        primary_row = max(
            confirmed_rows,
            key=lambda row: (
                _safe_float(row["classification"].get("confidence")),
                _safe_float(row["proposal"].get("end_pts")) - _safe_float(row["proposal"].get("start_pts")),
            ),
            default=None,
        )
        inferred_profile = str(primary_row["classification"]["profile"]) if primary_row else "unknown"
        biomechanics_profile = inferred_profile if inferred_profile in {"jump", "spin", "step", "spiral"} else "step"
        bio_data = biomechanics.analyze_biomechanics(
            pose_data,
            "自由滑",
            biomechanics_profile,
            effective_fps=sampling.effective_fps,
            source_fps=sampling.source_fps,
            window_seconds=sampling.window_end_sec - sampling.window_start_sec,
        )
        if hasattr(biomechanics, "attach_key_frame_candidates"):
            bio_data = biomechanics.attach_key_frame_candidates(
                bio_data,
                pose_data,
                motion_scores,
                biomechanics_profile,
                sampling.effective_fps,
            )

        target_flags = target_payload.get("quality_flags") if isinstance(target_payload.get("quality_flags"), list) else []
        selected_bbox = target_payload.get("selected_bbox") if isinstance(target_payload.get("selected_bbox"), dict) else None
        result.update(
            {
                "sampling": {
                    "frame_count": len(frame_paths),
                    "source_fps": sampling.source_fps,
                    "effective_fps": sampling.effective_fps,
                    "window_start": sampling.action_window_start,
                    "window_end": sampling.action_window_end,
                    "selection_reason": motion_scores.get("window_diagnostics", {}).get("selection_reason")
                    if isinstance(motion_scores.get("window_diagnostics"), dict)
                    else None,
                },
                "target_lock": {
                    "status": target_payload.get("status"),
                    "lock_confidence": round(_safe_float(target_payload.get("lock_confidence")), 4),
                    "candidate_count": len(getattr(preview, "candidates", []) or []),
                    "detected_candidate_count": len(candidates),
                    "selected_candidate_id": target_payload.get("selected_candidate_id"),
                    "selected_bbox_area": round(_bbox_area(selected_bbox), 6),
                    "quality_flags": target_flags,
                    "auto_locked": str(target_payload.get("status")) == "auto_locked",
                },
                "tracker": {
                    "quality_flags": tracker_flags,
                    "states": _state_counts(tracker_diagnostics, "state"),
                    "lost_or_reused_frames": sum(
                        1
                        for item in tracker_diagnostics
                        if isinstance(item, dict) and str(item.get("state") or "") not in {"tracked", "relocked"}
                    ),
                    "relocked_frames": sum(
                        1 for item in tracker_diagnostics if isinstance(item, dict) and str(item.get("state") or "") == "relocked"
                    ),
                },
                "pose": _pose_summary(pose_data),
                "action_recognition": {
                    "profile": inferred_profile,
                    "state": primary_row["classification"]["state"] if primary_row else "unknown",
                    "confidence": primary_row["classification"]["confidence"] if primary_row else 0.0,
                    "proposal_count": len(proposal_rows),
                    "legacy_profile_for_comparison": legacy_profile,
                    "jump_gate_passed": bool(profile_evidence.get("jump_gate_passed")) if isinstance(profile_evidence, dict) else False,
                    "airborne_frames_detected": profile_evidence.get("airborne_frames_detected") if isinstance(profile_evidence, dict) else None,
                    "hip_rotation_signal": profile_evidence.get("hip_rotation_signal") if isinstance(profile_evidence, dict) else None,
                    "quality_flags": list(dict.fromkeys([
                        *(profile_evidence.get("quality_flags") if isinstance(profile_evidence, dict) else []),
                        *source_evidence.warnings,
                    ])),
                },
                "keyframes": _keyframe_summary(
                    bio_data.get("key_frame_candidates") if isinstance(bio_data, dict) else None
                ),
                "failure_notes": _failure_notes(pose_data, tracker_diagnostics, motion_scores),
                "quality_flags": _quality_flags(target_payload, pose_data, bio_data),
                "raw_diagnostics": _json_safe(
                    {
                        "frame_paths": frame_paths,
                        "sampling": sampling,
                        "motion_scores": motion_scores,
                        "detected_candidates": candidates,
                        "preview": {
                            "preview_frame": getattr(preview, "preview_frame", None),
                            "preview_frame_index": getattr(preview, "preview_frame_index", None),
                            "auto_candidate_id": getattr(preview, "auto_candidate_id", None),
                            "lock_confidence": getattr(preview, "lock_confidence", None),
                            "target_lock_status": getattr(preview, "target_lock_status", None),
                            "candidates": getattr(preview, "candidates", []),
                        },
                        "target_lock": target_payload,
                        "bbox_per_frame": bbox_per_frame,
                        "tracker_flags": tracker_flags,
                        "tracker_diagnostics": tracker_diagnostics,
                        "pose_data": pose_data,
                        "profile_evidence": profile_evidence,
                        "biomechanics": bio_data,
                        "source_evidence": {
                            "schema_version": "diagnostic-source-only-evidence.v2",
                            "source_video_hash": source_hash,
                            "source_duration_sec": source_evidence.source_duration_sec,
                            "source_timeline_fingerprint": source_evidence.source_timeline_fingerprint,
                            "warnings": source_evidence.warnings,
                            "proposal_samples": [item.model_dump(mode="json") for item in source_evidence.proposal_samples],
                            "moment_samples": [item.model_dump(mode="json") for item in source_evidence.moment_samples],
                            "rotation_samples": [item.model_dump(mode="json") for item in source_evidence.rotation_samples],
                            "rotation_diagnostics": source_evidence.rotation_diagnostics,
                            "proposal_collection": proposal_collection.model_dump(mode="json"),
                            "events": proposal_rows,
                        },
                    }
                ),
            }
        )
    except Exception as exc:
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        result["elapsed_sec"] = round(time.perf_counter() - started, 3)
    return result


def _aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [item for item in results if item.get("status") == "ok"]
    failures = [item for item in results if item.get("status") != "ok"]

    def avg(path: tuple[str, ...]) -> float:
        values: list[float] = []
        for item in ok:
            current: Any = item
            for key in path:
                current = current.get(key) if isinstance(current, dict) else None
            if isinstance(current, (int, float)):
                values.append(float(current))
        return round(sum(values) / len(values), 4) if values else 0.0

    profile_counts = Counter(str(item.get("action_recognition", {}).get("profile") or "unknown") for item in ok)
    failure_scenes = Counter()
    for item in ok:
        for note in item.get("failure_notes", []):
            if isinstance(note, dict):
                failure_scenes[str(note.get("scene") or "unknown")] += 1

    tal_complete = sum(1 for item in ok if item.get("keyframes", {}).get("complete"))
    return {
        "videos_total": len(results),
        "videos_ok": len(ok),
        "videos_failed": len(failures),
        "auto_lock_rate": round(
            sum(1 for item in ok if item.get("target_lock", {}).get("auto_locked")) / max(len(ok), 1),
            4,
        ),
        "average_pose_tracked_ratio": avg(("pose", "tracked_ratio")),
        "average_pose_lost_ratio": avg(("pose", "lost_ratio")),
        "average_pose_low_confidence_ratio": avg(("pose", "low_confidence_ratio")),
        "average_keyframe_coverage": avg(("keyframes", "coverage_score")),
        "average_keyframe_confidence": avg(("keyframes", "average_confidence")),
        "tal_complete_rate": round(tal_complete / max(len(ok), 1), 4),
        "profile_counts": dict(profile_counts),
        "failure_scene_counts": dict(failure_scenes),
        "failed_videos": [{"video": item.get("video"), "error": item.get("error")} for item in failures],
    }


def _delta(current: float, previous: float) -> float:
    return round(current - previous, 4)


def _write_report(output_path: Path, payload: dict[str, Any], baseline: dict[str, Any] | None) -> None:
    aggregate = payload["aggregate"]
    lines = [
        "# Skate Video Iteration Diagnostics",
        "",
        f"- Label: {payload['label']}",
        f"- Repo: {payload['repo']}",
        f"- Videos: {aggregate['videos_ok']}/{aggregate['videos_total']} ok",
        f"- Auto lock rate: {aggregate['auto_lock_rate']:.2%}",
        f"- Avg pose tracked ratio: {aggregate['average_pose_tracked_ratio']:.2%}",
        f"- Avg pose lost ratio: {aggregate['average_pose_lost_ratio']:.2%}",
        f"- Avg pose low-confidence ratio: {aggregate['average_pose_low_confidence_ratio']:.2%}",
        f"- T/A/L complete rate: {aggregate['tal_complete_rate']:.2%}",
        f"- Avg keyframe coverage: {aggregate['average_keyframe_coverage']:.2%}",
        f"- Avg keyframe confidence: {aggregate['average_keyframe_confidence']:.3f}",
        "",
    ]
    if baseline:
        base = baseline["aggregate"]
        lines.extend(
            [
                "## Comparison",
                "",
                "| Metric | Baseline | Current | Delta |",
                "| --- | ---: | ---: | ---: |",
                f"| videos ok | {base['videos_ok']}/{base['videos_total']} | {aggregate['videos_ok']}/{aggregate['videos_total']} | {_delta(float(aggregate['videos_ok']), float(base['videos_ok'])):.0f} |",
                f"| auto lock rate | {base['auto_lock_rate']:.2%} | {aggregate['auto_lock_rate']:.2%} | {_delta(aggregate['auto_lock_rate'], base['auto_lock_rate']):.2%} |",
                f"| pose tracked ratio | {base['average_pose_tracked_ratio']:.2%} | {aggregate['average_pose_tracked_ratio']:.2%} | {_delta(aggregate['average_pose_tracked_ratio'], base['average_pose_tracked_ratio']):.2%} |",
                f"| pose lost ratio | {base['average_pose_lost_ratio']:.2%} | {aggregate['average_pose_lost_ratio']:.2%} | {_delta(aggregate['average_pose_lost_ratio'], base['average_pose_lost_ratio']):.2%} |",
                f"| pose low-confidence ratio | {base['average_pose_low_confidence_ratio']:.2%} | {aggregate['average_pose_low_confidence_ratio']:.2%} | {_delta(aggregate['average_pose_low_confidence_ratio'], base['average_pose_low_confidence_ratio']):.2%} |",
                f"| T/A/L complete rate | {base['tal_complete_rate']:.2%} | {aggregate['tal_complete_rate']:.2%} | {_delta(aggregate['tal_complete_rate'], base['tal_complete_rate']):.2%} |",
                f"| keyframe coverage | {base['average_keyframe_coverage']:.2%} | {aggregate['average_keyframe_coverage']:.2%} | {_delta(aggregate['average_keyframe_coverage'], base['average_keyframe_coverage']):.2%} |",
                "",
            ]
        )
    lines.extend(
        [
            "## Failure Scenes",
            "",
            json.dumps(aggregate["failure_scene_counts"], ensure_ascii=False, indent=2),
            "",
            "## Profile Counts",
            "",
            json.dumps(aggregate["profile_counts"], ensure_ascii=False, indent=2),
            "",
        ]
    )
    if aggregate["failed_videos"]:
        lines.extend(["## Failed Videos", "", json.dumps(aggregate["failed_videos"], ensure_ascii=False, indent=2), ""])
    output_path.write_text("\n".join(lines), encoding="utf-8")


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Run local skating video diagnostics for iteration comparisons.")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Repository root whose backend services should be imported.")
    parser.add_argument("--model-root", type=Path, default=Path.cwd(), help="Repository root containing local models/.")
    parser.add_argument("--video-dir", type=Path, default=DEFAULT_VIDEO_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--label", default="current")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of videos; 0 means all.")
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="Analyze only videos whose file name matches one of these exact names. Can be passed multiple times.",
    )
    parser.add_argument("--compare", type=Path, default=None, help="Optional baseline JSON to compare against.")
    parser.add_argument(
        "--identity-anchors",
        type=Path,
        default=None,
        help="Optional private parent-confirmed identity-anchor manifest for non-tracking diagnostic masks.",
    )
    parser.add_argument(
        "--redact-progress",
        action="store_true",
        help="Print only ordinal source aliases while preserving private names in the private output artifact.",
    )
    args = parser.parse_args()

    repo = _repo_root(args.repo)
    model_root = _repo_root(args.model_root)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    _install_backend(repo, model_root)

    from app.analysis_v2 import action_classification, event_proposals, profile_moments
    from app.analysis_v2.evaluation import identity_anchor, source_evidence_adapter
    from app.services import action_profiles, biomechanics, person_tracker, pose, target_lock, video

    modules = {
        "action_profiles": action_profiles,
        "biomechanics": biomechanics,
        "person_tracker": person_tracker,
        "pose": pose,
        "target_lock": target_lock,
        "video": video,
        "action_classification": action_classification,
        "event_proposals": event_proposals,
        "profile_moments": profile_moments,
        "source_evidence_adapter": source_evidence_adapter,
        "identity_anchor": identity_anchor,
    }
    identity_anchors = None
    if args.identity_anchors is not None:
        identity_anchors = identity_anchor.load_parent_identity_anchor_manifest(args.identity_anchors.resolve()).by_source()

    only_names = {str(name).strip() for name in args.only if str(name).strip()}
    video_paths = sorted(path for path in args.video_dir.iterdir() if path.suffix.lower() in VIDEO_SUFFIXES)
    if only_names:
        video_paths = [path for path in video_paths if path.name in only_names]
        missing_names = sorted(only_names - {path.name for path in video_paths})
        if missing_names:
            parser.error(f"--only names not found in {args.video_dir}: {', '.join(missing_names)}")
    if args.limit > 0:
        video_paths = video_paths[: args.limit]
    results: list[dict[str, Any]] = []
    for index, video_path in enumerate(video_paths, start=1):
        progress_name = f"source-{index:03d}" if args.redact_progress else video_path.name
        print(f"[{index}/{len(video_paths)}] {progress_name}", flush=True)
        results.append(await _analyze_one(video_path, output_dir / args.label, modules, identity_anchors))

    payload = {
        "label": args.label,
        "repo": str(repo),
        "video_dir": str(args.video_dir),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "aggregate": _aggregate(results),
        "videos": results,
    }
    json_path = output_dir / f"{args.label}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    baseline = None
    if args.compare and args.compare.exists():
        baseline = json.loads(args.compare.read_text(encoding="utf-8"))
    _write_report(output_dir / f"{args.label}.md", payload, baseline)
    print(json.dumps(payload["aggregate"], ensure_ascii=False, indent=2), flush=True)
    print(f"Wrote {json_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
