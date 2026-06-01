from __future__ import annotations

import base64
import asyncio
import hashlib
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

try:
    from openai import APIConnectionError, APITimeoutError, AsyncOpenAI
except Exception:  # noqa: BLE001
    class APIConnectionError(Exception):
        pass

    class APITimeoutError(Exception):
        pass

    from openai import AsyncOpenAI

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models import AIProvider
from app.schemas import ApiConnectionTestResponse
from app.services.analysis_errors import AnalysisErrorCode, AnalysisPipelineError, classify_ai_failure
from app.services.vision_vote_config import load_vision_vote_config


logger = logging.getLogger(__name__)
AI_RETRY_DELAYS_SECONDS = (1.0, 2.0, 4.0)
DEFAULT_QWEN_VISION_MODEL = "qwen3.6-plus"
DEPRECATED_QWEN_VISION_MODELS = {"qwen-vl-max-latest"}
DEFAULT_DOUBAO_VISION_MODEL = "doubao-1.5-vision-pro-32k"
DOUBAO_VISION_MAX_MB = 50
DOUBAO_VISION_MAX_SECONDS = 60.0
DEFAULT_MIMO_VISION_MODEL = "mimo-v2.5"
DEFAULT_MIMO_REPORT_MODEL = "mimo-v2.5-pro"
MIMO_BASE_URL = "https://api.xiaomimimo.com/v1"
MIMO_TOKEN_PLAN_BASE_URL = "https://token-plan-cn.xiaomimimo.com/v1"
MIMO_VIDEO_MAX_BASE64_MB = 50
MIMO_VIDEO_FPS = 2
MIMO_VIDEO_MEDIA_RESOLUTION = "default"
QWEN_VIDEO_GENERATION_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
_VISION_VIDEO_COST_DAY: date | None = None
_VISION_VIDEO_COST_CNY = 0.0


ENV_KEYS_BY_PROVIDER = {
    "qwen": ["QWEN_API_KEY", "DASHSCOPE_API_KEY"],
    "deepseek": ["DEEPSEEK_API_KEY"],
    "kimi": ["KIMI_API_KEY"],
    "doubao": ["DOUBAO_API_KEY"],
    "minimax": ["MINIMAX_API_KEY"],
    "glm": ["GLM_API_KEY"],
    "mimo": ["MIMO_API_KEY"],
}

TINY_PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAFElEQVR42mP4TyJgGNUwqmH4agAAr639H23ooMoAAAAASUVORK5CYII="
)
CLAUDE_COMPATIBLE_PROVIDERS = {"claude_compatible"}


@dataclass(slots=True)
class ActiveProviderConfig:
    id: str
    slot: str
    name: str
    provider: str
    base_url: str
    model_id: str
    vision_model: str | None
    api_key: str
    notes: str | None


def _require_secret_key() -> bytes:
    secret = os.getenv("SECRET_KEY", "").strip()
    if not secret:
        raise RuntimeError("SECRET_KEY 未配置，无法加密或解密 API Key。")
    return hashlib.sha256(secret.encode("utf-8")).digest()


def encrypt_api_key(api_key: str) -> str:
    if not api_key:
        return ""

    aesgcm = AESGCM(_require_secret_key())
    nonce = os.urandom(12)
    encrypted = aesgcm.encrypt(nonce, api_key.encode("utf-8"), None)
    return base64.b64encode(nonce + encrypted).decode("utf-8")


def decrypt_api_key(payload: str) -> str:
    if not payload:
        return ""

    raw = base64.b64decode(payload.encode("utf-8"))
    nonce, ciphertext = raw[:12], raw[12:]
    aesgcm = AESGCM(_require_secret_key())
    return aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8")


def mask_api_key(payload: str) -> str:
    return "***" if payload else ""


def _resolve_preset_api_key(provider: str) -> str:
    for env_name in ENV_KEYS_BY_PROVIDER.get(provider, []):
        value = os.getenv(env_name, "").strip()
        if value:
            return value
    return ""


