"""Synthetic pixels only: bound motion, actual preview and keyframe consumers."""
import asyncio
import copy
import socket
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from app.services import continuous_tracking as ct
from app.services import keyframe_candidates as kc
from app.services import target_lock as tl
from app.services.person_tracker import PersonBBoxTracker


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError("network/model forbidden in motion regression")
    loop = asyncio.new_event_loop()  # Windows creates its local self-pipe before network interception.
    monkeypatch.setattr(asyncio, "run", lambda coro: loop.run_until_complete(coro))
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(PersonBBoxTracker, "_get_yolo_model", forbidden)
    from app.services import pose
    monkeypatch.setattr(pose, "extract_pose", forbidden)
    monkeypatch.setattr(pose, "_resolve_tasks_landmarker", forbidden)
    yield
    loop.close()


def prepare(tmp_path, monkeypatch, *, times=None, start=0., scale=1., wanted=None):
    times = times or [i / 10 for i in range(20)]
    wanted = wanted or [times[0], times[8], times[17]]
    pool = tmp_path / "tracking"
    pool.mkdir()
    pose = tmp_path / "pose"
    pose.mkdir()
    observations = []
    for i, t in enumerate(times):
        # A sharp, label-free image change at observation8, a smaller change17.
        value = 0 if i < 8 else (64 if i < 17 else 72)
        image = pool / f"observation_{i:04d}.jpg"
        cv2.imwrite(str(image), np.full((32, 48, 3), value, np.uint8))
        observations.append(dict(index=i, file=image.name, sha256=ct.file_sha256(image),
            source_pts=round((t+7)*1000), source_time_base="1/1000",
            source_pts_time=t+7, timestamp=t))
    intervals = np.diff(times)
    period = float(np.median(intervals))
    manifest = dict(version=1, observations=observations, source_origin_sec=7.,
        window_start=start, window_end=times[-1]+period, coverage_end=times[-1],
        period_sec=period, pose_bindings=[], cap_reached=True)
    frames = []
    for i in range(len(wanted)):
        p=pose / f"frame_{i+1:04d}.jpg"
        p.write_bytes(b"old-image")
        frames.append(p)
    old = dict(scores=[.01]*20, frame_rate=10., window_start=start,
        window_end=times[-1]+period, slow_motion_scale=scale,
        selected=[dict(frame_id=p.stem,timestamp=t,motion_score=.95 if i==1 else .01)
                  for i,(p,t) in enumerate(zip(frames,wanted))])
    old["scores"][8] = .95
    async def extract(*a, **kw):
        return copy.deepcopy(manifest)
    monkeypatch.setattr(ct, "extract_tracking_pool", extract)
    result = asyncio.run(ct.prepare_continuous_pose_inputs(
        tmp_path/"unused.mp4",pose,pool,frames,old,SimpleNamespace(effective_fps=1.)))
    return result, old, manifest, pool


def test_peak_reaches_actual_preview_and_keyframe_consumers(tmp_path, monkeypatch):
    (frames, motion), old, m, pool = prepare(tmp_path, monkeypatch)
    records = kc._motion_records(motion, 1.5)
    assert records[0][1:] == (frames[1].stem, .8, 1.), records
    by_frame, selected, scores = kc._selected_records(motion)
    assert kc._motion_score_at(1,frames[1].stem,3,by_frame,selected,scores) == 1.
    assert kc._motion_score_at(0,frames[0].stem,3,by_frame,selected,scores) is None
    assert tl._motion_anchor_frame_names(motion,limit=1) == [frames[1].name]
    preview=tl.build_target_preview("synthetic",[p.name for p in frames],motion_scores=motion)
    assert preview.preview_frame == frames[1].name
    assert preview.preview_frame_source == "motion_peak"
    assert old["scores"][8] == .95  # no mutation of saved legacy payload
    assert motion["frame_rate"] is None  # cannot invent uniform PTS from this series
    row=motion["selected"][1]
    assert row["source_sample_index"] == 8
    assert row["sha256"] == ct.file_sha256(frames[1])
    interval=row["motion_interval"]
    assert interval["current"]["source_pts"] == 7800
    assert interval["previous"]["source_pts"] == 7700
    assert interval["source_duration_sec"] == pytest.approx(.1)
    assert len(motion["scores"]) > 0 and max(motion["scores"]) == 1.


