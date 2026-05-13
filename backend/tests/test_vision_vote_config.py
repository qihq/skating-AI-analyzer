from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.providers import get_vision_providers


class VisionVoteConfigTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_vision_providers_uses_ui_selected_primary_and_secondary(self) -> None:
        providers = [
            _provider("primary", "qwen", "encrypted-primary"),
            _provider("secondary", "doubao", "encrypted-secondary"),
        ]
        session = SimpleNamespace()
        session.execute = AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: providers)))

        with (
            patch(
                "app.services.providers.load_vision_vote_config",
                return_value={"primary_provider_id": "primary", "secondary_provider_id": "secondary"},
            ),
            patch("app.services.providers.decrypt_api_key", side_effect=lambda value: value.replace("encrypted-", "key-")),
        ):
            result = await get_vision_providers(session)

        self.assertEqual([provider.id for provider in result], ["primary", "secondary"])
        self.assertEqual([provider.provider for provider in result], ["qwen", "doubao"])
        self.assertEqual([provider.api_key for provider in result], ["key-primary", "key-secondary"])

    async def test_get_vision_providers_allows_same_provider_for_two_votes(self) -> None:
        providers = [_provider("primary", "qwen", "encrypted-primary")]
        session = SimpleNamespace()
        session.execute = AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: providers)))

        with (
            patch(
                "app.services.providers.load_vision_vote_config",
                return_value={"primary_provider_id": "primary", "secondary_provider_id": "primary"},
            ),
            patch("app.services.providers.decrypt_api_key", return_value="key-primary"),
        ):
            result = await get_vision_providers(session)

        self.assertEqual([provider.id for provider in result], ["primary", "primary"])


def _provider(provider_id: str, provider_name: str, api_key: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=provider_id,
        slot="vision",
        name=provider_name,
        provider=provider_name,
        base_url="https://example.com/v1",
        model_id="model",
        vision_model=None,
        api_key=api_key,
        notes=None,
    )


if __name__ == "__main__":
    unittest.main()