def _resolve_qwen_vision_model(provider: AIProvider) -> str:
    env_model = os.getenv("QWEN_VISION_MODEL", "").strip()
    if env_model in DEPRECATED_QWEN_VISION_MODELS:
        logger.warning(
            "QWEN_VISION_MODEL=%s is deprecated; qwen3.6-plus is the default vision model.",
            env_model,
        )
    if provider.vision_model:
        return provider.vision_model
    if provider.provider == "qwen" and provider.slot == "vision" and env_model:
        return env_model
    if provider.model_id:
        return provider.model_id
    if provider.provider == "qwen" and provider.slot in {"vision", "vision_path_a", "vision_path_b"}:
        return DEFAULT_QWEN_VISION_MODEL
    if provider.provider == "mimo" and provider.slot in {"vision", "vision_path_a", "vision_path_b"}:
        return DEFAULT_MIMO_VISION_MODEL
    if provider.provider == "mimo" and provider.slot == "report":
        return DEFAULT_MIMO_REPORT_MODEL
    return provider.model_id


def _resolve_env_vision_model(provider_name: str) -> str:
    normalized = provider_name.strip().lower()
    if normalized == "qwen":
        env_model = os.getenv("QWEN_VISION_MODEL", "").strip()
        if env_model in DEPRECATED_QWEN_VISION_MODELS:
            logger.warning(
                "QWEN_VISION_MODEL=%s is deprecated; qwen3.6-plus is the default vision model.",
                env_model,
            )
        return env_model or DEFAULT_QWEN_VISION_MODEL
    if normalized == "doubao":
        return os.getenv("DOUBAO_VISION_MODEL", "").strip() or DEFAULT_DOUBAO_VISION_MODEL
    if normalized == "mimo":
        return os.getenv("MIMO_VISION_MODEL", "").strip() or DEFAULT_MIMO_VISION_MODEL
    return os.getenv(f"{normalized.upper()}_VISION_MODEL", "").strip() or normalized


def _env_vision_provider_config(provider_name: str) -> ActiveProviderConfig | None:
    normalized = provider_name.strip().lower()
    if not normalized:
        return None

    api_key = _resolve_preset_api_key(normalized)
    if not api_key:
        return None

    base_urls = {
        "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "doubao": "https://ark.cn-beijing.volces.com/api/v3",
        "kimi": "https://api.moonshot.cn/v1",
        "glm": "https://open.bigmodel.cn/api/paas/v4",
        "mimo": MIMO_BASE_URL,
    }
    return ActiveProviderConfig(
        id=f"env:vision:{normalized}",
        slot="vision",
        name=f"{normalized} vision",
        provider=normalized,
        base_url=os.getenv(f"{normalized.upper()}_VISION_BASE_URL", "").strip() or base_urls.get(normalized, ""),
        model_id=_resolve_env_vision_model(normalized),
        vision_model=None,
        api_key=api_key,
        notes="env VISION_PROVIDERS",
    )


def _active_provider_config_from_model(provider: AIProvider, api_key: str) -> ActiveProviderConfig:
    return ActiveProviderConfig(
        id=provider.id,
        slot=provider.slot,
        name=provider.name,
        provider=provider.provider,
        base_url=provider.base_url,
        model_id=_resolve_qwen_vision_model(provider),
        vision_model=provider.vision_model,
        api_key=api_key,
        notes=provider.notes,
    )


def _vision_video_daily_limit_cny() -> float:
    raw = os.getenv("QWEN_VISION_DAILY_COST_LIMIT_CNY", "30").strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 30.0


def _vision_video_estimated_cost_cny() -> float:
    raw = os.getenv("QWEN_VISION_VIDEO_ESTIMATED_COST_CNY", "0.6").strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 0.6


def _reserve_vision_video_budget() -> None:
    global _VISION_VIDEO_COST_DAY, _VISION_VIDEO_COST_CNY

    today = date.today()
    if _VISION_VIDEO_COST_DAY != today:
        _VISION_VIDEO_COST_DAY = today
        _VISION_VIDEO_COST_CNY = 0.0

    limit = _vision_video_daily_limit_cny()
    estimated = _vision_video_estimated_cost_cny()
    if limit > 0 and _VISION_VIDEO_COST_CNY + estimated > limit:
        raise AnalysisPipelineError(
            AnalysisErrorCode.AI_API_QUOTA_EXCEEDED,
            "Qwen vision video daily cost limit exceeded; falling back to frame mode.",
        )
    _VISION_VIDEO_COST_CNY += estimated


