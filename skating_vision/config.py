from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class ProviderConfig:
    name: str
    provider: str
    base_url: str
    model_id: str
    api_key: str
    vision_model: str | None = None
    notes: str | None = None


@dataclass(slots=True)
class VisionConfig:
    vision_provider: ProviderConfig
    report_provider: ProviderConfig
    uploads_dir: Path = field(default_factory=lambda: Path("/tmp/skating-analyzer/uploads"))
    processing_root: Path = field(default_factory=lambda: Path("/tmp/skating-analyzer"))
    project_root: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent)
    frame_sample_count: int = field(default_factory=lambda: int(os.getenv("FRAME_SAMPLE_COUNT", "20")))
    frame_thumb_size: str = field(default_factory=lambda: os.getenv("FRAME_THUMB_SIZE", "160x90"))
    frame_full_size: str = field(default_factory=lambda: os.getenv("FRAME_FULL_SIZE", "854x480"))
    max_upload_size_mb: int = field(default_factory=lambda: int(os.getenv("MAX_UPLOAD_SIZE_MB", "500")))
    pose_num_poses: int = field(default_factory=lambda: int(os.getenv("POSE_NUM_POSES", "4")))
    mediapipe_pose_task_path: str = field(default_factory=lambda: os.getenv("MEDIAPIPE_POSE_TASK_PATH", "").strip())
