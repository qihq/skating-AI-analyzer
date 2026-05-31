from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.providers import (
    request_dashscope_video_completion,
    request_doubao_vision_completion,
    request_mimo_video_completion,
    request_text_completion,
)


class ProviderVisionContentTests(unittest.IsolatedAsyncioTestCase):
    async def test_claude_provider_translates_openai_vision_content(self) -> None:
        provider = SimpleNamespace(
            provider="claude_compatible",
            base_url="https://api.anthropic.com/v1",
            model_id="claude-test",
            api_key="test-key",
        )
        response = {
            "content": [{"type": "text", "text": '{"ok": true}'}],
        }
        post_mock = AsyncMock()
        post_mock.return_value.raise_for_status = lambda: None
        post_mock.return_value.json = lambda: response

        with patch("app.services.providers.httpx.AsyncClient") as client_cls:
            client_cls.return_value.__aenter__.return_value.post = post_mock
            content = await request_text_completion(
                provider,
                temperature=0.1,
                max_tokens=128,
                messages=[
                    {"role": "system", "content": "system prompt"},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "look"},
                            {
                                "type": "image_url",
                                "image_url": {"url": "data:image/jpeg;base64,QUJD"},
                            },
                        ],
                    },
                ],
            )

        payload = post_mock.await_args.kwargs["json"]
        user_content = payload["messages"][0]["content"]
        self.assertEqual(content, '{"ok": true}')
        self.assertEqual(payload["system"], "system prompt")
        self.assertEqual(user_content[0], {"type": "text", "text": "look"})
        self.assertEqual(user_content[1]["type"], "image")
        self.assertEqual(user_content[1]["source"]["media_type"], "image/jpeg")
        self.assertEqual(user_content[1]["source"]["data"], "QUJD")

    async def test_deepseek_v4_disables_thinking_by_default(self) -> None:
        provider = SimpleNamespace(
            provider="deepseek",
            base_url="https://api.deepseek.com/v1",
            model_id="deepseek-v4-pro",
            api_key="test-key",
        )
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))]
        )

        with patch("app.services.providers.AsyncOpenAI") as client_cls:
            create_mock = AsyncMock(return_value=response)
            client_cls.return_value.chat.completions.create = create_mock
            content = await request_text_completion(
                provider,
                temperature=0.1,
                max_tokens=128,
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": "return json"}],
            )

        self.assertEqual(content, '{"ok": true}')
        kwargs = create_mock.await_args.kwargs
        self.assertEqual(kwargs["extra_body"], {"thinking": {"type": "disabled"}})
        self.assertEqual(kwargs["response_format"], {"type": "json_object"})

    async def test_mimo_text_uses_max_completion_tokens_and_response_format(self) -> None:
        provider = SimpleNamespace(
            provider="mimo",
            base_url="https://api.xiaomimimo.com/v1",
            model_id="mimo-v2.5-pro",
            api_key="test-key",
        )
        response = {"choices": [{"message": {"content": '{"ok": true}'}}]}
        post_mock = AsyncMock()
        post_mock.return_value.raise_for_status = lambda: None
        post_mock.return_value.json = lambda: response

        with patch("app.services.providers.httpx.AsyncClient") as client_cls:
            client_cls.return_value.__aenter__.return_value.post = post_mock
            content = await request_text_completion(
                provider,
                temperature=0.1,
                max_tokens=128,
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": "return json"}],
            )

        self.assertEqual(content, '{"ok": true}')
        self.assertEqual(post_mock.await_args.kwargs["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(post_mock.await_args.kwargs["headers"]["api-key"], "test-key")
        self.assertEqual(post_mock.await_args.args[0], "https://api.xiaomimimo.com/v1/chat/completions")
        payload = post_mock.await_args.kwargs["json"]
        self.assertEqual(payload["max_completion_tokens"], 128)
        self.assertNotIn("max_tokens", payload)
        self.assertEqual(payload["response_format"], {"type": "json_object"})

    async def test_mimo_video_sends_base64_video_url_options(self) -> None:
        provider = SimpleNamespace(
            id="mimo-provider",
            slot="vision",
            name="mimo",
            provider="mimo",
            base_url="https://api.xiaomimimo.com/v1",
            model_id="mimo-v2.5",
            vision_model=None,
            api_key="test-key",
            notes=None,
        )
        response = {"choices": [{"message": {"content": "video ok"}}]}
        post_mock = AsyncMock()
        post_mock.return_value.raise_for_status = lambda: None
        post_mock.return_value.json = lambda: response

        with patch("app.services.providers.httpx.AsyncClient") as client_cls:
            client_cls.return_value.__aenter__.return_value.post = post_mock
            content = await request_mimo_video_completion(
                provider,
                video_path=Path(__file__),
                system_prompt="system",
                user_prompt="user",
                temperature=0,
                max_tokens=32,
            )

        self.assertEqual(content, "video ok")
        payload = post_mock.await_args.kwargs["json"]
        video_block = payload["messages"][1]["content"][0]
        self.assertEqual(video_block["type"], "video_url")
        self.assertTrue(video_block["video_url"]["url"].startswith("data:video/mp4;base64,"))
        self.assertEqual(video_block["fps"], 2)
        self.assertEqual(video_block["media_resolution"], "default")
        self.assertEqual(payload["max_completion_tokens"], 32)

    async def test_mimo_video_rejects_base64_over_50mb_before_api_call(self) -> None:
        provider = SimpleNamespace(
            id="mimo-provider",
            slot="vision",
            name="mimo",
            provider="mimo",
            base_url="https://api.xiaomimimo.com/v1",
            model_id="mimo-v2.5",
            vision_model=None,
            api_key="test-key",
            notes=None,
        )

        fake_stat = SimpleNamespace(st_size=40 * 1024 * 1024)
        with (
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "stat", return_value=fake_stat),
            patch("app.services.providers.httpx.AsyncClient") as client_cls,
            self.assertRaises(Exception) as caught,
        ):
            await request_mimo_video_completion(
                provider,
                video_path=Path("large.mp4"),
                system_prompt="system",
                user_prompt="user",
                temperature=0,
                max_tokens=32,
            )

        self.assertIn("50MB", str(caught.exception))
        client_cls.assert_not_called()

    async def test_dashscope_video_budget_exceeded_raises_quota(self) -> None:
        provider = SimpleNamespace(
            id="vision-provider",
            slot="vision",
            name="qwen",
            provider="qwen",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model_id="qwen3.6-plus",
            vision_model=None,
            api_key="test-key",
            notes=None,
        )

        with (
            patch.dict(
                "os.environ",
                {
                    "QWEN_VISION_DAILY_COST_LIMIT_CNY": "0.1",
                    "QWEN_VISION_VIDEO_ESTIMATED_COST_CNY": "0.6",
                },
            ),
            self.assertRaises(Exception) as caught,
        ):
            await request_dashscope_video_completion(
                provider,
                video_path=Path(__file__),
                system_prompt="system",
                user_prompt="user",
                temperature=0,
                max_tokens=32,
            )

        self.assertIn("daily cost limit", str(caught.exception))

    async def test_doubao_video_rejects_files_over_50mb_before_api_call(self) -> None:
        provider = SimpleNamespace(
            id="doubao-provider",
            slot="vision",
            name="doubao",
            provider="doubao",
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            model_id="doubao-1.5-vision-pro-32k",
            vision_model=None,
            api_key="test-key",
            notes=None,
        )

        fake_stat = SimpleNamespace(st_size=51 * 1024 * 1024)
        with (
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "stat", return_value=fake_stat),
            patch("app.services.providers.AsyncOpenAI") as client_cls,
            self.assertRaises(Exception) as caught,
        ):
            await request_doubao_vision_completion(
                provider,
                video_path=Path("large.mp4"),
                system_prompt="system",
                user_prompt="user",
                temperature=0,
                max_tokens=32,
            )

        self.assertIn("50MB", str(caught.exception))
        client_cls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
