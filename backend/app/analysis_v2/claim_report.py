"""Report boundary: only explain already-fused EvidenceClaim records."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from app.analysis_v2.contracts import EvidenceClaim


_FORBIDDEN_REPORT_CLAIMS = {
    "invented_action",
    "invented_timestamp",
    "invented_rotation",
    "invented_technique_defect",
}


def _hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _claim_key(claim: EvidenceClaim) -> str:
    return f"{claim.event_id or 'whole'}:{claim.claim_type}:{claim.definition_version}"


def _safe_claim(claim: EvidenceClaim) -> dict[str, Any]:
    return {
        "claim_type": claim.claim_type,
        "event_id": claim.event_id,
        "value": claim.value,
        "status": claim.status,
        "observability": claim.observability,
        "confidence": claim.confidence,
        "sources": list(claim.sources),
        "source_references": list(claim.source_references),
        "conflicts": list(claim.conflicts),
        "alternatives": list(claim.alternatives),
        "selected_source": claim.selected_source,
        "definition_version": claim.definition_version,
        "unit": claim.unit,
        "convention": claim.convention,
        "compatibility_group": claim.compatibility_group,
        "source_fingerprints": dict(claim.source_fingerprints),
        "provenance": list(claim.provenance),
        "source_fact_hash": claim.source_fact_hash,
        "refusal_reason": claim.refusal_reason,
    }


def build_report_evidence(claims: Iterable[EvidenceClaim]) -> dict[str, Any]:
    ordered = tuple(sorted(claims, key=lambda claim: (_claim_key(claim), claim.definition_version)))
    return {
        "schema_version": "fused-report-evidence.v1",
        "claims": [_safe_claim(claim) for claim in ordered],
        "claim_keys": [_claim_key(claim) for claim in ordered],
        "source_fact_hash": _hash([claim.model_dump(mode="json") for claim in ordered]),
    }


def _flatten_claim_text(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        output: list[str] = []
        for key, item in value.items():
            output.extend(_flatten_claim_text(key))
            output.extend(_flatten_claim_text(item))
        return tuple(output)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        output: list[str] = []
        for item in value:
            output.extend(_flatten_claim_text(item))
        return tuple(output)
    return (str(value),)


def _claim_supports_action(claim: EvidenceClaim, family: str) -> bool:
    if claim.status != "confirmed" or claim.value is None:
        return False
    if claim.claim_type not in {"action_family", "action_family_support", "action_profile", "action_classifier"}:
        return False
    return family.casefold() in " ".join(_flatten_claim_text(claim.value)).casefold()


def _claim_supports_action_label(claim: EvidenceClaim, label: str) -> bool:
    """Check a concrete action label without treating family support as label support."""

    if claim.status != "confirmed" or claim.observability != "observed" or claim.conflicts or not label:
        return False
    if claim.claim_type not in {"action_label", "action_confirmation", "action_subtype"}:
        return False
    value = claim.value
    if isinstance(value, Mapping):
        values = [value.get(key) for key in ("confirmed_action", "jump_type", "action_label", "action_subtype")]
    else:
        values = [value]
    return any(str(item).strip().casefold() == label.strip().casefold() for item in values if item not in (None, ""))


def _claim_supports_issue(claim: EvidenceClaim, text: str) -> bool:
    if claim.status != "confirmed" or claim.value is None:
        return False
    if claim.claim_type not in {"visible_observation", "path_a_contradiction", "technique_observation", "technical_observation", "issue"}:
        return False
    haystack = " ".join((*_flatten_claim_text(claim.value), *_flatten_claim_text(claim.alternatives))).casefold()
    needle = text.casefold()
    if not haystack or not needle:
        return False
    return needle in haystack or any(token and token in haystack for token in needle.split() if len(token) >= 3)


# A report may describe exact timing/rotation only when the value is present
# in a confirmed, source-linked claim.  Path A is intentionally absent here:
# its visual review can support broad stages/observations, but it is never a
# timing or measurement authority.
_TIMING_CLAIM_TYPES = frozenset({"key_moment", "moment", "timestamp"})
_ROTATION_CLAIM_TYPES = frozenset({
    "rotation",
    "rotation_turns",
    "rotation_estimate",
    "metric_estimated_rotations",
    "airborne_body_rotation_turns_v1",
    "observed_spin_rotation_turns_v1",
})
_EXACT_VALUE_SOURCES = frozenset({
    "deterministic",
    "deterministic_measurement",
    "key_moment",
    "rotation_estimator",
})


def _number(value: Any) -> float | None:
    """Return a finite report-comparable number, or ``None``."""

    if isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _confirmed_exact_claim(claim: EvidenceClaim, *, claim_types: frozenset[str]) -> bool:
    return bool(
        claim.status == "confirmed"
        and claim.observability == "observed"
        and not claim.conflicts
        and claim.claim_type in claim_types
        and _EXACT_VALUE_SOURCES.intersection(claim.sources)
    )


def _claim_exact_numbers(claim: EvidenceClaim, *, kind: str) -> tuple[float, ...]:
    """Extract only values that the claim explicitly labels as exact.

    Do not flatten arbitrary nested numbers: a technical claim can contain
    confidence, frame IDs, ranges, or diagnostics alongside its authoritative
    value.  Restrict extraction to the field names owned by each contract.
    """

    claim_types = _TIMING_CLAIM_TYPES if kind == "timestamp" else _ROTATION_CLAIM_TYPES
    if not _confirmed_exact_claim(claim, claim_types=claim_types):
        return ()
    value = claim.value
    candidates: list[Any] = []
    if isinstance(value, Mapping):
        if kind == "timestamp":
            candidates.extend(value.get(key) for key in ("pts_sec", "source_pts", "timestamp", "timestamp_sec"))
        else:
            candidates.extend(value.get(key) for key in ("turns", "value_turns", "rotation_turns", "estimate_turns", "class_turns", "value"))
    else:
        candidates.append(value)
    output: list[float] = []
    for candidate in candidates:
        numeric = _number(candidate)
        if numeric is not None and numeric not in output:
            output.append(numeric)
    return tuple(output)


def _exact_report_value_supported(report_value: Any, claims: Sequence[EvidenceClaim], *, kind: str) -> bool:
    reported = _number(report_value)
    if reported is None:
        return False
    return any(
        math.isclose(reported, candidate, rel_tol=1e-6, abs_tol=1e-3)
        for claim in claims
        for candidate in _claim_exact_numbers(claim, kind=kind)
    )


def _claim_issue_text_supported(issue: Mapping[str, Any], claims: Sequence[EvidenceClaim]) -> bool:
    text = " ".join(str(issue.get(key, "")) for key in ("category", "description", "target", "action")).strip()
    return any(_claim_supports_issue(claim, text) for claim in claims)


def unsupported_report_claims(report: Mapping[str, Any] | None, claims: Iterable[EvidenceClaim]) -> tuple[str, ...]:
    """Return report statements that cannot be traced to fused claims.

    The check is deliberately conservative: structured fields are validated
    exactly, while prose is checked against source text and claim values.  A
    caller should reject/strip the returned fields before exposing a report.
    """

    raw = report if isinstance(report, Mapping) else {}
    claims_tuple = tuple(claims)
    by_type: dict[str, list[EvidenceClaim]] = {}
    for claim in claims_tuple:
        by_type.setdefault(claim.claim_type, []).append(claim)
    unsupported: list[str] = []
    action = raw.get("action_confirmation")
    if isinstance(action, Mapping):
        family = action.get("action_family") or action.get("confirmed_action")
        family_supported = bool(family) and any(
            _claim_supports_action(claim, str(family))
            for group in by_type.values() for claim in group
        )
        label = action.get("confirmed_action") or action.get("jump_type")
        # A concrete label must have its own explicit claim.  Family support
        # (for example ``jump``) cannot authorize an invented subtype
        # (for example ``Toe Loop``).
        if not label:
            label_supported = True
        elif family and str(label).strip().casefold() == str(family).strip().casefold():
            label_supported = True
        else:
            label_supported = any(_claim_supports_action_label(claim, str(label)) for claim in claims_tuple)
        if not family_supported:
            unsupported.append("invented_action")
        elif not label_supported:
            unsupported.append("invented_action")
    for field, marker, kind in (
        ("timestamp", "invented_timestamp", "timestamp"),
        ("turns", "invented_rotation", "rotation"),
    ):
        if raw.get(field) is None:
            continue
        if not _exact_report_value_supported(raw.get(field), claims_tuple, kind=kind):
            unsupported.append(marker)
    issues = raw.get("issues")
    if isinstance(issues, Sequence) and not isinstance(issues, (str, bytes, bytearray)):
        for issue in issues:
            if not isinstance(issue, Mapping):
                continue
            text = " ".join(str(issue.get(key, "")) for key in ("category", "description", "target", "action")).strip()
            if not text:
                continue
            supported = any(_claim_supports_issue(claim, text) for claim in claims_tuple)
            if not supported:
                unsupported.append("invented_technique_defect")
    return tuple(dict.fromkeys(unsupported))


def constrain_report_payload(report: Mapping[str, Any] | None, claims: Iterable[EvidenceClaim]) -> dict[str, Any]:
    """Return a report payload with unsupported technical fields removed."""

    raw = dict(report or {})
    claims_tuple = tuple(claims)
    unsupported = unsupported_report_claims(raw, claims_tuple)
    if "invented_action" in unsupported:
        action = raw.get("action_confirmation")
        if isinstance(action, Mapping):
            family = action.get("action_family")
            family_supported = bool(family) and any(_claim_supports_action(claim, str(family)) for claim in claims_tuple)
            if family_supported:
                safe_action = dict(action)
                safe_action.pop("confirmed_action", None)
                safe_action.pop("jump_type", None)
                safe_action["notes"] = "具体动作未由已融合证据确认"
                raw["action_confirmation"] = safe_action
            else:
                raw.pop("action_confirmation", None)
    if "invented_timestamp" in unsupported:
        raw.pop("timestamp", None)
    if "invented_rotation" in unsupported:
        raw.pop("turns", None)
    if "invented_technique_defect" in unsupported:
        raw["issues"] = [
            issue for issue in raw.get("issues", ())
            if isinstance(issue, Mapping) and _claim_issue_text_supported(issue, claims_tuple)
        ] if isinstance(raw.get("issues"), Sequence) and not isinstance(raw.get("issues"), (str, bytes, bytearray)) else []
    raw["evidence_claims"] = build_report_evidence(claims_tuple)
    raw["unsupported_claims"] = list(unsupported)
    raw["report_source_fact_hash"] = raw["evidence_claims"]["source_fact_hash"]
    return raw


def build_claim_explainer_prompt(
    claims: Iterable[EvidenceClaim],
    *,
    action_family: str | None = None,
    user_question: str | None = None,
) -> str:
    evidence = build_report_evidence(claims)
    return json.dumps({
        "task": "explain_fused_evidence_only",
        "action_family": action_family,
        "user_question": user_question,
        "fused_evidence": evidence,
        "rules": [
            "Every technical sentence must be traceable to one or more claim_keys.",
            "Do not create action, exact source time, turn count, or technique defect absent from claims.",
            "Preserve uncertain/conflict/unobservable wording and alternatives.",
            "When no supported claim exists, say unavailable and provide one review action.",
        ],
    }, ensure_ascii=False, sort_keys=True, indent=2)


__all__ = ["build_report_evidence", "unsupported_report_claims", "constrain_report_payload", "build_claim_explainer_prompt"]
