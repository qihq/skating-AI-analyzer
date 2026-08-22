from __future__ import annotations

"""Profile-specific source-time moment localization for Iteration 12.

Only exact source-PTS samples from an identity-confirmed target may contribute.
Sparse semantic frames can be retained as review provenance, but they never
score a candidate or define an exact source marker.
"""

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import Field, model_validator

from app.analysis_v2.contracts import ContractModel, EventMomentSet, KeyMoment, MomentCandidate


Profile = Literal["jump", "spin", "step", "spiral"]
MomentKind = Literal["point", "interval", "representative"]


@dataclass(frozen=True)
class MomentDefinition:
    profile: Profile
    semantic_key: str
    kind: MomentKind
    definition_version: str
    operational_definition: str
    required_evidence: tuple[str, ...]
    order: int
    required_for_complete: bool = True


PROFILE_DEFINITIONS: dict[Profile, tuple[MomentDefinition, ...]] = {
    "jump": (
        MomentDefinition("jump", "takeoff", "point", "jump-tal.source-contact.v1", "First original source frame whose confirmed target evidence begins sustained airborne support after a confirmed ice-contact frame.", ("ice_contact", "airborne"), 0),
        MomentDefinition("jump", "apex", "point", "jump-tal.source-contact.v1", "Original source frame between takeoff and landing with the highest confirmed body centre (minimum image-space body_center_y).", ("body_center_y", "airborne"), 1),
        MomentDefinition("jump", "landing", "point", "jump-tal.source-contact.v1", "First original source frame after sustained airborne support where confirmed ice contact returns; absent or visually ambiguous contact is unavailable.", ("ice_contact", "airborne"), 2),
    ),
    "spin": (
        MomentDefinition("spin", "spin_entry", "interval", "spin-phases.periodic-axis.v1", "Confirmed turning preparation immediately before sustained periodic rotation.", ("turning_motion", "rotation_periodicity"), 0),
        MomentDefinition("spin", "spin_main", "interval", "spin-phases.periodic-axis.v1", "Longest confirmed interval of sustained periodic turning with a stable axis.", ("turning_motion", "rotation_periodicity", "axis_stability"), 1),
        MomentDefinition("spin", "spin_exit", "interval", "spin-phases.periodic-axis.v1", "Confirmed deceleration/release interval after main rotation until periodic turning ends.", ("turning_motion", "rotation_periodicity"), 2),
    ),
    "spiral": (
        MomentDefinition("spiral", "spiral_entry", "interval", "spiral-phases.extension-hold.v1", "Confirmed extension build-up immediately before the sustained hold.", ("extension",), 0),
        MomentDefinition("spiral", "spiral_hold", "interval", "spiral-phases.extension-hold.v1", "Longest confirmed interval of sustained extension and body-axis stability.", ("extension", "axis_stability"), 1),
        MomentDefinition("spiral", "spiral_exit", "interval", "spiral-phases.extension-hold.v1", "Confirmed release interval after the hold until extension returns below the hold threshold.", ("extension",), 2),
    ),
    "step": (
        MomentDefinition("step", "step_sequence_interval", "interval", "step-sequence.edge-complexity.v1", "Longest confirmed interval with sustained edge/step complexity distinct from ordinary travel.", ("step_complexity", "edge_change"), 0),
        MomentDefinition("step", "step_representative_1", "representative", "step-sequence.edge-complexity.v1", "Highest-scoring confirmed edge/step change inside the sequence interval.", ("step_complexity", "edge_change"), 1),
        MomentDefinition("step", "step_representative_2", "representative", "step-sequence.edge-complexity.v1", "Second distinct confirmed edge/step change inside the sequence interval when observable.", ("step_complexity", "edge_change"), 2, False),
        MomentDefinition("step", "step_representative_3", "representative", "step-sequence.edge-complexity.v1", "Third distinct confirmed edge/step change inside the sequence interval when observable.", ("step_complexity", "edge_change"), 3, False),
    ),
}


