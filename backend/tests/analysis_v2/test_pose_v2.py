from __future__ import annotations

import pytest

from app.analysis_v2.contracts import (
    JointObservation,
    PoseObservation,
    TrackState,
)
from app.analysis_v2.pose_v2 import (
    PoseProviderConfig,
    TargetCrop,
    build_target_crop,
    interpolate_pose_for_display,
    smooth_pose_observations,
)
from app.services.pose import get_pose_runtime_status


def _track(state: str = "confirmed") -> TrackState:
    return TrackState(
        state=state,
        bbox=(0.2, 0.2, 0.4, 0.8) if state == "confirmed" else None,
        identity_score=0.9 if state == "confirmed" else 0.1,
        bbox_source="measured" if state == "confirmed" else "none",
    )


def _pose(pts: float, x: float, *, track_state: str = "confirmed", scene_cut: bool = False) -> PoseObservation:
    blocked = track_state != "confirmed"
    joint = JointObservation(
        x=0 if blocked else x,
        y=0 if blocked else 0.4,
        confidence=0 if blocked else 0.9,
        visibility=0 if blocked else 0.9,
        provenance="identity-blocked" if blocked else "measured",
        source="identity-blocked" if blocked else "measured",
        raw_x=None if blocked else x,
        raw_y=None if blocked else 0.4,
        raw_confidence=None if blocked else 0.9,
        raw_visibility=None if blocked else 0.9,
    )
    return PoseObservation(
        source_video_hash="sha256:v",
        source_frame_index=round(pts * 30),
        pts_sec=pts,
        track_state=_track(track_state),
        identity_state=track_state,
        joints={"nose": joint},
        pose_quality=0.9 if not blocked else 0,
        authoritative=not blocked,
        scene_cut=scene_cut,
        source_method="test",
    )


def test_target_crop_requires_confirmed_measured_identity_and_maps_context() -> None:
    crop = build_target_crop(_track(), image_size=(1000, 500), context_margin=0.1)
    assert crop == TargetCrop(left=100, top=50, right=500, bottom=450, clipped=False, context_margin=0.1)
    assert build_target_crop(_track("uncertain"), image_size=(1000, 500), context_margin=0.1) is None


def test_interpolated_display_only_is_not_authoritative() -> None:
    frames = [_pose(0.0, 0.2), _pose(0.1, 0.4), _pose(0.2, 0.6)]
    frames[1] = frames[1].model_copy(update={"joints": {"nose": JointObservation(x=0, y=0, confidence=0, visibility=0, provenance="missing")}, "pose_quality": 0})
    output = interpolate_pose_for_display(frames, max_gap_sec=0.25)
    assert output[1].joints["nose"].provenance == "interpolated-display-only"
    assert output[1].authoritative is False


def test_smoothing_uses_pts_and_breaks_on_identity_scene_cut_and_large_gap() -> None:
    frames = [_pose(0.0, 0.0), _pose(0.1, 1.0), _pose(1.0, 3.0), _pose(1.1, 4.0, scene_cut=True), _pose(1.2, 5.0)]
    smoothed = smooth_pose_observations(frames, max_gap_sec=0.3, smoothing_tau_sec=0.2)
    assert smoothed[1].joints["nose"].provenance == "smoothed"
    assert 0 < smoothed[1].joints["nose"].x < 1
    assert smoothed[2].joints["nose"].provenance == "measured"
    assert smoothed[3].joints["nose"].provenance == "measured"


def test_uncertain_identity_has_no_authoritative_skeleton() -> None:
    blocked = _pose(0.2, 0.5, track_state="uncertain")
    assert blocked.authoritative is False
    assert all(joint.provenance == "identity-blocked" for joint in blocked.joints.values())


def test_provider_config_preserves_legacy_modes_and_fingerprint() -> None:
    config = PoseProviderConfig(num_poses=4, task_model_path="models/pose.task", context_margin=0.1)
    assert config.num_poses == 4
    assert config.fingerprint().startswith("sha256:")
    with pytest.raises(ValueError):
        PoseProviderConfig(num_poses=0)


def test_runtime_status_exposes_model_identity_and_pipeline_use(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKATING_ANALYSIS_PIPELINE", "shadow")
    monkeypatch.delenv("MEDIAPIPE_POSE_TASK_PATH", raising=False)
    status = get_pose_runtime_status()
    assert status["legacy_use"] is False
    assert status["v2_use"] is True
    assert status["fallback"] is True
    assert status["dependent_artifact_invalidation"] == "pose_v2_and_biomechanics_shadow_only"
