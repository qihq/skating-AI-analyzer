from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class MonthlyFactsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        os.environ["DATA_DIR"] = self.tmpdir.name
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(self.tmpdir.name) / 'test.db'}"
        for module_name in [
            "app.database",
            "app.models",
            "app.services.pipeline_version",
            "app.services.monthly_facts",
        ]:
            sys.modules.pop(module_name, None)
        app_pkg = sys.modules.get("app")
        if app_pkg is not None:
            for attr in ("database", "models"):
                if hasattr(app_pkg, attr):
                    delattr(app_pkg, attr)

        import app.database as database
        import app.models as models

        self.database = database
        self.models = models
        database.ensure_storage_dirs()
        await database.init_db()

    async def asyncTearDown(self) -> None:
        await self.database.engine.dispose()
        self.tmpdir.cleanup()

    def _analysis(self, **kwargs) -> "object":
        base = dict(
            skater_id="skater-1",
            action_type="跳跃",
            action_subtype="Waltz",
            video_path="x.mp4",
            status="completed",
        )
        base.update(kwargs)
        base.setdefault("created_at", datetime(2026, 7, 15, tzinfo=timezone.utc))
        return self.models.Analysis(id=base.pop("id"), **base)

    async def _snapshot(self, **kwargs) -> dict:
        from app.services.monthly_facts import build_monthly_fact_snapshot

        async with self.database.AsyncSessionLocal() as session:
            return await build_monthly_fact_snapshot(
                session,
                kwargs.pop("skater_id", "skater-1"),
                kwargs.pop("year_month", "2026-07"),
                now=kwargs.pop("now", datetime(2026, 7, 31, tzinfo=timezone.utc)),
            )

    async def test_only_counts_completed_analyses_within_calendar_month(self) -> None:
        async with self.database.AsyncSessionLocal() as session:
            session.add(self.models.Skater(id="skater-1", name="tantan"))
            session.add_all([
                self._analysis(id="a-june", status="completed", created_at=datetime(2026, 6, 20, tzinfo=timezone.utc)),
                self._analysis(id="a-july-1", status="completed", created_at=datetime(2026, 7, 5, tzinfo=timezone.utc)),
                self._analysis(id="a-july-2", status="completed", created_at=datetime(2026, 7, 28, tzinfo=timezone.utc)),
                self._analysis(id="a-failed", status="failed", created_at=datetime(2026, 7, 10, tzinfo=timezone.utc)),
            ])
            await session.commit()

        snap = await self._snapshot()
        self.assertEqual(snap["schema_version"], "monthly_facts.v1")
        self.assertEqual(snap["skater_id"], "skater-1")
        self.assertEqual(snap["year_month"], "2026-07")
        self.assertEqual(snap["coverage"]["completed_analyses"], 2)
        session_count = next(f for f in snap["facts"] if f["id"] == "session_count")
        # distinct training sessions within the month (none explicitly attached)
        self.assertEqual(session_count["value"], 0)

    async def test_session_count_is_distinct_sessions(self) -> None:
        async with self.database.AsyncSessionLocal() as session:
            session.add(self.models.Skater(id="skater-1", name="tantan"))
            session.add_all([
                self.models.TrainingSession(id="s-1", skater_id="skater-1", session_date=date(2026, 7, 3)),
                self.models.TrainingSession(id="s-2", skater_id="skater-1", session_date=date(2026, 7, 15)),
                self.models.TrainingSession(id="s-3", skater_id="skater-1", session_date=date(2026, 6, 28)),
                self._analysis(id="a-1", skater_id="skater-1", session_id="s-1", action_type="跳跃",
                               action_subtype="Waltz", status="completed",
                               created_at=datetime(2026, 7, 3, tzinfo=timezone.utc)),
                self._analysis(id="a-2", skater_id="skater-1", session_id="s-1", action_type="跳跃",
                               action_subtype="Waltz", status="completed",
                               created_at=datetime(2026, 7, 3, 12, tzinfo=timezone.utc)),
                self._analysis(id="a-3", skater_id="skater-1", session_id="s-2", action_type="跳跃",
                               action_subtype="Waltz", status="completed",
                               created_at=datetime(2026, 7, 15, tzinfo=timezone.utc)),
                self._analysis(id="a-4", skater_id="skater-1", session_id="s-3", action_type="跳跃",
                               action_subtype="Waltz", status="completed",
                               created_at=datetime(2026, 7, 1, tzinfo=timezone.utc)),
            ])
            await session.commit()

        snap = await self._snapshot()
        # sessions within July that have a completed analysis: s-1 and s-2 (s-3 created_at July but session_date is June; counted by session_date in month)
        session_count = next(f for f in snap["facts"] if f["id"] == "session_count")
        self.assertEqual(session_count["value"], 2)
        self.assertEqual(snap["coverage"]["sessions"], 2)

    async def test_milestone_facts_from_unlocks_within_month(self) -> None:
        async with self.database.AsyncSessionLocal() as session:
            session.add(self.models.Skater(id="skater-1", name="tantan"))
            session.add_all([
                self.models.SkillNode(
                    id="skill-waltz", chapter="fs1", chapter_order=1, stage=1,
                    stage_name="Basics", group_name="Jumps", sort_order=1, name="Waltz jump", xp=100,
                ),
                self.models.SkillNode(
                    id="skill-cross", chapter="fs1", chapter_order=1, stage=1,
                    stage_name="Basics", group_name="Skating", sort_order=2, name="Back crossovers", xp=100,
                ),
            ])
            await session.flush()
            session.add_all([
                self.models.SkaterSkill(
                    id="p-1", skater_id="skater-1", skill_id="skill-waltz",
                    status="unlocked", unlocked_by="parent", unlocked_at=datetime(2026, 7, 12, tzinfo=timezone.utc),
                ),
                self._analysis(id="a-unlock", skater_id="skater-1", action_type="跳跃",
                               action_subtype="Waltz", status="completed", auto_unlocked_skill="skill-waltz",
                               created_at=datetime(2026, 7, 12, tzinfo=timezone.utc)),
                # unlocked in June -> excluded from the month
                self.models.SkaterSkill(
                    id="p-2", skater_id="skater-1", skill_id="skill-cross",
                    status="unlocked", unlocked_by="auto", unlocked_at=datetime(2026, 6, 5, tzinfo=timezone.utc),
                ),
            ])
            await session.commit()

        snap = await self._snapshot()
        milestone_facts = [f for f in snap["facts"] if f["kind"] == "milestone"]
        self.assertEqual(len(milestone_facts), 1)
        self.assertEqual(milestone_facts[0]["verification"], "parent_confirmed")
        self.assertEqual(milestone_facts[0]["skill_id"], "skill-waltz")
        self.assertEqual(milestone_facts[0]["source_analysis_ids"], ["a-unlock"])

    async def test_quote_facts_retain_speaker(self) -> None:
        async with self.database.AsyncSessionLocal() as session:
            session.add(self.models.Skater(id="skater-1", name="tantan"))
            session.add_all([
                self._analysis(id="a-q1", highlight_quote="我今天敢往后滑了", quote_speaker="skater",
                               status="completed", created_at=datetime(2026, 7, 10, tzinfo=timezone.utc)),
                self._analysis(id="a-q2", highlight_quote="孩子今天进步很大", quote_speaker="parent",
                               status="completed", created_at=datetime(2026, 7, 11, tzinfo=timezone.utc)),
            ])
            await session.commit()

        snap = await self._snapshot()
        quote_facts = [f for f in snap["facts"] if f["kind"] == "quote"]
        self.assertEqual({f["speaker"] for f in quote_facts}, {"skater", "parent"})
        self.assertEqual({f["text"] for f in quote_facts}, {"我今天敢往后滑了", "孩子今天进步很大"})
        for fact in quote_facts:
            self.assertTrue(fact["id"].startswith("quote:"))

    async def test_recurring_observation_requires_two_nonpoor_reports(self) -> None:
        async with self.database.AsyncSessionLocal() as session:
            session.add(self.models.Skater(id="skater-1", name="tantan"))
            session.add_all([
                self._analysis(id="a-r1",
                              report={"data_quality": "good", "issues": [{"category": "落冰", "description": "落冰偏左", "severity": "medium"}],
                                      "training_focus": "落冰", "summary": "ok"},
                              status="completed", created_at=datetime(2026, 7, 4, tzinfo=timezone.utc)),
                self._analysis(id="a-r2",
                              report={"data_quality": "partial", "issues": [{"category": "落冰", "description": "又偏了", "severity": "medium"}],
                                      "training_focus": "落冰", "summary": "ok"},
                              status="completed", created_at=datetime(2026, 7, 11, tzinfo=timezone.utc)),
                # poor quality -> not counted
                self._analysis(id="a-r3",
                              report={"data_quality": "poor", "issues": [{"category": "起跳", "description": "x", "severity": "medium"}],
                                      "training_focus": "起跳", "summary": "ok"},
                              status="completed", created_at=datetime(2026, 7, 18, tzinfo=timezone.utc)),
            ])
            await session.commit()

        snap = await self._snapshot()
        recurring = [f for f in snap["facts"] if f["kind"] == "observation"]
        self.assertEqual(len(recurring), 1)
        self.assertEqual(recurring[0]["category"], "落冰")
        # training_focus also tracked when two nonpoor reports share it -> focus fact
        focus_facts = [f for f in snap["facts"] if f["id"] == "training_focus"]
        self.assertTrue(focus_facts)

    async def test_comparable_metric_only_when_two_records_share_subtype_and_acceptable_quality(self) -> None:
        async with self.database.AsyncSessionLocal() as session:
            session.add(self.models.Skater(id="skater-1", name="tantan"))
            session.add_all([
                self._analysis(id="a-m1", action_subtype="Waltz",
                              bio_data={"jump_metrics": {"air_time_seconds": 0.40, "estimated_height_cm": 8.0},
                                        "jump_metrics_status": "ok"},
                              report={"data_quality": "good"}, status="completed",
                              created_at=datetime(2026, 7, 3, tzinfo=timezone.utc)),
                self._analysis(id="a-m2", action_subtype="Waltz",
                              bio_data={"jump_metrics": {"air_time_seconds": 0.50, "estimated_height_cm": 11.0},
                                        "jump_metrics_status": "ok"},
                              report={"data_quality": "partial"}, status="completed",
                              created_at=datetime(2026, 7, 17, tzinfo=timezone.utc)),
                # only one record for Loop -> not eligible
                self._analysis(id="a-m3", action_subtype="Loop",
                              bio_data={"jump_metrics": {"air_time_seconds": 0.45, "estimated_height_cm": 9.0},
                                        "jump_metrics_status": "ok"},
                              report={"data_quality": "good"}, status="completed",
                              created_at=datetime(2026, 7, 9, tzinfo=timezone.utc)),
            ])
            await session.commit()

        snap = await self._snapshot()
        metric_facts = [f for f in snap["facts"] if f["kind"] == "metric"]
        # air_time_seconds and estimated_height_cm both eligible for Waltz
        self.assertEqual(len(metric_facts), 2)
        names = {f["metric"] for f in metric_facts}
        self.assertEqual(names, {"air_time_seconds", "estimated_height_cm"})
        for fact in metric_facts:
            self.assertEqual(fact["action_subtype"], "Waltz")
            self.assertGreaterEqual(fact["sample_count"], 2)
            self.assertIn("before", fact)
            self.assertIn("after", fact)
            self.assertIn("source_analysis_ids", fact)

    async def test_fact_order_is_deterministic(self) -> None:
        async with self.database.AsyncSessionLocal() as session:
            session.add(self.models.Skater(id="skater-1", name="tantan"))
            session.add(self.models.SkillNode(
                id="skill-waltz", chapter="fs1", chapter_order=1, stage=1,
                stage_name="Basics", group_name="Jumps", sort_order=1, name="Waltz jump", xp=100,
            ))
            await session.flush()
            session.add_all([
                self.models.SkaterSkill(
                    id="p-1", skater_id="skater-1", skill_id="skill-waltz",
                    status="unlocked", unlocked_by="parent", unlocked_at=datetime(2026, 7, 12, tzinfo=timezone.utc),
                ),
                self._analysis(id="a-1", action_subtype="Waltz",
                              highlight_quote="我今天敢往后滑了", quote_speaker="skater",
                              bio_data={"jump_metrics": {"air_time_seconds": 0.40}, "jump_metrics_status": "ok"},
                              report={"data_quality": "good", "issues": [{"category": "落冰", "description": "x", "severity": "medium"}],
                                      "training_focus": "落冰", "summary": "ok"},
                              status="completed", created_at=datetime(2026, 7, 12, tzinfo=timezone.utc)),
                self._analysis(id="a-2", action_subtype="Waltz",
                              bio_data={"jump_metrics": {"air_time_seconds": 0.50}, "jump_metrics_status": "ok"},
                              report={"data_quality": "good", "issues": [{"category": "落冰", "description": "y", "severity": "medium"}],
                                      "training_focus": "落冰", "summary": "ok"},
                              status="completed", created_at=datetime(2026, 7, 14, tzinfo=timezone.utc)),
            ])
            await session.commit()

        snap1 = await self._snapshot()
        snap2 = await self._snapshot()
        order = [f["kind"] for f in snap1["facts"]]
        # counts, metric, milestone, observation, quote ordering
        self.assertEqual(order[0], "count")
        self.assertIn("metric", order)
        self.assertIn("milestone", order)
        self.assertIn("observation", order)
        self.assertEqual(order[-1], "quote")
        self.assertEqual([f["id"] for f in snap1["facts"]], [f["id"] for f in snap2["facts"]])

    async def test_hash_is_stable_for_unchanged_sources(self) -> None:
        async with self.database.AsyncSessionLocal() as session:
            session.add(self.models.Skater(id="skater-1", name="tantan"))
            session.add_all([
                self._analysis(id="a-1", status="completed", created_at=datetime(2026, 7, 4, tzinfo=timezone.utc)),
                self._analysis(id="a-2", status="completed", created_at=datetime(2026, 7, 9, tzinfo=timezone.utc)),
            ])
            await session.commit()

        from app.services.monthly_facts import monthly_source_hash

        snap1 = await self._snapshot()
        snap2 = await self._snapshot()
        h1 = monthly_source_hash(snap1)
        h2 = monthly_source_hash(snap2)
        self.assertEqual(h1, h2)
        # generated_at is part of the snapshot but excluded from the hash
        self.assertIn("generated_at", snap1)
        import app.services.monthly_facts as mf

        canonical = mf._canonical_snapshot_for_hash(snap1)
        self.assertNotIn("generated_at", canonical)

    async def test_insufficient_quality_flag_when_no_trend(self) -> None:
        async with self.database.AsyncSessionLocal() as session:
            session.add(self.models.Skater(id="skater-1", name="tantan"))
            session.add_all([
                # single poor report, no reliable trend
                self._analysis(id="a-1",
                              report={"data_quality": "poor", "summary": "ok", "training_focus": "x"},
                              status="completed", created_at=datetime(2026, 7, 4, tzinfo=timezone.utc)),
            ])
            await session.commit()

        snap = await self._snapshot()
        self.assertIn("insufficient_comparable_evidence", snap["quality_flags"])

    async def test_invalid_year_month_raises(self) -> None:
        from fastapi import HTTPException
        from app.services.monthly_facts import build_monthly_fact_snapshot

        async with self.database.AsyncSessionLocal() as session:
            with self.assertRaises(HTTPException) as ctx:
                await build_monthly_fact_snapshot(session, "skater-1", "2026-7", now=datetime(2026, 7, 31, tzinfo=timezone.utc))
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_representative_frames_capped_at_four(self) -> None:
        async with self.database.AsyncSessionLocal() as session:
            session.add(self.models.Skater(id="skater-1", name="tantan"))
            for index in range(6):
                session.add(self._analysis(
                    id=f"a-rf{index}",
                    bio_data={"key_frames": {"T": f"frame_{index}_t", "A": f"frame_{index}_a", "L": f"frame_{index}_l"},
                              "key_frame_timestamps": {"T": 0.1, "A": 0.2, "L": 0.3},
                              "key_frame_candidates": {
                                  "L": {"frame_id": f"frame_{index}_l", "timestamp": 0.3, "confidence": 0.8},
                              },
                              "jump_metrics_status": "ok"},
                    report={"data_quality": "good"}, status="completed",
                    created_at=datetime(2026, 7, 1 + index, tzinfo=timezone.utc),
                    auto_unlocked_skill=None,
                ))
            await session.commit()

        snap = await self._snapshot()
        self.assertLessEqual(len(snap["representative_frames"]), 4)
        for frame in snap["representative_frames"]:
            self.assertIn("analysis_id", frame)
            self.assertIn("frame_id", frame)
            self.assertIn("timestamp", frame)
            self.assertIn("phase", frame)
            self.assertIn("evidence_source", frame)