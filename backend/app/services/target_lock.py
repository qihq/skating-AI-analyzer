from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from app.services.analysis_errors import AnalysisErrorCode, AnalysisPipelineError


TARGET_LOCK_AUTO_THRESHOLD = 0.72
TARGET_LOCK_STABLE_ZOOMED_AUTO_THRESHOLD = 0.68
TARGET_LOCK_STABLE_ZOOMED_MIN_SUPPORT = 5
TARGET_LOCK_STABLE_ZOOMED_MAX_AREA = 0.04
TARGET_LOCK_STABLE_ZOOMED_NEAR_THRESHOLD = 0.70
TARGET_LOCK_STABLE_ZOOMED_NEAR_MIN_SUPPORT = 8
TARGET_LOCK_STABLE_ZOOMED_NEAR_MAX_AREA = 0.12
TARGET_LOCK_STABLE_ZOOMED_AGGREGATE_THRESHOLD = 0.78
TARGET_LOCK_STABLE_ZOOMED_AGGREGATE_MIN_SUPPORT = 8
TARGET_LOCK_STABLE_ZOOMED_AGGREGATE_MIN_UNIQUE_FRAMES = 5
TARGET_LOCK_STABLE_ZOOMED_AGGREGATE_MAX_AREA = 0.012
TARGET_LOCK_TINY_ZOOMED_MANUAL_REVIEW_MAX_AREA = 0.012
TARGET_LOCK_TINY_ZOOMED_MIN_SUPPORT_CONFIDENCE = 0.65
TARGET_LOCK_DISTANT_SINGLE_JUMP_MIN_SUPPORT = 3
TARGET_LOCK_DISTANT_SINGLE_JUMP_MIN_UNIQUE_FRAMES = 2
TARGET_LOCK_DISTANT_SINGLE_JUMP_MIN_CONFIDENCE = 0.40
TARGET_LOCK_DISTANT_SINGLE_JUMP_MAX_AREA = 0.010
TARGET_LOCK_DISTANT_SINGLE_JUMP_MAX_COMPETITOR_CONFIDENCE = 0.35
TARGET_PERSON_MIN_CONFIDENCE = 0.15
MANUAL_BBOX_MIN_SIDE = 0.02
FALLBACK_TARGET_CONFIDENCE = 0.22
TARGET_PREVIEW_ANCHOR_FRACTIONS = (0.50, 0.42, 0.58, 0.35, 0.65, 0.25, 0.75)
TARGET_PREVIEW_CENTER_DISTANCE = 0.22
TARGET_PREVIEW_AREA_RATIO_RANGE = (0.20, 5.0)
TARGET_LOCK_TINY_STABLE_MAX_AREA = 0.012
TARGET_LOCK_COMPLETE_BODY_MIN_AREA = 0.045
TARGET_LOCK_COMPLETE_BODY_MAX_AREA = 0.18
TARGET_LOCK_COMPLETE_BODY_MIN_HEIGHT = 0.35
TARGET_LOCK_COMPLETE_BODY_MIN_WIDTH = 0.07
TARGET_LOCK_COMPLETE_BODY_CONFIDENCE_ADVANTAGE = 0.15
TARGET_LOCK_ZOOMED_MULTIPERSON_MIN_CONFIDENCE = 0.55
TARGET_LOCK_ZOOMED_MULTIPERSON_MIN_CENTER_DISTANCE = 0.08


@dataclass(slots=True)
class TargetPreview:
    preview_frame: str | None
    preview_frame_url: str | None
    preview_frame_index: int | None
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
    if not frame_names:
        return []
    return [
        {
            "id": "fallback_center",
            "bbox": _normalized_bbox(0.40, 0.24, 0.20, 0.42),
            "confidence": FALLBACK_TARGET_CONFIDENCE,
            "source": "layout_fallback",
        }
    ]


def _candidate_id(candidate: dict[str, Any]) -> str:
    return str(candidate.get("id") or "").strip()


