from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from openai import AsyncOpenAI


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


async def request_text_completion(
    provider: ActiveProviderConfig,
    *,
    messages: list[dict[str, object]],
    temperature: float,
    max_tokens: int,
    extra_body: dict[str, Any] | None = None,
    timeout: float = 45.0,
) -> str:
    if is_claude_compatible_provider(provider.provider):
        return await _request_claude_compatible_completion(
            provider, messages=messages, temperature=temperature, max_tokens=max_tokens, timeout=timeout,
        )
    client = AsyncOpenAI(api_key=provider.api_key, base_url=provider.base_url, timeout=timeout, max_retries=0)
    response = await client.chat.completions.create(
        model=provider.model_id,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        extra_body=extra_body or default_extra_body(provider.model_id),
    )
    return extract_message_text(response.choices[0].message.content).strip()
