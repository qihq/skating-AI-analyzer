from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.analysis_errors import AnalysisErrorCode, AnalysisPipelineError
from app.services.video import FramePayload
from app.services.vision_dual import analyze_frames_dual, dual_path_summary


def _payloads(count: int) -> list[FramePayload]:
    return [
        FramePayload(
            frame_id=f"frame_{index + 1:04d}",
            data_url=f"data:image/jpeg;base64,{index}",
            timestamp_sec=index * 0.1,
        )
        for index in range(count)
    ]


def _path_a_result() -> dict:
    return {
        "path": "A",
        "frame_analysis": [{"frame_id": "frame_0001", "phase": "takeoff"}],
        "action_phase_summary": {"detected_phases": ["takeoff"]},
        "pure_vision_subscores": {
            "takeoff_power": 80,
            "rotation_axis": 80,
            "arm_coordination": 80,
            "landing_absorption": 80,
            "core_stability": 80,
        },
    }


def _path_b_result() -> dict:
    return {
        "path": "B",
        "n_frames": 1,
        "frame_analysis": [{"frame_id": "frame_0001", "phase": "takeoff"}],
        "action_phase_summary": {"detected_phases": ["takeoff"]},
        "subscores": {
            "takeoff_power": 80,
            "rotation_axis": 80,
            "arm_coordination": 80,
            "landing_absorption": 80,
            "core_stability": 80,
        },
    }


