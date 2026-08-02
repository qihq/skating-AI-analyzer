from app.analysis_v2.contracts import TrackCandidate
from app.analysis_v2.detection import build_proposal_diagnostics, estimate_camera_motion, estimate_camera_motion_from_matches, preserve_short_tracks, score_candidate_quality
from app.analysis_v2.detection import resolve_provider_config


def test_camera_pan_is_reliable_and_deterministic() -> None:
    result = estimate_camera_motion([(0, 0), (10, 0), (20, 0)], [(5, 0), (15, 0), (25, 0)])
    assert result.motion_type == "pan"
    assert result.reliability > 0
    assert result == estimate_camera_motion([(0, 0), (10, 0), (20, 0)], [(5, 0), (15, 0), (25, 0)])


def test_camera_failure_lowers_reliability() -> None:
    result = estimate_camera_motion([], [])
    assert result.reliability == 0
    assert result.failure_reason


def test_quality_ranks_anchor_candidates() -> None:
    quality = score_candidate_quality((10, 10, 90, 190), (200, 200), blur=1.0)
    candidate = TrackCandidate(candidate_id="c1", bbox=(10, 10, 90, 190), detector_score=0.8, quality_score=quality.quality_score)
    diagnostics = build_proposal_diagnostics(candidates=[candidate])
    assert diagnostics.anchor_suggestions == ("c1",)
    assert diagnostics.invalidation_scope == "shadow_diagnostics_only"


def test_crossing_and_detector_dropout_remain_distinct_uncertain_tracks() -> None:
    tracks = preserve_short_tracks([
        {"candidate_id": "left", "short_track_id": "track-left", "source_frame_indices": [0, 1, 3], "pts_sec": [0, .04, .12], "boxes": [(0, 0, 10, 20)] * 3, "detector_scores": [.9, .8, .7], "uncertainty": ["detector_miss_at_frame_2"]},
        {"candidate_id": "right", "short_track_id": "track-right", "source_frame_indices": [0, 1, 2, 3], "pts_sec": [0, .04, .08, .12], "boxes": [(20, 0, 30, 20)] * 4, "detector_scores": [.8] * 4, "uncertainty": ["crossing_overlap"]},
    ])
    assert [track.short_track_id for track in tracks] == ["track-left", "track-right"]
    assert "detector_miss_at_frame_2" in tracks[0].uncertainty


def test_masked_background_feature_failure_is_soft() -> None:
    result = estimate_camera_motion_from_matches([], masked=5)
    assert result.reliability == 0
    assert result.motion_type == "unknown"


def test_provider_model_source_states_are_explicit(tmp_path) -> None:
    missing = resolve_provider_config({"YOLO_PERSON_MODEL_PATH": str(tmp_path / "missing.pt")})
    assert missing.model_source == "missing"
    assert missing.model_hash is None
    default = resolve_provider_config({})
    assert default.model_source in {"default", "mounted", "downloaded", "missing", "unknown"}
