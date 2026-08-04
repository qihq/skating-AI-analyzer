from __future__ import annotations

"""Iteration 11 eligibility boundary for migrated downstream consumers."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from app.analysis_v2.facts import ActionProfile, AnalysisFactsV2


ProfileConsumer = Literal[
    "training_plan", "filters", "progress_grouping", "comparison", "skill_matching",
    "monthly_facts", "memory_suggestions", "growth_admission", "automatic_skill_unlock",
]


CONSUMER_PERMISSION: dict[ProfileConsumer, str] = {
    "training_plan": "coaching",
    "filters": "family_display",
    "progress_grouping": "aggregation",
    "comparison": "comparison",
    "skill_matching": "coaching",
    "monthly_facts": "aggregation",
    "memory_suggestions": "coaching",
    "growth_admission": "aggregation",
    "automatic_skill_unlock": "automation",
}


@dataclass(frozen=True)
class ProfileEligibilityDecision:
    consumer: ProfileConsumer
    eligible: bool
    profile: ActionProfile | None
    reason: str | None
    automatic_skill_unlock: bool = False


def profile_eligibility(
    facts: AnalysisFactsV2,
    consumer: ProfileConsumer,
    *,
    compatible_profiles: Iterable[ActionProfile] | None = None,
    diagnostic_only: bool = False,
) -> ProfileEligibilityDecision:
    # V2 automatic unlock remains explicitly disabled through Iteration 14.
    if consumer == "automatic_skill_unlock":
        return ProfileEligibilityDecision(consumer, False, None, "v2_automatic_unlock_disabled_until_iteration14", False)
    if diagnostic_only:
        return ProfileEligibilityDecision(consumer, False, None, "shadow_diagnostic", False)
    base = facts.profile_eligibility(permission=CONSUMER_PERMISSION[consumer])
    profile = base["profile"]
    if not base["eligible"] or profile is None:
        return ProfileEligibilityDecision(consumer, False, None, str(base["reason"]), False)
    compatible = set(compatible_profiles or ())
    if compatible and profile not in compatible:
        return ProfileEligibilityDecision(consumer, False, None, "incompatible_profile", False)
    return ProfileEligibilityDecision(consumer, True, profile, None, False)


def growth_admission(
    fact_sets: Iterable[AnalysisFactsV2], *, compatible_profiles: Iterable[ActionProfile] | None = None,
    diagnostic_fact_set_ids: Iterable[str] = (),
) -> dict[str, object]:
    included: list[str] = []
    excluded: dict[str, int] = {}
    diagnostic_ids = set(diagnostic_fact_set_ids)
    for facts in fact_sets:
        decision = profile_eligibility(
            facts,
            "growth_admission",
            compatible_profiles=compatible_profiles,
            diagnostic_only=facts.analysis_id in diagnostic_ids,
        )
        if decision.eligible:
            included.append(facts.analysis_id)
        else:
            reason = decision.reason or "not_eligible"
            excluded[reason] = excluded.get(reason, 0) + 1
    return {"included_analysis_ids": included, "included_count": len(included), "excluded_count": sum(excluded.values()), "excluded_reasons": excluded}
