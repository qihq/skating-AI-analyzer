from __future__ import annotations

"""Small-data, profile-specific action classification for the V2 shadow path.

The proposal generator owns only temporal localization.  This module owns the
separate family decision and deliberately keeps every family classifier
isolated: each has its own feature weights, configuration fingerprint and
contribution set.  It is an interpretable diagnostic classifier, not a trained
large model and not an identity/localization authority.
"""

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import Field

from app.analysis_v2.contracts import ContractModel
from app.analysis_v2.event_proposals import EventProposal, ProposalEvidenceSample, PROFILE_KEYS


Profile = Literal["jump", "spin", "step", "spiral"]
ClassificationState = Literal["confirmed", "ambiguous", "unknown"]
_SUBTYPE_REPORTING_MINIMUM = 4


def _hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ProfileClassifierConfig:
    profile: Profile
    definition_version: str
    feature_weights: tuple[tuple[str, float], ...]
    confirmation_threshold: float = 0.50
    margin_threshold: float = 0.12
    minimum_evidence: int = 2
    # Mirrors golden-gate-policy.v2 without making the reusable classifier
    # depend on the private evaluator package or its runtime artifacts.
    subtype_minimum_evidence: int = _SUBTYPE_REPORTING_MINIMUM

    @property
    def fingerprint(self) -> str:
        return _hash({
            "profile": self.profile,
            "definition_version": self.definition_version,
            "feature_weights": self.feature_weights,
            "confirmation_threshold": self.confirmation_threshold,
            "margin_threshold": self.margin_threshold,
            "minimum_evidence": self.minimum_evidence,
            "subtype_minimum_evidence": self.subtype_minimum_evidence,
        })


DEFAULT_CONFIGS: dict[Profile, ProfileClassifierConfig] = {
    "jump": ProfileClassifierConfig(
        "jump", "profile-jump-temporal.v1",
        (("airborne_proxy", .28), ("vertical_excursion", .20), ("ice_contact_proxy", .18), ("pose_dynamics", .16), ("motion", .10), ("semantic", .08)),
    ),
    "spin": ProfileClassifierConfig(
        "spin", "profile-spin-temporal.v1",
        (("periodicity", .30), ("turning_motion", .23), ("pose_dynamics", .15), ("motion", .12), ("axis_stability", .12), ("semantic", .08)),
    ),
    "step": ProfileClassifierConfig(
        "step", "profile-step-temporal.v1",
        (("contact_pattern", .27), ("horizontal_motion", .22), ("periodicity", .16), ("pose_dynamics", .13), ("motion", .12), ("semantic", .10)),
    ),
    "spiral": ProfileClassifierConfig(
        "spiral", "profile-spiral-temporal.v2",
        (("extension_proxy", .30), ("axis_stability", .18), ("pose_dynamics", .16), ("horizontal_motion", .14), ("motion", .10), ("semantic", .12)),
        confirmation_threshold=.28,
    ),
}


class ProfileClassifier(Protocol):
    profile: Profile
    config: ProfileClassifierConfig

    def classify(self, evidence: "ActionClassificationEvidence") -> "ProfileContribution": ...


class ActionClassificationEvidence(ContractModel):
    schema_version: Literal["action-classification-evidence.v1"] = "action-classification-evidence.v1"
    source_video_hash: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    samples: tuple[ProposalEvidenceSample, ...] = ()
    temporal_features: dict[str, float] = Field(default_factory=dict)
    path_a_support: dict[str, float] = Field(default_factory=dict)
    path_b_support: dict[str, float] = Field(default_factory=dict)
    path_a_contradictions: dict[str, float] = Field(default_factory=dict)
    path_b_contradictions: dict[str, float] = Field(default_factory=dict)
    tracking_coverage: float = Field(default=0, ge=0, le=1)
    pose_coverage: float = Field(default=0, ge=0, le=1)
    observability: Literal["observable", "partially_observable", "unobservable"] = "unobservable"
    evidence_sources: tuple[str, ...] = ()
    identity_confirmed: bool = False
    subtype_candidates: dict[Profile, tuple[tuple[str, float], ...]] = Field(default_factory=dict)
    subtype_validation_n: dict[Profile, dict[str, int]] = Field(default_factory=dict)

    @property
    def evidence_count(self) -> int:
        return len(self.samples) + sum(1 for value in self.temporal_features.values() if value > 0)

    @property
    def semantic_conflict(self) -> bool:
        for profile in PROFILE_KEYS:
            if self.path_a_support.get(profile, 0) > .2 and self.path_a_contradictions.get(profile, 0) > .2:
                return True
            if self.path_b_support.get(profile, 0) > .2 and self.path_b_contradictions.get(profile, 0) > .2:
                return True
        return False


