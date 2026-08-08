from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


class ProviderRouteAuthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        os.environ["DATA_DIR"] = self.tmpdir.name
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(self.tmpdir.name) / 'test.db'}"
        os.environ["SECRET_KEY"] = "test-secret-key-for-provider-route-auth"
        for module_name in [
            "app.database",
            "app.models",
            "app.schemas",
            "app.routers.providers",
            "app.services.vision_vote_config",
        ]:
            sys.modules.pop(module_name, None)

        import app.database as database
        import app.models as models
        from app.services.auth import hash_pin

        self.database = database
        self.models = models
        database.ensure_storage_dirs()
        await database.init_db()
        async with database.AsyncSessionLocal() as session:
            session.add(models.ParentAuth(pin_hash=hash_pin("1234"), pin_length=4))
            session.add_all(
                [
                    models.AIProvider(
                        id="report-1",
                        slot="report",
                        name="Report",
                        provider="qwen",
                        base_url="https://example.com/v1",
                        model_id="report-model",
                        api_key="encrypted-report-key",
                        is_active=True,
                    ),
                    models.AIProvider(
                        id="vision-1",
                        slot="vision",
                        name="Vision",
                        provider="qwen",
                        base_url="https://example.com/v1",
                        model_id="vision-model",
                        api_key="encrypted-vision-key",
                        is_active=True,
                    ),
                    models.AIProvider(
                        id="vision-2",
                        slot="vision",
                        name="Vision backup",
                        provider="qwen",
                        base_url="https://example.com/v1",
                        model_id="vision-model-2",
                        api_key="encrypted-vision-key-2",
                        is_active=False,
                    ),
                ]
            )
            await session.commit()

        import app.routers.providers as providers

        self.router = providers

    async def asyncTearDown(self) -> None:
        await self.database.engine.dispose()
        self.tmpdir.cleanup()

    async def test_sensitive_reads_and_mutations_require_parent_pin(self) -> None:
        from fastapi import HTTPException
        from app.schemas import ProviderCreate, ProviderUpdate

        create_payload = ProviderCreate(
            slot="report",
            name="New report",
            provider="qwen",
            base_url="https://example.com/v1",
            model_id="new-model",
            api_key="new-key",
        )

        async with self.database.AsyncSessionLocal() as session:
            calls = [
                lambda: self.router.list_providers(x_parent_pin=None, session=session),
                lambda: self.router.get_provider_metrics(x_parent_pin="9999", session=session),
                lambda: self.router.get_vision_vote_config(x_parent_pin=None, session=session),
                lambda: self.router.get_active_provider("report", x_parent_pin="9999", session=session),
                lambda: self.router.create_provider(create_payload, x_parent_pin=None, session=session),
                lambda: self.router.update_provider("report-1", ProviderUpdate(name="Nope"), x_parent_pin="9999", session=session),
                lambda: self.router.activate_provider_route("vision-2", x_parent_pin=None, session=session),
                lambda: self.router.delete_provider("vision-2", x_parent_pin="9999", session=session),
                lambda: self.router.test_provider("report-1", x_parent_pin=None, session=session),
            ]
            for call in calls:
                with self.subTest(call=call):
                    with self.assertRaises(HTTPException) as raised:
                        await call()
                    self.assertEqual(raised.exception.status_code, 403)

    async def test_valid_parent_pin_allows_provider_settings_and_vote_config(self) -> None:
        from app.schemas import ProviderCreate, ProviderUpdate, VisionVoteConfig

        async with self.database.AsyncSessionLocal() as session:
            providers = await self.router.list_providers(x_parent_pin="1234", session=session)
            self.assertEqual({item.id for item in providers}, {"report-1", "vision-1", "vision-2"})
            self.assertEqual((await self.router.get_provider_metrics(x_parent_pin="1234", session=session)), [])
            config = await self.router.get_vision_vote_config(x_parent_pin="1234", session=session)
            self.assertFalse(config.applies_to_v2_fusion)

            updated_config = await self.router.update_vision_vote_config(
                VisionVoteConfig(primary_provider_id="vision-1", secondary_provider_id="vision-2"),
                x_parent_pin="1234",
                session=session,
            )
            self.assertEqual(updated_config.primary_provider_id, "vision-1")
            self.assertFalse(updated_config.applies_to_v2_fusion)

            created = await self.router.create_provider(create_payload := ProviderCreate(
                slot="report",
                name="New report",
                provider="qwen",
                base_url="https://example.com/v1",
                model_id="new-model",
                api_key="new-key",
            ), x_parent_pin="1234", session=session)
            changed = await self.router.update_provider(
                created.id,
                ProviderUpdate(name="Changed report"),
                x_parent_pin="1234",
                session=session,
            )
            self.assertEqual(changed.name, "Changed report")
            activated = await self.router.activate_provider_route("vision-2", x_parent_pin="1234", session=session)
            self.assertTrue(activated.is_active)

            with patch.object(self.router, "test_provider_connectivity", new=AsyncMock(return_value=(True, "ok"))):
                tested = await self.router.test_provider("report-1", x_parent_pin="1234", session=session)
            self.assertTrue(tested.success)

            response = await self.router.delete_provider(created.id, x_parent_pin="1234", session=session)
            self.assertEqual(response.status_code, 204)


if __name__ == "__main__":
    unittest.main()
