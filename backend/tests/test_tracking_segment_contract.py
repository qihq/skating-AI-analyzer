"""Independent segment identity: actual tracking, synthetic JPEG/detection only."""
import copy
import json
import os
from pathlib import Path
import cv2
import numpy as np
import pytest
from app.services import continuous_tracking as ct
from app.services.person_tracker import PersonBBoxTracker
from app.services.pose import _tracker_bbox_is_reliable
from test_tracking_clock_contract import offline, run_prepare


def segment_case(tmp_path, monkeypatch, kind="same", origin=7., anchor=0, segments=2):
    pool=tmp_path/"pool";pool.mkdir();pose=tmp_path/"pose";pose.mkdir()
    rows=[];detections={}
    for i in range(segments*6):
        seg=i//6;local=i%6;x=100+local*2 if not seg else 340+local*2
        image=np.zeros((240,640,3),np.uint8);image[:8,:8]=i*8
        present=not(seg and (kind=="absent" or (kind=="single" and local>0)))
        boxes=[]
        if present:
            colors=((0,0,230),(0,210,0)) if not(seg and kind=="replacement") else ((230,0,0),(0,210,230))
            if seg and kind=="replacement":x=100+local*2
            if kind=="missing_reference" and not seg:colors=((100,100,100),(100,100,100))
            if kind=="conflicting_reference" and not seg and i==1:colors=((230,0,0),(0,210,230))
            for xx in ([x,480] if seg and (kind=="ambiguous" or (kind=="crossing" and local==1)) else [x]):
                image[50:105,xx:xx+80]=colors[0];image[105:190,xx:xx+80]=colors[1]
                boxes.append((float(xx),50.,float(xx+80),190.,.95))
        f=pool/f"observation_{i:04d}.jpg";cv2.imwrite(str(f),image)
        t=seg*1.4+local*.1;pts=round((origin+t)*600)
        rows.append(dict(index=i,file=f.name,sha256=ct.file_sha256(f),source_pts=pts,source_time_base="1/600",source_pts_time=pts/600.,timestamp=t))
        detections[i]=boxes
    m=dict(version=1,source_origin_sec=origin,period_sec=.1,window_start=0.,window_end=rows[-1]["timestamp"]+.1,coverage_end=rows[-1]["timestamp"],canvas=dict(width=640,height=240),pose_bindings=[],observations=rows)
    frames,motion=run_prepare(tmp_path,monkeypatch,m,pool,pose,scale=4.)
    calls=[]
    def detect(self,image,*,conf_threshold=.4):
        assert conf_threshold==.4
        i=round(float(image[:8,:8].mean())/8);calls.append(i)
        if (kind in ("fault","unknown") and i==7) or (kind in ("late_fault","late_unknown") and i==10):
            raise (OSError if kind in ("fault","late_fault") else RuntimeError)("synthetic confirmation failure")
        return detections[i]
    monkeypatch.setattr(PersonBBoxTracker,"_detect",detect)
    x=100+(anchor%6)*2 if anchor<6 else 340+(anchor%6)*2
    lock=dict(selected_bbox=dict(x=x/640,y=50/240,width=80/640,height=140/240),manual_override=False,preview_frame_index=anchor)
    return pool,frames,motion,lock,calls


def save(name,payload):
    if os.environ.get("SEGMENT_EVIDENCE"):
        p=Path(os.environ["SEGMENT_EVIDENCE"]);p.mkdir(parents=True,exist_ok=True)
        (p/(name+".json")).write_text(json.dumps(payload,indent=2),encoding="utf-8")


@pytest.mark.parametrize("origin,anchor,segments",[(7.,0,2),(-7.,0,2),(7.,5,3),(7.,6,2),(7.,11,2)])
def test_production_segment_confirmation(tmp_path,monkeypatch,origin,anchor,segments):
    pool,frames,motion,lock,calls=segment_case(tmp_path,monkeypatch,origin=origin,anchor=anchor,segments=segments)
    before=copy.deepcopy(motion)
    boxes,ds,summary=ct.track_bound_pose_frames(frames,lock,motion["continuous_tracking"],pool)
    save(f"same-{origin}-{anchor}-{segments}",dict(diagnostics=ds,summary=summary,calls=calls))
    target_segment=1 if anchor<6 else 0;start=target_segment*6
    assert all(_tracker_bbox_is_reliable(d) for d in ds[start+2:start+6]),ds
    assert all(not _tracker_bbox_is_reliable(d) for d in ds[start:start+2])
    assert all(d["image_binding_valid"] for d in ds[start:start+6])
    assert ds[start+2]["identity_status"]=="identity_confirmed"
    assert ds[start+2]["segment_identity"]["anchor"]["observation_index"]==start+2
    assert len(ds[start+2]["segment_identity"]["support"])==3
    assert all(d["continuity_segment"]==target_segment for d in ds[start:start+6])
    assert len(calls)==len(set(calls)) and len(calls)<=len(frames)
    for seg in range(segments):
        if seg != anchor//6:
            assert all(_tracker_bbox_is_reliable(d) for d in ds[seg*6+2:seg*6+6])
            assert ds[seg*6+2]["segment_identity"]["reference_segment"] == anchor//6
    assert motion==before


