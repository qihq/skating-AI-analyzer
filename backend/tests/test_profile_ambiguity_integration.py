"""Offline integration checks for routing uncertainty; all storage is temporary."""
from __future__ import annotations
import copy
import importlib
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from sqlalchemy import select, func


def evidence():
    return {
        "profile_hint": "mixed_auto", "mixed_action_input": True,
        "profile_confidence": "low", "profile_route_only": True, "jump_spin_ambiguous": True, "airborne_frames_detected": 0,
        "jump_gate_passed": False, "hip_rotation_signal": 0.6,
        "quality_flags": ["mixed_action_profile_inferred_spin_from_rotation", "jump_spin_ambiguous", "profile_route_only"],
        "negative_constraints": ["证据不足，暂不能自动区分跳跃和旋转；旋转线索不能排除跳跃，也不能确认旋转、周数或单跳/连跳。"],
    }


def metadata():
    return SimpleNamespace(effective_fps=6.0, source_fps=30.0, window_start_sec=0.0, window_end_sec=2.0)


class ProfileAmbiguityRecoveryTests(unittest.TestCase):
    def test_recovery_changes_route_without_erasing_uncertainty(self):
        from app.routers import analysis as router
        original = evidence()
        snapshot = copy.deepcopy(original)
        raw_bio = {"quality_flags": ["target_tracking_uncertain"], "key_frames": {}}
        with (
            patch.object(router, "_profile_from_resolved_video_ai_for_mixed_action", return_value=("jump", ["recovery_candidate"])),
            patch.object(router, "analyze_biomechanics", return_value=raw_bio),
            patch.object(router, "attach_key_frame_candidates", side_effect=lambda bio, *a: bio),
            patch.object(router, "infer_jump_subtype_evidence", return_value={}),
        ):
            profile, bio, recovered = router._apply_resolved_video_ai_profile_override_to_bio_data(
                action_type="自由滑", action_subtype="节目片段", current_profile="spin",
                video_temporal={}, resolved_keyframes={}, bio_data={}, pose_data={"frames": []},
                motion_scores={}, sampling_metadata=metadata(), profile_evidence=original, target_lock={},
            )
        self.assertEqual(profile, "jump")
        self.assertEqual(original, snapshot)
        self.assertEqual(recovered["profile_confidence"], "low")
        self.assertFalse(recovered["jump_gate_passed"])
        self.assertIn("jump_spin_ambiguous", bio["quality_flags"])
        self.assertIn("target_tracking_uncertain", bio["quality_flags"])
        self.assertIn("不能", bio.get("profile_warning", ""))
        self.assertIn("跳跃", bio.get("profile_warning", ""))
        self.assertNotIn("仅按旋转方向路由", bio["profile_warning"])
        self.assertEqual(bio["profile_evidence"]["negative_constraints"], original["negative_constraints"])


class ProfileAmbiguityPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_saved_native_report_and_report_retry_keep_same_uncertainty(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, {
            "DATA_DIR": tmpdir, "DATABASE_URL": f"sqlite+aiosqlite:///{Path(tmpdir) / 'test.db'}"
        }):
            for name in ["app.database", "app.models", "app.routers.analysis", "app.services.pipeline_version"]:
                sys.modules.pop(name, None)
            database = importlib.import_module("app.database")
            models = importlib.import_module("app.models")
            router = importlib.import_module("app.routers.analysis")
            database.ensure_storage_dirs()
            await database.init_db()
            try:
                analysis_id = str(uuid4())
                async with database.AsyncSessionLocal() as session:
                    session.add(models.Analysis(id=analysis_id, action_type="自由滑", action_subtype="节目片段",
                        analysis_profile="spin", video_path=str(Path(tmpdir)/"absent.mp4"),
                        vision_structured={}, status="processing"))
                    await session.commit()
                with (
                    patch.object(router, "analyze_biomechanics", return_value={"quality_flags": [], "key_frames": {}}),
                    patch.object(router, "attach_key_frame_candidates", side_effect=lambda bio, *a: bio),
                ):
                    bio = router._build_bio_data_for_profile(pose_data={"frames": []}, motion_scores={},
                        action_type="自由滑", analysis_profile="spin", sampling_metadata=metadata(),
                        profile_evidence=evidence(), target_lock={})
                self.assertTrue(await router._save_analysis_fields_with_retry(analysis_id,
                    {"bio_data": bio, "analysis_profile": "spin"}, context="ambiguity_synthetic_save"))
                await router._save_local_analysis_result(analysis_id, "自由滑", {}, time.monotonic(), bio_data=bio, pose_ran=True)
                async with database.AsyncSessionLocal() as session:
                    saved = await session.get(models.Analysis, analysis_id)
                    first_bio = copy.deepcopy(saved.bio_data)
                    self.assertEqual(saved.status, "completed")
                    self.assertEqual(saved.analysis_profile, "spin")
                    self.assertEqual(saved.bio_data["profile_evidence"]["profile_confidence"], "low")
                    self.assertIn("不能", saved.bio_data.get("profile_warning", ""))
                    self.assertIn(saved.bio_data["profile_warning"], saved.report["summary"])
                    self.assertIsNone(saved.force_score)
                    first_warning = saved.report["profile_warning"]
                with (
                    patch("app.trial.external_ai_allowed", return_value=False),
                    patch.object(router, "extract_pose", side_effect=AssertionError("no inference")),
                    patch.object(router, "analyze_biomechanics", side_effect=AssertionError("no recomputation")),
                    patch.object(router, "build_analysis_prompt_context", AsyncMock(return_value=None)),
                    patch.object(router, "auto_update_skill_progress", AsyncMock(return_value=None)),
                    patch.object(router, "sync_skater_progress", AsyncMock(return_value=None)),
                    patch.object(router, "suggest_memory_updates", AsyncMock(return_value=None)),
                ):
                    await router.process_analysis(analysis_id, retry_from="report")
                async with database.AsyncSessionLocal() as session:
                    saved = await session.get(models.Analysis, analysis_id)
                    self.assertEqual(saved.id, analysis_id)
                    self.assertEqual(saved.status, "completed")
                    self.assertIsNone(saved.retry_from_stage)
                    self.assertEqual(saved.bio_data, first_bio)
                    self.assertEqual(saved.report["profile_warning"], first_warning)
                    self.assertIn(first_warning, saved.report["summary"])
                    self.assertEqual(await session.scalar(select(func.count()).select_from(models.Analysis)), 1)
            finally:
                await database.engine.dispose()


class ProfileAmbiguitySyntheticTests(unittest.TestCase):
    @staticmethod
    def frame(ankle=.7, dy=0.0, scale=1.0, dx=0.0):
        coords = {0:(.5,.2),11:(.54,.4),12:(.46,.4),23:(.525,.5),24:(.475,.5),27:(.52,ankle),28:(.48,ankle)}
        return {"keypoints":[{"id":i,"x":(x-.5)*scale+.5+dx,"y":y*scale+dy,"visibility":.99} for i,(x,y) in coords.items()]}

    def test_geometry_counterexamples_remain_candidates_not_confirmation(self):
        from app.services.action_profiles import infer_analysis_profile
        cases = {
            "local_ankle_rise": [self.frame(a) for a in (.7,.58,.57,.7)],
            "camera_translation": [self.frame(dy=y) for y in (0,-.12,-.13,0)],
            "camera_zoom": [self.frame(scale=s) for s in (1,.82,.80,1)],
        }
        for label, frames in cases.items():
            with self.subTest(case=label):
                profile, info = infer_analysis_profile("自由滑", "节目片段", {"frames":frames}, {"scores":[.08]*4})
                self.assertEqual(profile, "jump")
                self.assertTrue(info["jump_gate_passed"])  # preserved heuristic, not blade-contact truth
                self.assertTrue(info["profile_route_only"])
                self.assertTrue(any("候选" in s and ("离冰" in s or "接触" in s) for s in info["negative_constraints"]))

    def test_horizontal_glide_default_does_not_exclude_jump(self):
        from app.services.action_profiles import infer_analysis_profile
        profile, info = infer_analysis_profile("自由滑", "节目片段", {"frames":[self.frame(dx=x) for x in (0,.05,.1,.15)]}, {"scores":[.08]*4})
        self.assertEqual(profile, "step")
        self.assertFalse(info["jump_gate_passed"])
        self.assertTrue(info["profile_route_only"])
        self.assertTrue(any("跳跃" in s and ("排除" in s or "不代表" in s) for s in info["negative_constraints"]))
