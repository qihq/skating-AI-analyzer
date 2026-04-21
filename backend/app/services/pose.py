from __future__ import annotations

from pathlib import Path
from typing import Any


LANDMARK_NAMES = [
    "nose",
    "left_eye_inner",
    "left_eye",
    "left_eye_outer",
    "right_eye_inner",
    "right_eye",
    "right_eye_outer",
    "left_ear",
    "right_ear",
    "mouth_left",
    "mouth_right",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_pinky",
    "right_pinky",
    "left_index",
    "right_index",
    "left_thumb",
    "right_thumb",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
    "left_heel",
    "right_heel",
    "left_foot_index",
    "right_foot_index",
]

POSE_CONNECTIONS = [
    [11, 12],
    [11, 13],
    [13, 15],
    [12, 14],
    [14, 16],
    [11, 23],
    [12, 24],
    [23, 24],
    [23, 25],
    [25, 27],
    [27, 29],
    [29, 31],
    [24, 26],
    [26, 28],
    [28, 30],
    [30, 32],
    [0, 11],
    [0, 12],
]


def _empty_payload() -> dict[str, Any]:
    return {"connections": POSE_CONNECTIONS, "frames": []}


def extract_pose(frames_dir: str) -> dict[str, Any]:
    frame_paths = sorted(Path(frames_dir).glob("frame_*.jpg"))
    if not frame_paths:
        return _empty_payload()

    try:
        import cv2  # type: ignore
        import mediapipe as mp  # type: ignore
    except Exception:
        return _empty_payload()

    frames: list[dict[str, Any]] = []
    pose = mp.solutions.pose.Pose(
        static_image_mode=True,
        model_complexity=1,
        enable_segmentation=False,
        min_detection_confidence=0.5,
    )

    try:
        for frame_path in frame_paths:
            image = cv2.imread(str(frame_path))
            if image is None:
                frames.append({"frame": frame_path.name, "keypoints": []})
                continue

            image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            result = pose.process(image_rgb)
            keypoints: list[dict[str, Any]] = []
            if result.pose_landmarks:
                for index, landmark in enumerate(result.pose_landmarks.landmark):
                    visibility = float(getattr(landmark, "visibility", 0.0))
                    keypoints.append(
                        {
                            "id": index,
                            "name": LANDMARK_NAMES[index] if index < len(LANDMARK_NAMES) else f"landmark_{index}",
                            "x": float(landmark.x),
                            "y": float(landmark.y),
                            "z": float(landmark.z),
                            "visibility": visibility if visibility >= 0.5 else 0.0,
                        }
                    )

            frames.append({"frame": frame_path.name, "keypoints": keypoints})
    finally:
        pose.close()

    return {"connections": POSE_CONNECTIONS, "frames": frames}
