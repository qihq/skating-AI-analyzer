from __future__ import annotations

from datetime import datetime, timezone
import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis_v2.fact_consumers import consumer_for_analysis, generation_fingerprint
from app.models import Analysis, Skater, SkaterSkill, SkillNode
from app.services.skills import ensure_skater_skill_rows, refresh_skater_profile, is_unlocked


logger = logging.getLogger(__name__)


_AUTOMATION_RULE_VERSION = "skill-unlock-rule.v2"
_VERSION_PATTERN = re.compile(r"(?:^|[._/-])v(?P<version>\d+)(?:$|[._/-])", re.IGNORECASE)
_BLOCKED_PROVENANCE = {
    "interpolated-display-only",
    "identity-blocked",
    "corrected-but-unconfirmed",
    "correction-pending",
    "pending-correction",
    "human_correction_pending",
}


def _score_unlock_config(node: SkillNode) -> dict[str, Any] | None:
    config = node.unlock_config if isinstance(node.unlock_config, dict) else {}
    score_config = config.get("score") if isinstance(config.get("score"), dict) else config
    if not isinstance(score_config, dict):
        return None

    threshold = int(score_config.get("threshold", 0))
    consecutive = max(int(score_config.get("consecutive", 1)), 1)
    action_type = score_config.get("action_type")
    result: dict[str, Any] = {"threshold": threshold, "consecutive": consecutive}
    if action_type is not None:
        result["action_type"] = str(action_type).strip()

    # Iteration 14 makes the rule boundary explicit while keeping the seeded
    # skill catalog backward compatible.  Existing nodes omit these fields and
    # therefore use the current evaluator version; a future catalog can pin a
    # definition/compatibility contract per rule without changing this service.
    rule = config.get("rule") if isinstance(config.get("rule"), dict) else {}
    for output_key, keys in {
        "rule_version": ("rule_version", "version"),
        "score_definition_version": ("score_definition_version", "definition_version"),
        "score_compatibility_group": ("score_compatibility_group", "compatibility_group"),
        "profile_definition_version": ("profile_definition_version", "profile_definition"),
        "profile_compatibility_group": ("profile_compatibility_group", "profile_compatibility"),
    }.items():
        value = next(
            (
                candidate
                for key in keys
                for candidate in (score_config.get(key), rule.get(key), config.get(key))
                if candidate not in (None, "")
            ),
            None,
        )
        if value is not None:
            result[output_key] = str(value).strip()
    return result  # type: ignore[return-value]


def _fact_score_and_profile(consumer) -> tuple[float | None, str | None]:
    profile = consumer.facts
    action_profile = next((fact for fact in profile if fact.claim_type == "action_profile"), None)
    score_fact = next((fact for fact in profile if fact.claim_type in {"force_score", "score"}), None)
    action_value = str(action_profile.value).strip().lower() if action_profile is not None else None
    score_value = score_fact.value if score_fact is not None else None
    score = float(score_value) if isinstance(score_value, (int, float)) and not isinstance(score_value, bool) else None
    return score, action_value


def _fact_version(value: Any) -> int | None:
    """Extract a trailing/segment version from a fact definition string."""

    if not isinstance(value, str):
        return None
    match = _VERSION_PATTERN.search(value.strip())
    if match is None:
        return None
    try:
        return int(match.group("version"))
    except (TypeError, ValueError):
        return None


