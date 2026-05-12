from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.analysis_errors import AnalysisErrorCode, AnalysisPipelineError
from app.services.providers import request_text_completion


def _provider() -> SimpleNamespace:
    return SimpleNamespace(
        id="provider-1",
        slot="report",
        name="test-provider",
        provider="openai_compatible",
        base_url="https://example.com/v1",
        model_id="test-model",
        vision_model=None,
        api_key="test-key",
        notes=None,
    )


def _http_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://example.com/v1/chat/completions")
    response = httpx.Response(status_code, request=request, text="provider error")
    return httpx.HTTPStatusError("provider error", request=request, response=response)


class ProviderRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_retries_5xx_then_returns_success(self) -> None:
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])

        with (
            patch("app.services.providers.asyncio.sleep", AsyncMock()) as sleep_mock,
            patch("app.services.providers.AsyncOpenAI") as client_cls,
        ):
            create_mock = AsyncMock(side_effect=[_http_status_error(500), _http_status_error(502), response])
            client_cls.return_value.chat.completions.create = create_mock

            result = await request_text_completion(
                _provider(),
                messages=[{"role": "user", "content": "hello"}],
                temperature=0,
                max_tokens=16,
            )

        self.assertEqual(result, "ok")
        self.assertEqual(create_mock.await_count, 3)
        self.assertEqual([call.args[0] for call in sleep_mock.await_args_list], [1.0, 2.0])

    async def test_retries_429_and_raises_quota_after_final_failure(self) -> None:
        with (
            patch("app.services.providers.asyncio.sleep", AsyncMock()) as sleep_mock,
            patch("app.services.providers.AsyncOpenAI") as client_cls,
        ):
            create_mock = AsyncMock(side_effect=_http_status_error(429))
            client_cls.return_value.chat.completions.create = create_mock

            with self.assertRaises(AnalysisPipelineError) as context:
                await request_text_completion(
                    _provider(),
                    messages=[{"role": "user", "content": "hello"}],
                    temperature=0,
                    max_tokens=16,
                )

        self.assertEqual(context.exception.code, AnalysisErrorCode.AI_API_QUOTA_EXCEEDED)
        self.assertEqual(create_mock.await_count, 4)
        self.assertEqual([call.args[0] for call in sleep_mock.await_args_list], [1.0, 2.0, 4.0])

    async def test_auth_error_is_not_retried(self) -> None:
        with (
            patch("app.services.providers.asyncio.sleep", AsyncMock()) as sleep_mock,
            patch("app.services.providers.AsyncOpenAI") as client_cls,
        ):
            create_mock = AsyncMock(side_effect=_http_status_error(401))
            client_cls.return_value.chat.completions.create = create_mock

            with self.assertRaises(AnalysisPipelineError) as context:
                await request_text_completion(
                    _provider(),
                    messages=[{"role": "user", "content": "hello"}],
                    temperature=0,
                    max_tokens=16,
                )

        self.assertEqual(context.exception.code, AnalysisErrorCode.AI_API_AUTH_ERROR)
        self.assertEqual(create_mock.await_count, 1)
        sleep_mock.assert_not_awaited()

    async def test_network_timeout_retries_then_raises_timeout(self) -> None:
        with (
            patch("app.services.providers.asyncio.sleep", AsyncMock()) as sleep_mock,
            patch("app.services.providers.AsyncOpenAI") as client_cls,
        ):
            create_mock = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            client_cls.return_value.chat.completions.create = create_mock

            with self.assertRaises(AnalysisPipelineError) as context:
                await request_text_completion(
                    _provider(),
                    messages=[{"role": "user", "content": "hello"}],
                    temperature=0,
                    max_tokens=16,
                )

        self.assertEqual(context.exception.code, AnalysisErrorCode.AI_API_TIMEOUT)
        self.assertEqual(create_mock.await_count, 4)
        self.assertEqual([call.args[0] for call in sleep_mock.await_args_list], [1.0, 2.0, 4.0])


if __name__ == "__main__":
    unittest.main()
