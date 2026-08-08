from __future__ import annotations

from pathlib import Path

import pytest

from app.analysis_v2.capabilities import build_advanced_capabilities, build_public_capabilities
from app.analysis_v2.config import load_runtime_config


def test_public_capability_is_legacy_authoritative_in_shadow_mode(tmp_path: Path) -> None:
    config = load_runtime_config(
        {
            "SKATING_ANALYSIS_PIPELINE": "shadow",
            "V2_RUNTIME_ROOT": str(tmp_path / "runtime"),
        },
        project_root=tmp_path,
    )

    payload = build_public_capabilities(config).model_dump(mode="json")

    assert payload["runtime_mode"] == "shadow"
    assert payload["public_authority"] == "legacy"
    assert payload["analysis_experience_v2_enabled"] is True
    assert payload["supported_analysis_experience_schema_versions"] == ["analysis-experience.v2"]
    assert str(tmp_path) not in str(payload)
    assert "runtime_root" not in payload
    assert "database_url" not in payload


def test_advanced_capability_reports_honest_noop_state(tmp_path: Path) -> None:
    config = load_runtime_config(
        {
            "SKATING_ANALYSIS_PIPELINE": "shadow",
            "V2_RUNTIME_ROOT": str(tmp_path / "runtime"),
        },
        project_root=tmp_path,
    )

    payload = build_advanced_capabilities(config).model_dump(mode="json")

    assert payload["shadow_status"] == "ready"
    assert payload["shadow_execution"] == "bounded_local_queue"
    assert payload["writes_user_data"] is False
    assert str(tmp_path) not in str(payload)


def test_advanced_capability_is_disabled_in_legacy_mode(tmp_path: Path) -> None:
    config = load_runtime_config({}, project_root=tmp_path)

    assert build_advanced_capabilities(config).shadow_status == "disabled"
