"""逐帧目标 bbox 跟踪。

职责: 使用 OpenCV CSRT 在抽样帧序列中跟踪主目标 bbox。
输入: frame_paths、初始 bbox。
输出: 每帧 bbox 与质量标记列表。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


def _normalize_bbox(bbox: dict[str, Any]) -> dict[str, float]:
    width = float(bbox.get("width", bbox.get("w", 0.0)))
    height = float(bbox.get("height", bbox.get("h", 0.0)))
    x = _clamp(float(bbox.get("x", 0.0)), 0.0, 1.0)
    y = _clamp(float(bbox.get("y", 0.0)), 0.0, 1.0)
    width = _clamp(width, 0.05, 1.0 - x)
    height = _clamp(height, 0.05, 1.0 - y)
    return {"x": round(x, 4), "y": round(y, 4), "width": round(width, 4), "height": round(height, 4)}


def _to_pixel_bbox(bbox: dict[str, float], image_width: int, image_height: int) -> tuple[int, int, int, int]:
    x = int(_clamp(bbox["x"], 0.0, 1.0) * image_width)
    y = int(_clamp(bbox["y"], 0.0, 1.0) * image_height)
    width = int(_clamp(bbox["width"], 0.05, 1.0) * image_width)
    height = int(_clamp(bbox["height"], 0.05, 1.0) * image_height)
    return x, y, max(width, 1), max(height, 1)


def _from_pixel_bbox(pixel_bbox: tuple[float, float, float, float], image_width: int, image_height: int) -> dict[str, float]:
    x, y, width, height = pixel_bbox
    return _normalize_bbox(
        {
            "x": x / max(image_width, 1),
            "y": y / max(image_height, 1),
            "width": width / max(image_width, 1),
            "height": height / max(image_height, 1),
        }
    )


def _create_tracker() -> Any:
    import cv2  # type: ignore

    if hasattr(cv2, "TrackerCSRT_create"):
        return cv2.TrackerCSRT_create()
    legacy = getattr(cv2, "legacy", None)
    if legacy is not None and hasattr(legacy, "TrackerCSRT_create"):
        return legacy.TrackerCSRT_create()
    raise RuntimeError("OpenCV CSRT tracker is not available.")


def track_bbox(frame_paths: list[Path], initial_bbox: dict[str, Any]) -> tuple[list[dict[str, float]], list[str]]:
    """使用 OpenCV CSRT 在抽样帧序列中跟踪主目标 bbox。

    Args:
        frame_paths: 按时间排序的抽样帧路径。
        initial_bbox: 第一帧上的归一化 bbox。

    Returns:
        每帧 bbox 与质量标记列表。跟踪失败时使用上一帧速度线性外推。

    Raises:
        RuntimeError: OpenCV 或首帧不可用时抛出，调用方应降级到静态 bbox。
    """
    if not frame_paths:
        return [], []

    import cv2  # type: ignore

    first = cv2.imread(str(frame_paths[0]))
    if first is None:
        raise RuntimeError(f"Could not read first frame for bbox tracking: {frame_paths[0]}")

    image_height, image_width = first.shape[:2]
    normalized_initial = _normalize_bbox(initial_bbox)
    tracker = _create_tracker()
    tracker.init(first, _to_pixel_bbox(normalized_initial, image_width, image_height))

    tracked = [normalized_initial]
    quality_flags: list[str] = []
    previous = normalized_initial
    velocity = (0.0, 0.0)

    for frame_path in frame_paths[1:]:
        image = cv2.imread(str(frame_path))
        if image is None:
            quality_flags.append("bbox_tracker_frame_read_failed")
            next_bbox = _normalize_bbox({**previous, "x": previous["x"] + velocity[0], "y": previous["y"] + velocity[1]})
            tracked.append(next_bbox)
            previous = next_bbox
            continue

        image_height, image_width = image.shape[:2]
        ok, pixel_bbox = tracker.update(image)
        if ok:
            next_bbox = _from_pixel_bbox(pixel_bbox, image_width, image_height)
            velocity = (next_bbox["x"] - previous["x"], next_bbox["y"] - previous["y"])
            previous = next_bbox
            tracked.append(next_bbox)
            continue

        quality_flags.append("bbox_tracker_extrapolated")
        logger.warning("bbox tracker lost target at %s; using linear extrapolation", frame_path.name)
        next_bbox = _normalize_bbox({**previous, "x": previous["x"] + velocity[0], "y": previous["y"] + velocity[1]})
        tracked.append(next_bbox)
        previous = next_bbox

    return tracked, sorted(set(quality_flags))