@pytest.mark.parametrize("kind",["replacement","ambiguous","absent","missing_reference","conflicting_reference","single","crossing"])
def test_independent_identity_rejects_unsupported_segments(tmp_path,monkeypatch,kind):
    pool,frames,motion,lock,calls=segment_case(tmp_path,monkeypatch,kind)
    _,ds,summary=ct.track_bound_pose_frames(frames,lock,motion["continuous_tracking"],pool)
    save(kind,dict(diagnostics=ds,summary=summary,calls=calls))
    assert not any(_tracker_bbox_is_reliable(d) for d in ds[6:])
    assert all(d["identity_status"]=="identity_unconfirmed" for d in ds[6:])
    assert all(d["image_binding_valid"] for d in ds[6:])
    assert len(calls)==len(set(calls))


@pytest.mark.parametrize("kind",["fault","unknown"])
def test_confirmation_failure_preserves_prefix(tmp_path,monkeypatch,kind):
    pool,frames,motion,lock,calls=segment_case(tmp_path,monkeypatch,kind)
    _,ds,summary=ct.track_bound_pose_frames(frames,lock,motion["continuous_tracking"],pool)
    save(kind,dict(diagnostics=ds,summary=summary,calls=calls))
    assert all(_tracker_bbox_is_reliable(d) for d in ds[:6])
    assert not any(_tracker_bbox_is_reliable(d) for d in ds[6:9])
    assert calls.count(7)==1
    if kind=="unknown":assert not any(_tracker_bbox_is_reliable(d) for d in ds[6:])
    else:assert _tracker_bbox_is_reliable(ds[-1])


