"""Offline TAL production-contract regressions; no material-specific labels."""
import copy
import pytest
from app.services import keyframe_candidates as kc
from app.services.jump_features import compute_jump_evidence
from app.services.biomechanics import attach_key_frame_candidates
from test_analysis_keyframe_candidates import _pose_data, _motion_scores


def inputs():
    return _pose_data(), _motion_scores()


@pytest.mark.parametrize("fields", [
    {"quality": {"analysis_usable": False}},
    {"quality": {"limb_consistency": {"status": "uncertain"}}},
    {"interpolated": True}, {"quality": {"source": "display_interpolation"}},
    {"x": None}, {"y": float("nan")}, {"z": float("inf")},
])
def test_rejected_pose_cannot_support_candidates(fields):
    pose, _ = inputs()
    for f in pose["frames"]:
        for p in f["keypoints"]: p.update(copy.deepcopy(fields))
    result = kc.detect_key_frame_candidates(pose, None, "jump", 10.)
    assert all(result[k]["frame_id"] is None for k in ("T", "A", "L"))


def test_smoothing_and_windows_preserve_holes(monkeypatch):
    for flag in ("0", "1"):
        monkeypatch.setenv("KEYFRAME_ONE_EURO_SMOOTHING", flag)
        out = kc._smooth([1., None, 100.], fps=10.)
        assert out == [1., None, 100.]
    assert kc._window_values([1., None, 100.], 2, 2, 0) == [100.]


@pytest.mark.parametrize("anchor", [{}, {"T": "unknown99"}, {"T": "prefix_frame_0003"}, {"T": "other_0003.jpg"}])
def test_missing_or_numeric_collision_anchor_is_unavailable(anchor):
    pose, _ = inputs()
    e = compute_jump_evidence(pose, anchor, 10.)
    assert e["anchor"]["status"] == "unavailable"
    assert e["takeoff_foot"] == "unknown"
    assert e["toe_pick_pulse"] is None
    assert e["feet_together_at_takeoff"] is None
    assert e["pre_takeoff_edge_score"] is None


@pytest.mark.parametrize("defect", ["duplicate", "rejected", "time", "binding"])
def test_anchor_validation(defect):
    pose, _ = inputs(); anchor = {"T": {"frame_id": "frame_0003", "timestamp": .2}}
    for i, f in enumerate(pose["frames"]): f["timestamp"] = i/10
    if defect == "duplicate": pose["frames"].append(copy.deepcopy(pose["frames"][2]))
    if defect == "rejected":
        for p in pose["frames"][2]["keypoints"]: p["quality"] = {"analysis_usable": False}
    if defect == "time": anchor["T"]["timestamp"] = .7
    if defect == "binding": pose["frames"][2]["input_binding_valid"] = False
    assert compute_jump_evidence(pose, anchor, 10.)["anchor"]["status"] == "unavailable"


@pytest.mark.parametrize("quality", [None, {"analysis_usable": True, "source": "native_observation"}])
def test_valid_stages_have_support_and_no_invented_measurements(quality):
    pose, motion = inputs()
    if quality:
        for f in pose["frames"]:
            for p in f["keypoints"]: p["quality"] = quality
    result = attach_key_frame_candidates({"key_frames": {"T": "frame_0009"}}, pose, motion, "jump", 10.)
    stages = result["jump_stages"]
    for k in ("takeoff", "apex", "landing"):
        s = stages[k]
        assert s["status"] == "candidate"
        assert s["frame_id"] and s["image_ref"]["frame_id"] == s["frame_id"]
        assert s["source"] == "key_frame_candidates"
        assert s["evidence"]["support_frames"]
    for k in ("pull-in", "rotation"):
        assert stages[k]["status"] == "unavailable" and stages[k]["frame_id"] is None
    assert result["jump_measurements"]["physical_height"]["value"] is None
    assert result["jump_measurements"]["air_time"]["value"] is None
    evidence = compute_jump_evidence(pose, result["jump_stage_anchors"], 10.)
    assert evidence["anchor"]["frame_id"] == stages["takeoff"]["frame_id"]
    assert evidence["anchor"]["frame_id"] != "frame_0009"


def test_step_is_not_applicable():
    pose, motion = inputs()
    b = attach_key_frame_candidates({}, pose, motion, "step", 10.)
    assert all(s["status"] == "not_applicable" and s["frame_id"] is None for s in b["jump_stages"].values())


