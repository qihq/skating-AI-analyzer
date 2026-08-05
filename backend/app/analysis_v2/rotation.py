from __future__ import annotations

"""Profile-aware multi-signal rotation estimation on exact source PTS.

The estimator treats every visual cue as fallible.  Pose orientation,
appearance periodicity, silhouette orientation and target-crop optical flow
produce independent likelihoods with explicit reliability.  Fusion caps each
signal's influence, preserves competing hypotheses and refuses when source
sampling or visibility cannot distinguish turn counts.
"""

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import cv2
import numpy as np
from pydantic import Field, model_validator

from app.analysis_v2.contracts import (
    ContractModel,
    PoseObservation,
    RotationEstimate,
    RotationPhase,
    RotationPhaseEstimate,
    RotationRefusalReason,
    RotationSignalEstimate,
    RotationSignalKind,
)


Profile = Literal["jump", "spin"]


class RotationEvidenceSample(ContractModel):
    schema_version: Literal["rotation-evidence-sample.v1"] = "rotation-evidence-sample.v1"
    source_frame_index: int = Field(ge=0)
    pts_sec: float = Field(ge=0)
    phase: RotationPhase
    timing_provenance: Literal["source_pts", "legacy_approximate"] = "source_pts"
    frame_status: Literal["available", "duplicate_pts", "gap_after_previous", "discontinuity", "timestamp_unavailable"] = "available"
    tracking_state: Literal["confirmed", "uncertain", "lost"] = "confirmed"
    occlusion: float = Field(default=0, ge=0, le=1)
    blur: float = Field(default=0, ge=0, le=1)
    pose_quality: float | None = Field(default=None, ge=0, le=1)
    left_right_assignment_confidence: float | None = Field(default=None, ge=0, le=1)
    shoulder_orientation_rad: float | None = None
    hip_orientation_rad: float | None = None
    torso_appearance_phase_rad: float | None = None
    silhouette_orientation_rad: float | None = None
    silhouette_confidence: float | None = Field(default=None, ge=0, le=1)
    limb_appearance_phase_rad: float | None = None
    optical_flow_rotation_rad: float | None = None
    optical_flow_confidence: float | None = Field(default=None, ge=0, le=1)
    camera_roll_rad: float | None = None
    camera_roll_reliability: float | None = Field(default=None, ge=0, le=1)
    arm_position_context: float | None = Field(default=None, ge=0, le=1)
    upright_axis_confidence: float = Field(default=1, ge=0, le=1)
    provenance: tuple[str, ...] = ()

    @property
    def exact_confirmed(self) -> bool:
        return (
            self.timing_provenance == "source_pts"
            and self.frame_status != "timestamp_unavailable"
            and self.tracking_state == "confirmed"
        )


class TargetCropFrame(ContractModel):
    """Metadata for one crop; pixels are passed separately to keep wire models bounded."""

    source_frame_index: int = Field(ge=0)
    pts_sec: float = Field(ge=0)
    camera_roll_rad: float | None = None
    camera_roll_reliability: float | None = Field(default=None, ge=0, le=1)


@dataclass(frozen=True)
class OpticalFlowObservation:
    source_frame_index: int
    pts_sec: float
    rotation_rad: float | None
    confidence: float
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class CropAppearanceObservation:
    source_frame_index: int
    pts_sec: float
    torso_phase_rad: float | None
    silhouette_orientation_rad: float | None
    silhouette_confidence: float
    limb_phase_rad: float | None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class _SignalWork:
    estimate: RotationSignalEstimate
    severe_warning: RotationRefusalReason | None = None


CLASS_GRID = tuple(index / 2 for index in range(0, 25))
SIGNAL_WEIGHT_CAP = .45
MIN_SIGNAL_RELIABILITY = .18
MIN_INDEPENDENT_SIGNALS = 2
MIN_INDEPENDENT_SIGNAL_FAMILIES = 2
AXEL_SUBTYPE_SUPPORT_MIN = .75
MAX_OBSERVABLE_GAP_SEC = .12
MAX_UNALIASED_DELTA_TURNS = .42
MAX_YAW_RPS = 9.0