def is_claude_compatible_provider(provider_name: str) -> bool:
    return provider_name in CLAUDE_COMPATIBLE_PROVIDERS


def default_extra_body(model_id: str) -> dict[str, Any] | None:
    normalized_model = model_id.strip().lower()
    if normalized_model == "qwen3.6-plus":
        return {"enable_thinking": False}
    if normalized_model.startswith("deepseek-v4-"):
        return {"thinking": {"type": "disabled"}}
    return None


def extract_message_text(content: object) -> str:
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts).strip()

    text_attr = getattr(content, "text", None)
    if isinstance(text_attr, str):
        return text_attr.strip()

    return ""


def _claude_content_blocks(content: object) -> str | list[dict[str, Any]]:
    if isinstance(content, str):
        return content.strip()

    if not isinstance(content, list):
        return extract_message_text(content)

    blocks: list[dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "text":
            text = str(item.get("text", "")).strip()
            if text:
                blocks.append({"type": "text", "text": text})
            continue
        if item_type != "image_url":
            continue

        image_url = item.get("image_url")
        url = image_url.get("url") if isinstance(image_url, dict) else None
        if not isinstance(url, str) or not url:
            continue
        if url.startswith("data:"):
            header, _, encoded = url.partition(",")
            media_type = header[5:].split(";", 1)[0] or "image/jpeg"
            if encoded:
                blocks.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": encoded,
                        },
                    }
                )
            continue
        blocks.append({"type": "image", "source": {"type": "url", "url": url}})

    if not blocks:
        return ""
    return blocks


def _split_system_messages(messages: list[dict[str, object]]) -> tuple[str | None, list[dict[str, object]]]:
    system_parts: list[str] = []
    normalized_messages: list[dict[str, object]] = []

    for message in messages:
        role = str(message.get("role", "")).strip()
        raw_content = message.get("content")
        content = extract_message_text(raw_content) if role == "system" else _claude_content_blocks(raw_content)
        if not content:
            continue
        if role == "system":
            system_parts.append(str(content))
            continue
        if role in {"user", "assistant"}:
            normalized_messages.append({"role": role, "content": content})

    system_prompt = "\n\n".join(system_parts).strip() or None
    return system_prompt, normalized_messages


def _claude_messages_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/messages"):
        return normalized
    if normalized.endswith("/v1"):
        return f"{normalized}/messages"
    return f"{normalized}/messages"


def is_mimo_provider(provider_name: str) -> bool:
    return provider_name.strip().lower() == "mimo"


def _mimo_chat_completions_url(base_url: str) -> str:
    normalized = (base_url or MIMO_BASE_URL).rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    if normalized.endswith("/v1"):
        return f"{normalized}/chat/completions"
    return f"{normalized}/v1/chat/completions"


def _mimo_effective_base_url(provider: ActiveProviderConfig) -> str:
    base_url = (provider.base_url or MIMO_BASE_URL).strip()
    api_key = (provider.api_key or "").strip()
    if api_key.startswith("tp-") and "api.xiaomimimo.com" in base_url:
        return MIMO_TOKEN_PLAN_BASE_URL
    return base_url


def _extract_status_code(exc: Exception) -> int | None:
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code

    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    if isinstance(response_status, int):
        return response_status
    return None


def _is_retryable_completion_error(exc: Exception) -> bool:
    status_code = _extract_status_code(exc)
    if status_code == 429 or (status_code is not None and 500 <= status_code <= 599):
        return True
    return isinstance(
        exc,
        (
            APITimeoutError,
            APIConnectionError,
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.TransportError,
        ),
    )


def _as_pipeline_completion_error(exc: Exception) -> Exception:
    failure = classify_ai_failure(exc)
    if failure.code in {
        AnalysisErrorCode.AI_API_AUTH_ERROR,
        AnalysisErrorCode.AI_API_QUOTA_EXCEEDED,
        AnalysisErrorCode.AI_API_TIMEOUT,
    }:
        return AnalysisPipelineError(failure.code, failure.detail)
    return exc


