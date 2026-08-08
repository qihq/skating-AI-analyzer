"""Deterministic claim-by-claim fusion for Iteration 14."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from app.analysis_v2.contracts import EvidenceClaim, IdentityConflictInterval, IdentityTimeline


SourceState = Literal["complete", "failed", "timeout", "not_run"]


@dataclass(frozen=True, slots=True)
class ClaimSourceState:
    source: str
    state: SourceState
    fingerprint: str | None = None
    error: str | None = None
    retryable: bool = False


@dataclass(frozen=True, slots=True)
class FusionResult:
    claims: tuple[EvidenceClaim, ...]
    source_states: tuple[ClaimSourceState, ...]
    fusion_fingerprint: str
    retryable_sources: tuple[str, ...]
    deterministic_evidence_preserved: bool
    conflicts: tuple[str, ...]

    def model_dump(self) -> dict[str, Any]:
        return {
            "schema_version": "claim-fusion-result.v1",
            "claims": [claim.model_dump(mode="json") for claim in self.claims],
            "source_states": [state.__dict__ if hasattr(state, "__dict__") else {
                "source": state.source,
                "state": state.state,
                "fingerprint": state.fingerprint,
                "error": state.error,
                "retryable": state.retryable,
            } for state in self.source_states],
            "fusion_fingerprint": self.fusion_fingerprint,
            "retryable_sources": list(self.retryable_sources),
            "deterministic_evidence_preserved": self.deterministic_evidence_preserved,
            "conflicts": list(self.conflicts),
        }


_SOURCE_RELIABILITY: dict[str, float] = {
    "identity": 1.0,
    "deterministic": 1.0,
    "deterministic_measurement": 1.0,
    "action_classifier": .92,
    "key_moment": .95,
    "rotation_estimator": .95,
    "human_confirmation": 1.0,
    "path_b": .72,
    "path_a": .58,
}

_IDENTITY_INDEPENDENT_CLAIMS = {
    "identity_state",
    "identity_conflict",
    "target_observability",
    "camera_observability",
}

_TECHNICAL_PREFIXES = (
    "pose",
    "joint",
    "rotation",
    "technique",
    "landing",
    "takeoff",
    "axis",
    "arm_",
    "knee_",
    "body_",
    "stage",
    "moment",
)


def _hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)


def _source_weight(claim: EvidenceClaim) -> float:
    weights = [_SOURCE_RELIABILITY.get(source, .5) for source in claim.sources]
    return max(weights or [.5]) * max(0.0, min(1.0, claim.confidence))


def _values_compatible(left: EvidenceClaim, right: EvidenceClaim) -> bool:
    if left.definition_version != right.definition_version:
        return False
    if left.unit != right.unit or left.convention != right.convention:
        return False
    # Missing-vs-present compatibility metadata is not silently compatible:
    # downstream aggregation cannot prove that the two estimates share a
    # definition.  This keeps definition drift visible as a conflict.
    if left.compatibility_group != right.compatibility_group:
        return False
    return True


def _values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isclose(float(left), float(right), rel_tol=1e-6, abs_tol=1e-6)
    return _canonical(left) == _canonical(right)


def _identity_intervals(
    identity: IdentityTimeline | Mapping[str, Any] | Sequence[IdentityConflictInterval | Mapping[str, Any]] | None,
) -> tuple[tuple[float, float], ...]:
    if identity is None:
        return ()
    if isinstance(identity, IdentityTimeline):
        return tuple((item.start_pts_sec, item.end_pts_sec) for item in identity.conflicts)
    raw: Any = identity
    if isinstance(identity, Mapping):
        raw = identity.get("conflicts", ())
    output: list[tuple[float, float]] = []
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        for item in raw:
            if isinstance(item, IdentityConflictInterval):
                output.append((item.start_pts_sec, item.end_pts_sec))
            elif isinstance(item, Mapping):
                try:
                    output.append((float(item.get("start_pts_sec", item.get("start_pts"))), float(item.get("end_pts_sec", item.get("end_pts")))))
                except (TypeError, ValueError):
                    continue
    return tuple(output)


def _claim_interval(claim: EvidenceClaim) -> tuple[float, float] | None:
    value = claim.value
    if isinstance(value, Mapping):
        starts = (value.get("start_pts_sec"), value.get("start_pts"), value.get("pts_sec"), value.get("timestamp"))
        ends = (value.get("end_pts_sec"), value.get("end_pts"), value.get("pts_sec"), value.get("timestamp"))
        start = next((item for item in starts if isinstance(item, (int, float))), None)
        end = next((item for item in ends if isinstance(item, (int, float))), start)
        if start is not None and end is not None:
            return float(start), float(end)
    refs = " ".join(claim.source_references)
    match = re_search_pts(refs)
    return (match, match) if match is not None else None


def re_search_pts(text: str) -> float | None:
    import re

    match = re.search(r"(?:pts|time|timestamp)[:=]([0-9]+(?:\.[0-9]+)?)", text, re.IGNORECASE)
    return float(match.group(1)) if match else None


def _identity_blocks(claim: EvidenceClaim, conflicts: tuple[tuple[float, float], ...]) -> bool:
    if not conflicts or claim.claim_type in _IDENTITY_INDEPENDENT_CLAIMS:
        return False
    is_technical = claim.claim_type.startswith(_TECHNICAL_PREFIXES) or any(
        source in {"path_b", "deterministic_measurement", "rotation_estimator", "key_moment"}
        for source in claim.sources
    )
    if not is_technical:
        return False
    interval = _claim_interval(claim)
    if interval is None:
        # Technical evidence without an interval cannot prove it lies outside a
        # known identity conflict; refuse conservatively.
        return True
    start, end = interval
    return any(not (end < conflict_start or start > conflict_end) for conflict_start, conflict_end in conflicts)


def _blocked_identity_claim(claim: EvidenceClaim) -> EvidenceClaim:
    fingerprints = dict(claim.source_fingerprints)
    fingerprints.setdefault("identity_block", _hash({"claim": claim.claim_type, "references": claim.source_references}))
    return claim.model_copy(update={
        "value": None,
        "sources": tuple(dict.fromkeys((*claim.sources, "identity"))),
        "conflicts": tuple(dict.fromkeys((*claim.conflicts, "identity_conflict"))),
        "alternatives": (),
        "selected_source": None,
        "confidence": 0.0,
        "observability": "unobservable",
        "status": "unobservable",
        "source_fingerprints": fingerprints,
        "refusal_reason": "identity_conflict",
        "review_task": "confirm_main_skater_anchor",
    })


def _merge_fingerprints(claims: Iterable[EvidenceClaim]) -> dict[str, str]:
    output: dict[str, str] = {}
    for claim in claims:
        output.update(claim.source_fingerprints)
        if claim.model_fingerprint:
            output.setdefault("model", claim.model_fingerprint)
        if claim.configuration_fingerprint:
            output.setdefault("configuration", claim.configuration_fingerprint)
        if claim.prompt_fingerprint:
            output.setdefault("prompt", claim.prompt_fingerprint)
    return output


def _merge_refs(claims: Iterable[EvidenceClaim]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(ref for claim in claims for ref in claim.source_references))


def _merge_sources(claims: Iterable[EvidenceClaim]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(source for claim in claims for source in claim.sources))


def _same_value_claim(claims: Sequence[EvidenceClaim]) -> EvidenceClaim:
    ordered = sorted(claims, key=lambda claim: (_source_weight(claim), claim.sources), reverse=True)
    best = ordered[0]
    confidence = min(.99, 1 - math.prod(1 - min(.99, _source_weight(item)) for item in ordered))
    observability = "observed" if all(item.observability == "observed" for item in ordered) else "partial"
    status = "confirmed" if observability == "observed" and confidence >= .6 else "uncertain"
    return best.model_copy(update={
        "sources": _merge_sources(ordered),
        "source_references": _merge_refs(ordered),
        "source_fingerprints": _merge_fingerprints(ordered),
        "conflicts": tuple(dict.fromkeys(conflict for item in ordered for conflict in item.conflicts)),
        "confidence": round(confidence, 6),
        "observability": observability,
        "status": status,
        "selected_source": best.sources[0] if best.sources else None,
    })


def _conflicted_claim(claims: Sequence[EvidenceClaim], *, incompatible: bool) -> EvidenceClaim:
    ordered = sorted(claims, key=lambda claim: (_source_weight(claim), claim.sources), reverse=True)
    best = ordered[0]
    alternatives = tuple({
        "value": item.value,
        "sources": list(item.sources),
        "confidence": item.confidence,
        "definition_version": item.definition_version,
        "unit": item.unit,
        "convention": item.convention,
        "compatibility_group": item.compatibility_group,
    } for item in ordered)
    source_pairs = [f"{','.join(item.sources) or 'unknown'}={_canonical(item.value)}" for item in ordered]
    conflict = "incompatible_estimates_preserved" if incompatible else "claim_value_conflict"
    return best.model_copy(update={
        # Never average incompatible or disagreeing estimates.  The best
        # supported value is retained only as a visible candidate; status stays
        # uncertain and all alternatives remain in the claim.
        "sources": _merge_sources(ordered),
        "source_references": _merge_refs(ordered),
        "source_fingerprints": _merge_fingerprints(ordered),
        "conflicts": tuple(dict.fromkeys((*best.conflicts, conflict, *source_pairs))),
        "alternatives": alternatives,
        "selected_source": best.sources[0] if best.sources else None,
        "confidence": round(min(.49, _source_weight(best)), 6),
        "observability": "partial",
        "status": "uncertain",
        "review_task": best.review_task or f"review_{best.claim_type}_conflict",
    })


def _unobservable_claim(claims: Sequence[EvidenceClaim]) -> EvidenceClaim:
    best = claims[0]
    return best.model_copy(update={
        "value": None,
        "sources": _merge_sources(claims),
        "source_references": _merge_refs(claims),
        "source_fingerprints": _merge_fingerprints(claims),
        "conflicts": tuple(dict.fromkeys(conflict for item in claims for conflict in item.conflicts)),
        "confidence": 0.0,
        "observability": "unobservable",
        "status": "unobservable",
        "refusal_reason": best.refusal_reason or "evidence_unobservable",
    })


def _group_key(claim: EvidenceClaim) -> tuple[str | None, str]:
    """Return the semantic claim identity, deliberately excluding definition.

    Definition/version/unit/convention are *evidence compatibility metadata*,
    not identity.  Including them here would put incompatible estimates in
    separate buckets and make the conflict branch unreachable.  They are
    compared after grouping and retained in ``alternatives``/``conflicts``.
    """

    return claim.event_id, claim.claim_type


def fuse_evidence_claims(
    *claim_sets: Iterable[EvidenceClaim],
    identity: IdentityTimeline | Mapping[str, Any] | Sequence[IdentityConflictInterval | Mapping[str, Any]] | None = None,
    source_states: Sequence[ClaimSourceState | Mapping[str, Any]] = (),
    fusion_configuration: Mapping[str, Any] | None = None,
) -> FusionResult:
    """Fuse claims independently while preserving conflicts and retry state."""

    all_claims = [claim for claims in claim_sets for claim in claims]
    identity_conflicts = _identity_intervals(identity)
    grouped: dict[tuple[str | None, str], list[EvidenceClaim]] = defaultdict(list)
    blocked: list[EvidenceClaim] = []
    for claim in all_claims:
        if _identity_blocks(claim, identity_conflicts):
            blocked.append(_blocked_identity_claim(claim))
        else:
            grouped[_group_key(claim)].append(claim)

    fused: list[EvidenceClaim] = []
    fused.extend(blocked)
    for claims in grouped.values():
        observable = [claim for claim in claims if claim.status != "unobservable" and claim.observability != "unobservable" and claim.value is not None]
        if not observable:
            fused.append(_unobservable_claim(claims))
            continue
        incompatible = any(not _values_compatible(observable[0], claim) for claim in observable[1:])
        equal = all(_values_equal(observable[0].value, claim.value) for claim in observable[1:])
        fused.append(_same_value_claim(observable) if equal and not incompatible else _conflicted_claim(observable, incompatible=incompatible))

    normalized_states: list[ClaimSourceState] = []
    for value in source_states:
        if isinstance(value, ClaimSourceState):
            normalized_states.append(value)
            continue
        state = str(value.get("state", "not_run"))
        normalized_states.append(ClaimSourceState(
            source=str(value.get("source", "unknown")),
            state=state if state in {"complete", "failed", "timeout", "not_run"} else "not_run",  # type: ignore[arg-type]
            fingerprint=str(value.get("fingerprint")) if value.get("fingerprint") else None,
            error=str(value.get("error")) if value.get("error") else None,
            retryable=bool(value.get("retryable", state in {"failed", "timeout"})),
        ))
    retryable = tuple(dict.fromkeys(state.source for state in normalized_states if state.retryable and state.state in {"failed", "timeout"}))
    state_fingerprints = {
        state.source: state.fingerprint
        for state in normalized_states
        if state.fingerprint
    }
    conflicts = tuple(dict.fromkeys(conflict for claim in fused for conflict in claim.conflicts))
    payload = {
        "claims": [claim.model_dump(mode="json") for claim in fused],
        "source_states": [(state.source, state.state, state.fingerprint, state.retryable) for state in normalized_states],
        "configuration": dict(fusion_configuration or {}),
        "version": "claim-fusion.v1",
    }
    fp = _hash(payload)
    finalized = tuple(claim.model_copy(update={
        "source_fingerprints": {
            **state_fingerprints_for_claim(claim, state_fingerprints),
            **claim.source_fingerprints,
            "fusion": fp,
        },
    }) for claim in sorted(fused, key=lambda item: (item.event_id or "", item.claim_type, item.definition_version, _canonical(item.value))))
    deterministic_preserved = any(
        source in {"deterministic", "deterministic_measurement", "identity", "action_classifier", "key_moment", "rotation_estimator"}
        for claim in finalized for source in claim.sources
    ) or not finalized
    return FusionResult(finalized, tuple(normalized_states), fp, retryable, deterministic_preserved, conflicts)


def source_state_from_payload(source: str, payload: Mapping[str, Any] | None, *, fingerprint: str | None = None) -> ClaimSourceState:
    if payload is None:
        return ClaimSourceState(source, "not_run", fingerprint=fingerprint)
    raw = payload if isinstance(payload, Mapping) else {}
    error = str(raw.get("error", ""))
    if not error:
        return ClaimSourceState(source, "complete", fingerprint=fingerprint)
    state: SourceState = "timeout" if "timeout" in error.lower() else "failed"
    return ClaimSourceState(source, state, fingerprint=fingerprint, error=error, retryable=True)


def state_fingerprints_for_claim(claim: EvidenceClaim, state_fingerprints: Mapping[str, str]) -> dict[str, str]:
    """Attach source-state fingerprints only for sources supporting a claim."""

    output: dict[str, str] = {}
    for source in claim.sources:
        fingerprint = state_fingerprints.get(source)
        if fingerprint:
            output.setdefault(source, fingerprint)
    return output


__all__ = ["ClaimSourceState", "FusionResult", "fuse_evidence_claims", "source_state_from_payload", "state_fingerprints_for_claim"]
