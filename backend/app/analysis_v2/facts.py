from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Authority = Literal["legacy", "v2"]
FactStatus = Literal["confirmed", "uncertain", "unobservable"]
FactProvenance = Literal[
    "measured",
    "smoothed",
    "interpolated-display-only",
    "missing",
    "clipped",
    "identity-blocked",
    "legacy-whole-record",
]
Observability = Literal["observable", "partially_observable", "unobservable"]


class FactPermission(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    family_display: bool = True
    aggregation: bool = False
    comparison: bool = False
    coaching: bool = False
    correction: bool = False
    automation: bool = False
    share: bool = False
    export: bool = True


class AnalysisFactV2(BaseModel):
    """Backend-owned, single-authority semantic fact used by downstream services."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    analysis_id: str
    event_id: str | None = None
    claim_type: str
    value: Any = None
    authority: Authority
    source_pipeline_fingerprint: str
    source_fact_revision: int = Field(default=1, ge=1)
    definition_version: str
    compatibility_group: str | None = None
    unit: str | None = None
    convention: str | None = None
    status: FactStatus = "confirmed"
    observability: Observability = "observable"
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    provenance: tuple[str, ...] = ()
    source_references: tuple[str, ...] = ()
    permissions: FactPermission = Field(default_factory=FactPermission)
    source_fact_hash: str | None = None

    @model_validator(mode="after")
    def _validate_status(self) -> "AnalysisFactV2":
        forbidden_pose_provenance = {"interpolated-display-only", "identity-blocked"}
        if forbidden_pose_provenance.intersection(self.provenance):
            if self.permissions.aggregation or self.permissions.comparison or self.permissions.coaching or self.permissions.automation:
                raise ValueError("interpolated-only or identity-blocked facts cannot be used downstream")
            if self.status == "confirmed":
                raise ValueError("blocked pose provenance cannot be confirmed")
        if self.status == "unobservable" or self.observability == "unobservable":
            if self.value is not None:
                raise ValueError("unobservable fact cannot carry a value")
            if self.permissions.aggregation or self.permissions.comparison or self.permissions.coaching:
                raise ValueError("unobservable fact cannot be used downstream")
        if self.authority == "v2" and self.source_pipeline_fingerprint == "":
            raise ValueError("V2 facts require a pipeline fingerprint")
        if self.source_fact_hash is None:
            object.__setattr__(self, "source_fact_hash", fact_hash(self))
        return self


def _fact_payload(fact: AnalysisFactV2) -> dict[str, Any]:
    payload = fact.model_dump(mode="json", exclude={"source_fact_hash"})
    return payload


def fact_hash(fact: AnalysisFactV2) -> str:
    canonical = json.dumps(_fact_payload(fact), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AnalysisFactsV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    analysis_id: str
    authority: Authority
    facts: tuple[AnalysisFactV2, ...] = ()
    source_fact_hash: str = ""

    def __init__(self, **data: Any) -> None:
        facts = data.get("facts") or ()
        authority = data.get("authority")
        for fact in facts:
            fact_authority = fact.authority if isinstance(fact, AnalysisFactV2) else fact.get("authority")
            if authority is not None and fact_authority != authority:
                from app.analysis_v2.presentation import AuthorityMismatchError

                raise AuthorityMismatchError("all facts must use the collection authority")
        super().__init__(**data)

    @model_validator(mode="after")
    def _validate_authority(self) -> "AnalysisFactsV2":
        mismatched = [fact for fact in self.facts if fact.analysis_id != self.analysis_id or fact.authority != self.authority]
        if mismatched:
            raise ValueError("all facts must belong to the same analysis and authority")
        canonical = [fact_hash(fact) for fact in self.facts]
        expected = hashlib.sha256("|".join(canonical).encode("ascii")).hexdigest()
        if self.source_fact_hash and self.source_fact_hash != expected:
            raise ValueError("source_fact_hash does not match facts")
        object.__setattr__(self, "source_fact_hash", expected)
        return self

    def eligible(self, permission: str) -> tuple[AnalysisFactV2, ...]:
        return tuple(
            fact
            for fact in self.facts
            if getattr(fact.permissions, permission, False)
            and fact.status == "confirmed"
            and fact.observability == "observable"
            and not {"interpolated-display-only", "identity-blocked"}.intersection(fact.provenance)
        )


class DerivedArtifactReferenceV2(BaseModel):
    """Immutable provenance link stored by newly generated downstream artifacts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["derived-artifact-reference.v2"] = "derived-artifact-reference.v2"
    artifact_type: str = Field(min_length=1)
    source_fact_schema_version: Literal["analysis-facts.v2"] = "analysis-facts.v2"
    source_fact_hash: str = Field(min_length=1)
    source_fact_revision: int = Field(ge=1)
    authority: Authority
    source_pipeline_fingerprint: str = Field(min_length=1)
    generation_fingerprint: str = Field(min_length=1)