async def _with_completion_retry(operation) -> str:
    last_exc: Exception | None = None
    for attempt in range(len(AI_RETRY_DELAYS_SECONDS) + 1):
        try:
            return await operation()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if not _is_retryable_completion_error(exc) or attempt >= len(AI_RETRY_DELAYS_SECONDS):
                raise _as_pipeline_completion_error(exc) from exc
            # 设计说明: 仅对瞬时网络/限流/服务端错误退避，避免认证类 4xx 被无意义重试。
            await asyncio.sleep(AI_RETRY_DELAYS_SECONDS[attempt])

    if last_exc is not None:
        raise _as_pipeline_completion_error(last_exc) from last_exc
    raise AnalysisPipelineError(AnalysisErrorCode.UNKNOWN_ERROR, "AI completion failed without an exception.")


async def _request_claude_compatible_completion(
    provider: ActiveProviderConfig,
    *,
    messages: list[dict[str, object]],
    temperature: float,
    max_tokens: int,
    timeout: float,
) -> str:
    system_prompt, normalized_messages = _split_system_messages(messages)
    if not normalized_messages:
        normalized_messages = [{"role": "user", "content": "Reply with ok."}]

    payload: dict[str, Any] = {
        "model": provider.model_id,
        "max_tokens": max_tokens,
        "messages": normalized_messages,
        "temperature": temperature,
    }
    if system_prompt:
        payload["system"] = system_prompt

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            _claude_messages_url(provider.base_url),
            headers={
                "x-api-key": provider.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    content = data.get("content", [])
    if not isinstance(content, list):
        return ""

    text_parts = [
        str(item.get("text", "")).strip()
        for item in content
        if isinstance(item, dict) and item.get("type") == "text" and str(item.get("text", "")).strip()
    ]
    return "\n".join(text_parts).strip()


async def _request_mimo_completion(
    provider: ActiveProviderConfig,
    *,
    messages: list[dict[str, object]],
    temperature: float,
    max_tokens: int,
    extra_body: dict[str, Any] | None = None,
    response_format: dict[str, Any] | None = None,
    timeout: float,
) -> str:
    payload: dict[str, Any] = {
        "model": provider.model_id,
        "messages": messages,
        "max_completion_tokens": max_tokens,
        "temperature": temperature,
    }
    if extra_body:
        payload.update(extra_body)
    if response_format:
        payload["response_format"] = response_format

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            _mimo_chat_completions_url(_mimo_effective_base_url(provider)),
            headers={
                "api-key": provider.api_key,
                "Authorization": f"Bearer {provider.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    choices = data.get("choices") if isinstance(data, dict) else None
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    return extract_message_text(content).strip()


async def request_text_completion(
    provider: ActiveProviderConfig,
    *,
    messages: list[dict[str, object]],
    temperature: float,
    max_tokens: int,
    extra_body: dict[str, Any] | None = None,
    response_format: dict[str, Any] | None = None,
    timeout: float = 45.0,
) -> str:
    """
    Request a text completion from the active AI provider.

    Args:
        provider: Active provider configuration.
        messages: OpenAI-compatible message payload.
        temperature: Sampling temperature.
        max_tokens: Maximum generated tokens.
        extra_body: Provider-specific extra request body.
        response_format: Optional structured response format.
        timeout: Request timeout in seconds.

    Returns:
        The normalized assistant text content.

    Raises:
        AnalysisPipelineError: When auth, quota, or timeout failures are classified.
        Exception: For non-retryable provider errors that do not map to a known pipeline code.
    """

    async def operation() -> str:
        if is_claude_compatible_provider(provider.provider):
            return await _request_claude_compatible_completion(
                provider,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
        if is_mimo_provider(provider.provider):
            return await _request_mimo_completion(
                provider,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                extra_body=extra_body,
                response_format=response_format,
                timeout=timeout,
            )

        client = AsyncOpenAI(api_key=provider.api_key, base_url=provider.base_url, timeout=timeout, max_retries=0)
        response = await client.chat.completions.create(
            model=provider.model_id,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            extra_body=extra_body or default_extra_body(provider.model_id),
            response_format=response_format,
        )
        return extract_message_text(response.choices[0].message.content).strip()

    return await _with_completion_retry(operation)


async def request_dashscope_video_completion(
    provider: ActiveProviderConfig,
    *,
    video_path: Path,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
    timeout: float = 180.0,
) -> str:
    """
    Request native Qwen-VL video understanding through DashScope multimodal generation.

    Args:
        provider: Active Qwen provider configuration.
        video_path: Local action-window clip path.
        system_prompt: System instruction.
        user_prompt: User instruction paired with the video.
        temperature: Sampling temperature.
        max_tokens: Maximum generated tokens.
        timeout: Request timeout in seconds.

    Returns:
        Assistant text content.

    Raises:
        AnalysisPipelineError: When provider, budget, or request failures should trigger fallback.
        Exception: For non-retryable SDK errors.
    """
    if provider.provider != "qwen":
        raise AnalysisPipelineError(
            AnalysisErrorCode.UNKNOWN_ERROR,
            "Native video mode currently requires the qwen provider.",
        )
    if not video_path.exists():
        raise AnalysisPipelineError(AnalysisErrorCode.FRAME_EXTRACT_FAILED, f"Video clip not found: {video_path}")

    _reserve_vision_video_budget()

    async def operation() -> str:
        def _call_dashscope() -> str:
            try:
                import dashscope  # type: ignore
            except Exception as exc:  # noqa: BLE001
                raise AnalysisPipelineError(
                    AnalysisErrorCode.UNKNOWN_ERROR,
                    "dashscope SDK is not installed; cannot use native video mode.",
                ) from exc

            dashscope.api_key = provider.api_key
            messages = [
                {"role": "system", "content": [{"text": system_prompt}]},
                {
                    "role": "user",
                    "content": [
                        {"video": f"file://{video_path.resolve().as_posix()}", "fps": 2},
                        {"text": user_prompt},
                    ],
                },
            ]
            # Design note: local file:// upload is handled by DashScope SDK, which avoids OSS setup on NAS deployments.
            response = dashscope.MultiModalConversation.call(
                api_key=provider.api_key,
                model=provider.model_id,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
            status_code = getattr(response, "status_code", None)
            if status_code not in (None, 200):
                message = getattr(response, "message", "") or getattr(response, "code", "") or str(response)
                raise RuntimeError(f"DashScope video request failed: {message}")

            output = getattr(response, "output", None)
            choices = output.get("choices") if isinstance(output, dict) else None
            if isinstance(choices, list) and choices:
                message = choices[0].get("message") if isinstance(choices[0], dict) else None
                if isinstance(message, dict):
                    return extract_message_text(message.get("content")).strip()
            return extract_message_text(output).strip() if output is not None else ""

        return await asyncio.wait_for(asyncio.to_thread(_call_dashscope), timeout=timeout)

    return await _with_completion_retry(operation)


def _probe_video_duration_seconds(video_path: Path) -> float | None:
    try:
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:  # noqa: BLE001
        return None

    try:
        return float(completed.stdout.strip())
    except ValueError:
        return None


async def request_doubao_vision_completion(
    provider: ActiveProviderConfig,
    *,
    video_path: Path,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
    timeout: float = 180.0,
) -> str:
    """
    Request Doubao vision understanding through Ark's OpenAI-compatible API.

    Args:
        provider: Active Doubao provider configuration.
        video_path: Local action-window clip path.
        system_prompt: System instruction.
        user_prompt: User instruction paired with the video.
        temperature: Sampling temperature.
        max_tokens: Maximum generated tokens.
        timeout: Request timeout in seconds.

    Returns:
        Assistant text content.

    Raises:
        AnalysisPipelineError: When provider, file size, or duration constraints are not satisfied.
        Exception: For non-retryable provider errors.
    """
    if provider.provider != "doubao":
        raise AnalysisPipelineError(
            AnalysisErrorCode.UNKNOWN_ERROR,
            "Doubao vision mode requires the doubao provider.",
        )
    if not video_path.exists():
        raise AnalysisPipelineError(AnalysisErrorCode.FRAME_EXTRACT_FAILED, f"Video clip not found: {video_path}")

    size_mb = video_path.stat().st_size / (1024 * 1024)
    if size_mb > DOUBAO_VISION_MAX_MB:
        raise AnalysisPipelineError(
            AnalysisErrorCode.AI_API_QUOTA_EXCEEDED,
            f"Doubao vision video exceeds {DOUBAO_VISION_MAX_MB}MB limit; skipping provider.",
        )

    duration = _probe_video_duration_seconds(video_path)
    if duration is not None and duration > DOUBAO_VISION_MAX_SECONDS:
        raise AnalysisPipelineError(
            AnalysisErrorCode.AI_API_QUOTA_EXCEEDED,
            f"Doubao vision video exceeds {DOUBAO_VISION_MAX_SECONDS:.0f}s limit; skipping provider.",
        )

    with video_path.open("rb") as handle:
        encoded_video = base64.b64encode(handle.read()).decode("ascii")

    async def operation() -> str:
        client = AsyncOpenAI(api_key=provider.api_key, base_url=provider.base_url, timeout=timeout, max_retries=0)
        # 设计说明: Ark 的 OpenAI 兼容入口接受 video_url 内容块；本地短片转 data URL 可避免 NAS 部署额外公网对象存储。
        response = await client.chat.completions.create(
            model=provider.model_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "video_url",
                            "video_url": {"url": f"data:video/mp4;base64,{encoded_video}"},
                        },
                        {"type": "text", "text": user_prompt},
                    ],
                },
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return extract_message_text(response.choices[0].message.content).strip()

    return await _with_completion_retry(operation)


def _base64_encoded_size_bytes(raw_size_bytes: int) -> int:
    return ((max(0, raw_size_bytes) + 2) // 3) * 4


def _mimo_video_limit_bytes() -> int:
    return MIMO_VIDEO_MAX_BASE64_MB * 1024 * 1024


async def request_mimo_video_completion(
    provider: ActiveProviderConfig,
    *,
    video_path: Path,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
    response_format: dict[str, Any] | None = None,
    timeout: float = 180.0,
) -> str:
    """
    Request MiMo video understanding through its OpenAI-compatible API.

    Local action clips are sent as Base64 data URLs because this project does
    not publish temporary video files to a public URL.
    """
    if not is_mimo_provider(provider.provider):
        raise AnalysisPipelineError(
            AnalysisErrorCode.UNKNOWN_ERROR,
            "MiMo video mode requires the mimo provider.",
        )
    if not video_path.exists():
        raise AnalysisPipelineError(AnalysisErrorCode.FRAME_EXTRACT_FAILED, f"Video clip not found: {video_path}")

    projected_encoded_size = _base64_encoded_size_bytes(video_path.stat().st_size)
    if projected_encoded_size > _mimo_video_limit_bytes():
        raise AnalysisPipelineError(
            AnalysisErrorCode.AI_API_QUOTA_EXCEEDED,
            f"MiMo vision video base64 exceeds {MIMO_VIDEO_MAX_BASE64_MB}MB limit; skipping provider.",
        )

    with video_path.open("rb") as handle:
        encoded_video = base64.b64encode(handle.read()).decode("ascii")

    if len(encoded_video.encode("ascii")) > _mimo_video_limit_bytes():
        raise AnalysisPipelineError(
            AnalysisErrorCode.AI_API_QUOTA_EXCEEDED,
            f"MiMo vision video base64 exceeds {MIMO_VIDEO_MAX_BASE64_MB}MB limit; skipping provider.",
        )

    messages: list[dict[str, object]] = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {
                    "type": "video_url",
                    "video_url": {"url": f"data:video/mp4;base64,{encoded_video}"},
                    "fps": MIMO_VIDEO_FPS,
                    "media_resolution": MIMO_VIDEO_MEDIA_RESOLUTION,
                },
                {"type": "text", "text": user_prompt},
            ],
        },
    ]

    async def operation() -> str:
        return await _request_mimo_completion(
            provider,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            timeout=timeout,
        )

    return await _with_completion_retry(operation)