def extract_target_crop_optical_flow(
    frames: Sequence[TargetCropFrame],
    grayscale_crops: Sequence[np.ndarray],
) -> tuple[OpticalFlowObservation, ...]:
    """Estimate in-plane crop rotation between exact-PTS target crops.

    The affine rotation is a bounded evidence provider, not the final body
    rotation.  Camera roll is subtracted only when its reliability is known.
    """

    if len(frames) != len(grayscale_crops):
        raise ValueError("target crop metadata and pixels must have equal length")
    output: list[OpticalFlowObservation] = []
    for index, frame in enumerate(frames):
        if index == 0:
            output.append(OpticalFlowObservation(frame.source_frame_index, frame.pts_sec, None, 0, ("first_crop_has_no_flow_delta",)))
            continue
        previous = frames[index - 1]
        prior_image = np.asarray(grayscale_crops[index - 1])
        image = np.asarray(grayscale_crops[index])
        warnings: list[str] = []
        if frame.pts_sec <= previous.pts_sec:
            output.append(OpticalFlowObservation(frame.source_frame_index, frame.pts_sec, None, 0, ("non_positive_pts_delta",)))
            continue
        if prior_image.ndim == 3:
            prior_image = cv2.cvtColor(prior_image.astype(np.uint8), cv2.COLOR_BGR2GRAY)
        if image.ndim == 3:
            image = cv2.cvtColor(image.astype(np.uint8), cv2.COLOR_BGR2GRAY)
        if prior_image.shape != image.shape or prior_image.size == 0:
            output.append(OpticalFlowObservation(frame.source_frame_index, frame.pts_sec, None, 0, ("crop_shape_changed",)))
            continue
        corners = cv2.goodFeaturesToTrack(prior_image.astype(np.uint8), maxCorners=120, qualityLevel=.015, minDistance=4, blockSize=5)
        if corners is None or len(corners) < 8:
            output.append(OpticalFlowObservation(frame.source_frame_index, frame.pts_sec, None, 0, ("insufficient_flow_features",)))
            continue
        tracked, status, error = cv2.calcOpticalFlowPyrLK(prior_image.astype(np.uint8), image.astype(np.uint8), corners, None)
        if tracked is None or status is None:
            output.append(OpticalFlowObservation(frame.source_frame_index, frame.pts_sec, None, 0, ("optical_flow_failed",)))
            continue
        good = status.reshape(-1) == 1
        source_points = corners.reshape(-1, 2)[good]
        target_points = tracked.reshape(-1, 2)[good]
        if len(source_points) < 8:
            output.append(OpticalFlowObservation(frame.source_frame_index, frame.pts_sec, None, 0, ("insufficient_tracked_features",)))
            continue
        affine, inliers = cv2.estimateAffinePartial2D(source_points, target_points, method=cv2.RANSAC, ransacReprojThreshold=2.5)
        if affine is None:
            output.append(OpticalFlowObservation(frame.source_frame_index, frame.pts_sec, None, 0, ("affine_rotation_unavailable",)))
            continue
        rotation = math.atan2(float(affine[1, 0]), float(affine[0, 0]))
        roll_reliability = min(previous.camera_roll_reliability or 0, frame.camera_roll_reliability or 0)
        if previous.camera_roll_rad is not None and frame.camera_roll_rad is not None and roll_reliability >= .55:
            rotation -= _wrap(frame.camera_roll_rad - previous.camera_roll_rad, 2 * math.pi)
        elif previous.camera_roll_rad is not None and frame.camera_roll_rad is not None and abs(frame.camera_roll_rad - previous.camera_roll_rad) >= .08:
            warnings.append("camera_roll_unresolved")
        inlier_rate = float(np.mean(inliers)) if inliers is not None and len(inliers) else 0.0
        tracking_rate = len(source_points) / len(corners)
        mean_error = float(np.mean(error.reshape(-1)[good])) if error is not None and np.any(good) else 20.0
        confidence = max(0.0, min(1.0, .55 * inlier_rate + .35 * tracking_rate + .10 * max(0.0, 1 - mean_error / 20)))
        output.append(OpticalFlowObservation(frame.source_frame_index, frame.pts_sec, rotation, confidence, tuple(warnings)))
    return tuple(output)


def rotation_sample_from_pose(
    pose: PoseObservation,
    *,
    phase: RotationPhase,
    occlusion: float = 0,
    blur: float = 0,
    camera_roll_rad: float | None = None,
    camera_roll_reliability: float | None = None,
    arm_position_context: float | None = None,
) -> RotationEvidenceSample:
    """Extract shoulder/hip orientation only from identity-authorized pose."""

    def orientation(left_name: str, right_name: str) -> float | None:
        left = pose.joints.get(left_name)
        right = pose.joints.get(right_name)
        if left is None or right is None or not left.is_authoritative or not right.is_authoritative:
            return None
        return math.atan2(right.y - left.y, right.x - left.x)

    assignment_confidence = None if pose.left_right_assignment_uncertainty is None else 1 - pose.left_right_assignment_uncertainty
    return RotationEvidenceSample(
        source_frame_index=pose.source_frame_index,
        pts_sec=pose.pts_sec,
        phase=phase,
        tracking_state=pose.track_state.state,
        occlusion=occlusion,
        blur=blur,
        pose_quality=pose.pose_quality,
        left_right_assignment_confidence=assignment_confidence,
        shoulder_orientation_rad=orientation("left_shoulder", "right_shoulder"),
        hip_orientation_rad=orientation("left_hip", "right_hip"),
        camera_roll_rad=camera_roll_rad,
        camera_roll_reliability=camera_roll_reliability,
        arm_position_context=arm_position_context,
        provenance=("source_pts", "pose_observation", pose.source_method),
    )


