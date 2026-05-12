"""
AI 供应商管理模块（独立版）。

职责：
- 管理多个 AI 供应商配置（vision 槽 + report 槽）
- API Key 加密/解密
- OpenAI 兼容 API 调用
- Claude 兼容 API 调用
- 连通性测试

独立版说明：原版依赖 SQLAlchemy 数据库存储供应商配置。
本独立版改为从环境变量读取 API Key，支持通过 config dict 传入。
"""
from __future__ import annotations

import base64
import hashlib
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from openai import AsyncOpenAI

from src.utils.analysis_errors import AnalysisErrorCode, classify_ai_failure


PRESET_PROVIDERS = [
    {"slot": "vision", "name": "Qwen 3.6 Plus（推荐）", "provider": "qwen",
     "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model_id": "qwen3.6-plus", "is_active": True},
    {"slot": "vision", "name": "Kimi K2.5", "provider": "kimi",
     "base_url": "https://api.moonshot.cn/v1", "model_id": "kimi-k2.5", "is_active": False},
    {"slot": "vision", "name": "GLM-4.5V", "provider": "glm",
     "base_url": "https://open.bigmodel.cn/api/paas/v4", "model_id": "glm-4.5v", "is_active": False},
    {"slot": "vision", "name": "Doubao Seed 2.0（豆包/火山方舟）", "provider": "doubao",
     "base_url": "https://ark.cn-beijing.volces.com/api/v3", "model_id": "doubao-seed-2-0-250615", "is_active": False},
    {"slot": "report", "name": "DeepSeek-V3（推荐）", "provider": "deepseek",
     "base_url": "https://api.deepseek.com/v1", "model_id": "deepseek-chat", "is_active": True},
    {"slot": "report", "name": "Doubao Seed 2.0（豆包/火山方舟）", "provider": "doubao",
     "base_url": "https://ark.cn-beijing.volces.com/api/v3", "model_id": "ep-xxxxxxxx-xxxxx", "is_active": False},
    {"slot": "report", "name": "MiniMax M2.7", "provider": "minimax",
     "base_url": "https://api.minimax.chat/v1", "model_id": "MiniMax-Text-01", "is_active": False},
    {"slot": "report", "name": "GLM-5", "provider": "glm",
     "base_url": "https://open.bigmodel.cn/api/paas/v4", "model_id": "glm-5", "is_active": False},
    {"slot": "report", "name": "Qwen-Max", "provider": "qwen",
     "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model_id": "qwen-max-latest", "is_active": False},
]

ENV_KEYS_BY_PROVIDER = {
    "qwen": ["QWEN_API_KEY", "DASHSCOPE_API_KEY"],
    "deepseek": ["DEEPSEEK_API_KEY"],
    "kimi": ["KIMI_API_KEY"],
    "doubao": ["DOUBAO_API_KEY"],
    "minimax": ["MINIMAX_API_KEY"],
    "glm": ["GLM_API_KEY"],
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


def is_claude_compatible_provider(provider_name: str) -> bool:
    return provider_name in CLAUDE_COMPATIBLE_PROVIDERS


def default_extra_body(model_id: str) -> dict[str, Any] | None:
    return {"enable_thinking": False} if model_id == "qwen3.6-plus" else None


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


def _split_system_messages(messages: list[dict[str, object]]) -> tuple[str | None, list[dict[str, str]]]:
    system_parts: list[str] = []
    normalized_messages: list[dict[str, str]] = []
    for message in messages:
        role = str(message.get("role", "")).strip()
        content = extract_message_text(message.get("content"))
        if not content:
            continue
        if role == "system":
            system_parts.append(content)
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


async def _request_claude_compatible_completion(
    provider: ActiveProviderConfig, *, messages: list[dict[str, object]],
    temperature: float, max_tokens: int, timeout: float,
) -> str:
    system_prompt, normalized_messages = _split_system_messages(messages)
    if not normalized_messages:
        normalized_messages = [{"role": "user", "content": "Reply with ok."}]
    payload: dict[str, Any] = {"model": provider.model_id, "max_tokens": max_tokens,
                                "messages": normalized_messages, "temperature": temperature}
    if system_prompt:
        payload["system"] = system_prompt
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            _claude_messages_url(provider.base_url),
            headers={"x-api-key": provider.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json=payload)
        response.raise_for_status()
        data = response.json()
    content = data.get("content", [])
    if not isinstance(content, list):
        return ""
    text_parts = [str(item.get("text", "")).strip() for item in content
                  if isinstance(item, dict) and item.get("type") == "text" and str(item.get("text", "")).strip()]
    return "\n".join(text_parts).strip()


async def request_text_completion(
    provider: ActiveProviderConfig, *, messages: list[dict[str, object]],
    temperature: float, max_tokens: int, extra_body: dict[str, Any] | None = None, timeout: float = 45.0,
) -> str:
    if is_claude_compatible_provider(provider.provider):
        return await _request_claude_compatible_completion(
            provider, messages=messages, temperature=temperature, max_tokens=max_tokens, timeout=timeout)
    client = AsyncOpenAI(api_key=provider.api_key, base_url=provider.base_url, timeout=timeout, max_retries=0)
    response = await client.chat.completions.create(
        model=provider.model_id, messages=messages, max_tokens=max_tokens,
        temperature=temperature, extra_body=extra_body or default_extra_body(provider.model_id))
    return extract_message_text(response.choices[0].message.content).strip()


async def get_active_provider(slot: str, session=None) -> ActiveProviderConfig:
    """
    获取指定 slot 的激活供应商配置。

    独立版：从环境变量读取 API Key，使用预置供应商列表。
    原版从 SQLAlchemy 数据库查询。
    """
    for preset in PRESET_PROVIDERS:
        if preset["slot"] == slot and preset["is_active"]:
            api_key = _resolve_preset_api_key(preset["provider"])
            if not api_key:
                raise RuntimeError(f"{preset['name']} 尚未配置 API Key，请设置环境变量 {ENV_KEYS_BY_PROVIDER.get(preset['provider'], ['API_KEY'])}")
            return ActiveProviderConfig(
                id=f"preset_{preset['provider']}_{slot}",
                slot=slot, name=preset["name"], provider=preset["provider"],
                base_url=preset["base_url"], model_id=preset["model_id"],
                vision_model=None, api_key=api_key, notes="系统预置")
    raise RuntimeError(f"未找到 slot={slot} 的激活供应商。")
