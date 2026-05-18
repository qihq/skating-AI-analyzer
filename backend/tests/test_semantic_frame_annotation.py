from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.video import FramePayload
from app.services.vision_dual import analyze_frames_dual


def _provider() -> SimpleNamespace:
    return SimpleNamespace(api_key="key", base_url="https://example.com/v1", model_id="qwen3.6-plus")


def _path_a() -> dict:
    return {
        "path": "A",
        "frame_analysis": [{"frame_id": "semantic_0001", "phase": "起跳", "confidence": 0.8}],
        "action_phase_summary": {"detected_phases": ["起跳"]},
        "pure_vision_subscores": {},
    }


def _path_b() -> dict:
    return {
        "path": "B",
        "n_frames": 1,
        "frame_analysis": [{"frame_id": "semantic_0001", "phase": "起跳", "confidence": 0.8}],
        "action_phase_summary": {"detected_phases": ["起跳"]},
        "subscores": {},
    }


def _semantic_payload() -> list[FramePayload]:
    return [FramePayload(frame_id="semantic_0001", data_url="data:image/jpeg;base64,AAA", timestamp_sec=1.2)]


def _resolved() -> dict[str, object]:
    return {
        "source": "video_ai_refined",
        "selected": [{"frame_id": "semantic_0001", "timestamp": 1.2, "phase_code": "takeoff", "phase_label": "起跳"}],
    }


