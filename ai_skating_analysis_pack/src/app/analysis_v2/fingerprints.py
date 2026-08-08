from __future__ import annotations

import hashlib
import json
from typing import Any


SECRET_KEYS = {"api_key", "apikey", "secret", "token", "password", "authorization", "credential"}


def _redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "<redacted>" if str(key).lower() in SECRET_KEYS or any(term in str(key).lower() for term in SECRET_KEYS) else _redact_secrets(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_secrets(item) for item in value]
    return value


def pipeline_fingerprint(*, source_commit: str, model_files: dict[str, str], configuration: dict[str, Any], provider: str, model: str, prompt_version: str, contract_version: str, **_: Any) -> str:
    payload = {
        "source_commit": source_commit,
        "model_files": model_files,
        "configuration": _redact_secrets(configuration),
        "provider": provider,
        "model": model,
        "prompt_version": prompt_version,
        "contract_version": contract_version,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
