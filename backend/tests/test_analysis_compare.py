from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4


def _reset_app_modules() -> None:
    for module_name in [
        "app.database",
        "app.models",
        "app.routers.analysis",
        "app.services.pipeline_version",
    ]:
        sys.modules.pop(module_name, None)


def _report(score: int, severity: str = "medium") -> dict[str, object]:
    return {
        "summary": "ok",
        "issues": [{"category": "落冰", "description": "落冰不稳", "severity": severity}],
        "improvements": [],
        "training_focus": "稳定落冰",
        "subscores": {
            "takeoff_power": score,
            "rotation_axis": score - 1,
            "arm_coordination": score - 2,
            "landing_absorption": score - 3,
            "core_stability": score - 4,
        },
        "data_quality": "good",
    }


def _bio(score: int) -> dict[str, object]:
    return {
        "key_frames": {"T": "frame_0001", "A": "frame_0002", "L": "frame_0003"},
        "key_frame_timestamps": {"T": 0.1, "A": 0.2, "L": 0.3},
        "key_frame_candidates": {
            "T": {"frame_id": "frame_0001", "timestamp": 0.1, "confidence": 0.8},
            "A": {"frame_id": "frame_0002", "timestamp": 0.2, "confidence": 0.82},
            "L": {"frame_id": "frame_0003", "timestamp": 0.3, "confidence": 0.84},
        },
        "jump_metrics_status": "ok",
        "jump_metrics": {
            "air_time_seconds": round(score / 100, 2),
            "estimated_height_cm": float(score),
            "takeoff_speed_mps": round(score / 50, 2),
            "rotation_rps": round(score / 40, 2),
            "estimated_rotations": round(score / 80, 2),
        },
        "bio_subscores": {"takeoff_power": score},
        "quality_flags": [],
    }


def _video_identity(sha256: str) -> dict[str, object]:
    return {
        "schema_version": "video_identity_v1",
        "sha256": sha256,
        "size_bytes": 10,
        "filename": "source.mp4",
    }


class AnalysisCompareTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["DATA_DIR"] = self.tmp.name
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(self.tmp.name) / 'test.db'}"
        _reset_app_modules()

        import app.database as database
        import app.models as models
        import app.routers.analysis as analysis_router

        self.database = database
        self.models = models
        self.analysis_router = analysis_router
        database.ensure_storage_dirs()
        await database.init_db()

    async def asyncTearDown(self) -> None:
        self.tmp.cleanup()

    def _make_upload(self, analysis_id: str) -> Path:
        upload_dir = Path(self.tmp.name) / "uploads" / analysis_id
        frames_dir = upload_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        semantic_dir = upload_dir / "semantic_frames"
        semantic_dir.mkdir(parents=True, exist_ok=True)
        video_path = upload_dir / "source.mp4"
        video_path.write_bytes(b"fake-video")
        for index in range(1, 4):
            (frames_dir / f"frame_{index:04d}.jpg").write_bytes(b"fake-frame")
            (semantic_dir / f"semantic_{index:04d}.jpg").write_bytes(b"fake-semantic-frame")
        return video_path

    async def _insert_analysis(
        self,
        *,
        analysis_id: str,
        skater_id: str,
        score: int,
        created_at: datetime,
        action_subtype: str = "一周跳",
        status: str = "completed",
    ) -> None:
        video_path = self._make_upload(analysis_id)
        async with self.database.AsyncSessionLocal() as session:
            session.add(
                self.models.Analysis(
                    id=analysis_id,
                    skater_id=skater_id,
                    action_type="跳跃",
                    action_subtype=action_subtype,
                    analysis_profile="jump",
                    pipeline_version="test",
                    video_path=str(video_path),
                    status=status,
                    force_score=score,
                    report=_report(score),
                    bio_data=_bio(score),
                    frame_motion_scores={
                        "video_identity": _video_identity(analysis_id),
                        "selected": [
                            {"frame_id": "frame_0001", "timestamp": 0.1},
                            {"frame_id": "frame_0002", "timestamp": 0.2},
                            {"frame_id": "frame_0003", "timestamp": 0.3},
                        ],
                        "resolved_keyframes": {
                            "source": "video_ai_refined",
                            "confidence": 0.88,
                            "selected": [
                                {
                                    "frame_id": "semantic_0001",
                                    "timestamp": 0.12,
                                    "phase_code": "takeoff",
                                    "phase_label": "起跳",
                                    "key_moment": "T_takeoff_sec",
                                    "selection_reason": "video_phase_range_motion_peak",
                                    "pre_refine_timestamp": 0.1,
                                    "refinement_method": "local_motion_peak",
                                    "refinement_delta_sec": 0.02,
                                    "confidence": 0.86,
                                },
                                {
                                    "frame_id": "semantic_0002",
                                    "timestamp": 0.24,
                                    "phase_code": "air",
                                    "phase_label": "腾空",
                                    "key_moment": "A_air_sec",
                                    "selection_reason": "video_phase_range_key_moment_motion_nearby",
                                    "pre_refine_timestamp": 0.24,
                                    "refinement_method": "apex_preserved",
                                    "refinement_delta_sec": 0.0,
                                    "confidence": 0.87,
                                },
                                {
                                    "frame_id": "semantic_0003",
                                    "timestamp": 0.36,
                                    "phase_code": "landing",
                                    "phase_label": "落冰",
                                    "key_moment": "L_landing_sec",
                                    "selection_reason": "video_phase_range_skeleton_candidate",
                                    "confidence": 0.88,
                                },
                            ],
                        },
                    },
                    action_window_start=0.1,
                    action_window_end=0.9,
                    source_fps=30.0,
                    is_slow_motion=False,
                    target_lock={"status": "locked"},
                    target_lock_status="locked",
                    created_at=created_at,
                    updated_at=created_at,
                )
            )
            await session.commit()

    async def test_compare_returns_ordered_deltas_keyframes_and_video_payload(self) -> None:
        older_id = str(uuid4())
        newer_id = str(uuid4())
        skater_id = str(uuid4())
        await self._insert_analysis(
            analysis_id=newer_id,
            skater_id=skater_id,
            score=82,
            created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        await self._insert_analysis(
            analysis_id=older_id,
            skater_id=skater_id,
            score=70,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

        completion_mock = AsyncMock(return_value="孩子这次动作更稳定。")
        with (
            patch("app.routers.analysis.get_active_provider", AsyncMock(return_value=object())),
            patch("app.routers.analysis.request_text_completion", completion_mock),
        ):
            async with self.database.AsyncSessionLocal() as session:
                result = await self.analysis_router.compare_analyses(newer_id, older_id, session=session)

        self.assertEqual(result.analysis_a.id, older_id)
        self.assertEqual(result.analysis_b.id, newer_id)
        self.assertEqual(result.score_delta, 12)
        self.assertEqual(result.subscore_deltas[0].delta, 12)
        self.assertTrue(result.metric_deltas[0].available)
        self.assertEqual(result.keyframe_compare[0].before.frame_id, "frame_0001")
        self.assertEqual(result.keyframe_compare[0].before.source, "bio_key_frames")
        self.assertEqual(result.keyframe_compare[0].before.timestamp, 0.1)
        self.assertEqual(result.keyframe_compare[0].before.confidence, 0.8)
        self.assertTrue(result.keyframe_compare[0].before.available)
        self.assertEqual(result.keyframe_compare[0].after.timestamp, 0.1)
        self.assertEqual(result.keyframe_compare[0].delta_seconds, 0.0)
        self.assertEqual(result.keyframe_compare[0].before_offset_seconds, 0.0)
        self.assertEqual(result.keyframe_compare[0].after_offset_seconds, 0.0)
        self.assertEqual(result.keyframe_compare[0].relative_delta_seconds, 0.0)
        self.assertIsNotNone(result.video_compare)
        assert result.video_compare is not None
        self.assertTrue(result.video_compare.before.available)
        self.assertEqual(result.video_compare.sync_mode, "bio_keyframe")
        messages = completion_mock.await_args.kwargs["messages"]
        self.assertIn("不要夸大进步", messages[0]["content"])
        self.assertIn("动作子类型未知", messages[0]["content"])
        self.assertIn("谨慎观察", messages[1]["content"])
        self.assertEqual(result.video_compare.sync_anchor_key, "T")
        self.assertEqual(result.video_compare.before.sync_start, 0.0)
        self.assertEqual(result.video_compare.before.sync_duration, 0.9)
        self.assertEqual(result.ai_narrative, "孩子这次动作更稳定。")

    async def test_compare_video_sync_uses_final_bio_keyframe_when_semantic_conflicts(self) -> None:
        older_id = str(uuid4())
        newer_id = str(uuid4())
        skater_id = str(uuid4())
        await self._insert_analysis(
            analysis_id=older_id,
            skater_id=skater_id,
            score=70,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        await self._insert_analysis(
            analysis_id=newer_id,
            skater_id=skater_id,
            score=82,
            created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )

        async with self.database.AsyncSessionLocal() as session:
            older = await session.get(self.models.Analysis, older_id)
            newer = await session.get(self.models.Analysis, newer_id)
            assert older is not None
            assert newer is not None
            for item in (older, newer):
                assert isinstance(item.bio_data, dict)
                bio_data = dict(item.bio_data)
                bio_data["key_frame_timestamps"] = {"T": 3.2, "A": 3.6, "L": 3.9}
                item.bio_data = bio_data
                assert isinstance(item.frame_motion_scores, dict)
                frame_motion_scores = dict(item.frame_motion_scores)
                frame_motion_scores["resolved_keyframes"] = {
                    "source": "blended",
                    "quality_flags": ["video_temporal_quality_retry_skeleton_tal_conflict"],
                    "selected": [
                        {
                            "frame_id": "semantic_0001",
                            "timestamp": 0.5,
                            "phase_code": "takeoff",
                            "key_moment": "T_takeoff_sec",
                        },
                        {
                            "frame_id": "semantic_0002",
                            "timestamp": 0.8,
                            "phase_code": "air",
                            "key_moment": "A_air_sec",
                        },
                        {
                            "frame_id": "semantic_0003",
                            "timestamp": 1.1,
                            "phase_code": "landing",
                            "key_moment": "L_landing_sec",
                        },
                    ],
                }
                item.frame_motion_scores = frame_motion_scores
            await session.commit()

        with (
            patch("app.routers.analysis.get_active_provider", AsyncMock(return_value=None)),
            patch("app.routers.analysis.request_text_completion", AsyncMock(return_value="")),
        ):
            async with self.database.AsyncSessionLocal() as session:
                result = await self.analysis_router.compare_analyses(older_id, newer_id, session=session)

        self.assertIsNotNone(result.video_compare)
        assert result.video_compare is not None
        self.assertEqual(result.video_compare.sync_mode, "bio_keyframe")
        self.assertEqual(result.video_compare.before.sync_start, 2.85)
        self.assertEqual(result.video_compare.after.sync_start, 2.85)
        self.assertEqual(result.video_compare.before.sync_duration, 1.4)

    async def test_compare_keyframes_include_takeoff_relative_phase_deltas(self) -> None:
        older_id = str(uuid4())
        newer_id = str(uuid4())
        skater_id = str(uuid4())
        await self._insert_analysis(
            analysis_id=older_id,
            skater_id=skater_id,
            score=70,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        await self._insert_analysis(
            analysis_id=newer_id,
            skater_id=skater_id,
            score=72,
            created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )

        async with self.database.AsyncSessionLocal() as session:
            older = await session.get(self.models.Analysis, older_id)
            newer = await session.get(self.models.Analysis, newer_id)
            assert older is not None
            assert newer is not None
            older.bio_data = {
                **older.bio_data,
                "key_frame_timestamps": {"T": 1.0, "A": 1.4, "L": 1.8},
            }
            newer.bio_data = {
                **newer.bio_data,
                "key_frame_timestamps": {"T": 2.0, "A": 2.5, "L": 3.0},
            }
            await session.commit()

        with (
            patch("app.routers.analysis.get_active_provider", AsyncMock(return_value=None)),
            patch("app.routers.analysis.request_text_completion", AsyncMock(return_value="")),
        ):
            async with self.database.AsyncSessionLocal() as session:
                result = await self.analysis_router.compare_analyses(older_id, newer_id, session=session)

        by_key = {item.key: item for item in result.keyframe_compare}
        self.assertEqual(by_key["T"].delta_seconds, 1.0)
        self.assertEqual(by_key["T"].relative_delta_seconds, 0.0)
        self.assertEqual(by_key["A"].delta_seconds, 1.1)
        self.assertEqual(by_key["A"].before_offset_seconds, 0.4)
        self.assertEqual(by_key["A"].after_offset_seconds, 0.5)
        self.assertEqual(by_key["A"].relative_delta_seconds, 0.1)
        self.assertEqual(by_key["L"].delta_seconds, 1.2)
        self.assertEqual(by_key["L"].relative_delta_seconds, 0.2)

    async def test_compare_uses_profile_keyframes_for_step_and_spiral(self) -> None:
        cases = [
            ("step", "step_sequence", "步法序列", "步法序列", 1.2, 1.35),
            ("spiral", "spiral_hold", "峰值", "姿态峰值", 2.0, 2.12),
        ]

        for profile, phase_code, key, label, before_ts, after_ts in cases:
            with self.subTest(profile=profile):
                older_id = str(uuid4())
                newer_id = str(uuid4())
                skater_id = str(uuid4())
                await self._insert_analysis(
                    analysis_id=older_id,
                    skater_id=skater_id,
                    score=70,
                    created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                )
                await self._insert_analysis(
                    analysis_id=newer_id,
                    skater_id=skater_id,
                    score=72,
                    created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                )

                async with self.database.AsyncSessionLocal() as session:
                    older = await session.get(self.models.Analysis, older_id)
                    newer = await session.get(self.models.Analysis, newer_id)
                    assert older is not None
                    assert newer is not None
                    for analysis, timestamp in ((older, before_ts), (newer, after_ts)):
                        analysis.analysis_profile = profile
                        analysis.action_window_start = max(0.0, timestamp - 0.50)
                        analysis.action_window_end = timestamp + 0.90
                        analysis.bio_data = {
                            "key_frames": {},
                            "key_frame_timestamps": {},
                            "key_frame_candidates": {},
                            "quality_flags": [],
                        }
                        analysis.frame_motion_scores = {
                            "video_identity": _video_identity(analysis.id),
                            "resolved_keyframes": {
                                "source": "video_ai_refined",
                                "confidence": 0.9,
                                "selected": [
                                    {
                                        "frame_id": "semantic_0001",
                                        "timestamp": timestamp,
                                        "phase_code": phase_code,
                                        "phase_label": label,
                                        "key_moment": phase_code,
                                        "selection_reason": "video_phase_range_motion_peak",
                                        "confidence": 0.88,
                                    }
                                ],
                            },
                        }
                    await session.commit()

                with (
                    patch("app.routers.analysis.get_active_provider", AsyncMock(return_value=None)),
                    patch("app.routers.analysis.request_text_completion", AsyncMock(return_value="")),
                ):
                    async with self.database.AsyncSessionLocal() as session:
                        result = await self.analysis_router.compare_analyses(older_id, newer_id, session=session)

                self.assertEqual([item.key for item in result.keyframe_compare], [key])
                pair = result.keyframe_compare[0]
                self.assertEqual(pair.label, label)
                self.assertEqual(pair.before.timestamp, before_ts)
                self.assertEqual(pair.after.timestamp, after_ts)
                self.assertEqual(pair.delta_seconds, round(after_ts - before_ts, 3))
                self.assertEqual(pair.before_offset_seconds, 0.0)
                self.assertEqual(pair.after_offset_seconds, 0.0)
                self.assertEqual(pair.relative_delta_seconds, 0.0)
                self.assertIsNotNone(result.video_compare)
                assert result.video_compare is not None
                self.assertEqual(result.video_compare.sync_mode, "bio_keyframe")
                self.assertEqual(result.video_compare.sync_anchor_key, key)
                self.assertEqual(result.video_compare.before.sync_start, round(max(0.0, before_ts - 0.35), 3))
                self.assertEqual(result.video_compare.after.sync_start, round(max(0.0, after_ts - 0.35), 3))

    async def test_compare_uses_semantic_metadata_for_synced_bio_keyframes(self) -> None:
        older_id = str(uuid4())
        newer_id = str(uuid4())
        skater_id = str(uuid4())
        await self._insert_analysis(
            analysis_id=older_id,
            skater_id=skater_id,
            score=70,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        await self._insert_analysis(
            analysis_id=newer_id,
            skater_id=skater_id,
            score=82,
            created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )

        async with self.database.AsyncSessionLocal() as session:
            older = await session.get(self.models.Analysis, older_id)
            newer = await session.get(self.models.Analysis, newer_id)
            assert older is not None
            assert newer is not None
            for item in (older, newer):
                assert isinstance(item.bio_data, dict)
                bio_data = dict(item.bio_data)
                bio_data["key_frames"] = {"T": "semantic_0001", "A": "semantic_0002", "L": "semantic_0003"}
                bio_data["key_frame_timestamps"] = {"T": 5.187, "A": 5.8, "L": 6.167}
                bio_data["key_frame_source"] = "video_ai_refined"
                bio_data["key_frame_candidates"] = {
                    "T": {"frame_id": "frame_0016", "timestamp": 4.812, "confidence": 0.486},
                    "A": {"frame_id": "frame_0017", "timestamp": 5.188, "confidence": 0.494},
                    "L": {"frame_id": "frame_0017", "timestamp": 5.688, "confidence": 0.498},
                }
                item.bio_data = bio_data
                assert isinstance(item.frame_motion_scores, dict)
                frame_motion_scores = dict(item.frame_motion_scores)
                frame_motion_scores["resolved_keyframes"] = {
                    "source": "video_ai_refined",
                    "confidence": 0.8,
                    "selected": [
                        {
                            "frame_id": "semantic_0001",
                            "timestamp": 5.187,
                            "phase_code": "takeoff",
                            "phase_label": "takeoff",
                            "key_moment": "T_takeoff_sec",
                            "selection_reason": "video_phase_range_key_moment",
                            "confidence": 0.75,
                            "pre_refine_timestamp": 5.2,
                            "refinement_method": "local_motion_peak",
                            "refinement_delta_sec": -0.013,
                        },
                        {
                            "frame_id": "semantic_0002",
                            "timestamp": 5.8,
                            "phase_code": "air",
                            "phase_label": "air",
                            "key_moment": "A_air_sec",
                            "selection_reason": "video_phase_range_key_moment",
                            "confidence": 0.8,
                            "pre_refine_timestamp": 5.8,
                            "refinement_method": "apex_preserved",
                            "refinement_delta_sec": 0.0,
                        },
                        {
                            "frame_id": "semantic_0003",
                            "timestamp": 6.167,
                            "phase_code": "landing",
                            "phase_label": "landing",
                            "key_moment": "L_landing_sec",
                            "selection_reason": "video_phase_range_key_moment",
                            "confidence": 0.8,
                            "pre_refine_timestamp": 6.4,
                            "refinement_method": "local_motion_peak",
                            "refinement_delta_sec": -0.233,
                        },
                    ],
                }
                item.frame_motion_scores = frame_motion_scores
            await session.commit()

        with (
            patch("app.routers.analysis.get_active_provider", AsyncMock(return_value=None)),
            patch("app.routers.analysis.request_text_completion", AsyncMock(return_value="")),
        ):
            async with self.database.AsyncSessionLocal() as session:
                result = await self.analysis_router.compare_analyses(older_id, newer_id, session=session)

        takeoff = result.keyframe_compare[0].before
        self.assertEqual(takeoff.source, "bio_key_frames")
        self.assertEqual(takeoff.frame_id, "semantic_0001")
        self.assertEqual(takeoff.timestamp, 5.187)
        self.assertEqual(takeoff.confidence, 0.75)
        self.assertEqual(takeoff.selection_reason, "video_phase_range_key_moment")
        self.assertEqual(takeoff.refinement_method, "local_motion_peak")
        self.assertEqual(takeoff.refinement_delta_sec, -0.013)

    async def test_compare_video_sync_derives_bio_timestamp_when_legacy_timestamp_missing(self) -> None:
        older_id = str(uuid4())
        newer_id = str(uuid4())
        skater_id = str(uuid4())
        await self._insert_analysis(
            analysis_id=older_id,
            skater_id=skater_id,
            score=70,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        await self._insert_analysis(
            analysis_id=newer_id,
            skater_id=skater_id,
            score=82,
            created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )

        async with self.database.AsyncSessionLocal() as session:
            older = await session.get(self.models.Analysis, older_id)
            newer = await session.get(self.models.Analysis, newer_id)
            assert older is not None
            assert newer is not None
            for item in (older, newer):
                assert isinstance(item.bio_data, dict)
                bio_data = dict(item.bio_data)
                bio_data.pop("key_frame_timestamps", None)
                item.bio_data = bio_data
                assert isinstance(item.frame_motion_scores, dict)
                frame_motion_scores = dict(item.frame_motion_scores)
                frame_motion_scores["resolved_keyframes"] = {
                    "selected": [
                        {"frame_id": "semantic_0001", "timestamp": 3.0, "phase_code": "takeoff"},
                        {"frame_id": "semantic_0002", "timestamp": 3.3, "phase_code": "air"},
                        {"frame_id": "semantic_0003", "timestamp": 3.6, "phase_code": "landing"},
                    ],
                }
                item.frame_motion_scores = frame_motion_scores
            await session.commit()

        with (
            patch("app.routers.analysis.get_active_provider", AsyncMock(return_value=None)),
            patch("app.routers.analysis.request_text_completion", AsyncMock(return_value="")),
        ):
            async with self.database.AsyncSessionLocal() as session:
                result = await self.analysis_router.compare_analyses(older_id, newer_id, session=session)

        self.assertIsNotNone(result.video_compare)
        assert result.video_compare is not None
        self.assertEqual(result.video_compare.sync_mode, "bio_keyframe")
        self.assertEqual(result.video_compare.before.sync_start, 0.0)
        self.assertEqual(result.video_compare.before.sync_duration, 0.9)

    async def test_compare_suppresses_report_issue_noise_for_stable_same_video_repeat(self) -> None:
        older_id = str(uuid4())
        newer_id = str(uuid4())
        skater_id = str(uuid4())
        await self._insert_analysis(
            analysis_id=older_id,
            skater_id=skater_id,
            score=77,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        await self._insert_analysis(
            analysis_id=newer_id,
            skater_id=skater_id,
            score=77,
            created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )

        async with self.database.AsyncSessionLocal() as session:
            older = await session.get(self.models.Analysis, older_id)
            newer = await session.get(self.models.Analysis, newer_id)
            assert older is not None
            assert newer is not None
            same_identity = _video_identity("same-video-sha")
            for item in (older, newer):
                assert isinstance(item.frame_motion_scores, dict)
                frame_motion_scores = dict(item.frame_motion_scores)
                frame_motion_scores["video_identity"] = same_identity
                item.frame_motion_scores = frame_motion_scores

            assert isinstance(newer.report, dict)
            report = dict(newer.report)
            report["issues"] = [
                *(report.get("issues") if isinstance(report.get("issues"), list) else []),
                {"category": "axis_control", "description": "same video report wording drift", "severity": "medium"},
            ]
            newer.report = report
            await session.commit()

        with (
            patch("app.routers.analysis.get_active_provider", AsyncMock(return_value=None)) as provider_mock,
            patch("app.routers.analysis.request_text_completion", AsyncMock(return_value="")) as completion_mock,
        ):
            async with self.database.AsyncSessionLocal() as session:
                result = await self.analysis_router.compare_analyses(older_id, newer_id, session=session)

        provider_mock.assert_not_awaited()
        completion_mock.assert_not_awaited()
        self.assertEqual(result.score_delta, 0)
        self.assertEqual(result.summary.added, [])
        self.assertEqual(result.summary.improved, [])
        self.assertTrue(any(item.category == "axis_control" for item in result.summary.unchanged))
        self.assertIsNotNone(result.quality)
        assert result.quality is not None
        self.assertTrue(any("同一原视频重复分析" in warning for warning in result.quality.warnings))

    async def test_compare_rejects_different_skater_or_subtype(self) -> None:
        first_id = str(uuid4())
        second_id = str(uuid4())
        await self._insert_analysis(
            analysis_id=first_id,
            skater_id="kid-a",
            score=70,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        await self._insert_analysis(
            analysis_id=second_id,
            skater_id="kid-b",
            score=80,
            created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        async with self.database.AsyncSessionLocal() as session:
            with self.assertRaises(Exception) as ctx:
                await self.analysis_router.compare_analyses(first_id, second_id, session=session)
        self.assertIn("同一位小朋友", str(ctx.exception))

        async with self.database.AsyncSessionLocal() as session:
            second = await session.get(self.models.Analysis, second_id)
            assert second is not None
            second.skater_id = "kid-a"
            second.action_subtype = "后外点冰跳"
            await session.commit()

        with (
            patch("app.routers.analysis.get_active_provider", AsyncMock(return_value=None)),
            patch("app.routers.analysis.request_text_completion", AsyncMock(return_value="")),
        ):
            async with self.database.AsyncSessionLocal() as session:
                result = await self.analysis_router.compare_analyses(first_id, second_id, session=session)
        self.assertIsNotNone(result.quality)
        assert result.quality is not None
        self.assertTrue(result.quality.subtype_mismatch)
        self.assertTrue(any("趋势参考" in warning for warning in result.quality.warnings))

    async def test_video_endpoint_rejects_missing_video(self) -> None:
        analysis_id = str(uuid4())
        await self._insert_analysis(
            analysis_id=analysis_id,
            skater_id="kid-a",
            score=70,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        video_path = Path(self.tmp.name) / "uploads" / analysis_id / "source.mp4"
        video_path.unlink()
        async with self.database.AsyncSessionLocal() as session:
            with self.assertRaises(Exception) as ctx:
                await self.analysis_router.get_analysis_video(analysis_id, session=session)
        self.assertIn("原视频", str(ctx.exception))


    async def test_tiny_target_pose_tracking_risk_flag_helper(self) -> None:
        target_lock = {
            "selected_bbox": {"x": 0.4, "y": 0.3, "width": 0.0205, "height": 0.0893},
            "quality_flags": ["person_tracker_target_lost"],
            "person_tracker_diagnostics": (
                [{"state": "tracked"} for _ in range(5)]
                + [{"state": "lost_reused"} for _ in range(16)]
                + [{"state": "detector_relocked"} for _ in range(2)]
            ),
        }
        pose_data = {"pose_diagnostics": {"tracked_frames": 15, "total_frames": 32}}

        flags = self.analysis_router._tiny_target_pose_tracking_risk_flags(target_lock, pose_data)

        self.assertEqual(flags, ["person_tracker_tiny_target_low_pose_tracking_risk"])

    async def test_multiperson_relock_instability_risk_flag_helper(self) -> None:
        target_lock = {
            "selected_candidate_id": "target",
            "selected_bbox": {"x": 0.43, "y": 0.2, "width": 0.095, "height": 0.375},
            "quality_flags": [
                "target_lock_zoomed_multiperson_manual_review",
                "target_lock_zoomed_multiperson_scale_competitor_manual_review",
                "person_tracker_target_lost",
                "person_tracker_relock_rejected",
            ],
            "candidates": [
                {
                    "id": "target",
                    "multiperson_ambiguous_frame_count": 9,
                    "multiperson_competitor_count": 26,
                    "multiperson_other_frame_ambiguous_count": 9,
                }
            ],
            "person_tracker_diagnostics": (
                [{"state": "tracked"} for _ in range(14)]
                + [{"state": "full_frame_yolo_relock_pending"} for _ in range(3)]
                + [{"state": "local_zoom_yolo_relock_pending"} for _ in range(2)]
                + [{"state": "relock_rejected"} for _ in range(3)]
                + [{"state": "lost_reused"} for _ in range(2)]
                + [{"state": "detector_relocked"} for _ in range(2)]
                + [{"state": "relocked"}]
            ),
        }
        pose_data = {"pose_diagnostics": {"tracked_frames": 17, "total_frames": 32}}

        flags = self.analysis_router._multiperson_relock_instability_risk_flags(target_lock, pose_data)

        self.assertEqual(flags, ["person_tracker_multiperson_relock_instability_risk"])

    async def test_tiny_target_pose_tracking_risk_helper_ignores_stable_large_target(self) -> None:
        target_lock = {
            "selected_bbox": {"x": 0.35, "y": 0.2, "width": 0.12, "height": 0.48},
            "quality_flags": [],
            "person_tracker_diagnostics": [{"state": "tracked"} for _ in range(24)],
        }
        pose_data = {"pose_diagnostics": {"tracked_frames": 24, "total_frames": 24}}

        flags = self.analysis_router._tiny_target_pose_tracking_risk_flags(target_lock, pose_data)

        self.assertEqual(flags, [])


if __name__ == "__main__":
    unittest.main()
