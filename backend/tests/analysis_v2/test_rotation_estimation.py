from __future__ import annotations

import math

import cv2
import numpy as np
import pytest

from app.analysis_v2.rotation import (
    RotationEvidenceSample,
    TargetCropFrame,
    _capped_weights,
    estimate_rotation,
    extract_target_crop_appearance,
    extract_target_crop_optical_flow,
)


def samples(
    turns: float,
    *,
    phase: str = "airborne",
    count: int = 31,
    start_pts: float = 0.0,
    duration_sec: float = 1.0,
    shoulder_turns: float | None = None,
    hip_turns: float | None = None,
    appearance_turns: float | None = None,
    flow_turns: float | None = None,
    left_right_confidence: float = .98,
    pose_quality: float = .95,
    occlusion: float = 0,
    upright_axis_confidence: float = 1,
    arm_change: bool = False,
    camera_roll_turns: float = 0,
    camera_roll_reliability: float | None = .9,
) -> list[RotationEvidenceSample]:
    shoulder_turns = turns if shoulder_turns is None else shoulder_turns
    hip_turns = turns if hip_turns is None else hip_turns
    appearance_turns = turns if appearance_turns is None else appearance_turns
    flow_turns = turns if flow_turns is None else flow_turns
    output = []
    for index in range(count):
        progress = index / (count - 1)
        pts = start_pts + progress * duration_sec
        roll = camera_roll_turns * 2 * math.pi * progress
        output.append(RotationEvidenceSample(
            source_frame_index=index,
            pts_sec=pts,
            phase=phase,
            pose_quality=pose_quality,
            left_right_assignment_confidence=left_right_confidence,
            shoulder_orientation_rad=shoulder_turns * 2 * math.pi * progress + roll,
            hip_orientation_rad=hip_turns * 2 * math.pi * progress + .02 + roll,
            torso_appearance_phase_rad=appearance_turns * 2 * math.pi * progress - .03 + roll,
            silhouette_orientation_rad=appearance_turns * 2 * math.pi * progress + roll,
            silhouette_confidence=.9,
            limb_appearance_phase_rad=appearance_turns * 2 * math.pi * progress + .04 + roll,
            optical_flow_rotation_rad=0 if index == 0 else flow_turns * 2 * math.pi / (count - 1),
            optical_flow_confidence=.9,
            camera_roll_rad=roll,
            camera_roll_reliability=camera_roll_reliability,
            arm_position_context=progress if arm_change else .5,
            occlusion=occlusion,
            upright_axis_confidence=upright_axis_confidence,
            provenance=("synthetic_source_pts",),
        ))
    return output


def estimate(event_samples: list[RotationEvidenceSample], **changes):
    return estimate_rotation(
        event_id="event-1",
        profile="jump",
        event_start_pts=min(item.pts_sec for item in event_samples),
        event_end_pts=max(item.pts_sec for item in event_samples),
        samples=event_samples,
        source_timeline_fingerprint="source-pts-fingerprint",
        **changes,
    )


@pytest.mark.parametrize("turns", [1.0, 1.5, 2.0, 3.0])
def test_ideal_turns_are_exact_and_half_integer_classified(turns: float) -> None:
    result = estimate(samples(turns), subtype="axel" if turns == 1.5 else "toe_loop", subtype_support=.9)
    assert result.status == "exact"
    assert result.value_turns == pytest.approx(turns, abs=.03)
    assert result.class_turns == turns
    assert result.class_kind == ("integer" if turns.is_integer() else "half_integer")
    assert max(_capped_weights([.99, .18, .18])) <= .45


def test_front_or_back_flip_axis_is_rejected_as_unobservable() -> None:
    result = estimate(samples(1.0, upright_axis_confidence=.2))
    assert result.status == "unobservable"
    assert result.refusal_reason == "required_phase_unobservable"


def test_left_right_swaps_do_not_change_turn_count_when_other_signals_agree() -> None:
    event_samples = samples(2.0, left_right_confidence=.3)
    for index, item in enumerate(event_samples):
        if index % 2:
            event_samples[index] = item.model_copy(update={
                "shoulder_orientation_rad": item.shoulder_orientation_rad + math.pi,
                "hip_orientation_rad": item.hip_orientation_rad + math.pi,
            })
    result = estimate(event_samples)
    assert result.status == "exact"
    assert result.class_turns == 2
    pose_signals = [item for item in result.signals if item.signal in {"shoulder_orientation", "hip_orientation"} and item.phase == "airborne"]
    assert all("left_right_assignment_uncertain" in item.warnings for item in pose_signals)


def test_unreliable_shoulder_signal_cannot_dominate_independent_appearance_and_flow() -> None:
    event_samples = samples(2.0, shoulder_turns=0, pose_quality=.05)
    event_samples = [item.model_copy(update={"hip_orientation_rad": None}) for item in event_samples]
    result = estimate(event_samples)
    assert result.status == "exact"
    assert result.class_turns == 2
    shoulder = next(item for item in result.signals if item.signal == "shoulder_orientation" and item.phase == "airborne")
    assert shoulder.estimate_turns == 0
    assert shoulder.reliability < .18


def test_two_signal_fusion_preserves_unassigned_uncertainty_mass() -> None:
    weights = _capped_weights([.9, .9])
    assert weights == pytest.approx([.45, .45])
    assert sum(weights) == pytest.approx(.9)


def test_two_pose_axes_alone_are_not_treated_as_independent_signal_families() -> None:
    event_samples = [item.model_copy(update={
        "torso_appearance_phase_rad": None,
        "silhouette_orientation_rad": None,
        "limb_appearance_phase_rad": None,
        "optical_flow_rotation_rad": None,
    }) for item in samples(1.0)]
    result = estimate(event_samples)
    assert result.status == "unobservable"
    assert result.refusal_reason == "insufficient_independent_signals"


