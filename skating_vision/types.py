from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class FramePayload:
    frame_id: str
    data_url: str


@dataclass(slots=True)
class VideoSamplingMetadata:
    action_window_start: float
    action_window_end: float
    source_fps: float
    is_slow_motion: bool