def _automation_fact_gate(
    consumer: Any,
    score_fact: Any,
    profile_fact: Any,
    unlock_config: dict[str, Any],
) -> tuple[bool, str | None, dict[str, Any]]:
    """Validate the immutable fact/rule contract used by auto-unlock.

    This is deliberately claim-level and fail-closed.  It never turns an
    uncertain, conflicted, identity-blocked, or definition-incompatible fact
    into an eligible skill mutation.  The returned metadata is persisted in
    the generation fingerprint so rule changes cannot silently reuse history.
    """

    rule_version = str(unlock_config.get("rule_version") or _AUTOMATION_RULE_VERSION).strip()
    rule_version_number = _fact_version(rule_version)
    if rule_version != _AUTOMATION_RULE_VERSION or rule_version_number is None:
        return False, "unsupported_rule_version", {"rule_version": rule_version}

    facts = (score_fact, profile_fact)
    for fact in facts:
        if fact is None:
            return False, "missing_required_fact", {"rule_version": rule_version}
        if str(getattr(fact, "authority", "") or "") != str(getattr(consumer, "authority", "") or ""):
            return False, "authority_mismatch", {"rule_version": rule_version}
        if getattr(fact, "status", None) != "confirmed":
            return False, "corrected_but_unconfirmed" if "correction" in " ".join(getattr(fact, "provenance", ()) or ()).lower() else "fact_not_confirmed", {"rule_version": rule_version}
        if getattr(fact, "observability", None) != "observable":
            return False, "fact_not_observable", {"rule_version": rule_version}
        if getattr(fact, "conflicts", ()):
            return False, "fact_conflict", {"rule_version": rule_version}
        provenance = {str(item).strip().lower() for item in (getattr(fact, "provenance", ()) or ())}
        if provenance.intersection(_BLOCKED_PROVENANCE):
            return False, "blocked_provenance", {"rule_version": rule_version, "provenance": sorted(provenance)}
        definition = str(getattr(fact, "definition_version", "") or "").strip()
        compatibility = str(getattr(fact, "compatibility_group", "") or "").strip()
        if not definition or _fact_version(definition) is None:
            return False, "unversioned_fact_definition", {"rule_version": rule_version, "definition": definition}
        if not compatibility:
            return False, "missing_compatibility_group", {"rule_version": rule_version, "definition": definition}

    score_definition = str(getattr(score_fact, "definition_version", "") or "").strip()
    profile_definition = str(getattr(profile_fact, "definition_version", "") or "").strip()
    score_version = _fact_version(score_definition)
    profile_version = _fact_version(profile_definition)
    if score_version != profile_version:
        return False, "definition_version_mismatch", {
            "rule_version": rule_version,
            "score_definition_version": score_definition,
            "profile_definition_version": profile_definition,
        }

    score_group = str(getattr(score_fact, "compatibility_group", "") or "").strip()
    profile_group = str(getattr(profile_fact, "compatibility_group", "") or "").strip()
    expected_score_definition = unlock_config.get("score_definition_version")
    expected_score_group = unlock_config.get("score_compatibility_group")
    expected_profile_definition = unlock_config.get("profile_definition_version")
    expected_profile_group = unlock_config.get("profile_compatibility_group")
    if expected_score_definition and score_definition != expected_score_definition:
        return False, "score_definition_incompatible", {"rule_version": rule_version}
    if expected_score_group and score_group != expected_score_group:
        return False, "score_compatibility_incompatible", {"rule_version": rule_version}
    if expected_profile_definition and profile_definition != expected_profile_definition:
        return False, "profile_definition_incompatible", {"rule_version": rule_version}
    if expected_profile_group and profile_group != expected_profile_group:
        return False, "profile_compatibility_incompatible", {"rule_version": rule_version}

    score_event = getattr(score_fact, "event_id", None)
    profile_event = getattr(profile_fact, "event_id", None)
    if score_event and profile_event and score_event != profile_event:
        return False, "required_fact_event_mismatch", {"rule_version": rule_version}

    source_hash = str(getattr(consumer, "source_fact_hash", "") or "").strip()
    source_fingerprint = str(getattr(consumer, "source_pipeline_fingerprint", "") or "").strip()
    revision = getattr(consumer, "source_fact_revision", None)
    if not source_hash or not source_fingerprint or not isinstance(revision, int) or revision < 1:
        return False, "missing_fact_provenance", {"rule_version": rule_version}

    metadata = {
        "rule_version": rule_version,
        "score_definition_version": score_definition,
        "score_compatibility_group": score_group,
        "profile_definition_version": profile_definition,
        "profile_compatibility_group": profile_group,
        "authority": str(getattr(consumer, "authority", "") or ""),
        "source_fact_revision": revision,
    }
    return True, None, metadata