class SemanticFrameAnnotationTests(unittest.IsolatedAsyncioTestCase):
    async def test_semantic_frames_use_light_pose_for_path_b_annotation_without_replacing_main_pose(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frame_path = root / "semantic_0001.jpg"
            frame_path.write_bytes(b"frame")
            main_pose = {"frames": [{"frame": "frame_0001.jpg", "keypoints": [{"source": "main"}]}], "connections": []}
            semantic_pose = {"frames": [{"frame": "semantic_0001.jpg", "keypoints": [{"source": "semantic"}]}], "connections": []}
            mock_b = AsyncMock(return_value=_path_b())

            with (
                patch("app.services.vision_dual._semantic_pose_for_annotation", return_value=semantic_pose) as pose_mock,
                patch("app.services.vision_dual.annotate_frames_batch", return_value=[frame_path]) as annotate_mock,
                patch("app.services.vision_dual.encode_frames", AsyncMock(return_value=_semantic_payload())),
                patch("app.services.vision_dual.analyze_path_a", AsyncMock(return_value=_path_a())),
                patch("app.services.vision_dual.analyze_path_b", mock_b),
            ):
                result = await analyze_frames_dual(
                    "跳跃",
                    [frame_path],
                    _semantic_payload(),
                    main_pose,
                    {"quality_flags": []},
                    _provider(),
                    _provider(),
                    annotated_dir=root / "annotated",
                    resolved_keyframes=_resolved(),
                )

        pose_mock.assert_called_once()
        self.assertEqual(annotate_mock.call_args.args[1]["semantic_0001"]["keypoints"], [{"source": "semantic"}])
        self.assertEqual(mock_b.await_args.kwargs["frame_bio_context"], {})
        self.assertTrue(mock_b.await_args.kwargs["preserve_all_frames"])
        self.assertEqual(result.dual_path_meta["path_b_annotation_source"], "semantic_light_pose")
        self.assertTrue(result.dual_path_meta["path_b_preserve_all_frames"])
        self.assertEqual(main_pose["frames"][0]["frame"], "frame_0001.jpg")

    async def test_semantic_light_pose_failure_keeps_path_b_running_with_original_frames(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frame_path = root / "semantic_0001.jpg"
            frame_path.write_bytes(b"frame")
            main_pose = {"frames": [{"frame": "frame_0001.jpg", "keypoints": [{"source": "main"}]}], "connections": []}
            mock_b = AsyncMock(return_value=_path_b())

            with (
                patch("app.services.vision_dual._semantic_pose_for_annotation", side_effect=RuntimeError("pose failed")),
                patch("app.services.vision_dual.annotate_frames_batch", return_value=[frame_path]) as annotate_mock,
                patch("app.services.vision_dual.encode_frames", AsyncMock(return_value=_semantic_payload())),
                patch("app.services.vision_dual.analyze_path_a", AsyncMock(return_value=_path_a())),
                patch("app.services.vision_dual.analyze_path_b", mock_b),
            ):
                result = await analyze_frames_dual(
                    "跳跃",
                    [frame_path],
                    _semantic_payload(),
                    main_pose,
                    {"quality_flags": []},
                    _provider(),
                    _provider(),
                    annotated_dir=root / "annotated",
                    resolved_keyframes=_resolved(),
                )

        self.assertEqual(annotate_mock.call_args.args[1], {})
        mock_b.assert_awaited_once()
        self.assertTrue(mock_b.await_args.kwargs["preserve_all_frames"])
        self.assertFalse(result.dual_path_meta["path_b_failed"])
        self.assertEqual(result.dual_path_meta["path_b_annotation_source"], "semantic_pose_failed_original_frames")
        self.assertEqual(main_pose["frames"][0]["keypoints"], [{"source": "main"}])

    async def test_non_semantic_flow_uses_main_pose_for_annotation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frame_path = root / "frame_0001.jpg"
            frame_path.write_bytes(b"frame")
            main_pose = {"frames": [{"frame": "frame_0001.jpg", "keypoints": [{"source": "main"}]}], "connections": []}

            with (
                patch("app.services.vision_dual._semantic_pose_for_annotation", side_effect=AssertionError("should not run")),
                patch("app.services.vision_dual.annotate_frames_batch", return_value=[frame_path]) as annotate_mock,
                patch("app.services.vision_dual.encode_frames", AsyncMock(return_value=[FramePayload("frame_0001", "data:image/jpeg;base64,AAA")])),
                patch("app.services.vision_dual.analyze_path_a", AsyncMock(return_value={"path": "A", "frame_analysis": [], "action_phase_summary": {}, "pure_vision_subscores": {}})),
                patch("app.services.vision_dual.analyze_path_b", AsyncMock(return_value={"path": "B", "frame_analysis": [], "subscores": {}, "action_phase_summary": {}})),
            ):
                result = await analyze_frames_dual(
                    "跳跃",
                    [frame_path],
                    [FramePayload("frame_0001", "data:image/jpeg;base64,AAA")],
                    main_pose,
                    {"quality_flags": []},
                    _provider(),
                    _provider(),
                    annotated_dir=root / "annotated",
                    resolved_keyframes={"source": "skeleton_fallback", "selected": []},
                )

        self.assertEqual(annotate_mock.call_args.args[1]["frame_0001"]["keypoints"], [{"source": "main"}])
        self.assertEqual(result.dual_path_meta["path_b_annotation_source"], "main_pose")

    async def test_semantic_frames_do_not_downsample_path_b_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frame_paths = []
            payloads = []
            selected = []
            for index in range(1, 13):
                frame_id = f"semantic_{index:04d}"
                frame_path = root / f"{frame_id}.jpg"
                frame_path.write_bytes(b"frame")
                frame_paths.append(frame_path)
                payloads.append(FramePayload(frame_id, "data:image/jpeg;base64,AAA", timestamp_sec=float(index)))
                selected.append({"frame_id": frame_id, "timestamp": float(index), "phase_code": "air", "phase_label": "腾空"})

            mock_b = AsyncMock(return_value={"path": "B", "n_frames": 12, "frame_analysis": [], "subscores": {}, "action_phase_summary": {}})

            with (
                patch("app.services.vision_dual._semantic_pose_for_annotation", return_value={"frames": [], "connections": []}),
                patch("app.services.vision_dual.annotate_frames_batch", return_value=frame_paths),
                patch("app.services.vision_dual.encode_frames", AsyncMock(return_value=payloads)),
                patch("app.services.vision_dual.analyze_path_a", AsyncMock(return_value={"path": "A", "frame_analysis": [], "action_phase_summary": {}, "pure_vision_subscores": {}})),
                patch("app.services.vision_dual.analyze_path_b", mock_b),
            ):
                result = await analyze_frames_dual(
                    "跳跃",
                    frame_paths,
                    payloads,
                    {"frames": [], "connections": []},
                    {"quality_flags": []},
                    _provider(),
                    _provider(),
                    annotated_dir=root / "annotated",
                    resolved_keyframes={"source": "video_ai_refined", "selected": selected},
                )

        self.assertTrue(mock_b.await_args.kwargs["preserve_all_frames"])
        self.assertEqual(len(mock_b.await_args.kwargs["annotated_frame_payloads"]), 12)
        self.assertEqual(result.dual_path_meta["annotated_frame_count"], 12)

    async def test_skeleton_fallback_semantic_frames_use_semantic_path_b_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frame_path = root / "semantic_0001.jpg"
            frame_path.write_bytes(b"frame")
            main_pose = {"frames": [{"frame": "frame_0001.jpg", "keypoints": [{"source": "main"}]}], "connections": []}
            semantic_pose = {"frames": [{"frame": "semantic_0001.jpg", "keypoints": [{"source": "semantic"}]}], "connections": []}
            mock_b = AsyncMock(return_value=_path_b())

            with (
                patch("app.services.vision_dual._semantic_pose_for_annotation", return_value=semantic_pose) as pose_mock,
                patch("app.services.vision_dual.annotate_frames_batch", return_value=[frame_path]),
                patch("app.services.vision_dual.encode_frames", AsyncMock(return_value=_semantic_payload())),
                patch("app.services.vision_dual.analyze_path_a", AsyncMock(return_value=_path_a())),
                patch("app.services.vision_dual.analyze_path_b", mock_b),
            ):
                result = await analyze_frames_dual(
                    "跳跃",
                    [frame_path],
                    _semantic_payload(),
                    main_pose,
                    {"quality_flags": []},
                    _provider(),
                    _provider(),
                    annotated_dir=root / "annotated",
                    resolved_keyframes={"source": "skeleton_fallback", "selected": [{"frame_id": "semantic_0001", "timestamp": 1.2, "phase_code": "takeoff"}]},
                )

        pose_mock.assert_called_once()
        self.assertTrue(mock_b.await_args.kwargs["preserve_all_frames"])
        self.assertEqual(result.dual_path_meta["path_b_annotation_source"], "semantic_light_pose")


if __name__ == "__main__":
    unittest.main()
