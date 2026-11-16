"""POSE-05: known motion/time/quality oracles; no real model or video decoding."""
import copy
import math
import sys
import types
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from app.services.smoothing import smooth_keypoint_sequence
from app.services import jump_features as jump


def trajectory(values, times=None):
    return [{"frame": f"frame_{i+1:04d}.jpg", "timestamp": times[i] if times is not None else i/15,
             "tracking_state": "tracked", "tracker_id": 7,
             "keypoints": [{"id": 27, "name": "left_ankle", "x": x, "y": .5, "z": 0., "visibility": .99}]}
            for i, x in enumerate(values)]


def xs(frames):
    return np.array([f["keypoints"][0]["x"] for f in frames])


@pytest.mark.parametrize("kind", ["constant_velocity", "acceleration", "deceleration", "reversal", "short_peak"])
def test_motion_fidelity(kind):
    t = np.arange(41)/15
    if kind == "constant_velocity": values = .2 + .15*t
    elif kind == "acceleration": values = .2 + .05*t*t
    elif kind == "deceleration": values = .2 + .3*t - .05*t*t
    elif kind == "reversal": values = .5 - .015*np.abs(np.arange(41)-20)
    else: values = .2 + .1*np.exp(-((np.arange(41)-20)/2)**2)
    out = xs(smooth_keypoint_sequence(trajectory(values), 15.))
    if kind in {"constant_velocity", "acceleration", "deceleration"}:
        # Exact low-degree known motion, normalized error below 1/100 of one step.
        assert np.max(np.abs(out-values)) < 1e-4
    else:
        assert int(np.argmax(out)) == int(np.argmax(values))
        assert abs(out[20]-values[20]) < .01  # < 2/3 one-sample reversal step, <10% peak amplitude
        assert np.max(np.abs(out-values)) < .01


def test_stationary_noise_reduction_and_input_immutability():
    rng = np.random.default_rng(9021)
    values = .5 + rng.normal(0, .005, 201)
    source = trajectory(values); saved = copy.deepcopy(source)
    result = smooth_keypoint_sequence(source, 15.)
    # Meaningful noise energy reduction, not merely current-frame pass-through.
    assert np.sqrt(np.mean((xs(result)[2:-2]-.5)**2)) < np.std(values[2:-2])*.85
    assert source == saved
    assert result[5]["keypoints"][0]["quality"]["processing_version"] == "pose-temporal.v2"


def test_irregular_actual_times_preserve_linear_motion():
    times = [0., .02, .08, .12, .21, .28, .31, .4, .48]
    values = [.2+.3*t for t in times]
    result = smooth_keypoint_sequence(trajectory(values, times), 999.)
    assert np.max(np.abs(xs(result)-values)) < 1e-5
    assert result[3]["temporal"]["analysis_timestamp"] == pytest.approx(times[3])
    assert result[3]["temporal"]["time_source"] == "frame_timestamp"


@pytest.mark.parametrize("bad_time", [None, float("nan"), .1, .05, 2.])
def test_invalid_clock_does_not_cross_filter_or_fill(bad_time):
    frames = trajectory([.1, .1, .9, .9, .9], [0., .1, bad_time, 2.1, 2.2])
    frames[2]["keypoints"][0]["visibility"] = 0.
    result = smooth_keypoint_sequence(frames, 15.)
    assert not result[2]["keypoints"][0].get("interpolated", False)
    assert result[2]["keypoints"][0]["quality"]["analysis_usable"] is False
    assert xs(result)[1] == pytest.approx(.1)
    assert xs(result)[3] == pytest.approx(.9)


@pytest.mark.parametrize("barrier", ["empty", "lost", "identity", "untrusted_binding", "low_confidence"])
def test_target_discontinuity_is_a_filter_and_interpolation_barrier(barrier):
    frames = trajectory([.1, .1, .9, .9, .9])
    if barrier == "empty": frames[2]["keypoints"] = []
    elif barrier == "lost": frames[2]["tracking_state"] = "lost"
    elif barrier == "identity": frames[2]["tracker_id"] = 8
    elif barrier == "low_confidence": frames[2]["tracking_state"] = "low_confidence"
    else: frames[2]["input_binding_valid"] = False
    result = smooth_keypoint_sequence(frames, 15.)
    assert result[1]["keypoints"][0]["x"] == pytest.approx(.1)
    assert result[3]["keypoints"][0]["x"] == pytest.approx(.9)
    assert result[1]["temporal"]["segment_id"] != result[3]["temporal"]["segment_id"]