@pytest.mark.parametrize("defect", ["lost", "binding", "relock", "identity", "segment", "duplicate_time", "reverse_time", "gap", "missing", "empty", "point_hole"])
def test_candidate_support_does_not_bridge_boundaries(defect):
    pose, motion = inputs()
    for i,f in enumerate(pose["frames"]): f["timestamp"] = i/10
    f = pose["frames"][4]
    if defect == "lost": f["tracking_state"] = "lost"
    if defect == "binding": f["input_binding_valid"] = False
    if defect == "relock": f["tracker_state"] = "relocked"
    if defect == "identity":
        for x in pose["frames"][4:]: x["identity_id"] = "second"
    if defect == "segment":
        for i,x in enumerate(pose["frames"]): x["temporal"] = {"segment_id": int(i>=4), "analysis_timestamp": i/10}
    if defect in ("duplicate_time", "reverse_time"): f["timestamp"] = .3 if defect == "duplicate_time" else .2
    if defect == "gap":
        for x in pose["frames"][4:]: x["timestamp"] += 2
    if defect == "missing": pose["frames"].pop(4); motion["selected"].pop(4)
    if defect == "empty": f["keypoints"] = []
    if defect == "point_hole": f["keypoints"][27]["quality"] = {"analysis_usable": False}
    # Source times take priority over sampling-array positions.
    motion = None
    r = kc.detect_key_frame_candidates(pose, motion, "jump", 10.)
    refs = [c["evidence"].get("support_frames", []) for k,c in r.items() if k in ("T", "A", "L") and c["frame_id"]]
    assert refs
    for support in refs:
        assert support
        indices = {x["pose_index"] for x in support}
        assert not (any(i<4 for i in indices) and any(i>4 for i in indices))


def test_motion_only_never_claims_pose_or_contact():
    pose, motion = inputs()
    for f in pose["frames"]:
        for p in f["keypoints"]: p["quality"] = {"analysis_usable": False}
    b = attach_key_frame_candidates({}, pose, motion, "jump", 10.)
    assert any(b["key_frame_candidates"][k]["frame_id"] for k in ("T", "A", "L"))
    for k in ("T", "A", "L"):
        c = b["key_frame_candidates"][k]
        if c["frame_id"]:
            assert c["evidence"]["signal_source"] == "motion_only"
            assert c["evidence"]["support_point_ids"] == []
    assert b["jump_stage_anchors"]["T"]["status"] == "unavailable"


def test_formal_window_cannot_borrow_before_candidate_support():
    from app.services import jump_features as jf
    pose, _ = inputs()
    support = [{"pose_index": i, "frame_id": f["frame"].split(".")[0], "timestamp": i / 10} for i, f in enumerate(pose["frames"]) if 2 <= i <= 4]
    for i, f in enumerate(pose["frames"]): f["timestamp"] = i / 10
    anchor = {"T": {"frame_id": "frame_0005", "timestamp": .4,
                    "evidence": {"signal_source": "pose_geometry", "support_frames": support}}}
    evidence = jf.compute_jump_evidence(pose, anchor, 10.)
    assert evidence["anchor"]["status"] == "available"
    assert evidence["window_support"]["approach"] == ["frame_0003", "frame_0004", "frame_0005"]


@pytest.mark.parametrize("defect", ["duplicate_time", "reverse_time", "bad_support"])
def test_anchor_rejects_broken_time_or_support(defect):
    pose, _ = inputs()
    for i, f in enumerate(pose["frames"]): f["timestamp"] = i / 10
    a = {"frame_id": "frame_0003", "timestamp": .2}
    if defect == "duplicate_time": pose["frames"][1]["timestamp"] = .2
    if defect == "reverse_time": pose["frames"][1]["timestamp"] = .3
    if defect == "bad_support": a["evidence"] = {"support_frames": [{"frame_id": "missing", "timestamp": 0.}]}
    assert compute_jump_evidence(pose, {"T": a}, 10.)["anchor"]["status"] == "unavailable"


def test_valid_unique_legacy_stem_remains_compatible_through_stage_contract():
    from app.services.jump_stages import attach_jump_stages
    pose, _ = inputs()
    b = attach_jump_stages({"key_frames": {"T": "frame_0003.jpg"}}, pose, None, "jump")
    assert compute_jump_evidence(pose, b["jump_stage_anchors"], 10.)["anchor"]["status"] == "available"


