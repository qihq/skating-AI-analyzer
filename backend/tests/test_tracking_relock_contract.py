"""TRACK-RELOCK-01: bounded detector capabilities and retained observations.

JPEG reads/synthetic detector output only. Never exercise a real model/decoder.
"""
import json
import os
import socket
import subprocess
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.routers import analysis
from app.services import continuous_tracking as ct
from app.services.person_tracker import PersonBBoxTracker
from app.services.pose import _tracker_bbox_is_reliable
from test_continuous_tracking import make_pool, fake_detect
from test_tracking_clock_contract import offline


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("real model/network/video decode/subprocess forbidden")
    monkeypatch.setattr(PersonBBoxTracker, "_get_yolo_model", forbidden)
    monkeypatch.setattr(cv2, "VideoCapture", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(ct, "_probe", forbidden)


def full_pool(tmp_path, count=9, anchor=0):
    pool, _, manifest = make_pool(tmp_path, count=count)
    frames = ct.bind_pose_frames(pool, tmp_path / "pose", manifest,
                                 list(range(count)))
    lock = dict(selected_bbox=dict(x=(40 + 4 * anchor) / 640,
        y=50 / 240, width=40 / 640, height=100 / 240),
        manual_override=False, preview_frame_index=anchor)
    return pool, frames, manifest, lock


def snapshot(name, payload):
    if os.environ.get("RELOCK_EVIDENCE"):
        out = Path(os.environ["RELOCK_EVIDENCE"]); out.mkdir(parents=True, exist_ok=True)
        (out / (name + ".json")).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf8")


@pytest.mark.parametrize("anchor,fault", [(0, 3), (4, 1), (4, 7), (8, 5)])
def test_local_detection_failure_retains_completed_prefix_and_other_direction(tmp_path, monkeypatch, anchor, fault):
    pool, frames, manifest, lock = full_pool(tmp_path, anchor=anchor)
    calls = []
    def detector(self, image, *, conf_threshold=.4):
        index = round(float(image[:8, :8].mean())); calls.append(index)
        if index == fault:
            raise OSError("synthetic single-frame detector outage")
        return fake_detect(self, image, conf_threshold=conf_threshold)
    monkeypatch.setattr(PersonBBoxTracker, "_detect", detector)
    boxes, diagnostics, summary = ct.track_bound_pose_frames(frames, lock, manifest, pool)
    previous = fault - 1 if fault > anchor else fault + 1
    snapshot(f"prefix-{anchor}-{fault}", dict(diagnostics=diagnostics, summary=summary, calls=calls))
    assert _tracker_bbox_is_reliable(diagnostics[previous]), "completed trusted prefix was erased"
    assert not _tracker_bbox_is_reliable(diagnostics[fault])
    assert diagnostics[fault]["observation_valid"] is True
    assert diagnostics[fault]["input_binding_valid"] is True, "image identity and person lock are independent"
    assert calls.count(fault) == 1
    opposite = 0 if fault > anchor else len(frames) - 1
    assert _tracker_bbox_is_reliable(diagnostics[opposite])


def test_explicit_unsupported_request_is_local_and_keeps_prefix(tmp_path, monkeypatch):
    pool, frames, manifest, lock = full_pool(tmp_path, count=5, anchor=4)
    attempted = []
    def process(self, image, seed_xyxy, *, frame_index=0, **kwargs):
        if frame_index == 3:
            attempted.append(frame_index)
            self._detect(image, conf_threshold=.35)  # actual production cache boundary
        return seed_xyxy, dict(state="tracked", rejected_reasons=[], tracker_id=77)
    monkeypatch.setattr(PersonBBoxTracker, "process_frame_detailed", process)
    boxes, diagnostics, summary = ct.track_bound_pose_frames(frames, lock, manifest, pool)
    snapshot("unsupported-request", dict(diagnostics=diagnostics, summary=summary, attempted=attempted))
    assert attempted == [3]
    assert _tracker_bbox_is_reliable(diagnostics[2]), "earlier valid observation must survive later request rejection"
    assert not _tracker_bbox_is_reliable(diagnostics[1])
    assert summary["detector_calls"] == 0


@pytest.mark.parametrize("kind", ["crop", "config", "foreign_pixels"])
def test_request_boundary_is_reached_and_request_is_never_inferred(tmp_path, monkeypatch, kind):
    pool, frames, manifest, lock = full_pool(tmp_path, count=5)
    attempted = []
    def process(self, image, seed_xyxy, *, frame_index=0, **kwargs):
        if frame_index == 2:
            attempted.append(kind)
            request = image[:20, :20] if kind == "crop" else image.copy()
            if kind == "foreign_pixels": request[:] = 219
            self._detect(request, conf_threshold=.35 if kind == "config" else .4)
        return seed_xyxy, dict(state="tracked", rejected_reasons=[], tracker_id=77)
    monkeypatch.setattr(PersonBBoxTracker, "process_frame_detailed", process)
    _, diagnostics, summary = ct.track_bound_pose_frames(frames, lock, manifest, pool)
    assert attempted == [kind]
    assert _tracker_bbox_is_reliable(diagnostics[1])
    assert not _tracker_bbox_is_reliable(diagnostics[2])
    assert summary["detector_calls"] == 0
    assert summary["cache_audit"][-1]["result"] == ("unknown_image" if kind == "foreign_pixels" else "unsupported_request")


@pytest.mark.parametrize("anchor,fault", [(0, 3), (4, 1), (4, 7), (8, 5)])
def test_unknown_fault_preserves_prefix_stops_direction_and_never_replays(tmp_path, monkeypatch, anchor, fault):
    pool, frames, manifest, lock = full_pool(tmp_path, anchor=anchor)
    calls = []
    def detect(self, image, **kwargs):
        index = round(float(image[:8, :8].mean())); calls.append(index)
        if index == fault: raise RuntimeError("synthetic unknown program fault")
        return fake_detect(self, image)
    monkeypatch.setattr(PersonBBoxTracker, "_detect", detect)
    _, diagnostics, summary = ct.track_bound_pose_frames(frames, lock, manifest, pool)
    step = 1 if fault > anchor else -1
    assert _tracker_bbox_is_reliable(diagnostics[fault-step])
    assert all(not _tracker_bbox_is_reliable(diagnostics[i]) for i in range(fault, len(frames) if step==1 else -1, step))
    assert all(i not in calls for i in range(fault+step, len(frames) if step==1 else -1, step))
    assert _tracker_bbox_is_reliable(diagnostics[0 if step==1 else -1])
    assert calls.count(anchor) == calls.count(fault) == 1
    assert "synthetic unknown program fault" in str(summary["branch_errors"])
    snapshot(f"unknown-{anchor}-{fault}", dict(diagnostics=diagnostics, summary=summary, calls=calls))


@pytest.mark.parametrize("failure", [OSError, RuntimeError])
def test_shared_anchor_failure_is_cached_once(tmp_path, monkeypatch, failure):
    pool, frames, manifest, lock = full_pool(tmp_path, anchor=4)
    calls = []
    def detect(self, image, **kwargs):
        index = round(float(image[:8, :8].mean())); calls.append(index)
        if index == 4: raise failure("synthetic anchor fault")
        return fake_detect(self, image)
    monkeypatch.setattr(PersonBBoxTracker, "_detect", detect)
    _, diagnostics, summary = ct.track_bound_pose_frames(frames, lock, manifest, pool)
    assert calls.count(4) == 1
    audit = [r for r in summary["cache_audit"] if r["result"]=="failure"]
    assert len(audit) == 2 and [r["cache_hit"] for r in audit] == [False, True]
    assert not _tracker_bbox_is_reliable(diagnostics[4])
    if failure is RuntimeError: assert summary["detector_calls"] == 1


@pytest.mark.parametrize("anchor,fault", [(0, 3), (8, 5)])
def test_real_relock_path_recovers_only_after_full_frame_confirmation(tmp_path, monkeypatch, anchor, fault):
    pool, frames, manifest, lock = full_pool(tmp_path, anchor=anchor)
    calls=[]
    def detect(self, image, *, conf_threshold=.4):
        index=round(float(image[:8,:8].mean())); calls.append((index,conf_threshold,image.shape))
        if index==fault: raise OSError("synthetic one frame outage")
        # Full-frame target and a spatially incompatible competing person.
        return fake_detect(self,image,conf_threshold=conf_threshold)
    monkeypatch.setattr(PersonBBoxTracker,"_detect",detect)
    _, diagnostics, summary=ct.track_bound_pose_frames(frames,lock,manifest,pool)
    step=1 if anchor==0 else -1
    assert not _tracker_bbox_is_reliable(diagnostics[fault])
    assert not _tracker_bbox_is_reliable(diagnostics[fault+step])
    assert diagnostics[fault+step]["state"] == "full_frame_yolo_relock_pending"
    assert diagnostics[fault+2*step]["state"] == "detector_relocked"
    assert _tracker_bbox_is_reliable(diagnostics[fault+2*step])
    assert summary["detector_calls"] == len(frames)
    assert len(calls)==len(frames) and all(c[1:]==(.4,(240,640,3)) for c in calls)
    assert not summary["branch_errors"]
    snapshot(f"recovery-{anchor}-{fault}",dict(diagnostics=diagnostics,summary=summary,calls=calls))


def test_normal_restricted_relock_does_not_request_zoom_and_can_recover(tmp_path, monkeypatch):
    from test_person_tracker import _FakeDetections
    pool, frames, manifest, lock=full_pool(tmp_path, count=7)
    calls=[]
    def detect(self,image,*,conf_threshold=.4):
        index=round(float(image[:8,:8].mean())); calls.append(index)
        assert conf_threshold==.4 and image.shape==(240,640,3)
        return [] if index==2 else fake_detect(self,image)
    monkeypatch.setattr(PersonBBoxTracker,"_detect",detect)
    # Association output is deterministic; sequence, lost handling, candidate
    # selection, identity gates and multi-frame confirmation are production code.
    monkeypatch.setattr(PersonBBoxTracker,"_update_tracks",lambda *a: _FakeDetections([],[],[]))
    _, diagnostics, summary=ct.track_bound_pose_frames(frames,lock,manifest,pool)
    assert diagnostics[0]["state"]=="full_frame_yolo_relock_pending"
    assert diagnostics[1]["state"]=="detector_relocked"
    assert not _tracker_bbox_is_reliable(diagnostics[2])
    assert diagnostics[3]["state"]=="full_frame_yolo_relock_pending"
    assert diagnostics[4]["state"]=="detector_relocked"
    assert summary["detector_calls"]==7 and len(calls)==7
    assert not summary["branch_errors"]
    snapshot("normal-compatible-relock",dict(diagnostics=diagnostics,summary=summary,calls=calls))


def test_competitor_after_fault_never_becomes_target(tmp_path, monkeypatch):
    pool, frames, manifest, lock=full_pool(tmp_path, count=25)
    def detect(self,image,**kw):
        i=round(float(image[:8,:8].mean()))
        if i==3: raise OSError("synthetic fault")
        if i>3: return [(530.,50.,570.,150.,.99)]
        return fake_detect(self,image)
    monkeypatch.setattr(PersonBBoxTracker,"_detect",detect)
    _, diagnostics, summary=ct.track_bound_pose_frames(frames,lock,manifest,pool)
    assert _tracker_bbox_is_reliable(diagnostics[2])
    assert all(not _tracker_bbox_is_reliable(d) for d in diagnostics[3:])
    assert summary["detector_calls"]==25


@pytest.mark.parametrize("all_missing", [False, True])
def test_local_fault_through_real_prepare_pose_route_report_sqlite_get(tmp_path, monkeypatch, all_missing):
    import sys
    from types import SimpleNamespace
    from test_tracking_clock_contract import fixture_pool, run_prepare
    from test_tracking_time_origin import assert_clocks
    from test_analysis_keyframe_candidates import _keypoints
    from test_tal_persistence import consume_contract
    from app.services import pose as poses
    from app.services.action_profiles import infer_analysis_profile
    from app.services.pose_observations import observation_slots

    origin, scale = 7., 4.
    pts=tuple(4200+i*60 for i in range(14))+tuple(5100+i*60 for i in range(3))
    pool, pose_dir, manifest=fixture_pool(tmp_path,pts,origin=origin)
    frames,motion=run_prepare(tmp_path,monkeypatch,manifest,pool,pose_dir,scale=scale)
    calls=[]; model_calls=[]
    fault_enabled = False
    def detector(self,image,**kw):
        index=round(float(image.mean())/10);calls.append(index)
        if fault_enabled and (all_missing or index==9): raise OSError("synthetic isolated detector outage")
        return [(200.+4*index,10.,320.+4*index,230.,.95)]
    monkeypatch.setattr(PersonBBoxTracker,"_detect",detector)
    lock=dict(selected_bbox=dict(x=200/640,y=10/240,width=120/640,height=220/240),manual_override=False)
    import copy
    control_lock=copy.deepcopy(lock)
    control_boxes=analysis._build_bbox_per_frame(frames,control_lock,10.,tracking_manifest=motion["continuous_tracking"],tracking_dir=pool)
    control_calls=list(calls); calls.clear(); fault_enabled=True
    boxes=analysis._build_bbox_per_frame(frames,lock,10.,tracking_manifest=motion["continuous_tracking"],tracking_dir=pool)
    class SyntheticPose:
        def __init__(self,**kw): pass
        def process(self,image):
            index=round(float(image.mean())/10); model_calls.append(index)
            com=[.4,.4,.3,.22,.2,.2,.25,.35,.4][index] if index<9 else .4
            points=_keypoints(com_y=com,knee_state="straight")
            return SimpleNamespace(pose_landmarks=SimpleNamespace(landmark=[SimpleNamespace(**{k:p[k] for k in ("x","y","z","visibility")}) for p in points]))
        def close(self): pass
    monkeypatch.setitem(sys.modules,"mediapipe",SimpleNamespace(solutions=SimpleNamespace(pose=SimpleNamespace(Pose=SyntheticPose))))
    monkeypatch.setattr(poses,"_resolve_tasks_landmarker",lambda:None)
    pose=poses.extract_pose(str(pose_dir),lock,boxes,10.,frame_times=motion["selected"],slow_motion_scale=scale)
    profile,evidence=infer_analysis_profile("自由滑","节目片段",pose,motion)
    name="chain-all-missing" if all_missing else "chain-local-recovered"
    result=consume_contract(tmp_path,pose,motion,profile,name=name,fps=10.,saved_images={f.name:f.read_bytes() for f in frames})
    snapshot(name,dict(inputs=dict(pose=pose,motion=motion,lock=lock),automatic_profile=profile,automatic_evidence=evidence,readback=result,synthetic_detector_calls=calls,synthetic_pose_calls=model_calls))
    assert len(control_calls)==14
    if not all_missing:
        assert boxes[:9]==control_boxes[:9]
        for a,b in zip(lock["person_tracker_diagnostics"][:9],control_lock["person_tracker_diagnostics"][:9]):
            assert a==b  # hash/PTS binding, person identity, state and segment
    assert len(calls)==len(set(calls))==14  # shared anchor; no detection across gap
    assert len(result["image_reads"])==17 and result["http"]["commit_calls"]==0
    assert result["detail"]["pose_data"]==pose
    for i,(frame,binding) in enumerate(zip(result["pose"]["frames"],motion["continuous_tracking"]["pose_bindings"])):
        assert result["image_reads"][frame["frame"]]==binding["sha256"]
        assert frame["temporal"]["binding"]==binding
        assert frame["temporal"]["tracking_continuity_segment"]==(0 if i<14 else 1)
        if i<14:
            assert frame["input_binding_valid"] is True
            assert frame["temporal"]["playback_timestamp"]==pytest.approx((pts[i]-4200)/600)
            assert frame["temporal"]["analysis_timestamp"]==pytest.approx((pts[i]-4200)/2400)
        else:
            assert frame["temporal"]["playback_timestamp"] is None
            assert frame["temporal"]["analysis_timestamp"] is None
            assert not frame["keypoints"]
    missing=set(range(17)) if all_missing else {9,10,14,15,16}
    assert all(not result["pose"]["frames"][i]["keypoints"] for i in missing)
    assert set(model_calls).isdisjoint(missing)
    assert all(slot is None for i,slot in enumerate(observation_slots(pose,motion)) if i in missing)
    bio=result["detail"]["bio_data"]
    assert result["detail"]["report"]["jump_stages"]==bio["jump_stages"]
    assert result["detail"]["report"]["jump_measurements"]==bio["jump_measurements"]
    assert bio["jump_measurements"]["rotation_count"]["value"] is None
    if all_missing:
        assert not model_calls and profile=="step"
        assert all(stage["status"] in ("unavailable","not_applicable") for stage in bio["jump_stages"].values() if isinstance(stage,dict))
        assert not bio["jump_measurements"]["trajectory"].get("points")
        assert bio["jump_measurements"]["trajectory"]["value"] is None
    else:
        assert profile=="jump"
        assert all(result["pose"]["frames"][i]["keypoints"] for i in list(range(9))+[11,12,13])
        assert "synthetic isolated detector outage" in str(result["pose"]["frames"][9]["temporal"]["tracking_rejected_reasons"])
        assert lock["person_tracker_diagnostics"][10]["state"]=="full_frame_yolo_relock_pending"
        assert lock["person_tracker_diagnostics"][11]["state"]=="detector_relocked"
        trajectory=bio["jump_measurements"]["trajectory"]
        assert trajectory["points"]
        for point in trajectory["points"]:
            assert point["pose_index"] not in missing
            assert_clocks(point,origin,scale)
        # No interpolation/line can cross the fault or the legal clock gap.
        assert len(trajectory["segments"])>=2
        for segment in trajectory["segments"]:
            indexes=[trajectory["points"][i]["pose_index"] for i in segment["point_indices"]]
            assert not (min(indexes)<9 and max(indexes)>10)
        for stage in bio["jump_stages"].values():
            if not isinstance(stage,dict): continue
            for ref in (stage.get("evidence") or {}).get("support_frames",[]):
                assert int(ref["frame_id"].split("_")[-1])-1 not in missing



def test_a_second_fault_clears_pending_identity_confirmation(tmp_path, monkeypatch):
    pool, frames, manifest, lock=full_pool(tmp_path)
    def detect(self,image,**kw):
        index=round(float(image[:8,:8].mean()))
        if index in (2,4): raise OSError("synthetic interrupted confirmation")
        return fake_detect(self,image)
    monkeypatch.setattr(PersonBBoxTracker,"_detect",detect)
    _,diagnostics,summary=ct.track_bound_pose_frames(frames,lock,manifest,pool)
    assert diagnostics[3]["state"]=="full_frame_yolo_relock_pending"
    assert not _tracker_bbox_is_reliable(diagnostics[4])
    assert diagnostics[5]["state"]=="full_frame_yolo_relock_pending"
    assert diagnostics[6]["state"]=="detector_relocked"
    assert summary["detector_calls"]==9


def test_manual_lock_fault_does_not_bypass_existing_relock_policy(tmp_path, monkeypatch):
    pool, frames, manifest, lock=full_pool(tmp_path)
    lock["manual_override"]=True
    monkeypatch.delenv("PERSON_TRACKER_MANUAL_LOCK_SELF_HEAL",raising=False)
    def detect(self,image,**kw):
        index=round(float(image[:8,:8].mean()))
        if index==3: raise OSError("synthetic manual fault")
        return fake_detect(self,image)
    monkeypatch.setattr(PersonBBoxTracker,"_detect",detect)
    _,diagnostics,_=ct.track_bound_pose_frames(frames,lock,manifest,pool)
    assert _tracker_bbox_is_reliable(diagnostics[2])
    assert all(not _tracker_bbox_is_reliable(d) for d in diagnostics[3:])
    assert "manual_lock_relock_blocked" in diagnostics[4]["rejected_reasons"]
