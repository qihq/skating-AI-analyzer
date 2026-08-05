from __future__ import annotations

"""Versioned rotation facts and definition-compatible downstream selectors."""

from dataclasses import dataclass
from typing import Literal

from app.analysis_v2.contracts import RotationEstimate
from app.analysis_v2.facts import AnalysisFactV2, AnalysisFactsV2, FactPermission


RotationConsumer = Literal["comparison", "progress", "monthly", "annual", "report_context"]
ROTATION_DEFINITION = "airborne-body-rotation.source-pts.v1"
ROTATION_COMPATIBILITY_GROUP = "rotation/airborne-body/source-pts/v1"
SPIN_ROTATION_DEFINITION = "observed-spin-rotation.source-pts.v1"
SPIN_ROTATION_COMPATIBILITY_GROUP = "rotation/observed-spin/source-pts/v1"
ROTATION_UNIT = "turns"


@dataclass(frozen=True)
class RotationSelectorResult:
    eligible: bool
    fact: AnalysisFactV2 | None
    reason: str | None
    context: tuple[AnalysisFactV2, ...] = ()


def rotation_fact_from_estimate(
    *, analysis_id: str, estimate: RotationEstimate, source_pipeline_fingerprint: str,
    diagnostic_only: bool = False,
) -> AnalysisFactV2:
    permission = FactPermission(
        family_display=True,
        aggregation=not diagnostic_only and estimate.status == "exact",
        comparison=not diagnostic_only and estimate.status == "exact",
        coaching=False,
        correction=True,
        automation=False,
        share=True,
        export=True,
    )
    if estimate.status == "exact":
        value: object = estimate.value_turns
        status = "confirmed"
        observability = "observable"
    elif estimate.status == "range":
        value = {"min_turns": estimate.range_turns[0], "max_turns": estimate.range_turns[1]} if estimate.range_turns else None
        status = "uncertain"
        observability = "partially_observable"
    else:
        value = None
        status = "unobservable"
        observability = "unobservable"
    return AnalysisFactV2(
        analysis_id=analysis_id,
        event_id=estimate.event_id,
        claim_type="airborne_body_rotation_turns_v1" if estimate.profile == "jump" else "observed_spin_rotation_turns_v1",
        value=value,
        authority="v2",
        source_pipeline_fingerprint=source_pipeline_fingerprint,
        definition_version=estimate.definition_version,
        compatibility_group=ROTATION_COMPATIBILITY_GROUP if estimate.profile == "jump" else SPIN_ROTATION_COMPATIBILITY_GROUP,
        unit=ROTATION_UNIT,
        convention=estimate.value_convention,
        status=status,
        observability=observability,
        confidence=estimate.confidence,
        provenance=tuple(dict.fromkeys(("multi_signal_rotation", *(item.signal for item in estimate.signals)))),
        source_references=tuple(item.phase for item in estimate.phases),
        permissions=permission,
    )


def select_rotation_fact(facts: AnalysisFactsV2, consumer: RotationConsumer) -> RotationSelectorResult:
    permission = "family_display" if consumer == "report_context" else "comparison" if consumer == "comparison" else "aggregation"
    candidates = tuple(
        fact for fact in facts.facts
        if fact.claim_type in {"airborne_body_rotation_turns_v1", "observed_spin_rotation_turns_v1"}
    )
    def matches_authoritative_definition(fact: AnalysisFactV2) -> bool:
        if fact.claim_type == "airborne_body_rotation_turns_v1":
            return (
                fact.definition_version == ROTATION_DEFINITION
                and fact.compatibility_group == ROTATION_COMPATIBILITY_GROUP
                and fact.convention == "airborne_body_rotation"
            )
        return (
            fact.definition_version == SPIN_ROTATION_DEFINITION
            and fact.compatibility_group == SPIN_ROTATION_COMPATIBILITY_GROUP
            and fact.convention == "observed_spin_rotation"
        )

    eligible = tuple(
        fact for fact in candidates
        if fact.status == "confirmed"
        and fact.observability == "observable"
        and getattr(fact.permissions, permission, False)
        and fact.unit == ROTATION_UNIT
        and matches_authoritative_definition(fact)
    )
    if eligible:
        return RotationSelectorResult(True, eligible[0], None, candidates)
    if not candidates:
        reason = "missing_rotation_fact"
    elif any(fact.status == "uncertain" or fact.observability == "partially_observable" for fact in candidates):
        reason = "rotation_range_context_only"
    elif any(fact.status == "unobservable" or fact.observability == "unobservable" for fact in candidates):
        reason = "rotation_unobservable_context_only"
    elif any(fact.unit != ROTATION_UNIT for fact in candidates):
        reason = "rotation_unit_mismatch"
    elif any(
        (fact.claim_type == "airborne_body_rotation_turns_v1" and fact.convention != "airborne_body_rotation")
        or (fact.claim_type == "observed_spin_rotation_turns_v1" and fact.convention != "observed_spin_rotation")
        for fact in candidates
    ):
        reason = "rotation_convention_mismatch"
    elif any(
        (fact.claim_type == "airborne_body_rotation_turns_v1" and fact.definition_version != ROTATION_DEFINITION)
        or (fact.claim_type == "observed_spin_rotation_turns_v1" and fact.definition_version != SPIN_ROTATION_DEFINITION)
        for fact in candidates
    ):
        reason = "rotation_definition_mismatch"
    elif any(
        (fact.claim_type == "airborne_body_rotation_turns_v1" and fact.compatibility_group != ROTATION_COMPATIBILITY_GROUP)
        or (fact.claim_type == "observed_spin_rotation_turns_v1" and fact.compatibility_group != SPIN_ROTATION_COMPATIBILITY_GROUP)
        for fact in candidates
    ):
        reason = "rotation_compatibility_group_mismatch"
    else:
        reason = "rotation_not_eligible"
    return RotationSelectorResult(False, None, reason, candidates)


def select_rotation_delta(left: AnalysisFactsV2, right: AnalysisFactsV2) -> dict[str, object]:
    left_result = select_rotation_fact(left, "comparison")
    right_result = select_rotation_fact(right, "comparison")
    context = {"left": left_result.context, "right": right_result.context}
    if not left_result.eligible or not right_result.eligible or left_result.fact is None or right_result.fact is None:
        mismatch_reasons = {
            "rotation_definition_mismatch",
            "rotation_unit_mismatch",
            "rotation_convention_mismatch",
            "rotation_compatibility_group_mismatch",
        }
        reason = left_result.reason or right_result.reason
        if left_result.reason in mismatch_reasons or right_result.reason in mismatch_reasons:
            reason = "rotation_definition_unit_or_convention_mismatch"
        return {"eligible": False, "delta_turns": None, "reason": reason, "context": context}
    if (
        left_result.fact.definition_version != right_result.fact.definition_version
        or left_result.fact.unit != right_result.fact.unit
        or left_result.fact.convention != right_result.fact.convention
        or left_result.fact.compatibility_group != right_result.fact.compatibility_group
    ):
        return {"eligible": False, "delta_turns": None, "reason": "rotation_definition_unit_or_convention_mismatch", "context": context}
    return {
        "eligible": True,
        "delta_turns": round(float(right_result.fact.value) - float(left_result.fact.value), 4),
        "reason": None,
        "definition_version": left_result.fact.definition_version,
        "unit": left_result.fact.unit,
        "convention": left_result.fact.convention,
        "context": context,
    }