@pytest.mark.parametrize("scale",[1.,4.])
def test_irregular_pts_nonzero_start_and_analysis_clock(tmp_path,monkeypatch,scale):
    times=[2.+i*.1 for i in range(20)]
    times[8]+=.01
    (frames,motion),_,m,_=prepare(tmp_path,monkeypatch,times=times,start=2.,scale=scale)
    row=motion["selected"][1]
    assert row["timestamp"] == pytest.approx(2.81)
    assert row["analysis_timestamp"] == pytest.approx(2.81/scale)
    assert row["motion_interval"]["source_duration_sec"] == pytest.approx(.11)
    assert row["motion_interval"]["analysis_duration_sec"] == pytest.approx(.11/scale)
    assert kc._motion_records(motion,1.)[0][2] == pytest.approx(2.81/scale)
    # Other video consumers use source playback time, without uniform reconstruction.
    from app.services.video_temporal import _motion_records_from_scores as temporal
    from app.services.semantic_keyframe_pipeline import _motion_records_from_scores as semantic
    assert [r for r in temporal(motion) if r.get("motion_score") is not None][0]["timestamp"] == pytest.approx(2.81)
    assert semantic(motion)[0]["timestamp"] == pytest.approx(2.81)
    from app.routers.analysis import _saved_pose_frame_timestamps
    assert _saved_pose_frame_timestamps([{"frame":p.name} for p in frames],motion)[frames[1].name] == pytest.approx(2.81)


def test_duplicate_selection_bounds_and_cap(tmp_path,monkeypatch):
    (frames,motion),_,_,_=prepare(tmp_path,monkeypatch,wanted=[-.1,0.,.8,.801,1.7,2.5])
    assert len(frames)==3
    assert [r["source_sample_index"] for r in motion["selected"]]==[0,8,17]
    assert motion["unrepresented_pose_targets"]==[-.1,2.5]


def test_unknown_score_or_time_cannot_fall_back_to_wrong_frame(tmp_path,monkeypatch):
    (frames,motion),_,_,_=prepare(tmp_path,monkeypatch)
    motion["selected"][1]["motion_score"]=None
    motion["selected"][2]["analysis_timestamp"]=None
    by_frame, selected, scores=kc._selected_records(motion)
    assert kc._motion_score_at(1,frames[1].stem,3,by_frame,selected,scores) is None
    assert kc._motion_score_at(1,"unmapped",3,by_frame,selected,scores) is None
    assert kc._motion_records(motion,100.) == []
    assert kc._dense_motion_score_records(motion,100.,[]) == []
    assert kc._timestamp_at({},2,frames[2].stem,100.,by_frame,selected) is None
    assert kc._build_signals({"frames":[{"frame":frames[2].name,"keypoints":[]}]},motion,100.) == []


def test_unknown_motion_is_explicit_preview_fallback():
    motion={"motion_signal_version":2,"selected":[
        {"motion_signal_version":2,"frame_id":"frame_0002","timestamp":1.,"motion_score":None}]}
    assert tl._motion_anchor_frame_names(motion)==[]
    preview=tl.build_target_preview("synthetic",["frame_0001.jpg","frame_0002.jpg"],motion_scores=motion)
    assert preview.preview_frame=="frame_0001.jpg"
    assert preview.preview_frame_source=="uniform_fallback"


@pytest.mark.parametrize("damage",["hash","pts","gap","unreadable"])
def test_invalid_pool_never_creates_valid_motion(tmp_path,monkeypatch,damage):
    # Build once, then inspect the generic same-pool signal builder independently.
    (_,motion),_,m,pool=prepare(tmp_path,monkeypatch)
    row=m["observations"][8]
    if damage=="hash": row["sha256"]="0"*64
    if damage=="pts": row["source_pts"]=None
    if damage=="gap":
        row["source_pts"]+=50; row["source_pts_time"]+=.05; row["timestamp"]+=.05
    if damage=="unreadable":
        p=pool/row["file"];p.write_bytes(b"invalid");row["sha256"]=ct.file_sha256(p)
    records=ct.bound_motion_records(pool,m,1.)
    assert records[8]["motion_score"] is None
    assert records[8]["motion_status"] != "valid"


def test_legacy_format_unchanged():
    motion={"selected":[{"frame_id":"frame_0001","timestamp":.8,"motion_score":.95}],"scores":[.01]}
    assert kc._motion_records(motion,5.)==[(0,"frame_0001",.8,.95)]
    assert tl._motion_anchor_frame_names(motion)==["frame_0001.jpg"]


@pytest.mark.parametrize("field,value",[("sha256","bad"),("source_pts",123),("source_sample_index",2)])
def test_motion_score_refuses_mismatched_endpoint(tmp_path,monkeypatch,field,value):
    (frames,motion),_,_,_=prepare(tmp_path,monkeypatch)
    motion["selected"][1][field]=value
    by_frame,selected,scores=kc._selected_records(motion)
    assert kc._motion_score_at(1,frames[1].stem,3,by_frame,selected,scores) is None
    assert frames[1].name not in tl._motion_anchor_frame_names(motion)


@pytest.mark.parametrize("timestamp",[None,float("nan"),float("inf")])
def test_unknown_selection_time_refused_before_deleting_inputs(tmp_path,monkeypatch,timestamp):
    with pytest.raises((ValueError,TypeError)):
        prepare(tmp_path,monkeypatch,wanted=[0.,timestamp,1.7])
    assert (tmp_path/"pose"/"frame_0001.jpg").read_bytes()==b"old-image"