class MomentEvidenceSample(ContractModel):
    schema_version: Literal["moment-evidence-sample.v1"] = "moment-evidence-sample.v1"
    source_frame_index: int = Field(ge=0)
    pts_sec: float = Field(ge=0)
    frame_status: Literal["available", "duplicate_pts", "gap_after_previous", "discontinuity", "timestamp_unavailable"] = "available"
    gap_before_sec: float = Field(default=0, ge=0)
    timing_provenance: Literal["source_pts", "legacy_approximate"] = "source_pts"
    tracking_state: Literal["confirmed", "uncertain", "lost"] = "confirmed"
    pose_authoritative: bool = True
    pose_quality: float | None = Field(default=None, ge=0, le=1)
    body_center_y: float | None = Field(default=None, ge=0, le=1)
    vertical_velocity: float | None = Field(default=None, ge=-10, le=10)
    ice_contact: float | None = Field(default=None, ge=0, le=1)
    airborne: float | None = Field(default=None, ge=0, le=1)
    turning_motion: float | None = Field(default=None, ge=0, le=1)
    rotation_periodicity: float | None = Field(default=None, ge=0, le=1)
    axis_stability: float | None = Field(default=None, ge=0, le=1)
    extension: float | None = Field(default=None, ge=0, le=1)
    edge_change: float | None = Field(default=None, ge=0, le=1)
    step_complexity: float | None = Field(default=None, ge=0, le=1)
    motion_observable: bool = True
    semantic_review_keys: tuple[str, ...] = ()
    provenance: tuple[str, ...] = ()

    @property
    def exact_confirmed(self) -> bool:
        return self.timing_provenance == "source_pts" and self.frame_status != "timestamp_unavailable" and self.tracking_state == "confirmed"


class CoarseMomentWindow(ContractModel):
    semantic_key: str
    start_pts_sec: float = Field(ge=0)
    end_pts_sec: float = Field(ge=0)

    @model_validator(mode="after")
    def ordered(self) -> "CoarseMomentWindow":
        if self.end_pts_sec < self.start_pts_sec:
            raise ValueError("coarse moment window must be ordered")
        return self


FORBIDDEN_EVALUATION_KEYS = frozenset({
    "golden", "golden_label", "golden_labels", "resolved_semantic_label",
    "resolved_semantic_labels", "resolved_keyframes", "selected_semantic_frames",
    "ground_truth", "ground_truth_moments", "target_moments",
})