_PROFILE_ACTION_TYPES = {"jump": "跳跃", "spin": "旋转", "step": "步法", "spiral": "步法"}


async def auto_update_skill_progress(analysis_id: str, db: AsyncSession) -> None:
    analysis = await db.get(Analysis, analysis_id)
    if analysis is None:
        return

    if not analysis.skill_node_id or not analysis.skater_id:
        return

    try:
        consumer = consumer_for_analysis(analysis, "automation")
    except (ValueError, TypeError):
        return
    current_score, action_profile = _fact_score_and_profile(consumer)
    if current_score is None or action_profile is None:
        return

    profile_fact = next((fact for fact in consumer.facts if fact.claim_type == "action_profile"), None)
    score_fact = next((fact for fact in consumer.facts if fact.claim_type in {"force_score", "score"}), None)

    skater = await db.get(Skater, analysis.skater_id)
    node = await db.get(SkillNode, analysis.skill_node_id)
    if skater is None or node is None:
        return

    await ensure_skater_skill_rows(db, skater)
    row_result = await db.execute(
        select(SkaterSkill).where(SkaterSkill.skater_id == skater.id, SkaterSkill.skill_id == node.id).limit(1)
    )
    row = row_result.scalar_one_or_none()
    if row is None:
        return

    analysis.auto_unlocked_skill = None

    unlock_config = _score_unlock_config(node)
    if unlock_config is None:
        await refresh_skater_profile(db, skater.id)
        return

    # Legacy projections retain their historical score behavior.  V2 facts
    # must pass the explicit, versioned claim/rule boundary before they can
    # mutate attempt/best/unlock state.  This keeps Shadow, uncertain,
    # unobservable, corrected, and incompatible definitions inert.
    rule_metadata: dict[str, Any] = {}
    if str(consumer.authority) == "v2":
        eligible, reason, rule_metadata = _automation_fact_gate(
            consumer,
            score_fact,
            profile_fact,
            unlock_config,
        )
        if not eligible:
            logger.info(
                "Analysis %s skill automation excluded: %s",
                analysis_id,
                reason or "ineligible",
            )
            await refresh_skater_profile(db, skater.id)
            return

    current_score = max(int(current_score), 0)
    row.best_score = max(row.best_score or 0, current_score)

    threshold = unlock_config["threshold"]
    consecutive = unlock_config["consecutive"]

    expected_action_type = unlock_config.get("action_type")
    if expected_action_type and _PROFILE_ACTION_TYPES.get(action_profile) != expected_action_type:
        await refresh_skater_profile(db, skater.id)
        return

    if current_score < threshold:
        await refresh_skater_profile(db, skater.id)
        return

    row.attempt_count = max(row.attempt_count or 0, 0) + 1

    if row.attempt_count >= consecutive:
        previously_unlocked = is_unlocked(row.status)
        row.status = "unlocked"
        row.unlocked_by = "auto"
        row.unlocked_at = row.unlocked_at or datetime.now(timezone.utc)
        row.facts_authority = consumer.authority
        row.facts_schema_version = "analysis-facts.v2"
        row.source_fact_hash = consumer.source_fact_hash
        row.source_fact_revision = consumer.source_fact_revision
        row.source_pipeline_fingerprint = consumer.source_pipeline_fingerprint
        row.generation_fingerprint = generation_fingerprint(
            artifact_type="skill-automation",
            source_fact_hash=consumer.source_fact_hash,
            prompt_version=_AUTOMATION_RULE_VERSION,
            extra={
                "skill_id": node.id,
                "rule": unlock_config,
                "rule_metadata": rule_metadata,
            },
        )
        if not previously_unlocked:
            analysis.auto_unlocked_skill = node.id
    elif row.status == "locked":
        row.status = "attempting"

    await refresh_skater_profile(db, skater.id)