async def get_active_provider(slot: str, session: AsyncSession | None = None) -> ActiveProviderConfig:
    owns_session = session is None
    if owns_session:
        session = AsyncSessionLocal()

    try:
        result = await session.execute(
            select(AIProvider).where(AIProvider.slot == slot, AIProvider.is_active.is_(True)).limit(1)
        )
        provider = result.scalar_one_or_none()
        if provider is None:
            raise RuntimeError(f"未找到 slot={slot} 的激活供应商。")

        api_key = decrypt_api_key(provider.api_key)
        if not api_key:
            raise RuntimeError(f"{provider.name} 尚未配置 API Key。")

        return _active_provider_config_from_model(provider, api_key)
    finally:
        if owns_session:
            await session.close()


async def get_vision_providers(session: AsyncSession | None = None) -> list[ActiveProviderConfig]:
    """
    Return the configured ordered vision provider list.

    Args:
        session: Optional database session used for persisted provider lookup.

    Returns:
        Ordered active provider configs. `VISION_PROVIDERS=qwen,doubao` enables env-driven multi-provider slots.

    Raises:
        RuntimeError: When no usable provider can be resolved.
    """
    requested = [item.strip().lower() for item in os.getenv("VISION_PROVIDERS", "").split(",") if item.strip()]
    if requested:
        providers = [config for name in requested if (config := _env_vision_provider_config(name)) is not None]
        if providers:
            return providers

    owns_session = session is None
    if owns_session:
        session = AsyncSessionLocal()

    try:
        vote_config = load_vision_vote_config()
        selected_ids = [
            provider_id
            for provider_id in [vote_config.get("primary_provider_id"), vote_config.get("secondary_provider_id")]
            if provider_id
        ]
        if selected_ids:
            unique_ids = set(selected_ids)
            result = await session.execute(
                select(AIProvider).where(AIProvider.slot == "vision", AIProvider.id.in_(unique_ids))
            )
            providers_by_id = {provider.id: provider for provider in result.scalars().all()}
            providers: list[ActiveProviderConfig] = []
            for provider_id in selected_ids:
                provider = providers_by_id.get(provider_id)
                if provider is None:
                    continue
                api_key = decrypt_api_key(provider.api_key)
                if not api_key:
                    continue
                providers.append(_active_provider_config_from_model(provider, api_key))
            if providers:
                return providers

        result = await session.execute(
            select(AIProvider)
            .where(AIProvider.slot == "vision", AIProvider.is_active.is_(True))
            .order_by(AIProvider.created_at.asc())
        )
        providers: list[ActiveProviderConfig] = []
        for provider in result.scalars():
            api_key = decrypt_api_key(provider.api_key)
            if not api_key:
                continue
            providers.append(_active_provider_config_from_model(provider, api_key))
        if providers:
            return providers
    finally:
        if owns_session:
            await session.close()

    return [await get_active_provider("vision", None if owns_session else session)]

