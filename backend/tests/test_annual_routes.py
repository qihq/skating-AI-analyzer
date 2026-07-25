from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch


class AnnualRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        os.environ["DATA_DIR"] = self.tmpdir.name
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(self.tmpdir.name) / 'test.db'}"
        for name in ["app.database", "app.models", "app.schemas", "app.services.annual_collections", "app.routers.annual"]:
            sys.modules.pop(name, None)
        import app.database as database
        import app.models as models
        from app.services.auth import hash_pin

        self.database = database
        self.models = models
        database.ensure_storage_dirs()
        await database.init_db()
        from app.services.monthly_facts import monthly_source_hash

        facts = {"schema_version": "monthly_facts.v1", "coverage": {}, "facts": [], "representative_frames": []}
        async with database.AsyncSessionLocal() as session:
            session.add(models.Skater(id="skater-1", name="Tantan"))
            session.add(models.ParentAuth(pin_hash=hash_pin("1234"), pin_length=4))
            session.add(models.MonthlyChapter(
                id="chapter-1", skater_id="skater-1", year_month="2026-01", revision=1,
                status="published", fact_snapshot=facts,
                source_hash=monthly_source_hash(facts), final_text="Published chapter", representative_frames=[],
                published_at=datetime(2026, 1, 31, tzinfo=timezone.utc),
            ))
            await session.commit()

    async def asyncTearDown(self) -> None:
        await self.database.engine.dispose()
        self.tmpdir.cleanup()

    async def test_preview_create_export_and_download(self) -> None:
        import app.routers.annual as annual
        from app.schemas import AnnualCollectionCreateRequest

        request = AnnualCollectionCreateRequest(chapter_ids=["chapter-1"], milestone_ids=[])
        async with self.database.AsyncSessionLocal() as session:
            preview = await annual.preview_collection("skater-1", 2026, request, session=session)
            self.assertEqual(preview.coverage["published_chapter_count"], 1)
            collection = await annual.create_collection("skater-1", 2026, request, x_parent_pin="1234", session=session)
            self.assertEqual(collection.status, "ready")
            self.assertEqual(collection.revision, 1)

        with patch("app.routers.annual.run_export", new=AsyncMock()) as run_export:
            async with self.database.AsyncSessionLocal() as session:
                export = await annual.create_export(collection.id, background_tasks=_BackgroundTasksStub(), x_parent_pin="1234", session=session)
            self.assertEqual(export.status, "pending")
            run_export.assert_not_awaited()

        asset_root = annual.ANNUAL_ASSET_ROOT
        relative_path = Path("annual") / collection.id / f"{export.id}.pdf"
        file_path = asset_root / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(b"%PDF-1.4\n")
        async with self.database.AsyncSessionLocal() as session:
            row = await session.get(self.models.AnnualExport, export.id)
            assert row is not None
            row.status = "completed"
            row.asset_relative_path = relative_path.as_posix()
            row.completed_at = datetime.now(timezone.utc)
            await session.commit()

        async with self.database.AsyncSessionLocal() as session:
            response = await annual.download_export(export.id, session=session)
        self.assertIn("attachment", response.headers["content-disposition"])

    async def test_download_rejects_path_outside_annual_root(self) -> None:
        import app.routers.annual as annual
        from fastapi import HTTPException

        async with self.database.AsyncSessionLocal() as session:
            collection = self.models.AnnualCollection(
                id="collection-1", skater_id="skater-1", year=2026, revision=1, status="ready", title="Annual",
                selected_chapter_ids=[], selected_milestone_ids=[], snapshot={}, source_hash="a" * 64,
            )
            session.add(collection)
            session.add(self.models.AnnualExport(
                id="export-1", collection_id="collection-1", status="completed", renderer_version="annual_pdf.v1",
                asset_relative_path="../../escape.pdf", file_sha256="a" * 64, page_count=1,
            ))
            await session.commit()

        async with self.database.AsyncSessionLocal() as session:
            with self.assertRaises(HTTPException) as raised:
                await annual.download_export("export-1", session=session)
        self.assertEqual(raised.exception.status_code, 404)

    async def test_missing_completed_asset_creates_a_rebuild_job(self) -> None:
        import app.routers.annual as annual

        async with self.database.AsyncSessionLocal() as session:
            collection = self.models.AnnualCollection(
                id="collection-missing", skater_id="skater-1", year=2026, revision=1, status="exported", title="Annual",
                selected_chapter_ids=["chapter-1"], selected_milestone_ids=[], snapshot={}, source_hash="a" * 64,
            )
            session.add(collection)
            session.add(self.models.AnnualExport(
                id="export-missing", collection_id=collection.id, status="completed", renderer_version="annual_pdf.v1",
                asset_relative_path="annual/collection-missing/export-missing.pdf", file_sha256="a" * 64, page_count=1,
            ))
            await session.commit()

        async with self.database.AsyncSessionLocal() as session:
            created = await annual.create_export("collection-missing", background_tasks=_BackgroundTasksStub(), x_parent_pin="1234", session=session)
            missing = await session.get(self.models.AnnualExport, "export-missing")
            assert missing is not None
            self.assertEqual(missing.status, "failed")
        self.assertNotEqual(created.id, "export-missing")
        self.assertEqual(created.status, "pending")

    async def test_lists_only_the_selected_years_milestones(self) -> None:
        import app.routers.annual as annual

        async with self.database.AsyncSessionLocal() as session:
            session.add_all([
                self.models.SkillNode(id="skill-1", chapter="c", chapter_order=1, stage=1, stage_name="Basics", group_name="Jumps", sort_order=1, name="Waltz", xp=1),
                self.models.SkillNode(id="skill-2", chapter="c", chapter_order=1, stage=1, stage_name="Basics", group_name="Jumps", sort_order=2, name="Old", xp=1),
            ])
            session.add_all([
                self.models.SkaterSkill(id="milestone-2026", skater_id="skater-1", skill_id="skill-1", status="unlocked", unlocked_by="parent", unlocked_at=datetime(2026, 3, 1, tzinfo=timezone.utc)),
                self.models.SkaterSkill(id="milestone-2025", skater_id="skater-1", skill_id="skill-2", status="unlocked", unlocked_by="parent", unlocked_at=datetime(2025, 3, 1, tzinfo=timezone.utc)),
            ])
            await session.commit()

        async with self.database.AsyncSessionLocal() as session:
            items = await annual.list_milestones("skater-1", 2026, session=session)
        self.assertEqual([item.id for item in items], ["milestone-2026"])

    async def test_run_export_marks_renderer_failure_and_recovery_requeues_incomplete_jobs(self) -> None:
        import app.routers.annual as annual

        async with self.database.AsyncSessionLocal() as session:
            collection = self.models.AnnualCollection(
                id="collection-export", skater_id="skater-1", year=2026, revision=1, status="ready", title="Annual",
                selected_chapter_ids=["chapter-1"], selected_milestone_ids=[], snapshot={}, source_hash="a" * 64,
            )
            session.add(collection)
            session.add_all([
                self.models.AnnualExport(id="export-failure", collection_id=collection.id, status="pending", renderer_version="annual_pdf.v1"),
                self.models.AnnualExport(id="export-recover", collection_id=collection.id, status="processing", renderer_version="annual_pdf.v1"),
            ])
            await session.commit()

        with patch("app.routers.annual.render_annual_pdf", side_effect=RuntimeError("renderer down")):
            await annual.run_export("export-failure")
        async with self.database.AsyncSessionLocal() as session:
            failed = await session.get(self.models.AnnualExport, "export-failure")
            assert failed is not None
            self.assertEqual(failed.status, "failed")

        enqueue = AsyncMock()
        recovered = await annual.recover_incomplete_exports(enqueue=enqueue)
        self.assertEqual(recovered, ["export-recover"])
        enqueue.assert_awaited_once_with("export-recover")
        async with self.database.AsyncSessionLocal() as session:
            recovered_export = await session.get(self.models.AnnualExport, "export-recover")
            assert recovered_export is not None
            self.assertEqual(recovered_export.status, "pending")

    async def test_revision_recycle_restore_and_permanent_delete(self) -> None:
        import app.routers.annual as annual
        from app.schemas import AnnualCollectionCreateRequest, AnnualCollectionRevisionRequest

        async with self.database.AsyncSessionLocal() as session:
            original = await annual.create_collection(
                "skater-1", 2026,
                AnnualCollectionCreateRequest(title="原年度报告", chapter_ids=["chapter-1"], milestone_ids=[]),
                x_parent_pin="1234",
                session=session,
            )
            revised = await annual.revise_collection(
                original.id,
                AnnualCollectionRevisionRequest(title="修订年度报告", chapter_ids=["chapter-1"], milestone_ids=[]),
                x_parent_pin="1234",
                session=session,
            )
            original_row = await session.get(self.models.AnnualCollection, original.id)
            assert original_row is not None
            self.assertEqual(original_row.title, "原年度报告")
            self.assertEqual(revised.parent_revision_id, original.id)
            self.assertEqual(revised.revision, 2)

        async with self.database.AsyncSessionLocal() as session:
            await annual.recycle_collection(revised.id, x_parent_pin="1234", session=session)
            active = await annual.list_collections("skater-1", 2026, recycled=False, session=session)
            recycled = await annual.list_collections("skater-1", 2026, recycled=True, session=session)
            self.assertEqual([item.id for item in active], [original.id])
            self.assertEqual([item.id for item in recycled], [revised.id])
            await annual.restore_collection(revised.id, x_parent_pin="1234", session=session)
            await annual.recycle_collection(revised.id, x_parent_pin="1234", session=session)
            await annual.permanently_delete_collection(revised.id, x_parent_pin="1234", session=session)
            self.assertIsNone(await session.get(self.models.AnnualCollection, revised.id))

    async def test_mutation_requires_a_valid_parent_pin(self) -> None:
        import app.routers.annual as annual
        from app.schemas import AnnualCollectionCreateRequest
        from fastapi import HTTPException

        request = AnnualCollectionCreateRequest(chapter_ids=["chapter-1"], milestone_ids=[])
        async with self.database.AsyncSessionLocal() as session:
            for pin in (None, "9999"):
                with self.assertRaises(HTTPException) as raised:
                    await annual.create_collection("skater-1", 2026, request, x_parent_pin=pin, session=session)
                self.assertEqual(raised.exception.status_code, 403)
            created = await annual.create_collection("skater-1", 2026, request, x_parent_pin="1234", session=session)
            self.assertEqual(created.status, "ready")

    async def test_permanent_delete_keeps_records_when_asset_removal_fails(self) -> None:
        import app.routers.annual as annual
        from fastapi import HTTPException

        relative_path = "annual/collection-delete/export-delete.pdf"
        asset_path = annual.ANNUAL_ASSET_ROOT / relative_path
        asset_path.parent.mkdir(parents=True, exist_ok=True)
        asset_path.write_bytes(b"%PDF-1.4\n")
        async with self.database.AsyncSessionLocal() as session:
            collection = self.models.AnnualCollection(
                id="collection-delete", skater_id="skater-1", year=2026, revision=1, status="exported",
                title="Annual", selected_chapter_ids=[], selected_milestone_ids=[], snapshot={},
                source_hash="a" * 64, deleted_at=datetime.now(timezone.utc),
            )
            session.add(collection)
            session.add(self.models.AnnualExport(
                id="export-delete", collection_id=collection.id, status="completed",
                renderer_version="annual_pdf.v1", asset_relative_path=relative_path,
            ))
            await session.commit()
            collection_id = collection.id
            with patch("pathlib.Path.unlink", side_effect=OSError("permission denied")):
                with self.assertRaises(HTTPException) as raised:
                    await annual.permanently_delete_collection(collection_id, x_parent_pin="1234", session=session)
            self.assertEqual(raised.exception.status_code, 500)
            self.assertIsNotNone(await session.get(self.models.AnnualCollection, collection_id))
            self.assertIsNotNone(await session.get(self.models.AnnualExport, "export-delete"))

    async def test_export_deduplicates_active_job_and_force_creates_new_job(self) -> None:
        import app.routers.annual as annual

        async with self.database.AsyncSessionLocal() as session:
            session.add(self.models.AnnualCollection(
                id="collection-dedup", skater_id="skater-1", year=2026, revision=1,
                status="ready", title="Annual", selected_chapter_ids=["chapter-1"],
                selected_milestone_ids=[], snapshot={}, source_hash="a" * 64,
            ))
            session.add(self.models.AnnualExport(
                id="export-active", collection_id="collection-dedup", status="pending", renderer_version="annual_pdf.v1",
            ))
            await session.commit()
            deduplicated = await annual.create_export(
                "collection-dedup", background_tasks=_BackgroundTasksStub(), force=True, x_parent_pin="1234", session=session,
            )
            self.assertEqual(deduplicated.id, "export-active")
            active = await session.get(self.models.AnnualExport, "export-active")
            assert active is not None
            active.status = "completed"
            active.asset_relative_path = "annual/collection-dedup/export-active.pdf"
            await session.commit()
            forced = await annual.create_export(
                "collection-dedup", background_tasks=_BackgroundTasksStub(), force=True, x_parent_pin="1234", session=session,
            )
            self.assertNotEqual(forced.id, "export-active")
            self.assertEqual(forced.status, "pending")


class _BackgroundTasksStub:
    def add_task(self, *args, **kwargs) -> None:
        self.task = (args, kwargs)


if __name__ == "__main__":
    unittest.main()
