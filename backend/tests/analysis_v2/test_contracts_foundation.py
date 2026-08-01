import pytest
from pydantic import ValidationError

from app.analysis_v2.contracts import (
    ActionEvent,
    EvidenceClaim,
    FrameObservation,
    JointObservation,
    PoseObservation,
    TrackState,
    adapt_legacy_key_moments,
    adapt_legacy_pose_observations,
    adapt_legacy_sampled_frames,
    adapt_legacy_track_states,
)


def test_frame_observation_round_trip_is_deterministic():
    frame = FrameObservation(
        source_video_hash="sha256:video",
        source_frame_index=3,
        pts_sec=0.5,
        duration_sec=0.04,
        image_size=(1920, 1080),
        pipeline_version="v2.test",
    )
    assert FrameObservation.model_validate_json(frame.model_dump_json()).model_dump() == frame.model_dump()
    assert frame.canonical_json() == frame.canonical_json()


def test_confirmed_track_requires_valid_bbox():
    with pytest.raises(ValidationError):
        TrackState(state="confirmed", bbox=None, identity_score=0.9)
    with pytest.raises(ValidationError):
        TrackState(state="confirmed", bbox=(1, 2, 1, 4), identity_score=0.9)


def test_interpolated_joint_cannot_claim_measured():
    with pytest.raises(ValidationError):
        JointObservation(x=0.2, y=0.3, confidence=0.8, provenance="interpolated", source="measured")


def test_contract_rejects_invalid_pts_confidence_and_coordinate_space():
    with pytest.raises(ValidationError):
        FrameObservation(source_video_hash="x", source_frame_index=0, pts_sec=-1, duration_sec=0.1, image_size=(1, 1), pipeline_version="x")
    with pytest.raises(ValidationError):
        EvidenceClaim(claim_type="rotation", value=1, confidence=1.2, observability="observed", status="confirmed")
    with pytest.raises(ValidationError):
        JointObservation(x=1, y=2, confidence=0.5, provenance="measured", coordinate_space="world")


def test_action_event_requires_ordered_interval_and_observability():
    with pytest.raises(ValidationError):
        ActionEvent(event_id="e", profile="jump", start_pts_sec=2, end_pts_sec=1, confidence=0.5, observability="observed")


def test_legacy_shadow_adapters_are_read_only_and_explicitly_approximate():
    legacy = {
        "frames": [{"frame_id": "frame_0001", "frame_index": 4, "timestamp": 0.2, "width": 1280, "height": 720}],
        "tracks": [{"frame_index": 4, "bbox": [10, 20, 100, 200], "confidence": 0.7}],
        "poses": [{"frame_index": 4, "timestamp": 0.2, "joints": {"nose": {"x": 0.5, "y": 0.2, "confidence": 0.8}}}],
        "key_frames": {"takeoff": "frame_0001"},
        "key_frame_timestamps": {"takeoff": 0.2},
    }
    before = __import__("copy").deepcopy(legacy)

    frames = adapt_legacy_sampled_frames(legacy["frames"], source_video_hash="sha256:v", pipeline_version="legacy:v5")
    tracks = adapt_legacy_track_states(legacy["tracks"])
    poses = adapt_legacy_pose_observations(legacy["poses"], source_video_hash="sha256:v", tracks=tracks)
    moments = adapt_legacy_key_moments(legacy["key_frames"], legacy["key_frame_timestamps"], event_id="e")

    assert frames[0].timing_provenance == "legacy_approximate"
    assert tracks[0].reasons == ("legacy_shadow_adapter",)
    assert poses[0].joints["nose"].provenance == "measured"
    assert moments[0].warnings == ("legacy_approximate_timing",)
    assert legacy == before
