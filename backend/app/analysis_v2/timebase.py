from __future__ import annotations

import hashlib
import json
import math
from statistics import median
from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator


TimestampStatus = Literal["exact", "approximate_legacy", "unavailable"]
FrameStatus = Literal["available", "duplicate_pts", "gap_after_previous", "discontinuity", "timestamp_unavailable"]


class TimebaseError(ValueError):
    """Raised when source timing or coordinate evidence is unsafe to use."""


class Timebase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    numerator: int = Field(gt=0)
    denominator: int = Field(gt=0)
    average_fps: float | None = Field(default=None, gt=0)
    nominal_fps: float | None = Field(default=None, gt=0)
    is_vfr: bool = False


class DecodeGap(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    previous_frame_index: int = Field(ge=0)
    next_frame_index: int = Field(ge=0)
    previous_pts_sec: float = Field(ge=0)
    next_pts_sec: float = Field(ge=0)
    missing_duration_sec: float = Field(gt=0)
    reason: Literal["dropped_frames", "timestamp_discontinuity"]


class SourceFrameReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_frame_index: int = Field(ge=0)
    pts_sec: float | None = Field(default=None, ge=0)
    duration_sec: float | None = Field(default=None, gt=0)
    image_size: tuple[int, int] | None = None
    status: FrameStatus = "available"
    gap_before_sec: float = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_reference(self) -> "SourceFrameReference":
        if self.image_size is not None and (self.image_size[0] <= 0 or self.image_size[1] <= 0):
            raise ValueError("source frame image_size must be positive")
        if self.pts_sec is None and self.status != "timestamp_unavailable":
            raise ValueError("frames without PTS must be marked timestamp_unavailable")
        return self


class SourceFrameIndex(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["source-frame-index.v1"] = "source-frame-index.v1"
    source_video_hash: str = Field(min_length=1)
    duration_sec: float | None = Field(default=None, gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    rotation_degrees: Literal[0, 90, 180, 270] = 0
    timebase: Timebase
    timestamp_status: TimestampStatus = "exact"
    frames: tuple[SourceFrameReference, ...] = ()
    decode_gaps: tuple[DecodeGap, ...] = ()
    pts_discontinuities: tuple[int, ...] = ()

    @model_validator(mode="after")
    def validate_order(self) -> "SourceFrameIndex":
        indexes = [frame.source_frame_index for frame in self.frames]
        if indexes != list(range(len(indexes))):
            raise ValueError("source frame indexes must preserve decode order")
        return self

    @property
    def exact(self) -> bool:
        return self.timestamp_status == "exact" and bool(self.frames) and all(frame.pts_sec is not None for frame in self.frames)

    def frame_at_index(self, source_frame_index: int) -> SourceFrameReference:
        if source_frame_index < 0 or source_frame_index >= len(self.frames):
            raise TimebaseError("requested source frame is unavailable")
        return self.frames[source_frame_index]

    def frame_at_pts(self, pts_sec: float) -> SourceFrameReference:
        if not math.isfinite(pts_sec) or pts_sec < 0:
            raise TimebaseError("PTS must be a finite non-negative number")
        candidates = [frame for frame in self.frames if frame.pts_sec is not None]
        if not candidates:
            raise TimebaseError("source timestamps are unavailable")
        return min(candidates, key=lambda frame: (abs(frame.pts_sec - pts_sec), frame.source_frame_index))

    def fingerprint(self) -> str:
        payload = self.model_dump(mode="json")
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    def to_timeline(self) -> dict[str, Any]:
        return {
            "schema_version": "source-timeline.v1",
            "source_video_hash": self.source_video_hash,
            "duration_sec": self.duration_sec,
            "width": self.width,
            "height": self.height,
            "rotation_degrees": self.rotation_degrees,
            "timebase": self.timebase.model_dump(mode="json"),
            "timestamp_status": self.timestamp_status,
            "frames": [frame.model_dump(mode="json") for frame in self.frames],
            "decode_gaps": [gap.model_dump(mode="json") for gap in self.decode_gaps],
            "pts_discontinuities": list(self.pts_discontinuities),
            "fingerprint": self.fingerprint(),
        }


class TrackingProxy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    width: int = Field(gt=0)
    height: int = Field(gt=0)
    source_frame_index: int = Field(ge=0)
    pts_sec: float | None = Field(default=None, ge=0)
    timestamp_status: TimestampStatus = "exact"


class SourcePoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    x: float
    y: float


class SourceBox(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    left: float
    top: float
    right: float
    bottom: float

    @model_validator(mode="after")
    def positive_area(self) -> "SourceBox":
        if self.right <= self.left or self.bottom <= self.top:
            raise ValueError("box must have positive area")
        return self


class MediaGeometry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_width: int = Field(gt=0)
    source_height: int = Field(gt=0)
    display_rotation_degrees: Literal[0, 90, 180, 270] = 0

    @property
    def display_width(self) -> int:
        return self.source_height if self.display_rotation_degrees in {90, 270} else self.source_width

    @property
    def display_height(self) -> int:
        return self.source_width if self.display_rotation_degrees in {90, 270} else self.source_height


def _normalized(point: SourcePoint, width: int, height: int) -> SourcePoint:
    return SourcePoint(x=point.x / width, y=point.y / height)


def _pixel(point: SourcePoint, width: int, height: int) -> SourcePoint:
    return SourcePoint(x=point.x * width, y=point.y * height)


def source_to_display(point: SourcePoint, geometry: MediaGeometry) -> SourcePoint:
    normalized = _normalized(point, geometry.source_width, geometry.source_height)
    rotation = geometry.display_rotation_degrees
    if rotation == 0:
        rotated = normalized
    elif rotation == 90:
        rotated = SourcePoint(x=1 - normalized.y, y=normalized.x)
    elif rotation == 180:
        rotated = SourcePoint(x=1 - normalized.x, y=1 - normalized.y)
    else:
        rotated = SourcePoint(x=normalized.y, y=1 - normalized.x)
    return _pixel(rotated, geometry.display_width, geometry.display_height)


def display_to_source(point: SourcePoint, geometry: MediaGeometry) -> SourcePoint:
    normalized = _normalized(point, geometry.display_width, geometry.display_height)
    rotation = geometry.display_rotation_degrees
    if rotation == 0:
        source = normalized
    elif rotation == 90:
        source = SourcePoint(x=normalized.y, y=1 - normalized.x)
    elif rotation == 180:
        source = SourcePoint(x=1 - normalized.x, y=1 - normalized.y)
    else:
        source = SourcePoint(x=1 - normalized.y, y=normalized.x)
    return _pixel(source, geometry.source_width, geometry.source_height)


def source_to_tracking_proxy(point: SourcePoint, geometry: MediaGeometry, proxy_width: int, proxy_height: int) -> SourcePoint:
    normalized = _normalized(point, geometry.source_width, geometry.source_height)
    return _pixel(normalized, proxy_width, proxy_height)


def tracking_proxy_to_source(point: SourcePoint, geometry: MediaGeometry, proxy_width: int, proxy_height: int) -> SourcePoint:
    normalized = _normalized(point, proxy_width, proxy_height)
    return _pixel(normalized, geometry.source_width, geometry.source_height)


def source_to_target_crop(point: SourcePoint, crop: SourceBox) -> SourcePoint:
    if not crop.left <= point.x <= crop.right or not crop.top <= point.y <= crop.bottom:
        raise TimebaseError("source point is outside target crop")
    return SourcePoint(x=(point.x - crop.left) / (crop.right - crop.left), y=(point.y - crop.top) / (crop.bottom - crop.top))


def target_crop_to_source(point: SourcePoint, crop: SourceBox) -> SourcePoint:
    if not 0 <= point.x <= 1 or not 0 <= point.y <= 1:
        raise TimebaseError("target crop point must be normalized")
    return SourcePoint(x=crop.left + point.x * (crop.right - crop.left), y=crop.top + point.y * (crop.bottom - crop.top))


def source_box_to_display(box: SourceBox, geometry: MediaGeometry) -> SourceBox:
    points = [
        source_to_display(SourcePoint(x=box.left * geometry.source_width, y=box.top * geometry.source_height), geometry),
        source_to_display(SourcePoint(x=box.right * geometry.source_width, y=box.top * geometry.source_height), geometry),
        source_to_display(SourcePoint(x=box.left * geometry.source_width, y=box.bottom * geometry.source_height), geometry),
        source_to_display(SourcePoint(x=box.right * geometry.source_width, y=box.bottom * geometry.source_height), geometry),
    ]
    return SourceBox(
        left=min(point.x for point in points) / geometry.display_width,
        top=min(point.y for point in points) / geometry.display_height,
        right=max(point.x for point in points) / geometry.display_width,
        bottom=max(point.y for point in points) / geometry.display_height,
    )


def build_source_frame_index(
    records: Sequence[Mapping[str, Any]],
    *,
    source_video_hash: str,
    width: int,
    height: int,
    duration_sec: float | None,
    timebase: Timebase,
    rotation_degrees: int = 0,
    timestamp_status: TimestampStatus = "exact",
) -> SourceFrameIndex:
    if rotation_degrees not in {0, 90, 180, 270}:
        raise TimebaseError("rotation must be one of 0, 90, 180, 270 degrees")
    raw_pts = [_number(record.get("pts_sec", record.get("pts_time", record.get("pts")))) for record in records]
    positive_deltas = [right - left for left, right in zip(raw_pts, raw_pts[1:]) if left is not None and right is not None and right > left]
    nominal_interval = (1 / timebase.nominal_fps) if timebase.nominal_fps else (median(positive_deltas) if positive_deltas else None)
    frames: list[SourceFrameReference] = []
    gaps: list[DecodeGap] = []
    discontinuities: list[int] = []
    for index, record in enumerate(records):
        pts = raw_pts[index]
        duration = _number(record.get("duration_sec", record.get("duration_time", record.get("duration"))))
        status: FrameStatus = "available"
        gap_before = 0.0
        if pts is None:
            status = "timestamp_unavailable"
        elif index:
            previous = raw_pts[index - 1]
            if previous is not None:
                delta = pts - previous
                if abs(delta) <= 1e-9:
                    status = "duplicate_pts"
                elif delta < 0:
                    status = "discontinuity"
                    discontinuities.append(index)
                    gaps.append(DecodeGap(previous_frame_index=index - 1, next_frame_index=index, previous_pts_sec=previous, next_pts_sec=pts, missing_duration_sec=0.0 + abs(delta), reason="timestamp_discontinuity"))
                elif nominal_interval and delta > max(nominal_interval * 1.5, nominal_interval + 0.001):
                    status = "gap_after_previous"
                    gap_before = max(0.0, delta - nominal_interval)
                    gaps.append(DecodeGap(previous_frame_index=index - 1, next_frame_index=index, previous_pts_sec=previous, next_pts_sec=pts, missing_duration_sec=gap_before, reason="dropped_frames"))
        image_size = (int(record.get("width", width)), int(record.get("height", height)))
        frames.append(SourceFrameReference(source_frame_index=index, pts_sec=pts, duration_sec=duration, image_size=image_size, status=status, gap_before_sec=gap_before))
    effective_timestamp_status: TimestampStatus = timestamp_status
    if timestamp_status == "exact" and any(frame.pts_sec is None for frame in frames):
        effective_timestamp_status = "unavailable"
    return SourceFrameIndex(source_video_hash=source_video_hash, duration_sec=duration_sec, width=width, height=height, rotation_degrees=rotation_degrees, timebase=timebase, timestamp_status=effective_timestamp_status, frames=tuple(frames), decode_gaps=tuple(gaps), pts_discontinuities=tuple(discontinuities))


def _number(value: object) -> float | None:
    try:
        number = float(str(value))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None