def test_interpolation_uses_time_retains_raw_quality_and_is_display_only():
    frames = trajectory([.2, .99, .5], [0., .03, .3])
    frames[1]["keypoints"][0]["visibility"] = 0.
    out = smooth_keypoint_sequence(frames, 15.)[1]["keypoints"][0]
    assert out["x"] == pytest.approx(.23)
    assert out["visibility"] == 0.
    assert out["interpolated"] is True
    assert out["quality"]["source"] == "display_interpolation"
    assert out["quality"]["raw_coordinates"]["x"] == .99
    assert out["quality"]["analysis_usable"] is False


def test_nonfinite_coordinates_and_sparse_ids_never_become_zero_or_wrong_joint():
    frames = trajectory([.2]*5)
    frames[2]["keypoints"][0]["x"] = float("nan")
    frames[2]["keypoints"][0]["y"] = None
    out = smooth_keypoint_sequence(frames, 15.)
    assert all(f["keypoints"][0]["id"] == 27 for f in out)
    assert out[2]["keypoints"][0]["quality"]["analysis_usable"] is False
    assert out[2]["keypoints"][0]["quality"]["raw_coordinates"]["y"] is None
    assert out[2]["keypoints"][0]["x"] != 0.


def test_legacy_no_pts_is_explicit_compatibility_and_unknown_is_not_fallback():
    frames = trajectory([.2, .3, .4])
    for f in frames: f.pop("timestamp")
    out = smooth_keypoint_sequence(frames, 5.)
    assert out[1]["temporal"]["time_source"] == "legacy_effective_fps"
    frames[1]["timestamp"] = None
    out = smooth_keypoint_sequence(frames, 5.)
    assert out[1]["temporal"]["analysis_timestamp"] is None


def test_jump_rejects_interpolation_even_high_visibility_and_keeps_native_source():
    pts = [{"id": i, "x": .3, "y": .5, "z": 0., "visibility": .99} for i in range(33)]
    for vis in (0., .2, .99):
        pts[27].update(visibility=vis, interpolated=True)
        assert jump._keypoint(pts, 27) is None
    pts[27].update(visibility=.99, interpolated=False, quality={"source": "smoothed_native", "analysis_usable": True})
    assert jump._keypoint(pts, 27)["quality"]["source"] == "smoothed_native"
    pts[27]["quality"]["analysis_usable"] = False
    assert jump._keypoint(pts, 27) is None


def test_jump_missing_ankles_cannot_fabricate_toe_pulse_by_compressing_gap():
    frames = []
    for i, y in enumerate([.3, .4, .9, .3]):
        pts = [{"id": j, "x": .4+j*.001, "y": y, "z": 0., "visibility": .99} for j in range(33)]
        if i == 2:
            for j in (27, 28): pts[j].update(visibility=0., interpolated=True)
        frames.append({"frame": f"frame_{i+1:04d}.jpg", "keypoints": pts})
    result = jump.compute_jump_evidence({"frames": frames}, {"T": "frame_0004.jpg"}, 15.)
    assert result["toe_pick_pulse"] is False
    assert "jump_contact_evidence_incomplete" in result["quality_flags"]
    assert result["point_quality"]["excluded_interpolated"] == 2


