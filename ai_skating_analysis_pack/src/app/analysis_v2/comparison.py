from __future__ import annotations

"""Definition-safe, event-aware comparison selectors for V2 facts."""

from dataclasses import dataclass
from typing import Any

from app.analysis_v2.facts import AnalysisFactV2, AnalysisFactsV2


@dataclass(frozen=True)
class ComparisonMatch:
    eligible: bool
    left: AnalysisFactV2 | None = None
    right: AnalysisFactV2 | None = None
    delta: float | None = None
    reason: str | None = None
    cross_definition: bool = False


def _eligible_by_key(facts: AnalysisFactsV2) -> dict[tuple[str | None, str, str | None], AnalysisFactV2]:
    return {
        (fact.event_id, fact.claim_type, fact.compatibility_group): fact
        for fact in facts.eligible("comparison")
    }


def _event_profile(facts: AnalysisFactsV2, event_id: str | None) -> str | None:
    """Return a confirmed, comparable action profile for one event.

    Event ids are analysis-local, so comparison must not infer compatibility
    from ids alone.  A profile is only used when it is an eligible claim; an
    uncertain/blocked profile remains unknown and is handled by the normal
    missing-evidence path.
    """

    for fact in facts.eligible("comparison"):
        if fact.event_id != event_id or fact.claim_type not in {
            "action_profile",
            "action_family",
            "action_family_support",
        }:
            continue
        value = fact.value
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
        if isinstance(value, dict):
            for key in ("profile", "action_profile", "action_family", "family"):
                candidate = value.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip().lower()
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def match_comparable_claim(
    left: AnalysisFactsV2,
    right: AnalysisFactsV2,
    *,
    claim_type: str,
    left_event_id: str | None,
    right_event_id: str | None,
) -> ComparisonMatch:
    """Match one event/profile claim and refuse incompatible deltas."""

    left_candidates = [
        fact for fact in left.eligible("comparison")
        if fact.claim_type == claim_type and fact.event_id == left_event_id
    ]
    right_candidates = [
        fact for fact in right.eligible("comparison")
        if fact.claim_type == claim_type and fact.event_id == right_event_id
    ]
    if not left_candidates or not right_candidates:
        return ComparisonMatch(False, reason="missing_confirmed_comparable_claim")
    left_fact, right_fact = left_candidates[0], right_candidates[0]
    compatible = (
        left_fact.definition_version == right_fact.definition_version
        and left_fact.compatibility_group == right_fact.compatibility_group
        and left_fact.unit == right_fact.unit
        and left_fact.convention == right_fact.convention
    )
    if not compatible:
        return ComparisonMatch(
            False,
            left_fact,
            right_fact,
            reason="cross_definition_delta_refused",
            cross_definition=True,
        )
    before, after = _number(left_fact.value), _number(right_fact.value)
    if before is None or after is None:
        return ComparisonMatch(False, left_fact, right_fact, reason="non_numeric_claim_context_only")
    return ComparisonMatch(True, left_fact, right_fact, round(after - before, 6))


def compare_fact_sets(
    left: AnalysisFactsV2,
    right: AnalysisFactsV2,
    *,
    event_pairs: tuple[tuple[str | None, str | None], ...] = ((None, None),),
) -> dict[str, Any]:
    """Return explicit compatible deltas and excluded coverage for a comparison artifact."""

    deltas: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    profile_mismatch = False
    claim_types = sorted({fact.claim_type for fact in left.facts} | {fact.claim_type for fact in right.facts})
    for left_event_id, right_event_id in event_pairs:
        left_profile = _event_profile(left, left_event_id)
        right_profile = _event_profile(right, right_event_id)
        if left_profile is not None and right_profile is not None and left_profile != right_profile:
            # Keep the conflicting event pair visible, but never calculate a
            # technical delta across action definitions.  This is distinct
            # from a metric's cross-definition mismatch so callers can render
            # the family-safe reason to parents.
            profile_mismatch = True
            excluded.append(
                {
                    "claim_type": "event_profile",
                    "left_event_id": left_event_id,
                    "right_event_id": right_event_id,
                    "reason": "profile_mismatch",
                    "cross_definition": True,
                }
            )
            continue
        for claim_type in claim_types:
            match = match_comparable_claim(
                left,
                right,
                claim_type=claim_type,
                left_event_id=left_event_id,
                right_event_id=right_event_id,
            )
            item = {
                "claim_type": claim_type,
                "left_event_id": left_event_id,
                "right_event_id": right_event_id,
                "reason": match.reason,
                "cross_definition": match.cross_definition,
            }
            if match.eligible and match.left is not None:
                deltas.append(
                    {
                        **item,
                        "before": match.left.value,
                        "after": match.right.value if match.right is not None else None,
                        "delta": match.delta,
                        "unit": match.left.unit,
                        "definition_version": match.left.definition_version,
                        "compatibility_group": match.left.compatibility_group,
                    }
                )
            elif match.left is not None or match.right is not None:
                excluded.append(item)
    return {
        "schema_version": "analysis-fact-comparison.v2",
        "left_authority": left.authority,
        "right_authority": right.authority,
        "left_source_fact_hash": left.source_fact_hash,
        "right_source_fact_hash": right.source_fact_hash,
        "deltas": deltas,
        "excluded": excluded,
        "profile_mismatch": profile_mismatch,
    }
