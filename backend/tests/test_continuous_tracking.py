"""TRACK-02 regressions: real association, synthetic pixels; model calls forbidden."""
import asyncio
import copy
import hashlib
import inspect
import json
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.routers import analysis
from app.services import continuous_tracking as ct
from app.services.person_tracker import PersonBBoxTracker
from app.services.pose import _tracker_bbox_is_reliable


def make_pool(tmp_path, count=21, step=4):
    pool = tmp_path / "tracking"
    pose = tmp_path / "pose"
    pool.mkdir(); pose.mkdir()
    records = []
    for i in range(count):
        image = np.zeros((240, 640, 3), dtype=np.uint8)
        image[0:8, 0:8] = i
        cv2.rectangle(image, (40 + step*i, 50), (80 + step*i, 150), (80,180,220), -1)
        p = pool / f"observation_{i:04d}.jpg"
        cv2.imwrite(str(p), image)
        records.append({"index": i, "file": p.name, "sha256": ct.file_sha256(p),
                        "source_pts": i, "source_time_base": "1/10",
                        "source_pts_time": i/10, "timestamp": i/10})
    manifest = {"version": 1, "nominal_hz": 10., "period_sec": .1,
                "gap_tolerance_sec": .025, "window_start": 0., "window_end": count/10,
                "source_origin_sec": 0., "cap_reached": False, "observations": records,
                "canvas": {"width": 640, "height": 240}, "pose_bindings": []}
    frames = ct.bind_pose_frames(pool, pose, manifest, [0, count//2, count-1])
    return pool, frames, manifest


def fake_detect(self, image, *, conf_threshold=.4):
    assert conf_threshold == .4, "unexpected detector config"
    i = round(float(image[:8,:8].mean()))
    x = 40. + 4*i
    return [(x,50.,x+40.,150.,.95), (530.,50.,570.,150.,.95)]


def forbid_model(self):
    raise AssertionError("real model must never run in synthetic regressions")


@pytest.fixture(autouse=True)
def no_real_model(monkeypatch):
    monkeypatch.setattr(PersonBBoxTracker,"_get_yolo_model",forbid_model)


def test_production_dense_pool_keeps_target_while_sparse_input_breaks(tmp_path, monkeypatch):
    pool, frames, manifest = make_pool(tmp_path)
    monkeypatch.setattr(PersonBBoxTracker, "_detect", fake_detect)
    monkeypatch.setattr(PersonBBoxTracker, "_get_model", forbid_model, raising=False)
    seed = {"x":40/640, "y":50/240, "width":40/640, "height":100/240}
    old = {"selected_bbox":seed, "manual_override":True}
    analysis._build_bbox_per_frame(frames, old, effective_fps=1.)
    assert not all(_tracker_bbox_is_reliable(d) for d in old["person_tracker_diagnostics"])
    target = {"selected_bbox":seed, "manual_override":True, "preview_frame_index":0}
    result = analysis._build_bbox_per_frame(frames, target, 1., tracking_manifest=manifest, tracking_dir=pool)
    assert len(result) == len(frames) == 3
    assert target["tracking_observation_count"] == 21
    for i, (box, d) in enumerate(zip(result, target["person_tracker_diagnostics"])):
        assert d["frame_index"] == i and d["frame"] == frames[i].name
        assert d["observation_index"] == [0,10,20][i]
        assert _tracker_bbox_is_reliable(d)
        assert box["x"] == pytest.approx((40+4*[0,10,20][i])/640, abs=1e-4)
    assert target["continuous_tracking_summary"]["detector_calls"] == 21


def test_middle_anchor_independent_directions_and_exact_binding(tmp_path, monkeypatch):
    pool, frames, m = make_pool(tmp_path)
    monkeypatch.setattr(PersonBBoxTracker, "_detect", fake_detect)
    lock={"selected_bbox":{"x":80/640,"y":50/240,"width":40/640,"height":100/240},
          "manual_override":True,"preview_frame_index":1}
    analysis._build_bbox_per_frame(frames, lock, 1., tracking_manifest=m, tracking_dir=pool)
    d=lock["person_tracker_diagnostics"]
    assert [x["observation_index"] for x in d] == [0,10,20]
    assert [x["tracking_direction"] for x in d] == ["backward","forward","forward"]
    assert all(_tracker_bbox_is_reliable(x) for x in d)
    assert lock["continuous_tracking_summary"]["detector_calls"] == 21
    states = lock["continuous_tracking_summary"]["observation_states"]
    assert all(row["tracker_id"] == 1 for row in states)
    assert len(list(frames[0].parent.glob("frame_*.jpg"))) == 3
    assert len(list(pool.glob("*.jpg"))) == 21


@pytest.mark.parametrize("damage", ["duplicate_pts","missing_pts","out_of_window","gap","hash","mapping","missing_file"])
def test_invalid_binding_or_clock_never_reaches_pose(tmp_path, monkeypatch, damage):
    pool, frames, m=make_pool(tmp_path)
    monkeypatch.setattr(PersonBBoxTracker,"_detect",fake_detect)
    if damage=="duplicate_pts": m["observations"][5]["source_pts"]=4
    if damage=="missing_pts": m["observations"][5].pop("source_pts")
    if damage=="out_of_window": m["window_end"]=.4
    if damage=="gap":
        for o in m["observations"][5:]:
            o["source_pts"]+=10; o["source_pts_time"]+=1; o["timestamp"]+=1
        m["window_end"]+=1
    if damage=="hash": frames[-1].write_bytes(frames[0].read_bytes())
    if damage=="mapping": m["pose_bindings"][-1]["observation_index"]=0
    if damage=="missing_file": (pool/m["observations"][5]["file"]).unlink()
    lock={"selected_bbox":{"x":40/640,"y":50/240,"width":40/640,"height":100/240},"manual_override":False}
    analysis._build_bbox_per_frame(frames,lock,1.,tracking_manifest=m,tracking_dir=pool)
    assert not _tracker_bbox_is_reliable(lock["person_tracker_diagnostics"][-1])
    assert lock["person_tracker_diagnostics"][-1]["input_binding_valid"] is False


def test_occlusion_and_wrong_person_do_not_rebind(tmp_path,monkeypatch):
    pool,frames,m=make_pool(tmp_path)
    def detect(self,image,**kwargs):
        i=round(float(image[:8,:8].mean()))
        return fake_detect(self,image) if i<8 else [(530.,50.,570.,150.,.95)]
    monkeypatch.setattr(PersonBBoxTracker,"_detect",detect)
    lock={"selected_bbox":{"x":40/640,"y":50/240,"width":40/640,"height":100/240},"manual_override":True}
    analysis._build_bbox_per_frame(frames,lock,1.,tracking_manifest=m,tracking_dir=pool)
    assert not _tracker_bbox_is_reliable(lock["person_tracker_diagnostics"][-1])


def test_native_stage_is_wired_before_preview_and_pose():
    text=inspect.getsource(analysis)
    assert text.index("await prepare_continuous_pose_inputs(") < text.index("local_detected_candidates =")
    assert "tracking_manifest=motion_scores.get('continuous_tracking')" in text
    assert "if not existing_target_lock_confirmed and not golden_overrides:" in text


@pytest.mark.parametrize("offset,vfr",[(0,False),(7,False),(7,True)])
def test_real_ffmpeg_pts_padding_window_and_cap(tmp_path,offset,vfr):
    assert shutil.which("ffmpeg") and shutil.which("ffprobe")
    video=tmp_path/"synthetic.mkv"
    vf=f"setpts=PTS+{offset}/TB"
    if vfr: vf=f"select='not(eq(mod(n,7),0))',setpts=PTS+{offset}/TB"
    subprocess.run(["ffmpeg","-v","error","-y","-f","lavfi","-i","testsrc2=size=90x160:rate=30:duration=3", "-vf",vf,"-fps_mode","passthrough","-c:v","ffv1",str(video)],check=True)
    m=asyncio.run(ct.extract_tracking_pool(video,tmp_path/"tracking",.5,2.5,nominal_hz=10,max_frames=12))
    obs=m["observations"]
    assert 1 <= len(obs) <= 12 and m["cap_reached"]
    assert all(.5 <= o["timestamp"] < 2.5 for o in obs)
    assert all(o["source_pts_time"] >= offset+.5 for o in obs)
    assert all(o["source_pts_time"] == pytest.approx(o["source_pts"]*float(ct.Fraction(o["source_time_base"]))) for o in obs)
    assert m["geometry"]["content_width"] < m["canvas"]["width"]
    assert len({o["source_pts"] for o in obs}) == len(obs)
    assert cv2.imread(str(tmp_path/"tracking"/obs[0]["file"])).shape[:2] == (480,854)


def test_real_pose_entry_scans_only_bound_images_and_blocks_changed_file(tmp_path,monkeypatch):
    import sys
    import types
    from app.services import pose
    pool,frames,m=make_pool(tmp_path)
    monkeypatch.setattr(PersonBBoxTracker,"_detect",fake_detect)
    lock={"selected_bbox":{"x":40/640,"y":50/240,"width":40/640,"height":100/240},"manual_override":False}
    boxes=analysis._build_bbox_per_frame(frames,lock,1.,tracking_manifest=m,tracking_dir=pool)
    class FakePose:
        calls=0
        def __init__(self,**kwargs): pass
        def process(self,image):
            FakePose.calls+=1
            return types.SimpleNamespace(pose_landmarks=None)
        def close(self): pass
    monkeypatch.setitem(sys.modules,"mediapipe",types.SimpleNamespace(solutions=types.SimpleNamespace(pose=types.SimpleNamespace(Pose=FakePose))))
    monkeypatch.setattr(pose,"_resolve_tasks_landmarker",lambda:None)
    # Count the production crop entry, one allowed synthetic pose attempt per image.
    attempts=[]
    def crop(model, image, image_width, image_height, bbox, **kwargs):
        attempts.append(round(float(image[:8,:8].mean())))
        return None,{"success":False,"reason":"synthetic_no_landmarks"}
    monkeypatch.setattr(pose,"_run_single_pose_crop",crop)
    changed=frames[1]
    changed.write_bytes(frames[0].read_bytes())
    payload=pose.extract_pose(str(frames[0].parent),lock,boxes,1.)
    assert len(payload["frames"])==3
    assert payload["pose_diagnostics"]["input_binding_blocked_frames"]==1
    assert payload["frames"][1]["keypoints"]==[]
    assert payload["pose_diagnostics"]["frames"][1]["reason"]=="continuous_input_binding_invalid"
    assert FakePose.calls == 0
    assert set(attempts) == {0,20}  # existing multiple crops are only of these two pose images


def test_prepare_chooses_pool_images_before_any_lock_and_retains_pool(tmp_path):
    from app.services.video import VideoSamplingMetadata,_extract_uniform_frames_in_window
    video=tmp_path/"source.mkv"
    subprocess.run(["ffmpeg","-v","error","-y","-f","lavfi","-i","testsrc2=size=320x180:rate=30:duration=2","-c:v","ffv1",str(video)],check=True)
    pose_dir=tmp_path/"pose"; pose_dir.mkdir()
    old=[]
    for i in range(3):
        p=pose_dir/f"frame_{i+1:04d}.jpg"; p.write_bytes(b"old-unbound"); old.append(p)
    meta=VideoSamplingMetadata(action_window_start=0.,action_window_end=2.,window_start_sec=0.,window_end_sec=2.,effective_fps=1.5,source_fps=30.,is_slow_motion=False)
    scores={"window_start":0.,"window_end":2.,"selected":[{"timestamp":v} for v in [0.,.8,1.7]]}
    frames,payload=asyncio.run(ct.prepare_continuous_pose_inputs(video,pose_dir,tmp_path/"tracking",old,scores,meta))
    m=payload["continuous_tracking"]
    assert len(m["observations"])>len(frames)==3
    for p,b in zip(frames,m["pose_bindings"]): assert ct.file_sha256(p)==b["sha256"]
    count=len(list((tmp_path/"tracking").glob("*.jpg")))
    asyncio.run(_extract_uniform_frames_in_window(video,tmp_path/"legacy",0.,2.,10,3))
    assert len(list((tmp_path/"tracking").glob("*.jpg")))==count


def test_cache_rejects_crop_or_threshold_and_observation_limit(tmp_path,monkeypatch):
    pool,frames,m=make_pool(tmp_path)
    monkeypatch.setattr(PersonBBoxTracker,"_detect",fake_detect)
    def force_extra(self,paths,seed,**kwargs):
        self._detect(np.zeros((10,10,3),dtype=np.uint8),conf_threshold=.2)
        raise AssertionError("config rejection required")
    monkeypatch.setattr(PersonBBoxTracker,"track_sequence_detailed",force_extra)
    lock={"selected_bbox":{"x":.1,"y":.2,"width":.1,"height":.4},"manual_override":True}
    analysis._build_bbox_per_frame(frames,lock,1.,tracking_manifest=m,tracking_dir=pool)
    assert all(not _tracker_bbox_is_reliable(d) for d in lock["person_tracker_diagnostics"])
    assert lock["continuous_tracking_summary"]["detector_calls"]==0
    assert "uncached_crop_or_detector_config_rejected" in str(lock["continuous_tracking_summary"])
    with pytest.raises(ValueError): asyncio.run(ct.extract_tracking_pool(tmp_path/"absent",tmp_path/"overflow",0.,1.,max_frames=241))


def test_continuous_nonmanual_lost_input_cannot_fall_back_to_other_person_pose(tmp_path,monkeypatch):
    import sys,types
    from app.services import pose
    pool,frames,m=make_pool(tmp_path)
    def detect(self,image,**kwargs):
        return [] if round(float(image[:8,:8].mean()))>=8 else fake_detect(self,image)
    monkeypatch.setattr(PersonBBoxTracker,"_detect",detect)
    lock={"selected_bbox":{"x":40/640,"y":50/240,"width":40/640,"height":100/240},"manual_override":False}
    lock["manual_override"]=True
    boxes=analysis._build_bbox_per_frame(frames,lock,1.,tracking_manifest=m,tracking_dir=pool)
    lock["manual_override"]=False  # the pose binding barrier must also protect nonmanual callers
    class NeverPose:
        def __init__(self,**kwargs): pass
        def close(self): pass
    monkeypatch.setitem(sys.modules,"mediapipe",types.SimpleNamespace(solutions=types.SimpleNamespace(pose=types.SimpleNamespace(Pose=NeverPose))))
    monkeypatch.setattr(pose,"_resolve_tasks_landmarker",lambda:None)
    calls=[]
    def crop(*args,**kwargs):
        calls.append(1); return None,{"success":False}
    monkeypatch.setattr(pose,"_run_single_pose_crop",crop)
    result=pose.extract_pose(str(frames[0].parent),lock,boxes,1.)
    assert len(calls)==1
    assert result["pose_diagnostics"]["input_binding_blocked_frames"]==2
    assert result["frames"][-1]["keypoints"]==[]


def test_detector_failure_is_cached_across_directions(tmp_path,monkeypatch):
    pool,frames,m=make_pool(tmp_path)
    calls=[]
    def fail(self,image,**kwargs): calls.append(1); raise RuntimeError("synthetic detector unavailable")
    monkeypatch.setattr(PersonBBoxTracker,"_detect",fail)
    lock={"selected_bbox":{"x":80/640,"y":50/240,"width":40/640,"height":100/240},"manual_override":True,"preview_frame_index":1}
    analysis._build_bbox_per_frame(frames,lock,1.,tracking_manifest=m,tracking_dir=pool)
    assert len(calls)==1
    assert lock["continuous_tracking_summary"]["detector_calls"]==1
    assert all(not _tracker_bbox_is_reliable(d) for d in lock["person_tracker_diagnostics"])


def test_gap_before_anchor_only_blocks_the_side_across_gap(tmp_path,monkeypatch):
    pool,frames,m=make_pool(tmp_path)
    for o in m["observations"][5:]:
        o["source_pts"]+=10; o["source_pts_time"]+=1; o["timestamp"]+=1
    for b in m["pose_bindings"]:
        b["source_pts"]=m["observations"][b["observation_index"]]["source_pts"]
    m["window_end"]+=1
    monkeypatch.setattr(PersonBBoxTracker,"_detect",fake_detect)
    lock={"selected_bbox":{"x":80/640,"y":50/240,"width":40/640,"height":100/240},"manual_override":True,"preview_frame_index":1}
    analysis._build_bbox_per_frame(frames,lock,1.,tracking_manifest=m,tracking_dir=pool)
    d=lock["person_tracker_diagnostics"]
    assert not _tracker_bbox_is_reliable(d[0])
    assert _tracker_bbox_is_reliable(d[1]) and _tracker_bbox_is_reliable(d[2])


def test_real_ffmpeg_vfr_gap_is_a_barrier_and_rotation_is_recorded(tmp_path):
    video=tmp_path/"gap.mkv"
    subprocess.run(["ffmpeg","-v","error","-y","-f","lavfi","-i","testsrc2=size=320x180:rate=30:duration=3", "-vf","select='not(between(n,25,40))'","-fps_mode","passthrough","-c:v","ffv1",str(video)],check=True)
    m=asyncio.run(ct.extract_tracking_pool(video,tmp_path/"gap_pool",0.,3.,nominal_hz=10,max_frames=48))
    _,errors=ct._validated_observations(tmp_path/"gap_pool",m)
    assert "tracking_clock_gap" in errors
    plain=tmp_path/"plain.mp4"; rotated=tmp_path/"rotated.mp4"
    subprocess.run(["ffmpeg","-v","error","-y","-f","lavfi","-i","testsrc2=size=320x180:rate=30:duration=1","-c:v","mpeg4",str(plain)],check=True)
    subprocess.run(["ffmpeg","-v","error","-y","-display_rotation","90","-i",str(plain),"-c","copy",str(rotated)],check=True)
    rotated_manifest=asyncio.run(ct.extract_tracking_pool(rotated,tmp_path/"rotated_pool",0.,1.))
    assert abs(rotated_manifest["geometry"]["rotation"][0])==90
    assert rotated_manifest["geometry"]["content_width"]<rotated_manifest["geometry"]["content_height"]


def test_missing_bound_timestamp_is_explicitly_unreliable(tmp_path, monkeypatch):
    pool, frames, manifest = make_pool(tmp_path)
    monkeypatch.setattr(PersonBBoxTracker, "_detect", fake_detect)
    manifest["observations"][10].pop("timestamp")
    lock = {"selected_bbox": {"x":40/640,"y":50/240,"width":40/640,"height":100/240},
            "manual_override": True, "preview_frame_index": 0}
    analysis._build_bbox_per_frame(frames, lock, 1., tracking_manifest=manifest, tracking_dir=pool)
    diagnostic = lock["person_tracker_diagnostics"][1]
    assert diagnostic["input_binding_valid"] is False
    assert diagnostic["timestamp"] is None
    assert not _tracker_bbox_is_reliable(diagnostic)