@pytest.mark.parametrize("kind", ["same", "ambiguous", "replacement"])
def test_segment_actual_saved_chain(tmp_path, monkeypatch, kind):
    import sys
    from types import SimpleNamespace
    from fractions import Fraction
    from app.services import pose as poses
    from app.routers import analysis
    from app.services.action_profiles import infer_analysis_profile
    from app.services.pose_observations import observation_slots
    from app.services.jump_projection import extract_projection
    from test_analysis_keyframe_candidates import _keypoints
    from test_tal_persistence import consume_contract

    pool, frames, motion, lock, calls = segment_case(tmp_path, monkeypatch, kind)
    boxes = analysis._build_bbox_per_frame(frames, lock, 10.,
        tracking_manifest=motion["continuous_tracking"], tracking_dir=pool)
    landmark_calls = []
    class SyntheticPose:
        def __init__(self, **kwargs): pass
        def process(self, image):
            landmark_calls.append(1)
            points = _keypoints(com_y=.4, knee_state="straight")
            return SimpleNamespace(pose_landmarks=SimpleNamespace(landmark=[
                SimpleNamespace(**{k:p[k] for k in ("x","y","z","visibility")}) for p in points]))
        def close(self): pass
    monkeypatch.setitem(sys.modules, "mediapipe", SimpleNamespace(solutions=SimpleNamespace(pose=SimpleNamespace(Pose=SyntheticPose))))
    monkeypatch.setattr(poses, "_resolve_tasks_landmarker", lambda: None)
    pose = poses.extract_pose(str(frames[0].parent), lock, boxes, 10.,
        frame_times=motion["selected"], slow_motion_scale=4.)
    profile, evidence = infer_analysis_profile("è‡ªç”±æ»‘", "èŠ‚ç›®ç‰‡æ®µ", pose, motion)
    save("chain-input-"+kind, dict(synthetic_detection=True, synthetic_landmarks=True,
         pose=pose, motion=motion, lock=lock, automatic_profile=profile, automatic_evidence=evidence))
    assert all(f["keypoints"] for f in pose["frames"][:6]), pose["pose_diagnostics"]
    assert all(not f["keypoints"] for f in pose["frames"][6:8])
    if kind == "same":
        assert all(f["keypoints"] for f in pose["frames"][8:]), pose["pose_diagnostics"]
    else:
        assert all(not f["keypoints"] for f in pose["frames"][6:])
    result = consume_contract(tmp_path, pose, motion, profile, name="segment-"+kind,
        fps=10., saved_images={p.name:p.read_bytes() for p in frames})
    save("chain-readback-"+kind, result)
    assert result["detail"]["pose_data"] == pose
    assert result["detail"]["frame_motion_scores"] == motion
    assert len(result["image_reads"]) == 12
    # The automatic step route may omit jump metrics. Exercise the same actual
    # projection consumer additionally, without forcing the production profile.
    projection = extract_projection(pose, motion)
    save("chain-projection-"+kind, projection)
    assert len(projection["segments"]) == (2 if kind == "same" else 1), projection
    assert not any(p["pose_index"] in (6,7) for p in projection["points"])
    assert all(f is None for f in observation_slots(pose,motion)[6:8])
    for i, f in enumerate(result["pose"]["frames"]):
        assert f["image_binding_valid"] is True
        assert f["temporal"]["tracking_continuity_segment"] == i//6
        if f["keypoints"]:
            t=f["temporal"]; b=t["binding"]
            source=float(b["source_pts"]*Fraction(b["source_time_base"]))
            assert t["playback_timestamp"] == pytest.approx(source-7.)
            assert t["analysis_timestamp"] == pytest.approx((source-7.)/4.)
        if i>=8 and kind=="same":
            identity=f["temporal"]["segment_identity"]
            assert identity["anchor"]["observation_index"]==8
            assert [s["observation_index"] for s in identity["support"]]==[6,7,8]
            for r in identity["reference"]+identity["support"]:
                original=motion["continuous_tracking"]["observations"][r["observation_index"]]
                assert r["sha256"]==original["sha256"] and r["source_pts"]==original["source_pts"]
    assert not result["detail"]["bio_data"]["jump_measurements"]["rotation_count"]["value"]


@pytest.mark.parametrize("kind", ["late_fault", "late_unknown"])
def test_confirmed_prefix_survives_local_error(tmp_path, monkeypatch, kind):
    pool,frames,motion,lock,calls=segment_case(tmp_path,monkeypatch,kind)
    _,ds,summary=ct.track_bound_pose_frames(frames,lock,motion["continuous_tracking"],pool)
    save(kind,dict(diagnostics=ds,summary=summary,calls=calls))
    assert all(_tracker_bbox_is_reliable(d) for d in ds[:6]+ds[8:10])
    assert not any(_tracker_bbox_is_reliable(d) for d in ds[10:])
    assert calls.count(10)==1 and len(calls)==len(set(calls))
    assert any(a["result"]=="failure" for a in summary["cache_audit"])
    assert summary["cache_hits"]>0


@pytest.mark.parametrize("fault", ["pool_hash", "bad_jpeg", "duplicate_clock", "backward_clock", "selected_hash", "reference_hash"])
def test_identity_cannot_repair_invalid_binding_or_clock(tmp_path, monkeypatch, fault):
    pool,frames,motion,lock,calls=segment_case(tmp_path,monkeypatch)
    m=motion["continuous_tracking"]
    index=1 if fault=="reference_hash" else 7
    if fault in ("pool_hash", "reference_hash", "bad_jpeg"):
        p=pool/m["observations"][index]["file"];p.write_bytes(b"not a JPEG")
        if fault=="bad_jpeg":
            m["observations"][index]["sha256"]=ct.file_sha256(p)
    elif fault=="selected_hash":
        frames[index].write_bytes(b"different selected image")
    else:
        row=m["observations"][index];row["source_pts"]=m["observations"][index-1]["source_pts"]-(60 if fault=="backward_clock" else 0)
        row["source_pts_time"]=row["source_pts"]/600.;row["timestamp"]=row["source_pts_time"]-7.
        m["pose_bindings"][index]["source_pts"]=row["source_pts"]
    _,ds,summary=ct.track_bound_pose_frames(frames,lock,m,pool)
    save(fault,dict(diagnostics=ds,summary=summary,calls=calls))
    assert not _tracker_bbox_is_reliable(ds[index])
    assert ds[index]["image_binding_valid"] is False
    assert _tracker_bbox_is_reliable(ds[0])
    for d in ds:
        if d.get("segment_identity",{}).get("anchor"):
            identity=d["segment_identity"]
            assert all(s["observation_index"]!=index for s in identity["reference"]+identity["support"])
            assert len({s["continuity_segment"] for s in identity["support"]})==1
    if fault=="reference_hash":
        assert not any(_tracker_bbox_is_reliable(d) for d in ds[6:])


