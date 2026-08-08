"""Bounded semantic-review adapters for Iteration 14.

The legacy vision services still expose their historical payloads for API
compatibility.  This module is the strict V2 boundary: it describes what each
reviewer may receive, validates provenance, and converts model output into
claim-shaped evidence without allowing a language model to become an
identity/timing/measurement authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from app.analysis_v2.contracts import EvidenceClaim


# These are input/authority fields Path A must never receive.  The generated
# prompt is allowed to mention a boundary in a negative instruction (for
# example, "never emit exact rotation"); the checker therefore distinguishes a
# forbidden field from a prohibition that describes the boundary itself.
_FORBIDDEN_A_TERMS = (
    "pose",
    "skeleton",
    "biomechan",
    "joint angle",
    "rotation count",
    "turn count",
    "exact rotation",
    "key moment",
    "timestamp",
    "frame index",
    "frame_id",
    "reid",
)
_FORBIDDEN_A_FIELD_RE = re.compile(
    r"(?<![a-z0-9_])(?:pose|skeleton|biomechan\w*|joint\s+angle|rotation\s+count|turn\s+count|"
    r"exact\s+rotation|key\s+moment|timestamp|frame\s+index|frame_id|reid)(?![a-z0-9_])",
    re.IGNORECASE,
)
_NEGATION_RE = re.compile(
    r"(?:\b(?:never|do\s+not|don't|not|without|exclude|excluding|no)\b|禁止|不得|不要|不能)"
    r"[^.!?\n]{0,48}$",
    re.IGNORECASE,
)

_BLOCKED_PROVENANCE = {
    "interpolated",
    "interpolated-display-only",
    "uncertain",
    "missing",
    "identity-blocked",
    "lost",
    "clipped",
}
_SUPPORTED_PROVENANCE = {"measured", "smoothed"}


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class TargetClipPolicy:
    """Evidence policy for the target-focused Path A clip."""

    identity_state: str = "unknown"
    target_id: str | None = None
    crop_bbox: tuple[float, float, float, float] | None = None
    context_before_sec: float = 0.0
    context_after_sec: float = 0.0
    includes_travel_context: bool = False
    includes_ice_contact_context: bool = False
    target_marking: str = "none"
    crop_policy_version: str = "target-clip-policy.v2"

    @property
    def confirmed(self) -> bool:
        return self.identity_state == "confirmed"

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.__dict__ if hasattr(self, "__dict__") else {
            "identity_state": self.identity_state,
            "target_id": self.target_id,
            "crop_bbox": self.crop_bbox,
            "context_before_sec": self.context_before_sec,
            "context_after_sec": self.context_after_sec,
            "includes_travel_context": self.includes_travel_context,
            "includes_ice_contact_context": self.includes_ice_contact_context,
            "target_marking": self.target_marking,
            "crop_policy_version": self.crop_policy_version,
        })

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not self.confirmed:
            errors.append("identity_not_confirmed")
        if self.crop_bbox is None:
            errors.append("target_crop_missing")
        elif len(self.crop_bbox) != 4 or any(value < 0 or value > 1 for value in self.crop_bbox):
            errors.append("target_crop_invalid")
        if self.context_before_sec <= 0 or self.context_after_sec <= 0:
            errors.append("insufficient_surrounding_context")
        if not self.includes_travel_context:
            errors.append("travel_context_missing")
        if not self.includes_ice_contact_context:
            errors.append("ice_contact_context_missing")
        if self.target_marking in {"none", "unmarked"}:
            errors.append("target_marking_missing")
        return tuple(errors)


def target_clip_policy_from(value: Mapping[str, Any] | TargetClipPolicy | None) -> TargetClipPolicy:
    if isinstance(value, TargetClipPolicy):
        return value
    raw = value if isinstance(value, Mapping) else {}
    bbox = raw.get("crop_bbox", raw.get("bbox"))
    normalized_bbox: tuple[float, float, float, float] | None = None
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        try:
            normalized_bbox = tuple(float(item) for item in bbox)  # type: ignore[assignment]
        except (TypeError, ValueError):
            normalized_bbox = None
    return TargetClipPolicy(
        identity_state=str(raw.get("identity_state", raw.get("state", "unknown"))),
        target_id=str(raw.get("target_id")) if raw.get("target_id") is not None else None,
        crop_bbox=normalized_bbox,
        context_before_sec=float(raw.get("context_before_sec", raw.get("before_sec", 0)) or 0),
        context_after_sec=float(raw.get("context_after_sec", raw.get("after_sec", 0)) or 0),
        includes_travel_context=bool(raw.get("includes_travel_context", raw.get("travel_context", False))),
        includes_ice_contact_context=bool(raw.get("includes_ice_contact_context", raw.get("ice_contact_context", False))),
        target_marking=str(raw.get("target_marking", raw.get("marker", "none"))),
        crop_policy_version=str(raw.get("crop_policy_version", "target-clip-policy.v2")),
    )


def build_path_a_v2_prompt(
    *,
    action_family: str | None = None,
    target_policy: Mapping[str, Any] | TargetClipPolicy | None = None,
    output_language: str = "zh-CN",
) -> tuple[str, str]:
    """Return a leakage-resistant system/user prompt for target review.

    The prompt intentionally contains no pose/biomechanics/timing/rotation
    input fields.  Relative stage wording is allowed; exact source moments are
    explicitly refused.
    """

    policy = target_clip_policy_from(target_policy)
    errors = policy.validate()
    system = (
        "You are a bounded target-clip visual reviewer. "
        "Review only what is visibly present in the marked target clip. "
        "The deterministic pipeline owns person selection, source-time markers, physical measurements, and turn totals. "
        "Do not infer another skater's behavior when the marked target is unclear. "
        "Return JSON only."
    )
    user = {
        "task": "support_or_refuse_action_family_review",
        "action_family_hint": action_family or "unknown",
        "target_clip_policy": {
            "confirmed_target": policy.confirmed,
            "target_marking": policy.target_marking,
            "travel_context": policy.includes_travel_context,
            "ice_contact_context": policy.includes_ice_contact_context,
            "context_before_sec": policy.context_before_sec,
            "context_after_sec": policy.context_after_sec,
            "policy_errors": list(errors),
        },
        "allowed_output": {
            "action_family_support": "jump|spin|step|spiral|unknown",
            "broad_stages": ["preparation", "entry", "main", "exit", "unknown"],
            "visible_observations": ["short observations grounded in the marked target"],
            "contradictions": ["visible reasons not to support the hint"],
            "observability": "observed|partial|unobservable",
            "confidence": "0..1",
        },
        "hard_limits": [
            "never identify or relocalize a person",
            "never emit source frame numbers, exact time markers, exact stage boundaries, turn totals, or computed values",
            "never emit body landmarks, numeric physical fields, or computed technical scores",
            "use unobservable/refusal when blur, occlusion, crop, or multiple skaters prevent safe observation",
        ],
    }
    return system, json.dumps(user, ensure_ascii=False, sort_keys=True, indent=2)


def path_a_prompt_has_leakage(text: str) -> bool:
    """Static prompt-leakage check used by boundary tests."""

    normalized = str(text or "")
    for match in _FORBIDDEN_A_FIELD_RE.finditer(normalized):
        # A forbidden term in a hard-limit/refusal sentence is a safe boundary
        # declaration.  A term used as a JSON key, value, or positive input is
        # leakage.  Keep the look-behind deliberately short so a distant
        # unrelated "not" cannot mask an actual payload field.
        prefix = normalized[max(0, match.start() - 64):match.start()]
        # JSON-like field/value syntax is always input leakage, even if a
        # previous sentence happened to contain a negation.
        immediate = normalized[max(0, match.start() - 4):match.end() + 2]
        if re.search(r"[\"']\s*[:=]|[:=]\s*[\"']?$", immediate):
            return True
        if _NEGATION_RE.search(prefix):
            continue
        return True
    return False


def validate_path_a_prompt(system_prompt: str, user_prompt: str) -> tuple[str, ...]:
    errors: list[str] = []
    joined = f"{system_prompt}\n{user_prompt}"
    if path_a_prompt_has_leakage(joined):
        errors.append("forbidden_technical_or_timing_term")
    for required in ("unobservable", "action_family", "contradictions"):
        if required not in joined:
            errors.append(f"missing_{required}_boundary")
    return tuple(errors)


def _text_list(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return tuple(str(item) for item in value if str(item).strip())
    return ()


def normalize_path_a_review(
    payload: Mapping[str, Any] | None,
    *,
    event_id: str | None = None,
    source_fingerprints: Mapping[str, str] | None = None,
    target_policy: Mapping[str, Any] | TargetClipPolicy | None = None,
) -> tuple[EvidenceClaim, ...]:
    """Convert bounded Path A output into non-authoritative claims."""

    raw = payload if isinstance(payload, Mapping) else {}
    policy = target_clip_policy_from(target_policy)
    fingerprints = {str(key): str(value) for key, value in (source_fingerprints or {}).items() if value}
    if policy.fingerprint:
        fingerprints.setdefault("target_clip_policy", policy.fingerprint)
    blocked = bool(policy.validate())
    observability = str(raw.get("observability", "observed"))
    if observability not in {"observed", "partial", "unobservable"}:
        observability = "unobservable"
    error_reason = str(raw.get("error", "")).strip()
    if blocked or error_reason:
        observability = "unobservable"
    confidence = float(raw.get("confidence", raw.get("element_confidence", 0.0)) or 0.0)
    confidence = max(0.0, min(1.0, confidence)) if observability != "unobservable" else 0.0
    claims: list[EvidenceClaim] = []
    family = raw.get("action_family_support", raw.get("action_family"))
    if family is None:
        summary = raw.get("action_phase_summary")
        if isinstance(summary, Mapping):
            family = summary.get("action_family")
    if family is not None or blocked:
        claims.append(EvidenceClaim(
            event_id=event_id,
            claim_type="action_family_support",
            value=None if blocked else str(family),
            sources=("path_a",),
            source_fingerprints=fingerprints,
            confidence=confidence,
            observability=observability,  # type: ignore[arg-type]
            status="unobservable" if observability == "unobservable" else "uncertain" if observability == "partial" else "confirmed",
            refusal_reason=";".join((*policy.validate(), *(tuple((f"provider_error:{error_reason}",) if error_reason else ())))) if (blocked or error_reason) else None,
            review_task="confirm_target_clip" if blocked else None,
            provenance=("target_clip_review", "refused") if (blocked or error_reason) else ("target_clip_review",),
        ))
    stages = raw.get("broad_stages", raw.get("stages"))
    if stages is None and isinstance(raw.get("action_phase_summary"), Mapping):
        stages = raw["action_phase_summary"].get("detected_phases")
    if stages:
        claims.append(EvidenceClaim(event_id=event_id, claim_type="broad_stage_support", value=list(_text_list(stages)), sources=("path_a",), source_fingerprints=fingerprints, confidence=confidence, observability=observability, status="uncertain" if observability != "observed" else "confirmed", provenance=("target_clip_review",)))
    observations = raw.get("visible_observations", raw.get("observations", raw.get("top_positives")))
    for index, text in enumerate(_text_list(observations)):
        claims.append(EvidenceClaim(event_id=event_id, claim_type="visible_observation", value=text, sources=("path_a",), source_references=(f"observation:{index}",), source_fingerprints=fingerprints, confidence=confidence, observability=observability, status="uncertain" if observability != "observed" else "confirmed", provenance=("target_clip_review",)))
    contradictions = raw.get("contradictions", raw.get("top_issues"))
    for index, text in enumerate(_text_list(contradictions)):
        claims.append(EvidenceClaim(event_id=event_id, claim_type="path_a_contradiction", value=text, sources=("path_a",), source_references=(f"contradiction:{index}",), source_fingerprints=fingerprints, confidence=confidence, observability=observability, status="uncertain" if observability != "observed" else "confirmed", provenance=("target_clip_review",)))
    return tuple(claims)


def measurement_provenance(value: Mapping[str, Any] | None) -> str:
    raw = value if isinstance(value, Mapping) else {}
    explicit = str(raw.get("provenance", raw.get("source", "missing"))).strip().lower()
    aliases = {"interpolated_display_only": "interpolated-display-only", "identity_blocked": "identity-blocked"}
    return aliases.get(explicit, explicit or "missing")


def measurement_is_supported(value: Mapping[str, Any] | None) -> bool:
    provenance = measurement_provenance(value)
    return provenance in _SUPPORTED_PROVENANCE and bool(value) and value.get("value") is not None


def _normalize_measurement_records(
    measurements: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Normalize list/dict measurement payloads without losing metric names.

    Legacy callers often pass ``{metric_name: scalar}`` or
    ``{metric_name: {angle: ..., provenance: ...}}``.  Iterating ``dict.values``
    loses the metric name and can even pass primitives to ``dict(item)``.  The
    V2 boundary always emits a record with an explicit ``claim_type`` and a
    source-linked value, while leaving unknown nested structures untouched.
    """

    if isinstance(measurements, Mapping):
        source_items = list(measurements.items())
    else:
        source_items = [(None, item) for item in (measurements or ())]

    records: list[dict[str, Any]] = []
    for key, value in source_items:
        if isinstance(value, Mapping):
            record = dict(value)
            claim_type = record.get("claim_type") or record.get("metric") or key or "measurement"
            record["claim_type"] = str(claim_type)
            # Common deterministic adapters use a field named after the metric
            # (angle/measurement/metric_value) instead of ``value``.
            if "value" not in record:
                for candidate in ("measurement", "metric_value", "angle", "degrees", "score", "value_raw"):
                    if candidate in record and not isinstance(record[candidate], Mapping):
                        record["value"] = record[candidate]
                        break
            records.append(record)
            continue
        if key is None and not isinstance(value, Mapping):
            # A bare scalar in a list has no safe claim name; retain it as an
            # explicitly generic measurement so it can be refused or traced.
            records.append({"claim_type": "measurement", "value": value, "provenance": "missing"})
        else:
            records.append({"claim_type": str(key or "measurement"), "value": value, "provenance": "measured"})
    return records