class Contribution(ContractModel):
    schema_version: Literal["classifier-contribution.v1"] = "classifier-contribution.v1"
    feature: str
    value: float = Field(ge=-1, le=1)
    weight: float = Field(ge=0, le=1)
    contribution: float = Field(ge=-1, le=1)
    source: Literal["temporal", "path_a_bounded", "path_b_semantic", "missing", "contradiction"]


class SubtypeResult(ContractModel):
    schema_version: Literal["classifier-subtype.v1"] = "classifier-subtype.v1"
    subtype: str | None = None
    state: ClassificationState = "unknown"
    confidence: float = Field(ge=0, le=1)
    underpowered: bool = True
    reason: str = "subtype evidence is underpowered"


class ProfileContribution(ContractModel):
    schema_version: Literal["profile-contribution.v1"] = "profile-contribution.v1"
    profile: Profile
    score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    contributions: tuple[Contribution, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    contradiction_evidence: tuple[str, ...] = ()
    config_fingerprint: str
    classifier_fingerprint: str


class ProfileClassification(ContractModel):
    schema_version: Literal["profile-classification.v1"] = "profile-classification.v1"
    event_id: str
    profile: Profile | Literal["unknown"]
    state: ClassificationState
    confidence: float = Field(ge=0, le=1)
    margin: float = Field(ge=0, le=1)
    subtype: SubtypeResult = Field(default_factory=SubtypeResult)
    contributions: tuple[ProfileContribution, ...] = ()
    evidence_summary: dict[str, Any] = Field(default_factory=dict)
    confirmation_task: str | None = None
    definition_version: str = "profile-classification.v1"
    classifier_fingerprint: str


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _temporal_features(evidence: ActionClassificationEvidence) -> dict[str, float]:
    samples = evidence.samples
    motion = [_clamp(item.camera_compensated_track_motion * item.camera_reliability) for item in samples]
    pose = [_clamp(item.pose_dynamics) for item in samples]
    contact = [_clamp(item.ice_contact_proxy) for item in samples]
    periodic = [_clamp(item.periodicity) for item in samples]
    supplied = {key: _clamp(value) for key, value in evidence.temporal_features.items()}
    # The supplied fields are documented temporal summaries from the V2 evidence
    # pipeline; they augment, but never replace, source observations.
    supplied.setdefault("motion", _mean(motion))
    supplied.setdefault("pose_dynamics", _mean(pose))
    supplied.setdefault("ice_contact_proxy", _mean(contact))
    supplied.setdefault("periodicity", _mean(periodic))
    supplied.setdefault("horizontal_motion", _clamp(supplied.get("motion", 0) * (1 - supplied.get("vertical_excursion", 0))))
    supplied.setdefault("vertical_excursion", _clamp(supplied.get("airborne_proxy", 0)))
    supplied.setdefault("airborne_proxy", _clamp(max(supplied.get("vertical_excursion", 0), supplied.get("ice_contact_proxy", 0) * .15)))
    supplied.setdefault("turning_motion", _clamp(supplied.get("periodicity", 0) * .9))
    supplied.setdefault("contact_pattern", _clamp(supplied.get("ice_contact_proxy", 0) * .9 + supplied.get("periodicity", 0) * .1))
    supplied.setdefault("extension_proxy", _clamp(supplied.get("pose_dynamics", 0) * .7 + supplied.get("horizontal_motion", 0) * .1))
    supplied.setdefault("axis_stability", _clamp(1 - supplied.get("turning_motion", 0) * .35))
    # Keep generic body-motion from becoming a free spin vote.  Rotation needs
    # a periodic/turning cue; otherwise the family remains rejectable.
    supplied["axis_stability"] = _clamp(supplied["axis_stability"] * (0.55 + 0.45 * supplied.get("periodicity", 0)))
    return supplied


def _semantic_values(evidence: ActionClassificationEvidence, profile: Profile) -> tuple[float, float, float]:
    a = _clamp(evidence.path_a_support.get(profile, 0))
    b = _clamp(evidence.path_b_support.get(profile, 0))
    contradiction = _clamp(max(evidence.path_a_contradictions.get(profile, 0), evidence.path_b_contradictions.get(profile, 0)))
    # Path A is a bounded semantic cue only.  It cannot localize an interval,
    # select identity or outweigh temporal evidence.
    bounded_a = min(a, .18)
    bounded_contradiction = min(contradiction, .18)
    return bounded_a, min(b, .35), bounded_contradiction


@dataclass(frozen=True)
class _ConfiguredClassifier:
    profile: Profile
    config: ProfileClassifierConfig

    def classify(self, evidence: ActionClassificationEvidence) -> ProfileContribution:
        temporal = _temporal_features(evidence)
        contributions: list[Contribution] = []
        missing: list[str] = []
        contradictions: list[str] = []
        total = 0.0
        for feature, weight in self.config.feature_weights:
            value = temporal.get(feature, 0.0)
            if feature == "semantic":
                a, b, contradiction = _semantic_values(evidence, self.profile)
                value = min(1.0, a + b)
                if value == 0:
                    missing.append(f"semantic:{self.profile}")
                if contradiction > 0:
                    contradictions.append(f"semantic:{self.profile}")
                if a:
                    contributions.append(Contribution(feature=feature, value=a, weight=weight, contribution=a * weight, source="path_a_bounded"))
                if b:
                    contributions.append(Contribution(feature=feature, value=b, weight=weight, contribution=b * weight, source="path_b_semantic"))
                if contradiction:
                    contributions.append(Contribution(feature="semantic_contradiction", value=-contradiction, weight=weight, contribution=-contradiction * weight, source="contradiction"))
                total += (a + b) * weight - contradiction * weight
                continue
            if value <= 0:
                missing.append(feature)
            contribution = value * weight
            if self.profile == "spin" and feature in {"pose_dynamics", "axis_stability"} and temporal.get("periodicity", 0) < .18:
                contribution *= .25
            if self.profile == "step" and feature == "contact_pattern" and temporal.get("horizontal_motion", 0) < .12:
                contribution *= .55
            if self.profile == "spiral" and feature != "extension_proxy" and temporal.get("extension_proxy", 0) < .42:
                contribution *= .18
            if self.profile == "jump" and feature not in {"airborne_proxy", "ice_contact_proxy"} and temporal.get("airborne_proxy", 0) < .55:
                contribution *= .20
            if self.profile == "step" and feature not in {"pose_dynamics", "motion", "semantic"} and temporal.get("step_complexity", 0) < .30:
                contribution *= .35
            contributions.append(Contribution(feature=feature, value=value, weight=weight, contribution=contribution, source="temporal"))
            total += contribution
        coverage = min(1.0, evidence.tracking_coverage)
        coverage *= 0.55 + 0.45 * evidence.pose_coverage if evidence.pose_coverage > 0 else 0.55
        if evidence.observability == "unobservable":
            coverage = 0
        confidence = _clamp((.55 * coverage) + (.45 * min(1.0, evidence.evidence_count / 12)))
        if evidence.semantic_conflict:
            confidence *= .72
        score = _clamp(total * (0.65 + .35 * coverage))
        classifier_fp = _hash({"profile": self.profile, "config": self.config.fingerprint, "contract": "profile-classifier.v1"})
        return ProfileContribution(
            profile=self.profile,
            score=score,
            confidence=_clamp(confidence),
            contributions=tuple(contributions),
            missing_evidence=tuple(sorted(set(missing))),
            contradiction_evidence=tuple(sorted(set(contradictions))),
            config_fingerprint=self.config.fingerprint,
            classifier_fingerprint=classifier_fp,
        )


def classifiers(configs: Mapping[Profile, ProfileClassifierConfig] | None = None) -> dict[Profile, ProfileClassifier]:
    selected = dict(configs or DEFAULT_CONFIGS)
    return {profile: _ConfiguredClassifier(profile, selected[profile]) for profile in PROFILE_KEYS}


def _subtype(
    evidence: ActionClassificationEvidence,
    profile: Profile,
    confidence: float,
    config: ProfileClassifierConfig,
) -> SubtypeResult:
    candidates = [(name, _clamp(value)) for name, value in evidence.subtype_candidates.get(profile, ()) if value > 0]
    if not candidates:
        return SubtypeResult(confidence=_clamp(confidence * .5), underpowered=True, reason="specialty subtype sample size is underpowered; manual confirmation required")
    name, score = max(candidates, key=lambda item: item[1])
    validation_n = max(0, int(evidence.subtype_validation_n.get(profile, {}).get(name, 0)))
    if validation_n < config.subtype_minimum_evidence:
        return SubtypeResult(
            confidence=_clamp(confidence * .5),
            underpowered=True,
            reason=f"specialty subtype validation N={validation_n} is below required N={config.subtype_minimum_evidence}; manual confirmation required",
        )
    return SubtypeResult(subtype=name, state="confirmed" if score >= .8 else "ambiguous", confidence=score, underpowered=False, reason="validation-calibrated subtype evidence")


def classify_action(evidence: ActionClassificationEvidence, *, configs: Mapping[Profile, ProfileClassifierConfig] | None = None) -> ProfileClassification:
    selected_configs = dict(configs or DEFAULT_CONFIGS)
    results = tuple(classifiers(selected_configs)[profile].classify(evidence) for profile in PROFILE_KEYS)
    ranked = sorted(results, key=lambda item: (item.score, item.confidence), reverse=True)
    best = ranked[0]
    second = ranked[1]
    margin = _clamp(best.score - second.score)
    coverage = min(1.0, evidence.tracking_coverage)
    coverage *= 0.55 + 0.45 * evidence.pose_coverage if evidence.pose_coverage > 0 else 0.55
    missing = bool(best.missing_evidence) and evidence.evidence_count < selected_configs[best.profile].minimum_evidence
    localization_is_broad = "sparse_observability_envelope" in evidence.evidence_sources
    if evidence.observability == "unobservable" or coverage <= 0 or missing:
        state: ClassificationState = "unknown"
        profile: Profile | Literal["unknown"] = "unknown"
        confidence = 0.0
        task = f"{evidence.event_id}:confirm_action_profile"
    elif localization_is_broad or evidence.semantic_conflict or margin < selected_configs[best.profile].margin_threshold:
        state = "ambiguous"
        profile = best.profile
        confidence = min(.49, _clamp(best.confidence * .7)) if localization_is_broad else _clamp(best.confidence * .7)
        task = f"{evidence.event_id}:resolve_action_profile_conflict"
    elif best.score >= selected_configs[best.profile].confirmation_threshold and best.confidence >= .5 and (best.profile != "spin" or _temporal_features(evidence).get("periodicity", 0) >= .18):
        state = "confirmed"
        profile = best.profile
        confidence = _clamp(best.confidence)
        task = None
    else:
        state = "ambiguous"
        profile = best.profile
        confidence = _clamp(best.confidence * .65)
        task = f"{evidence.event_id}:confirm_action_profile"
    fp = _hash({"classifier_fingerprints": [item.classifier_fingerprint for item in results], "definition": "profile-classification.v1"})
    return ProfileClassification(
        event_id=evidence.event_id,
        profile=profile,
        state=state,
        confidence=confidence,
        margin=margin,
        subtype=_subtype(evidence, best.profile, confidence, selected_configs[best.profile]) if profile != "unknown" else SubtypeResult(confidence=0, reason="broad profile is unknown"),
        contributions=results,
        evidence_summary={
            "tracking_coverage": evidence.tracking_coverage,
            "pose_coverage": evidence.pose_coverage,
            "observability": evidence.observability,
            "semantic_conflict": evidence.semantic_conflict,
            "localization_is_broad": localization_is_broad,
            "missing": list(best.missing_evidence),
            "contradictions": list(best.contradiction_evidence),
            "evidence_sources": list(evidence.evidence_sources),
        },
        confirmation_task=task,
        classifier_fingerprint=fp,
    )


def _semantic_scores(raw: Mapping[str, Any], path: str) -> tuple[dict[str, float], dict[str, float]]:
    payload = raw.get(path)
    if not isinstance(payload, Mapping):
        return {}, {}
    text_parts: list[str] = []
    for key in ("overall_raw_text", "top_issues", "top_positives", "action_phase_summary", "frame_analysis"):
        value = payload.get(key)
        text_parts.append(json.dumps(value, ensure_ascii=False))
    text = " ".join(text_parts)
    markers: dict[Profile, tuple[str, ...]] = {
        "jump": ("起跳", "腾空", "落冰", "跳跃", "华尔兹", "waltz", "salchow", "toe loop", "axel"),
        "spin": ("旋转入", "旋转中", "旋转出", "旋转", "转体", "spin"),
        "step": ("步法", "滑行", "蹬冰", "方向转换", "step"),
        "spiral": ("燕式", "螺旋线", "spiral", "单足延展", "阿拉贝斯克", "后腿抬高"),
    }
    support = {profile: min(.35, sum(text.lower().count(marker.lower()) for marker in words) / 12) for profile, words in markers.items()}
    contradiction = {profile: 0.0 for profile in PROFILE_KEYS}
    return support, contradiction


def classification_evidence_from_analysis(
    source_video_hash: str,
    event_id: str,
    analysis: Mapping[str, Any],
    samples: Sequence[ProposalEvidenceSample],
    *,
    tracking_coverage: float,
    pose_coverage: float,
    observability: Literal["observable", "partially_observable", "unobservable"],
    subtype_candidates: Mapping[Profile, Sequence[tuple[str, float]]] | None = None,
    subtype_validation_n: Mapping[Profile, Mapping[str, int]] | None = None,
) -> ActionClassificationEvidence:
    path_a, _ = _semantic_scores(analysis, "vision_path_a")
    path_b, _ = _semantic_scores(analysis, "vision_path_b")
    cross = analysis.get("cross_validation") if isinstance(analysis.get("cross_validation"), Mapping) else {}
    raw_conflicts = cross.get("conflict_fields") if isinstance(cross, Mapping) else None
    conflicts = raw_conflicts if isinstance(raw_conflicts, Sequence) and not isinstance(raw_conflicts, (str, bytes)) else ()
    contradiction = {profile: .25 if "detected_phases" in conflicts else 0.0 for profile in PROFILE_KEYS}
    return ActionClassificationEvidence(
        source_video_hash=source_video_hash,
        event_id=event_id,
        samples=tuple(samples),
        path_a_support=path_a,
        path_b_support=path_b,
        path_a_contradictions=contradiction,
        path_b_contradictions=contradiction,
        tracking_coverage=tracking_coverage,
        pose_coverage=pose_coverage,
        observability=observability,
        evidence_sources=("motion", "pose", "path_a_bounded_semantics", "path_b_semantics"),
        identity_confirmed=False,
        subtype_candidates={profile: tuple(values) for profile, values in (subtype_candidates or {}).items()},
        subtype_validation_n={profile: dict(values) for profile, values in (subtype_validation_n or {}).items()},
    )


def classify_proposal(
    proposal: EventProposal,
    *,
    analysis: Mapping[str, Any] | None = None,
    samples: Sequence[ProposalEvidenceSample] = (),
) -> ProfileClassification:
    evidence = ActionClassificationEvidence(
        source_video_hash=proposal.source_video_hash,
        event_id=proposal.event_id,
        samples=tuple(samples),
        path_a_support={},
        path_b_support={},
        tracking_coverage=proposal.tracking_coverage,
        pose_coverage=proposal.pose_coverage,
        observability=proposal.observability,
        evidence_sources=proposal.evidence_sources,
    )
    if analysis is not None:
        evidence = classification_evidence_from_analysis(
            proposal.source_video_hash,
            proposal.event_id,
            analysis,
            samples,
            tracking_coverage=proposal.tracking_coverage,
            pose_coverage=proposal.pose_coverage,
            observability=proposal.observability,
        )
        evidence = evidence.model_copy(update={"evidence_sources": tuple(sorted({*evidence.evidence_sources, *proposal.evidence_sources}))})
    return classify_action(evidence)


def classifier_fingerprint(profile: Profile, config: ProfileClassifierConfig | None = None) -> str:
    selected = config or DEFAULT_CONFIGS[profile]
    if selected.profile != profile:
        raise ValueError("classifier config profile mismatch")
    return _hash({"profile": profile, "config_fingerprint": selected.fingerprint, "contract": "profile-classifier.v1"})