def extract_target_crop_appearance(
    frames: Sequence[TargetCropFrame],
    grayscale_crops: Sequence[np.ndarray],
) -> tuple[CropAppearanceObservation, ...]:
    """Extract silhouette orientation and bounded torso/limb appearance phases."""

    if len(frames) != len(grayscale_crops):
        raise ValueError("target crop metadata and pixels must have equal length")
    output: list[CropAppearanceObservation] = []
    for frame, crop in zip(frames, grayscale_crops):
        image = np.asarray(crop)
        if image.ndim == 3:
            image = cv2.cvtColor(image.astype(np.uint8), cv2.COLOR_BGR2GRAY)
        image = image.astype(np.uint8)
        if image.size == 0 or min(image.shape[:2]) < 8:
            output.append(CropAppearanceObservation(frame.source_frame_index, frame.pts_sec, None, None, 0, None, ("crop_too_small",)))
            continue
        border = np.concatenate((image[0], image[-1], image[:, 0], image[:, -1]))
        foreground_strength = cv2.absdiff(image, np.full_like(image, int(np.median(border))))
        _threshold, mask = cv2.threshold(foreground_strength, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        points = np.column_stack(np.nonzero(mask))
        if len(points) < 20:
            output.append(CropAppearanceObservation(frame.source_frame_index, frame.pts_sec, None, None, 0, None, ("silhouette_unavailable",)))
            continue
        y = points[:, 0].astype(float)
        x = points[:, 1].astype(float)
        covariance = np.cov(np.column_stack((x, y)), rowvar=False)
        eigenvalues, eigenvectors = np.linalg.eigh(covariance)
        axis = eigenvectors[:, int(np.argmax(eigenvalues))]
        silhouette = math.atan2(float(axis[1]), float(axis[0]))
        anisotropy = float((max(eigenvalues) - min(eigenvalues)) / max(max(eigenvalues), 1e-9))
        height, width = image.shape[:2]
        mid_x, mid_y = width // 2, height // 2
        weights = foreground_strength.astype(float) * (mask.astype(float) / 255)
        left = float(weights[:, :mid_x].sum())
        right = float(weights[:, mid_x:].sum())
        top_left = float(weights[:mid_y, :mid_x].sum())
        top_right = float(weights[:mid_y, mid_x:].sum())
        bottom_left = float(weights[mid_y:, :mid_x].sum())
        bottom_right = float(weights[mid_y:, mid_x:].sum())
        torso_phase = math.atan2((top_right + bottom_left) - (top_left + bottom_right), right - left)
        center_x = float(np.average(x, weights=foreground_strength[points[:, 0], points[:, 1]].astype(float) + 1))
        center_y = float(np.average(y, weights=foreground_strength[points[:, 0], points[:, 1]].astype(float) + 1))
        outer = (np.abs(x - center_x) > width * .22) | (np.abs(y - center_y) > height * .30)
        limb_phase = math.atan2(float(np.mean(y[outer]) - center_y), float(np.mean(x[outer]) - center_x)) if np.any(outer) else None
        output.append(CropAppearanceObservation(
            frame.source_frame_index,
            frame.pts_sec,
            torso_phase,
            silhouette,
            max(0.0, min(1.0, anisotropy)),
            limb_phase,
        ))
    return tuple(output)


def attach_crop_appearance(
    samples: Sequence[RotationEvidenceSample], observations: Sequence[CropAppearanceObservation],
) -> tuple[RotationEvidenceSample, ...]:
    by_frame = {item.source_frame_index: item for item in observations}
    return tuple(
        sample.model_copy(update={
            "torso_appearance_phase_rad": by_frame[sample.source_frame_index].torso_phase_rad,
            "silhouette_orientation_rad": by_frame[sample.source_frame_index].silhouette_orientation_rad,
            "silhouette_confidence": by_frame[sample.source_frame_index].silhouette_confidence,
            "limb_appearance_phase_rad": by_frame[sample.source_frame_index].limb_phase_rad,
            "provenance": tuple(dict.fromkeys((*sample.provenance, *by_frame[sample.source_frame_index].warnings, "target_crop_appearance"))),
        }) if sample.source_frame_index in by_frame else sample
        for sample in samples
    )


def attach_optical_flow(
    samples: Sequence[RotationEvidenceSample], observations: Sequence[OpticalFlowObservation],
) -> tuple[RotationEvidenceSample, ...]:
    by_frame = {item.source_frame_index: item for item in observations}
    return tuple(
        sample.model_copy(update={
            "optical_flow_rotation_rad": by_frame[sample.source_frame_index].rotation_rad,
            "optical_flow_confidence": by_frame[sample.source_frame_index].confidence,
            "provenance": tuple(dict.fromkeys((*sample.provenance, *by_frame[sample.source_frame_index].warnings, "target_crop_optical_flow"))),
        }) if sample.source_frame_index in by_frame else sample
        for sample in samples
    )


def estimate_rotation(
    *,
    event_id: str,
    profile: Profile,
    event_start_pts: float,
    event_end_pts: float,
    samples: Sequence[RotationEvidenceSample],
    source_timeline_fingerprint: str,
    subtype: str | None = None,
    subtype_support: float | None = None,
) -> RotationEstimate:
    if event_end_pts < event_start_pts:
        raise ValueError("rotation event interval must be ordered")
    ordered = sorted(
        (sample for sample in samples if event_start_pts <= sample.pts_sec <= event_end_pts),
        key=lambda item: (item.pts_sec, item.source_frame_index),
    )
    fingerprint = _fingerprint({
        "version": "multi-signal-rotation.v1",
        "profile": profile,
        "weight_cap": SIGNAL_WEIGHT_CAP,
        "weight_policy": "bounded_with_unassigned_uncertainty_mass.v1",
        "sampling_gap": MAX_OBSERVABLE_GAP_SEC,
        "alias_delta": MAX_UNALIASED_DELTA_TURNS,
        "source_timeline": source_timeline_fingerprint,
    })
    if source_timeline_fingerprint in {"", "unavailable", "source-timeline:unavailable"} or not ordered or any(item.timing_provenance != "source_pts" or item.frame_status == "timestamp_unavailable" for item in ordered):
        return _refusal(event_id, profile, fingerprint, source_timeline_fingerprint, "timestamp_unavailable", subtype_support)
    if not any(item.tracking_state == "confirmed" for item in ordered):
        return _refusal(event_id, profile, fingerprint, source_timeline_fingerprint, "identity_not_confirmed", subtype_support)

    phase_order: tuple[RotationPhase, ...] = (
        ("pre_takeoff", "airborne", "post_landing") if profile == "jump" else ("spin_main", "whole_event")
    )
    phase_results: dict[RotationPhase, tuple[RotationPhaseEstimate, tuple[RotationSignalEstimate, ...], tuple[str, ...], tuple[str, ...]]] = {}
    for phase in phase_order:
        phase_samples = [item for item in ordered if item.phase == phase]
        if phase == "whole_event" and not phase_samples:
            phase_samples = ordered
        phase_results[phase] = _estimate_phase(phase, phase_samples)

    authoritative_phase: RotationPhase = "airborne" if profile == "jump" else "spin_main"
    main, signals, conflicts, warnings = phase_results[authoritative_phase]
    all_signals = tuple(signal for phase in phase_order for signal in phase_results[phase][1])
    all_conflicts = tuple(dict.fromkeys(value for phase in phase_order for value in phase_results[phase][2]))
    all_warnings = tuple(dict.fromkeys(value for phase in phase_order for value in phase_results[phase][3]))
    phases = tuple(phase_results[phase][0] for phase in phase_order if phase != "whole_event" or profile == "spin")
    class_turns = _nearest_half(main.value_turns) if main.status == "exact" and main.value_turns is not None else None
    class_kind = None if class_turns is None else "integer" if abs(class_turns - round(class_turns)) < 1e-9 else "half_integer"
    competition_convention, competition_turns, competition_class = _competition_naming(
        profile=profile,
        subtype=subtype,
        subtype_support=subtype_support,
        class_turns=class_turns,
    )
    evidence_summary = tuple(
        f"{item.signal}:{item.estimate_turns:.2f} turns, reliability {item.reliability:.2f}"
        for item in signals
        if item.estimate_turns is not None and item.reliability >= MIN_SIGNAL_RELIABILITY
    )
    return RotationEstimate(
        event_id=event_id,
        profile=profile,
        definition_version="airborne-body-rotation.source-pts.v1" if profile == "jump" else "observed-spin-rotation.source-pts.v1",
        status=main.status,
        value_turns=main.value_turns,
        range_turns=main.range_turns,
        class_turns=class_turns,
        class_kind=class_kind,
        confidence=main.confidence,
        observability=main.observability,
        refusal_reason=main.refusal_reason,
        value_convention="airborne_body_rotation" if profile == "jump" else "observed_spin_rotation",
        competition_convention=competition_convention,
        competition_naming_turns=competition_turns,
        competition_naming_class=competition_class,
        subtype_support=subtype_support,
        phases=phases,
        signals=all_signals,
        evidence_summary=evidence_summary,
        conflicts=all_conflicts or conflicts,
        warnings=all_warnings or warnings,
        estimator_fingerprint=fingerprint,
        source_timeline_fingerprint=source_timeline_fingerprint,
        review_required=main.status == "range",
    )


def _estimate_phase(
    phase: RotationPhase,
    samples: Sequence[RotationEvidenceSample],
) -> tuple[RotationPhaseEstimate, tuple[RotationSignalEstimate, ...], tuple[str, ...], tuple[str, ...]]:
    if len(samples) < 2:
        return _phase_refusal(phase, "required_phase_unobservable"), (), (), ("required_phase_unobservable",)
    exact = [item for item in samples if item.exact_confirmed]
    if len(exact) < 2:
        return _phase_refusal(phase, "identity_not_confirmed"), (), (), ("identity_not_confirmed",)
    duration = exact[-1].pts_sec - exact[0].pts_sec
    gaps = [current.pts_sec - prior.pts_sec for prior, current in zip(exact, exact[1:])]
    if duration <= 0:
        return _phase_refusal(phase, "timestamp_unavailable"), (), (), ("timestamp_unavailable",)
    sampling_warning = len(exact) < 5 or not gaps or max(gaps) > MAX_OBSERVABLE_GAP_SEC
    occlusion_mean = sum(item.occlusion for item in exact) / len(exact)
    upright_mean = sum(item.upright_axis_confidence for item in exact) / len(exact)
    arm_values = [item.arm_position_context for item in exact if item.arm_position_context is not None]
    arm_change = max(arm_values) - min(arm_values) if len(arm_values) >= 2 else 0.0
    camera_roll_unresolved = _camera_roll_unresolved(exact)
    works = [
        _orientation_signal(exact, phase, "shoulder_orientation", "shoulder_orientation_rad", left_right=True),
        _orientation_signal(exact, phase, "hip_orientation", "hip_orientation_rad", left_right=True),
        _orientation_signal(exact, phase, "torso_appearance_periodicity", "torso_appearance_phase_rad"),
        _orientation_signal(exact, phase, "silhouette_orientation", "silhouette_orientation_rad", axial=True),
        _orientation_signal(exact, phase, "limb_appearance_periodicity", "limb_appearance_phase_rad"),
        _optical_flow_signal(exact, phase),
    ]
    signals = tuple(item.estimate for item in works if item.estimate.sample_count > 0 or item.estimate.observability == "unobservable")
    candidates = [item.estimate for item in works if item.estimate.estimate_turns is not None and item.estimate.reliability >= MIN_SIGNAL_RELIABILITY]
    warnings: list[str] = []
    if sampling_warning:
        warnings.append("insufficient_sampling")
    if occlusion_mean >= .35:
        warnings.append("occlusion")
    if camera_roll_unresolved:
        warnings.append("camera_roll_unresolved")
    if arm_change >= .32:
        warnings.append("changing_arm_position")
    if upright_mean < .48:
        warnings.append("upright_axis_unobservable")
    if any("signal_aliasing" in item.warnings for item in candidates):
        warnings.append("signal_aliasing")
    signal_families = {_signal_family(item.signal) for item in candidates}
    if len(candidates) < MIN_INDEPENDENT_SIGNALS or len(signal_families) < MIN_INDEPENDENT_SIGNAL_FAMILIES:
        reason: RotationRefusalReason = "insufficient_sampling" if sampling_warning else "insufficient_independent_signals"
        return _phase_refusal(phase, reason), signals, (), tuple(dict.fromkeys(warnings))
    if upright_mean < .35:
        return _phase_refusal(phase, "required_phase_unobservable"), signals, (), tuple(dict.fromkeys(warnings))

    estimates = [float(item.estimate_turns) for item in candidates if item.estimate_turns is not None]
    raw_weights = [item.reliability for item in candidates]
    weights = _capped_weights(raw_weights)
    assigned_weight = sum(weights)
    fusion_weights = [weight / assigned_weight for weight in weights]
    fused = sum(value * weight for value, weight in zip(estimates, fusion_weights))
    spread = math.sqrt(sum(weight * (value - fused) ** 2 for value, weight in zip(estimates, fusion_weights)))
    likelihoods = _fused_likelihoods(candidates, weights)
    ranked = sorted(likelihoods.items(), key=lambda item: (-item[1], float(item[0])))
    top_class = float(ranked[0][0]) if ranked else _nearest_half(fused)
    top_probability = ranked[0][1] if ranked else 0.0
    second_probability = ranked[1][1] if len(ranked) > 1 else 0.0
    class_margin = top_probability - second_probability
    aliased = sampling_warning or any("signal_aliasing" in item.warnings for item in candidates)
    conflict = spread > .38 or class_margin < .16 or any(abs(value - top_class) >= .65 for value in estimates)
    if conflict:
        warnings.append("conflicting_turn_hypotheses")
    effective_reliability = sum(weight * candidate.reliability for weight, candidate in zip(weights, candidates))
    visibility = max(0.0, min(1.0, (1 - occlusion_mean) * upright_mean * (1 - .45 * min(1.0, arm_change / .5))))
    agreement = max(0.0, min(1.0, 1 - spread / .75))
    confidence = max(0.0, min(1.0, effective_reliability * visibility * agreement * (.72 + .28 * min(1.0, len(candidates) / 4))))
    interval_radius = max(.08, 1.65 * spread + (1 - confidence) * .18)
    low = max(0.0, min(min(estimates), fused - interval_radius))
    high = max(max(estimates), fused + interval_radius)
    if aliased:
        high += .5
    if occlusion_mean >= .6:
        return _phase_refusal(phase, "occlusion"), signals, (), tuple(dict.fromkeys(warnings))
    if camera_roll_unresolved and sum(item.reliability for item in candidates if item.signal in {"shoulder_orientation", "hip_orientation", "silhouette_orientation", "target_crop_optical_flow"}) >= sum(item.reliability for item in candidates) * .55:
        return _phase_refusal(phase, "camera_roll_unresolved"), signals, (), tuple(dict.fromkeys(warnings))
    if not conflict and not aliased and confidence >= .70 and high - low <= .35 and class_margin >= .18:
        return RotationPhaseEstimate(
            phase=phase,
            status="exact",
            value_turns=round(fused, 4),
            confidence=round(confidence, 4),
            observability="observed",
        ), signals, (), tuple(dict.fromkeys(warnings))
    reason = "signal_aliasing" if aliased else "conflicting_turn_hypotheses" if conflict else "changing_arm_position" if arm_change >= .32 else "required_phase_unobservable"
    bounded_low = math.floor(low * 4) / 4
    bounded_high = math.ceil(high * 4) / 4
    if bounded_high - bounded_low > 1.5 or confidence < .22:
        return _phase_refusal(phase, reason), signals, (reason,), tuple(dict.fromkeys(warnings))
    return RotationPhaseEstimate(
        phase=phase,
        status="range",
        range_turns=(round(bounded_low, 2), round(bounded_high, 2)),
        confidence=round(confidence, 4),
        observability="partial",
        refusal_reason=reason,
    ), signals, (reason,), tuple(dict.fromkeys(warnings))


def _orientation_signal(
    samples: Sequence[RotationEvidenceSample],
    phase: RotationPhase,
    signal: RotationSignalKind,
    field: str,
    *,
    left_right: bool = False,
    axial: bool = False,
) -> _SignalWork:
    present = [(item, getattr(item, field)) for item in samples if getattr(item, field) is not None]
    if len(present) < 2:
        return _unobservable_signal(signal, phase, "signal_not_available")
    left_right_confidence = [item.left_right_assignment_confidence for item, _value in present if item.left_right_assignment_confidence is not None]
    lr = sum(left_right_confidence) / len(left_right_confidence) if left_right_confidence else .45
    period = math.pi if axial or (left_right and lr < .62) else 2 * math.pi
    values = [float(value) for _item, value in present]
    pts = [item.pts_sec for item, _value in present]
    roll = [item.camera_roll_rad for item, _value in present]
    roll_reliability = [item.camera_roll_reliability or 0 for item, _value in present]
    deltas: list[float] = []
    warnings: list[str] = []
    aliased_intervals = 0
    for index in range(1, len(values)):
        gap = pts[index] - pts[index - 1]
        if gap <= 0:
            continue
        delta = _wrap(values[index] - values[index - 1], period)
        if roll[index] is not None and roll[index - 1] is not None and min(roll_reliability[index], roll_reliability[index - 1]) >= .55:
            delta -= _wrap(float(roll[index]) - float(roll[index - 1]), 2 * math.pi)
        elif roll[index] is not None and roll[index - 1] is not None and abs(float(roll[index]) - float(roll[index - 1])) >= .08:
            warnings.append("camera_roll_unresolved")
        delta_turns = abs(delta) / (2 * math.pi)
        if gap > MAX_OBSERVABLE_GAP_SEC or delta_turns > MAX_UNALIASED_DELTA_TURNS or delta_turns / gap > MAX_YAW_RPS:
            aliased_intervals += 1
            warnings.append("signal_aliasing")
        deltas.append(delta)
    if not deltas:
        return _unobservable_signal(signal, phase, "insufficient_sampling")
    signed = sum(deltas)
    total = abs(signed) / (2 * math.pi)
    direction_agreement = abs(signed) / max(sum(abs(value) for value in deltas), 1e-9)
    visibility = sum((1 - item.occlusion) * (1 - .45 * item.blur) for item, _value in present) / len(present)
    pose = sum((item.pose_quality if item.pose_quality is not None else .55) for item, _value in present) / len(present)
    silhouette = sum((item.silhouette_confidence if item.silhouette_confidence is not None else .55) for item, _value in present) / len(present)
    base = silhouette if signal == "silhouette_orientation" else pose if signal in {"shoulder_orientation", "hip_orientation"} else .72
    if left_right:
        base *= .35 + .65 * lr
        if lr < .62:
            warnings.append("left_right_assignment_uncertain")
    reliability = base * visibility * (.55 + .45 * direction_agreement) * (1 - .55 * aliased_intervals / max(1, len(deltas)))
    reliability = max(0.0, min(1.0, reliability))
    uncertainty = .08 + (1 - reliability) * .30 + aliased_intervals * .25
    likelihoods = _signal_likelihoods(total, uncertainty)
    return _SignalWork(RotationSignalEstimate(
        signal=signal,
        phase=phase,
        estimate_turns=round(total, 5),
        interval_turns=(round(max(0.0, total - uncertainty), 5), round(total + uncertainty, 5)),
        class_likelihoods=likelihoods,
        reliability=round(reliability, 5),
        observability="observed" if reliability >= .55 and not warnings else "partial",
        sample_count=len(present),
        duration_sec=round(pts[-1] - pts[0], 6),
        warnings=tuple(dict.fromkeys(warnings)),
        provenance=tuple(dict.fromkeys(("source_pts", "confirmed_target", field, *(value for item, _ in present for value in item.provenance)))),
    ))


def _optical_flow_signal(samples: Sequence[RotationEvidenceSample], phase: RotationPhase) -> _SignalWork:
    present = [item for item in samples if item.optical_flow_rotation_rad is not None]
    if len(present) < 2:
        return _unobservable_signal("target_crop_optical_flow", phase, "signal_not_available")
    deltas = [float(item.optical_flow_rotation_rad) for item in present]
    pts = [item.pts_sec for item in present]
    warnings: list[str] = []
    aliased = 0
    for prior, current, delta in zip(present, present[1:], deltas[1:]):
        gap = current.pts_sec - prior.pts_sec
        if gap <= 0:
            continue
        delta_turns = abs(delta) / (2 * math.pi)
        if gap > MAX_OBSERVABLE_GAP_SEC or delta_turns > MAX_UNALIASED_DELTA_TURNS or delta_turns / gap > MAX_YAW_RPS:
            aliased += 1
            warnings.append("signal_aliasing")
    signed = sum(deltas)
    total = abs(signed) / (2 * math.pi)
    confidence = sum(item.optical_flow_confidence or 0 for item in present) / len(present)
    visibility = sum((1 - item.occlusion) * (1 - .5 * item.blur) for item in present) / len(present)
    camera_penalty = .45 if _camera_roll_unresolved(present) else 1.0
    if camera_penalty < 1:
        warnings.append("camera_roll_unresolved")
    direction_agreement = abs(signed) / max(sum(abs(value) for value in deltas), 1e-9)
    reliability = max(0.0, min(1.0, confidence * visibility * camera_penalty * (.55 + .45 * direction_agreement) * (1 - .55 * aliased / max(1, len(deltas) - 1))))
    uncertainty = .10 + (1 - reliability) * .34 + aliased * .25
    return _SignalWork(RotationSignalEstimate(
        signal="target_crop_optical_flow",
        phase=phase,
        estimate_turns=round(total, 5),
        interval_turns=(round(max(0.0, total - uncertainty), 5), round(total + uncertainty, 5)),
        class_likelihoods=_signal_likelihoods(total, uncertainty),
        reliability=round(reliability, 5),
        observability="observed" if reliability >= .55 and not warnings else "partial",
        sample_count=len(present),
        duration_sec=round(pts[-1] - pts[0], 6),
        warnings=tuple(dict.fromkeys(warnings)),
        provenance=("source_pts", "confirmed_target", "target_crop_optical_flow"),
    ))


def _unobservable_signal(signal: RotationSignalKind, phase: RotationPhase, warning: str) -> _SignalWork:
    return _SignalWork(RotationSignalEstimate(
        signal=signal,
        phase=phase,
        reliability=0,
        observability="unobservable",
        sample_count=0,
        warnings=(warning,),
        provenance=("refusal",),
    ))


def _phase_refusal(phase: RotationPhase, reason: RotationRefusalReason) -> RotationPhaseEstimate:
    return RotationPhaseEstimate(
        phase=phase,
        status="unobservable",
        confidence=0,
        observability="unobservable",
        refusal_reason=reason,
    )


def _refusal(
    event_id: str,
    profile: Profile,
    fingerprint: str,
    source_timeline_fingerprint: str,
    reason: RotationRefusalReason,
    subtype_support: float | None,
) -> RotationEstimate:
    return RotationEstimate(
        event_id=event_id,
        profile=profile,
        definition_version="airborne-body-rotation.source-pts.v1" if profile == "jump" else "observed-spin-rotation.source-pts.v1",
        status="unobservable",
        confidence=0,
        observability="unobservable",
        refusal_reason=reason,
        value_convention="airborne_body_rotation" if profile == "jump" else "observed_spin_rotation",
        subtype_support=subtype_support,
        evidence_summary=("画面不足，暂不判断",),
        warnings=(reason,),
        estimator_fingerprint=fingerprint,
        source_timeline_fingerprint=source_timeline_fingerprint,
    )


def _competition_naming(
    *, profile: Profile, subtype: str | None, subtype_support: float | None, class_turns: float | None,
) -> tuple[Literal["not_applied", "axel", "non_axel", "unknown"], float | None, str | None]:
    if profile != "jump" or class_turns is None:
        return "not_applied", None, None
    normalized = (subtype or "").strip().lower()
    if "axel" in normalized:
        if subtype_support is None or subtype_support < AXEL_SUBTYPE_SUPPORT_MIN:
            return "unknown", None, None
        name_by_turns = {1.5: "single_axel", 2.5: "double_axel", 3.5: "triple_axel", 4.5: "quad_axel"}
        return "axel", class_turns, name_by_turns.get(class_turns, f"axel_{class_turns:g}_turns")
    if subtype_support is None or subtype_support < AXEL_SUBTYPE_SUPPORT_MIN:
        return "unknown", None, None
    name_by_turns = {0.5: "half", 1.0: "single", 1.5: "one_and_half", 2.0: "double", 2.5: "two_and_half", 3.0: "triple", 4.0: "quad"}
    return "non_axel", class_turns, name_by_turns.get(class_turns, f"{class_turns:g}_turns")


def _camera_roll_unresolved(samples: Sequence[RotationEvidenceSample]) -> bool:
    roll = [(item.camera_roll_rad, item.camera_roll_reliability or 0) for item in samples if item.camera_roll_rad is not None]
    if len(roll) < 2:
        return False
    variation = max(float(value) for value, _ in roll) - min(float(value) for value, _ in roll)
    reliability = sum(value for _, value in roll) / len(roll)
    return variation >= .08 and reliability < .55


def _signal_likelihoods(estimate: float, uncertainty: float) -> dict[str, float]:
    sigma = max(.10, uncertainty)
    raw = {f"{candidate:g}": math.exp(-.5 * ((candidate - estimate) / sigma) ** 2) for candidate in CLASS_GRID}
    total = sum(raw.values()) or 1.0
    return {key: round(value / total, 6) for key, value in raw.items()}


def _fused_likelihoods(signals: Sequence[RotationSignalEstimate], weights: Sequence[float]) -> dict[str, float]:
    log_scores: dict[str, float] = {}
    for candidate in CLASS_GRID:
        key = f"{candidate:g}"
        log_scores[key] = sum(weight * math.log(max(signal.class_likelihoods.get(key, 1e-8), 1e-8)) for signal, weight in zip(signals, weights))
    peak = max(log_scores.values()) if log_scores else 0.0
    raw = {key: math.exp(value - peak) for key, value in log_scores.items()}
    total = sum(raw.values()) or 1.0
    return {key: value / total for key, value in raw.items()}


def _capped_weights(values: Sequence[float]) -> list[float]:
    total = sum(values)
    if total <= 0:
        return [0 for _ in values]
    weights = [value / total for value in values]
    for _ in range(8):
        excess = sum(max(0.0, value - SIGNAL_WEIGHT_CAP) for value in weights)
        if excess <= 1e-9:
            break
        weights = [min(value, SIGNAL_WEIGHT_CAP) for value in weights]
        uncapped = [index for index, value in enumerate(weights) if value < SIGNAL_WEIGHT_CAP - 1e-9]
        if not uncapped:
            break
        base = sum(weights[index] for index in uncapped)
        for index in uncapped:
            weights[index] += excess * (weights[index] / base if base else 1 / len(uncapped))
    return weights


def _nearest_half(value: float) -> float:
    return round(value * 2) / 2


def _signal_family(signal: RotationSignalKind) -> str:
    if signal in {"shoulder_orientation", "hip_orientation"}:
        return "pose_orientation"
    if signal == "target_crop_optical_flow":
        return "target_crop_motion"
    return "target_crop_appearance"


def _wrap(value: float, period: float) -> float:
    return (value + period / 2) % period - period / 2


def _fingerprint(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()