def test_identity_flag_blocks_otherwise_optimistic_consumers():
    from app.services.pose_observations import frame_usable
    contradictory=dict(state="tracked",tracker_state="tracked",tracking_state="tracked",input_binding_valid=True,
                       image_binding_valid=True,identity_status="identity_unconfirmed")
    assert not _tracker_bbox_is_reliable(contradictory)
    assert not frame_usable(contradictory)


def test_original_saved_jpegs_prepare_and_no_identity_evidence(tmp_path, monkeypatch):
    import shutil
    fixture=os.environ.get("TRACK_CLOCK_SAVED_FIXTURE")
    if not fixture: pytest.skip("explicit read-only copy of original JPEG fixture required")
    saved=Path(fixture);detail=json.loads((saved/"detail.body").read_text(encoding="utf8"))
    original_pose=json.loads((saved/"pose.body").read_text(encoding="utf8"))
    m=detail["frame_motion_scores"]["continuous_tracking"]
    pool=tmp_path/"pool";shutil.copytree(saved/"pool",pool);pose=tmp_path/"pose";pose.mkdir()
    frames,motion=run_prepare(tmp_path,monkeypatch,m,pool,pose,
        wanted=[r["timestamp"] for r in detail["frame_motion_scores"]["selected"]])
    assert len(frames)==40
    assert [ct.file_sha256(p) for p in frames]==[b["sha256"] for b in m["pose_bindings"]]
    assert [b["source_pts"] for b in motion["continuous_tracking"]["pose_bindings"]]==[b["source_pts"] for b in m["pose_bindings"]]
    calls=[]
    def absent(self,image,*,conf_threshold=.4):
        calls.append(1);return []  # Explicit synthetic no-evidence, not a real detector.
    monkeypatch.setattr(PersonBBoxTracker,"_detect",absent)
    _,ds,summary=ct.track_bound_pose_frames(frames,copy.deepcopy(detail["target_lock"]),motion["continuous_tracking"],pool)
    late=[d for d in ds if d["continuity_segment"]==1]
    assert len(late)==19 and not any(_tracker_bbox_is_reliable(d) for d in late)
    assert all(d["image_binding_valid"] and d["identity_status"]=="identity_unconfirmed" for d in late)
    assert motion["motion_records"][44]["continuity_reason"]=="tracking_clock_gap"
    assert sum(bool(f["keypoints"]) for f in original_pose["frames"])==6
    save("original-replay",dict(synthetic_detection="empty; no identity evidence",original_nonempty_pose_count=6,
         original_postgap_selected=19,original_real_recovery="unverified",diagnostics=ds,summary=summary,
         binding_hash_pts_preserved=True,pool_count=105,selected_count=40))


def test_direction_does_not_select_a_different_identity(tmp_path, monkeypatch):
    pool,frames,motion,lock,calls=segment_case(tmp_path,monkeypatch)
    _,first,_=ct.track_bound_pose_frames(frames,lock,motion["continuous_tracking"],pool)
    reverse=copy.deepcopy(lock);reverse["preview_frame_index"]=5
    reverse["selected_bbox"]["x"]=110/640
    _,second,_=ct.track_bound_pose_frames(frames,reverse,motion["continuous_tracking"],pool)
    assert [d["identity_status"] for d in first]==[d["identity_status"] for d in second]
    for a,b in zip(first[8:],second[8:]):
        assert a["bbox"]==b["bbox"]
        # Moving the original anchor changes the three frozen JPEG references,
        # so their float appearance scores may differ; the selected identity,
        # support images/PTS/boxes and independent anchor must not change.
        for left,right in zip(a["segment_identity"]["support"],b["segment_identity"]["support"]):
            assert left["similarity"]>=.9 and right["similarity"]>=.9
            assert {k:v for k,v in left.items() if k!="similarity"} == {k:v for k,v in right.items() if k!="similarity"}
        assert a["segment_identity"]["anchor"]["observation_index"]==b["segment_identity"]["anchor"]["observation_index"]
