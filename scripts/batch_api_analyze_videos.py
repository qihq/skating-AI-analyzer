from __future__ import annotations

import argparse
import json
import mimetypes
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

import httpx


VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
DEFAULT_VIDEO_DIR = Path(r"C:\Users\qihq\Pictures\skate testing video")
DEFAULT_OUTPUT_DIR = Path("tmp") / "api-batch-skate-analysis"
DEFAULT_NOTE_PREFIX = "codex api full coverage 2026-05-30"
AUTO_ACTION_TYPE = "auto"
UPLOAD_ACTION_ALIASES = {
    "jump": ("跳跃", "未指定"),
    "jumps": ("跳跃", "未指定"),
    "spin": ("旋转", "未指定"),
    "spins": ("旋转", "未指定"),
    "step": ("步法", "未指定"),
    "steps": ("步法", "未指定"),
    "spiral": ("步法", "燕式滑行"),
    "spirals": ("步法", "燕式滑行"),
}
AUTO_UPLOAD_ACTION_TYPE = "自由滑"
AUTO_UPLOAD_ACTION_SUBTYPE = "节目片段"
PROFILE_KEYFRAME_KEYS = {
    "jump": ("T", "A", "L"),
    "spin": ("旋转入", "旋转中", "旋转出"),
    "spiral": ("峰值",),
    "step": ("步法序列",),
}
PROFILE_KEYFRAME_ALIASES = {
    "步法序列": ("步法序列", "峰值"),
}
IN_PROGRESS_STATUSES = {"pending", "processing", "extracting_frames", "analyzing", "generating_report"}
POLL_RETRYABLE_STATUS_CODES = {500, 502, 503, 504}
RETRYABLE_HTTP_ERRORS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadError,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
    httpx.WriteError,
    httpx.WriteTimeout,
)


def _current_pipeline_version() -> str:
    version_path = Path(__file__).resolve().parents[1] / "backend" / "app" / "services" / "pipeline_version.py"
    try:
        text = version_path.read_text(encoding="utf-8")
    except OSError:
        return ""
    match = re.search(r'CURRENT_PIPELINE_VERSION\s*=\s*["\']([^"\']+)["\']', text)
    return match.group(1) if match else ""


def _parse_timestamp(value: Any) -> float | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def _pipeline_version_tuple(value: Any) -> tuple[int, int, int]:
    match = re.search(r"v?(\d+)\.(\d+)\.(\d+)", str(value or ""))
    if not match:
        return (0, 0, 0)
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _status_rank(item: dict[str, Any]) -> int:
    status = str(item.get("status") or "")
    if status == "completed":
        return 3
    if status == "awaiting_target_selection":
        return 2
    if status:
        return 1
    return 0


def _row_recency_key(item: dict[str, Any]) -> tuple[float, tuple[int, int, int], int]:
    timestamp = _parse_timestamp(item.get("updated_at"))
    if timestamp is None:
        timestamp = _parse_timestamp(item.get("created_at"))
    return (
        timestamp if timestamp is not None else -1.0,
        _pipeline_version_tuple(item.get("pipeline_version")),
        _status_rank(item),
    )


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _resolve_upload_action(action_type: str, action_subtype: str) -> tuple[str, str]:
    action = str(action_type or "").strip()
    subtype = str(action_subtype or "").strip()
    if not action or action.lower() == AUTO_ACTION_TYPE:
        return AUTO_UPLOAD_ACTION_TYPE, AUTO_UPLOAD_ACTION_SUBTYPE
    alias = UPLOAD_ACTION_ALIASES.get(action.lower())
    if alias:
        alias_action, alias_subtype = alias
        return alias_action, subtype or alias_subtype
    return action, subtype


def _profile_keyframe_keys(analysis_profile: str | None) -> tuple[str, ...]:
    return PROFILE_KEYFRAME_KEYS.get(str(analysis_profile or "").strip().lower(), ("T", "A", "L"))


def _profile_keyframe_aliases(key: str) -> tuple[str, ...]:
    return PROFILE_KEYFRAME_ALIASES.get(key, (key,))


def _profile_keyframe_value(source: dict[str, Any], key: str) -> Any:
    for alias in _profile_keyframe_aliases(key):
        value = source.get(alias)
        if value is not None:
            return value
    return None


def _quality_flags(*payloads: Any) -> list[str]:
    flags: list[str] = []
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        values = payload.get("quality_flags")
        if isinstance(values, list):
            for value in values:
                text = str(value).strip()
                if text and text not in flags:
                    flags.append(text)
    return flags


def _bbox_area(bbox: Any) -> float:
    if not isinstance(bbox, dict):
        return 0.0
    return max(0.0, _safe_float(bbox.get("width"))) * max(0.0, _safe_float(bbox.get("height")))


