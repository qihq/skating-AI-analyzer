from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from app.services.analysis_errors import AnalysisErrorCode, AnalysisPipelineError


TARGET_LOCK_AUTO_THRESHOLD = 0.72
TARGET_PERSON_MIN_CONFIDENCE = 0.15
MANUAL_BBOX_MIN_SIDE = 0.02


@dataclass(slots=True)
class TargetPreview:
    preview_frame: str | None
    preview_frame_url: str | None
    auto_candidate_id: str | None
    lock_confidence: float
    candidates: list[dict[str, Any]]
    target_lock_status: str


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


def _normalized_bbox(x: float, y: float, width: float, height: float) -> dict[str, float]:
    return {
        "x": round(_clamp(x, 0.0, 1.0), 4),
        "y": round(_clamp(y, 0.0, 1.0), 4),
        "width": round(_clamp(width, MANUAL_BBOX_MIN_SIDE, 1.0), 4),
        "height": round(_clamp(height, MANUAL_BBOX_MIN_SIDE, 1.0), 4),
    }


def validate_manual_bbox(bbox: dict[str, Any] | None) -> dict[str, float]:
    """校验并标准化前端手动框选的主目标 bbox。

    Args:
        bbox: 前端传入的归一化 bbox，支持 width/height 或 w/h 字段。

    Returns:
        标准化后的 bbox，字段为 x/y/width/height。

    Raises:
        AnalysisPipelineError: bbox 缺字段、越界或尺寸过小时抛出 TARGET_BBOX_INVALID。
    """
    if not isinstance(bbox, dict):
        raise AnalysisPipelineError(AnalysisErrorCode.TARGET_BBOX_INVALID, "manual_bbox must be an object.")

    try:
        x = float(bbox["x"])
        y = float(bbox["y"])
        width = float(bbox.get("width", bbox.get("w")))
        height = float(bbox.get("height", bbox.get("h")))
    except (KeyError, TypeError, ValueError) as exc:
        raise AnalysisPipelineError(AnalysisErrorCode.TARGET_BBOX_INVALID, "manual_bbox requires x/y/w/h values.") from exc

    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 and 0.0 <= width <= 1.0 and 0.0 <= height <= 1.0):
        raise AnalysisPipelineError(AnalysisErrorCode.TARGET_BBOX_INVALID, "manual_bbox values must be normalized to 0-1.")
    if width < MANUAL_BBOX_MIN_SIDE or height < MANUAL_BBOX_MIN_SIDE:
        raise AnalysisPipelineError(
            AnalysisErrorCode.TARGET_BBOX_INVALID,
            f"manual_bbox width and height must be at least {MANUAL_BBOX_MIN_SIDE}.",
        )
    if x + width > 1.0 or y + height > 1.0:
        raise AnalysisPipelineError(AnalysisErrorCode.TARGET_BBOX_INVALID, "manual_bbox must stay inside the frame.")

    return {
        "x": round(x, 4),
        "y": round(y, 4),
        "width": round(width, 4),
        "height": round(height, 4),
    }


def _fallback_candidates(frame_names: Sequence[str]) -> list[dict[str, Any]]:
    return []


def build_target_preview(
    analysis_id: str,
    frame_names: Sequence[str],
    *,
    existing_target_lock: dict[str, Any] | None = None,
) -> TargetPreview:
    preview_frame = frame_names[0] if frame_names else None
    candidates = _fallback_candidates(frame_names)

    if isinstance(existing_target_lock, dict) and existing_target_lock.get("candidates"):
        candidates = [item for item in existing_target_lock.get("candidates", []) if isinstance(item, dict)]

    visible_candidates = [
        item
        for item in candidates
        if isinstance(item, dict) and float(item.get("confidence", 0.0) or 0.0) >= TARGET_PERSON_MIN_CONFIDENCE
    ]
    if not visible_candidates:
        auto_candidate_id = None
        lock_confidence = 0.0
        target_lock_status = "no_person_detected"
    else:
        auto_candidate_id = str(visible_candidates[0].get("id") or "") or None
        lock_confidence = float(visible_candidates[0].get("confidence", 0.0) or 0.0)
        target_lock_status = "auto_locked" if lock_confidence >= TARGET_LOCK_AUTO_THRESHOLD else "awaiting_manual"

    if isinstance(existing_target_lock, dict):
        auto_candidate_id = str(existing_target_lock.get("selected_candidate_id") or auto_candidate_id or "")
        lock_confidence = float(existing_target_lock.get("lock_confidence", lock_confidence) or lock_confidence)
        target_lock_status = str(existing_target_lock.get("status", target_lock_status))

    return TargetPreview(
        preview_frame=preview_frame,
        preview_frame_url=f"/api/frames/{analysis_id}/{preview_frame}" if preview_frame else None,
        auto_candidate_id=auto_candidate_id or None,
        lock_confidence=round(lock_confidence, 4),
        candidates=candidates,
        target_lock_status=target_lock_status,
    )


def resolve_manual_candidate(
    candidates: Sequence[dict[str, Any]],
    candidate_id: str | None,
    x: float | None,
    y: float | None,
) -> dict[str, Any] | None:
    if candidate_id:
        for candidate in candidates:
            if str(candidate.get("id")) == candidate_id:
                return candidate

    if x is None or y is None:
        return None

    for candidate in candidates:
        bbox = candidate.get("bbox")
        if not isinstance(bbox, dict):
            continue
        left = float(bbox.get("x", 0.0))
        top = float(bbox.get("y", 0.0))
        width = float(bbox.get("width", 0.0))
        height = float(bbox.get("height", 0.0))
        if left <= x <= left + width and top <= y <= top + height:
            return candidate
    return None


def build_target_lock_payload(
    preview: TargetPreview,
    *,
    selected_candidate: dict[str, Any] | None = None,
    manual_bbox: dict[str, Any] | None = None,
    manual: bool = False,
) -> dict[str, Any]:
    if manual_bbox is not None:
        selected_bbox = validate_manual_bbox(manual_bbox)
        return {
            "preview_frame": preview.preview_frame,
            "candidates": preview.candidates,
            "selected_candidate_id": None,
            "selected_bbox": selected_bbox,
            "lock_confidence": 1.0,
            "status": "manual",
            "manual_override": True,
            "quality_flags": [],
        }

    chosen = selected_candidate
    if chosen is None and preview.auto_candidate_id:
        chosen = next((item for item in preview.candidates if str(item.get("id")) == preview.auto_candidate_id), None)

    return {
        "preview_frame": preview.preview_frame,
        "candidates": preview.candidates,
        "selected_candidate_id": chosen.get("id") if isinstance(chosen, dict) else preview.auto_candidate_id,
        "selected_bbox": chosen.get("bbox") if isinstance(chosen, dict) else None,
        "lock_confidence": float(chosen.get("confidence", preview.lock_confidence)) if isinstance(chosen, dict) else preview.lock_confidence,
        "status": "locked" if manual else preview.target_lock_status,
        "manual_override": manual,
        "quality_flags": [],
    }


def extract_pose_target_bbox(target_lock: dict[str, Any] | None) -> dict[str, float] | None:
    if not isinstance(target_lock, dict):
        return None
    bbox = target_lock.get("selected_bbox")
    return bbox if isinstance(bbox, dict) else None


def frame_names_from_dir(frames_dir: str | Path) -> list[str]:
    frame_paths = sorted(Path(frames_dir).glob("frame_*.jpg"))
    return [frame_path.name for frame_path in frame_paths]
