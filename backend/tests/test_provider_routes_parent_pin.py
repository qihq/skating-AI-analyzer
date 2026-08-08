from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class ProviderRouteParentPinTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        os.environ["DATA_DIR"] = self.tmpdir.name
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(self.tmpdir.name) / 'test.db'}"
        self._previous_secret_key = os.environ.get("SECRET_KEY")
        os.environ["SECRET_KEY"] = "provider-route-test-secret-key"
        for name in (
            "app.database",
            "app.models",
            "app.schemas",
            "app.routers.providers",
        ):
            sys.modules.pop(name, None)

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
                        id="provider-active",
                        slot="vision",
                        name="Vision active",
                        provider="qwen",
                        base_url="https://example.test/v1",
                        model_id="vision-a",
                        api_key="encrypted-key-a",
                        is_active=True,
                    ),
                    models.AIProvider(
                        id="provider-secondary",
                        slot="vision",
                        name="Vision secondary",
                        provider="qwen",
                        base_url="https://example.test/v1",
                        model_id="vision-b",
                        api_key="encrypted-key-b",
                        is_active=False,
                    ),
                ]
            )
            await session.commit()

        import app.routers.providers as providers

        self.router = providers

    async def asyncTearDown(self) -> None:
        await self.database.engine.dispose()
        if self._previous_secret_key is None:
            os.environ.pop("SECRET_KEY", None)
        else:
            os.environ["SECRET_KEY"] = self._previous_secret_key
        self.tmpdir.cleanup()

    async def _session(self):
        return self.database.AsyncSessionLocal()

    async def test_all_sensitive_provider_routes_reject_missing_and_wrong_pin(self) -> None:
        from app.schemas import ProviderCreate, ProviderUpdate, VisionVoteConfig

        async with self.database.AsyncSessionLocal() as session:
            calls = (
                (self.router.list_providers, (), {}),
                (self.router.get_provider_metrics, (), {}),
                (self.router.get_vision_vote_config, (), {}),
                (self.router.update_vision_vote_config, (VisionVoteConfig(primary_provider_id=None, secondary_provider_id=None),), {}),
                (self.router.get_active_provider, ("vision",), {}),
                (
                    self.router.create_provider,
                    (
                        ProviderCreate(
                            slot="report",
                            name="Report",
                            provider="qwen",
                            base_url="https://example.test/v1",
                            model_id="report-a",
                            api_key="secret",
                        ),
                    ),
                    {},
                ),
                (self.router.update_provider, ("provider-secondary", ProviderUpdate(model_id="vision-b2")), {}),
                (self.router.activate_provider_route, ("provider-secondary",), {}),
                (self.router.delete_provider, ("provider-secondary",), {}),
                (self.router.test_provider, ("provider-active",), {}),
            )
            for route, args, kwargs in calls:
                for pin in (None, "9999"):
                    with self.subTest(route=route.__name__, pin=pin):
                        with self.assertRaises(HTTPException) as raised:
                            await route(*args, x_parent_pin=pin, session=session, **kwargs)
                        self.assertEqual(raised.exception.status_code, 403)

    async def test_valid_parent_pin_allows_provider_crud_activation_test_and_vote_config(self) -> None:
        from app.schemas import ProviderCreate, ProviderUpdate, VisionVoteConfig

        async with self.database.AsyncSessionLocal() as session:
            providers = await self.router.list_providers(x_parent_pin="1234", session=session)
            self.assertEqual({item.id for item in providers}, {"provider-active", "provider-secondary"})

            active = await self.router.get_active_provider("vision", x_parent_pin="1234", session=session)
            self.assertEqual(active.id, "provider-active")

            self.assertEqual(
                await self.router.get_provider_metrics(x_parent_pin="1234", session=session),
                [],
            )

            with patch.object(self.router, "load_vision_vote_config", return_value={"primary_provider_id": None, "secondary_provider_id": None}), patch.object(
                self.router,
                "save_vision_vote_config",
                return_value={"primary_provider_id": "provider-active", "secondary_provider_id": "provider-secondary"},
            ):
                current = await self.router.get_vision_vote_config(x_parent_pin="1234", session=session)
                self.assertFalse(current.applies_to_v2_fusion)
                updated_vote = await self.router.update_vision_vote_config(
                    VisionVoteConfig(primary_provider_id="provider-active", secondary_provider_id="provider-secondary"),
                    x_parent_pin="1234",
                    session=session,
                )
                self.assertEqual(updated_vote.primary_provider_id, "provider-active")
                self.assertFalse(updated_vote.applies_to_v2_fusion)

            created = await self.router.create_provider(
                ProviderCreate(
                    slot="report",
                    name="Report",
                    provider="qwen",
                    base_url="https://example.test/v1",
                    model_id="report-a",
                    api_key="secret",
                ),
                x_parent_pin="1234",
                session=session,
            )
            self.assertEqual(created.slot, "report")

            updated = await self.router.update_provider(
                "provider-secondary",
                ProviderUpdate(model_id="vision-b2"),
                x_parent_pin="1234",
                session=session,
            )
            self.assertEqual(updated.model_id, "vision-b2")

            activated = await self.router.activate_provider_route(
                "provider-secondary",
                x_parent_pin="1234",
                session=session,
            )
            self.assertEqual(activated.id, "provider-secondary")

            with patch.object(self.router, "test_provider_connectivity", return_value=(True, "ok")):
                tested = await self.router.test_provider("provider-secondary", x_parent_pin="1234", session=session)
            self.assertTrue(tested.success)

            deleted = await self.router.delete_provider("provider-active", x_parent_pin="1234", session=session)
            self.assertEqual(deleted.status_code, 204)


if __name__ == "__main__":
    unittest.main()