def _state_counts(items: Any, key: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                counts[str(item.get(key) or "unknown")] += 1
    return dict(counts)


def _pose_summary(analysis: dict[str, Any]) -> dict[str, Any]:
    pose_data = analysis.get("pose_data") if isinstance(analysis.get("pose_data"), dict) else {}
    diagnostics = pose_data.get("pose_diagnostics") if isinstance(pose_data.get("pose_diagnostics"), dict) else {}
    frames = diagnostics.get("frames") if isinstance(diagnostics.get("frames"), list) else []
    total = int(diagnostics.get("total_frames") or len(frames) or 0)
    tracked = int(diagnostics.get("tracked_frames") or 0)
    lost = int(diagnostics.get("lost_frames") or 0)
    low_conf = int(diagnostics.get("low_confidence_frames") or 0)
    interpolated = int(diagnostics.get("interpolated_frames") or 0)
    return {
        "mode": diagnostics.get("mode"),
        "total_frames": total,
        "tracked_frames": tracked,
        "lost_frames": lost,
        "low_confidence_frames": low_conf,
        "interpolated_frames": interpolated,
        "tracked_ratio": round(tracked / max(total, 1), 4),
        "lost_ratio": round(lost / max(total, 1), 4),
        "low_confidence_ratio": round(low_conf / max(total, 1), 4),
        "state_counts": _state_counts(frames, "tracking_state"),
    }


def _keyframe_summary(analysis: dict[str, Any]) -> dict[str, Any]:
    bio_data = analysis.get("bio_data") if isinstance(analysis.get("bio_data"), dict) else {}
    candidates = bio_data.get("key_frame_candidates") if isinstance(bio_data.get("key_frame_candidates"), dict) else {}
    key_frames = bio_data.get("key_frames") if isinstance(bio_data.get("key_frames"), dict) else {}
    key_timestamps = bio_data.get("key_frame_timestamps") if isinstance(bio_data.get("key_frame_timestamps"), dict) else {}
    analysis_profile = str(analysis.get("analysis_profile") or "").strip().lower()
    expected_keys = _profile_keyframe_keys(analysis_profile)
    timestamps: list[float] = []
    final_confidences: list[float] = []
    result: dict[str, Any] = {
        "analysis_profile": analysis.get("analysis_profile"),
        "expected_keys": list(expected_keys),
        "key_frames": {key: key_frames.get(key) for key in expected_keys},
        "complete": False,
        "tal_order_valid": False,
        "coverage_score": 0.0,
        "profile_keyframe_complete": False,
        "profile_keyframe_coverage_score": 0.0,
        "average_confidence": 0.0,
        "source": bio_data.get("key_frame_source"),
        "quality_flags": candidates.get("quality_flags") if isinstance(candidates.get("quality_flags"), list) else [],
    }
    for key in ("T", "A", "L"):
        item = candidates.get(key) if isinstance(candidates.get(key), dict) else {}
        confidence = _safe_float(item.get("confidence"))
        frame_id = key_frames.get(key)
        timestamp = key_timestamps.get(key)
        if timestamp is None and frame_id and item.get("frame_id") == frame_id:
            timestamp = item.get("timestamp")
        result[key] = {
            "frame_id": frame_id,
            "timestamp": timestamp,
            "confidence": round(confidence, 4),
            "warnings": item.get("warnings") if isinstance(item.get("warnings"), list) else [],
        }
        result[f"{key}_candidate_evidence"] = {
            "frame_id": item.get("frame_id"),
            "timestamp": item.get("timestamp"),
            "confidence": round(confidence, 4),
            "warnings": item.get("warnings") if isinstance(item.get("warnings"), list) else [],
        }
        if frame_id:
            if item.get("frame_id") == frame_id and confidence >= 0.0:
                final_confidences.append(confidence)
            elif isinstance(bio_data.get("key_frame_confidence"), (int, float)):
                final_confidences.append(_safe_float(bio_data.get("key_frame_confidence")))
        if timestamp is not None:
            timestamps.append(_safe_float(timestamp))
    result["profile_keyframes"] = {
        key: {
            "frame_id": _profile_keyframe_value(key_frames, key),
            "timestamp": _profile_keyframe_value(key_timestamps, key),
        }
        for key in expected_keys
    }
    result["complete"] = all(result[key].get("frame_id") for key in ("T", "A", "L"))
    result["coverage_score"] = round(sum(1 for key in ("T", "A", "L") if result[key].get("frame_id")) / 3.0, 4)
    expected_present = sum(
        1
        for key in expected_keys
        if _profile_keyframe_value(key_frames, key) or _profile_keyframe_value(key_timestamps, key) is not None
    )
    result["profile_keyframe_complete"] = bool(expected_keys) and expected_present == len(expected_keys)
    result["profile_keyframe_coverage_score"] = round(expected_present / max(len(expected_keys), 1), 4)
    result["average_confidence"] = round(sum(final_confidences) / len(final_confidences), 4) if final_confidences else 0.0
    result["tal_order_valid"] = len(timestamps) == 3 and timestamps[0] < timestamps[1] < timestamps[2]
    return result


def _target_summary(analysis: dict[str, Any]) -> dict[str, Any]:
    target_lock = analysis.get("target_lock") if isinstance(analysis.get("target_lock"), dict) else {}
    diagnostics = target_lock.get("person_tracker_diagnostics")
    return {
        "status": target_lock.get("status") or analysis.get("target_lock_status"),
        "lock_confidence": round(_safe_float(target_lock.get("lock_confidence")), 4),
        "selected_candidate_id": target_lock.get("selected_candidate_id"),
        "selected_bbox_area": round(_bbox_area(target_lock.get("selected_bbox")), 6),
        "quality_flags": target_lock.get("quality_flags") if isinstance(target_lock.get("quality_flags"), list) else [],
        "tracker_state_counts": _state_counts(diagnostics, "state"),
    }


def _video_temporal_summary(analysis: dict[str, Any]) -> dict[str, Any]:
    vt = analysis.get("video_temporal_diagnostics")
    if not isinstance(vt, dict):
        return {"available": False}
    selected = vt.get("selected_semantic_frames") if isinstance(vt.get("selected_semantic_frames"), list) else []
    return {
        "available": True,
        "provider": vt.get("video_ai_provider"),
        "model": vt.get("video_ai_model"),
        "confidence": vt.get("video_ai_confidence"),
        "timestamp_source": vt.get("timestamp_source"),
        "resolver_source": vt.get("resolver_source"),
        "used_semantic_frames": bool(vt.get("used_semantic_frames")),
        "used_legacy_sampled_frames": bool(vt.get("used_legacy_sampled_frames")),
        "selected_count": len(selected),
        "quality_flags": vt.get("quality_flags") if isinstance(vt.get("quality_flags"), list) else [],
        "retry_rejection_flags": vt.get("retry_rejection_flags") if isinstance(vt.get("retry_rejection_flags"), list) else [],
    }


def _analysis_summary(
    video_path: Path,
    analysis: dict[str, Any],
    *,
    created: bool,
    requested_action_type: str | None = None,
    requested_action_subtype: str | None = None,
) -> dict[str, Any]:
    cross_validation = analysis.get("cross_validation") if isinstance(analysis.get("cross_validation"), dict) else {}
    vision = analysis.get("vision_structured") if isinstance(analysis.get("vision_structured"), dict) else {}
    auto_eval = cross_validation.get("auto_eval") if isinstance(cross_validation.get("auto_eval"), dict) else {}
    pose = _pose_summary(analysis)
    keyframes = _keyframe_summary(analysis)
    target = _target_summary(analysis)
    video_temporal = _video_temporal_summary(analysis)
    return {
        "video": video_path.name,
        "video_path": str(video_path),
        "analysis_id": analysis.get("id"),
        "report_url": f"http://localhost:5173/report/{analysis.get('id')}" if analysis.get("id") else None,
        "created_by_batch": created,
        "status": analysis.get("status"),
        "force_score": analysis.get("force_score"),
        "requested_action_type": requested_action_type,
        "requested_action_subtype": requested_action_subtype,
        "action_type": analysis.get("action_type"),
        "action_subtype": analysis.get("action_subtype"),
        "analysis_profile": analysis.get("analysis_profile"),
        "pipeline_version": analysis.get("pipeline_version"),
        "note": analysis.get("note"),
        "target": target,
        "pose": pose,
        "keyframes": keyframes,
        "video_temporal": video_temporal,
        "auto_eval": auto_eval,
        "quality_flags": _quality_flags(target, keyframes, video_temporal, vision, auto_eval),
        "processing_timings": analysis.get("processing_timings"),
        "created_at": analysis.get("created_at"),
        "updated_at": analysis.get("updated_at"),
        "error_code": analysis.get("error_code"),
        "error_message": analysis.get("error_message"),
        "error_detail": analysis.get("error_detail"),
    }


def _is_jump_profile(item: dict[str, Any]) -> bool:
    return str(item.get("analysis_profile") or "").strip().lower() == "jump"


def _keyframe_progress_label(summary: dict[str, Any]) -> str:
    keyframes = summary.get("keyframes") if isinstance(summary.get("keyframes"), dict) else {}
    profile_coverage = _safe_float(keyframes.get("profile_keyframe_coverage_score"))
    tal_label = (
        f"TAL={_safe_float(keyframes.get('coverage_score')):.2%}"
        if _is_jump_profile(summary)
        else "TAL=n/a"
    )
    return f"profile_keyframes={profile_coverage:.2%} {tal_label}"


def _aggregate(items: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [item for item in items if item.get("status") == "completed"]
    completed_jump = [item for item in completed if _is_jump_profile(item)]
    failed = [item for item in items if item.get("status") == "failed"]
    awaiting = [item for item in items if item.get("status") == "awaiting_target_selection"]

    def avg(path: tuple[str, ...], source: list[dict[str, Any]] | None = None) -> float:
        values: list[float] = []
        for item in completed if source is None else source:
            current: Any = item
            for key in path:
                current = current.get(key) if isinstance(current, dict) else None
            if isinstance(current, (int, float)):
                values.append(float(current))
        return round(sum(values) / len(values), 4) if values else 0.0

    flag_counts: Counter[str] = Counter()
    profile_counts: Counter[str] = Counter()
    for item in completed:
        profile_counts[str(item.get("analysis_profile") or "unknown")] += 1
        for flag in item.get("quality_flags", []):
            flag_counts[str(flag)] += 1

    return {
        "videos_total": len(items),
        "completed": len(completed),
        "failed": len(failed),
        "awaiting_target_selection": len(awaiting),
        "average_force_score": avg(("force_score",)),
        "average_pose_tracked_ratio": avg(("pose", "tracked_ratio")),
        "average_pose_lost_ratio": avg(("pose", "lost_ratio")),
        "average_pose_low_confidence_ratio": avg(("pose", "low_confidence_ratio")),
        "average_keyframe_coverage": avg(("keyframes", "coverage_score"), completed_jump),
        "average_tal_keyframe_coverage": avg(("keyframes", "coverage_score"), completed_jump),
        "average_profile_keyframe_coverage": avg(("keyframes", "profile_keyframe_coverage_score")),
        "average_keyframe_confidence": avg(("keyframes", "average_confidence"), completed_jump),
        "average_tal_keyframe_confidence": avg(("keyframes", "average_confidence"), completed_jump),
        "tal_metric_profile": "jump",
        "tal_complete_rate": round(
            sum(1 for item in completed_jump if item.get("keyframes", {}).get("complete"))
            / max(len(completed_jump), 1),
            4,
        ),
        "tal_metric_completed_count": len(completed_jump),
        "profile_keyframe_complete_rate": round(
            sum(1 for item in completed if item.get("keyframes", {}).get("profile_keyframe_complete")) / max(len(completed), 1),
            4,
        ),
        "tal_order_valid_rate": round(
            sum(1 for item in completed_jump if item.get("keyframes", {}).get("tal_order_valid"))
            / max(len(completed_jump), 1),
            4,
        ),
        "semantic_frame_usage_rate": round(
            sum(1 for item in completed if item.get("video_temporal", {}).get("used_semantic_frames")) / max(len(completed), 1),
            4,
        ),
        "profile_counts": dict(profile_counts),
        "top_quality_flags": flag_counts.most_common(20),
        "failed_videos": [
            {
                "video": item.get("video"),
                "analysis_id": item.get("analysis_id"),
                "error_code": item.get("error_code"),
                "error_message": item.get("error_message"),
            }
            for item in failed
        ],
    }


def _write_outputs(output_dir: Path, label: str, payload: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{label}.json"
    md_path = output_dir / f"{label}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    aggregate = payload["aggregate"]
    lines = [
        "# API Batch Skate Analysis",
        "",
        f"- Label: {payload['label']}",
        f"- Generated: {payload['generated_at']}",
        f"- Completed: {aggregate['completed']}/{aggregate['videos_total']}",
        f"- Failed: {aggregate['failed']}",
        f"- Awaiting target selection: {aggregate['awaiting_target_selection']}",
        f"- Avg Force Score: {aggregate['average_force_score']:.2f}",
        f"- Avg pose tracked ratio: {aggregate['average_pose_tracked_ratio']:.2%}",
        f"- Avg pose lost ratio: {aggregate['average_pose_lost_ratio']:.2%}",
        f"- Avg pose low-confidence ratio: {aggregate['average_pose_low_confidence_ratio']:.2%}",
        f"- T/A/L metric jump count: {aggregate['tal_metric_completed_count']}",
        f"- Avg T/A/L keyframe coverage (jump only): {aggregate['average_tal_keyframe_coverage']:.2%}",
        f"- Avg T/A/L keyframe confidence (jump only): {aggregate['average_tal_keyframe_confidence']:.2%}",
        f"- T/A/L complete rate (jump only): {aggregate['tal_complete_rate']:.2%}",
        f"- T/A/L order-valid rate (jump only): {aggregate['tal_order_valid_rate']:.2%}",
        f"- Profile keyframe complete rate: {aggregate['profile_keyframe_complete_rate']:.2%}",
        f"- Avg profile keyframe coverage: {aggregate['average_profile_keyframe_coverage']:.2%}",
        f"- Semantic frame usage rate: {aggregate['semantic_frame_usage_rate']:.2%}",
        "",
        "## Profile Counts",
        "",
        json.dumps(aggregate["profile_counts"], ensure_ascii=False, indent=2),
        "",
        "## Top Quality Flags",
        "",
        json.dumps(aggregate["top_quality_flags"], ensure_ascii=False, indent=2),
        "",
    ]
    if aggregate["failed_videos"]:
        lines.extend(["## Failed Videos", "", json.dumps(aggregate["failed_videos"], ensure_ascii=False, indent=2), ""])
    md_path.write_text("\n".join(lines), encoding="utf-8")


class BatchClient:
    def __init__(self, base_url: str, timeout: float, *, retry_attempts: int = 3, retry_delay_seconds: float = 2.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=httpx.Timeout(timeout, connect=20.0), follow_redirects=True)
        self.retry_attempts = max(1, retry_attempts)
        self.retry_delay_seconds = max(0.0, retry_delay_seconds)

    def close(self) -> None:
        self.client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(1, self.retry_attempts + 1):
            try:
                return self.client.request(method, f"{self.base_url}{path}", **kwargs)
            except RETRYABLE_HTTP_ERRORS as exc:
                last_error = exc
                if attempt >= self.retry_attempts:
                    raise
                time.sleep(self.retry_delay_seconds * attempt)
        assert last_error is not None
        raise last_error

    def get_json(self, path: str, **params: Any) -> Any:
        response = self._request("GET", path, params={k: v for k, v in params.items() if v is not None})
        response.raise_for_status()
        return response.json()

    def post_json(self, path: str, payload: dict[str, Any] | None = None, **params: Any) -> Any:
        response = self._request(
            "POST",
            path,
            json=payload,
            params={k: v for k, v in params.items() if v is not None},
        )
        response.raise_for_status()
        return response.json()

    def upload(self, video_path: Path, data: dict[str, str]) -> dict[str, Any]:
        mime_type = mimetypes.guess_type(video_path.name)[0] or "video/mp4"
        last_error: Exception | None = None
        for attempt in range(1, self.retry_attempts + 1):
            try:
                with video_path.open("rb") as handle:
                    files = {"file": (video_path.name, handle, mime_type)}
                    response = self.client.post(f"{self.base_url}/api/analysis/upload", data=data, files=files)
                response.raise_for_status()
                return response.json()
            except RETRYABLE_HTTP_ERRORS as exc:
                last_error = exc
                if attempt >= self.retry_attempts:
                    raise
                time.sleep(self.retry_delay_seconds * attempt)
        assert last_error is not None
        raise last_error


def _find_existing_by_note(analyses: list[dict[str, Any]], note: str) -> dict[str, Any] | None:
    matches = [item for item in analyses if isinstance(item, dict) and item.get("note") == note]
    if not matches:
        return None
    current_version = _current_pipeline_version()

    def sort_key(item: dict[str, Any]) -> tuple[int, int, tuple[float, tuple[int, int, int], int]]:
        status = str(item.get("status") or "")
        pipeline_version = str(item.get("pipeline_version") or "")
        return (
            1 if status == "completed" else 0,
            1 if current_version and pipeline_version == current_version else 0,
            _row_recency_key(item),
        )

    return max(matches, key=sort_key)


def _load_completed_batch_results_from_path(
    path: Path | None,
    *,
    target_selection_video_names: set[str] | None = None,
) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("unique_by_video_rows"), list):
        rows = payload["unique_by_video_rows"]
    elif isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        rows = payload["rows"]
    elif isinstance(payload, dict):
        rows = payload.get("videos")
    else:
        rows = payload
    if not isinstance(rows, list):
        return []
    resumable_statuses = {"completed", "awaiting_target_selection"}
    selected_names = target_selection_video_names or set()
    resumable: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        video_name = str(item.get("video") or "").strip()
        if not video_name or item.get("status") not in resumable_statuses:
            continue
        if item.get("status") == "awaiting_target_selection" and video_name in selected_names:
            continue
        resumable.append(item)
    return resumable


def _load_completed_batch_results(
    paths: list[Path] | Path | None,
    *,
    target_selection_video_names: set[str] | None = None,
) -> list[dict[str, Any]]:
    if paths is None:
        return []
    path_list = paths if isinstance(paths, list) else [paths]
    latest_by_video: dict[str, dict[str, Any]] = {}
    no_video_rows: list[dict[str, Any]] = []
    for source_index, path in enumerate(path_list):
        for item in _load_completed_batch_results_from_path(
            path,
            target_selection_video_names=target_selection_video_names,
        ):
            row = dict(item)
            row["_resume_source_index"] = source_index
            video = str(row.get("video") or Path(str(row.get("video_path") or "")).name).strip()
            if not video:
                no_video_rows.append(row)
                continue
            previous = latest_by_video.get(video)
            if previous is None or (
                _row_recency_key(row),
                int(_safe_float(row.get("_resume_source_index")) or 0),
            ) >= (
                _row_recency_key(previous),
                int(_safe_float(previous.get("_resume_source_index")) or 0),
            ):
                latest_by_video[video] = row
    return [*latest_by_video.values(), *no_video_rows]


def _load_target_selection_map(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_items = payload.get("videos") if isinstance(payload, dict) and isinstance(payload.get("videos"), dict) else payload
    if not isinstance(raw_items, dict):
        raise ValueError("target selection JSON must be an object keyed by video file name.")
    selections: dict[str, dict[str, Any]] = {}
    for video_name, raw_selection in raw_items.items():
        if not isinstance(raw_selection, dict):
            raise ValueError(f"target selection for {video_name!r} must be an object.")
        user_values = {
            key: value
            for key, value in raw_selection.items()
            if not str(key).startswith("_")
        }
        if not any(str(value).strip() if isinstance(value, str) else value is not None for value in user_values.values()):
            continue
        selection: dict[str, Any] = {}
        candidate_id = str(raw_selection.get("candidate_id") or "").strip()
        if candidate_id:
            selection["candidate_id"] = candidate_id
        manual_bbox = raw_selection.get("manual_bbox")
        if manual_bbox is None and all(key in raw_selection for key in ("x", "y")):
            manual_bbox = {
                "x": raw_selection.get("x"),
                "y": raw_selection.get("y"),
                "width": raw_selection.get("width", raw_selection.get("w")),
                "height": raw_selection.get("height", raw_selection.get("h")),
            }
        if isinstance(manual_bbox, dict):
            selection["manual_bbox"] = manual_bbox
        if not selection:
            raise ValueError(f"target selection for {video_name!r} must include candidate_id or manual_bbox.")
        selections[str(video_name)] = selection
    return selections


def _explicit_target_payload(preview: dict[str, Any], selection: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(selection, dict):
        return None
    manual_bbox = selection.get("manual_bbox")
    if isinstance(manual_bbox, dict):
        return {"manual_bbox": manual_bbox}
    candidate_id = str(selection.get("candidate_id") or "").strip()
    if not candidate_id:
        return None
    candidates = preview.get("candidates") if isinstance(preview.get("candidates"), list) else []
    if candidates and not any(isinstance(item, dict) and str(item.get("id") or "") == candidate_id for item in candidates):
        raise ValueError(f"target candidate_id {candidate_id!r} was not present in target preview.")
    return {"candidate_id": candidate_id}


def _pick_target_candidate(
    preview: dict[str, Any],
    *,
    confirm_manual_review_auto_candidate: bool = False,
) -> str | None:
    status = str(preview.get("target_lock_status") or "")
    if status != "auto_locked" and not (confirm_manual_review_auto_candidate and status == "awaiting_manual"):
        return None
    auto_id = preview.get("auto_candidate_id")
    if auto_id:
        candidates = preview.get("candidates")
        if isinstance(candidates, list):
            for item in candidates:
                if not isinstance(item, dict) or str(item.get("id") or "") != str(auto_id):
                    continue
                flags = item.get("quality_flags")
                if (
                    not confirm_manual_review_auto_candidate
                    and isinstance(flags, list)
                    and any("_manual_review" in str(flag) for flag in flags)
                ):
                    return None
                break
        return str(auto_id)
    if confirm_manual_review_auto_candidate:
        return None
    candidates = preview.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return None
    candidates = [
        item
        for item in candidates
        if isinstance(item, dict)
        and item.get("id")
        and not (
            isinstance(item.get("quality_flags"), list)
            and any("_manual_review" in str(flag) for flag in item.get("quality_flags", []))
        )
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda item: (_safe_float(item.get("confidence")), _bbox_area(item.get("bbox"))), reverse=True)
    return str(candidates[0].get("id"))


def _poll_until_done(
    api: BatchClient,
    analysis_id: str,
    *,
    poll_seconds: float,
    max_wait_seconds: float,
    auto_confirm_target: bool,
    target_selection: dict[str, Any] | None = None,
    confirm_manual_review_auto_candidate: bool = False,
) -> dict[str, Any]:
    started = time.monotonic()
    target_confirm_attempted = False
    last_poll_error: Exception | None = None
    while True:
        try:
            analysis = api.get_json(f"/api/analysis/{analysis_id}", is_parent_request="true")
            last_poll_error = None
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in POLL_RETRYABLE_STATUS_CODES:
                raise
            last_poll_error = exc
            if time.monotonic() - started > max_wait_seconds:
                raise TimeoutError(
                    f"analysis {analysis_id} did not finish within {max_wait_seconds:.0f}s; "
                    f"last poll failed with HTTP {exc.response.status_code}"
                ) from exc
            print(
                f"  poll transient HTTP {exc.response.status_code}; retrying in {poll_seconds:.1f}s",
                flush=True,
            )
            time.sleep(poll_seconds)
            continue
        except RETRYABLE_HTTP_ERRORS as exc:
            last_poll_error = exc
            if time.monotonic() - started > max_wait_seconds:
                raise TimeoutError(
                    f"analysis {analysis_id} did not finish within {max_wait_seconds:.0f}s; "
                    f"last poll failed with {type(exc).__name__}"
                ) from exc
            print(f"  poll transient {type(exc).__name__}; retrying in {poll_seconds:.1f}s", flush=True)
            time.sleep(poll_seconds)
            continue
        status = str(analysis.get("status") or "")
        if status == "awaiting_target_selection" and auto_confirm_target and not target_confirm_attempted:
            target_confirm_attempted = True
            preview = api.get_json(f"/api/analysis/{analysis_id}/target-preview")
            target_payload = _explicit_target_payload(preview, target_selection)
            if target_payload is None:
                candidate_id = _pick_target_candidate(
                    preview,
                    confirm_manual_review_auto_candidate=confirm_manual_review_auto_candidate,
                )
                target_payload = {"candidate_id": candidate_id} if candidate_id else None
            if target_payload:
                api.post_json(f"/api/analysis/{analysis_id}/target-lock", target_payload)
                time.sleep(max(poll_seconds, 2.0))
                continue
        if status not in IN_PROGRESS_STATUSES:
            return analysis
        if time.monotonic() - started > max_wait_seconds:
            message = f"analysis {analysis_id} did not finish within {max_wait_seconds:.0f}s"
            if last_poll_error is not None:
                message = f"{message}; last poll failed with {type(last_poll_error).__name__}"
            raise TimeoutError(message)
        time.sleep(poll_seconds)


def _process_video_job(
    *,
    base_url: str,
    timeout: float,
    video_path: Path,
    note: str,
    requested_action_type: str,
    requested_action_subtype: str,
    action_type: str,
    action_subtype: str | None,
    skill_category: str,
    skater_id: str,
    existing_match: dict[str, Any] | None,
    poll_seconds: float,
    max_wait_seconds: float,
    auto_confirm_target: bool,
    target_selection: dict[str, Any] | None,
    confirm_manual_review_auto_candidate: bool,
) -> dict[str, Any]:
    api = BatchClient(base_url, timeout)
    try:
        created = False
        if existing_match and existing_match.get("id"):
            analysis_id = str(existing_match["id"])
            print(f"  reuse {analysis_id} status={existing_match.get('status')}", flush=True)
            analysis = api.get_json(f"/api/analysis/{analysis_id}", is_parent_request="true")
            status = str(analysis.get("status") or "")
            if status in IN_PROGRESS_STATUSES or status == "awaiting_target_selection":
                analysis = _poll_until_done(
                    api,
                    analysis_id,
                    poll_seconds=poll_seconds,
                    max_wait_seconds=max_wait_seconds,
                    auto_confirm_target=auto_confirm_target,
                    target_selection=target_selection,
                    confirm_manual_review_auto_candidate=confirm_manual_review_auto_candidate,
                )
        else:
            data = {
                "action_type": action_type,
                "note": note,
            }
            if action_subtype:
                data["action_subtype"] = action_subtype
            if skater_id:
                data["skater_id"] = skater_id
            if skill_category.strip():
                data["skill_category"] = skill_category.strip()
            uploaded = api.upload(video_path, data)
            analysis_id = str(uploaded["id"])
            created = True
            print(f"  uploaded {analysis_id}", flush=True)
            analysis = _poll_until_done(
                api,
                analysis_id,
                poll_seconds=poll_seconds,
                max_wait_seconds=max_wait_seconds,
                auto_confirm_target=auto_confirm_target,
                target_selection=target_selection,
                confirm_manual_review_auto_candidate=confirm_manual_review_auto_candidate,
            )
        return _analysis_summary(
            video_path,
            analysis,
            created=created,
            requested_action_type=requested_action_type,
            requested_action_subtype=requested_action_subtype,
        )
    finally:
        api.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload local skating videos through the running API and wait for full analyses.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--video-dir", type=Path, default=DEFAULT_VIDEO_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--label", default=datetime.now().strftime("run-%Y%m%d-%H%M%S"))
    parser.add_argument("--note-prefix", default=DEFAULT_NOTE_PREFIX)
    parser.add_argument(
        "--action-type",
        default=AUTO_ACTION_TYPE,
        help="Action type to send. Use auto (default) to upload as 自由滑/节目片段 and infer jump/spin/step/spiral.",
    )
    parser.add_argument(
        "--action-subtype",
        default="",
        help="Optional action subtype. Leave empty in auto mode.",
    )
    parser.add_argument("--skill-category", default="")
    parser.add_argument("--skater-id", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="Analyze only videos whose file name matches one of these exact names. Can be passed multiple times.",
    )
    parser.add_argument("--poll-seconds", type=float, default=8.0)
    parser.add_argument("--max-wait-seconds", type=float, default=900.0)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--api-retry-attempts",
        type=int,
        default=3,
        help="Retry attempts for transient API disconnects before upload/polling starts.",
    )
    parser.add_argument(
        "--api-retry-delay-seconds",
        type=float,
        default=2.0,
        help="Base delay for transient API request retries; actual delay is multiplied by attempt number.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Maximum active upload/poll jobs. Jobs are submitted lazily so backend queue depth stays bounded.",
    )
    parser.add_argument(
        "--stop-on-failure",
        action="store_true",
        help="Stop submitting new videos after the first failed batch job; active jobs are allowed to finish.",
    )
    parser.add_argument("--force", action="store_true", help="Create new analyses even when a completed matching note exists.")
    parser.add_argument(
        "--skip-completed-from",
        type=Path,
        action="append",
        default=[],
        help="Existing batch JSON whose completed or awaiting-target-selection rows should be kept and skipped when resuming a run.",
    )
    parser.add_argument("--no-auto-confirm-target", action="store_true")
    parser.add_argument(
        "--confirm-manual-review-auto-candidate",
        action="store_true",
        help="Research mode: confirm the preview auto_candidate_id even when the target lock requires manual review.",
    )
    parser.add_argument(
        "--target-selection-json",
        type=Path,
        default=None,
        help="Optional JSON map keyed by video name with candidate_id or manual_bbox for explicit target confirmation.",
    )
    args = parser.parse_args()
    upload_action_type, upload_action_subtype = _resolve_upload_action(args.action_type, args.action_subtype)

    only_names = {str(name).strip() for name in args.only if str(name).strip()}
    video_paths = sorted(path for path in args.video_dir.iterdir() if path.suffix.lower() in VIDEO_SUFFIXES)
    if only_names:
        video_paths = [path for path in video_paths if path.name in only_names]
        missing_names = sorted(only_names - {path.name for path in video_paths})
        if missing_names:
            parser.error(f"--only names not found in {args.video_dir}: {', '.join(missing_names)}")
    if args.limit > 0:
        video_paths = video_paths[: args.limit]
    target_selections = _load_target_selection_map(args.target_selection_json)
    resumed_results = _load_completed_batch_results(
        args.skip_completed_from,
        target_selection_video_names=set(target_selections),
    )
    resumed_by_video = {str(item.get("video") or ""): item for item in resumed_results}
    if resumed_by_video:
        video_paths = [path for path in video_paths if path.name not in resumed_by_video]
        print(f"Resuming from {args.skip_completed_from}: keeping {len(resumed_by_video)} completed videos.", flush=True)
    api = BatchClient(
        args.base_url,
        args.timeout,
        retry_attempts=args.api_retry_attempts,
        retry_delay_seconds=args.api_retry_delay_seconds,
    )
    results: list[dict[str, Any]] = list(resumed_by_video.values())
    try:
        skaters = api.get_json("/api/skaters")
        skater_id = args.skater_id.strip()
        if not skater_id and isinstance(skaters, list):
            default_skater = next((item for item in skaters if isinstance(item, dict) and item.get("is_default")), None)
            if isinstance(default_skater, dict):
                skater_id = str(default_skater.get("id") or "")

        existing_items: list[dict[str, Any]] = []
        if not args.force:
            existing = api.get_json("/api/analysis/", limit=500)
            existing_items = existing if isinstance(existing, list) else []

        jobs = []
        for index, video_path in enumerate(video_paths, start=1):
            note = f"{args.note_prefix} {video_path.name}"
            existing_match = None if args.force else _find_existing_by_note(existing_items, note)
            jobs.append((index, video_path, note, existing_match))

        output_lock = Lock()

        def persist_progress(summary: dict[str, Any]) -> None:
            with output_lock:
                existing_index = next(
                    (idx for idx, item in enumerate(results) if item.get("video") == summary.get("video")),
                    None,
                )
                if existing_index is None:
                    results.append(summary)
                else:
                    results[existing_index] = summary
                results.sort(key=lambda item: str(item.get("video") or ""))
                payload = {
                    "label": args.label,
                    "generated_at": datetime.now().isoformat(timespec="seconds"),
                    "base_url": args.base_url,
                    "video_dir": str(args.video_dir),
                    "note_prefix": args.note_prefix,
                    "requested_action_type": args.action_type,
                    "requested_action_subtype": args.action_subtype,
                    "upload_action_type": upload_action_type,
                    "upload_action_subtype": upload_action_subtype,
                    "aggregate": _aggregate(results),
                    "videos": results,
                }
                _write_outputs(args.output_dir, args.label, payload)

        if max(1, args.concurrency) == 1:
            for index, video_path, note, existing_match in jobs:
                print(f"[{index}/{len(video_paths)}] {video_path.name}", flush=True)
                summary = _process_video_job(
                    base_url=args.base_url,
                    timeout=args.timeout,
                    video_path=video_path,
                    note=note,
                    requested_action_type=args.action_type,
                    requested_action_subtype=args.action_subtype,
                    action_type=upload_action_type,
                    action_subtype=upload_action_subtype,
                    skill_category=args.skill_category,
                    skater_id=skater_id,
                    existing_match=existing_match,
                    poll_seconds=args.poll_seconds,
                    max_wait_seconds=args.max_wait_seconds,
                    auto_confirm_target=not args.no_auto_confirm_target,
                    target_selection=target_selections.get(video_path.name),
                    confirm_manual_review_auto_candidate=args.confirm_manual_review_auto_candidate,
                )
                persist_progress(summary)
                print(
                    f"  done status={summary['status']} score={summary.get('force_score')} "
                    f"pose={summary['pose']['tracked_ratio']:.2%} "
                    f"profile={summary.get('analysis_profile')} "
                    f"{_keyframe_progress_label(summary)}",
                    flush=True,
                )
        else:
            worker_count = max(1, args.concurrency)
            stop_submitting = False
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                future_map = {}
                next_job_index = 0

                def submit_next_job() -> bool:
                    nonlocal next_job_index
                    if next_job_index >= len(jobs):
                        return False
                    index, video_path, note, existing_match = jobs[next_job_index]
                    next_job_index += 1
                    print(f"[{index}/{len(video_paths)}] queued {video_path.name}", flush=True)
                    future = executor.submit(
                        _process_video_job,
                        base_url=args.base_url,
                        timeout=args.timeout,
                        video_path=video_path,
                        note=note,
                        requested_action_type=args.action_type,
                        requested_action_subtype=args.action_subtype,
                        action_type=upload_action_type,
                        action_subtype=upload_action_subtype,
                        skill_category=args.skill_category,
                        skater_id=skater_id,
                        existing_match=existing_match,
                        poll_seconds=args.poll_seconds,
                        max_wait_seconds=args.max_wait_seconds,
                        auto_confirm_target=not args.no_auto_confirm_target,
                        target_selection=target_selections.get(video_path.name),
                        confirm_manual_review_auto_candidate=args.confirm_manual_review_auto_candidate,
                    )
                    future_map[future] = (index, video_path)
                    return True

                for _ in range(min(worker_count, len(jobs))):
                    submit_next_job()

                while future_map:
                    for future in as_completed(list(future_map)):
                        break
                    index, video_path = future_map.pop(future)
                    try:
                        summary = future.result()
                    except Exception as exc:  # noqa: BLE001
                        summary = {
                            "video": video_path.name,
                            "video_path": str(video_path),
                            "analysis_id": None,
                            "report_url": None,
                            "created_by_batch": False,
                            "status": "failed",
                            "force_score": None,
                            "requested_action_type": args.action_type,
                            "requested_action_subtype": args.action_subtype,
                            "action_type": upload_action_type,
                            "action_subtype": upload_action_subtype,
                            "analysis_profile": None,
                            "pipeline_version": None,
                            "note": f"{args.note_prefix} {video_path.name}",
                            "target": {},
                            "pose": {"tracked_ratio": 0.0, "lost_ratio": 0.0, "low_confidence_ratio": 0.0},
                            "keyframes": {"coverage_score": 0.0, "average_confidence": 0.0, "complete": False},
                            "video_temporal": {"available": False},
                            "auto_eval": {},
                            "quality_flags": ["batch_job_exception"],
                            "processing_timings": None,
                            "created_at": None,
                            "updated_at": None,
                            "error_code": "BATCH_JOB_EXCEPTION",
                            "error_message": f"{type(exc).__name__}: {exc}",
                            "error_detail": str(exc),
                        }
                    persist_progress(summary)
                    print(
                        f"[{index}/{len(video_paths)}] done {video_path.name} status={summary['status']} "
                        f"score={summary.get('force_score')} pose={summary['pose'].get('tracked_ratio', 0.0):.2%} "
                        f"profile={summary.get('analysis_profile')} "
                        f"{_keyframe_progress_label(summary)}",
                        flush=True,
                    )
                    if args.stop_on_failure and summary.get("status") == "failed":
                        stop_submitting = True
                    if not stop_submitting:
                        submit_next_job()
    finally:
        api.close()

    print(json.dumps(_aggregate(results), ensure_ascii=True, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
