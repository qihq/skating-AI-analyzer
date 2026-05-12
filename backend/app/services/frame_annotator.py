from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

import cv2

from app.services.pose import POSE_CONNECTIONS


logger = logging.getLogger(__name__)

VISIBILITY_THRESHOLD = 0.2
POINT_COLOR = (80, 220, 255)
LINE_COLOR = (40, 180, 90)
TEXT_COLOR = (255, 255, 255)
TEXT_BG_COLOR = (20, 20, 20)


def build_pose_by_stem(pose_data: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Build frame stem -> pose frame mapping, stripping suffixes such as .jpg."""
    if not isinstance(pose_data, dict):
        return {}

    out: dict[str, dict[str, Any]] = {}
    frames = pose_data.get("frames")
    if not isinstance(frames, list):
        return out

    for frame in frames:
        if not isinstance(frame, dict):
            continue
        frame_name = frame.get("frame")
        if not isinstance(frame_name, str) or not frame_name:
            continue
        out[Path(frame_name).stem] = frame
    return out


def _copy_frame(src: Path, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() != dst.resolve():
        shutil.copy2(src, dst)
    return dst


def _point(
    keypoints: list[dict[str, Any]],
    index: int,
    width: int,
    height: int,
) -> tuple[int, int] | None:
    if index >= len(keypoints):
        return None
    raw = keypoints[index]
    if not isinstance(raw, dict):
        return None
    try:
        visibility = float(raw.get("visibility", 1.0))
        x = float(raw.get("x"))
        y = float(raw.get("y"))
    except (TypeError, ValueError):
        return None
    if visibility < VISIBILITY_THRESHOLD:
        return None
    return int(round(x * width)), int(round(y * height))


def _draw_label(image: Any, text: str, origin: tuple[int, int]) -> None:
    x, y = origin
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.45
    thickness = 1
    (tw, th), baseline = cv2.getTextSize(text, font, scale, thickness)
    cv2.rectangle(
        image,
        (x - 3, y - th - baseline - 3),
        (x + tw + 3, y + baseline + 3),
        TEXT_BG_COLOR,
        -1,
    )
    cv2.putText(image, text, (x, y), font, scale, TEXT_COLOR, thickness, cv2.LINE_AA)


def _draw_pose(
    image: Any,
    keypoints: list[dict[str, Any]],
    connections: list[list[int]] | None = None,
) -> None:
    height, width = image.shape[:2]
    points = {
        index: _point(keypoints, index, width, height)
        for index in range(len(keypoints))
    }

    for pair in connections or POSE_CONNECTIONS:
        if not isinstance(pair, list) or len(pair) != 2:
            continue
        start = points.get(int(pair[0]))
        end = points.get(int(pair[1]))
        if start and end:
            cv2.line(image, start, end, LINE_COLOR, 2, cv2.LINE_AA)

    for point in points.values():
        if point:
            cv2.circle(image, point, 3, POINT_COLOR, -1, cv2.LINE_AA)

    for label, index in [("LKnee", 25), ("RKnee", 26), ("LElbow", 13), ("RElbow", 14)]:
        point = points.get(index)
        if point:
            _draw_label(image, label, (point[0] + 5, point[1] - 5))


def annotate_frame(
    frame_path: Path,
    pose_frame: dict[str, Any] | None,
    output_path: Path,
    *,
    connections: list[list[int]] | None = None,
) -> Path:
    """
    Write an annotated copy of a frame.

    Missing pose data or lost frames (keypoints=[]) are copied unchanged.
    """
    keypoints = pose_frame.get("keypoints") if isinstance(pose_frame, dict) else None
    if not isinstance(keypoints, list) or not keypoints:
        return _copy_frame(frame_path, output_path)

    image = cv2.imread(str(frame_path))
    if image is None:
        logger.warning("Failed to read frame for annotation: %s", frame_path)
        return _copy_frame(frame_path, output_path)

    _draw_pose(image, keypoints, connections)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), image):
        logger.warning("Failed to write annotated frame: %s", output_path)
        return _copy_frame(frame_path, output_path)
    return output_path


def annotate_frames_batch(
    frame_paths: list[Path],
    pose_by_stem: dict[str, dict[str, Any]],
    output_dir: Path,
    *,
    connections: list[list[int]] | None = None,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    return [
        annotate_frame(
            frame_path,
            pose_by_stem.get(frame_path.stem),
            output_dir / frame_path.name,
            connections=connections,
        )
        for frame_path in frame_paths
    ]