@pytest.mark.parametrize("smoothing_failure", [False, True])
def test_production_fake_model_time_quality_and_json_readback(tmp_path, monkeypatch, smoothing_failure):
    from app.services import pose
    from app.routers.analysis import _build_pose_response
    from app.schemas import PoseResponse
    for i in range(5): (tmp_path/f"frame_{i+1:04d}.jpg").write_bytes(b"synthetic")
    class FakePose:
        def __init__(self, **kwargs): pass
        def close(self): pass
        def process(self, image):
            landmarks = [types.SimpleNamespace(x=.4+(i%2)*.1, y=.2+(i/33)*.5, z=0., visibility=.99) for i in range(33)]
            return types.SimpleNamespace(pose_landmarks=types.SimpleNamespace(landmark=landmarks))
    monkeypatch.setitem(sys.modules, "mediapipe", types.SimpleNamespace(solutions=types.SimpleNamespace(pose=types.SimpleNamespace(Pose=FakePose))))
    monkeypatch.setattr(pose, "_resolve_tasks_landmarker", lambda: None)
    import cv2
    monkeypatch.setattr(cv2, "imread", lambda _: np.zeros((100, 100, 3), dtype=np.uint8))
    # Keep real production extraction/mapping/postprocessing; only isolate target scoring.
    monkeypatch.setattr(pose, "_candidate_rejection_reasons", lambda *a, **k: [])
    records = [{"frame_id": f"frame_{i+1:04d}", "timestamp": t} for i, t in enumerate([1., 1.02, 1.1, 1.2, 1.3])]
    if smoothing_failure:
        monkeypatch.setattr(pose, "smooth_keypoint_sequence", lambda *a: (_ for _ in ()).throw(RuntimeError("synthetic postprocessing failure")))
    result = pose.extract_pose(str(tmp_path), effective_fps=99., frame_times=records, slow_motion_scale=2.)
    assert all(f["keypoints"] for f in result["frames"])
    assert all(f["projection_geometry"] == {"schema_version":"pose-projection.v1", "coordinate_space":"full_image_normalized", "image_width":100, "image_height":100, "provenance":"landmarks_mapped_to_full_image"} for f in result["frames"])
    for f, r in zip(result["frames"], records):
        assert f["timestamp"] == r["timestamp"]
        assert f["temporal"]["analysis_timestamp"] == pytest.approx(r["timestamp"]/2)
        if smoothing_failure:
            assert f["keypoints"][0]["quality"]["source"] == "postprocessing_failed"
            assert f["keypoints"][0]["quality"]["analysis_usable"] is False
        else:
            assert f["keypoints"][0]["quality"]["raw_visibility"] == .99
    import json
    saved = json.loads(json.dumps(result))  # same JSON column serialization as saved pose_data
    response = _build_pose_response("synthetic", saved, {"selected": records})
    readback = PoseResponse.model_validate(response.model_dump()).model_dump()
    assert readback["frames"][2]["keypoints"][0]["quality"] == saved["frames"][2]["keypoints"][0]["quality"]
    assert readback["frames"][2]["temporal"] == saved["frames"][2]["temporal"]
    assert readback["frames"][2]["projection_geometry"] == saved["frames"][2]["projection_geometry"]


@pytest.mark.parametrize("mutation", ["valid", "hash", "duplicate_selected", "missing_time", "different_pts"])
def test_exact_bound_frame_timing_never_nearest_or_fps(tmp_path, mutation):
    import hashlib
    from app.services.pose import _attach_pose_frame_times
    path = tmp_path/"frame_0001.jpg"; path.write_bytes(b"synthetic-bound-image")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    binding = {"frame": path.name, "frame_id": path.stem, "observation_index": 2, "sha256": sha,
               "source_pts": 210, "source_time_base": "1/100"}
    diagnostic = {"frame_index": 0, "state": "tracked", "input_binding_valid": True,
                  "observation_index": 2, "source_pts": 210, "timestamp": 2.1, "tracker_id": 9}
    selected = [{"frame_id": path.stem, "sha256": sha, "timestamp": 2.1}]
    if mutation == "hash": binding["sha256"] = "0"*64
    elif mutation == "duplicate_selected": selected.append(dict(selected[0]))
    elif mutation == "missing_time": selected[0]["timestamp"] = None
    elif mutation == "different_pts": diagnostic["source_pts"] = 211
    frames = trajectory([.4])
    _attach_pose_frame_times(frames, [path], {"pose_frame_bindings": [binding], "person_tracker_diagnostics": [diagnostic]}, selected, 999., 3.)
    temporal = frames[0]["temporal"]
    if mutation == "valid":
        assert temporal["analysis_timestamp"] == pytest.approx(.7)
        assert temporal["time_source"] == "bound_source_pts"
        assert temporal["binding"]["sha256"] == sha
        assert frames[0]["tracker_id"] == 9
    else:
        assert temporal["analysis_timestamp"] is None
        assert frames[0]["input_binding_valid"] is False


def test_clock_unknown_keeps_current_native_display_but_no_temporal_evidence():
    frames = trajectory([.2, .3, .4], [0., None, .2])
    out = smooth_keypoint_sequence(frames, 15.)
    assert out[1]["keypoints"][0]["x"] == .3
    assert out[1]["keypoints"][0]["quality"]["analysis_usable"] is False
    assert out[1]["keypoints"][0]["quality"]["source"] == "native_observation"


