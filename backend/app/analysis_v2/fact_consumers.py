from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal, Mapping

from app.analysis_v2.facts import (
    AnalysisFactV2,
    AnalysisFactsV2,
    Authority,
    DerivedArtifactReferenceV2,
)
from app.analysis_v2.presentation import AuthorityMismatchError, project_analysis_facts


FACTS_SCHEMA_VERSION = "analysis-facts.v2"


FactUse = Literal[
    "family_display",
    "coaching",
    "aggregation",
    "comparison",
    "correction",
    "automation",
    "share",
    "export",
]


@dataclass(frozen=True)
class AnalysisFactConsumer:
    """Bounded same-authority input for migrated semantic consumers."""

    analysis_id: str
    authority: Authority
    use: FactUse
    source_fact_hash: str
    source_fact_revision: int
    source_pipeline_fingerprint: str
    facts: tuple[AnalysisFactV2, ...]
    # Complete same-authority set retained for conversational consumers that
    # must disclose uncertainty/conflict instead of silently dropping it.
    all_facts: tuple[AnalysisFactV2, ...] = ()


def build_fact_consumer(facts: AnalysisFactsV2, use: FactUse) -> AnalysisFactConsumer:
    revisions = [fact.source_fact_revision for fact in facts.facts]
    fingerprints = {fact.source_pipeline_fingerprint for fact in facts.facts}
    if len(fingerprints) > 1:
        raise AuthorityMismatchError("fact consumer cannot combine pipeline fingerprints")
    return AnalysisFactConsumer(
        analysis_id=facts.analysis_id,
        authority=facts.authority,
        use=use,
        source_fact_hash=facts.source_fact_hash,
        source_fact_revision=max(revisions, default=1),
        source_pipeline_fingerprint=next(iter(fingerprints), f"{facts.authority}:empty"),
        facts=facts.eligible(use),
        all_facts=facts.facts,
    )


def _stored_facts(record: Any) -> AnalysisFactsV2 | None:
    payload = getattr(record, "analysis_facts", None)
    if not isinstance(payload, Mapping):
        return None
    raw = dict(payload)
    if raw.get("schema_version") not in {None, FACTS_SCHEMA_VERSION}:
        raise ValueError("unsupported persisted analysis facts schema")
    raw.pop("schema_version", None)
    fact_set = AnalysisFactsV2.model_validate(raw)
    declared_authority = getattr(record, "facts_authority", None)
    declared_hash = getattr(record, "source_fact_hash", None)
    if declared_authority and declared_authority != fact_set.authority:
        raise AuthorityMismatchError("persisted facts authority does not match analysis metadata")
    if declared_hash and declared_hash != fact_set.source_fact_hash:
        raise ValueError("persisted facts hash does not match analysis metadata")
    return fact_set


def facts_for_analysis(record: Any) -> AnalysisFactsV2:
    """Return the one persisted authority, or a wholesale legacy projection.

    Shadow data is never eligible here: if no family-authoritative V2 facts are
    persisted, the legacy whole-record adapter is used.  Services therefore do
    not inspect raw fields or decide authority independently.
    """

    stored = _stored_facts(record)
    if stored is not None:
        return stored
    return project_analysis_facts(record, pipeline_mode="legacy")


def consumer_for_analysis(record: Any, use: FactUse) -> AnalysisFactConsumer:
    return build_fact_consumer(facts_for_analysis(record), use)


def persist_analysis_facts(record: Any, facts: AnalysisFactsV2) -> None:
    if str(getattr(record, "id", "")) != facts.analysis_id:
        raise ValueError("analysis facts belong to another analysis")
    consumer = build_fact_consumer(facts, "family_display")
    record.analysis_facts = {
        "schema_version": FACTS_SCHEMA_VERSION,
        **facts.model_dump(mode="json"),
    }
    record.facts_authority = facts.authority
    record.facts_schema_version = FACTS_SCHEMA_VERSION
    record.source_fact_hash = facts.source_fact_hash
    record.source_fact_revision = consumer.source_fact_revision
    record.source_pipeline_fingerprint = consumer.source_pipeline_fingerprint


def generation_fingerprint(
    *,
    artifact_type: str,
    source_fact_hash: str,
    provider: str | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
    renderer_version: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> str:
    payload = {
        "artifact_type": artifact_type,
        "source_fact_hash": source_fact_hash,
        "provider": provider or "deterministic",
        "model": model or "none",
        "prompt_version": prompt_version or "none",
        "renderer_version": renderer_version or "none",
        "extra": dict(extra or {}),
    }
    canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def artifact_reference(
    consumer: AnalysisFactConsumer,
    *,
    artifact_type: str,
    generation: str,
) -> DerivedArtifactReferenceV2:
    return DerivedArtifactReferenceV2(
        artifact_type=artifact_type,
        source_fact_hash=consumer.source_fact_hash,
        source_fact_revision=consumer.source_fact_revision,
        authority=consumer.authority,
        source_pipeline_fingerprint=consumer.source_pipeline_fingerprint,
        generation_fingerprint=generation,
    )


def artifact_metadata(reference: DerivedArtifactReferenceV2) -> dict[str, Any]:
    return {
        "facts_authority": reference.authority,
        "facts_schema_version": reference.source_fact_schema_version,
        "source_fact_hash": reference.source_fact_hash,
        "source_fact_revision": reference.source_fact_revision,
        "source_pipeline_fingerprint": reference.source_pipeline_fingerprint,
        "generation_fingerprint": reference.generation_fingerprint,
    }


def apply_artifact_metadata(target: Any, reference: DerivedArtifactReferenceV2) -> None:
    for name, value in artifact_metadata(reference).items():
        setattr(target, name, value)


def family_safe_fact_payload(
    consumer: AnalysisFactConsumer,
    *,
    include_noneligible: bool = False,
) -> dict[str, Any]:
    """Serialize bounded semantic facts without exposing raw provider fields.

    Most downstream consumers intentionally receive only confirmed eligible
    facts.  Follow-up chat is different: it must tell the user when evidence
    is uncertain, conflicted, or unobservable.  ``include_noneligible`` keeps
    those same-authority claims while preserving the exact safe field allowlist.
    """
    source_facts = consumer.all_facts if include_noneligible else consumer.facts
    return {
        "schema_version": FACTS_SCHEMA_VERSION,
        "analysis_id": consumer.analysis_id,
        "authority": consumer.authority,
        "source_fact_hash": consumer.source_fact_hash,
        "source_fact_revision": consumer.source_fact_revision,
        "source_pipeline_fingerprint": consumer.source_pipeline_fingerprint,
        "facts": [
            {
                "event_id": fact.event_id,
                "claim_type": fact.claim_type,
                "value": fact.value,
                "status": fact.status,
                "observability": fact.observability,
                "confidence": fact.confidence,
                "sources": list(fact.sources),
                "conflicts": list(fact.conflicts),
                "source_fingerprints": dict(fact.source_fingerprints),
                "definition_version": fact.definition_version,
                "compatibility_group": fact.compatibility_group,
                "unit": fact.unit,
                "convention": fact.convention,
                "source_references": list(fact.source_references),
            }
            for fact in source_facts
        ],
    }