def test_sparse_reordered_point_ids_and_duplicate_point_rejection():
    pose, motion = inputs()
    expected = kc.detect_key_frame_candidates(pose, motion, "jump", 10.)
    for f in pose["frames"]: f["keypoints"] = list(reversed([p for p in f["keypoints"] if p["id"] in (11,12,23,24,25,26,27,28)]))
    reordered = kc.detect_key_frame_candidates(pose, motion, "jump", 10.)
    assert [reordered[k]["frame_id"] for k in ("T","A","L")] == [expected[k]["frame_id"] for k in ("T","A","L")]
    for f in pose["frames"]: f["keypoints"].extend(copy.deepcopy([p for p in f["keypoints"] if p["id"] == 23]))
    b = attach_key_frame_candidates({}, pose, None, "jump", 10.)
    assert all(b["jump_stages"][k]["frame_id"] is None for k in ("takeoff","apex","landing"))


def timed_pose(scale=2.):
    pose, motion = inputs()
    for i, f in enumerate(pose["frames"]):
        for point in f["keypoints"]:
            point["name"] = f"landmark_{point['id']}"
        playback = i / 10
        f["timestamp"] = playback
        f["temporal"] = {"time_source": "bound_source_pts", "playback_timestamp": playback,
            "analysis_timestamp": playback / scale, "slow_motion_scale": scale, "segment_id": 0,
            "binding": {"source_pts": i, "source_time_base": "1/10"}}
    return pose, motion


def test_slow_motion_uses_analysis_axis_and_candidate_interval_is_not_airtime():
    pose, motion = timed_pose()
    b = attach_key_frame_candidates({"jump_metrics": {"jump_height_cm": 73}}, pose, motion, "jump", 20.)
    assert all(b["jump_stages"][n]["status"] == "candidate" for n in ("takeoff", "apex", "landing"))
    t, l = b["jump_stages"]["takeoff"], b["jump_stages"]["landing"]
    assert t["source_timestamp"] == pytest.approx(t["playback_timestamp"])
    assert t["source_timestamp"] == pytest.approx(t["timestamp"] * 2)
    m = b["jump_measurements"]
    assert m["candidate_interval"]["value"] == l["timestamp"] - t["timestamp"]
    assert m["air_time"]["value"] is None and b["jump_metrics"] is None
    assert m["physical_height"]["value"] is None and m["horizontal_distance"]["value"] is None


@pytest.mark.parametrize("defect", ["pts", "scale", "source_time_base"])
def test_bound_time_contract_cannot_be_repaired_from_array(defect):
    pose, motion = timed_pose()
    for f in pose["frames"]:
        if defect == "pts": f["temporal"]["binding"]["source_pts"] += 10
        if defect == "scale": f["temporal"]["slow_motion_scale"] = None
        if defect == "source_time_base": f["temporal"]["binding"]["source_time_base"] = "0/0"
    b = attach_key_frame_candidates({}, pose, motion, "jump", 20.)
    assert b["jump_stages"]["takeoff"]["status"] == "unavailable"
    assert b["jump_measurements"]["candidate_interval"]["value"] is None


def test_candidate_rejection_never_falls_back_to_legacy_labels():
    from app.services.jump_stages import attach_jump_stages
    pose, _ = inputs()
    b = attach_jump_stages({"key_frames": {"T": "frame_0003"}, "key_frame_candidates": {"T": {"frame_id": "missing"}}}, pose, None, "jump")
    assert b["jump_stage_anchors"]["T"]["status"] == "unavailable"
    assert compute_jump_evidence(pose, b["jump_stage_anchors"], 10.)["toe_pick_pulse"] is None


def test_smoothing_uses_actual_time_when_enabled(monkeypatch):
    times = []
    class Filter:
        def __init__(self, **kw): pass
        def filter(self, value, timestamp): times.append(timestamp); return value
    monkeypatch.setattr(kc, "OneEuroFilter", Filter)
    monkeypatch.setenv("KEYFRAME_ONE_EURO_SMOOTHING", "1")
    kc._smooth([1., 2., 3.], fps=10., timestamps=[1., 1.06, 1.18])
    assert times == [1., 1.06, 1.18]


# Keep the old heuristic assertions intact while checking the actual public
# detector against their sparse, occluded and low-visibility input fixtures.
import test_keyframe_candidates as legacy_candidates


@pytest.mark.parametrize("name", [name for name in dir(legacy_candidates.KeyframeCandidateTests)
    if name.startswith("test_") and "detect_key_frame_candidates" in
    getattr(legacy_candidates.KeyframeCandidateTests, name).__code__.co_names])
