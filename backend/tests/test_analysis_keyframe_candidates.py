from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _keypoints(
    *,
    com_y: float,
    knee_state: str,
) -> list[dict[str, float | int]]:
    keypoints: list[dict[str, float | int]] = [
        {"id": index, "x": 0.0, "y": 0.0, "z": 0.0, "visibility": 0.0}
        for index in range(33)
    ]
    shoulder_y = com_y - 0.16
    hip_y = com_y + 0.16
    left_hip = (0.44, hip_y)
    right_hip = (0.56, hip_y)

    if knee_state == "straight":
        knee_offset_x = 0.0
        lower_dx = 0.0
        lower_dy = 0.18
    elif knee_state == "soft":
        knee_offset_x = 0.02
        lower_dx = 0.06
        lower_dy = 0.16
    else:
        knee_offset_x = 0.03
        lower_dx = 0.13
        lower_dy = 0.10

    left_knee = (left_hip[0] + knee_offset_x, hip_y + 0.18)
    right_knee = (right_hip[0] - knee_offset_x, hip_y + 0.18)
    left_ankle = (left_knee[0] + lower_dx, left_knee[1] + lower_dy)
    right_ankle = (right_knee[0] - lower_dx, right_knee[1] + lower_dy)

    visible = {
        11: (0.42, shoulder_y),
        12: (0.58, shoulder_y),
        23: left_hip,
        24: right_hip,
        25: left_knee,
        26: right_knee,
        27: left_ankle,
        28: right_ankle,
    }
    for index, (x_value, y_value) in visible.items():
        keypoints[index] = {
            "id": index,
            "x": x_value,
            "y": y_value,
            "z": 0.0,
            "visibility": 0.95,
        }
    return keypoints


def _pose_data() -> dict[str, object]:
    com_values = [0.62, 0.60, 0.56, 0.49, 0.43, 0.38, 0.42, 0.50, 0.58]
    knee_states = ["bent", "bent", "soft", "straight", "straight", "straight", "straight", "soft", "bent"]
    return {
        "frames": [
            {
                "frame": f"frame_{index + 1:04d}.jpg",
                "keypoints": _keypoints(com_y=com_values[index], knee_state=knee_states[index]),
            }
            for index in range(len(com_values))
        ],
        "connections": [],
    }


def _motion_scores() -> dict[str, object]:
    scores = [0.05, 0.12, 0.35, 0.95, 0.45, 0.25, 0.35, 0.9, 0.25]
    return {
        "sample_count": len(scores),
        "selected": [
            {
                "frame_id": f"frame_{index + 1:04d}",
                "timestamp": round(index / 10.0, 3),
                "motion_score": score,
            }
            for index, score in enumerate(scores)
        ],
        "scores": scores,
    }


