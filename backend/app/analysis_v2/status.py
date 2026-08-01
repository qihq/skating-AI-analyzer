from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.analysis_v2.facts import AnalysisFactV2, Authority
from app.analysis_v2.presentation import AnalysisExperienceV2, AuthorityMismatchError


SCHEMA_VERSION = "analysis-experience.v2"


@dataclass(frozen=True)
class ExperienceCacheKey:
    schema_version: str
    authority: Authority
    source_pipeline_fingerprint: str
    analysis_id: str

    def __str__(self) -> str:
        return ":".join(
            (self.schema_version, self.authority, self.source_pipeline_fingerprint, self.analysis_id)
        )

    @classmethod
    def parse(cls, value: str) -> "ExperienceCacheKey":
        if not isinstance(value, str):
            raise ValueError("cache key must be a string")
        parts = value.split(":", 2)
        if len(parts) != 3:
            raise ValueError("invalid experience cache key")
        schema_version, authority, rest = parts
        fingerprint, separator, analysis_id = rest.rpartition(":")
        if not separator:
            raise ValueError("invalid experience cache key")
        if schema_version != SCHEMA_VERSION or authority not in {"legacy", "v2"}:
            raise ValueError("unsupported experience cache key")
        if not fingerprint or not analysis_id:
            raise ValueError("cache key identity is incomplete")
        return cls(schema_version, authority, fingerprint, analysis_id)


def build_experience_cache_key(*, analysis_id: str, authority: Authority, source_pipeline_fingerprint: str) -> str:
    if not analysis_id or not source_pipeline_fingerprint:
        raise ValueError("analysis_id and source_pipeline_fingerprint are required")
    if authority not in {"legacy", "v2"}:
        raise ValueError("unsupported experience authority")
    return str(ExperienceCacheKey(SCHEMA_VERSION, authority, source_pipeline_fingerprint, analysis_id))


@dataclass(frozen=True)
class StatusLanguageV2:
    code: Literal["ready", "diagnostic_only", "unavailable", "unsupported_schema", "mixed_authority"]
    authority: Authority | None
    family_usable: bool
    diagnostic_only: bool
    message: str


def status_language_for_payload(payload: Any) -> StatusLanguageV2:
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        return StatusLanguageV2(
            code="unsupported_schema",
            authority=None,
            family_usable=False,
            diagnostic_only=True,
            message="此分析版本暂不支持，无法安全显示新的分析结论。",
        )
    authority = payload.get("authority")
    if authority not in {"legacy", "v2"}:
        return StatusLanguageV2("mixed_authority", None, False, True, "分析来源不一致，需要重新读取。")
    diagnostic_only = bool(payload.get("diagnostic_only", False))
    family_usable = bool(payload.get("family_usable", not diagnostic_only)) and not diagnostic_only
    return StatusLanguageV2(
        code="diagnostic_only" if diagnostic_only else ("ready" if family_usable else "unavailable"),
        authority=authority,
        family_usable=family_usable,
        diagnostic_only=diagnostic_only,
        message="仅供家长诊断查看，尚未用于家庭页面。" if diagnostic_only else ("分析结果可查看。" if family_usable else "分析结果暂不可用。"),
    )


def validate_same_authority(experiences: tuple[AnalysisExperienceV2, ...] | list[AnalysisExperienceV2]) -> None:
    if not experiences:
        return
    first = experiences[0]
    identity = (first.schema_version, first.authority, first.source_pipeline_fingerprint, first.analysis_id)
    if any((item.schema_version, item.authority, item.source_pipeline_fingerprint, item.analysis_id) != identity for item in experiences[1:]):
        raise AuthorityMismatchError("experiences must share schema, authority, fingerprint, and analysis")


def select_experience_claim(
    experience: AnalysisExperienceV2,
    claim_type: str,
    *,
    authority: Authority,
    source_pipeline_fingerprint: str,
) -> AnalysisFactV2 | None:
    if experience.schema_version != SCHEMA_VERSION or experience.authority != authority:
        raise AuthorityMismatchError("selector authority does not match experience")
    if experience.source_pipeline_fingerprint != source_pipeline_fingerprint:
        raise AuthorityMismatchError("selector fingerprint does not match experience")
    for claim in experience.claims:
        if claim.authority != authority or claim.source_pipeline_fingerprint != source_pipeline_fingerprint:
            raise AuthorityMismatchError("experience contains mixed claim authority")
        if claim.claim_type == claim_type:
            return claim
    return None
