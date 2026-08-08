from __future__ import annotations

import base64
from pathlib import Path

import cv2
import numpy as np

from app.services.video import FramePayload
from app.services.vision_dual import (
    TARGET_CLIP_ARTIFACT_KIND,
    TARGET_CLIP_ARTIFACT_UNVERIFIED,
    _identity_conflicts_from_target_lock,
    _target_marked_frame_payloads,
)


def _frame(path: Path, *, width: int = 100, height: int = 80) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, :] = (20, 30, 40)
    assert cv2.imwrite(str(path), image)
    return path


def test_target_marked_payload_is_cropped_and_fingerprinted(tmp_path: Path) -> None:
    frame_path = _frame(tmp_path / "frame_0001.jpg")
    payload = FramePayload(
        frame_id="frame_0001",
        data_url="data:image/jpeg;base64," + base64.b64encode(frame_path.read_bytes()).decode(),
        timestamp_sec=1.25,
    )
    marked, artifact = _target_marked_frame_payloads(
        [frame_path],
        [payload],
        target_lock={
            "selected_bbox": {"x": 0.40, "y": 0.25, "width": 0.20, "height": 0.40},
            "bbox_per_frame": [{"x": 0.42, "y": 0.25, "width": 0.18, "height": 0.38}],
        },
        output_dir=tmp_path / "target_clip",
    )
    assert artifact["artifact_kind"] == TARGET_CLIP_ARTIFACT_KIND
    assert artifact["frame_count"] == 1
    assert artifact["fingerprint"].startswith("sha256:")
    assert marked[0].frame_id == "frame_0001"
    encoded = base64.b64decode(marked[0].data_url.split(",", 1)[1])
    decoded = cv2.imdecode(np.frombuffer(encoded, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded is not None
    # 75% context padding still remains bounded by the source frame.
    assert decoded.shape[1] <= 100
    assert decoded.shape[0] <= 80


def test_target_marked_payload_fails_closed_when_bbox_is_missing(tmp_path: Path) -> None:
    frame_path = _frame(tmp_path / "frame_0001.jpg")
    payload = FramePayload(frame_id="frame_0001", data_url="data:image/jpeg;base64,AA==", timestamp_sec=0.0)
    marked, artifact = _target_marked_frame_payloads(
        [frame_path],
        [payload],
        target_lock={"status": "awaiting_manual"},
        output_dir=tmp_path / "target_clip",
    )
    assert marked == []
    assert artifact["artifact_kind"] == TARGET_CLIP_ARTIFACT_UNVERIFIED


def test_tracker_identity_diagnostics_become_merged_conflict_intervals() -> None:
    payloads = [
        FramePayload(frame_id="frame_0001", data_url="data:image/jpeg;base64,AA==", timestamp_sec=0.0),
        FramePayload(frame_id="frame_0002", data_url="data:image/jpeg;base64,AA==", timestamp_sec=0.1),
        FramePayload(frame_id="frame_0003", data_url="data:image/jpeg;base64,AA==", timestamp_sec=0.2),
    ]
    intervals = _identity_conflicts_from_target_lock(
        {
            "quality_flags": [],
            "person_tracker_diagnostics": [
                {"frame": "frame_0002.jpg", "frame_index": 1, "state": "relock_pending"},
                {"frame": "frame_0003.jpg", "frame_index": 2, "state": "relock_rejected", "rejected_reasons": ["false_relock"]},
            ],
        },
        frame_payloads=payloads,
    )
    assert len(intervals) == 1
    assert intervals[0]["start_pts_sec"] == 0.1
    assert intervals[0]["end_pts_sec"] == 0.2
    assert intervals[0]["frame_indices"] == (1, 2)