class AnalysisKeyframeCandidatesTests(unittest.IsolatedAsyncioTestCase):
    async def test_biomechanics_retry_persists_candidates_and_detail_returns_them(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["DATA_DIR"] = tmpdir
            os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(tmpdir) / 'test.db'}"

            for module_name in [
                "app.database",
                "app.models",
                "app.routers.analysis",
                "app.services.pipeline_version",
            ]:
                sys.modules.pop(module_name, None)

            import app.database as database
            import app.models as models
            import app.routers.analysis as analysis_router
            from app.services.pipeline_version import CURRENT_PIPELINE_VERSION

            database.ensure_storage_dirs()
            await database.init_db()

            analysis_id = str(uuid4())
            upload_dir = Path(tmpdir) / "uploads" / analysis_id
            frames_dir = upload_dir / "frames"
            frames_dir.mkdir(parents=True, exist_ok=True)
            (upload_dir / "source.mp4").write_bytes(b"fake-video")
            for index in range(1, 10):
                (frames_dir / f"frame_{index:04d}.jpg").write_bytes(b"fake-frame")

            pose_data = _pose_data()
            motion_scores = _motion_scores()
            target_lock = {"status": "locked", "selected_candidate_id": "candidate_center"}
            vision_structured = {
                "frame_analysis": [
                    {"frame_id": "frame_0004", "phase": "takeoff", "issues": [], "positives": [], "confidence": 0.9}
                ],
                "action_phase_summary": {"detected_phases": ["takeoff"], "weakest_phase": "landing", "strongest_phase": "takeoff"},
                "overall_raw_text": "ok",
            }
            report = {
                "summary": "ok",
                "issues": [],
                "improvements": [],
                "training_focus": "ok",
                "subscores": {
                    "takeoff_power": 80,
                    "rotation_axis": 80,
                    "arm_coordination": 80,
                    "landing_absorption": 80,
                    "core_stability": 80,
                },
                "data_quality": "good",
            }
            dual = SimpleNamespace(
                path_a=vision_structured,
                path_b={"path": "B", "subscores": {}},
                validation=SimpleNamespace(to_dict=lambda: {"recommended_path": "A"}),
                dual_path_meta={"recommended_path": "A"},
                blend_weights=(1.0, 0.0),
                annotated_dir=None,
                used_key_frames=set(),
            )

            async with database.AsyncSessionLocal() as session:
                analysis = models.Analysis(
                    id=analysis_id,
                    action_type="跳跃",
                    action_subtype="单跳",
                    analysis_profile="jump",
                    retry_from_stage="biomechanics",
                    pipeline_version=CURRENT_PIPELINE_VERSION,
                    video_path=str(upload_dir / "source.mp4"),
                    frame_motion_scores=motion_scores,
                    pose_data=pose_data,
                    target_lock=target_lock,
                    target_lock_status="locked",
                    action_window_start=0.0,
                    action_window_end=0.8,
                    source_fps=30.0,
                    is_slow_motion=False,
                    status="failed",
                    error_code="UNKNOWN_ERROR",
                )
                session.add(analysis)
                await session.commit()

            with (
                patch(
                    "app.routers.analysis.encode_frames",
                    AsyncMock(return_value=[SimpleNamespace(frame_id="frame_0004", data_url="data:image/jpeg;base64,AAA")]),
                ),
                patch("app.routers.analysis.cut_action_window_ai_clip", AsyncMock(return_value=upload_dir / "path_a_input_window_ai.mp4")),
                patch("app.routers.analysis.analyze_frames_dual", AsyncMock(return_value=dual)),
                patch("app.routers.analysis.dual_path_summary", return_value={"recommended": "A", "n_frames_b": 0}),
                patch("app.routers.analysis._provider_for_slot", AsyncMock(return_value=SimpleNamespace())),
                patch("app.routers.analysis.generate_report", AsyncMock(return_value=report)),
                patch("app.routers.analysis.calculate_force_score", return_value=80),
                patch("app.routers.analysis.auto_update_skill_progress", AsyncMock(return_value=None)),
                patch("app.routers.analysis.sync_skater_progress", AsyncMock(return_value=None)),
                patch("app.routers.analysis.suggest_memory_updates", AsyncMock(return_value=None)),
            ):
                await analysis_router.process_analysis(analysis_id, retry_from="biomechanics")

            async with database.AsyncSessionLocal() as session:
                saved = await session.get(models.Analysis, analysis_id)
                self.assertIsNotNone(saved)
                assert saved is not None
                self.assertEqual(saved.status, "completed")
                self.assertIsInstance(saved.bio_data, dict)
                assert isinstance(saved.bio_data, dict)
                self.assertIn("key_frames", saved.bio_data)
                self.assertIn("key_frame_candidates", saved.bio_data)
                self.assertEqual(saved.bio_data["key_frame_candidates"]["T"]["frame_id"], "frame_0004")
                self.assertEqual(saved.bio_data["key_frame_candidates"]["A"]["frame_id"], "frame_0006")
                self.assertEqual(saved.bio_data["key_frame_candidates"]["L"]["frame_id"], "frame_0008")

                detail = await analysis_router.get_analysis(analysis_id, session=session)
                self.assertIsInstance(detail.bio_data, dict)
                assert isinstance(detail.bio_data, dict)
                self.assertIn("key_frames", detail.bio_data)
                self.assertIn("key_frame_candidates", detail.bio_data)
                self.assertEqual(detail.bio_data["key_frame_candidates"]["T"]["frame_id"], "frame_0004")


if __name__ == "__main__":
    unittest.main()
