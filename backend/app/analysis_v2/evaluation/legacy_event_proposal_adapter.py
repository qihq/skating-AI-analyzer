from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.analysis_v2.event_proposals import ProposalEvidenceSample


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if result == result and abs(result) != float("inf") else default
    except (TypeError, ValueError):
        return default


def _records(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else []


def _periodicity(values: Sequence[float], index: int) -> float:
    window = values[max(0, index - 3): index + 4]
    if len(window) < 4:
        return 0.0
    changes = [window[pos + 1] - window[pos] for pos in range(len(window) - 1)]
    return min(1.0, sum(changes[pos] * changes[pos + 1] < 0 for pos in range(len(changes) - 1)) / 3)


def evidence_from_legacy_analysis(source_hash: str, analysis: Mapping[str, Any]) -> tuple[float, tuple[ProposalEvidenceSample, ...]]:
    motion = analysis.get("frame_motion_scores") if isinstance(analysis.get("frame_motion_scores"), Mapping) else {}
    selected = _records(motion.get("selected"))
    timestamps = {str(item.get("frame_id")): _number(item.get("timestamp")) for item in selected}
    pose_payload = analysis.get("pose_data") if isinstance(analysis.get("pose_data"), Mapping) else {}
    pose: dict[float, tuple[float, float, bool]] = {}
    previous_center: tuple[float, float] | None = None
    for item in _records(pose_payload.get("frames")):
        pts = timestamps.get(str(item.get("frame", "")).replace(".jpg", ""))
        if pts is None:
            continue
        points = [(_number(point.get("x")), _number(point.get("y"))) for point in _records(item.get("keypoints")) if _number(point.get("visibility", point.get("confidence", 0))) >= 0.35]
        center = (sum(x for x, _ in points) / len(points), sum(y for _, y in points) / len(points)) if points else None
        dynamics = 0.0 if center is None or previous_center is None else min(1.0, ((center[0] - previous_center[0]) ** 2 + (center[1] - previous_center[1]) ** 2) ** 0.5 * 8)
        bbox = item.get("target_bbox") if isinstance(item.get("target_bbox"), Mapping) else {}
        contact = min(1.0, dynamics * 0.55 + max(0.0, 0.20 - _number(bbox.get("height"))) * 1.8)
        pose[pts] = (dynamics, contact, bool(points) and str(item.get("tracking_state", "")) not in {"lost", "uncertain"})
        if center is not None:
            previous_center = center
    values = [_number(item.get("motion_score")) for item in selected]
    peak = max(values, default=1.0) or 1.0
    temporal = analysis.get("video_temporal_diagnostics") if isinstance(analysis.get("video_temporal_diagnostics"), Mapping) else {}
    semantic = min(0.35, _number(temporal.get("resolved_confidence"), _number(temporal.get("video_ai_confidence"))))
    samples = tuple(ProposalEvidenceSample(
        source_frame_index=max(0, int(_number(item.get("source_thumb_index"), index))), pts_sec=_number(item.get("timestamp")),
        camera_compensated_track_motion=min(1.0, _number(item.get("motion_score")) / peak), pose_dynamics=pose.get(_number(item.get("timestamp")), (0, 0, False))[0],
        ice_contact_proxy=pose.get(_number(item.get("timestamp")), (0, 0, False))[1], periodicity=_periodicity(values, index),
        semantic_hints={key: semantic for key in ("jump", "spin", "step", "spiral")}, tracking_observable=True,
        pose_observable=pose.get(_number(item.get("timestamp")), (0, 0, False))[2], camera_reliability=0.45,
        provenance=("legacy_motion_fixture", "legacy_pose_fixture", "bounded_untyped_semantic_hint"),
    ) for index, item in enumerate(selected))
    duration = _number(analysis.get("source_duration_sec"), _number(motion.get("source_duration_sec"), max((item.pts_sec for item in samples), default=0.0)))
    return max(duration, 0.001), samples
