from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.database import DATA_DIR


logger = logging.getLogger(__name__)

VISION_VOTE_CONFIG_PATH = DATA_DIR / "vision_vote_config.json"


def load_vision_vote_config() -> dict[str, str | None]:
    """
    Load the persisted UI-selected vision voting provider ids.

    Args:
        None.

    Returns:
        Dict with primary_provider_id and secondary_provider_id.

    Raises:
        No exception is propagated; malformed config falls back to empty ids.
    """
    if not VISION_VOTE_CONFIG_PATH.exists():
        return {"primary_provider_id": None, "secondary_provider_id": None}

    try:
        data = json.loads(VISION_VOTE_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to read vision vote config, using defaults: %s", exc)
        return {"primary_provider_id": None, "secondary_provider_id": None}

    if not isinstance(data, dict):
        return {"primary_provider_id": None, "secondary_provider_id": None}

    return {
        "primary_provider_id": _optional_string(data.get("primary_provider_id")),
        "secondary_provider_id": _optional_string(data.get("secondary_provider_id")),
    }


def save_vision_vote_config(payload: dict[str, Any]) -> dict[str, str | None]:
    """
    Persist the UI-selected vision voting provider ids.

    Args:
        payload: Raw payload with primary_provider_id and secondary_provider_id.

    Returns:
        Normalized saved config.

    Raises:
        OSError: When the config file cannot be written.
    """
    normalized = {
        "primary_provider_id": _optional_string(payload.get("primary_provider_id")),
        "secondary_provider_id": _optional_string(payload.get("secondary_provider_id")),
    }
    VISION_VOTE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(VISION_VOTE_CONFIG_PATH, normalized)
    return normalized


def _optional_string(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)