def test_production_contract_on_legacy_sparse_and_occluded_fixtures(name, monkeypatch):
    import test_keyframe_candidates as legacy
    from app.services.pose_observations import frame_usable, _frame_key
    captured = []
    production_detector = kc.detect_key_frame_candidates
    def record(*args, **kwargs):
        captured.append(args)
        return kc._detect_contiguous_candidates(*args, **kwargs)
    monkeypatch.setattr(legacy, "detect_key_frame_candidates", record)
    monkeypatch.setattr(kc, "detect_key_frame_candidates", record)
    case = legacy.KeyframeCandidateTests(name)
    getattr(case, name)()  # all original selection assertions still run
    assert captured
    for pose, motion, profile, fps in captured:
        result = production_detector(pose, motion, profile, fps)
        refs = []
        frames = pose.get("frames", []) if isinstance(pose, dict) else []
        fps = kc._valid_effective_fps(fps)
        available = [result[k] for k in ("T", "A", "L") if result[k]["frame_id"]]
        for c in available:
            evidence = c["evidence"]
            support = evidence["support_frames"]
            assert support and c["frame_id"] in [r["frame_id"] for r in support]
            indices = [r["pose_index"] for r in support]
            assert indices == list(range(indices[0], indices[-1] + 1))
            for r in support:
                f = frames[r["pose_index"]]
                assert frame_usable(f) and _frame_key(f["frame"]) == r["frame_id"]
            assert all(b["timestamp"] > a["timestamp"] and b["timestamp"]-a["timestamp"] <= 2/fps+.002 for a,b in zip(support,support[1:]))
            if evidence["signal_source"] == "motion_only":
                assert evidence["support_point_ids"] == []
                assert not any(k in evidence for k in ("com_y", "knee_extension_deg", "ankle_return_delta"))
                assert c["confidence"] < .6
            else:
                assert {11,12,23,24}.issubset(evidence["support_point_ids"])
            refs.append(evidence["continuous_segment"])
        assert len(set(refs)) <= 1
        if frames and all(not frame_usable(f) for f in frames):
            assert not available  # identity protection wins over full-frame motion


def test_downstream_frame_consumers_do_not_restore_conflicting_legacy_stages():
    from app.services.bio_context import extract_key_frame_stems
    from app.services.vision import _candidate_key_frames_from_bio
    from app.services.auto_eval import _final_key_frame_records
    from app.services.phase_smoother import _key_frame_phase_overrides
    pose,motion = inputs()
    b = attach_key_frame_candidates({"key_frames":{"T":"ghost99","takeoff":"ghost99"}},pose,motion,"jump",10.)
    trusted = {k:a for k,a in b["jump_stage_anchors"].items() if a["status"] == "available"}
    assert extract_key_frame_stems(b) == {a["frame_id"] for a in trusted.values()}
    assert _candidate_key_frames_from_bio(b) == trusted
    assert _final_key_frame_records(b) == trusted
    # Weak geometry candidates must not override independent visual phase votes.
    assert _key_frame_phase_overrides(b) == {}
    for f in pose["frames"]:
        for p in f["keypoints"]: p["quality"] = {"analysis_usable":False}
    b = attach_key_frame_candidates({"key_frames":{"T":"ghost99"}},pose,motion,"jump",10.)
    assert extract_key_frame_stems(b) == set()
    assert _candidate_key_frames_from_bio(b) == {}
    assert _final_key_frame_records(b) is None


@pytest.mark.parametrize("profile,key", [("spin","spin_main"),("spiral","峰值"),("step","步法序列")])
def test_non_jump_frame_consumers_keep_discipline_references(profile,key,monkeypatch):
    from app.services.bio_context import extract_key_frame_stems
    from app.services.vision import _candidate_key_frames_from_bio
    from app.routers import analysis as router
    from app.models import Analysis
    pose,motion = inputs()
    frame = "frame_0003"
    b = attach_key_frame_candidates({"key_frames":{key:frame,"T":"ghost99"},
        "key_frame_timestamps":{key:.2,"T":99.}},pose,motion,profile,10.)
    assert all(s["status"] == "not_applicable" for s in b["jump_stages"].values())
    assert extract_key_frame_stems(b) == {frame}
    assert _candidate_key_frames_from_bio(b) == {key:frame}
    record = Analysis(id="discipline",analysis_profile=profile,bio_data=b,status="completed")
    assert router._legacy_keyframes(record) == {key:frame}
    assert router._legacy_keyframe_timestamps(record) == {key:.2}
    monkeypatch.setattr(router,"_frame_exists_and_url",lambda a,f:(True,"/api/frames/discipline/"+f+".jpg"))
    result = router._build_keyframe_side(record,key)
    assert result.frame_id == frame and result.timestamp == .2 and result.available