async def activate_provider(provider: AIProvider, session: AsyncSession) -> AIProvider:
    result = await session.execute(select(AIProvider).where(AIProvider.slot == provider.slot))
    for candidate in result.scalars():
        candidate.is_active = candidate.id == provider.id

    await session.commit()
    await session.refresh(provider)
    return provider


async def test_provider_connectivity(provider: AIProvider) -> tuple[bool, str]:
    api_key = decrypt_api_key(provider.api_key)
    if not api_key:
        return False, "API Key 为空，请先更新该供应商配置。"

    active_provider = ActiveProviderConfig(
        id=provider.id,
        slot=provider.slot,
        name=provider.name,
        provider=provider.provider,
        base_url=provider.base_url,
        model_id=provider.model_id,
        vision_model=provider.vision_model,
        api_key=api_key,
        notes=provider.notes,
    )

    if provider.slot in {"vision", "vision_path_a", "vision_path_b"}:
        messages: list[dict[str, object]] = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Reply with ok."},
                    {"type": "image_url", "image_url": {"url": TINY_PNG_DATA_URL}},
                ],
            }
        ]
        try:
            if is_mimo_provider(provider.provider):
                content = await request_text_completion(
                    active_provider,
                    messages=messages,
                    temperature=0,
                    max_tokens=16,
                    timeout=30.0,
                )
                return True, content or "连通性测试通过。"

            client = AsyncOpenAI(api_key=api_key, base_url=provider.base_url, timeout=30.0, max_retries=0)
            response = await client.chat.completions.create(
                model=provider.model_id,
                messages=messages,
                max_tokens=16,
                temperature=0,
                extra_body=default_extra_body(provider.model_id),
            )
            content = extract_message_text(response.choices[0].message.content)
            return True, content or "连通性测试通过。"
        except Exception as exc:  # noqa: BLE001
            return False, f"连通性测试失败：{exc}"

    try:
        content = await request_text_completion(
            active_provider,
            messages=[{"role": "user", "content": "Reply with ok."}],
            temperature=0,
            max_tokens=16,
            timeout=30.0,
        )
        return True, content or "连通性测试通过。"
    except Exception as exc:  # noqa: BLE001
        return False, f"连通性测试失败：{exc}"
