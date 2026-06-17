from __future__ import annotations

import os
import sys
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from itertools import cycle
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _report() -> dict[str, object]:
    return {
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


def _dual(vision_structured: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(
        path_a=vision_structured,
        path_b={"path": "B", "subscores": {}},
        validation=SimpleNamespace(to_dict=lambda: {"recommended_path": "A"}),
        dual_path_meta={"recommended_path": "A"},
        blend_weights=(1.0, 0.0),
        annotated_dir=None,
        used_key_frames=set(),
    )


def _auto_locked_preview(lock_confidence: float = 1.0) -> SimpleNamespace:
    return SimpleNamespace(lock_confidence=lock_confidence, target_lock_status="auto_locked")


class AnalysisVideoTemporalPipelineTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _mixed_action_input() -> tuple[str, str]:
        from app.services.action_profiles import ACTION_SUBTYPE_OPTIONS, is_mixed_action_input

        return next(
            (action, subtypes[0])
            for action, subtypes in ACTION_SUBTYPE_OPTIONS.items()
            if subtypes and is_mixed_action_input(action, subtypes[0])
        )

    def test_mixed_action_unknown_video_ai_can_recover_jump_from_strong_skeleton_candidates(self) -> None:
        import app.routers.analysis as analysis_router

        candidates = {
            "T": {"frame_id": "frame_0010", "timestamp": 3.7, "confidence": 0.34},
            "A": {"frame_id": "frame_0014", "timestamp": 4.1, "confidence": 0.34},
            "L": {"frame_id": "frame_0018", "timestamp": 4.5, "confidence": 0.34},
            "quality_flags": ["tal_candidate_weak_geometry"],
        }
        video_temporal = {
            "action_confirmation": {"action_family": "unknown", "confidence": 0.1},
            "fallback_recommendation": "manual_review",
        }
        profile_evidence = {
            "jump_gate_passed": True,
            "mixed_jump_gate_passed": False,
            "relative_vertical_range": 0.68,
            "hip_rotation_signal": 0.05,
        }

        self.assertTrue(
            analysis_router._mixed_action_should_recover_jump_from_skeleton(
                "自由滑",
                "节目片段",
                current_profile="step",
                video_ai_profile=None,
                video_temporal=video_temporal,
                profile_evidence=profile_evidence,
                jump_candidates=candidates,
            )
        )

    def test_mixed_action_low_quality_video_ai_jump_does_not_override_spin_evidence(self) -> None:
        import app.routers.analysis as analysis_router

        profile, flags = analysis_router._profile_from_video_ai_for_mixed_action(
            "自由滑",
            "节目片段",
            {
                "action_confirmation": {"action_family": "jump", "confidence": 0.65},
                "quality_flags": ["video_temporal_not_high_confidence", "low_resolution"],
            },
            {"hip_rotation_signal": 0.33},
        )

        self.assertIsNone(profile)
        self.assertIn("mixed_action_video_ai_jump_profile_low_confidence", flags)

    def test_mixed_action_weak_video_ai_jump_downgrades_low_confidence_skeleton_jump(self) -> None:
        import app.routers.analysis as analysis_router

        self.assertTrue(
            analysis_router._mixed_action_skeleton_jump_should_downgrade_to_step(
                current_profile="jump",
                video_ai_profile=None,
                video_ai_profile_flags=["mixed_action_video_ai_jump_profile_low_confidence"],
                bio_data={
                    "key_frame_candidates": {
                        "T": {"frame_id": "frame_0010", "confidence": 0.55},
                        "A": {"frame_id": "frame_0012", "confidence": 0.52},
                        "L": {"frame_id": "frame_0014", "confidence": 0.50},
                        "quality_flags": [],
                    }
                },
                profile_evidence={"hip_rotation_signal": 0.08},
            )
        )

    def test_mixed_action_weak_video_ai_jump_keeps_strong_skeleton_jump(self) -> None:
        import app.routers.analysis as analysis_router

        self.assertFalse(
            analysis_router._mixed_action_skeleton_jump_should_downgrade_to_step(
                current_profile="jump",
                video_ai_profile=None,
                video_ai_profile_flags=["mixed_action_video_ai_jump_profile_low_confidence"],
                bio_data={
                    "key_frame_candidates": {
                        "T": {"frame_id": "frame_0010", "confidence": 0.66},
                        "A": {"frame_id": "frame_0012", "confidence": 0.62},
                        "L": {"frame_id": "frame_0014", "confidence": 0.60},
                        "quality_flags": [],
                    }
                },
                profile_evidence={"hip_rotation_signal": 0.08},
            )
        )

    def test_mixed_action_weak_video_ai_jump_keeps_subtype_supported_small_jump(self) -> None:
        import app.routers.analysis as analysis_router

        self.assertFalse(
            analysis_router._mixed_action_skeleton_jump_should_downgrade_to_step(
                current_profile="jump",
                video_ai_profile=None,
                video_ai_profile_flags=["mixed_action_video_ai_jump_profile_low_confidence"],
                bio_data={
                    "key_frame_candidates": {
                        "T": {"frame_id": "frame_0010", "confidence": 0.55},
                        "A": {"frame_id": "frame_0012", "confidence": 0.52},
                        "L": {"frame_id": "frame_0014", "confidence": 0.50},
                        "quality_flags": [],
                    }
                },
                profile_evidence={
                    "hip_rotation_signal": 0.08,
                    "jump_subtype_evidence": {"free_leg_swing_confidence": 0.61},
                },
            )
        )

    def test_mixed_action_matching_jump_history_blocks_low_quality_video_ai_downgrade(self) -> None:
        import app.routers.analysis as analysis_router

        self.assertFalse(
            analysis_router._mixed_action_skeleton_jump_should_downgrade_to_step(
                current_profile="jump",
                video_ai_profile=None,
                video_ai_profile_flags=["mixed_action_video_ai_jump_profile_rejected_low_quality"],
                video_temporal={
                    "action_confirmation": {
                        "action_family": "jump",
                        "confidence": 0.7,
                    }
                },
                bio_data={
                    "key_frame_candidates": {
                        "T": {"frame_id": "frame_0010", "confidence": 0.34},
                        "A": {"frame_id": "frame_0012", "confidence": 0.34},
                        "L": {"frame_id": "frame_0014", "confidence": 0.34},
                        "quality_flags": ["tal_candidate_weak_geometry"],
                    }
                },
                profile_evidence={
                    "mixed_jump_gate_passed": True,
                    "hip_rotation_signal": 0.1475,
                },
                matching_profile_reuse={
                    "analysis_profile": "jump",
                    "match_count": 10,
                    "candidate_count": 12,
                    "profile_ratio": 0.833,
                    "video_ai_backed_count": 1,
                },
            )
        )

    def test_mixed_action_matching_jump_history_does_not_block_very_low_confidence_video_ai(self) -> None:
        import app.routers.analysis as analysis_router

        self.assertTrue(
            analysis_router._mixed_action_skeleton_jump_should_downgrade_to_step(
                current_profile="jump",
                video_ai_profile=None,
                video_ai_profile_flags=["mixed_action_video_ai_jump_profile_low_confidence"],
                video_temporal={
                    "action_confirmation": {
                        "action_family": "jump",
                        "confidence": 0.69,
                    }
                },
                bio_data={
                    "key_frame_candidates": {
                        "T": {"frame_id": "frame_0010", "confidence": 0.34},
                        "A": {"frame_id": "frame_0012", "confidence": 0.34},
                        "L": {"frame_id": "frame_0014", "confidence": 0.34},
                        "quality_flags": ["tal_candidate_weak_geometry"],
                    }
                },
                profile_evidence={
                    "mixed_jump_gate_passed": True,
                    "hip_rotation_signal": 0.1475,
                },
                matching_profile_reuse={
                    "analysis_profile": "jump",
                    "match_count": 10,
                    "candidate_count": 12,
                    "profile_ratio": 0.833,
                    "video_ai_backed_count": 1,
                },
            )
        )

    def test_mixed_action_matching_jump_history_does_not_block_rotation_conflict_downgrade(self) -> None:
        import app.routers.analysis as analysis_router

        self.assertTrue(
            analysis_router._mixed_action_skeleton_jump_should_downgrade_to_step(
                current_profile="jump",
                video_ai_profile=None,
                video_ai_profile_flags=["mixed_action_video_ai_jump_profile_rejected_rotation_conflict"],
                video_temporal={
                    "action_confirmation": {
                        "action_family": "jump",
                        "confidence": 0.9,
                    }
                },
                bio_data={
                    "key_frame_candidates": {
                        "T": {"frame_id": "frame_0010", "confidence": 0.34},
                        "A": {"frame_id": "frame_0012", "confidence": 0.34},
                        "L": {"frame_id": "frame_0014", "confidence": 0.34},
                        "quality_flags": ["tal_candidate_weak_geometry"],
                    }
                },
                profile_evidence={
                    "mixed_jump_gate_passed": True,
                    "hip_rotation_signal": 0.27,
                },
                matching_profile_reuse={
                    "analysis_profile": "jump",
                    "match_count": 10,
                    "candidate_count": 12,
                    "profile_ratio": 0.833,
                    "video_ai_backed_count": 1,
                },
            )
        )

    def test_mixed_action_high_confidence_video_ai_jump_can_override_when_clean(self) -> None:
        import app.routers.analysis as analysis_router

        profile, flags = analysis_router._profile_from_video_ai_for_mixed_action(
            "自由滑",
            "节目片段",
            {
                "action_confirmation": {"action_family": "jump", "confidence": 0.9},
                "quality_flags": [],
            },
            {"hip_rotation_signal": 0.05},
        )

        self.assertEqual(profile, "jump")
        self.assertEqual(flags, ["mixed_action_profile_overridden_by_video_ai"])

    def test_mixed_action_retry_step_can_override_skeleton_jump_evidence(self) -> None:
        import app.routers.analysis as analysis_router

        profile, flags = analysis_router._profile_from_video_ai_for_mixed_action(
            "自由滑",
            "节目片段",
            {
                "action_confirmation": {"action_family": "step", "confidence": 0.3},
                "quality_flags": ["video_temporal_low_confidence", "video_temporal_fallback_recommended"],
                "retry_attempt": {
                    "action_confirmation": {"action_family": "step", "confidence": 0.9},
                    "phase_segments": [
                        {
                            "phase_code": "step_sequence",
                            "time_start": 0.0,
                            "time_end": 15.0,
                            "key_frame_hint": 5.0,
                            "confidence": 0.85,
                        }
                    ],
                    "quality_flags": ["video_temporal_quality_retry"],
                },
            },
            {
                "jump_gate_passed": True,
                "mixed_jump_gate_passed": True,
                "relative_vertical_range": 0.32,
                "hip_rotation_signal": 0.25,
            },
        )

        self.assertEqual(profile, "step")
        self.assertEqual(
            flags,
            [
                "mixed_action_profile_overridden_by_video_ai",
                "mixed_action_profile_overridden_by_video_ai_retry_attempt",
            ],
        )

    def test_mixed_action_primary_step_does_not_override_strong_skeleton_jump(self) -> None:
        import app.routers.analysis as analysis_router

        action_type, action_subtype = self._mixed_action_input()

        profile, flags = analysis_router._profile_from_video_ai_for_mixed_action(
            action_type,
            action_subtype,
            {
                "action_confirmation": {"action_family": "step", "confidence": 0.75},
                "phase_segments": [
                    {
                        "phase_code": "step_sequence",
                        "time_start": 0.0,
                        "time_end": 8.0,
                        "key_frame_hint": 4.0,
                        "confidence": 0.75,
                    }
                ],
            },
            {
                "jump_gate_passed": True,
                "mixed_jump_gate_passed": True,
                "relative_vertical_range": 0.94,
                "airborne_frames_detected": 10,
                "hip_rotation_signal": 0.165,
            },
        )

        self.assertIsNone(profile)
        self.assertEqual(flags, ["mixed_action_video_ai_non_jump_profile_rejected_strong_skeleton_jump"])

    def test_mixed_action_high_confidence_primary_step_does_not_override_strong_skeleton_jump(self) -> None:
        import app.routers.analysis as analysis_router

        action_type, action_subtype = self._mixed_action_input()

        profile, flags = analysis_router._profile_from_video_ai_for_mixed_action(
            action_type,
            action_subtype,
            {
                "action_confirmation": {"action_family": "step", "confidence": 0.95},
                "phase_segments": [
                    {
                        "phase_code": "step_sequence",
                        "time_start": 0.0,
                        "time_end": 8.0,
                        "key_frame_hint": 4.0,
                        "confidence": 0.92,
                    }
                ],
            },
            {
                "jump_gate_passed": True,
                "mixed_jump_gate_passed": True,
                "relative_vertical_range": 0.94,
                "airborne_frames_detected": 10,
                "hip_rotation_signal": 0.165,
            },
        )

        self.assertIsNone(profile)
        self.assertEqual(flags, ["mixed_action_video_ai_non_jump_profile_rejected_strong_skeleton_jump"])

    def test_mixed_action_high_confidence_retry_step_can_override_strong_skeleton_jump(self) -> None:
        import app.routers.analysis as analysis_router

        action_type, action_subtype = self._mixed_action_input()

        profile, flags = analysis_router._profile_from_video_ai_for_mixed_action(
            action_type,
            action_subtype,
            {
                "action_confirmation": {"action_family": "jump", "confidence": 0.3},
                "retry_attempt": {
                    "action_confirmation": {"action_family": "step", "confidence": 0.9},
                    "phase_segments": [
                        {
                            "phase_code": "step_sequence",
                            "time_start": 0.0,
                            "time_end": 8.0,
                            "key_frame_hint": 4.0,
                            "confidence": 0.85,
                        }
                    ],
                },
            },
            {
                "jump_gate_passed": True,
                "mixed_jump_gate_passed": True,
                "relative_vertical_range": 0.94,
                "airborne_frames_detected": 10,
                "hip_rotation_signal": 0.165,
            },
        )

        self.assertEqual(profile, "step")
        self.assertEqual(
            flags,
            [
                "mixed_action_profile_overridden_by_video_ai",
                "mixed_action_profile_overridden_by_video_ai_retry_attempt",
            ],
        )

    def test_mixed_action_resolved_non_jump_profile_override_follows_resolver(self) -> None:
        import app.routers.analysis as analysis_router

        profile, flags = analysis_router._profile_from_resolved_video_ai_for_mixed_action(
            "\u81ea\u7531\u6ed1",
            "\u8282\u76ee\u7247\u6bb5",
            current_profile="spin",
            video_temporal={"action_confirmation": {"action_family": "step", "confidence": 0.8}},
            resolved_keyframes={
                "quality_flags": [
                    "video_temporal_resolver_profile_overridden_by_video_ai",
                    "video_temporal_resolver_coherent_profile_phases_used",
                ]
            },
        )

        self.assertEqual(profile, "step")
        self.assertEqual(flags, ["mixed_action_profile_overridden_by_video_ai_after_resolver"])

    def test_mixed_action_retry_step_can_override_weak_resolved_jump_profile(self) -> None:
        import app.routers.analysis as analysis_router

        profile, flags = analysis_router._profile_from_resolved_video_ai_for_mixed_action(
            "\u81ea\u7531\u6ed1",
            "\u8282\u76ee\u7247\u6bb5",
            current_profile="jump",
            video_temporal={
                "action_confirmation": {"action_family": "step", "confidence": 0.3},
                "quality_flags": ["video_temporal_low_confidence", "video_temporal_fallback_recommended"],
                "retry_attempt": {
                    "action_confirmation": {"action_family": "step", "confidence": 0.9},
                    "phase_segments": [
                        {
                            "phase_code": "step_sequence",
                            "time_start": 0.0,
                            "time_end": 15.0,
                            "key_frame_hint": 5.0,
                            "confidence": 0.85,
                        }
                    ],
                },
            },
            resolved_keyframes={"quality_flags": ["video_temporal_quality_retry_rejected"]},
            bio_data={
                "key_frame_candidates": {
                    "quality_flags": [
                        "tal_candidate_confidence_low",
                        "tal_candidate_weak_geometry",
                        "tal_candidate_temporal_geometry_unreliable",
                    ],
                    "T": {"frame_id": "frame_0172", "timestamp": 7.167, "confidence": 0.34},
                    "A": {"frame_id": "frame_0176", "timestamp": 7.333, "confidence": 0.34},
                    "L": {"frame_id": "frame_0180", "timestamp": 7.500, "confidence": 0.34},
                }
            },
        )

        self.assertEqual(profile, "step")
        self.assertEqual(
            flags,
            [
                "mixed_action_profile_overridden_by_video_ai_after_resolver",
                "mixed_action_profile_overridden_by_video_ai_retry_attempt",
            ],
        )

    def test_mixed_action_retry_step_does_not_override_strong_resolved_jump_profile(self) -> None:
        import app.routers.analysis as analysis_router

        profile, flags = analysis_router._profile_from_resolved_video_ai_for_mixed_action(
            "\u81ea\u7531\u6ed1",
            "\u8282\u76ee\u7247\u6bb5",
            current_profile="jump",
            video_temporal={
                "action_confirmation": {"action_family": "step", "confidence": 0.3},
                "retry_attempt": {
                    "action_confirmation": {"action_family": "step", "confidence": 0.9},
                    "phase_segments": [
                        {
                            "phase_code": "step_sequence",
                            "time_start": 0.0,
                            "time_end": 15.0,
                            "key_frame_hint": 5.0,
                            "confidence": 0.85,
                        }
                    ],
                },
            },
            resolved_keyframes={"quality_flags": ["video_temporal_quality_retry_rejected"]},
            bio_data={
                "key_frame_candidates": {
                    "quality_flags": [],
                    "T": {"frame_id": "frame_0100", "timestamp": 3.200, "confidence": 0.72},
                    "A": {"frame_id": "frame_0112", "timestamp": 3.600, "confidence": 0.74},
                    "L": {"frame_id": "frame_0124", "timestamp": 4.000, "confidence": 0.73},
                }
            },
        )

        self.assertIsNone(profile)
        self.assertEqual(flags, [])

    def test_mixed_action_resolved_profile_override_requires_coherent_phases(self) -> None:
        import app.routers.analysis as analysis_router

        profile, flags = analysis_router._profile_from_resolved_video_ai_for_mixed_action(
            "\u81ea\u7531\u6ed1",
            "\u8282\u76ee\u7247\u6bb5",
            current_profile="spin",
            video_temporal={"action_confirmation": {"action_family": "step", "confidence": 0.8}},
            resolved_keyframes={"quality_flags": ["video_temporal_resolver_profile_overridden_by_video_ai"]},
        )

        self.assertIsNone(profile)
        self.assertEqual(flags, [])

    def test_mixed_action_resolved_profile_override_ignores_jump_family(self) -> None:
        import app.routers.analysis as analysis_router

        profile, flags = analysis_router._profile_from_resolved_video_ai_for_mixed_action(
            "\u81ea\u7531\u6ed1",
            "\u8282\u76ee\u7247\u6bb5",
            current_profile="spin",
            video_temporal={"action_confirmation": {"action_family": "jump", "confidence": 0.95}},
            resolved_keyframes={
                "quality_flags": [
                    "video_temporal_resolver_profile_overridden_by_video_ai",
                    "video_temporal_resolver_coherent_profile_phases_used",
                ]
            },
        )

        self.assertIsNone(profile)
        self.assertEqual(flags, [])

    async def test_matching_mixed_action_profile_reuse_requires_stable_video_ai_backed_majority(self) -> None:
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

            database.ensure_storage_dirs()
            await database.init_db()

            action_type, action_subtype = self._mixed_action_input()
            identity = {"sha256": "mixed-profile-stable-sha"}
            now = datetime(2026, 6, 11, tzinfo=timezone.utc)

            async with database.AsyncSessionLocal() as session:
                session.add_all(
                    [
                        models.Analysis(
                            id="older-spin",
                            action_type=action_type,
                            action_subtype=action_subtype,
                            analysis_profile="spin",
                            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
                            video_path="/tmp/mixed.mp4",
                            status="completed",
                            created_at=now - timedelta(minutes=3),
                            frame_motion_scores={
                                "video_identity": identity,
                                "video_temporal": {
                                    "action_confirmation": {"action_family": "spin", "confidence": 0.92}
                                },
                            },
                        ),
                        models.Analysis(
                            id="newer-spin",
                            action_type=action_type,
                            action_subtype=action_subtype,
                            analysis_profile="spin",
                            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
                            video_path="/tmp/mixed.mp4",
                            status="completed",
                            created_at=now - timedelta(minutes=1),
                            frame_motion_scores={
                                "video_identity": identity,
                                "resolved_keyframes": {
                                    "video_ai": {
                                        "action_confirmation": {"action_family": "spin", "confidence": 0.88}
                                    }
                                },
                            },
                        ),
                    ]
                )
                await session.commit()

                reuse = await analysis_router._find_matching_mixed_action_profile(
                    session=session,
                    current_analysis_id="current",
                    video_sha256="mixed-profile-stable-sha",
                    action_type=action_type,
                    action_subtype=action_subtype,
                    current_motion_scores={"video_identity": identity},
                )

        self.assertIsNotNone(reuse)
        assert reuse is not None
        self.assertEqual(reuse["analysis_profile"], "spin")
        self.assertEqual(reuse["match_count"], 2)
        self.assertEqual(reuse["video_ai_backed_count"], 2)

    async def test_matching_mixed_action_profile_reuse_rejects_single_old_result(self) -> None:
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

            database.ensure_storage_dirs()
            await database.init_db()

            action_type, action_subtype = self._mixed_action_input()
            identity = {"sha256": "mixed-profile-single-sha"}

            async with database.AsyncSessionLocal() as session:
                session.add(
                    models.Analysis(
                        id="single-step",
                        action_type=action_type,
                        action_subtype=action_subtype,
                        analysis_profile="step",
                        pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
                        video_path="/tmp/mixed.mp4",
                        status="completed",
                        created_at=datetime(2026, 6, 11, tzinfo=timezone.utc),
                        frame_motion_scores={
                            "video_identity": identity,
                            "video_temporal": {
                                "action_confirmation": {"action_family": "step", "confidence": 0.95}
                            },
                        },
                    )
                )
                await session.commit()

                reuse = await analysis_router._find_matching_mixed_action_profile(
                    session=session,
                    current_analysis_id="current",
                    video_sha256="mixed-profile-single-sha",
                    action_type=action_type,
                    action_subtype=action_subtype,
                    current_motion_scores={"video_identity": identity},
                )

        self.assertIsNone(reuse)

    async def test_matching_mixed_action_profile_reuse_requires_video_ai_backing(self) -> None:
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

            database.ensure_storage_dirs()
            await database.init_db()

            action_type, action_subtype = self._mixed_action_input()
            identity = {"sha256": "mixed-profile-unbacked-sha"}
            now = datetime(2026, 6, 11, tzinfo=timezone.utc)

            async with database.AsyncSessionLocal() as session:
                session.add_all(
                    [
                        models.Analysis(
                            id="unbacked-step-a",
                            action_type=action_type,
                            action_subtype=action_subtype,
                            analysis_profile="step",
                            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
                            video_path="/tmp/mixed.mp4",
                            status="completed",
                            created_at=now - timedelta(minutes=2),
                            frame_motion_scores={"video_identity": identity},
                        ),
                        models.Analysis(
                            id="unbacked-step-b",
                            action_type=action_type,
                            action_subtype=action_subtype,
                            analysis_profile="step",
                            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
                            video_path="/tmp/mixed.mp4",
                            status="completed",
                            created_at=now,
                            frame_motion_scores={"video_identity": identity},
                        ),
                    ]
                )
                await session.commit()

                reuse = await analysis_router._find_matching_mixed_action_profile(
                    session=session,
                    current_analysis_id="current",
                    video_sha256="mixed-profile-unbacked-sha",
                    action_type=action_type,
                    action_subtype=action_subtype,
                    current_motion_scores={"video_identity": identity},
                )

        self.assertIsNone(reuse)

    async def test_non_jump_profile_stability_prefers_repeated_video_backed_spin_over_current_step(self) -> None:
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

            database.ensure_storage_dirs()
            await database.init_db()

            action_type, action_subtype = self._mixed_action_input()
            identity = {"sha256": "mixed-non-jump-spin-stable-sha"}
            now = datetime(2026, 6, 12, tzinfo=timezone.utc)

            async with database.AsyncSessionLocal() as session:
                session.add_all(
                    [
                        models.Analysis(
                            id="older-step",
                            action_type=action_type,
                            action_subtype=action_subtype,
                            analysis_profile="step",
                            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
                            video_path="/tmp/mixed.mp4",
                            status="completed",
                            created_at=now - timedelta(minutes=4),
                            frame_motion_scores={
                                "video_identity": identity,
                                "video_temporal": {
                                    "action_confirmation": {"action_family": "step", "confidence": 0.7}
                                },
                            },
                        ),
                        models.Analysis(
                            id="older-spin",
                            action_type=action_type,
                            action_subtype=action_subtype,
                            analysis_profile="spin",
                            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
                            video_path="/tmp/mixed.mp4",
                            status="completed",
                            created_at=now - timedelta(minutes=3),
                            frame_motion_scores={
                                "video_identity": identity,
                                "video_temporal": {
                                    "action_confirmation": {"action_family": "spin", "confidence": 0.9}
                                },
                            },
                        ),
                        models.Analysis(
                            id="newer-spin",
                            action_type=action_type,
                            action_subtype=action_subtype,
                            analysis_profile="spin",
                            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
                            video_path="/tmp/mixed.mp4",
                            status="completed",
                            created_at=now - timedelta(minutes=1),
                            frame_motion_scores={
                                "video_identity": identity,
                                "resolved_keyframes": {
                                    "video_ai": {
                                        "action_confirmation": {"action_family": "spin", "confidence": 0.85}
                                    }
                                },
                            },
                        ),
                    ]
                )
                await session.commit()

                reuse = await analysis_router._find_matching_mixed_action_non_jump_profile_stability(
                    session=session,
                    current_analysis_id="current",
                    video_sha256="mixed-non-jump-spin-stable-sha",
                    action_type=action_type,
                    action_subtype=action_subtype,
                    current_motion_scores={"video_identity": identity},
                    current_profile="step",
                    current_video_ai_confidence=0.85,
                )

        self.assertIsNotNone(reuse)
        assert reuse is not None
        self.assertEqual(reuse["analysis_profile"], "spin")
        self.assertEqual(reuse["video_ai_backed_count"], 2)
        self.assertEqual(reuse["video_ai_confidence"], 0.9)

    async def test_non_jump_profile_stability_rejects_single_prior_spin(self) -> None:
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

            database.ensure_storage_dirs()
            await database.init_db()

            action_type, action_subtype = self._mixed_action_input()
            identity = {"sha256": "mixed-non-jump-single-spin-sha"}

            async with database.AsyncSessionLocal() as session:
                session.add(
                    models.Analysis(
                        id="single-spin",
                        action_type=action_type,
                        action_subtype=action_subtype,
                        analysis_profile="spin",
                        pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
                        video_path="/tmp/mixed.mp4",
                        status="completed",
                        created_at=datetime(2026, 6, 12, tzinfo=timezone.utc),
                        frame_motion_scores={
                            "video_identity": identity,
                            "video_temporal": {
                                "action_confirmation": {"action_family": "spin", "confidence": 0.95}
                            },
                        },
                    )
                )
                await session.commit()

                reuse = await analysis_router._find_matching_mixed_action_non_jump_profile_stability(
                    session=session,
                    current_analysis_id="current",
                    video_sha256="mixed-non-jump-single-spin-sha",
                    action_type=action_type,
                    action_subtype=action_subtype,
                    current_motion_scores={"video_identity": identity},
                    current_profile="step",
                    current_video_ai_confidence=0.85,
                )

        self.assertIsNone(reuse)

    async def test_non_jump_profile_stability_prefers_repeated_spin_over_current_weak_jump(self) -> None:
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

            database.ensure_storage_dirs()
            await database.init_db()

            action_type, action_subtype = self._mixed_action_input()
            identity = {"sha256": "mixed-weak-jump-stable-spin-sha"}
            now = datetime(2026, 6, 12, tzinfo=timezone.utc)

            async with database.AsyncSessionLocal() as session:
                session.add_all(
                    [
                        models.Analysis(
                            id="older-spin",
                            action_type=action_type,
                            action_subtype=action_subtype,
                            analysis_profile="spin",
                            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
                            video_path="/tmp/mixed.mp4",
                            status="completed",
                            created_at=now - timedelta(minutes=4),
                            frame_motion_scores={
                                "video_identity": identity,
                                "video_temporal": {
                                    "action_confirmation": {"action_family": "spin", "confidence": 0.9}
                                },
                            },
                        ),
                        models.Analysis(
                            id="newer-spin",
                            action_type=action_type,
                            action_subtype=action_subtype,
                            analysis_profile="spin",
                            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
                            video_path="/tmp/mixed.mp4",
                            status="completed",
                            created_at=now - timedelta(minutes=2),
                            frame_motion_scores={
                                "video_identity": identity,
                                "resolved_keyframes": {
                                    "video_ai": {
                                        "action_confirmation": {"action_family": "spin", "confidence": 0.85}
                                    }
                                },
                            },
                        ),
                        models.Analysis(
                            id="legacy-jump",
                            action_type=action_type,
                            action_subtype=action_subtype,
                            analysis_profile="jump",
                            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
                            video_path="/tmp/mixed.mp4",
                            status="completed",
                            created_at=now - timedelta(minutes=1),
                            frame_motion_scores={
                                "video_identity": identity,
                                "video_temporal": {
                                    "action_confirmation": {"action_family": "jump", "confidence": 0.75}
                                },
                            },
                        ),
                    ]
                )
                await session.commit()

                weak_jump_bio = {
                    "key_frame_candidates": {
                        "quality_flags": [
                            "tal_candidate_skeleton_drifted_after_takeoff",
                            "keyframe_candidates_motion_fallback",
                            "keyframe_candidates_motion_fallback_from_takeoff_anchor",
                            "tal_candidate_motion_fallback_low_precision",
                        ],
                        "T": {"frame_id": "frame_0010", "confidence": 0.54},
                        "A": {"frame_id": "frame_0011", "confidence": 0.47},
                        "L": {"frame_id": "frame_0012", "confidence": 0.48},
                    }
                }
                current_video_temporal = {
                    "action_confirmation": {"action_family": "jump", "confidence": 0.75},
                    "quality_flags": [
                        "video_temporal_not_high_confidence",
                        "video_temporal_fallback_recommended",
                    ],
                }
                self.assertTrue(
                    analysis_router._mixed_action_weak_jump_can_yield_to_stable_non_jump_history(
                        current_profile="jump",
                        video_ai_profile=None,
                        video_ai_profile_flags=["mixed_action_video_ai_jump_profile_low_confidence"],
                        video_temporal=current_video_temporal,
                        bio_data=weak_jump_bio,
                    )
                )

                reuse = await analysis_router._find_matching_mixed_action_non_jump_profile_stability(
                    session=session,
                    current_analysis_id="current",
                    video_sha256="mixed-weak-jump-stable-spin-sha",
                    action_type=action_type,
                    action_subtype=action_subtype,
                    current_motion_scores={"video_identity": identity},
                    current_profile="jump",
                    current_video_ai_confidence=0.75,
                )

        self.assertIsNotNone(reuse)
        assert reuse is not None
        self.assertEqual(reuse["analysis_profile"], "spin")
        self.assertEqual(reuse["video_ai_backed_count"], 2)
        self.assertEqual(reuse["video_ai_confidence"], 0.9)

    def test_stable_non_jump_history_does_not_beat_clean_current_jump(self) -> None:
        import app.routers.analysis as analysis_router

        self.assertFalse(
            analysis_router._mixed_action_weak_jump_can_yield_to_stable_non_jump_history(
                current_profile="jump",
                video_ai_profile=None,
                video_ai_profile_flags=[],
                video_temporal={
                    "action_confirmation": {"action_family": "jump", "confidence": 0.91},
                    "quality_flags": [],
                },
                bio_data={
                    "key_frame_candidates": {
                        "quality_flags": [],
                        "T": {"frame_id": "frame_0010", "confidence": 0.72},
                        "A": {"frame_id": "frame_0012", "confidence": 0.74},
                        "L": {"frame_id": "frame_0014", "confidence": 0.73},
                    }
                },
            )
        )

    async def test_matching_prior_non_jump_profile_can_guard_weak_jump_drift(self) -> None:
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

            database.ensure_storage_dirs()
            await database.init_db()

            action_type, action_subtype = self._mixed_action_input()
            identity = {"sha256": "mixed-prior-step-sha"}
            now = datetime(2026, 6, 12, tzinfo=timezone.utc)

            async with database.AsyncSessionLocal() as session:
                session.add_all(
                    [
                        models.Analysis(
                            id="older-low-jump",
                            action_type=action_type,
                            action_subtype=action_subtype,
                            analysis_profile="jump",
                            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
                            video_path="/tmp/mixed.mp4",
                            status="completed",
                            created_at=now - timedelta(minutes=3),
                            frame_motion_scores={
                                "video_identity": identity,
                                "video_temporal": {
                                    "action_confirmation": {"action_family": "jump", "confidence": 0.75}
                                },
                            },
                        ),
                        models.Analysis(
                            id="newer-step",
                            action_type=action_type,
                            action_subtype=action_subtype,
                            analysis_profile="step",
                            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
                            video_path="/tmp/mixed.mp4",
                            status="completed",
                            created_at=now - timedelta(minutes=1),
                            frame_motion_scores={
                                "video_identity": identity,
                                "video_temporal": {
                                    "action_confirmation": {"action_family": "step", "confidence": 0.95}
                                },
                            },
                        ),
                    ]
                )
                await session.commit()

                prior = await analysis_router._find_matching_mixed_action_prior_non_jump_profile(
                    session=session,
                    current_analysis_id="current",
                    video_sha256="mixed-prior-step-sha",
                    action_type=action_type,
                    action_subtype=action_subtype,
                    current_motion_scores={"video_identity": identity},
                )

        self.assertIsNotNone(prior)
        assert prior is not None
        self.assertEqual(prior["analysis_profile"], "step")
        self.assertEqual(prior["match_count"], 1)
        self.assertEqual(prior["jump_match_count"], 1)
        self.assertEqual(prior["video_ai_backed_count"], 1)
        self.assertTrue(
            analysis_router._mixed_action_prior_non_jump_profile_should_override_weak_jump(
                current_profile="jump",
                prior_profile_reuse=prior,
                video_ai_profile=None,
                bio_data={
                    "key_frame_candidates": {
                        "quality_flags": [
                            "keyframe_candidates_motion_fallback",
                            "tal_candidate_motion_fallback_low_precision",
                        ],
                        "T": {"frame_id": "frame_0010", "confidence": 0.34},
                        "A": {"frame_id": "frame_0012", "confidence": 0.34},
                        "L": {"frame_id": "frame_0014", "confidence": 0.34},
                    }
                },
                profile_evidence={
                    "jump_subtype_evidence": {"free_leg_swing_confidence": 1.0},
                },
            )
        )

    def test_prior_non_jump_profile_does_not_override_clean_current_jump(self) -> None:
        import app.routers.analysis as analysis_router

        self.assertFalse(
            analysis_router._mixed_action_prior_non_jump_profile_should_override_weak_jump(
                current_profile="jump",
                prior_profile_reuse={"analysis_profile": "step", "match_count": 2, "video_ai_backed_count": 2},
                video_ai_profile=None,
                bio_data={
                    "key_frame_candidates": {
                        "quality_flags": [],
                        "T": {"frame_id": "frame_0010", "confidence": 0.72},
                        "A": {"frame_id": "frame_0012", "confidence": 0.73},
                        "L": {"frame_id": "frame_0014", "confidence": 0.71},
                    }
                },
                profile_evidence={},
            )
        )

    def test_matching_profile_reuse_does_not_override_jump_from_history(self) -> None:
        import app.routers.analysis as analysis_router

        self.assertFalse(
            analysis_router._mixed_action_matching_profile_reuse_should_override(
                current_profile="spin",
                reused_profile="jump",
                bio_data={"key_frame_candidates": {}},
            )
        )

    def test_matching_profile_reuse_is_blocked_by_high_confidence_current_video_ai(self) -> None:
        import app.routers.analysis as analysis_router

        self.assertFalse(
            analysis_router._mixed_action_profile_reuse_allowed_by_video_ai(
                {"action_confirmation": {"action_family": "spin", "confidence": 0.9}},
                [],
            )
        )

    def test_mixed_action_jump_recovery_rejects_strong_rotation_signal(self) -> None:
        import app.routers.analysis as analysis_router

        candidates = {
            "T": {"frame_id": "frame_0010", "timestamp": 3.0, "confidence": 0.54},
            "A": {"frame_id": "frame_0014", "timestamp": 3.7, "confidence": 0.46},
            "L": {"frame_id": "frame_0018", "timestamp": 4.1, "confidence": 0.45},
            "quality_flags": [],
        }
        profile_evidence = {
            "jump_gate_passed": True,
            "mixed_jump_gate_passed": False,
            "relative_vertical_range": 0.96,
            "hip_rotation_signal": 0.33,
        }

        self.assertFalse(
            analysis_router._mixed_action_should_recover_jump_from_skeleton(
                "自由滑",
                "节目片段",
                current_profile="spin",
                video_ai_profile=None,
                video_temporal={"action_confirmation": {"action_family": "unknown", "confidence": 0.3}},
                profile_evidence=profile_evidence,
                jump_candidates=candidates,
            )
        )

    def test_mixed_action_jump_recovery_rejects_tiny_target_weak_geometry_candidates(self) -> None:
        import app.routers.analysis as analysis_router

        candidates = {
            "T": {"frame_id": "frame_0012", "timestamp": 1.833, "confidence": 0.34},
            "A": {"frame_id": "frame_0015", "timestamp": 2.333, "confidence": 0.34},
            "L": {"frame_id": "frame_0016", "timestamp": 2.5, "confidence": 0.34},
            "quality_flags": [
                "keyframe_candidates_excluded_unreliable_pose_frames",
                "tal_candidate_takeoff_geometry_weak",
                "tal_candidate_apex_geometry_weak",
                "tal_candidate_landing_geometry_weak",
                "tal_candidate_weak_geometry",
                "tal_candidate_tiny_target_weak_geometry",
                "tal_candidate_temporal_geometry_unreliable",
                "tal_candidate_confidence_low",
            ],
        }
        profile_evidence = {
            "jump_gate_passed": True,
            "mixed_jump_gate_passed": False,
            "relative_vertical_range": 0.96,
            "hip_rotation_signal": 0.05,
        }

        self.assertFalse(
            analysis_router._mixed_action_should_recover_jump_from_skeleton(
                "\u81ea\u7531\u6ed1",
                "\u8282\u76ee\u7247\u6bb5",
                current_profile="step",
                video_ai_profile=None,
                video_temporal={"action_confirmation": {"action_family": "unknown", "confidence": 0.3}},
                profile_evidence=profile_evidence,
                jump_candidates=candidates,
            )
        )

    def test_formal_target_preview_candidates_selects_stable_detected_target(self) -> None:
        import app.routers.analysis as analysis_router

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            sampled = []
            for index in range(1, 6):
                path = root / f"frame_{index:04d}.jpg"
                path.write_bytes(b"frame")
                sampled.append(path)
            motion_scores = {"selected": [{"frame_id": "frame_0003", "timestamp": 0.6, "motion_score": 0.9}]}

            stable = {"bbox": {"x": 0.42, "y": 0.26, "width": 0.12, "height": 0.32}, "confidence": 0.83, "source": "yolo_preview"}
            other = {"bbox": {"x": 0.06, "y": 0.15, "width": 0.25, "height": 0.55}, "confidence": 0.91, "source": "yolo_preview"}

            def fake_detect(frame_path: Path, **_: object) -> list[dict[str, object]]:
                if frame_path.name in {"frame_0002.jpg", "frame_0003.jpg", "frame_0004.jpg"}:
                    return [stable]
                return [other]

            with patch("app.routers.analysis.detect_person_candidates", side_effect=fake_detect):
                candidates = analysis_router._formal_target_preview_candidates(sampled, motion_scores)

        self.assertGreaterEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["id"], "candidate_auto_stable")
        self.assertEqual(candidates[0]["bbox"], stable["bbox"])
        self.assertGreaterEqual(candidates[0]["support_count"], 3)

    async def test_video_temporal_diagnostics_include_partial_semantic_frames(self) -> None:
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

            database.ensure_storage_dirs()
            await database.init_db()

            analysis_id = str(uuid4())
            upload_dir = Path(tmpdir) / "uploads" / analysis_id
            semantic_dir = upload_dir / "semantic_frames"
            semantic_dir.mkdir(parents=True, exist_ok=True)
            partial_frame = semantic_dir / "partial_semantic_0001.jpg"
            partial_frame.write_bytes(b"partial")
            partial_records = [
                {
                    "frame_id": "partial_semantic_0001",
                    "timestamp": 1.2,
                    "phase_code": "air",
                    "selection_status": "partial_unreliable",
                }
            ]
            motion_scores = {
                "video_temporal": {"schema_version": "video_temporal_v1", "confidence": 0.75, "quality_flags": []},
                "resolved_keyframes": {
                    "source": "skeleton_fallback",
                    "confidence": 0.75,
                    "quality_flags": ["semantic_keyframes_partial_core_frames_available"],
                    "selected": [],
                    "partial_selected": partial_records,
                },
            }

            async with database.AsyncSessionLocal() as session:
                session.add(
                    models.Analysis(
                        id=analysis_id,
                        action_type="jump",
                        video_path=str(upload_dir / "source.mp4"),
                        status="completed",
                        frame_motion_scores=motion_scores,
                    )
                )
                await session.commit()
                analysis = await session.get(models.Analysis, analysis_id)
                assert analysis is not None
                diagnostics = analysis_router._video_temporal_diagnostics(analysis.frame_motion_scores, analysis_id=analysis_id)

                self.assertIsNotNone(diagnostics)
                assert diagnostics is not None
                self.assertFalse(diagnostics["used_semantic_frames"])
                self.assertTrue(diagnostics["used_legacy_sampled_frames"])
                self.assertEqual(diagnostics["partial_semantic_frames"], partial_records)
                response = await analysis_router.get_frame(analysis_id, "partial_semantic_0001.jpg", session)
                self.assertEqual(Path(response.path), partial_frame)

    async def test_video_temporal_diagnostics_preserve_complete_partial_tal(self) -> None:
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

            database.ensure_storage_dirs()
            await database.init_db()

            analysis_id = str(uuid4())
            upload_dir = Path(tmpdir) / "uploads" / analysis_id
            semantic_dir = upload_dir / "semantic_frames"
            semantic_dir.mkdir(parents=True, exist_ok=True)
            partial_records = []
            for index, phase_code in enumerate(("takeoff", "air", "landing"), start=1):
                frame_id = f"partial_semantic_{index:04d}"
                (semantic_dir / f"{frame_id}.jpg").write_bytes(b"partial")
                partial_records.append(
                    {
                        "frame_id": frame_id,
                        "timestamp": 5.0 + index * 0.2,
                        "phase_code": phase_code,
                        "key_moment": ["T_takeoff_sec", "A_air_sec", "L_landing_sec"][index - 1],
                        "selection_status": "partial_unreliable",
                    }
                )
            motion_scores = {
                "video_temporal": {
                    "schema_version": "video_temporal_v1",
                    "confidence": 0.5,
                    "fallback_recommendation": "manual_review",
                    "quality_flags": ["video_temporal_low_confidence"],
                },
                "resolved_keyframes": {
                    "source": "skeleton_fallback",
                    "confidence": 0.5,
                    "quality_flags": [
                        "video_temporal_resolver_low_video_confidence",
                        "semantic_keyframes_partial_core_frames_available",
                    ],
                    "selected": [],
                    "partial_selected": partial_records,
                },
            }

            async with database.AsyncSessionLocal() as session:
                session.add(
                    models.Analysis(
                        id=analysis_id,
                        action_type="jump",
                        video_path=str(upload_dir / "source.mp4"),
                        status="completed",
                        frame_motion_scores=motion_scores,
                    )
                )
                await session.commit()
                analysis = await session.get(models.Analysis, analysis_id)
                assert analysis is not None
                diagnostics = analysis_router._video_temporal_diagnostics(analysis.frame_motion_scores, analysis_id=analysis_id)

                self.assertIsNotNone(diagnostics)
                assert diagnostics is not None
                self.assertEqual(diagnostics["timestamp_source"], "sampled_frames")
                self.assertFalse(diagnostics["used_semantic_frames"])
                self.assertTrue(diagnostics["used_legacy_sampled_frames"])
                self.assertEqual([item["phase_code"] for item in diagnostics["partial_semantic_frames"]], ["takeoff", "air", "landing"])
                response = await analysis_router.get_frame(analysis_id, "partial_semantic_0003.jpg", session)
                self.assertEqual(Path(response.path), semantic_dir / "partial_semantic_0003.jpg")

    async def test_post_vision_partial_semantic_frames_from_low_confidence_phase_anchors(self) -> None:
        import app.routers.analysis as analysis_router

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.2,
                "quality_flags": ["video_temporal_resolver_low_video_confidence"],
                "selected": [],
            }
            vision_structured = {
                "frame_analysis": [
                    {"frame_id": "frame_0019", "phase": "起跳", "confidence": 0.2},
                    {"frame_id": "frame_0025", "phase": "腾空", "confidence": 0.1},
                    {"frame_id": "frame_0030", "phase": "滑出", "confidence": 0.3},
                ]
            }
            motion_scores = {
                "selected": [
                    {"frame_id": "frame_0019", "timestamp": 2.712},
                    {"frame_id": "frame_0025", "timestamp": 3.712},
                    {"frame_id": "frame_0030", "timestamp": 4.775},
                ]
            }
            partial_paths = [semantic_dir / "partial_semantic_0001.jpg", semantic_dir / "partial_semantic_0002.jpg"]
            partial_records = [
                {
                    "frame_id": "partial_semantic_0001",
                    "timestamp": 2.712,
                    "phase_code": "takeoff",
                    "key_moment": "T_takeoff_sec",
                    "selection_status": "partial_unreliable",
                },
                {
                    "frame_id": "partial_semantic_0002",
                    "timestamp": 3.712,
                    "phase_code": "air",
                    "key_moment": "A_air_sec",
                    "selection_status": "partial_unreliable",
                },
            ]

            with patch(
                "app.routers.analysis.extract_precise_frames_at_timestamps",
                AsyncMock(return_value=(partial_paths, partial_records)),
            ) as extract_mock:
                updated = await analysis_router._attach_post_vision_partial_semantic_frames(
                    video_path=video_path,
                    semantic_frames_dir=semantic_dir,
                    resolved_keyframes=resolved,
                    vision_structured=vision_structured,
                    frame_motion_scores=motion_scores,
                    analysis_profile="jump",
                )

        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertFalse(analysis_router.semantic_keyframes_are_reliable(updated))
        self.assertEqual(updated["partial_selected"], partial_records)
        self.assertIn("semantic_keyframes_post_vision_partial_phase_frames_available", updated["quality_flags"])
        extract_mock.assert_awaited_once()
        args = extract_mock.await_args.args
        self.assertEqual(args[0], video_path)
        self.assertEqual(args[1], semantic_dir)
        self.assertEqual(extract_mock.await_args.kwargs["prefix"], "partial_semantic")

    async def test_video_temporal_success_persists_resolved_keyframes_and_uses_semantic_frames(self) -> None:
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
            from app.services.video import VideoSamplingMetadata

            database.ensure_storage_dirs()
            await database.init_db()

            analysis_id = str(uuid4())
            upload_dir = Path(tmpdir) / "uploads" / analysis_id
            upload_dir.mkdir(parents=True, exist_ok=True)
            source_video = upload_dir / "source.mp4"
            source_video.write_bytes(b"fake-video")

            async with database.AsyncSessionLocal() as session:
                session.add(
                    models.Analysis(
                        id=analysis_id,
                        action_type="跳跃",
                        action_subtype="Axel",
                        video_path=str(source_video),
                        status="pending",
                    )
                )
                await session.commit()

            processing_dir, frames_dir = analysis_router.build_processing_frames_dir(analysis_id)
            sampled = []
            for index in range(1, 4):
                path = frames_dir / f"frame_{index:04d}.jpg"
                path.write_bytes(b"sampled")
                sampled.append(path)
            semantic_dir = processing_dir / "semantic_frames"
            semantic_dir.mkdir(parents=True, exist_ok=True)
            semantic_paths = []
            for index in range(1, 4):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.write_bytes(b"semantic")
                semantic_paths.append(path)

            motion_scores = {
                "selected": [
                    {"frame_id": "frame_0001", "timestamp": 1.0, "motion_score": 0.2},
                    {"frame_id": "frame_0002", "timestamp": 1.2, "motion_score": 0.9},
                ],
                "scores": [0.2, 0.9],
            }
            sampling_metadata = VideoSamplingMetadata(
                action_window_start=0.0,
                action_window_end=2.0,
                window_start_sec=0.0,
                window_end_sec=2.0,
                effective_fps=10.0,
                source_fps=30.0,
                is_slow_motion=False,
            )
            pose_data = {"frames": [{"frame": "frame_0001.jpg", "keypoints": []}], "connections": []}
            bio_data = {
                "key_frame_candidates": {"T": {"frame_id": "frame_0002", "timestamp": 1.2, "confidence": 0.8}},
                "quality_flags": [],
            }
            video_temporal = {"schema_version": "video_temporal_v1", "confidence": 0.86, "quality_flags": []}
            resolved_selected = [
                {
                    "frame_id": "semantic_0001",
                    "timestamp": 1.2,
                    "phase_code": "takeoff",
                    "phase_label": "èµ·è·³",
                    "key_moment": "T_takeoff_sec",
                },
                {
                    "frame_id": "semantic_0002",
                    "timestamp": 1.5,
                    "phase_code": "air",
                    "phase_label": "è…¾ç©º",
                    "key_moment": "A_air_sec",
                },
                {
                    "frame_id": "semantic_0003",
                    "timestamp": 1.8,
                    "phase_code": "landing",
                    "phase_label": "è½å†°",
                    "key_moment": "L_landing_sec",
                },
            ]
            refined_selected = [
                {
                    **record,
                    "timestamp": 1.24 if record["phase_code"] == "takeoff" else record["timestamp"],
                    "pre_refine_timestamp": record["timestamp"],
                    "refinement_method": "local_motion_peak" if record["phase_code"] != "air" else "apex_preserved",
                    "refinement_delta_sec": 0.04 if record["phase_code"] == "takeoff" else 0.0,
                }
                for record in resolved_selected
            ]
            resolved = {
                "source": "video_ai_refined",
                "confidence": 0.86,
                "quality_flags": [],
                "selected": resolved_selected,
                "video_ai": video_temporal,
            }
            semantic_records = refined_selected
            vision_structured = {
                "frame_analysis": [{"frame_id": "semantic_0001", "phase": "起跳", "confidence": 0.9}],
                "action_phase_summary": {"detected_phases": ["起跳"], "weakest_phase": "起跳", "strongest_phase": "起跳"},
                "overall_raw_text": "ok",
            }

            with ExitStack() as stack:
                stack.enter_context(patch("app.routers.analysis.build_processing_frames_dir", return_value=(processing_dir, frames_dir)))
                stack.enter_context(patch("app.routers.analysis.precheck_video", AsyncMock(return_value=None)))
                stack.enter_context(patch("app.routers.analysis.extract_motion_sampled_frames", AsyncMock(return_value=(sampled, motion_scores, sampling_metadata))))
                stack.enter_context(patch("app.routers.analysis.build_target_preview", return_value=_auto_locked_preview()))
                stack.enter_context(patch("app.routers.analysis.build_target_lock_payload", return_value={"status": "auto_locked", "selected_candidate_id": "candidate_center"}))
                stack.enter_context(patch("app.routers.analysis.extract_pose", return_value=pose_data))
                stack.enter_context(patch("app.routers.analysis.infer_analysis_profile", return_value=("jump", {"quality_flags": [], "negative_constraints": []})))
                stack.enter_context(patch("app.routers.analysis.analyze_biomechanics", return_value={"quality_flags": []}))
                stack.enter_context(patch("app.routers.analysis.attach_key_frame_candidates", return_value=bio_data))
                stack.enter_context(patch("app.routers.analysis.infer_jump_subtype_evidence", return_value={}))
                temporal_mock = stack.enter_context(patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", AsyncMock(return_value=video_temporal)))
                stack.enter_context(patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved))
                refine_mock = stack.enter_context(
                    patch(
                        "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
                        AsyncMock(
                            return_value=(
                                [
                                    {
                                        "frame_id": "semantic_0001",
                                        "timestamp": 1.24,
                                        "phase_code": "takeoff",
                                        "phase_label": "起跳",
                                        "pre_refine_timestamp": 1.2,
                                        "refinement_method": "local_motion_peak",
                                        "refinement_delta_sec": 0.04,
                                    }
                                ],
                                [],
                            )
                        ),
                    )
                )
                refine_mock.return_value = (refined_selected, [])
                stack.enter_context(patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(return_value=(semantic_paths, semantic_records))))
                encode_mock = stack.enter_context(
                    patch(
                        "app.routers.analysis.encode_frames",
                        AsyncMock(return_value=[SimpleNamespace(frame_id="semantic_0001", data_url="data:image/jpeg;base64,AAA", timestamp_sec=1.2)]),
                    )
                )
                ai_clip_mock = stack.enter_context(patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=processing_dir / "action_window_ai.mp4")))
                path_a_clip_mock = stack.enter_context(patch("app.routers.analysis.cut_action_window_ai_clip", AsyncMock(return_value=processing_dir / "path_a_input_window_ai.mp4")))
                stack.enter_context(patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=cycle([6.0, 2.0])))
                stack.enter_context(patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0))
                stack.enter_context(patch("app.routers.analysis._provider_for_slot", AsyncMock(return_value=SimpleNamespace())))
                stack.enter_context(patch("app.routers.analysis.build_analysis_prompt_context", AsyncMock(return_value=None)))
                dual_mock = stack.enter_context(patch("app.routers.analysis.analyze_frames_dual", AsyncMock(return_value=_dual(vision_structured))))
                stack.enter_context(patch("app.routers.analysis.dual_path_summary", return_value={"recommended": "A", "n_frames_b": 0}))
                stack.enter_context(patch("app.routers.analysis.generate_report", AsyncMock(return_value=_report())))
                stack.enter_context(patch("app.routers.analysis.calculate_force_score", return_value=80))
                stack.enter_context(patch("app.routers.analysis.auto_update_skill_progress", AsyncMock(return_value=None)))
                stack.enter_context(patch("app.routers.analysis.sync_skater_progress", AsyncMock(return_value=None)))
                stack.enter_context(patch("app.routers.analysis.suggest_memory_updates", AsyncMock(return_value=None)))
                await analysis_router.process_analysis(analysis_id)

            self.assertEqual(encode_mock.await_args.args[0], semantic_paths)
            ai_clip_mock.assert_awaited_once()
            self.assertEqual(ai_clip_mock.await_args.args[3].name, "action_window_ai.mp4")
            temporal_kwargs = temporal_mock.await_args.kwargs
            self.assertEqual(temporal_mock.await_args.args[0].name, "action_window_ai.mp4")
            self.assertEqual(temporal_kwargs["video_duration_sec"], 2.0)
            self.assertEqual(temporal_kwargs["source_video_duration_sec"], 6.0)
            self.assertEqual(temporal_kwargs["timestamp_offset_sec"], 0.0)
            self.assertEqual(temporal_kwargs["analyzed_video_kind"], "action_window_ai")
            self.assertEqual(refine_mock.await_args.args[2][0]["timestamp"], 1.2)
            self.assertEqual(dual_mock.await_args.kwargs["frame_paths"], semantic_paths)
            path_a_clip_mock.assert_not_awaited()
            self.assertIsNotNone(dual_mock.await_args.kwargs["clip_path"])
            self.assertEqual(dual_mock.await_args.kwargs["clip_path"].name, "action_window_ai.mp4")
            async with database.AsyncSessionLocal() as session:
                saved = await session.get(models.Analysis, analysis_id)
                self.assertIsNotNone(saved)
                assert saved is not None
                self.assertEqual(saved.status, "completed")
                self.assertIsInstance(saved.frame_motion_scores, dict)
                assert isinstance(saved.frame_motion_scores, dict)
                self.assertEqual(saved.frame_motion_scores["video_temporal"], video_temporal)
                self.assertEqual(saved.frame_motion_scores["resolved_keyframes"]["selected"], semantic_records)

    async def test_video_temporal_failure_keeps_existing_sampled_frame_flow(self) -> None:
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
            from app.services.video import VideoSamplingMetadata

            database.ensure_storage_dirs()
            await database.init_db()

            analysis_id = str(uuid4())
            upload_dir = Path(tmpdir) / "uploads" / analysis_id
            upload_dir.mkdir(parents=True, exist_ok=True)
            source_video = upload_dir / "source.mp4"
            source_video.write_bytes(b"fake-video")

            async with database.AsyncSessionLocal() as session:
                session.add(models.Analysis(id=analysis_id, action_type="跳跃", action_subtype="Axel", video_path=str(source_video), status="pending"))
                await session.commit()

            _, frames_dir = analysis_router.build_processing_frames_dir(analysis_id)
            sampled = []
            for index in range(1, 3):
                path = frames_dir / f"frame_{index:04d}.jpg"
                path.write_bytes(b"sampled")
                sampled.append(path)

            motion_scores = {"selected": [{"frame_id": "frame_0001", "timestamp": 0.5, "motion_score": 0.4}], "scores": [0.4]}
            sampling_metadata = VideoSamplingMetadata(0.0, 1.0, 0.0, 1.0, 10.0, 30.0, False)
            fallback_video_temporal = {"valid": False, "confidence": 0.0, "quality_flags": ["video_temporal_timeout"]}
            resolved = {"source": "skeleton_fallback", "confidence": 0.0, "quality_flags": [], "selected": [], "video_ai": fallback_video_temporal}
            vision_structured = {
                "frame_analysis": [{"frame_id": "frame_0001", "phase": "起跳", "confidence": 0.9}],
                "action_phase_summary": {"detected_phases": ["起跳"], "weakest_phase": "起跳", "strongest_phase": "起跳"},
                "overall_raw_text": "ok",
            }

            with ExitStack() as stack:
                stack.enter_context(patch("app.routers.analysis.build_processing_frames_dir", return_value=(frames_dir.parent, frames_dir)))
                stack.enter_context(patch("app.routers.analysis.precheck_video", AsyncMock(return_value=None)))
                stack.enter_context(patch("app.routers.analysis.extract_motion_sampled_frames", AsyncMock(return_value=(sampled, motion_scores, sampling_metadata))))
                stack.enter_context(patch("app.routers.analysis.build_target_preview", return_value=_auto_locked_preview()))
                stack.enter_context(patch("app.routers.analysis.build_target_lock_payload", return_value={"status": "auto_locked", "selected_candidate_id": "candidate_center"}))
                stack.enter_context(patch("app.routers.analysis.extract_pose", return_value={"frames": [], "connections": []}))
                stack.enter_context(patch("app.routers.analysis.infer_analysis_profile", return_value=("jump", {"quality_flags": [], "negative_constraints": []})))
                stack.enter_context(patch("app.routers.analysis.analyze_biomechanics", return_value={"quality_flags": []}))
                stack.enter_context(patch("app.routers.analysis.attach_key_frame_candidates", return_value={"quality_flags": []}))
                stack.enter_context(patch("app.routers.analysis.infer_jump_subtype_evidence", return_value={}))
                stack.enter_context(patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", AsyncMock(return_value=fallback_video_temporal)))
                stack.enter_context(patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved))
                precise_mock = stack.enter_context(patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock()))
                encode_mock = stack.enter_context(
                    patch(
                        "app.routers.analysis.encode_frames",
                        AsyncMock(return_value=[SimpleNamespace(frame_id="frame_0001", data_url="data:image/jpeg;base64,AAA", timestamp_sec=0.5)]),
                    )
                )
                ai_clip_mock = stack.enter_context(patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=Path(tmpdir) / "action_window_ai.mp4")))
                path_a_clip_mock = stack.enter_context(patch("app.routers.analysis.cut_action_window_ai_clip", AsyncMock(return_value=Path(tmpdir) / "path_a_input_window_ai.mp4")))
                stack.enter_context(patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=[4.0, 1.0]))
                stack.enter_context(patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0))
                stack.enter_context(patch("app.routers.analysis._provider_for_slot", AsyncMock(return_value=SimpleNamespace())))
                stack.enter_context(patch("app.routers.analysis.build_analysis_prompt_context", AsyncMock(return_value=None)))
                dual_mock = stack.enter_context(patch("app.routers.analysis.analyze_frames_dual", AsyncMock(return_value=_dual(vision_structured))))
                stack.enter_context(patch("app.routers.analysis.dual_path_summary", return_value={"recommended": "A", "n_frames_b": 0}))
                stack.enter_context(patch("app.routers.analysis.generate_report", AsyncMock(return_value=_report())))
                stack.enter_context(patch("app.routers.analysis.calculate_force_score", return_value=80))
                stack.enter_context(patch("app.routers.analysis.auto_update_skill_progress", AsyncMock(return_value=None)))
                stack.enter_context(patch("app.routers.analysis.sync_skater_progress", AsyncMock(return_value=None)))
                stack.enter_context(patch("app.routers.analysis.suggest_memory_updates", AsyncMock(return_value=None)))
                await analysis_router.process_analysis(analysis_id)

            self.assertEqual(encode_mock.await_args.args[0], sampled)
            self.assertEqual(ai_clip_mock.await_args_list[-1].args[3].name, "action_window_ai.mp4")
            path_a_clip_mock.assert_not_awaited()
            self.assertIsNotNone(dual_mock.await_args.kwargs["clip_path"])
            self.assertEqual(dual_mock.await_args.kwargs["clip_path"].name, "action_window_ai.mp4")
            precise_mock.assert_not_awaited()
            async with database.AsyncSessionLocal() as session:
                saved = await session.get(models.Analysis, analysis_id)
                self.assertIsNotNone(saved)
                assert saved is not None
                self.assertEqual(saved.status, "completed")
                self.assertEqual(saved.frame_motion_scores["video_temporal"], fallback_video_temporal)
                self.assertEqual(saved.frame_motion_scores["resolved_keyframes"]["source"], "skeleton_fallback")

    async def test_video_temporal_quality_retry_persists_retry_result_and_uses_semantic_frames(self) -> None:
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
            from app.services.video import VideoSamplingMetadata

            database.ensure_storage_dirs()
            await database.init_db()

            analysis_id = str(uuid4())
            upload_dir = Path(tmpdir) / "uploads" / analysis_id
            upload_dir.mkdir(parents=True, exist_ok=True)
            source_video = upload_dir / "source.mp4"
            source_video.write_bytes(b"fake-video")

            async with database.AsyncSessionLocal() as session:
                session.add(
                    models.Analysis(
                        id=analysis_id,
                        action_type="è·³è·ƒ",
                        action_subtype="Axel",
                        video_path=str(source_video),
                        status="pending",
                    )
                )
                await session.commit()

            processing_dir, frames_dir = analysis_router.build_processing_frames_dir(analysis_id)
            sampled = []
            for index in range(1, 4):
                path = frames_dir / f"frame_{index:04d}.jpg"
                path.write_bytes(b"sampled")
                sampled.append(path)
            semantic_dir = processing_dir / "semantic_frames"
            semantic_dir.mkdir(parents=True, exist_ok=True)
            semantic_paths = []
            semantic_records = []
            for index, phase_code in enumerate(("takeoff", "air", "landing"), start=1):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.write_bytes(b"semantic")
                semantic_paths.append(path)
                semantic_records.append(
                    {
                        "frame_id": f"semantic_{index:04d}",
                        "timestamp": 6.2 + index * 0.25,
                        "phase_code": phase_code,
                        "key_moment": {"takeoff": "T_takeoff_sec", "air": "A_air_sec", "landing": "L_landing_sec"}[phase_code],
                    }
                )

            motion_scores = {
                "selected": [
                    {"frame_id": "frame_0001", "timestamp": 6.2, "motion_score": 0.18},
                    {"frame_id": "frame_0002", "timestamp": 7.8, "motion_score": 0.30},
                ],
                "scores": [0.18, 0.30],
            }
            sampling_metadata = VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False)
            first_video = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.75,
                "phase_segments": [],
                "key_moments": {"T_takeoff_sec": None, "A_air_sec": None, "L_landing_sec": None},
                "quality_flags": ["video_temporal_missing_phase_segments"],
                "validation": {"valid": False, "errors": ["video_temporal_missing_phase_segments"], "warnings": []},
            }
            retry_video = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.75,
                "phase_segments": [
                    {"phase_code": "takeoff", "time_start": 6.25, "time_end": 6.65, "confidence": 0.8},
                    {"phase_code": "air", "time_start": 6.65, "time_end": 7.05, "confidence": 0.8},
                    {"phase_code": "landing", "time_start": 7.05, "time_end": 7.35, "confidence": 0.8},
                ],
                "key_moments": {"T_takeoff_sec": 6.45, "A_air_sec": 6.85, "L_landing_sec": 7.15},
                "quality_flags": [],
                "validation": {"valid": True, "errors": [], "warnings": []},
            }
            rejected = {
                "source": "skeleton_fallback",
                "confidence": 0.75,
                "quality_flags": ["video_temporal_missing_phase_segments", "video_temporal_resolver_no_semantic_selection"],
                "selected": [],
                "video_ai": first_video,
            }
            accepted = {
                "source": "blended",
                "confidence": 0.75,
                "quality_flags": ["video_temporal_resolver_coherent_tal_used"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 6.45, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 6.85, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 7.15, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": retry_video,
            }
            pose_data = {"frames": [{"frame": "frame_0001.jpg", "keypoints": []}], "connections": []}
            bio_data = {"quality_flags": [], "key_frame_candidates": {}}
            vision_structured = {
                "frame_analysis": [{"frame_id": "semantic_0001", "phase": "èµ·è·³", "confidence": 0.9}],
                "action_phase_summary": {"detected_phases": ["èµ·è·³"], "weakest_phase": "èµ·è·³", "strongest_phase": "èµ·è·³"},
                "overall_raw_text": "ok",
            }
            with ExitStack() as stack:
                stack.enter_context(patch("app.routers.analysis.build_processing_frames_dir", return_value=(processing_dir, frames_dir)))
                stack.enter_context(patch("app.routers.analysis.precheck_video", AsyncMock(return_value=None)))
                stack.enter_context(patch("app.routers.analysis.extract_motion_sampled_frames", AsyncMock(return_value=(sampled, motion_scores, sampling_metadata))))
                stack.enter_context(patch("app.routers.analysis.build_target_preview", return_value=_auto_locked_preview(0.7113)))
                stack.enter_context(patch("app.routers.analysis.build_target_lock_payload", return_value={"status": "auto_locked", "selected_candidate_id": "candidate_center"}))
                stack.enter_context(patch("app.routers.analysis.extract_pose", return_value=pose_data))
                stack.enter_context(patch("app.routers.analysis.infer_analysis_profile", return_value=("jump", {"quality_flags": [], "negative_constraints": []})))
                stack.enter_context(patch("app.routers.analysis.analyze_biomechanics", return_value={"quality_flags": []}))
                stack.enter_context(patch("app.routers.analysis.attach_key_frame_candidates", return_value=bio_data))
                stack.enter_context(patch("app.routers.analysis.infer_jump_subtype_evidence", return_value={}))
                analyze_mock = stack.enter_context(patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", AsyncMock(side_effect=[first_video, retry_video])))
                stack.enter_context(patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", side_effect=[rejected, accepted]))
                stack.enter_context(
                    patch(
                        "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
                        AsyncMock(return_value=(accepted["selected"], [])),
                    )
                )
                stack.enter_context(
                    patch(
                        "app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps",
                        AsyncMock(return_value=(semantic_paths, semantic_records)),
                    )
                )
                stack.enter_context(
                    patch(
                        "app.services.semantic_keyframe_pipeline.detect_person_candidates",
                        return_value=[{"bbox": {"x": 0.4, "y": 0.3, "width": 0.07, "height": 0.18}, "confidence": 0.8}],
                    )
                )
                encode_mock = stack.enter_context(
                    patch(
                        "app.routers.analysis.encode_frames",
                        AsyncMock(return_value=[SimpleNamespace(frame_id="semantic_0001", data_url="data:image/jpeg;base64,AAA", timestamp_sec=6.45)]),
                    )
                )
                ai_clip_mock = stack.enter_context(patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=processing_dir / "action_window_ai.mp4")))
                path_a_clip_mock = stack.enter_context(patch("app.routers.analysis.cut_action_window_ai_clip", AsyncMock(return_value=processing_dir / "path_a_input_window_ai.mp4")))
                stack.enter_context(patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=[9.568, 4.6, 9.568, 4.6]))
                stack.enter_context(patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0))
                stack.enter_context(patch("app.routers.analysis._provider_for_slot", AsyncMock(return_value=SimpleNamespace())))
                stack.enter_context(patch("app.routers.analysis.build_analysis_prompt_context", AsyncMock(return_value=None)))
                dual_mock = stack.enter_context(patch("app.routers.analysis.analyze_frames_dual", AsyncMock(return_value=_dual(vision_structured))))
                stack.enter_context(patch("app.routers.analysis.dual_path_summary", return_value={"recommended": "A", "n_frames_b": 0}))
                stack.enter_context(patch("app.routers.analysis.generate_report", AsyncMock(return_value=_report())))
                stack.enter_context(patch("app.routers.analysis.calculate_force_score", return_value=80))
                stack.enter_context(patch("app.routers.analysis.auto_update_skill_progress", AsyncMock(return_value=None)))
                stack.enter_context(patch("app.routers.analysis.sync_skater_progress", AsyncMock(return_value=None)))
                stack.enter_context(patch("app.routers.analysis.suggest_memory_updates", AsyncMock(return_value=None)))
                await analysis_router.process_analysis(analysis_id)

            self.assertEqual(analyze_mock.await_count, 2)
            self.assertEqual(analyze_mock.await_args_list[1].kwargs["analyzed_video_kind"], "action_window_ai_retry")
            self.assertIn("retry_context", analyze_mock.await_args_list[1].kwargs)
            self.assertIn("video_temporal_missing_phase_segments", analyze_mock.await_args_list[1].kwargs["retry_context"]["retry_reason_flags"])
            self.assertEqual(ai_clip_mock.await_count, 2)
            self.assertEqual(encode_mock.await_args.args[0], semantic_paths)
            self.assertEqual(dual_mock.await_args.kwargs["frame_paths"], semantic_paths)
            path_a_clip_mock.assert_not_awaited()
            self.assertIsNotNone(dual_mock.await_args.kwargs["clip_path"])
            self.assertEqual(dual_mock.await_args.kwargs["clip_path"].name, "action_window_ai.mp4")

            async with database.AsyncSessionLocal() as session:
                saved = await session.get(models.Analysis, analysis_id)
                self.assertIsNotNone(saved)
                assert saved is not None
                self.assertEqual(saved.status, "completed")
                assert isinstance(saved.frame_motion_scores, dict)
                self.assertEqual(saved.frame_motion_scores["video_temporal"], retry_video)
                self.assertIn("video_temporal_quality_retry", saved.frame_motion_scores["video_temporal"]["quality_flags"])
                self.assertEqual(saved.frame_motion_scores["resolved_keyframes"]["source"], "blended")
                self.assertEqual(saved.frame_motion_scores["resolved_keyframes"]["selected"], semantic_records)
                self.assertIn("video_temporal_quality_retry_used", saved.frame_motion_scores["resolved_keyframes"]["quality_flags"])

    async def test_process_analysis_reuses_matching_video_semantic_keyframes(self) -> None:
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
            from app.services.video import VideoSamplingMetadata

            database.ensure_storage_dirs()
            await database.init_db()

            video_bytes = b"same-video"
            previous_id = str(uuid4())
            current_id = str(uuid4())
            previous_dir = Path(tmpdir) / "uploads" / previous_id
            current_dir = Path(tmpdir) / "uploads" / current_id
            previous_dir.mkdir(parents=True, exist_ok=True)
            current_dir.mkdir(parents=True, exist_ok=True)
            previous_video = previous_dir / "source.mp4"
            current_video = current_dir / "source.mp4"
            previous_video.write_bytes(video_bytes)
            current_video.write_bytes(video_bytes)
            video_hash = analysis_router.compute_video_sha256(current_video)
            video_identity = {
                "schema_version": analysis_router.VIDEO_IDENTITY_VERSION,
                "sha256": video_hash,
                "size_bytes": len(video_bytes),
                "filename": "source.mp4",
            }
            normalized_subtype = analysis_router.normalize_action_subtype("è·³è·ƒ", "Axel")
            previous_selected = [
                {
                    "frame_id": "semantic_0001",
                    "timestamp": 4.5,
                    "phase_code": "takeoff",
                    "key_moment": "T_takeoff_sec",
                    "confidence": 0.88,
                },
                {
                    "frame_id": "semantic_0002",
                    "timestamp": 5.1,
                    "phase_code": "air",
                    "key_moment": "A_air_sec",
                    "confidence": 0.89,
                },
                {
                    "frame_id": "semantic_0003",
                    "timestamp": 5.453,
                    "phase_code": "landing",
                    "key_moment": "L_landing_sec",
                    "confidence": 0.90,
                },
            ]
            input_window_payload = {
                "source_duration_sec": 8.0,
                "input_window_start_sec": 0.0,
                "input_window_end_sec": 8.0,
                "input_window_duration_sec": 8.0,
                "input_window_mode": "full_context",
                "input_window_truncated": False,
                "input_window_reason": "full_context",
            }

            async with database.AsyncSessionLocal() as session:
                session.add(
                    models.Analysis(
                        id=previous_id,
                        action_type="è·³è·ƒ",
                        action_subtype=normalized_subtype,
                        analysis_profile="jump",
                        pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
                        video_path=str(previous_video),
                        status="completed",
                        frame_motion_scores={
                            **input_window_payload,
                            "input_window": input_window_payload,
                            "video_identity": video_identity,
                            "resolved_keyframes": {
                                "source": "video_ai_refined",
                                "confidence": 0.91,
                                "quality_flags": [],
                                "selected": previous_selected,
                            },
                        },
                    )
                )
                session.add(
                    models.Analysis(
                        id=current_id,
                        action_type="è·³è·ƒ",
                        action_subtype="Axel",
                        analysis_profile="jump",
                        pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
                        video_path=str(current_video),
                        status="pending",
                        frame_motion_scores={"video_identity": video_identity},
                    )
                )
                await session.commit()

            processing_dir, frames_dir = analysis_router.build_processing_frames_dir(current_id)
            sampled = []
            for index in range(1, 4):
                path = frames_dir / f"frame_{index:04d}.jpg"
                path.write_bytes(b"sampled")
                sampled.append(path)
            motion_scores = {
                "selected": [{"frame_id": "frame_0001", "timestamp": 4.4, "motion_score": 0.2}],
                "scores": [0.2],
                "video_identity": video_identity,
            }
            sampling_metadata = VideoSamplingMetadata(0.0, 8.0, 0.0, 8.0, 16.0, 30.0, False)
            pose_data = {"frames": [{"frame": "frame_0001.jpg", "keypoints": []}], "connections": []}
            bio_data = {"quality_flags": [], "key_frame_candidates": {}}
            vision_structured = {
                "frame_analysis": [{"frame_id": "semantic_0001", "phase": "èµ·è·³", "confidence": 0.9}],
                "action_phase_summary": {"detected_phases": ["èµ·è·³"], "weakest_phase": "èµ·è·³", "strongest_phase": "èµ·è·³"},
                "overall_raw_text": "ok",
            }
            semantic_records = [
                {**record, "frame_id": f"semantic_{index:04d}"}
                for index, record in enumerate(previous_selected, start=1)
            ]
            semantic_paths = []
            semantic_dir = processing_dir / "semantic_frames"
            semantic_dir.mkdir(parents=True, exist_ok=True)
            for index in range(1, 4):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.write_bytes(b"semantic")
                semantic_paths.append(path)

            with ExitStack() as stack:
                stack.enter_context(patch("app.routers.analysis.build_processing_frames_dir", return_value=(processing_dir, frames_dir)))
                stack.enter_context(patch("app.services.video.detect_video_duration", return_value=8.0))
                stack.enter_context(patch("app.routers.analysis.precheck_video", AsyncMock(return_value=None)))
                stack.enter_context(patch("app.routers.analysis.extract_motion_sampled_frames", AsyncMock(return_value=(sampled, motion_scores, sampling_metadata))))
                stack.enter_context(patch("app.routers.analysis._start_video_temporal_task_if_missing", AsyncMock(return_value=(None, None, None))))
                stack.enter_context(patch("app.routers.analysis.build_target_preview", return_value=_auto_locked_preview()))
                stack.enter_context(patch("app.routers.analysis.build_target_lock_payload", return_value={"status": "auto_locked", "selected_candidate_id": "candidate_center"}))
                stack.enter_context(patch("app.routers.analysis.extract_pose", return_value=pose_data))
                stack.enter_context(patch("app.routers.analysis.infer_analysis_profile", return_value=("jump", {"quality_flags": [], "negative_constraints": []})))
                stack.enter_context(patch("app.routers.analysis.analyze_biomechanics", return_value={"quality_flags": []}))
                stack.enter_context(patch("app.routers.analysis.attach_key_frame_candidates", return_value=bio_data))
                stack.enter_context(patch("app.routers.analysis.infer_jump_subtype_evidence", return_value={}))
                temporal_mock = stack.enter_context(patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", AsyncMock(return_value={"valid": True})))
                resolver_mock = stack.enter_context(patch("app.routers.analysis.resolve_semantic_keyframe_pipeline", AsyncMock()))
                stack.enter_context(
                    patch(
                        "app.routers.analysis.extract_precise_frames_at_timestamps",
                        AsyncMock(return_value=(semantic_paths, semantic_records)),
                    )
                )
                encode_mock = stack.enter_context(
                    patch(
                        "app.routers.analysis.encode_frames",
                        AsyncMock(return_value=[SimpleNamespace(frame_id="semantic_0001", data_url="data:image/jpeg;base64,AAA", timestamp_sec=4.5)]),
                    )
                )
                path_a_clip_mock = stack.enter_context(patch("app.routers.analysis.cut_action_window_ai_clip", AsyncMock(return_value=processing_dir / "path_a_input_window_ai.mp4")))
                stack.enter_context(patch("app.routers.analysis._provider_for_slot", AsyncMock(return_value=SimpleNamespace())))
                stack.enter_context(patch("app.routers.analysis.build_analysis_prompt_context", AsyncMock(return_value=None)))
                dual_mock = stack.enter_context(patch("app.routers.analysis.analyze_frames_dual", AsyncMock(return_value=_dual(vision_structured))))
                stack.enter_context(patch("app.routers.analysis.dual_path_summary", return_value={"recommended": "A", "n_frames_b": 0}))
                stack.enter_context(patch("app.routers.analysis.generate_report", AsyncMock(return_value=_report())))
                stack.enter_context(patch("app.routers.analysis.calculate_force_score", return_value=80))
                stack.enter_context(patch("app.routers.analysis.auto_update_skill_progress", AsyncMock(return_value=None)))
                stack.enter_context(patch("app.routers.analysis.sync_skater_progress", AsyncMock(return_value=None)))
                stack.enter_context(patch("app.routers.analysis.suggest_memory_updates", AsyncMock(return_value=None)))
                await analysis_router.process_analysis(current_id)

            temporal_mock.assert_not_awaited()
            resolver_mock.assert_not_awaited()
            path_a_clip_mock.assert_awaited_once()
            self.assertEqual(encode_mock.await_args.args[0], semantic_paths)
            self.assertEqual(dual_mock.await_args.kwargs["frame_paths"], semantic_paths)

            async with database.AsyncSessionLocal() as session:
                saved = await session.get(models.Analysis, current_id)
                self.assertIsNotNone(saved)
                assert saved is not None
                self.assertEqual(saved.status, "completed")
                assert isinstance(saved.frame_motion_scores, dict)
                resolved = saved.frame_motion_scores["resolved_keyframes"]
                self.assertIn("semantic_keyframes_reused_from_matching_video", resolved["quality_flags"])
                self.assertEqual([item["timestamp"] for item in resolved["selected"]], [4.5, 5.1, 5.453])
                self.assertEqual([item["frame_id"] for item in resolved["selected"]], ["semantic_0001", "semantic_0002", "semantic_0003"])
                self.assertEqual(resolved["reused_from_analysis_id"], previous_id)
                self.assertEqual(saved.bio_data["key_frame_timestamps"], {"T": 4.5, "A": 5.1, "L": 5.453})

    async def test_matching_semantic_reuse_finds_video_hash_beyond_recent_action_limit(self) -> None:
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

            database.ensure_storage_dirs()
            await database.init_db()

            selected = [
                {"frame_id": "semantic_0001", "timestamp": 6.2, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.8},
                {"frame_id": "semantic_0002", "timestamp": 6.7, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.8},
                {"frame_id": "semantic_0003", "timestamp": 7.433, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.8},
            ]
            video_hash = "matching-video-hash-outside-recent-window"
            matching_id = str(uuid4())
            current_id = str(uuid4())
            async with database.AsyncSessionLocal() as session:
                session.add(
                    models.Analysis(
                        id=matching_id,
                        action_type="Ã¨Â·Â³Ã¨Â·Æ’",
                        action_subtype="Toe Loop",
                        analysis_profile="jump",
                        pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
                        video_path=str(Path(tmpdir) / "matching.mp4"),
                        status="completed",
                        frame_motion_scores={
                            "video_identity": {"sha256": video_hash},
                            "resolved_keyframes": {
                                "source": "blended",
                                "confidence": 0.8,
                                "quality_flags": [],
                                "selected": selected,
                            },
                        },
                    )
                )
                for index in range(60):
                    session.add(
                        models.Analysis(
                            id=str(uuid4()),
                            action_type="Ã¨Â·Â³Ã¨Â·Æ’",
                            action_subtype="Toe Loop",
                            analysis_profile="jump",
                            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
                            video_path=str(Path(tmpdir) / f"other-{index}.mp4"),
                            status="completed",
                            frame_motion_scores={
                                "video_identity": {"sha256": f"other-hash-{index}"},
                                "resolved_keyframes": {
                                    "source": "blended",
                                    "confidence": 0.9,
                                    "quality_flags": [],
                                    "selected": [
                                        {"timestamp": 1.0, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                                        {"timestamp": 1.3, "phase_code": "air", "key_moment": "A_air_sec"},
                                        {"timestamp": 1.6, "phase_code": "landing", "key_moment": "L_landing_sec"},
                                    ],
                                },
                            },
                        )
                    )
                await session.commit()

            async with database.AsyncSessionLocal() as session:
                reuse = await analysis_router._find_matching_semantic_keyframes(
                    session=session,
                    current_analysis_id=current_id,
                    video_sha256=video_hash,
                    action_type="Ã¨Â·Â³Ã¨Â·Æ’",
                    action_subtype="Toe Loop",
                    analysis_profile="jump",
                    current_motion_scores={"video_identity": {"sha256": video_hash}},
                    current_bio_data={"key_frame_candidates": {}},
                )

        self.assertIsNotNone(reuse)
        assert reuse is not None
        self.assertEqual(reuse["analysis_id"], matching_id)
        self.assertEqual([item["timestamp"] for item in reuse["selected"]], [6.2, 6.7, 7.433])

    async def test_reuse_preserves_accepted_source_candidate_conflict_context(self) -> None:
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
            from app.services.video_temporal import semantic_keyframes_are_reliable

            database.ensure_storage_dirs()
            await database.init_db()

            video_hash = "phase-shifted-repeat-video"
            source_video = Path(tmpdir) / "source.mp4"
            source_video.write_bytes(b"fake-video")
            previous_id = str(uuid4())
            current_id = str(uuid4())
            selected = [
                {
                    "frame_id": "semantic_0001",
                    "timestamp": 2.053,
                    "phase_code": "takeoff",
                    "key_moment": "T_takeoff_sec",
                    "selection_reason": "video_phase_range_key_moment",
                    "confidence": 0.85,
                    "phase_time_start": 1.7,
                    "phase_time_end": 2.1,
                },
                {
                    "frame_id": "semantic_0002",
                    "timestamp": 2.3,
                    "phase_code": "air",
                    "key_moment": "A_air_sec",
                    "selection_reason": "video_phase_range_key_moment",
                    "confidence": 0.85,
                    "phase_time_start": 2.1,
                    "phase_time_end": 2.5,
                },
                {
                    "frame_id": "semantic_0003",
                    "timestamp": 2.767,
                    "phase_code": "landing",
                    "key_moment": "L_landing_sec",
                    "selection_reason": "video_phase_range_key_moment",
                    "confidence": 0.85,
                    "phase_time_start": 2.5,
                    "phase_time_end": 2.7,
                },
            ]
            candidate_flags = [
                "keyframe_candidates_excluded_unreliable_pose_frames",
                "keyframe_candidates_tail_motion_window_rejected",
                "keyframe_candidates_tail_motion_window_reselected",
                "tal_candidate_skeleton_drifted_after_takeoff",
                "keyframe_candidates_motion_fallback",
                "keyframe_candidates_motion_fallback_from_takeoff_anchor",
                "tal_candidate_motion_fallback_low_precision",
                "keyframe_candidates_motion_fallback_unreliable_pose_state",
                "tal_candidate_motion_fallback_unreliable_pose_low_confidence",
                "a_pose_signal_drifted",
                "l_pose_signal_drifted",
            ]
            motion_selected = [
                {"frame_id": "frame_0007", "timestamp": 0.375, "motion_score": 0.0633},
                {"frame_id": "frame_0015", "timestamp": 1.438, "motion_score": 0.0226},
                {"frame_id": "frame_0016", "timestamp": 1.625, "motion_score": 0.0206},
                {"frame_id": "frame_0019", "timestamp": 2.188, "motion_score": 0.0304},
                {"frame_id": "frame_0024", "timestamp": 4.25, "motion_score": 0.0239},
                {"frame_id": "frame_0032", "timestamp": 7.312, "motion_score": 0.0675},
            ]
            candidate_conflict = {
                "conflicts": [
                    {
                        "key": "A",
                        "semantic_timestamp": 2.3,
                        "candidate_timestamp": 1.625,
                        "delta_sec": 0.675,
                        "candidate_confidence": 0.483,
                    },
                    {
                        "key": "T",
                        "semantic_timestamp": 2.053,
                        "candidate_timestamp": 1.438,
                        "delta_sec": 0.615,
                        "candidate_confidence": 0.556,
                    },
                ],
                "candidate_quality_flags": candidate_flags,
                "takeoff_anchor_core_conflict": True,
                "motion_window_conflict": {
                    "global_peak_timestamp": 7.312,
                    "global_peak_motion_score": 0.0675,
                    "semantic_window": {
                        "start_sec": 2.053,
                        "end_sec": 2.767,
                        "peak_motion_score": 0.0304,
                    },
                    "candidate_window": {
                        "start_sec": 0.0,
                        "end_sec": 4.25,
                        "peak_motion_score": 0.0633,
                    },
                    "candidate_peak_ratio": 0.938,
                    "semantic_peak_ratio": 0.45,
                    "candidate_to_semantic_peak_ratio": 2.082,
                },
                "decision": "ignored_takeoff_anchor_phase_shifted_candidate",
            }
            current_bio_data = {
                "key_frame_candidates": {
                    "quality_flags": candidate_flags[:-2],
                    "T": {
                        "timestamp": 1.438,
                        "confidence": 0.556,
                        "evidence": {
                            "motion_score": 0.0226,
                            "motion_cluster_window": {"start_timestamp": 0.0, "end_timestamp": 4.25},
                        },
                        "warnings": ["keyframe_candidates_motion_fallback"],
                    },
                    "A": {
                        "timestamp": 1.625,
                        "confidence": 0.483,
                        "evidence": {"motion_score": 0.0206, "motion_fallback": True, "visibility_score": 0.0},
                        "warnings": ["keyframe_candidates_motion_fallback", "a_pose_signal_drifted"],
                    },
                    "L": {
                        "timestamp": 2.188,
                        "confidence": 0.34,
                        "evidence": {"motion_score": 0.0304, "motion_fallback": True, "visibility_score": 0.0},
                        "warnings": [
                            "keyframe_candidates_motion_fallback",
                            "l_pose_signal_drifted",
                            "keyframe_candidates_motion_fallback_unreliable_pose_state",
                        ],
                    },
                }
            }
            current_motion_scores = {
                "video_identity": {"sha256": video_hash},
                "input_window": {
                    "input_window_start_sec": 0.0,
                    "input_window_end_sec": 7.368,
                    "input_window_mode": "full_context",
                },
                "selected": motion_selected,
            }

            async with database.AsyncSessionLocal() as session:
                session.add(
                    models.Analysis(
                        id=previous_id,
                        action_type="jump",
                        action_subtype="single",
                        analysis_profile="jump",
                        pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
                        video_path=str(source_video),
                        status="completed",
                        frame_motion_scores={
                            **current_motion_scores,
                            "resolved_keyframes": {
                                "source": "video_ai_refined",
                                "confidence": 0.9,
                                "quality_flags": [
                                    "video_temporal_resolver_coherent_tal_used",
                                    "semantic_keyframes_candidate_motion_window_conflict_ignored_takeoff_anchor_phase_shift",
                                    "video_temporal_quality_retry_used",
                                ],
                                "selected": selected,
                                "semantic_candidate_tal_conflict": candidate_conflict,
                                "video_ai": {
                                    "confidence": 0.9,
                                    "quality_flags": ["video_temporal_quality_retry"],
                                    "action_confirmation": {"action_family": "jump", "confidence": 0.95},
                                    "phase_segments": [
                                        {"phase_code": "approach", "time_start": 0.0, "time_end": 1.3, "confidence": 0.95},
                                        {"phase_code": "preparation", "time_start": 1.3, "time_end": 1.7, "confidence": 0.9},
                                        {"phase_code": "takeoff", "time_start": 1.7, "time_end": 2.1, "confidence": 0.85},
                                        {"phase_code": "air", "time_start": 2.1, "time_end": 2.5, "confidence": 0.85},
                                        {"phase_code": "landing", "time_start": 2.5, "time_end": 2.7, "confidence": 0.85},
                                    ],
                                },
                            },
                        },
                    )
                )
                session.add(
                    models.Analysis(
                        id=current_id,
                        action_type="jump",
                        action_subtype="single",
                        analysis_profile="jump",
                        pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
                        video_path=str(source_video),
                        status="processing",
                        frame_motion_scores=current_motion_scores,
                        bio_data=current_bio_data,
                    )
                )
                await session.commit()

            semantic_dir = Path(tmpdir) / "semantic_frames"
            semantic_dir.mkdir(parents=True, exist_ok=True)
            semantic_paths = []
            semantic_records = []
            for index, record in enumerate(selected, start=1):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.write_bytes(b"semantic")
                semantic_paths.append(path)
                semantic_records.append({**record, "frame_id": f"semantic_{index:04d}"})

            with patch(
                "app.routers.analysis.extract_precise_frames_at_timestamps",
                AsyncMock(return_value=(semantic_paths, semantic_records)),
            ):
                resolved, frames, records, video_temporal = await analysis_router._reuse_matching_semantic_keyframes(
                    analysis_id=current_id,
                    video_path=source_video,
                    processing_frames_dir=Path(tmpdir) / "frames",
                    video_identity={"sha256": video_hash},
                    action_type="jump",
                    action_subtype="single",
                    analysis_profile="jump",
                    motion_scores=current_motion_scores,
                    bio_data=current_bio_data,
                    video_temporal_result=None,
                )

        self.assertIsNotNone(resolved)
        assert resolved is not None
        self.assertEqual(frames, semantic_paths)
        self.assertEqual(len(records), 3)
        self.assertIsInstance(video_temporal, dict)
        self.assertEqual(resolved["reused_from_analysis_id"], previous_id)
        self.assertIn(
            "semantic_keyframes_candidate_motion_window_conflict_ignored_takeoff_anchor_phase_shift",
            resolved["quality_flags"],
        )
        self.assertNotIn("semantic_keyframes_unreliable_candidate_motion_window_conflict", resolved["quality_flags"])
        self.assertNotIn("semantic_keyframes_unreliable_reused_current_candidate_conflict", resolved["quality_flags"])
        self.assertEqual(
            resolved["semantic_candidate_tal_conflict"]["decision"],
            "ignored_takeoff_anchor_phase_shifted_candidate",
        )
        self.assertTrue(resolved["semantic_candidate_tal_conflict"]["reused_from_source_analysis"])
        self.assertTrue(semantic_keyframes_are_reliable(resolved))

    async def test_semantic_reuse_preserves_current_video_temporal_action_family(self) -> None:
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

            database.ensure_storage_dirs()
            await database.init_db()

            action_type, action_subtype = self._mixed_action_input()
            video_hash = "spin-reuse-video"
            source_video = Path(tmpdir) / "source.mp4"
            source_video.write_bytes(b"fake-video")
            selected = [
                {"timestamp": 0.5, "phase_code": "spin_entry", "confidence": 0.9},
                {"timestamp": 1.5, "phase_code": "spin_main", "confidence": 0.9},
                {"timestamp": 2.5, "phase_code": "spin_exit", "confidence": 0.9},
            ]
            current_video_temporal = {
                "action_confirmation": {"action_family": "spin", "confidence": 0.91},
                "phase_segments": [
                    {"phase_code": "spin_entry", "time_start": 0.0, "time_end": 0.8, "confidence": 0.9},
                    {"phase_code": "spin_main", "time_start": 0.8, "time_end": 2.0, "confidence": 0.9},
                    {"phase_code": "spin_exit", "time_start": 2.0, "time_end": 3.0, "confidence": 0.9},
                ],
            }

            async with database.AsyncSessionLocal() as session:
                session.add(
                    models.Analysis(
                        id="prior-spin",
                        action_type=action_type,
                        action_subtype=action_subtype,
                        analysis_profile="spin",
                        pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
                        video_path=str(source_video),
                        status="completed",
                        frame_motion_scores={
                            "video_identity": {"sha256": video_hash},
                            "resolved_keyframes": {
                                "source": "video_ai_refined",
                                "confidence": 0.92,
                                "quality_flags": [],
                                "selected": selected,
                            },
                        },
                    )
                )
                await session.commit()

            semantic_paths = []
            semantic_records = []
            for index, record in enumerate(selected, start=1):
                path = Path(tmpdir) / f"semantic_{index:04d}.jpg"
                path.write_bytes(b"semantic")
                semantic_paths.append(path)
                semantic_records.append({**record, "frame_id": f"semantic_{index:04d}"})

            with patch(
                "app.routers.analysis.extract_precise_frames_at_timestamps",
                AsyncMock(return_value=(semantic_paths, semantic_records)),
            ):
                resolved, _frames, _records, video_temporal = await analysis_router._reuse_matching_semantic_keyframes(
                    analysis_id="current-spin",
                    video_path=source_video,
                    processing_frames_dir=Path(tmpdir) / "frames",
                    video_identity={"sha256": video_hash},
                    action_type=action_type,
                    action_subtype=action_subtype,
                    analysis_profile="spin",
                    motion_scores={"video_identity": {"sha256": video_hash}},
                    bio_data={"key_frame_candidates": {"quality_flags": ["keyframe_candidates_not_applicable_for_profile"]}},
                    video_temporal_result=current_video_temporal,
                )

        self.assertIsNotNone(resolved)
        self.assertIsInstance(video_temporal, dict)
        assert isinstance(video_temporal, dict)
        self.assertEqual(video_temporal["action_confirmation"]["action_family"], "spin")
        self.assertEqual(video_temporal["reused_semantic_keyframes_from_analysis_id"], "prior-spin")

    def test_semantic_reuse_candidate_rejects_old_pipeline_skeleton_or_unstable_flags(self) -> None:
        import app.routers.analysis as analysis_router

        selected = [
            {"timestamp": 4.5, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.9},
            {"timestamp": 5.1, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.9},
            {"timestamp": 5.45, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.9},
        ]
        identity = {"sha256": "abc"}
        base = SimpleNamespace(
            id="prior",
            status="completed",
            action_type="è·³è·ƒ",
            action_subtype="æœªæŒ‡å®š",
            analysis_profile="jump",
            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
            frame_motion_scores={
                "video_identity": identity,
                "resolved_keyframes": {
                    "source": "skeleton_fallback",
                    "confidence": 0.9,
                    "selected": selected,
                    "quality_flags": [],
                },
            },
        )

        self.assertIsNone(
            analysis_router._semantic_reuse_candidate_from_analysis(
                base,
                current_analysis_id="current",
                video_sha256="abc",
                action_type="è·³è·ƒ",
                action_subtype="æœªæŒ‡å®š",
                analysis_profile="jump",
                current_motion_scores={"video_identity": identity},
            )
        )

        base.frame_motion_scores["resolved_keyframes"]["source"] = "video_ai_refined"
        base.pipeline_version = "v5.2.57"
        self.assertIsNone(
            analysis_router._semantic_reuse_candidate_from_analysis(
                base,
                current_analysis_id="current",
                video_sha256="abc",
                action_type="è·³è·ƒ",
                action_subtype="æœªæŒ‡å®š",
                analysis_profile="jump",
                current_motion_scores={"video_identity": identity},
            )
        )

        base.pipeline_version = analysis_router.CURRENT_PIPELINE_VERSION
        base.frame_motion_scores["resolved_keyframes"]["quality_flags"] = [
            "semantic_keyframe_core_foreground_occlusion_repaired"
        ]
        self.assertIsNone(
            analysis_router._semantic_reuse_candidate_from_analysis(
                base,
                current_analysis_id="current",
                video_sha256="abc",
                action_type="è·³è·ƒ",
                action_subtype="æœªæŒ‡å®š",
                analysis_profile="jump",
                current_motion_scores={"video_identity": identity},
            )
        )

        base.frame_motion_scores["resolved_keyframes"]["quality_flags"] = [
            "video_temporal_resolver_motion_cluster_fallback_used",
            "video_temporal_resolver_weak_motion_cluster_fallback_used",
        ]
        self.assertIsNone(
            analysis_router._semantic_reuse_candidate_from_analysis(
                base,
                current_analysis_id="current",
                video_sha256="abc",
                action_type="Ã¨Â·Â³Ã¨Â·Æ’",
                action_subtype="Ã¦Å“ÂªÃ¦Å’â€¡Ã¥Â®Å¡",
                analysis_profile="jump",
                current_motion_scores={"video_identity": identity},
            )
        )

        base.frame_motion_scores["resolved_keyframes"]["quality_flags"] = []
        self.assertIsNotNone(
            analysis_router._semantic_reuse_candidate_from_analysis(
                base,
                current_analysis_id="current",
                video_sha256="abc",
                action_type="è·³è·ƒ",
                action_subtype="æœªæŒ‡å®š",
                analysis_profile="jump",
                current_motion_scores={"video_identity": identity},
            )
        )

    def test_semantic_reuse_candidate_accepts_spin_phase_keyframes(self) -> None:
        import app.routers.analysis as analysis_router

        identity = {"sha256": "spin-hash"}
        selected = [
            {"timestamp": 4.0, "phase_code": "spin_entry", "key_moment": None, "confidence": 0.86},
            {"timestamp": 5.2, "phase_code": "spin_main", "key_moment": None, "confidence": 0.88},
            {"timestamp": 6.5, "phase_code": "spin_exit", "key_moment": None, "confidence": 0.84},
        ]
        previous = SimpleNamespace(
            id="prior-spin",
            status="completed",
            action_type="free_skate",
            action_subtype="program",
            analysis_profile="spin",
            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
            frame_motion_scores={
                "video_identity": identity,
                "resolved_keyframes": {
                    "source": "blended",
                    "confidence": 0.85,
                    "selected": selected,
                    "quality_flags": ["video_temporal_resolver_coherent_profile_phases_used"],
                    "video_ai": {
                        "confidence": 0.85,
                        "quality_flags": ["video_temporal_quality_retry_used"],
                        "action_confirmation": {"action_family": "spin", "confidence": 0.9},
                    },
                },
            },
        )

        reuse = analysis_router._semantic_reuse_candidate_from_analysis(
            previous,
            current_analysis_id="current-spin",
            video_sha256="spin-hash",
            action_type="free_skate",
            action_subtype="program",
            analysis_profile="spin",
            current_motion_scores={"video_identity": identity},
        )

        self.assertIsNotNone(reuse)
        assert reuse is not None
        self.assertEqual(reuse["analysis_id"], "prior-spin")
        self.assertEqual([item["phase_code"] for item in reuse["selected"]], ["spin_entry", "spin_main", "spin_exit"])
        self.assertEqual([item["timestamp"] for item in reuse["selected"]], [4.0, 5.2, 6.5])

        previous.frame_motion_scores["resolved_keyframes"]["selected"] = selected[:2]
        self.assertIsNone(
            analysis_router._semantic_reuse_candidate_from_analysis(
                previous,
                current_analysis_id="current-spin",
                video_sha256="spin-hash",
                action_type="free_skate",
                action_subtype="program",
                analysis_profile="spin",
                current_motion_scores={"video_identity": identity},
            )
        )

    def test_semantic_reuse_candidate_accepts_step_sequence_coverage_frames(self) -> None:
        import app.routers.analysis as analysis_router

        identity = {"sha256": "step-hash"}
        selected = [
            {"timestamp": 1.74, "phase_code": "step_sequence", "key_moment": None, "confidence": 0.85},
            {"timestamp": 4.834, "phase_code": "step_sequence", "key_moment": None, "confidence": 0.86},
            {"timestamp": 7.928, "phase_code": "step_sequence", "key_moment": None, "confidence": 0.84},
        ]
        previous = SimpleNamespace(
            id="prior-step",
            status="completed",
            action_type="free_skate",
            action_subtype="program",
            analysis_profile="step",
            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
            frame_motion_scores={
                "video_identity": identity,
                "resolved_keyframes": {
                    "source": "video_ai_refined",
                    "confidence": 0.85,
                    "selected": selected,
                    "quality_flags": [
                        "video_temporal_resolver_coherent_profile_phases_used",
                        "video_temporal_resolver_step_sequence_multi_frame_coverage",
                    ],
                },
            },
        )

        reuse = analysis_router._semantic_reuse_candidate_from_analysis(
            previous,
            current_analysis_id="current-step",
            video_sha256="step-hash",
            action_type="free_skate",
            action_subtype="program",
            analysis_profile="step",
            current_motion_scores={"video_identity": identity},
        )

        self.assertIsNotNone(reuse)
        assert reuse is not None
        self.assertEqual([item["phase_code"] for item in reuse["selected"]], ["step_sequence"] * 3)
        self.assertEqual([item["timestamp"] for item in reuse["selected"]], [1.74, 4.834, 7.928])

    def test_semantic_reuse_candidate_accepts_visual_promotion_source_flags(self) -> None:
        import app.routers.analysis as analysis_router

        identity = {"sha256": "abc"}
        selected = [
            {"timestamp": 8.1, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.74},
            {"timestamp": 8.5, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.76},
            {"timestamp": 8.767, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.75},
        ]
        previous = SimpleNamespace(
            id="prior-promoted",
            status="completed",
            action_type="jump",
            action_subtype="single",
            analysis_profile="jump",
            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
            frame_motion_scores={
                "video_identity": identity,
                "resolved_keyframes": {
                    "source": "blended",
                    "confidence": 0.74,
                    "quality_flags": [
                        "semantic_keyframes_distant_full_context_visual_tal_promoted",
                        "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                        "semantic_keyframes_unreliable_tracker_final_loss_motion_fallback",
                        "semantic_keyframes_unreliable_tracker_final_loss_outside_reliable_pose",
                        "semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates",
                    ],
                    "selected": selected,
                    "video_ai": {
                        "confidence": 0.74,
                        "quality_flags": [
                            "video_temporal_resolver_distant_full_context_visual_tal_promoted",
                            "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
                        ],
                    },
                },
            },
        )

        reuse = analysis_router._semantic_reuse_candidate_from_analysis(
            previous,
            current_analysis_id="current",
            video_sha256="abc",
            action_type="jump",
            action_subtype="single",
            analysis_profile="jump",
            current_motion_scores={"video_identity": identity},
            current_bio_data={
                "quality_flags": [
                    "person_tracker_target_lost",
                    "person_tracker_final_unrecovered",
                ],
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_motion_fallback",
                        "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                        "tal_candidate_incomplete",
                        "tal_candidate_motion_fallback_low_precision",
                        "tal_order_unresolved",
                    ],
                    "motion_fallback_time_bounds": {"start_timestamp": 2.9, "end_timestamp": 3.4},
                    "T": {
                        "timestamp": 3.188,
                        "confidence": 0.52,
                        "warnings": ["keyframe_candidates_motion_fallback"],
                        "evidence": {"motion_fallback": True, "visibility_score": 0.0},
                    },
                    "A": {
                        "timestamp": 3.25,
                        "confidence": 0.51,
                        "warnings": ["keyframe_candidates_motion_fallback"],
                        "evidence": {"motion_fallback": True, "visibility_score": 0.0},
                    },
                    "L": {
                        "timestamp": 3.312,
                        "confidence": 0.51,
                        "warnings": ["keyframe_candidates_motion_fallback"],
                        "evidence": {"motion_fallback": True, "visibility_score": 0.0},
                    },
                },
            },
        )

        self.assertIsNotNone(reuse)
        assert reuse is not None
        self.assertEqual([item["timestamp"] for item in reuse["selected"]], [8.1, 8.5, 8.767])
        self.assertIn("semantic_keyframes_distant_full_context_visual_tal_promoted", reuse["source_quality_flags"])
        self.assertIn("semantic_keyframes_unreliable_fallback_to_sampled_frames", reuse["source_quality_flags"])

    def test_semantic_reuse_candidate_revalidates_against_current_tracker_final_loss_candidates(self) -> None:
        import app.routers.analysis as analysis_router

        identity = {"sha256": "abc"}
        selected = [
            {"timestamp": 3.553, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.65},
            {"timestamp": 3.8, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.6},
            {"timestamp": 4.1, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.65},
        ]
        previous = SimpleNamespace(
            id="prior",
            status="completed",
            action_type="Ã¨Â·Â³Ã¨Â·Æ’",
            action_subtype="Ã¦Å“ÂªÃ¦Å’â€¡Ã¥Â®Å¡",
            analysis_profile="jump",
            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
            frame_motion_scores={
                "video_identity": identity,
                "resolved_keyframes": {
                    "source": "blended",
                    "confidence": 0.65,
                    "quality_flags": [],
                    "selected": selected,
                },
            },
        )
        current_bio_data = {
            "quality_flags": [
                "person_tracker_target_lost",
                "person_tracker_relock_rejected",
                "person_tracker_final_unrecovered",
            ],
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_motion_fallback",
                    "tal_candidate_motion_fallback_low_precision",
                    "tal_candidate_incomplete",
                    "tal_order_unresolved",
                    "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                ],
                "motion_fallback_time_bounds": {"start_timestamp": 0.0, "end_timestamp": 4.1},
                "T": {"frame_id": "frame_0012", "timestamp": 2.875, "confidence": 0.54, "warnings": ["keyframe_candidates_motion_fallback"]},
                "A": {"frame_id": "frame_0013", "timestamp": 2.938, "confidence": 0.54, "warnings": ["keyframe_candidates_motion_fallback"]},
                "L": {"frame_id": "frame_0014", "timestamp": 3.0, "confidence": 0.504, "warnings": ["keyframe_candidates_motion_fallback"]},
            },
        }

        self.assertIsNone(
            analysis_router._semantic_reuse_candidate_from_analysis(
                previous,
                current_analysis_id="current",
                video_sha256="abc",
                action_type="Ã¨Â·Â³Ã¨Â·Æ’",
                action_subtype="Ã¦Å“ÂªÃ¦Å’â€¡Ã¥Â®Å¡",
                analysis_profile="jump",
                current_motion_scores={"video_identity": identity},
                current_bio_data=current_bio_data,
            )
        )

    def test_semantic_reuse_candidate_accepts_over_long_unresolved_motion_fallback(self) -> None:
        import app.routers.analysis as analysis_router

        identity = {"sha256": "43012-sha"}
        selected = [
            {"timestamp": 5.953, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.5},
            {"timestamp": 6.8, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.5},
            {"timestamp": 7.134, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.5},
        ]
        previous = SimpleNamespace(
            id="prior-stable-43012",
            status="completed",
            action_type="jump",
            action_subtype="single",
            analysis_profile="jump",
            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
            frame_motion_scores={
                "video_identity": identity,
                "resolved_keyframes": {
                    "source": "blended",
                    "confidence": 0.6,
                    "quality_flags": [
                        "video_temporal_resolver_coherent_tal_used",
                        "semantic_keyframe_core_foreground_occlusion_repaired",
                        "video_temporal_quality_retry_rejected",
                    ],
                    "selected": selected,
                    "video_ai": {
                        "confidence": 0.6,
                        "quality_flags": [
                            "video_temporal_not_high_confidence",
                            "video_temporal_fallback_recommended",
                        ],
                    },
                },
            },
        )
        current_bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "keyframe_candidates_tail_motion_window_rejected",
                    "tal_candidate_incomplete",
                    "tal_order_unresolved",
                    "keyframe_candidates_motion_fallback",
                    "tal_candidate_motion_fallback_low_precision",
                    "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                    "keyframe_candidates_motion_fallback_filtered_unreliable_pose_records",
                ],
                "T": {
                    "frame_id": "frame_0008",
                    "timestamp": 1.375,
                    "confidence": 0.497,
                    "warnings": ["keyframe_candidates_motion_fallback", "t_pose_signal_insufficient"],
                    "evidence": {"motion_fallback": True, "visibility_score": 0.0},
                },
                "A": {
                    "frame_id": "frame_0016",
                    "timestamp": 4.375,
                    "confidence": 0.473,
                    "warnings": ["keyframe_candidates_motion_fallback", "a_pose_signal_insufficient"],
                    "evidence": {"motion_fallback": True, "visibility_score": 0.0},
                },
                "L": {
                    "frame_id": "frame_0032",
                    "timestamp": 7.688,
                    "confidence": 0.534,
                    "warnings": ["keyframe_candidates_motion_fallback", "l_pose_signal_insufficient"],
                    "evidence": {"motion_fallback": True, "visibility_score": 0.0},
                },
            },
        }

        reuse = analysis_router._semantic_reuse_candidate_from_analysis(
            previous,
            current_analysis_id="current",
            video_sha256="43012-sha",
            action_type="jump",
            action_subtype="single",
            analysis_profile="jump",
            current_motion_scores={
                "video_identity": identity,
                "selected": [
                    {"frame_id": "frame_0008", "timestamp": 1.375, "motion_score": 0.0624},
                    {"frame_id": "frame_0016", "timestamp": 4.375, "motion_score": 0.0502},
                    {"frame_id": "frame_0032", "timestamp": 7.688, "motion_score": 0.0814},
                ],
            },
            current_bio_data=current_bio_data,
        )

        self.assertIsNotNone(reuse)
        assert reuse is not None
        self.assertEqual([item["timestamp"] for item in reuse["selected"]], [5.953, 6.8, 7.134])
        self.assertTrue(reuse["long_unresolved_motion_fallback_override"])
        self.assertEqual(reuse["candidate_max_abs_delta_sec"], 4.578)
        self.assertIn("video_temporal_quality_retry_rejected", reuse["source_quality_flags"])

    def test_semantic_reuse_candidate_accepts_degraded_semantic_low_visibility_source(self) -> None:
        import app.routers.analysis as analysis_router

        identity = {"sha256": "6c4a-sha"}
        candidate_quality_flags = [
            "keyframe_candidates_excluded_unreliable_pose_frames",
            "tal_candidate_incomplete",
            "tal_order_unresolved",
            "keyframe_candidates_motion_fallback",
            "tal_candidate_motion_fallback_low_precision",
            "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
            "keyframe_candidates_motion_fallback_filtered_unreliable_pose_records",
            "keyframe_candidates_motion_fallback_tiny_target_full_frame_motion_risk",
            "tal_candidate_motion_fallback_foreground_motion_risk",
        ]
        selected = [
            {
                "timestamp": 2.753,
                "phase_code": "takeoff",
                "key_moment": "T_takeoff_sec",
                "selection_reason": "video_phase_range_key_moment",
                "confidence": 0.8,
            },
            {
                "timestamp": 3.0,
                "phase_code": "air",
                "key_moment": "A_air_sec",
                "selection_reason": "video_phase_range_key_moment",
                "confidence": 0.8,
            },
            {
                "timestamp": 3.667,
                "phase_code": "landing",
                "key_moment": "L_landing_sec",
                "selection_reason": "video_phase_range_key_moment",
                "confidence": 0.8,
            },
        ]
        previous = SimpleNamespace(
            id="prior-degraded-semantic",
            status="completed",
            action_type="jump",
            action_subtype="single",
            analysis_profile="jump",
            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
            bio_data={
                "key_frame_timestamps": {"T": 2.753, "A": 3.0, "L": 3.667},
                "quality_flags": [
                    "bio_key_frames_synced_from_resolved_keyframes",
                    "bio_key_frames_synced_from_degraded_semantic_keyframes",
                    "bio_key_frames_degraded_semantic_unreliable_resolved_keyframes",
                ],
            },
            frame_motion_scores={
                "video_identity": identity,
                "resolved_keyframes": {
                    "source": "blended",
                    "confidence": 0.8,
                    "quality_flags": [
                        "semantic_keyframes_candidate_motion_window_conflict_ignored_insufficient_pose_low_visibility_fallback",
                        "semantic_keyframes_unreliable_tracker_final_loss_weak_semantic_motion",
                        "semantic_keyframes_unreliable_after_refinement",
                        "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                        "video_temporal_quality_retry_rejected",
                    ],
                    "selected": selected,
                    "semantic_candidate_tal_conflict": {
                        "conflicts": [],
                        "candidate_quality_flags": candidate_quality_flags,
                        "low_visibility_motion_fallback_keys": ["A", "L", "T"],
                        "decision": "ignored_insufficient_pose_low_visibility_motion_fallback_candidate",
                    },
                    "video_ai": {"confidence": 0.8, "quality_flags": []},
                },
            },
        )
        low_visibility_evidence = {
            "motion_fallback": True,
            "visibility_score": 0.0,
            "score_components": {"pose_visibility": 0.0},
        }
        current_bio_data = {
            "key_frame_candidates": {
                "quality_flags": candidate_quality_flags,
                "T": {
                    "timestamp": 0.062,
                    "confidence": 0.477,
                    "warnings": ["keyframe_candidates_motion_fallback", "t_pose_signal_insufficient"],
                    "evidence": low_visibility_evidence,
                },
                "A": {
                    "timestamp": 0.438,
                    "confidence": 0.463,
                    "warnings": ["keyframe_candidates_motion_fallback", "a_pose_signal_insufficient"],
                    "evidence": low_visibility_evidence,
                },
                "L": {
                    "timestamp": 1.062,
                    "confidence": 0.444,
                    "warnings": ["keyframe_candidates_motion_fallback", "l_pose_signal_insufficient"],
                    "evidence": low_visibility_evidence,
                },
            },
        }

        reuse = analysis_router._semantic_reuse_candidate_from_analysis(
            previous,
            current_analysis_id="current",
            video_sha256="6c4a-sha",
            action_type="jump",
            action_subtype="single",
            analysis_profile="jump",
            current_motion_scores={"video_identity": identity},
            current_bio_data=current_bio_data,
        )

        self.assertIsNotNone(reuse)
        assert reuse is not None
        self.assertEqual([item["timestamp"] for item in reuse["selected"]], [2.753, 3.0, 3.667])
        self.assertTrue(reuse["insufficient_pose_low_visibility_source_override"])
        self.assertTrue(reuse["degraded_semantic_low_visibility_source_override"])
        self.assertIn("semantic_keyframes_unreliable_after_refinement", reuse["source_quality_flags"])

    def test_semantic_reuse_candidate_accepts_degraded_low_confidence_bio_synced_source(self) -> None:
        import app.routers.analysis as analysis_router

        identity = {"sha256": "6c4a-sha"}
        candidate_quality_flags = [
            "keyframe_candidates_excluded_unreliable_pose_frames",
            "tal_candidate_incomplete",
            "tal_order_unresolved",
            "keyframe_candidates_motion_fallback",
            "tal_candidate_motion_fallback_low_precision",
            "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
            "keyframe_candidates_motion_fallback_filtered_unreliable_pose_records",
            "keyframe_candidates_motion_fallback_tiny_target_full_frame_motion_risk",
            "tal_candidate_motion_fallback_foreground_motion_risk",
        ]
        selected = [
            {
                "timestamp": 3.053,
                "phase_code": "takeoff",
                "key_moment": "T_takeoff_sec",
                "selection_reason": "video_phase_range_key_moment",
                "confidence": 0.5,
            },
            {
                "timestamp": 3.4,
                "phase_code": "air",
                "key_moment": "A_air_sec",
                "selection_reason": "video_phase_range_key_moment",
                "confidence": 0.5,
            },
            {
                "timestamp": 4.167,
                "phase_code": "landing",
                "key_moment": "L_landing_sec",
                "selection_reason": "video_phase_range_key_moment",
                "confidence": 0.6,
            },
        ]
        previous = SimpleNamespace(
            id="prior-degraded-low-confidence",
            status="completed",
            action_type="jump",
            action_subtype="single",
            analysis_profile="jump",
            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
            bio_data={
                "key_frame_timestamps": {"T": 3.053, "A": 3.4, "L": 4.167},
                "quality_flags": [
                    "bio_key_frames_synced_from_resolved_keyframes",
                    "bio_key_frames_synced_from_degraded_semantic_keyframes",
                    "bio_key_frames_degraded_semantic_unreliable_resolved_keyframes",
                ],
            },
            frame_motion_scores={
                "video_identity": identity,
                "resolved_keyframes": {
                    "source": "blended",
                    "confidence": 0.6,
                    "quality_flags": [
                        "video_temporal_resolver_skeleton_t_below_anchor_confidence",
                        "video_temporal_resolver_skeleton_a_below_anchor_confidence",
                        "video_temporal_resolver_skeleton_l_below_anchor_confidence",
                        "video_temporal_resolver_coherent_tal_used",
                        "video_temporal_resolver_moderate_confidence_tal_used",
                        "semantic_keyframes_candidate_motion_window_conflict_ignored_insufficient_pose_low_visibility_fallback",
                        "semantic_keyframes_unreliable_tracker_final_loss_weak_semantic_motion",
                        "semantic_keyframes_unreliable_after_refinement",
                        "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                        "semantic_keyframes_partial_core_frames_available",
                        "video_temporal_quality_retry_rejected",
                    ],
                    "selected": selected,
                    "semantic_candidate_tal_conflict": {
                        "conflicts": [],
                        "candidate_quality_flags": candidate_quality_flags,
                        "low_visibility_motion_fallback_keys": ["A", "L", "T"],
                        "decision": "ignored_insufficient_pose_low_visibility_motion_fallback_candidate",
                    },
                    "video_ai": {
                        "confidence": 0.6,
                        "quality_flags": ["distance_too_far", "low_resolution"],
                    },
                },
            },
        )
        low_visibility_evidence = {
            "motion_fallback": True,
            "visibility_score": 0.0,
            "score_components": {"pose_visibility": 0.0},
        }
        current_bio_data = {
            "key_frame_candidates": {
                "quality_flags": candidate_quality_flags,
                "T": {
                    "timestamp": 0.062,
                    "confidence": 0.477,
                    "warnings": ["keyframe_candidates_motion_fallback", "t_pose_signal_insufficient"],
                    "evidence": low_visibility_evidence,
                },
                "A": {
                    "timestamp": 0.438,
                    "confidence": 0.463,
                    "warnings": ["keyframe_candidates_motion_fallback", "a_pose_signal_insufficient"],
                    "evidence": low_visibility_evidence,
                },
                "L": {
                    "timestamp": 1.062,
                    "confidence": 0.444,
                    "warnings": ["keyframe_candidates_motion_fallback", "l_pose_signal_insufficient"],
                    "evidence": low_visibility_evidence,
                },
            },
        }

        reuse = analysis_router._semantic_reuse_candidate_from_analysis(
            previous,
            current_analysis_id="current",
            video_sha256="6c4a-sha",
            action_type="jump",
            action_subtype="single",
            analysis_profile="jump",
            current_motion_scores={"video_identity": identity},
            current_bio_data=current_bio_data,
        )

        self.assertIsNotNone(reuse)
        assert reuse is not None
        self.assertEqual(reuse["analysis_id"], "prior-degraded-low-confidence")
        self.assertEqual([item["timestamp"] for item in reuse["selected"]], [3.053, 3.4, 4.167])
        self.assertFalse(reuse["insufficient_pose_low_visibility_source_override"])
        self.assertTrue(reuse["degraded_semantic_low_visibility_source_override"])
        self.assertEqual(reuse["candidate_supported_key_count"], 0)

    def test_semantic_reuse_candidate_accepts_clean_video_tal_over_late_weak_candidate(self) -> None:
        import app.routers.analysis as analysis_router

        identity = {"sha256": "4d798-sha"}
        selected = [
            {
                "timestamp": 2.187,
                "phase_code": "takeoff",
                "key_moment": "T_takeoff_sec",
                "selection_reason": "video_phase_range_key_moment",
                "confidence": 0.9,
            },
            {
                "timestamp": 2.4,
                "phase_code": "air",
                "key_moment": "A_air_sec",
                "selection_reason": "video_phase_range_key_moment",
                "confidence": 0.9,
            },
            {
                "timestamp": 2.6,
                "phase_code": "landing",
                "key_moment": "L_landing_sec",
                "selection_reason": "video_phase_range_key_moment",
                "confidence": 0.9,
            },
        ]
        previous = SimpleNamespace(
            id="prior-clean-video-tal",
            status="completed",
            action_type="jump",
            action_subtype="single",
            analysis_profile="jump",
            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
            frame_motion_scores={
                "video_identity": identity,
                "resolved_keyframes": {
                    "source": "video_ai_refined",
                    "confidence": 0.9,
                    "quality_flags": [
                        "semantic_keyframe_refinement_delta_rejected",
                        "semantic_keyframes_unreliable_candidate_tal_conflict",
                        "semantic_keyframes_unreliable_after_refinement",
                        "video_temporal_quality_retry_rejected",
                        "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                    ],
                    "selected": selected,
                    "video_ai": {
                        "valid": True,
                        "confidence": 0.9,
                        "fallback_recommendation": "use_video_timestamps",
                        "quality_flags": [],
                        "action_confirmation": {"action_family": "jump", "confidence": 0.9},
                    },
                },
            },
        )
        current_bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_late_pose_core_reselected",
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "tal_candidate_temporal_geometry_unreliable",
                    "tal_candidate_apex_landing_gap_unreliable",
                    "tal_candidate_apex_landing_gap_compressed",
                ],
                "T": {"timestamp": 4.188, "confidence": 0.34, "warnings": ["tal_candidate_late_pose_core_reselected"]},
                "A": {"timestamp": 4.812, "confidence": 0.34, "warnings": ["tal_candidate_late_pose_core_reselected"]},
                "L": {"timestamp": 4.875, "confidence": 0.34, "warnings": ["tal_candidate_late_pose_core_reselected"]},
            },
        }

        reuse = analysis_router._semantic_reuse_candidate_from_analysis(
            previous,
            current_analysis_id="current",
            video_sha256="4d798-sha",
            action_type="jump",
            action_subtype="single",
            analysis_profile="jump",
            current_motion_scores={"video_identity": identity},
            current_bio_data=current_bio_data,
        )

        self.assertIsNotNone(reuse)
        assert reuse is not None
        self.assertTrue(reuse["clean_video_tal_late_weak_candidate_source_override"])
        self.assertEqual([item["timestamp"] for item in reuse["selected"]], [2.187, 2.4, 2.6])
        self.assertIn("semantic_keyframes_unreliable_after_refinement", reuse["source_quality_flags"])

    def test_semantic_reuse_candidate_rejects_invalid_fallback_video_tal_for_late_weak_candidate(self) -> None:
        import app.routers.analysis as analysis_router

        identity = {"sha256": "4d798-sha"}
        previous = SimpleNamespace(
            id="prior-invalid-video-tal",
            status="completed",
            action_type="jump",
            action_subtype="single",
            analysis_profile="jump",
            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
            frame_motion_scores={
                "video_identity": identity,
                "resolved_keyframes": {
                    "source": "blended",
                    "confidence": 0.9,
                    "quality_flags": [
                        "semantic_keyframes_unreliable_candidate_tal_conflict",
                        "semantic_keyframes_unreliable_after_refinement",
                        "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                        "video_temporal_quality_retry_rejected",
                    ],
                    "selected": [
                        {"timestamp": 2.753, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "selection_reason": "video_phase_range_key_moment", "confidence": 0.9},
                        {"timestamp": 3.1, "phase_code": "air", "key_moment": "A_air_sec", "selection_reason": "video_phase_range_key_moment", "confidence": 0.9},
                        {"timestamp": 3.767, "phase_code": "landing", "key_moment": "L_landing_sec", "selection_reason": "video_phase_range_key_moment", "confidence": 0.9},
                    ],
                    "video_ai": {
                        "valid": False,
                        "confidence": 0.9,
                        "fallback_recommendation": "use_sampled_frames",
                        "quality_flags": ["video_temporal_fallback_recommended"],
                        "action_confirmation": {"action_family": "jump", "confidence": 0.9},
                    },
                },
            },
        )
        current_bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_late_pose_core_reselected",
                    "tal_candidate_temporal_geometry_unreliable",
                ],
                "T": {"timestamp": 4.188, "confidence": 0.34},
                "A": {"timestamp": 4.812, "confidence": 0.34},
                "L": {"timestamp": 4.875, "confidence": 0.34},
            },
        }

        reuse = analysis_router._semantic_reuse_candidate_from_analysis(
            previous,
            current_analysis_id="current",
            video_sha256="4d798-sha",
            action_type="jump",
            action_subtype="single",
            analysis_profile="jump",
            current_motion_scores={"video_identity": identity},
            current_bio_data=current_bio_data,
        )

        self.assertIsNone(reuse)

    def test_semantic_reuse_candidate_accepts_repaired_occlusion_with_current_pose_support(self) -> None:
        import app.routers.analysis as analysis_router

        identity = {"sha256": "abc"}
        previous = SimpleNamespace(
            id="prior-repaired-occlusion",
            status="completed",
            action_type="jump",
            action_subtype="single",
            analysis_profile="jump",
            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
            frame_motion_scores={
                "video_identity": identity,
                "resolved_keyframes": {
                    "source": "video_ai_refined",
                    "confidence": 0.9,
                    "quality_flags": [
                        "semantic_keyframe_core_foreground_occlusion_repaired",
                        "video_temporal_quality_retry_skeleton_tal_conflict",
                        "video_temporal_quality_retry_rejected",
                    ],
                    "selected": [
                        {
                            "timestamp": 3.841,
                            "phase_code": "takeoff",
                            "key_moment": "T_takeoff_sec",
                            "selection_reason": "video_phase_range_skeleton_takeoff_anchor",
                            "confidence": 0.85,
                        },
                        {
                            "timestamp": 4.1,
                            "phase_code": "air",
                            "key_moment": "A_air_sec",
                            "selection_reason": "video_phase_range_key_moment",
                            "confidence": 0.8,
                        },
                        {
                            "timestamp": 4.5,
                            "phase_code": "landing",
                            "key_moment": "L_landing_sec",
                            "selection_reason": "video_phase_range_key_moment",
                            "confidence": 0.85,
                        },
                    ],
                },
            },
        )
        current_bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "tal_candidate_takeoff_geometry_weak",
                    "tal_candidate_landing_geometry_weak",
                    "tal_candidate_weak_geometry",
                ],
                "T": {
                    "timestamp": 3.688,
                    "confidence": 0.652,
                    "warnings": ["takeoff_geometry_weak"],
                    "evidence": {"score_components": {"pose_visibility": 0.527, "com_ascent": 1.0}},
                },
                "A": {
                    "timestamp": 3.75,
                    "confidence": 0.389,
                    "warnings": ["apex_local_minimum_not_clear"],
                    "evidence": {"score_components": {"pose_visibility": 0.571}},
                },
                "L": {
                    "timestamp": 3.938,
                    "confidence": 0.35,
                    "warnings": ["landing_geometry_weak"],
                    "evidence": {"score_components": {"pose_visibility": 0.837}},
                },
            }
        }

        reuse = analysis_router._semantic_reuse_candidate_from_analysis(
            previous,
            current_analysis_id="current",
            video_sha256="abc",
            action_type="jump",
            action_subtype="single",
            analysis_profile="jump",
            current_motion_scores={"video_identity": identity},
            current_bio_data=current_bio_data,
        )

        self.assertIsNotNone(reuse)
        assert reuse is not None
        self.assertTrue(reuse["foreground_occlusion_repaired_source_override"])
        self.assertEqual(reuse["analysis_id"], "prior-repaired-occlusion")
        self.assertLessEqual(reuse["candidate_supported_max_abs_delta_sec"], 0.75)

    def test_semantic_reuse_candidate_keeps_reuse_through_weak_temporal_geometry_conflict(self) -> None:
        import app.routers.analysis as analysis_router

        identity = {"sha256": "abc"}
        previous = SimpleNamespace(
            id="prior",
            status="completed",
            action_type="jump",
            action_subtype="single",
            analysis_profile="jump",
            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
            frame_motion_scores={
                "video_identity": identity,
                "resolved_keyframes": {
                    "source": "blended",
                    "confidence": 0.88,
                    "quality_flags": [],
                    "selected": [
                        {"timestamp": 4.4, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.88},
                        {"timestamp": 4.75, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.88},
                        {"timestamp": 5.25, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.88},
                    ],
                },
            },
        )
        current_bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "tal_candidate_temporal_geometry_unreliable",
                    "tal_candidate_takeoff_apex_gap_unreliable",
                ],
                "T": {"frame_id": "frame_0017", "timestamp": 6.375, "confidence": 0.545},
                "A": {"frame_id": "frame_0025", "timestamp": 8.188, "confidence": 0.579},
                "L": {"frame_id": "frame_0026", "timestamp": 8.25, "confidence": 0.701},
            }
        }

        reuse = analysis_router._semantic_reuse_candidate_from_analysis(
            previous,
            current_analysis_id="current",
            video_sha256="abc",
            action_type="jump",
            action_subtype="single",
            analysis_profile="jump",
            current_motion_scores={"video_identity": identity},
            current_bio_data=current_bio_data,
        )

        self.assertIsNotNone(reuse)
        assert reuse is not None
        self.assertEqual([item["timestamp"] for item in reuse["selected"]], [4.4, 4.75, 5.25])

    def test_semantic_reuse_candidate_rejects_phase_range_weak_geometry_without_core_motion_support(self) -> None:
        import app.routers.analysis as analysis_router

        identity = {"sha256": "43007-sha"}
        selected = [
            {
                "frame_id": "semantic_0001",
                "timestamp": 4.887,
                "phase_code": "takeoff",
                "key_moment": "T_takeoff_sec",
                "selection_reason": "video_phase_range_key_moment",
                "confidence": 0.75,
            },
            {
                "frame_id": "semantic_0002",
                "timestamp": 5.3,
                "phase_code": "air",
                "key_moment": "A_air_sec",
                "selection_reason": "video_phase_range_key_moment",
                "confidence": 0.7,
            },
            {
                "frame_id": "semantic_0003",
                "timestamp": 5.6,
                "phase_code": "landing",
                "key_moment": "L_landing_sec",
                "selection_reason": "video_phase_range_key_moment",
                "confidence": 0.75,
            },
            {
                "frame_id": "semantic_0004",
                "timestamp": 4.5,
                "phase_code": "preparation",
                "selection_reason": "video_phase_range_key_hint",
                "confidence": 0.8,
            },
        ]
        previous = SimpleNamespace(
            id="prior-43007",
            status="completed",
            action_type="jump",
            action_subtype="single",
            analysis_profile="jump",
            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
            frame_motion_scores={
                "video_identity": identity,
                "resolved_keyframes": {
                    "source": "blended",
                    "confidence": 0.75,
                    "quality_flags": [
                        "video_temporal_resolver_coherent_tal_used",
                        "semantic_keyframe_refinement_phase_rejected",
                        "semantic_keyframe_refinement_rejection_ignored_weak_temporal_geometry",
                        "semantic_keyframes_candidate_tal_conflict_ignored_weak_temporal_geometry",
                        "video_temporal_quality_retry_motion_cluster_conflict",
                        "semantic_keyframes_unreliable_after_refinement",
                        "video_temporal_quality_retry_rejected",
                        "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                    ],
                    "selected": selected,
                    "video_ai": {
                        "confidence": 0.75,
                        "action_confirmation": {
                            "action_family": "jump",
                            "confidence": 0.8,
                        },
                        "quality_flags": [
                            "video_temporal_not_high_confidence",
                            "video_temporal_phase_5_end_clamped_to_duration",
                        ],
                    },
                },
            },
        )
        current_bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "tal_candidate_landing_geometry_weak",
                    "tal_candidate_temporal_geometry_unreliable",
                    "tal_candidate_takeoff_apex_gap_unreliable",
                    "tal_candidate_apex_landing_gap_unreliable",
                    "tal_candidate_apex_landing_gap_compressed",
                    "tal_candidate_confidence_low",
                ],
                "T": {
                    "frame_id": "frame_0027",
                    "timestamp": 5.875,
                    "confidence": 0.34,
                    "warnings": [
                        "knee_extension_weak",
                        "takeoff_timing_window_weak",
                        "tal_candidate_temporal_geometry_unreliable",
                        "tal_candidate_compressed_temporal_geometry",
                    ],
                    "evidence": {
                        "motion_cluster_window": {
                            "start_timestamp": 3.938,
                            "end_timestamp": 7.75,
                        }
                    },
                },
                "A": {
                    "frame_id": "frame_0031",
                    "timestamp": 7.688,
                    "confidence": 0.34,
                    "warnings": [
                        "apex_local_minimum_not_clear",
                        "tal_candidate_temporal_geometry_unreliable",
                        "tal_candidate_compressed_temporal_geometry",
                    ],
                    "evidence": {
                        "motion_cluster_window": {
                            "start_timestamp": 3.938,
                            "end_timestamp": 7.75,
                        }
                    },
                },
                "L": {
                    "frame_id": "frame_0032",
                    "timestamp": 7.75,
                    "confidence": 0.34,
                    "warnings": [
                        "landing_geometry_weak",
                        "tal_candidate_temporal_geometry_unreliable",
                        "tal_candidate_compressed_temporal_geometry",
                    ],
                    "evidence": {
                        "motion_cluster_window": {
                            "start_timestamp": 3.938,
                            "end_timestamp": 7.75,
                        }
                    },
                },
            }
        }
        current_motion_scores = {
            "video_identity": identity,
            "selected": [
                {"frame_id": "frame_0017", "timestamp": 3.562, "motion_score": 0.1279},
                {"frame_id": "frame_0018", "timestamp": 3.625, "motion_score": 0.1510},
                {"frame_id": "frame_0019", "timestamp": 3.688, "motion_score": 0.1760},
                {"frame_id": "frame_0020", "timestamp": 3.750, "motion_score": 0.1799},
                {"frame_id": "frame_0021", "timestamp": 3.812, "motion_score": 0.1271},
                {"frame_id": "semantic_t", "timestamp": 4.887, "motion_score": 0.0262},
                {"frame_id": "semantic_a", "timestamp": 5.300, "motion_score": 0.0476},
                {"frame_id": "semantic_l", "timestamp": 5.600, "motion_score": 0.0275},
                {"frame_id": "frame_0032", "timestamp": 7.750, "motion_score": 0.0716},
            ],
        }

        reuse = analysis_router._semantic_reuse_candidate_from_analysis(
            previous,
            current_analysis_id="current",
            video_sha256="43007-sha",
            action_type="jump",
            action_subtype="single",
            analysis_profile="jump",
            current_motion_scores=current_motion_scores,
            current_bio_data=current_bio_data,
        )

        self.assertIsNone(reuse)

    async def test_matching_semantic_reuse_demotes_phase_range_weak_geometry_when_current_pose_supported_source_exists(self) -> None:
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

            database.ensure_storage_dirs()
            await database.init_db()

            identity = {"sha256": "43007-sha"}
            now = datetime(2026, 6, 5, tzinfo=timezone.utc)

            def selected(
                t: float,
                a: float,
                l: float,
                *,
                reason: str = "semantic_refined",
                confidence: float = 0.82,
            ) -> list[dict[str, object]]:
                return [
                    {
                        "timestamp": t,
                        "phase_code": "takeoff",
                        "key_moment": "T_takeoff_sec",
                        "selection_reason": reason,
                        "confidence": confidence,
                    },
                    {
                        "timestamp": a,
                        "phase_code": "air",
                        "key_moment": "A_air_sec",
                        "selection_reason": reason,
                        "confidence": confidence,
                    },
                    {
                        "timestamp": l,
                        "phase_code": "landing",
                        "key_moment": "L_landing_sec",
                        "selection_reason": reason,
                        "confidence": confidence,
                    },
                ]

            async with database.AsyncSessionLocal() as session:
                session.add_all(
                    [
                        models.Analysis(
                            id="historical-phase-range-weak",
                            action_type="jump",
                            action_subtype="single",
                            analysis_profile="jump",
                            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
                            video_path="/tmp/43007.mp4",
                            status="completed",
                            created_at=now - timedelta(minutes=20),
                            frame_motion_scores={
                                "video_identity": identity,
                                "selected": [
                                    {"frame_id": "frame_0019", "timestamp": 3.688, "motion_score": 0.1760},
                                    {"frame_id": "frame_0020", "timestamp": 3.750, "motion_score": 0.1799},
                                    {"frame_id": "semantic_t", "timestamp": 4.887, "motion_score": 0.0262},
                                    {"frame_id": "semantic_a", "timestamp": 5.300, "motion_score": 0.0476},
                                    {"frame_id": "semantic_l", "timestamp": 5.600, "motion_score": 0.0275},
                                    {"frame_id": "frame_0032", "timestamp": 7.750, "motion_score": 0.0716},
                                ],
                                "resolved_keyframes": {
                                    "source": "blended",
                                    "confidence": 0.75,
                                    "quality_flags": [
                                        "video_temporal_resolver_coherent_tal_used",
                                        "semantic_keyframe_refinement_phase_rejected",
                                        "semantic_keyframe_refinement_rejection_ignored_weak_temporal_geometry",
                                        "semantic_keyframes_candidate_tal_conflict_ignored_weak_temporal_geometry",
                                        "video_temporal_quality_retry_motion_cluster_conflict",
                                        "semantic_keyframes_unreliable_after_refinement",
                                        "video_temporal_quality_retry_rejected",
                                        "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                                    ],
                                    "selected": selected(
                                        4.887,
                                        5.3,
                                        5.6,
                                        reason="video_phase_range_key_moment",
                                        confidence=0.75,
                                    ),
                                    "video_ai": {
                                        "confidence": 0.75,
                                        "action_confirmation": {"action_family": "jump", "confidence": 0.8},
                                        "quality_flags": ["video_temporal_not_high_confidence"],
                                    },
                                },
                            },
                        ),
                        models.Analysis(
                            id="pose-supported-current-source",
                            action_type="jump",
                            action_subtype="single",
                            analysis_profile="jump",
                            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
                            video_path="/tmp/43007.mp4",
                            status="completed",
                            created_at=now - timedelta(minutes=5),
                            frame_motion_scores={
                                "video_identity": identity,
                                "selected": [
                                    {"frame_id": "frame_0019", "timestamp": 3.688, "motion_score": 0.1760},
                                    {"frame_id": "frame_0020", "timestamp": 3.750, "motion_score": 0.1799},
                                    {"frame_id": "frame_0027", "timestamp": 4.500, "motion_score": 0.1010},
                                ],
                                "resolved_keyframes": {
                                    "source": "blended",
                                    "confidence": 0.84,
                                    "quality_flags": [],
                                    "selected": selected(3.688, 3.9, 3.95, confidence=0.84),
                                },
                            },
                        ),
                    ]
                )
                await session.commit()

                reuse = await analysis_router._find_matching_semantic_keyframes(
                    session=session,
                    current_analysis_id="current",
                    video_sha256="43007-sha",
                    action_type="jump",
                    action_subtype="single",
                    analysis_profile="jump",
                    current_motion_scores={
                        "video_identity": identity,
                        "selected": [
                            {"frame_id": "frame_0019", "timestamp": 3.688, "motion_score": 0.1760},
                            {"frame_id": "frame_0020", "timestamp": 3.750, "motion_score": 0.1799},
                            {"frame_id": "frame_0027", "timestamp": 4.500, "motion_score": 0.1010},
                        ],
                    },
                    current_bio_data={
                        "key_frame_candidates": {
                            "quality_flags": ["tal_candidate_landing_geometry_weak"],
                            "T": {
                                "timestamp": 3.688,
                                "confidence": 0.73,
                                "evidence": {"score_components": {"knee_extension": 0.82, "com_ascent": 0.68}},
                            },
                            "A": {
                                "timestamp": 3.75,
                                "confidence": 0.66,
                                "evidence": {"score_components": {"com_descent": 0.52}},
                            },
                            "L": {
                                "timestamp": 3.938,
                                "confidence": 0.70,
                                "evidence": {"score_components": {"ankle_return": 0.74, "knee_absorption": 0.55}},
                            },
                        }
                    },
                )

        self.assertIsNotNone(reuse)
        assert reuse is not None
        self.assertEqual(reuse["analysis_id"], "pose-supported-current-source")
        self.assertEqual(reuse["ranking_mode"], "current_pose_supported_candidate_delta")
        self.assertEqual(reuse["candidate_supported_key_count"], 3)

    def test_semantic_reuse_candidate_rejects_current_motion_fallback_conflict(self) -> None:
        import app.routers.analysis as analysis_router

        identity = {"sha256": "abc"}
        previous = SimpleNamespace(
            id="prior",
            status="completed",
            action_type="jump",
            action_subtype="single",
            analysis_profile="jump",
            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
            frame_motion_scores={
                "video_identity": identity,
                "resolved_keyframes": {
                    "source": "blended",
                    "confidence": 0.88,
                    "quality_flags": [],
                    "selected": [
                        {"timestamp": 4.4, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.88},
                        {"timestamp": 4.75, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.88},
                        {"timestamp": 5.25, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.88},
                    ],
                },
            },
        )
        current_bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_motion_fallback",
                    "keyframe_candidates_motion_fallback_from_takeoff_anchor",
                    "tal_candidate_motion_fallback_low_precision",
                ],
                "T": {
                    "frame_id": "frame_0017",
                    "timestamp": 2.375,
                    "confidence": 0.58,
                    "warnings": ["keyframe_candidates_motion_fallback"],
                },
                "A": {
                    "frame_id": "frame_0025",
                    "timestamp": 2.688,
                    "confidence": 0.56,
                    "warnings": ["keyframe_candidates_motion_fallback"],
                },
                "L": {
                    "frame_id": "frame_0026",
                    "timestamp": 3.0,
                    "confidence": 0.55,
                    "warnings": ["keyframe_candidates_motion_fallback"],
                },
            }
        }

        self.assertIsNone(
            analysis_router._semantic_reuse_candidate_from_analysis(
                previous,
                current_analysis_id="current",
                video_sha256="abc",
                action_type="jump",
                action_subtype="single",
                analysis_profile="jump",
                current_motion_scores={"video_identity": identity},
                current_bio_data=current_bio_data,
            )
        )

    def test_semantic_reuse_candidate_rejects_early_motion_cluster_mismatch(self) -> None:
        import app.routers.analysis as analysis_router

        identity = {"sha256": "abc"}
        previous = SimpleNamespace(
            id="prior",
            status="completed",
            action_type="jump",
            action_subtype="single",
            analysis_profile="jump",
            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
            frame_motion_scores={
                "video_identity": identity,
                "resolved_keyframes": {
                    "source": "blended",
                    "confidence": 0.9,
                    "quality_flags": [],
                    "selected": [
                        {"timestamp": 6.553, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.9},
                        {"timestamp": 7.5, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.9},
                        {"timestamp": 7.92, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.9},
                    ],
                },
            },
        )
        current_bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "tal_candidate_motion_window_occlusion_contaminated",
                    "tal_candidate_motion_window_unreliable_tracker_state",
                ],
                "T": {
                    "frame_id": "frame_0012",
                    "timestamp": 1.688,
                    "confidence": 0.58,
                    "warnings": ["motion_window_occlusion_contaminated"],
                    "evidence": {"motion_cluster_window": {"start_timestamp": 1.5, "end_timestamp": 2.75}},
                },
                "A": {
                    "frame_id": "frame_0013",
                    "timestamp": 2.0,
                    "confidence": 0.52,
                    "warnings": ["motion_window_occlusion_contaminated"],
                    "evidence": {"motion_cluster_window": {"start_timestamp": 1.5, "end_timestamp": 2.75}},
                },
                "L": {
                    "frame_id": "frame_0018",
                    "timestamp": 2.75,
                    "confidence": 0.57,
                    "warnings": ["motion_window_occlusion_contaminated"],
                    "evidence": {"motion_cluster_window": {"start_timestamp": 1.5, "end_timestamp": 2.75}},
                },
            }
        }
        current_motion_scores = {
            "video_identity": identity,
            "selected": [
                {"frame_id": "frame_0015", "timestamp": 2.562, "motion_score": 0.2293},
                {"frame_id": "frame_0016", "timestamp": 2.625, "motion_score": 0.2258},
                {"frame_id": "frame_0017", "timestamp": 2.688, "motion_score": 0.1997},
                {"frame_id": "frame_0018", "timestamp": 2.75, "motion_score": 0.1515},
                {"frame_id": "semantic_t", "timestamp": 6.553, "motion_score": 0.018},
                {"frame_id": "semantic_a", "timestamp": 7.5, "motion_score": 0.025},
                {"frame_id": "semantic_l", "timestamp": 7.92, "motion_score": 0.02},
                {"frame_id": "frame_0032", "timestamp": 10.375, "motion_score": 0.1486},
            ],
        }

        self.assertIsNone(
            analysis_router._semantic_reuse_candidate_from_analysis(
                previous,
                current_analysis_id="current",
                video_sha256="abc",
                action_type="jump",
                action_subtype="single",
                analysis_profile="jump",
                current_motion_scores=current_motion_scores,
                current_bio_data=current_bio_data,
            )
        )

    def test_semantic_reuse_candidate_keeps_reuse_when_motion_peak_supports_core(self) -> None:
        import app.routers.analysis as analysis_router

        identity = {"sha256": "abc"}
        previous = SimpleNamespace(
            id="prior",
            status="completed",
            action_type="jump",
            action_subtype="single",
            analysis_profile="jump",
            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
            frame_motion_scores={
                "video_identity": identity,
                "resolved_keyframes": {
                    "source": "video_ai_refined",
                    "confidence": 0.9,
                    "quality_flags": [],
                    "selected": [
                        {"timestamp": 3.0, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.9},
                        {"timestamp": 3.3, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.9},
                        {"timestamp": 3.65, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.9},
                    ],
                },
            },
        )
        reuse = analysis_router._semantic_reuse_candidate_from_analysis(
            previous,
            current_analysis_id="current",
            video_sha256="abc",
            action_type="jump",
            action_subtype="single",
            analysis_profile="jump",
            current_motion_scores={
                "video_identity": identity,
                "selected": [
                    {"frame_id": "frame_0001", "timestamp": 2.95, "motion_score": 0.14},
                    {"frame_id": "frame_0002", "timestamp": 3.2, "motion_score": 0.20},
                    {"frame_id": "frame_0003", "timestamp": 3.55, "motion_score": 0.17},
                ],
            },
            current_bio_data={
                "key_frame_candidates": {
                    "quality_flags": ["keyframe_candidates_excluded_unreliable_pose_frames"],
                    "T": {"frame_id": "frame_0001", "timestamp": 3.02, "confidence": 0.42},
                    "A": {"frame_id": "frame_0002", "timestamp": 3.3, "confidence": 0.42},
                    "L": {"frame_id": "frame_0003", "timestamp": 3.65, "confidence": 0.42},
                }
            },
        )

        self.assertIsNotNone(reuse)
        assert reuse is not None
        self.assertEqual([item["timestamp"] for item in reuse["selected"]], [3.0, 3.3, 3.65])

    def test_semantic_reuse_accepts_late_reanchor_source_despite_early_approach_peak(self) -> None:
        import app.routers.analysis as analysis_router

        identity = {"sha256": "late-reanchor-sha"}
        previous = SimpleNamespace(
            id="prior-late-reanchor",
            status="completed",
            action_type="jump",
            action_subtype="single",
            analysis_profile="jump",
            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
            frame_motion_scores={
                "video_identity": identity,
                "resolved_keyframes": {
                    "source": "video_ai_refined",
                    "confidence": 0.8,
                    "quality_flags": [
                        "semantic_keyframes_phase_range_late_reanchored",
                        "video_temporal_resolver_phase_range_late_reanchored",
                        "semantic_keyframes_candidate_tal_conflict_ignored_weak_temporal_geometry",
                        "video_temporal_quality_retry_motion_cluster_conflict_ignored_phase_range_late_reanchor",
                    ],
                    "selected": [
                        {
                            "timestamp": 1.938,
                            "phase_code": "takeoff",
                            "key_moment": "T_takeoff_sec",
                            "selection_reason": "video_phase_range_key_moment",
                            "confidence": 0.8,
                            "pre_late_phase_reanchor_timestamp": 3.753,
                            "late_phase_range_reanchor": True,
                            "late_phase_range_reanchor_delta_sec": -1.815,
                        },
                        {
                            "timestamp": 2.438,
                            "phase_code": "air",
                            "key_moment": "A_air_sec",
                            "selection_reason": "video_phase_range_key_moment",
                            "confidence": 0.75,
                            "pre_late_phase_reanchor_timestamp": 4.2,
                            "late_phase_range_reanchor": True,
                            "late_phase_range_reanchor_delta_sec": -1.762,
                        },
                        {
                            "timestamp": 2.758,
                            "phase_code": "landing",
                            "key_moment": "L_landing_sec",
                            "selection_reason": "video_phase_range_key_moment",
                            "confidence": 0.7,
                            "pre_late_phase_reanchor_timestamp": 4.7,
                            "late_phase_range_reanchor": True,
                            "late_phase_range_reanchor_delta_sec": -1.942,
                        },
                    ],
                },
            },
        )

        reuse = analysis_router._semantic_reuse_candidate_from_analysis(
            previous,
            current_analysis_id="current",
            video_sha256="late-reanchor-sha",
            action_type="jump",
            action_subtype="single",
            analysis_profile="jump",
            current_motion_scores={
                "video_identity": identity,
                "selected": [
                    {"frame_id": "frame_0001", "timestamp": 0.188, "motion_score": 0.3040},
                    {"frame_id": "frame_0002", "timestamp": 0.312, "motion_score": 0.3185},
                    {"frame_id": "frame_0003", "timestamp": 1.938, "motion_score": 0.0817},
                    {"frame_id": "frame_0004", "timestamp": 2.438, "motion_score": 0.0610},
                    {"frame_id": "frame_0005", "timestamp": 2.758, "motion_score": 0.0780},
                ],
            },
            current_bio_data={
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_excluded_unreliable_pose_frames",
                        "tal_candidate_landing_geometry_weak",
                        "tal_candidate_temporal_geometry_unreliable",
                        "tal_candidate_apex_landing_gap_unreliable",
                        "tal_candidate_apex_landing_gap_compressed",
                    ],
                    "T": {
                        "frame_id": "frame_0002",
                        "timestamp": 0.312,
                        "confidence": 0.50,
                        "evidence": {
                            "motion_cluster_window": {
                                "start_timestamp": 0.125,
                                "end_timestamp": 0.375,
                            }
                        },
                    },
                    "A": {
                        "frame_id": "frame_0003",
                        "timestamp": 1.938,
                        "confidence": 0.46,
                    },
                    "L": {
                        "frame_id": "frame_0004",
                        "timestamp": 2.062,
                        "confidence": 0.46,
                        "warnings": ["landing_geometry_weak"],
                        "evidence": {
                            "motion_cluster_window": {
                                "start_timestamp": 1.938,
                                "end_timestamp": 2.062,
                            }
                        },
                    },
                }
            },
        )

        self.assertIsNotNone(reuse)
        assert reuse is not None
        self.assertEqual(reuse["analysis_id"], "prior-late-reanchor")
        self.assertTrue(reuse["phase_range_late_reanchor_source_override"])
        self.assertEqual([item["timestamp"] for item in reuse["selected"]], [1.938, 2.438, 2.758])

    async def test_matching_semantic_reuse_prefers_pose_supported_candidate_agreement_over_newest(self) -> None:
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

            database.ensure_storage_dirs()
            await database.init_db()

            identity = {"sha256": "43002-sha"}
            now = datetime(2026, 6, 5, tzinfo=timezone.utc)

            def selected(t: float, a: float, l: float) -> list[dict[str, object]]:
                return [
                    {"timestamp": t, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.9},
                    {"timestamp": a, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.9},
                    {"timestamp": l, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.9},
                ]

            async with database.AsyncSessionLocal() as session:
                session.add_all(
                    [
                        models.Analysis(
                            id="older-stable",
                            action_type="jump",
                            action_subtype="single",
                            analysis_profile="jump",
                            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
                            video_path="/tmp/43002.mp4",
                            status="completed",
                            created_at=now - timedelta(minutes=10),
                            frame_motion_scores={
                                "video_identity": identity,
                                "resolved_keyframes": {
                                    "source": "video_ai_refined",
                                    "confidence": 0.91,
                                    "quality_flags": [
                                        "semantic_keyframe_refinement_order_rejected",
                                        "semantic_keyframe_refinement_rejection_ignored_near_skeleton_candidate",
                                    ],
                                    "selected": selected(2.015, 2.3, 2.5),
                                },
                            },
                        ),
                        models.Analysis(
                            id="newer-early-drift",
                            action_type="jump",
                            action_subtype="single",
                            analysis_profile="jump",
                            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
                            video_path="/tmp/43002.mp4",
                            status="completed",
                            created_at=now,
                            frame_motion_scores={
                                "video_identity": identity,
                                "resolved_keyframes": {
                                    "source": "video_ai_refined",
                                    "confidence": 0.93,
                                    "quality_flags": [],
                                    "selected": selected(1.65, 1.87, 2.13),
                                },
                            },
                        ),
                    ]
                )
                await session.commit()

                reuse = await analysis_router._find_matching_semantic_keyframes(
                    session=session,
                    current_analysis_id="current",
                    video_sha256="43002-sha",
                    action_type="jump",
                    action_subtype="single",
                    analysis_profile="jump",
                    current_motion_scores={"video_identity": identity},
                    current_bio_data={
                        "key_frame_candidates": {
                            "T": {
                                "timestamp": 2.062,
                                "confidence": 0.72,
                                "evidence": {"score_components": {"knee_extension": 0.8, "com_ascent": 0.6}},
                            },
                            "A": {
                                "timestamp": 2.188,
                                "confidence": 0.68,
                                "evidence": {"score_components": {"com_descent": 0.4}},
                            },
                            "L": {
                                "timestamp": 2.438,
                                "confidence": 0.74,
                                "evidence": {"score_components": {"ankle_return": 0.7, "knee_absorption": 0.5}},
                            },
                        }
                    },
                )

        self.assertIsNotNone(reuse)
        assert reuse is not None
        self.assertEqual(reuse["analysis_id"], "older-stable")
        self.assertEqual(reuse["ranking_mode"], "current_pose_supported_candidate_delta")
        self.assertEqual(reuse["source_penalty_flags"], ["semantic_keyframe_refinement_order_rejected"])
        self.assertLess(reuse["candidate_supported_mean_abs_delta_sec"], 0.15)

    async def test_matching_semantic_reuse_ignores_weak_temporal_geometry_for_ranking(self) -> None:
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

            database.ensure_storage_dirs()
            await database.init_db()

            identity = {"sha256": "43010-sha"}
            now = datetime(2026, 6, 5, tzinfo=timezone.utc)

            def selected(t: float, a: float, l: float) -> list[dict[str, object]]:
                return [
                    {"timestamp": t, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.85},
                    {"timestamp": a, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.85},
                    {"timestamp": l, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.85},
                ]

            async with database.AsyncSessionLocal() as session:
                session.add_all(
                    [
                        models.Analysis(
                            id="stable-a",
                            action_type="jump",
                            action_subtype="single",
                            analysis_profile="jump",
                            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
                            video_path="/tmp/43010.mp4",
                            status="completed",
                            created_at=now - timedelta(minutes=20),
                            frame_motion_scores={
                                "video_identity": identity,
                                "resolved_keyframes": {
                                    "source": "video_ai_refined",
                                    "confidence": 0.84,
                                    "quality_flags": [],
                                    "selected": selected(3.453, 3.8, 4.033),
                                },
                            },
                        ),
                        models.Analysis(
                            id="stable-b",
                            action_type="jump",
                            action_subtype="single",
                            analysis_profile="jump",
                            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
                            video_path="/tmp/43010.mp4",
                            status="completed",
                            created_at=now - timedelta(minutes=10),
                            frame_motion_scores={
                                "video_identity": identity,
                                "resolved_keyframes": {
                                    "source": "blended",
                                    "confidence": 0.82,
                                    "quality_flags": [],
                                    "selected": selected(3.52, 3.84, 4.08),
                                },
                            },
                        ),
                        models.Analysis(
                            id="newer-weak-candidate-near",
                            action_type="jump",
                            action_subtype="single",
                            analysis_profile="jump",
                            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
                            video_path="/tmp/43010.mp4",
                            status="completed",
                            created_at=now,
                            frame_motion_scores={
                                "video_identity": identity,
                                "resolved_keyframes": {
                                    "source": "video_ai_refined",
                                    "confidence": 0.86,
                                    "quality_flags": [],
                                    "selected": selected(2.0, 2.5, 2.92),
                                },
                            },
                        ),
                    ]
                )
                await session.commit()

                reuse = await analysis_router._find_matching_semantic_keyframes(
                    session=session,
                    current_analysis_id="current",
                    video_sha256="43010-sha",
                    action_type="jump",
                    action_subtype="single",
                    analysis_profile="jump",
                    current_motion_scores={"video_identity": identity},
                    current_bio_data={
                        "key_frame_candidates": {
                            "quality_flags": [
                                "keyframe_candidates_excluded_unreliable_pose_frames",
                                "tal_candidate_temporal_geometry_unreliable",
                                "tal_candidate_apex_landing_gap_unreliable",
                            ],
                            "T": {
                                "timestamp": 2.625,
                                "confidence": 0.49,
                                "warnings": ["knee_extension_weak"],
                                "evidence": {"score_components": {"com_ascent": 0.956, "knee_extension": 0.0}},
                            },
                            "A": {
                                "timestamp": 2.688,
                                "confidence": 0.49,
                                "warnings": ["apex_local_minimum_not_clear"],
                                "evidence": {"score_components": {"com_velocity": 0.451}},
                            },
                            "L": {
                                "timestamp": 4.062,
                                "confidence": 0.404,
                                "warnings": ["landing_geometry_weak"],
                                "evidence": {"score_components": {"landing_contact": 0.086}},
                            },
                        }
                    },
                )

        self.assertIsNotNone(reuse)
        assert reuse is not None
        self.assertIn(reuse["analysis_id"], {"stable-a", "stable-b"})
        self.assertNotEqual(reuse["analysis_id"], "newer-weak-candidate-near")
        self.assertEqual(reuse["ranking_mode"], "historical_semantic_stability")
        self.assertEqual(reuse["candidate_supported_key_count"], 0)
        self.assertLess(reuse["peer_mean_abs_delta_sec"], 0.75)

    async def test_matching_semantic_reuse_ignores_low_visibility_no_pose_motion_fallback_for_ranking(self) -> None:
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

            database.ensure_storage_dirs()
            await database.init_db()

            identity = {"sha256": "42901-sha"}
            now = datetime(2026, 6, 5, tzinfo=timezone.utc)

            def selected(t: float, a: float, l: float) -> list[dict[str, object]]:
                return [
                    {"timestamp": t, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.9},
                    {"timestamp": a, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.9},
                    {"timestamp": l, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.9},
                ]

            async with database.AsyncSessionLocal() as session:
                session.add_all(
                    [
                        models.Analysis(
                            id="stable-late-a",
                            action_type="jump",
                            action_subtype="single",
                            analysis_profile="jump",
                            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
                            video_path="/tmp/42901.mp4",
                            status="completed",
                            created_at=now - timedelta(minutes=20),
                            frame_motion_scores={
                                "video_identity": identity,
                                "resolved_keyframes": {
                                    "source": "video_ai_refined",
                                    "confidence": 0.91,
                                    "quality_flags": [],
                                    "selected": selected(7.2, 7.7, 8.2),
                                },
                            },
                        ),
                        models.Analysis(
                            id="stable-late-b",
                            action_type="jump",
                            action_subtype="single",
                            analysis_profile="jump",
                            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
                            video_path="/tmp/42901.mp4",
                            status="completed",
                            created_at=now - timedelta(minutes=10),
                            frame_motion_scores={
                                "video_identity": identity,
                                "resolved_keyframes": {
                                    "source": "video_ai_refined",
                                    "confidence": 0.9,
                                    "quality_flags": [],
                                    "selected": selected(7.22, 7.68, 8.18),
                                },
                            },
                        ),
                        models.Analysis(
                            id="newer-foreground-motion",
                            action_type="jump",
                            action_subtype="single",
                            analysis_profile="jump",
                            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
                            video_path="/tmp/42901.mp4",
                            status="completed",
                            created_at=now,
                            frame_motion_scores={
                                "video_identity": identity,
                                "resolved_keyframes": {
                                    "source": "video_ai_refined",
                                    "confidence": 0.95,
                                    "quality_flags": [],
                                    "selected": selected(3.188, 3.438, 3.688),
                                },
                            },
                        ),
                    ]
                )
                await session.commit()

                low_visibility_evidence = {
                    "motion_fallback": True,
                    "visibility_score": 0.0,
                    "score_components": {"pose_visibility": 0.0},
                }
                reuse = await analysis_router._find_matching_semantic_keyframes(
                    session=session,
                    current_analysis_id="current",
                    video_sha256="42901-sha",
                    action_type="jump",
                    action_subtype="single",
                    analysis_profile="jump",
                    current_motion_scores={"video_identity": identity},
                    current_bio_data={
                        "quality_flags": ["person_tracker_final_unrecovered"],
                        "key_frame_candidates": {
                            "quality_flags": [
                                "keyframe_candidates_motion_fallback",
                                "tal_candidate_motion_fallback_low_precision",
                                "tal_candidate_incomplete",
                                "tal_order_unresolved",
                                "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                            ],
                            "T": {
                                "timestamp": 3.188,
                                "confidence": 0.54,
                                "warnings": ["keyframe_candidates_motion_fallback"],
                                "evidence": low_visibility_evidence,
                            },
                            "A": {
                                "timestamp": 3.438,
                                "confidence": 0.54,
                                "warnings": ["keyframe_candidates_motion_fallback"],
                                "evidence": low_visibility_evidence,
                            },
                            "L": {
                                "timestamp": 3.688,
                                "confidence": 0.54,
                                "warnings": ["keyframe_candidates_motion_fallback"],
                                "evidence": low_visibility_evidence,
                            },
                        },
                    },
                )

        self.assertIsNotNone(reuse)
        assert reuse is not None
        self.assertIn(reuse["analysis_id"], {"stable-late-a", "stable-late-b"})
        self.assertEqual(reuse["ranking_mode"], "historical_semantic_stability")
        self.assertEqual(reuse["candidate_supported_key_count"], 0)
        self.assertLess(reuse["peer_mean_abs_delta_sec"], 3.0)

    async def test_matching_semantic_reuse_accepts_prior_low_visibility_source_and_anchors_first_canonical_tal(self) -> None:
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

            database.ensure_storage_dirs()
            await database.init_db()

            identity = {"sha256": "4067-sha"}
            now = datetime(2026, 6, 5, tzinfo=timezone.utc)
            low_visibility_source_flags = [
                "video_temporal_resolver_skeleton_t_below_anchor_confidence",
                "video_temporal_resolver_skeleton_a_below_anchor_confidence",
                "video_temporal_resolver_skeleton_l_below_anchor_confidence",
                "video_temporal_resolver_coherent_tal_used",
                "semantic_keyframes_candidate_tal_conflict_ignored_insufficient_pose_low_visibility_fallback",
                "video_temporal_quality_retry_motion_cluster_conflict",
                "video_temporal_quality_retry_rejected",
            ]
            candidate_quality_flags = [
                "keyframe_candidates_excluded_unreliable_pose_frames",
                "tal_candidate_incomplete",
                "tal_order_unresolved",
                "keyframe_candidates_motion_fallback",
                "tal_candidate_motion_fallback_low_precision",
                "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                "keyframe_candidates_motion_fallback_filtered_unreliable_pose_records",
                "keyframe_candidates_motion_fallback_multiperson_relock_instability_risk",
                "tal_candidate_motion_fallback_foreground_motion_risk",
            ]

            def selected(t: float, a: float, l: float) -> list[dict[str, object]]:
                return [
                    {
                        "timestamp": t,
                        "phase_code": "takeoff",
                        "key_moment": "T_takeoff_sec",
                        "selection_reason": "video_phase_range_key_moment",
                        "confidence": 0.8,
                    },
                    {
                        "timestamp": a,
                        "phase_code": "air",
                        "key_moment": "A_air_sec",
                        "selection_reason": "video_phase_range_key_moment",
                        "confidence": 0.8,
                    },
                    {
                        "timestamp": l,
                        "phase_code": "landing",
                        "key_moment": "L_landing_sec",
                        "selection_reason": "video_phase_range_key_moment",
                        "confidence": 0.8,
                    },
                ]

            def resolved(t: float, a: float, l: float) -> dict[str, object]:
                return {
                    "source": "video_ai_refined",
                    "confidence": 0.8,
                    "quality_flags": low_visibility_source_flags,
                    "selected": selected(t, a, l),
                    "semantic_candidate_tal_conflict": {
                        "conflicts": [],
                        "candidate_quality_flags": candidate_quality_flags,
                        "low_visibility_motion_fallback_keys": ["A", "L", "T"],
                        "decision": "ignored_insufficient_pose_low_visibility_motion_fallback_candidate",
                    },
                    "video_ai": {
                        "confidence": 0.8,
                        "quality_flags": ["video_temporal_phase_5_end_clamped_to_duration"],
                    },
                }

            async with database.AsyncSessionLocal() as session:
                session.add_all(
                    [
                        models.Analysis(
                            id="first-accepted-low-visibility",
                            action_type="jump",
                            action_subtype="single",
                            analysis_profile="jump",
                            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
                            video_path="/tmp/4067.mp4",
                            status="completed",
                            created_at=now - timedelta(minutes=20),
                            frame_motion_scores={
                                "video_identity": identity,
                                "resolved_keyframes": resolved(5.187, 5.6, 5.953),
                            },
                        ),
                        models.Analysis(
                            id="newer-ai-drift-low-visibility",
                            action_type="jump",
                            action_subtype="single",
                            analysis_profile="jump",
                            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
                            video_path="/tmp/4067.mp4",
                            status="completed",
                            created_at=now - timedelta(minutes=5),
                            frame_motion_scores={
                                "video_identity": identity,
                                "resolved_keyframes": resolved(5.187, 5.8, 6.167),
                            },
                        ),
                    ]
                )
                await session.commit()

                low_visibility_evidence = {
                    "motion_fallback": True,
                    "visibility_score": 0.0,
                    "score_components": {"pose_visibility": 0.0},
                }
                current_candidates = {
                    "quality_flags": candidate_quality_flags,
                    "T": {
                        "timestamp": 4.812,
                        "confidence": 0.486,
                        "warnings": [
                            "keyframe_candidates_motion_fallback",
                            "t_pose_signal_insufficient",
                            "tal_candidate_motion_fallback_foreground_motion_risk",
                        ],
                        "evidence": low_visibility_evidence,
                    },
                    "A": {
                        "timestamp": 5.188,
                        "confidence": 0.494,
                        "warnings": [
                            "keyframe_candidates_motion_fallback",
                            "a_pose_signal_insufficient",
                            "tal_candidate_motion_fallback_foreground_motion_risk",
                        ],
                        "evidence": low_visibility_evidence,
                    },
                    "L": {
                        "timestamp": 5.688,
                        "confidence": 0.498,
                        "warnings": [
                            "keyframe_candidates_motion_fallback",
                            "l_pose_signal_insufficient",
                            "tal_candidate_motion_fallback_foreground_motion_risk",
                        ],
                        "evidence": low_visibility_evidence,
                    },
                }
                reuse = await analysis_router._find_matching_semantic_keyframes(
                    session=session,
                    current_analysis_id="current",
                    video_sha256="4067-sha",
                    action_type="jump",
                    action_subtype="single",
                    analysis_profile="jump",
                    current_motion_scores={"video_identity": identity},
                    current_bio_data={"key_frame_candidates": current_candidates},
                )

        self.assertIsNotNone(reuse)
        assert reuse is not None
        self.assertEqual(reuse["analysis_id"], "first-accepted-low-visibility")
        self.assertEqual([item["timestamp"] for item in reuse["selected"]], [5.187, 5.6, 5.953])
        self.assertTrue(reuse["insufficient_pose_low_visibility_source_override"])
        self.assertEqual(reuse["ranking_mode"], "historical_semantic_stability")
        self.assertEqual(reuse["candidate_supported_key_count"], 0)

    async def test_matching_semantic_reuse_overrides_sparse_track_stitched_candidate_drift(self) -> None:
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

            database.ensure_storage_dirs()
            await database.init_db()

            identity = {"sha256": "4067-sha"}
            now = datetime(2026, 6, 5, tzinfo=timezone.utc)

            def selected(t: float, a: float, l: float) -> list[dict[str, object]]:
                return [
                    {
                        "timestamp": t,
                        "phase_code": "takeoff",
                        "key_moment": "T_takeoff_sec",
                        "selection_reason": "semantic_reused_from_matching_video",
                        "confidence": 0.75,
                    },
                    {
                        "timestamp": a,
                        "phase_code": "air",
                        "key_moment": "A_air_sec",
                        "selection_reason": "semantic_reused_from_matching_video",
                        "confidence": 0.80,
                    },
                    {
                        "timestamp": l,
                        "phase_code": "landing",
                        "key_moment": "L_landing_sec",
                        "selection_reason": "semantic_reused_from_matching_video",
                        "confidence": 0.75,
                    },
                ]

            async with database.AsyncSessionLocal() as session:
                session.add_all(
                    [
                        models.Analysis(
                            id="canonical-4067-semantic",
                            action_type="jump",
                            action_subtype="single",
                            analysis_profile="jump",
                            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
                            video_path="/tmp/4067.mp4",
                            status="completed",
                            created_at=now - timedelta(minutes=20),
                            frame_motion_scores={
                                "video_identity": identity,
                                "resolved_keyframes": {
                                    "source": "video_ai_refined",
                                    "confidence": 0.8,
                                    "quality_flags": ["semantic_keyframes_reused_from_matching_video"],
                                    "selected": selected(5.187, 5.6, 5.953),
                                },
                            },
                        ),
                        models.Analysis(
                            id="newer-4067-semantic",
                            action_type="jump",
                            action_subtype="single",
                            analysis_profile="jump",
                            pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
                            video_path="/tmp/4067.mp4",
                            status="completed",
                            created_at=now - timedelta(minutes=5),
                            frame_motion_scores={
                                "video_identity": identity,
                                "resolved_keyframes": {
                                    "source": "video_ai_refined",
                                    "confidence": 0.8,
                                    "quality_flags": ["semantic_keyframes_reused_from_matching_video"],
                                    "selected": selected(5.187, 5.8, 6.167),
                                },
                            },
                        ),
                    ]
                )
                await session.commit()

                current_candidates = {
                    "quality_flags": [
                        "keyframe_candidates_excluded_unreliable_pose_frames",
                        "tal_candidate_takeoff_geometry_weak",
                        "tal_candidate_apex_geometry_weak",
                        "tal_candidate_weak_geometry",
                        "tal_candidate_sparse_track_stitched",
                        "tal_candidate_unreliable_sparse_track_stitch",
                        "tal_candidate_confidence_low",
                    ],
                    "T": {
                        "timestamp": 5.75,
                        "confidence": 0.34,
                        "warnings": ["tal_candidate_sparse_track_stitched"],
                        "evidence": {
                            "visibility_score": 0.679,
                            "score_components": {"pose_visibility": 0.679},
                        },
                    },
                    "A": {
                        "timestamp": 5.812,
                        "confidence": 0.34,
                        "warnings": ["tal_candidate_sparse_track_stitched"],
                        "evidence": {
                            "visibility_score": 0.86,
                            "score_components": {"pose_visibility": 0.86},
                        },
                    },
                    "L": {
                        "timestamp": 7.688,
                        "confidence": 0.34,
                        "warnings": ["tal_candidate_sparse_track_stitched"],
                        "evidence": {
                            "visibility_score": 0.907,
                            "score_components": {"pose_visibility": 0.907},
                        },
                    },
                }
                reuse = await analysis_router._find_matching_semantic_keyframes(
                    session=session,
                    current_analysis_id="current",
                    video_sha256="4067-sha",
                    action_type="jump",
                    action_subtype="single",
                    analysis_profile="jump",
                    current_motion_scores={"video_identity": identity},
                    current_bio_data={"key_frame_candidates": current_candidates},
                )

        self.assertIsNotNone(reuse)
        assert reuse is not None
        self.assertEqual(reuse["analysis_id"], "canonical-4067-semantic")
        self.assertEqual([item["timestamp"] for item in reuse["selected"]], [5.187, 5.6, 5.953])
        self.assertTrue(reuse["sparse_track_stitched_candidate_override"])
        self.assertEqual(reuse["ranking_mode"], "historical_semantic_stability")
        self.assertEqual(reuse["candidate_supported_key_count"], 0)

    async def test_matching_semantic_reuse_accepts_full_context_takeoff_anchor_fallback_candidate(self) -> None:
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

            database.ensure_storage_dirs()
            await database.init_db()

            identity = {"sha256": "43003-sha"}
            now = datetime(2026, 6, 5, tzinfo=timezone.utc)

            def selected(t: float, a: float, l: float) -> list[dict[str, object]]:
                return [
                    {"timestamp": t, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.8},
                    {"timestamp": a, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.75},
                    {"timestamp": l, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.8},
                ]

            async with database.AsyncSessionLocal() as session:
                session.add(
                    models.Analysis(
                        id="prior-43003-semantic",
                        action_type="jump",
                        action_subtype="single",
                        analysis_profile="jump",
                        pipeline_version=analysis_router.CURRENT_PIPELINE_VERSION,
                        video_path="/tmp/43003.mp4",
                        status="completed",
                        created_at=now,
                        frame_motion_scores={
                            "video_identity": identity,
                            "input_window_mode": "full_context",
                            "input_window_duration_sec": 8.868,
                            "resolved_keyframes": {
                                "source": "video_ai_refined",
                                "confidence": 0.85,
                                "quality_flags": [
                                    "video_temporal_resolver_coherent_tal_used",
                                    "semantic_keyframes_candidate_motion_window_conflict_ignored_full_context_takeoff_anchor_fallback",
                                ],
                                "selected": selected(2.620, 3.100, 3.667),
                            },
                        },
                    )
                )
                await session.commit()

                reuse = await analysis_router._find_matching_semantic_keyframes(
                    session=session,
                    current_analysis_id="current",
                    video_sha256="43003-sha",
                    action_type="jump",
                    action_subtype="single",
                    analysis_profile="jump",
                    current_motion_scores={
                        "video_identity": identity,
                        "input_window_mode": "full_context",
                        "input_window_duration_sec": 8.868,
                        "selected": [
                            {"frame_id": "frame_0059", "timestamp": 3.653, "motion_score": 0.0288},
                            {"frame_id": "frame_0066", "timestamp": 4.100, "motion_score": 0.0264},
                            {"frame_id": "frame_0070", "timestamp": 4.400, "motion_score": 0.0228},
                            {"frame_id": "frame_0112", "timestamp": 7.000, "motion_score": 0.1060},
                            {"frame_id": "frame_0116", "timestamp": 7.250, "motion_score": 0.1123},
                            {"frame_id": "frame_0125", "timestamp": 7.812, "motion_score": 0.1183},
                            {"frame_id": "frame_0127", "timestamp": 7.938, "motion_score": 0.1160},
                        ],
                    },
                    current_bio_data={
                        "key_frame_candidates": {
                            "quality_flags": [
                                "keyframe_candidates_excluded_unreliable_pose_frames",
                                "tal_candidate_skeleton_drifted_after_takeoff",
                                "keyframe_candidates_motion_fallback",
                                "keyframe_candidates_motion_fallback_from_takeoff_anchor",
                                "tal_candidate_motion_fallback_low_precision",
                            ],
                            "T": {
                                "frame_id": "frame_0112",
                                "timestamp": 7.000,
                                "confidence": 0.573,
                                "warnings": [
                                    "keyframe_candidates_motion_fallback",
                                    "keyframe_candidates_motion_fallback_from_takeoff_anchor",
                                ],
                            },
                            "A": {
                                "frame_id": "frame_0116",
                                "timestamp": 7.250,
                                "confidence": 0.539,
                                "evidence": {"motion_fallback": True, "visibility_score": 0.0},
                                "warnings": [
                                    "keyframe_candidates_motion_fallback",
                                    "tal_candidate_motion_fallback_low_precision",
                                    "tal_candidate_skeleton_drifted_after_takeoff",
                                ],
                            },
                            "L": {
                                "frame_id": "frame_0125",
                                "timestamp": 7.812,
                                "confidence": 0.577,
                                "evidence": {"motion_fallback": True, "visibility_score": 0.0},
                                "warnings": [
                                    "keyframe_candidates_motion_fallback",
                                    "tal_candidate_motion_fallback_low_precision",
                                ],
                            },
                        }
                    },
                )

        self.assertIsNotNone(reuse)
        assert reuse is not None
        self.assertEqual(reuse["analysis_id"], "prior-43003-semantic")
        self.assertEqual([item["timestamp"] for item in reuse["selected"]], [2.62, 3.1, 3.667])
        self.assertEqual(reuse["candidate_supported_key_count"], 0)
        self.assertEqual(reuse["ranking_mode"], "historical_semantic_stability")


if __name__ == "__main__":
    unittest.main()