def reject_evaluation_leakage(payload: Mapping[str, Any]) -> None:
    def walk(value: Any) -> None:
        if isinstance(value, Mapping):
            forbidden = FORBIDDEN_EVALUATION_KEYS.intersection(str(key).lower() for key in value)
            if forbidden:
                raise ValueError("moment prediction input contains evaluation-only or resolved semantic labels: " + ", ".join(sorted(forbidden)))
            for child in value.values():
                walk(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                walk(child)
    walk(payload)


def definition_catalog() -> dict[str, Any]:
    return {
        profile: [
            {
                "semantic_key": item.semantic_key,
                "kind": item.kind,
                "definition_version": item.definition_version,
                "operational_definition": item.operational_definition,
                "required_evidence": list(item.required_evidence),
                "required_for_complete": item.required_for_complete,
            }
            for item in definitions
        ]
        for profile, definitions in PROFILE_DEFINITIONS.items()
    }


def _fingerprint(value: Any) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def _mean(values: Sequence[float | None]) -> float:
    present = [float(value) for value in values if value is not None]
    return sum(present) / len(present) if present else 0.0


def _candidate(sample: MomentEvidenceSample, score: float, evidence: Sequence[str], *, end: MomentEvidenceSample | None = None, warnings: Sequence[str] = ()) -> MomentCandidate:
    provenance = tuple(dict.fromkeys((*sample.provenance, "source_pts", "confirmed_target")))
    return MomentCandidate(
        source_frame_index=sample.source_frame_index,
        pts_sec=sample.pts_sec,
        end_source_frame_index=end.source_frame_index if end else None,
        end_pts_sec=end.pts_sec if end else None,
        score=max(0.0, min(1.0, score)),
        observability="observed",
        evidence=tuple(evidence),
        provenance=provenance,
        warnings=tuple(warnings),
    )


def _unavailable(event_id: str, definition: MomentDefinition, reason: str) -> KeyMoment:
    return KeyMoment(
        event_id=event_id,
        semantic_key=definition.semantic_key,
        kind=definition.kind,
        status="unavailable",
        definition_version=definition.definition_version,
        confidence=0,
        warnings=(reason,),
        observability="unobservable",
        provenance=("refusal",),
    )


def _from_candidates(event_id: str, definition: MomentDefinition, candidates: Sequence[MomentCandidate], *, ambiguity_margin: float = .08, prefer_earliest: bool = False, competing_horizon_sec: float | None = None) -> KeyMoment:
    ranked = sorted(candidates, key=(lambda item: (item.pts_sec, -item.score, item.source_frame_index)) if prefer_earliest else (lambda item: (-item.score, item.pts_sec, item.source_frame_index)))
    if not ranked:
        return _unavailable(event_id, definition, "required_confirmed_source_evidence_absent")
    winner = ranked[0]
    competition_pool = [item for item in ranked if competing_horizon_sec is None or abs(item.pts_sec - winner.pts_sec) <= competing_horizon_sec]
    competing = tuple(competition_pool[:3])
    ambiguous = len(competition_pool) > 1 and abs(winner.score - competition_pool[1].score) < ambiguity_margin
    warnings = list(winner.warnings)
    if ambiguous:
        warnings.append("competing_candidates_within_margin")
    return KeyMoment(
        event_id=event_id,
        semantic_key=definition.semantic_key,
        kind=definition.kind,
        status="ambiguous" if ambiguous else "confirmed",
        source_frame_index=winner.source_frame_index,
        pts_sec=winner.pts_sec,
        end_source_frame_index=winner.end_source_frame_index,
        end_pts_sec=winner.end_pts_sec,
        definition_version=definition.definition_version,
        candidate_evidence=winner.evidence,
        confidence=winner.score,
        warnings=tuple(dict.fromkeys(warnings)),
        observability="partial" if ambiguous else winner.observability,
        provenance=winner.provenance,
        competing_candidates=competing,
        review_resolvable=ambiguous,
    )


def _runs(samples: Sequence[MomentEvidenceSample], predicate: Any) -> list[list[MomentEvidenceSample]]:
    result: list[list[MomentEvidenceSample]] = []
    active: list[MomentEvidenceSample] = []
    for sample in samples:
        if predicate(sample):
            active.append(sample)
        elif active:
            result.append(active)
            active = []
    if active:
        result.append(active)
    return result


def _jump(event_id: str, samples: Sequence[MomentEvidenceSample]) -> list[KeyMoment]:
    definitions = PROFILE_DEFINITIONS["jump"]
    takeoffs: list[MomentCandidate] = []
    landings: list[MomentCandidate] = []
    for previous, current in zip(samples, samples[1:]):
        if previous.ice_contact is not None and current.airborne is not None and previous.ice_contact >= .55 and current.airborne >= .55:
            score = .5 * current.airborne + .35 * previous.ice_contact + .15 * (current.pose_quality or .5)
            takeoffs.append(_candidate(current, score, ("airborne_transition", "prior_ice_contact")))
        if previous.airborne is not None and current.ice_contact is not None and previous.airborne >= .55 and current.ice_contact >= .55:
            score = .55 * current.ice_contact + .30 * previous.airborne + .15 * (current.pose_quality or .5)
            landings.append(_candidate(current, score, ("ice_contact_return", "prior_airborne")))
    takeoff = _from_candidates(event_id, definitions[0], takeoffs, prefer_earliest=True, competing_horizon_sec=.12)
    landing_candidates = [item for item in landings if takeoff.pts_sec is not None and item.pts_sec > takeoff.pts_sec]
    landing = _from_candidates(event_id, definitions[2], landing_candidates, prefer_earliest=True, competing_horizon_sec=.25)
    apex_candidates: list[MomentCandidate] = []
    if takeoff.pts_sec is not None:
        upper = landing.pts_sec if landing.pts_sec is not None else math.inf
        airborne = [sample for sample in samples if takeoff.pts_sec <= sample.pts_sec <= upper and sample.airborne is not None and sample.airborne >= .45 and sample.body_center_y is not None and sample.pose_authoritative]
        if airborne:
            min_y = min(sample.body_center_y for sample in airborne if sample.body_center_y is not None)
            for sample in airborne:
                height_score = 1 - max(0.0, (sample.body_center_y or min_y) - min_y) * 5
                apex_candidates.append(_candidate(sample, .65 * height_score + .25 * (sample.airborne or 0) + .10 * (sample.pose_quality or .5), ("maximum_body_height", "airborne_support")))
    apex = _from_candidates(event_id, definitions[1], apex_candidates)
    # Enforce order by refusing only the offending stage; never move or invent it.
    if apex.pts_sec is not None and takeoff.pts_sec is not None and apex.pts_sec <= takeoff.pts_sec:
        apex = _unavailable(event_id, definitions[1], "apex_not_strictly_after_takeoff")
    if landing.pts_sec is not None and apex.pts_sec is not None and landing.pts_sec <= apex.pts_sec:
        landing = _unavailable(event_id, definitions[2], "landing_not_strictly_after_apex")
    return [takeoff, apex, landing]


def _phase_triplet(event_id: str, profile: Literal["spin", "spiral"], samples: Sequence[MomentEvidenceSample]) -> list[KeyMoment]:
    definitions = PROFILE_DEFINITIONS[profile]
    if profile == "spin":
        main_runs = _runs(samples, lambda sample: (sample.rotation_periodicity or 0) >= .55 and (sample.turning_motion or 0) >= .45 and (sample.axis_stability or 0) >= .40)
        main_score = lambda run: .45 * _mean([item.rotation_periodicity for item in run]) + .35 * _mean([item.turning_motion for item in run]) + .20 * _mean([item.axis_stability for item in run])
        entry_predicate = lambda sample: (sample.turning_motion or 0) >= .22
        exit_predicate = lambda sample: (sample.turning_motion or 0) >= .18
    else:
        main_runs = _runs(samples, lambda sample: (sample.extension or 0) >= .62 and (sample.axis_stability or 0) >= .50)
        main_score = lambda run: .65 * _mean([item.extension for item in run]) + .35 * _mean([item.axis_stability for item in run])
        entry_predicate = lambda sample: (sample.extension or 0) >= .28
        exit_predicate = lambda sample: (sample.extension or 0) >= .24
    main_candidates = [_candidate(run[0], main_score(run), ("sustained_profile_state",), end=run[-1]) for run in main_runs if len(run) >= 2]
    main = _from_candidates(event_id, definitions[1], main_candidates)
    if main.source_frame_index is None or main.end_source_frame_index is None:
        return [_unavailable(event_id, definitions[0], "main_phase_absent"), main, _unavailable(event_id, definitions[2], "main_phase_absent")]
    main_start = next(index for index, sample in enumerate(samples) if sample.source_frame_index == main.source_frame_index)
    main_end = next(index for index, sample in enumerate(samples) if sample.source_frame_index == main.end_source_frame_index)
    before = list(samples[:main_start])
    after = list(samples[main_end + 1:])
    entry_runs = _runs(before, entry_predicate)
    exit_runs = _runs(after, exit_predicate)
    entry_candidates = [_candidate(run[0], _mean([(item.turning_motion if profile == "spin" else item.extension) for item in run]), ("profile_entry_transition",), end=run[-1]) for run in entry_runs if run and before and run[-1] is before[-1]]
    exit_candidates = [_candidate(run[0], _mean([(item.turning_motion if profile == "spin" else item.extension) for item in run]), ("profile_exit_transition",), end=run[-1]) for run in exit_runs if run and after and run[0] is after[0]]
    return [_from_candidates(event_id, definitions[0], entry_candidates), main, _from_candidates(event_id, definitions[2], exit_candidates)]


def _step(event_id: str, samples: Sequence[MomentEvidenceSample]) -> list[KeyMoment]:
    definitions = PROFILE_DEFINITIONS["step"]
    runs = _runs(samples, lambda sample: (sample.step_complexity or 0) >= .48 or ((sample.edge_change or 0) >= .42 and sample.motion_observable))
    interval_candidates = [
        _candidate(run[0], .6 * _mean([item.step_complexity for item in run]) + .4 * _mean([item.edge_change for item in run]), ("sustained_step_complexity", "edge_change"), end=run[-1])
        for run in runs if len(run) >= 2
    ]
    interval = _from_candidates(event_id, definitions[0], interval_candidates)
    representatives: list[KeyMoment] = []
    if interval.source_frame_index is None or interval.end_source_frame_index is None:
        return [interval, *[_unavailable(event_id, definition, "step_interval_absent") for definition in definitions[1:]]]
    inside = [sample for sample in samples if interval.source_frame_index <= sample.source_frame_index <= interval.end_source_frame_index]
    ranked = sorted(inside, key=lambda sample: (-((sample.step_complexity or 0) * .6 + (sample.edge_change or 0) * .4), sample.pts_sec))
    chosen: list[MomentEvidenceSample] = []
    for sample in ranked:
        if all(abs(sample.pts_sec - prior.pts_sec) >= .12 for prior in chosen):
            chosen.append(sample)
        if len(chosen) == 3:
            break
    chosen.sort(key=lambda sample: sample.pts_sec)
    for index, definition in enumerate(definitions[1:]):
        candidates = []
        if index < len(chosen):
            selected = chosen[index]
            candidates.append(_candidate(selected, .6 * (selected.step_complexity or 0) + .4 * (selected.edge_change or 0), ("representative_step_change",)))
        representatives.append(_from_candidates(event_id, definition, candidates))
    return [interval, *representatives]


def localize_profile_moments(
    *,
    event_id: str,
    profile: Profile,
    event_start_pts: float,
    event_end_pts: float,
    samples: Sequence[MomentEvidenceSample],
    source_timeline_fingerprint: str,
    coarse_windows: Sequence[CoarseMomentWindow] = (),
    revision: int = 1,
) -> EventMomentSet:
    if event_end_pts < event_start_pts:
        raise ValueError("event interval must be ordered")
    windows = {item.semantic_key: item for item in coarse_windows}
    ordered = sorted(
        (
            sample for sample in samples
            if event_start_pts <= sample.pts_sec <= event_end_pts and sample.exact_confirmed
        ),
        key=lambda sample: (sample.pts_sec, sample.source_frame_index),
    )
    # Coarse windows restrict the source-resolution search only when a profile
    # state machine asks for that semantic key; they never introduce a marker.
    if windows:
        lower = min(item.start_pts_sec for item in windows.values())
        upper = max(item.end_pts_sec for item in windows.values())
        ordered = [sample for sample in ordered if lower <= sample.pts_sec <= upper]
    if profile == "jump":
        moments = _jump(event_id, ordered)
    elif profile in {"spin", "spiral"}:
        moments = _phase_triplet(event_id, profile, ordered)
    else:
        moments = _step(event_id, ordered)
    definitions = PROFILE_DEFINITIONS[profile]
    required = {item.semantic_key for item in definitions if item.required_for_complete}
    present = tuple(item.semantic_key for item in moments if item.status != "unavailable")
    missing = tuple(item.semantic_key for item in moments if item.status == "unavailable")
    if not ordered:
        completeness = "unobservable"
    elif any(item.status == "ambiguous" for item in moments):
        completeness = "ambiguous"
    elif required.issubset(present):
        completeness = "complete"
    else:
        completeness = "incomplete"
    warnings: list[str] = []
    if any(sample.frame_status in {"gap_after_previous", "discontinuity"} for sample in ordered):
        warnings.append("source_decode_gap_or_discontinuity")
    if any(sample.semantic_review_keys for sample in ordered):
        warnings.append("semantic_keyframes_retained_as_review_evidence_only")
    definition_version = definitions[0].definition_version
    fingerprint_payload = {
        "definition_catalog": definition_catalog()[profile],
        "contract": "profile-moment-state-machine.v1",
        "thresholds": {"airborne": .55, "contact": .55, "spin_periodicity": .55, "spiral_extension": .62, "step_complexity": .48},
    }
    return EventMomentSet(
        event_id=event_id,
        profile=profile,
        definition_version=definition_version,
        moments=tuple(moments),
        expected_keys=tuple(item.semantic_key for item in definitions),
        required_keys=tuple(item.semantic_key for item in definitions if item.required_for_complete),
        present_keys=present,
        missing_keys=missing,
        completeness=completeness,
        warnings=tuple(warnings),
        source_timeline_fingerprint=source_timeline_fingerprint,
        state_machine_fingerprint=_fingerprint(fingerprint_payload),
        semantic_labels_consumed=False,
        revision=revision,
    )
