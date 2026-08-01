from __future__ import annotations

import pytest

from app.analysis_v2.presentation import AnalysisExperienceV2, AuthorityMismatchError, EventV2
from app.analysis_v2.status import (
    ExperienceCacheKey,
    StatusLanguageV2,
    build_experience_cache_key,
    select_experience_claim,
    status_language_for_payload,
    validate_same_authority,
)


def test_cache_key_is_deterministic_and_includes_contract_identity() -> None:
    key = build_experience_cache_key(
        analysis_id="a1",
        authority="v2",
        source_pipeline_fingerprint="fp-1",
    )
    assert key == "analysis-experience.v2:v2:fp-1:a1"
    assert ExperienceCacheKey.parse(key).analysis_id == "a1"


def test_cache_key_rejects_empty_identity_parts() -> None:
    with pytest.raises(ValueError):
        build_experience_cache_key(analysis_id="", authority="legacy", source_pipeline_fingerprint="fp")


def test_selector_rejects_claim_with_mixed_authority_or_fingerprint() -> None:
    experience = AnalysisExperienceV2(
        analysis_id="a1",
        authority="legacy",
        pipeline_mode="legacy",
        source_pipeline_fingerprint="legacy:1",
        claims=(),
    )
    with pytest.raises(AuthorityMismatchError):
        select_experience_claim(experience, "action", authority="v2", source_pipeline_fingerprint="v2:1")


def test_validate_same_authority_rejects_mixed_experiences() -> None:
    legacy = AnalysisExperienceV2(
        analysis_id="a1", authority="legacy", pipeline_mode="legacy", source_pipeline_fingerprint="legacy:1"
    )
    v2 = AnalysisExperienceV2(
        analysis_id="a1", authority="v2", pipeline_mode="v2", source_pipeline_fingerprint="v2:1"
    )
    with pytest.raises(AuthorityMismatchError):
        validate_same_authority((legacy, v2))


def test_unsupported_schema_has_safe_status_language_fallback() -> None:
    result = status_language_for_payload({"schema_version": "analysis-experience.v99", "analysis_id": "a1"})
    assert isinstance(result, StatusLanguageV2)
    assert result.code == "unsupported_schema"
    assert result.family_usable is False
    assert result.diagnostic_only is True
