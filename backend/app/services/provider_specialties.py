from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)

PROVIDER_SPECIALTIES_CONFIG_PATH = Path(__file__).resolve().parents[1] / "configs" / "provider_specialties.json"

SPECIALTY_WEIGHT_KEYS = (
    "frame_phase_weight",
    "video_temporal_weight",
    "jump_subtype_weight",
    "blade_edge_weight",
    "child_motion_weight",
    "json_reliability_weight",
)

CONSERVATIVE_DEFAULT_SPECIALTY: dict[str, float] = {
    key: 0.5 for key in SPECIALTY_WEIGHT_KEYS
}


def load_provider_specialty(provider_name: str | None) -> dict[str, float]:
    """
    Load base specialty weights for an AI provider.

    Missing provider config, malformed JSON, and incomplete provider entries all fall back
    to conservative defaults so provider scoring never fails the analysis pipeline.
    """
    config = _load_config()
    defaults = _normalize_weights(config.get("defaults") if isinstance(config, dict) else None)
    provider_key = _normalize_provider_name(provider_name)

    providers = config.get("providers") if isinstance(config, dict) else None
    provider_weights = providers.get(provider_key) if isinstance(providers, dict) and provider_key else None
    normalized = _normalize_weights(provider_weights, defaults)

    return dict(normalized)


def _load_config() -> dict[str, Any]:
    if not PROVIDER_SPECIALTIES_CONFIG_PATH.exists():
        return {}

    try:
        data = json.loads(PROVIDER_SPECIALTIES_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to read provider specialties config, using defaults: %s", exc)
        return {}

    return data if isinstance(data, dict) else {}


def _normalize_weights(
    raw_weights: Any,
    fallback: dict[str, float] | None = None,
) -> dict[str, float]:
    base = dict(fallback or CONSERVATIVE_DEFAULT_SPECIALTY)
    if not isinstance(raw_weights, dict):
        return base

    for key in SPECIALTY_WEIGHT_KEYS:
        value = raw_weights.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            base[key] = _clamp_weight(float(value))
    return base


def _clamp_weight(value: float) -> float:
    return max(0.0, min(1.0, value))


def _normalize_provider_name(provider_name: str | None) -> str:
    return str(provider_name or "").strip().lower()