def test_timed_production_lost_frame_never_whole_frame_interpolates():
    from app.services.pose import _apply_short_gap_interpolation
    frames = trajectory([.2, .3, .4])
    frames[1].update(tracking_state="lost", keypoints=[])
    smooth = smooth_keypoint_sequence(frames, 15.)
    count, lost = _apply_short_gap_interpolation(smooth, [{}, {}, {}])
    assert (count, lost) == (0, 1)
    assert smooth[1]["keypoints"] == []


def test_new_quality_gate_reaches_biomechanics_without_changing_legacy():
    from app.services.biomechanics import _point
    points = [{"id": 0, "x": .2, "y": .3, "z": 0., "visibility": .4}]
    assert _point(points, 0) is not None
    points[0]["quality"] = {"analysis_usable": False, "source": "low_visibility"}
    assert _point(points, 0) is None



def test_jump_new_temporal_window_uses_analysis_time_and_never_crosses_segment():
    frames = trajectory([.2]*6, [0., .01, .04, .16, .19, .3])
    output = smooth_keypoint_sequence(frames, 999.)
    window = jump._sample_window(output, 5, 999., .15)
    assert [i for i, _ in window] == [3, 4, 5]
    output[4]["temporal"]["segment_id"] = 6
    assert [i for i, _ in jump._sample_window(output, 5, 999., .15)] == [5]


@pytest.mark.parametrize("bad_z", [None, float("nan"), float("inf")])
def test_invalid_depth_never_becomes_contact_evidence_or_crashes_consumer(bad_z):
    from app.services.biomechanics import _point
    point = {"id": 0, "x": .2, "y": .3, "z": bad_z, "visibility": .9}
    assert _point([point], 0) is None
    assert jump._keypoint([point], 0) is None


def test_new_and_legacy_saved_pose_sqlite_and_http_readback(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from app import models
    from app.routers import analysis as router
    get_session = router.get_session
    engine = create_engine("sqlite:///"+str(tmp_path/"saved-pose.db"))
    models.Analysis.metadata.create_all(engine)
    new = {"connections": [], "frames": smooth_keypoint_sequence(trajectory([.2]*5), 15.)}
    # Unfillable low-visibility coordinates must survive JSON/schema as null.
    new["frames"][0]["keypoints"][0].update(x=None, y=None, z=None, visibility=0., interpolated=False,
        quality={"source": "missing", "analysis_usable": False, "processing_version": "pose-temporal.v2"})
    legacy = {"connections": [], "frames": trajectory([.2])}
    for f in legacy["frames"]: f.pop("timestamp")
    with Session(engine) as session:
        for name, data in (("new-saved", new), ("legacy-saved", legacy)):
            session.add(models.Analysis(id=name, action_type="jump", status="completed", video_path="never-open.mp4", pose_data=data))
        session.commit()
    with Session(engine) as session:
        rows = {name: session.scalar(select(models.Analysis).where(models.Analysis.id == name))
                for name in ("new-saved", "legacy-saved")}
        assert rows["new-saved"].pose_data == new
        assert rows["legacy-saved"].pose_data == legacy
        fake_session = AsyncMock()
        fake_session.get.side_effect = lambda model, name: rows[name]
        async def override_db(): yield fake_session
        app = FastAPI(); app.include_router(router.router)
        app.dependency_overrides[get_session] = override_db
        with patch.object(router, "trial_profile", return_value="legacy-analysis-preview"), \
             patch.object(router, "extract_pose", side_effect=AssertionError("inference forbidden")), \
             patch.object(router, "_restore_missing_analysis_frames", side_effect=AssertionError("backfill forbidden")), \
             TestClient(app) as client:
            payload = client.get("/api/analysis/new-saved/pose").json()
            assert payload["frames"][2]["temporal"] == new["frames"][2]["temporal"]
            assert payload["frames"][2]["keypoints"][0]["quality"] == new["frames"][2]["keypoints"][0]["quality"]
            assert payload["frames"][0]["keypoints"][0]["x"] is None
            old = client.get("/api/analysis/legacy-saved/pose").json()
            assert old["frames"][0]["keypoints"][0]["quality"] is None
        fake_session.commit.assert_not_awaited()
        assert rows["legacy-saved"].pose_data == legacy
    engine.dispose()