def _write_frames(root: Path, count: int = 1) -> list[Path]:
    frames_dir = root / "frames"
    frames_dir.mkdir()
    paths: list[Path] = []
    for index in range(count):
        path = frames_dir / f"frame_{index + 1:04d}.jpg"
        image = np.full((32, 32, 3), 255, dtype=np.uint8)
        cv2.putText(image, str(index), (5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        assert cv2.imwrite(str(path), image)
        paths.append(path)
    return paths


class VisionDualTests(unittest.IsolatedAsyncioTestCase):
    async def test_happy_path_and_summary_are_json_serializable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            frame_paths = _write_frames(Path(tmp), 1)
            provider = SimpleNamespace(api_key="key", base_url="https://example.com/v1", model_id="model")

            with (
                patch("app.services.vision_dual.analyze_path_a", new=AsyncMock(return_value=_path_a_result())),
                patch("app.services.vision_dual.analyze_path_b", new=AsyncMock(return_value=_path_b_result())),
            ):
                result = await analyze_frames_dual(
                    "jump",
                    frame_paths,
                    _payloads(1),
                    pose_data=None,
                    bio_data=None,
                    provider_path_a=provider,
                    provider_path_b=provider,
                    annotated_dir=Path(tmp) / "annotated",
                    timestamps={"frame_0001": 1.25},
                )

        self.assertEqual(result.path_a["path"], "A")
        self.assertEqual(result.path_b["path"], "B")
        self.assertIn(result.validation.recommended_path, {"blend", "A", "B"})
        self.assertEqual(result.used_key_frames, set())
        self.assertEqual(result.dual_path_meta["path_b_failed"], False)
        json.dumps(result.dual_path_meta, ensure_ascii=False)
        json.dumps(dual_path_summary(result), ensure_ascii=False)

    async def test_path_b_error_is_soft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            frame_paths = _write_frames(Path(tmp), 1)
            provider = SimpleNamespace(api_key="key", base_url="https://example.com/v1", model_id="model")

            with (
                patch("app.services.vision_dual.analyze_path_a", new=AsyncMock(return_value=_path_a_result())),
                patch(
                    "app.services.vision_dual.analyze_path_b",
                    new=AsyncMock(return_value={"path": "B", "error": "bad provider"}),
                ),
            ):
                result = await analyze_frames_dual(
                    "jump",
                    frame_paths,
                    _payloads(1),
                    None,
                    None,
                    provider,
                    provider,
                    annotated_dir=Path(tmp) / "annotated",
                )

        self.assertEqual(result.path_b["error"], "bad provider")
        self.assertEqual(result.validation.recommended_path, "A")
        self.assertEqual(result.dual_path_meta["path_b_failed"], True)

    async def test_path_a_error_is_hard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            frame_paths = _write_frames(Path(tmp), 1)
            provider = SimpleNamespace(api_key="key", base_url="https://example.com/v1", model_id="model")

            with (
                patch(
                    "app.services.vision_dual.analyze_path_a",
                    new=AsyncMock(
                        side_effect=AnalysisPipelineError(
                            AnalysisErrorCode.AI_RESPONSE_PARSE_FAIL,
                            "bad a",
                        )
                    ),
                ),
                patch("app.services.vision_dual.analyze_path_b", new=AsyncMock(return_value=_path_b_result())),
            ):
                with self.assertRaises(AnalysisPipelineError) as caught:
                    await analyze_frames_dual(
                        "jump",
                        frame_paths,
                        _payloads(1),
                        None,
                        None,
                        provider,
                        provider,
                        annotated_dir=Path(tmp) / "annotated",
                    )

        self.assertEqual(caught.exception.code, AnalysisErrorCode.AI_RESPONSE_PARSE_FAIL)

    async def test_bio_none_and_pose_none_degrade_without_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            frame_paths = _write_frames(Path(tmp), 1)
            provider = SimpleNamespace(api_key="key", base_url="https://example.com/v1", model_id="model")
            mock_b = AsyncMock(return_value=_path_b_result())

            with (
                patch("app.services.vision_dual.analyze_path_a", new=AsyncMock(return_value=_path_a_result())),
                patch("app.services.vision_dual.analyze_path_b", new=mock_b),
            ):
                result = await analyze_frames_dual(
                    "jump",
                    frame_paths,
                    _payloads(1),
                    None,
                    None,
                    provider,
                    provider,
                    annotated_dir=Path(tmp) / "annotated",
                )

        kwargs = mock_b.await_args.kwargs
        self.assertEqual(kwargs["frame_bio_context"], {})
        self.assertEqual(kwargs["key_frame_stems"], set())
        self.assertEqual(kwargs["jump_metrics_text"], "")
        self.assertEqual(result.used_key_frames, set())

    async def test_path_a_receives_bio_data_and_motion_features(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            frame_paths = _write_frames(Path(tmp), 1)
            provider = SimpleNamespace(api_key="key", base_url="https://example.com/v1", model_id="model")
            bio_data = {
                "key_frame_candidates": {
                    "T": {"frame_id": "frame_0001", "confidence": 0.7},
                    "A": {"frame_id": "frame_0001", "confidence": 0.8},
                    "L": {"frame_id": "frame_0001", "confidence": 0.6},
                }
            }
            frame_motion_scores = {
                "sample_count": 3,
                "scores": [0.1, 0.8, 0.3],
                "selected": [{"frame_id": "frame_0001", "motion_score": 0.8}],
            }
            mock_a = AsyncMock(return_value=_path_a_result())

            with (
                patch("app.services.vision_dual.analyze_path_a", new=mock_a),
                patch("app.services.vision_dual.analyze_path_b", new=AsyncMock(return_value=_path_b_result())),
                patch("app.services.vision_dual.encode_frames", new=AsyncMock(return_value=_payloads(1))),
            ):
                await analyze_frames_dual(
                    "jump",
                    frame_paths,
                    _payloads(1),
                    None,
                    bio_data,
                    provider,
                    provider,
                    frame_motion_scores=frame_motion_scores,
                    annotated_dir=Path(tmp) / "annotated",
                )

        kwargs = mock_a.await_args.kwargs
        self.assertEqual(kwargs["bio_data"], bio_data)
        self.assertEqual(kwargs["motion_features"]["sample_count"], 3)
        self.assertEqual(kwargs["motion_features"]["score_summary"]["max"], 0.8)
        self.assertEqual(kwargs["motion_features"]["selected"], frame_motion_scores["selected"])

    async def test_timestamps_are_passed_to_annotated_encode_frames(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            frame_paths = _write_frames(Path(tmp), 1)
            provider = SimpleNamespace(api_key="key", base_url="https://example.com/v1", model_id="model")
            timestamps = {"frame_0001": 1.25}

            with (
                patch("app.services.vision_dual.analyze_path_a", new=AsyncMock(return_value=_path_a_result())),
                patch("app.services.vision_dual.analyze_path_b", new=AsyncMock(return_value=_path_b_result())),
                patch("app.services.vision_dual.encode_frames", new=AsyncMock(return_value=_payloads(1))) as mock_encode,
            ):
                await analyze_frames_dual(
                    "jump",
                    frame_paths,
                    _payloads(1),
                    None,
                    None,
                    provider,
                    provider,
                    annotated_dir=Path(tmp) / "annotated",
                    timestamps=timestamps,
                )

        self.assertEqual(mock_encode.await_args.kwargs["timestamps"], timestamps)


if __name__ == "__main__":
    unittest.main()