def _merge_strings(*sources: Sequence[Any]) -> list[str]:
    merged: list[str] = []
    for source in sources:
        for item in source:
            value = str(item).strip()
            if value and value not in merged:
                merged.append(value)
    return merged


def _candidate_sort_key(candidate: dict[str, Any]) -> tuple[float, float]:
    try:
        confidence = float(candidate.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    bbox = candidate.get("bbox")
    area = _bbox_area(bbox) if isinstance(bbox, dict) else 0.0
    return confidence, area


def _candidate_rank_score(candidate: dict[str, Any]) -> float:
    confidence, area = _candidate_sort_key(candidate)
    support = 0.0
    try:
        support = float(candidate.get("support_count", 0.0) or 0.0)
    except (TypeError, ValueError):
        support = 0.0
    source = str(candidate.get("source") or "")
    zoom_bonus = 0.20 if source == "yolo_zoomed_content" else 0.0
    stable_bonus = 1.5 if support >= 2 else 0.0
    foreground_penalty = 1.0 if area >= 0.18 and support < 2 else 0.0
    return stable_bonus + min(support, 4.0) * 0.25 + confidence + zoom_bonus - foreground_penalty - max(0.0, area - 0.16)


def _stable_zoomed_candidate_auto_lock_flags(candidate: dict[str, Any]) -> list[str]:
    bbox = candidate.get("bbox")
    if not isinstance(bbox, dict):
        return []
    try:
        confidence = float(candidate.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    try:
        support_count = int(candidate.get("support_count", 0) or 0)
    except (TypeError, ValueError):
        support_count = 0
    try:
        support_frame_count = int(candidate.get("support_frame_count", 0) or 0)
    except (TypeError, ValueError):
        support_frame_count = 0
    try:
        support_confidence = float(candidate.get("support_confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        support_confidence = 0.0
    source = str(candidate.get("source") or "")
    area = _bbox_area(bbox)
    if source != "yolo_zoomed_content" or area <= 0.0:
        return []
    low_aggregate_support = bool(
        support_confidence
        and support_confidence < TARGET_LOCK_TINY_ZOOMED_MIN_SUPPORT_CONFIDENCE
        and area <= TARGET_LOCK_TINY_ZOOMED_MANUAL_REVIEW_MAX_AREA
    )
    if low_aggregate_support:
        return []

    aggregate_stable_target = (
        support_confidence >= TARGET_LOCK_STABLE_ZOOMED_AGGREGATE_THRESHOLD
        and support_count >= TARGET_LOCK_STABLE_ZOOMED_AGGREGATE_MIN_SUPPORT
        and support_frame_count >= TARGET_LOCK_STABLE_ZOOMED_AGGREGATE_MIN_UNIQUE_FRAMES
        and area <= TARGET_LOCK_STABLE_ZOOMED_AGGREGATE_MAX_AREA
    )
    small_stable_target = (
        confidence >= TARGET_LOCK_STABLE_ZOOMED_AUTO_THRESHOLD
        and support_count >= TARGET_LOCK_STABLE_ZOOMED_MIN_SUPPORT
        and area <= TARGET_LOCK_STABLE_ZOOMED_MAX_AREA
    )
    near_threshold_stable_target = (
        confidence >= TARGET_LOCK_STABLE_ZOOMED_NEAR_THRESHOLD
        and support_count >= TARGET_LOCK_STABLE_ZOOMED_NEAR_MIN_SUPPORT
        and area <= TARGET_LOCK_STABLE_ZOOMED_NEAR_MAX_AREA
    )
    if not aggregate_stable_target and not small_stable_target and not near_threshold_stable_target:
        return []
    flags = ["target_lock_stable_zoomed_candidate_auto_locked"]
    if aggregate_stable_target:
        flags.append("target_lock_stable_zoomed_aggregate_confidence_auto_locked")
    if near_threshold_stable_target and not small_stable_target:
        flags.append("target_lock_stable_zoomed_near_threshold_auto_locked")
    return flags


def _tiny_zoomed_candidate_requires_manual_review(candidate: dict[str, Any]) -> bool:
    bbox = candidate.get("bbox")
    if not isinstance(bbox, dict) or str(candidate.get("source") or "") != "yolo_zoomed_content":
        return False
    if _bbox_area(bbox) > TARGET_LOCK_TINY_ZOOMED_MANUAL_REVIEW_MAX_AREA:
        return False
    try:
        support_count = int(candidate.get("support_count", 0) or 0)
    except (TypeError, ValueError):
        support_count = 0
    try:
        support_frame_count = int(candidate.get("support_frame_count", 0) or 0)
    except (TypeError, ValueError):
        support_frame_count = 0
    try:
        support_confidence = float(candidate.get("support_confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        support_confidence = 0.0
    if support_count < 2 and support_frame_count < 2:
        return True
    return bool(support_confidence and support_confidence < TARGET_LOCK_TINY_ZOOMED_MIN_SUPPORT_CONFIDENCE)


def _distant_single_jump_auto_lock_flags(
    candidate: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
    analysis_profile: str | None,
) -> list[str]:
    if str(analysis_profile or "").strip().lower() != "jump":
        return []
    bbox = candidate.get("bbox")
    if not isinstance(bbox, dict) or str(candidate.get("source") or "") != "yolo_zoomed_content":
        return []
    area = _bbox_area(bbox)
    if area <= 0.0 or area > TARGET_LOCK_DISTANT_SINGLE_JUMP_MAX_AREA:
        return []
    try:
        confidence = float(candidate.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    try:
        support_count = int(candidate.get("support_count", 0) or 0)
    except (TypeError, ValueError):
        support_count = 0
    try:
        support_frame_count = int(candidate.get("support_frame_count", 0) or 0)
    except (TypeError, ValueError):
        support_frame_count = 0
    if (
        confidence < TARGET_LOCK_DISTANT_SINGLE_JUMP_MIN_CONFIDENCE
        or support_count < TARGET_LOCK_DISTANT_SINGLE_JUMP_MIN_SUPPORT
        or support_frame_count < TARGET_LOCK_DISTANT_SINGLE_JUMP_MIN_UNIQUE_FRAMES
    ):
        return []

    competitors: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict) or item is candidate or _candidate_id(item) == _candidate_id(candidate):
            continue
        if str(item.get("source") or "") == "layout_fallback":
            continue
        if _candidate_matches_anchor(item, candidate):
            continue
        try:
            item_confidence = float(item.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            item_confidence = 0.0
        if item_confidence >= TARGET_LOCK_DISTANT_SINGLE_JUMP_MAX_COMPETITOR_CONFIDENCE:
            competitors.append(item)
    if competitors:
        return []
    return [
        "target_lock_distant_single_jump_auto_locked",
        "target_lock_tiny_zoomed_low_support_manual_review",
    ]


def _zoomed_multiperson_manual_review_flags(
    candidate: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
) -> list[str]:
    if str(candidate.get("source") or "") != "yolo_zoomed_content":
        return []

    by_anchor_frame: dict[str, list[dict[str, Any]]] = {}
    for item in candidates:
        if not isinstance(item, dict) or str(item.get("source") or "") != "yolo_zoomed_content":
            continue
        if _candidate_confidence(item) < TARGET_LOCK_ZOOMED_MULTIPERSON_MIN_CONFIDENCE:
            continue
        if not isinstance(item.get("bbox"), dict):
            continue
        anchor_frame = str(item.get("anchor_frame") or "")
        if not anchor_frame:
            continue
        by_anchor_frame.setdefault(anchor_frame, []).append(item)

    for frame_candidates in by_anchor_frame.values():
        for index, first in enumerate(frame_candidates):
            first_bbox = first.get("bbox")
            if not isinstance(first_bbox, dict):
                continue
            for second in frame_candidates[index + 1 :]:
                second_bbox = second.get("bbox")
                if not isinstance(second_bbox, dict):
                    continue
                if _bbox_center_distance(first_bbox, second_bbox) >= TARGET_LOCK_ZOOMED_MULTIPERSON_MIN_CENTER_DISTANCE:
                    return ["target_lock_zoomed_multiperson_manual_review"]
    return []


def _candidate_confidence(candidate: dict[str, Any]) -> float:
    try:
        return float(candidate.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _candidate_effective_lock_confidence(candidate: dict[str, Any], fallback: float = 0.0) -> float:
    values = [_candidate_confidence(candidate), fallback]
    try:
        values.append(float(candidate.get("support_confidence", 0.0) or 0.0))
    except (TypeError, ValueError):
        pass
    return max(values)


def _is_tiny_stable_candidate(candidate: dict[str, Any]) -> bool:
    bbox = candidate.get("bbox")
    if not isinstance(bbox, dict):
        return False
    try:
        support_count = int(candidate.get("support_count", 0) or 0)
    except (TypeError, ValueError):
        support_count = 0
    return (
        str(candidate.get("source") or "") == "yolo_zoomed_content"
        and support_count >= TARGET_LOCK_STABLE_ZOOMED_MIN_SUPPORT
        and _bbox_area(bbox) <= TARGET_LOCK_TINY_STABLE_MAX_AREA
    )


def _is_complete_body_candidate(candidate: dict[str, Any]) -> bool:
    bbox = candidate.get("bbox")
    if not isinstance(bbox, dict):
        return False
    area = _bbox_area(bbox)
    width = float(bbox.get("width", 0.0) or 0.0)
    height = float(bbox.get("height", 0.0) or 0.0)
    source = str(candidate.get("source") or "")
    return (
        source in {"yolo_preview", "detector", "yolo_preview_multi_anchor"}
        and _candidate_confidence(candidate) >= TARGET_LOCK_AUTO_THRESHOLD
        and TARGET_LOCK_COMPLETE_BODY_MIN_AREA <= area <= TARGET_LOCK_COMPLETE_BODY_MAX_AREA
        and width >= TARGET_LOCK_COMPLETE_BODY_MIN_WIDTH
        and height >= TARGET_LOCK_COMPLETE_BODY_MIN_HEIGHT
    )


def _prefer_complete_body_candidate(
    top_candidate: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    if not _is_tiny_stable_candidate(top_candidate):
        return top_candidate
    top_confidence = _candidate_confidence(top_candidate)
    complete_candidates = [
        item
        for item in candidates
        if isinstance(item, dict)
        and _is_complete_body_candidate(item)
        and _candidate_confidence(item) >= top_confidence + TARGET_LOCK_COMPLETE_BODY_CONFIDENCE_ADVANTAGE
    ]
    if not complete_candidates:
        return top_candidate
    chosen = max(complete_candidates, key=lambda item: (_candidate_confidence(item), _bbox_area(item["bbox"])))
    flags = chosen.get("quality_flags") if isinstance(chosen.get("quality_flags"), list) else []
    chosen["quality_flags"] = _merge_strings(flags, ["target_lock_complete_body_candidate_preferred_over_tiny_stable"])
    return chosen


def _normalized_detected_candidates(candidates: Sequence[dict[str, Any]] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(candidates or [], start=1):
        if not isinstance(raw, dict) or not isinstance(raw.get("bbox"), dict):
            continue
        try:
            confidence = float(raw.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        item = dict(raw)
        item["id"] = _candidate_id(item) or f"candidate_detected_{index}"
        item["confidence"] = round(confidence, 4)
        item["source"] = str(item.get("source") or "detector")
        normalized.append(item)
    normalized.sort(key=_candidate_sort_key, reverse=True)
    return normalized


def _merge_candidate_lists(*sources: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in sources:
        for item in source:
            candidate_id = _candidate_id(item)
            if not candidate_id or candidate_id in seen:
                continue
            merged.append(item)
            seen.add(candidate_id)
    return merged


def _bbox_center(bbox: dict[str, Any]) -> tuple[float, float]:
    return (
        float(bbox.get("x", 0.0) or 0.0) + float(bbox.get("width", 0.0) or 0.0) / 2.0,
        float(bbox.get("y", 0.0) or 0.0) + float(bbox.get("height", 0.0) or 0.0) / 2.0,
    )


def _bbox_area(bbox: dict[str, Any]) -> float:
    return max(0.0, float(bbox.get("width", 0.0) or 0.0)) * max(0.0, float(bbox.get("height", 0.0) or 0.0))


def _bbox_center_distance(a: dict[str, Any], b: dict[str, Any]) -> float:
    ax, ay = _bbox_center(a)
    bx, by = _bbox_center(b)
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def target_preview_anchor_frame_indices(
    frame_names: Sequence[str],
    motion_scores: dict[str, Any] | None = None,
) -> list[int]:
    frame_count = len(frame_names)
    if frame_count <= 0:
        return []
    indices: list[int] = []
    for fraction in TARGET_PREVIEW_ANCHOR_FRACTIONS:
        index = round((frame_count - 1) * fraction)
        if index not in indices:
            indices.append(index)

    if isinstance(motion_scores, dict):
        frame_name_to_index = {frame_name: index for index, frame_name in enumerate(frame_names)}
        selected = [item for item in motion_scores.get("selected", []) if isinstance(item, dict)]
        selected.sort(key=lambda item: float(item.get("motion_score") or 0.0), reverse=True)
        for item in selected[:3]:
            frame_id = item.get("frame_id")
            if not isinstance(frame_id, str) or not frame_id:
                continue
            frame_name = frame_id if frame_id.endswith(".jpg") else f"{frame_id}.jpg"
            index = frame_name_to_index.get(frame_name)
            if index is not None and index not in indices:
                indices.append(index)
    return indices


def _candidate_matches_anchor(candidate: dict[str, Any], anchor: dict[str, Any]) -> bool:
    candidate_bbox = candidate.get("bbox")
    anchor_bbox = anchor.get("bbox")
    if not isinstance(candidate_bbox, dict) or not isinstance(anchor_bbox, dict):
        return False
    candidate_area = _bbox_area(candidate_bbox)
    anchor_area = _bbox_area(anchor_bbox)
    if candidate_area <= 0.0 or anchor_area <= 0.0:
        return False
    area_ratio = candidate_area / anchor_area
    return (
        TARGET_PREVIEW_AREA_RATIO_RANGE[0] <= area_ratio <= TARGET_PREVIEW_AREA_RATIO_RANGE[1]
        and _bbox_center_distance(candidate_bbox, anchor_bbox) <= TARGET_PREVIEW_CENTER_DISTANCE
    )


def _support_metrics_for_anchor(
    anchor: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
) -> tuple[int, int, float | None]:
    support = [item for item in candidates if _candidate_matches_anchor(item, anchor)]
    per_frame_confidence: dict[str, float] = {}
    for item in support:
        frame = str(item.get("anchor_frame") or item.get("id") or "")
        if not frame:
            continue
        try:
            confidence = float(item.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        per_frame_confidence[frame] = max(per_frame_confidence.get(frame, 0.0), confidence)
    support_confidence = (
        round(sum(per_frame_confidence.values()) / len(per_frame_confidence), 4)
        if per_frame_confidence
        else None
    )
    return len(support), len(per_frame_confidence), support_confidence


def _enrich_stable_candidate_support(candidates: Sequence[dict[str, Any]]) -> None:
    for candidate in candidates:
        if not isinstance(candidate, dict) or str(candidate.get("source") or "") != "yolo_zoomed_content":
            continue
        if not isinstance(candidate.get("bbox"), dict):
            continue
        support_count, support_frame_count, support_confidence = _support_metrics_for_anchor(candidate, candidates)
        if support_count <= 0 or support_confidence is None:
            continue
        try:
            existing_support_count = int(candidate.get("support_count", 0) or 0)
        except (TypeError, ValueError):
            existing_support_count = 0
        try:
            existing_support_frame_count = int(candidate.get("support_frame_count", 0) or 0)
        except (TypeError, ValueError):
            existing_support_frame_count = 0
        try:
            existing_support_confidence = float(candidate.get("support_confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            existing_support_confidence = 0.0
        candidate["support_count"] = max(existing_support_count, support_count)
        candidate["support_frame_count"] = max(existing_support_frame_count, support_frame_count)
        candidate["support_confidence"] = max(existing_support_confidence, support_confidence)


def select_stable_target_candidate(anchor_candidates: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    visible = [
        item
        for item in anchor_candidates
        if isinstance(item, dict)
        and isinstance(item.get("bbox"), dict)
        and float(item.get("confidence", 0.0) or 0.0) >= TARGET_PERSON_MIN_CONFIDENCE
    ]
    if not visible:
        return None

    max_anchor_index = max(int(item.get("anchor_index", 0) or 0) for item in visible)
    middle_anchor_index = max_anchor_index / 2.0
    best: dict[str, Any] | None = None
    best_score = float("-inf")
    for candidate in visible:
        support = [other for other in visible if _candidate_matches_anchor(other, candidate)]
        support_count = len({str(item.get("anchor_frame") or "") for item in support})
        support_confidence = sum(float(item.get("confidence", 0.0) or 0.0) for item in support) / max(len(support), 1)
        area = _bbox_area(candidate["bbox"])
        source = str(candidate.get("source") or "")
        frame_index = int(candidate.get("anchor_index", 9999) or 9999)
        frame_position_penalty = abs(frame_index - middle_anchor_index) / max(max_anchor_index, 1) * 0.15
        zoom_bonus = 0.75 if source == "yolo_zoomed_content" else 0.0
        foreground_penalty = 2.25 if area >= 0.18 and source != "yolo_zoomed_content" else 0.0
        score = support_count + support_confidence + min(area, 0.12) + zoom_bonus - foreground_penalty - frame_position_penalty
        if score > best_score:
            best = candidate
            best_score = score
    if best is None:
        return None

    chosen = dict(best)
    support_count, support_frame_count, support_confidence = _support_metrics_for_anchor(best, visible)
    chosen["id"] = str(chosen.get("id") or "candidate_auto_stable")
    chosen["source"] = str(chosen.get("source") or "yolo_preview_multi_anchor")
    chosen["support_count"] = support_count
    chosen["support_frame_count"] = support_frame_count
    if support_confidence is not None:
        chosen["support_confidence"] = support_confidence
    return chosen


def build_target_preview(
    analysis_id: str,
    frame_names: Sequence[str],
    *,
    existing_target_lock: dict[str, Any] | None = None,
    motion_scores: dict[str, Any] | None = None,
    detected_candidates: Sequence[dict[str, Any]] | None = None,
    analysis_profile: str | None = None,
) -> TargetPreview:
    frame_list = list(frame_names)
    existing_status = (
        str(existing_target_lock.get("status") or "")
        if isinstance(existing_target_lock, dict)
        else ""
    )
    preserve_existing_lock = existing_status in {"locked", "manual", "auto_locked"}
    existing_candidates = (
        [item for item in existing_target_lock.get("candidates", []) if isinstance(item, dict)]
        if isinstance(existing_target_lock, dict) and existing_target_lock.get("candidates")
        else []
    )
    existing_candidate_seed = (
        not existing_status
        and any(str(item.get("source") or "") != "layout_fallback" for item in existing_candidates)
    )
    existing_preview_frame = (
        str(existing_target_lock.get("preview_frame"))
        if (preserve_existing_lock or existing_candidate_seed)
        and isinstance(existing_target_lock, dict)
        and existing_target_lock.get("preview_frame")
        else None
    )
    detected = _normalized_detected_candidates(detected_candidates)
    detected_preview_frame = next(
        (
            str(item.get("anchor_frame"))
            for item in detected
            if isinstance(item.get("anchor_frame"), str) and item.get("anchor_frame") in frame_list
        ),
        None,
    )
    preview_frame = (
        existing_preview_frame
        if existing_preview_frame in frame_list
        else detected_preview_frame or _motion_anchor_frame(frame_list, motion_scores)
    )
    preview_frame_index = frame_list.index(preview_frame) if preview_frame in frame_list else None
    candidates = _merge_candidate_lists(detected, _fallback_candidates(frame_names))

    if existing_candidates:
        candidates = (
            _merge_candidate_lists(existing_candidates, candidates)
            if preserve_existing_lock or (existing_candidate_seed and not detected)
            else _merge_candidate_lists(candidates, existing_candidates)
        )
    _enrich_stable_candidate_support(candidates)

    visible_candidates = [
        item
        for item in candidates
        if isinstance(item, dict) and float(item.get("confidence", 0.0) or 0.0) >= TARGET_PERSON_MIN_CONFIDENCE
    ]
    visible_candidates.sort(key=_candidate_rank_score, reverse=True)
    if not visible_candidates:
        auto_candidate_id = None
        lock_confidence = 0.0
        target_lock_status = "no_person_detected"
    else:
        top_candidate = _prefer_complete_body_candidate(visible_candidates[0], visible_candidates)
        auto_candidate_id = str(top_candidate.get("id") or "") or None
        lock_confidence = float(top_candidate.get("confidence", 0.0) or 0.0)
        stable_zoomed_auto_lock_flags = _stable_zoomed_candidate_auto_lock_flags(top_candidate)
        stable_zoomed_auto_lock = bool(stable_zoomed_auto_lock_flags)
        if stable_zoomed_auto_lock:
            flags = top_candidate.get("quality_flags") if isinstance(top_candidate.get("quality_flags"), list) else []
            top_candidate["quality_flags"] = _merge_strings(flags, stable_zoomed_auto_lock_flags)
            try:
                support_confidence = float(top_candidate.get("support_confidence", 0.0) or 0.0)
            except (TypeError, ValueError):
                support_confidence = 0.0
            if support_confidence > lock_confidence:
                lock_confidence = support_confidence
        tiny_zoomed_manual_review = _tiny_zoomed_candidate_requires_manual_review(top_candidate)
        distant_single_jump_flags = _distant_single_jump_auto_lock_flags(top_candidate, candidates, analysis_profile)
        distant_single_jump_auto_lock = bool(distant_single_jump_flags)
        if distant_single_jump_auto_lock:
            flags = top_candidate.get("quality_flags") if isinstance(top_candidate.get("quality_flags"), list) else []
            top_candidate["quality_flags"] = _merge_strings(flags, distant_single_jump_flags)
        zoomed_multiperson_flags = _zoomed_multiperson_manual_review_flags(top_candidate, candidates)
        zoomed_multiperson_manual_review = bool(zoomed_multiperson_flags)
        if zoomed_multiperson_manual_review:
            flags = top_candidate.get("quality_flags") if isinstance(top_candidate.get("quality_flags"), list) else []
            top_candidate["quality_flags"] = _merge_strings(flags, zoomed_multiperson_flags)
        if tiny_zoomed_manual_review:
            flags = top_candidate.get("quality_flags") if isinstance(top_candidate.get("quality_flags"), list) else []
            top_candidate["quality_flags"] = _merge_strings(flags, ["target_lock_tiny_zoomed_low_support_manual_review"])
        if (
            lock_confidence < TARGET_LOCK_AUTO_THRESHOLD
            or tiny_zoomed_manual_review
            or zoomed_multiperson_manual_review
        ) and not stable_zoomed_auto_lock and not distant_single_jump_auto_lock:
            flags = top_candidate.get("quality_flags") if isinstance(top_candidate.get("quality_flags"), list) else []
            top_candidate["quality_flags"] = _merge_strings(flags, ["target_lock_manual_review_low_confidence"])
        global_auto_lock = (
            lock_confidence >= TARGET_LOCK_AUTO_THRESHOLD
            and not tiny_zoomed_manual_review
            and not zoomed_multiperson_manual_review
        )
        target_lock_status = (
            "auto_locked"
            if (global_auto_lock or stable_zoomed_auto_lock or distant_single_jump_auto_lock)
            and not zoomed_multiperson_manual_review
            else "awaiting_manual"
        )
        candidates.sort(
            key=lambda item: (
                1 if _candidate_id(item) == auto_candidate_id else 0,
                _candidate_rank_score(item),
            ),
            reverse=True,
        )

    if preserve_existing_lock and isinstance(existing_target_lock, dict):
        auto_candidate_id = str(existing_target_lock.get("selected_candidate_id") or auto_candidate_id or "")
        lock_confidence = float(existing_target_lock.get("lock_confidence", lock_confidence) or lock_confidence)
        target_lock_status = str(existing_target_lock.get("status", target_lock_status))

    return TargetPreview(
        preview_frame=preview_frame,
        preview_frame_url=f"/api/frames/{analysis_id}/{preview_frame}" if preview_frame else None,
        preview_frame_index=preview_frame_index,
        auto_candidate_id=auto_candidate_id or None,
        lock_confidence=round(lock_confidence, 4),
        candidates=candidates,
        target_lock_status=target_lock_status,
    )


def _motion_anchor_frame(frame_list: Sequence[str], motion_scores: dict[str, Any] | None) -> str | None:
    if not frame_list:
        return None
    if not isinstance(motion_scores, dict):
        return frame_list[0]

    available = set(frame_list)
    selected = motion_scores.get("selected")
    if not isinstance(selected, list):
        return frame_list[0]

    best_frame: str | None = None
    best_score = float("-inf")
    best_timestamp = float("inf")
    for item in selected:
        if not isinstance(item, dict):
            continue
        frame_id = item.get("frame_id")
        if not isinstance(frame_id, str) or not frame_id:
            continue
        frame_name = frame_id if frame_id.endswith(".jpg") else f"{frame_id}.jpg"
        if frame_name not in available:
            continue
        try:
            score = float(item.get("motion_score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        try:
            timestamp = float(item.get("timestamp") or 0.0)
        except (TypeError, ValueError):
            timestamp = 0.0
        if score > best_score or (score == best_score and timestamp < best_timestamp):
            best_frame = frame_name
            best_score = score
            best_timestamp = timestamp

    return best_frame or frame_list[0]


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
            "preview_frame_index": preview.preview_frame_index,
            "candidates": preview.candidates,
            "selected_candidate_id": None,
            "selected_bbox": selected_bbox,
            "lock_confidence": 1.0,
            "status": "manual",
            "manual_override": True,
            "quality_flags": [],
        }

    chosen = selected_candidate
    if chosen is None and preview.auto_candidate_id and preview.target_lock_status == "auto_locked":
        chosen = next((item for item in preview.candidates if str(item.get("id")) == preview.auto_candidate_id), None)
    diagnostic_candidate = chosen
    if diagnostic_candidate is None and preview.auto_candidate_id:
        diagnostic_candidate = next((item for item in preview.candidates if str(item.get("id")) == preview.auto_candidate_id), None)
    quality_flags = (
        diagnostic_candidate.get("quality_flags")
        if isinstance(diagnostic_candidate, dict) and isinstance(diagnostic_candidate.get("quality_flags"), list)
        else []
    )

    return {
        "preview_frame": preview.preview_frame,
        "preview_frame_index": preview.preview_frame_index,
        "candidates": preview.candidates,
        "selected_candidate_id": chosen.get("id") if isinstance(chosen, dict) else preview.auto_candidate_id,
        "selected_bbox": chosen.get("bbox") if isinstance(chosen, dict) else None,
        "lock_confidence": _candidate_effective_lock_confidence(chosen, preview.lock_confidence) if isinstance(chosen, dict) else preview.lock_confidence,
        "status": "locked" if manual else preview.target_lock_status,
        "manual_override": manual,
        "quality_flags": list(quality_flags),
    }


def extract_pose_target_bbox(target_lock: dict[str, Any] | None) -> dict[str, float] | None:
    if not isinstance(target_lock, dict):
        return None
    bbox = target_lock.get("selected_bbox")
    return bbox if isinstance(bbox, dict) else None


def frame_names_from_dir(frames_dir: str | Path) -> list[str]:
    frame_paths = sorted(Path(frames_dir).glob("frame_*.jpg"))
    return [frame_path.name for frame_path in frame_paths]
