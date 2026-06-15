from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.providers import _active_provider_config_from_model, _env_report_provider_config, get_vision_providers


class VisionVoteConfigTests(unittest.IsolatedAsyncioTestCase):
    async def test_env_report_provider_defaults_to_mimo(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "MIMO_API_KEY": "mimo-key",
                "REPORT_PROVIDER": "",
                "REPORT_MODEL": "",
                "REPORT_BASE_URL": "",
                "DEEPSEEK_API_KEY": "",
            },
            clear=False,
        ):
            provider = _env_report_provider_config()

        self.assertIsNotNone(provider)
        assert provider is not None
        self.assertEqual(provider.slot, "report")
        self.assertEqual(provider.provider, "mimo")
        self.assertEqual(provider.model_id, "mimo-v2.5-pro")
        self.assertEqual(provider.base_url, "https://api.xiaomimimo.com/v1")
        self.assertEqual(provider.api_key, "mimo-key")

    async def test_qwen_dual_path_slots_keep_their_configured_model_ids(self) -> None:
        path_a = _provider("path-a", "qwen", "encrypted-a", slot="vision_path_a", model_id="qwen3-omni-flash")
        path_b = _provider("path-b", "qwen", "encrypted-b", slot="vision_path_b", model_id="qwen3.6-plus")

        with patch.dict("os.environ", {"QWEN_VISION_MODEL": "qwen-vl-max-latest"}):
            result_a = _active_provider_config_from_model(path_a, "key-a")
            result_b = _active_provider_config_from_model(path_b, "key-b")

        self.assertEqual(result_a.model_id, "qwen3-omni-flash")
        self.assertEqual(result_b.model_id, "qwen3.6-plus")

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


def _provider(
    provider_id: str,
    provider_name: str,
    api_key: str,
    *,
    slot: str = "vision",
    model_id: str = "model",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=provider_id,
        slot=slot,
        name=provider_name,
        provider=provider_name,
        base_url="https://example.com/v1",
        model_id=model_id,
        vision_model=None,
        api_key=api_key,
        notes=None,
    )


if __name__ == "__main__":
    unittest.main()