def test_occlusion_sparse_sampling_aliasing_camera_roll_and_arm_changes_are_rejectable() -> None:
    occluded = estimate(samples(2.0, occlusion=.8))
    sparse = estimate(samples(2.0, count=4))
    unresolved_roll = estimate(samples(1.0, camera_roll_turns=.2, camera_roll_reliability=.2))
    arm_change = estimate(samples(1.0, arm_change=True))
    assert (occluded.status, occluded.refusal_reason) == ("unobservable", "occlusion")
    assert sparse.status in {"range", "unobservable"}
    assert sparse.refusal_reason == "signal_aliasing"
    assert unresolved_roll.status == "unobservable"
    assert unresolved_roll.refusal_reason == "camera_roll_unresolved"
    assert arm_change.status in {"range", "unobservable"}
    assert arm_change.refusal_reason == "changing_arm_position"


def test_reliable_camera_roll_is_compensated() -> None:
    result = estimate(samples(1.0, camera_roll_turns=.2, camera_roll_reliability=.95))
    assert result.status == "exact"
    assert result.class_turns == 1


def test_conflicting_turn_hypotheses_never_become_a_confident_count() -> None:
    result = estimate(samples(2.0, shoulder_turns=1, hip_turns=1))
    assert result.status in {"range", "unobservable"}
    assert result.value_turns is None
    assert result.class_turns is None
    assert result.refusal_reason == "conflicting_turn_hypotheses"


def test_axel_convention_never_changes_airborne_physical_rotation() -> None:
    supported = estimate(samples(1.5), subtype="Axel", subtype_support=.9)
    underpowered = estimate(samples(1.5), subtype="Axel", subtype_support=.74)
    non_axel = estimate(samples(2.0), subtype="toe loop", subtype_support=.9)
    assert supported.value_turns == pytest.approx(1.5)
    assert supported.competition_convention == "axel"
    assert supported.competition_naming_class == "single_axel"
    assert underpowered.value_turns == pytest.approx(1.5)
    assert underpowered.competition_convention == "unknown"
    assert underpowered.competition_naming_turns is None
    assert non_axel.competition_convention == "non_axel"


def test_pre_airborne_and_post_landing_rotation_are_separate_pts_phases() -> None:
    event_samples = [
        *samples(.25, phase="pre_takeoff", count=9, start_pts=1, duration_sec=.32),
        *samples(2.0, phase="airborne", count=21, start_pts=1.4, duration_sec=.64),
        *samples(.5, phase="post_landing", count=11, start_pts=2.1, duration_sec=.4),
    ]
    result = estimate_rotation(event_id="event-1", profile="jump", event_start_pts=1, event_end_pts=2.5, samples=event_samples, source_timeline_fingerprint="fp")
    phases = {item.phase: item for item in result.phases}
    assert result.class_turns == 2
    assert phases["pre_takeoff"].status == "range"
    assert phases["pre_takeoff"].range_turns[0] <= .25 <= phases["pre_takeoff"].range_turns[1]
    assert phases["airborne"].value_turns == pytest.approx(2, abs=.04)
    assert phases["post_landing"].status in {"exact", "range"}
    if phases["post_landing"].status == "exact":
        assert phases["post_landing"].value_turns == pytest.approx(.5, abs=.04)
    else:
        assert phases["post_landing"].range_turns[0] <= .5 <= phases["post_landing"].range_turns[1]


def test_spin_uses_spin_main_and_observed_spin_definition() -> None:
    event_samples = samples(3.0, phase="spin_main", count=31, duration_sec=1.4)
    result = estimate_rotation(
        event_id="spin-1",
        profile="spin",
        event_start_pts=0,
        event_end_pts=1.4,
        samples=event_samples,
        source_timeline_fingerprint="spin-source-pts",
    )
    assert result.status == "exact"
    assert result.value_turns == pytest.approx(3, abs=.04)
    assert result.definition_version == "observed-spin-rotation.source-pts.v1"
    assert result.value_convention == "observed_spin_rotation"
    assert result.competition_convention == "not_applied"
    assert next(phase for phase in result.phases if phase.phase == "spin_main").status == "exact"


def test_signal_duration_uses_pts_not_sample_count() -> None:
    result = estimate(samples(1.0, count=31, duration_sec=.47))
    shoulder = next(item for item in result.signals if item.signal == "shoulder_orientation" and item.phase == "airborne")
    assert shoulder.sample_count == 31
    assert shoulder.duration_sec == pytest.approx(.47)


def test_target_crop_extractors_produce_bounded_appearance_and_flow_evidence() -> None:
    rng = np.random.default_rng(7)
    base = np.zeros((96, 96), dtype=np.uint8)
    for x, y in rng.integers(14, 82, size=(70, 2)):
        cv2.circle(base, (int(x), int(y)), 1, 255, -1)
    cv2.rectangle(base, (38, 18), (58, 78), 180, -1)
    matrix = cv2.getRotationMatrix2D((48, 48), 8, 1)
    rotated = cv2.warpAffine(base, matrix, (96, 96))
    frames = (TargetCropFrame(source_frame_index=0, pts_sec=0), TargetCropFrame(source_frame_index=1, pts_sec=.04))
    appearance = extract_target_crop_appearance(frames, (base, rotated))
    flow = extract_target_crop_optical_flow(frames, (base, rotated))
    assert all(item.torso_phase_rad is not None and item.limb_phase_rad is not None for item in appearance)
    assert all(0 <= item.silhouette_confidence <= 1 for item in appearance)
    assert flow[1].rotation_rad is not None
    assert flow[1].confidence > .4