def build_path_b_v2_prompt(
    *,
    structured_measurements: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
    required_joints: Sequence[str] = (),
    identity_state: str = "unknown",
) -> tuple[str, str]:
    """Prompt for Path B: explain only source-linked deterministic evidence."""

    measurements = _normalize_measurement_records(structured_measurements)
    system = (
        "You are a structured-measurement explainer. "
        "The deterministic pipeline is authoritative for identity, source timing, and measured values. "
        "Explain supported measurements only; do not infer identity from pixels or fill missing joints. "
        "Return JSON only."
    )
    user = {
        "identity_state": identity_state,
        "required_joints": list(required_joints),
        "measurements": measurements,
        "provenance_vocabulary": ["measured", "smoothed", "interpolated", "uncertain", "missing"],
        "hard_limits": [
            "interpolated, uncertain, missing, clipped, or identity-blocked requirements suppress the related technical claim",
            "do not invent a value, exact source moment, rotation, action, or defect",
            "label each explanation with measured/smoothed/interpolated/uncertain/missing provenance",
        ],
        "output": {"supported_observations": [], "suppressed_claims": [], "contradictions": [], "observability": "observed|partial|unobservable"},
    }
    return system, json.dumps(user, ensure_ascii=False, sort_keys=True, indent=2)


def normalize_path_b_measurements(
    measurements: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
    *,
    event_id: str | None = None,
    identity_state: str = "unknown",
    required_joints: Sequence[str] = (),
    source_fingerprints: Mapping[str, str] | None = None,
) -> tuple[EvidenceClaim, ...]:
    """Project deterministic measurements into safe Path B claims."""

    records = _normalize_measurement_records(measurements)
    fingerprints = {str(key): str(value) for key, value in (source_fingerprints or {}).items() if value}
    required = set(str(item) for item in required_joints)
    required_unreliable = identity_state != "confirmed"
    for item in records:
        joint = item.get("joint") or item.get("joint_name") or item.get("required_joint")
        if joint in required and not measurement_is_supported(item):
            required_unreliable = True
    claims: list[EvidenceClaim] = []
    for item in records:
        claim_type = str(item.get("claim_type", item.get("metric", "measurement")))
        provenance = measurement_provenance(item)
        supported = measurement_is_supported(item) and identity_state == "confirmed"
        item_joint = item.get("joint") or item.get("joint_name") or item.get("required_joint")
        if required_unreliable and (item_joint in required or item.get("required") is True):
            supported = False
        obs = "observed" if supported and provenance == "measured" else "partial" if supported else "unobservable"
        status = "confirmed" if supported else "unobservable"
        value = item.get("value") if supported else None
        claims.append(EvidenceClaim(
            event_id=event_id,
            claim_type=claim_type,
            value=value,
            sources=("path_b", "deterministic_measurement"),
            source_references=tuple(str(item.get(key)) for key in ("source_reference", "frame_reference", "moment_reference") if item.get(key)),
            source_fingerprints=fingerprints,
            provenance=(provenance,),
            confidence=max(0.0, min(1.0, float(item.get("confidence", 0.0) or 0.0))) if supported else 0.0,
            observability=obs,  # type: ignore[arg-type]
            status=status,  # type: ignore[arg-type]
            refusal_reason=None if supported else ("identity_not_confirmed" if identity_state != "confirmed" else f"unsupported_provenance:{provenance}"),
            review_task="confirm_required_measurement" if not supported else None,
        ))
    if not records and required_unreliable:
        claims.append(EvidenceClaim(event_id=event_id, claim_type="technical_measurement", value=None, sources=("path_b",), source_fingerprints=fingerprints, confidence=0, observability="unobservable", status="unobservable", provenance=("missing",), refusal_reason="missing_required_measurement", review_task="provide_source_linked_measurement"))
    return tuple(claims)


__all__ = [
    "TargetClipPolicy",
    "target_clip_policy_from",
    "build_path_a_v2_prompt",
    "path_a_prompt_has_leakage",
    "validate_path_a_prompt",
    "normalize_path_a_review",
    "measurement_provenance",
    "measurement_is_supported",
    "build_path_b_v2_prompt",
    "normalize_path_b_measurements",
    "_normalize_measurement_records",
]
