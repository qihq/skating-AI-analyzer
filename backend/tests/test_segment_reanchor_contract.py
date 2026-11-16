"""Offline end-to-end reanchor contracts; synthetic detections/landmarks only."""
import base64
import asyncio
import copy
import json
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app import models
from app.database import get_session
from app.routers import analysis_v2, segment_reanchor as routes
from app.services import continuous_tracking as ct, segment_reanchor as service, pose as poses
from app.services.person_tracker import PersonBBoxTracker
from test_tracking_clock_contract import offline
from test_tracking_reference_contract import patterned_case
from test_analysis_keyframe_candidates import _keypoints


_clients = []

@pytest.fixture(autouse=True)
def cleanup_clients(offline):
    yield
    while _clients:
        _clients.pop().__exit__(None, None, None)


def save(name, value):
    if os.environ.get("SEGMENT_EVIDENCE"):
        path = Path(os.environ["SEGMENT_EVIDENCE"]); path.mkdir(parents=True, exist_ok=True)
        (path/(name+".json")).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf8")


def case(tmp_path, monkeypatch, kind="different", origin=9., scale=4., start=0.):
    pool, frames, motion, lock, calls, boxes = patterned_case(tmp_path, monkeypatch, kind, origin)
    video = tmp_path/"synthetic-never-decode.mp4"; video.write_bytes(b"synthetic source identity only; never media")
    manifest = motion["continuous_tracking"]
    manifest["source_sha256"] = ct.file_sha256(video)
    manifest["pool_directory"] = pool.name
    manifest["geometry"] = dict(content_width=640, content_height=240, pad_left=0, pad_top=0,
        source_width=640, source_height=240, sample_aspect_ratio="0:1", rotation=[], autorotate=True, filter="synthetic")
    if start:
        for row in manifest["observations"]:
            row["timestamp"] += start; row["source_pts"] += round(start*600); row["source_pts_time"] += start
        manifest["window_start"] += start; manifest["window_end"] += start; manifest["coverage_end"] += start
        for b in manifest["pose_bindings"]: b["source_pts"] += round(start*600)
    motion["slow_motion_scale"] = scale
    original_frames = tmp_path/"frames"; original_frames.mkdir()
    for frame in frames: shutil.copyfile(frame, original_frames/frame.name)
    if kind == "support_missing": boxes[7] = []
    if kind == "wrong_target": boxes[6].append((362.,44.,450.,200.,.95))
    if kind == "nested":
        for i in range(6,12): boxes[i].append((100.,44.,192.,200.,.95))
    _, diagnostics, summary = ct.track_bound_pose_frames(frames, lock, manifest, pool, record_receipts=True)
    # The 'different' positive really fails the original frozen reference. Other
    # negative controls model a stored failed automatic branch independently.
    if kind == "different":
        assert all(d["identity_status"] == "identity_unconfirmed" for d in diagnostics[6:])
    else:
        for state in summary["observation_states"]:
            if state["index"] >= 6: state["identity_status"] = "identity_unconfirmed"
    # Explicit synthetic full receipts for every fixture JPEG, including images
    # the failed automatic branch did not request. No historical receipt is filled.
    summary["detection_receipts"] = [dict(observation_index=i,
        image_sha256=row["sha256"], source_sha256=manifest["source_sha256"],
        source_pts=row["source_pts"], source_time_base=row["source_time_base"],
        detector_config={"classes":[0],"confidence":.4,"scope":"full_frame_only"},
        candidates=[list(b) for b in boxes[i]], complete=True)
        for i,row in enumerate(manifest["observations"])]
    lock["continuous_tracking_summary"] = summary
    lock["pose_frame_bindings"] = manifest["pose_bindings"]
    original = dict(id="synthetic-segment", video_path=str(video), status="completed", action_type="free skating",
        pose_data={"connections": [], "frames": [], "original_failure": "window_exhausted"},
        frame_motion_scores=motion, target_lock=lock, report={"summary": "original automatic failure"}, processing_logs=[])
    engine = create_async_engine("sqlite+aiosqlite:///"+str(tmp_path/"auxiliary.db"))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async def seed():
        async with engine.begin() as connection: await connection.run_sync(models.Base.metadata.create_all)
        async with sessions() as session:
            session.add(models.Analysis(**original)); await session.commit()
    asyncio.run(seed())
    async def dependency():
        async with sessions() as session: yield session
    async def parent(*args): pass
    monkeypatch.setattr(routes, "require_parent_pin", parent)
    class SyntheticPose:
        def __init__(self, **kwargs): pass
        def process(self, image):
            ps = _keypoints(com_y=.4, knee_state="straight")
            return SimpleNamespace(pose_landmarks=SimpleNamespace(landmark=[SimpleNamespace(**{k:p[k] for k in ("x","y","z","visibility")}) for p in ps]))
        def close(self): pass
    monkeypatch.setitem(sys.modules, "mediapipe", SimpleNamespace(solutions=SimpleNamespace(pose=SimpleNamespace(Pose=SyntheticPose))))
    monkeypatch.setattr(poses, "_resolve_tasks_landmarker", lambda: None)
    app = FastAPI(); app.include_router(analysis_v2.router); app.dependency_overrides[get_session] = dependency
    client = TestClient(app)
    client.__enter__(); _clients.append(client)
    base = "/api/analysis/synthetic-segment/identity/segments"
    return SimpleNamespace(client=client, app=app, sessions=sessions, engine=engine, base=base,
        original=copy.deepcopy(original), calls=calls, boxes=boxes, pool=pool, motion=motion)


def choose(c, index=6, candidate=0):
    response = c.client.get(c.base); assert response.status_code == 200, response.text
    data = response.json()
    row = next(r for r in data["observations"] if r["observation_index"] == index)
    return row["candidates"][candidate]["selection"], data


def submit(c, selection=None, key="synthetic-key-1"):
    selection = selection or choose(c)[0]
    preview = c.client.post(c.base+"/preview", json=selection)
    assert preview.status_code == 200, preview.text
    body = dict(selection=selection, preview_digest=preview.json()["preview_digest"], idempotency_key=key,
                confirmation="confirm_manual_segment_target")
    response = c.client.post(c.base+"/confirm", json=body)
    assert response.status_code == 202, response.text
    return response.json(), body, preview.json()


def read(c, revision=1):
    detail = c.client.get(c.base+f"/revisions/{revision}"); pose = c.client.get(c.base+f"/revisions/{revision}/pose")
    assert detail.status_code == pose.status_code == 200, (detail.text, pose.text)
    return detail.json(), pose.json()


@pytest.mark.parametrize("origin,scale,start", [(9.,1.,0.),(-9.,4.,.7),(9.,4.,.5),(-9.,1.,0.)])
def test_production_confirm_saved_chain(tmp_path, monkeypatch, origin, scale, start):
    c = case(tmp_path, monkeypatch, origin=origin, scale=scale, start=start)
    selection, candidate_get = choose(c)
    counts_before = len(c.calls)
    with patch.object(AsyncSession, "commit", new=AsyncMock(side_effect=AssertionError("preview wrote database"))), patch.object(AsyncSession,"flush",new=AsyncMock(side_effect=AssertionError("preview flushed"))):
        p = c.client.post(c.base+"/preview", json=selection); assert p.status_code == 200
        assert c.client.get(c.base).json() == candidate_get
    submitted, body, preview = submit(c, selection)
    assert submitted["status"] == "submitted" and submitted["parent_revision"] == 0
    detail, pose = read(c)
    assert detail["status"] == "success", detail
    assert pose["effective_fps"] == 1/c.motion["continuous_tracking"]["period_sec"]
    assert [bool(f["keypoints"]) for f in pose["frames"]] == [False,False,True,True,True,True]
    assert detail["identity_source"] == "manual_segment_selection" and not detail["automatic_cross_gap_identity"]
    assert not detail["profile_evidence"]["jump_gate_passed"] and detail["analysis_profile"] == "step"
    assert detail["report"]["summary"] and not detail["video_overlay_allowed"]
    assert all(node.get("frame_id") is None and node.get("timestamp") is None for node in detail["report"].get("jump_stages", {}).values())
    assert len(c.calls) == counts_before, "local production must only consume saved receipts"
    images = {}; image_bytes = {}
    forbidden = AsyncMock(side_effect=AssertionError("saved GET wrote database"))
    with patch.object(AsyncSession, "commit", new=forbidden), patch.object(AsyncSession, "flush", new=forbidden), patch.object(poses, "extract_pose", side_effect=AssertionError("GET pose inference")), patch.object(PersonBBoxTracker,"_detect",side_effect=AssertionError("GET detection")):
        for _ in range(2):
            assert read(c) == (detail,pose)
            for f in pose["frames"]:
                t = f["temporal"]; b = t["binding"]
                expected = b["source_pts"]/600-origin
                if f["keypoints"]:
                    assert t["playback_timestamp"] == pytest.approx(expected)
                    assert t["analysis_timestamp"] == pytest.approx(expected/scale)
                else:
                    # Saved JPEG clocks remain valid independently of pose eligibility.
                    assert t["binding"]["observation_index"] in (6, 7)
                url = pose["frame_urls"][f["frame"]]
                image = c.client.get(url); assert image.status_code == 200
                original = c.pool / c.motion["continuous_tracking"]["observations"][b["observation_index"]]["file"]
                assert image.content == original.read_bytes()
                images[f["frame"]] = ct.file_sha256(original)
                image_bytes[f["frame"]] = base64.b64encode(image.content).decode("ascii")
        forbidden.assert_not_awaited()
    async def reopen():
        await c.engine.dispose()
        other = create_async_engine("sqlite+aiosqlite:///"+str(tmp_path/"auxiliary.db"))
        async with async_sessionmaker(other, expire_on_commit=False)() as session:
            original = await session.get(models.Analysis,"synthetic-segment")
            for k,v in c.original.items(): assert getattr(original,k) == v, k
            revision = await session.scalar(select(models.SegmentReanchorRevision))
            assert revision.result["pose"]["frames"][2]["keypoints"]
            local_motion=revision.result["motion"]["selected"]
            assert all(r["motion_interval"] is None and r["motion_score"] is None for r in local_motion[:3])
            assert all(r["source_thumb_index"] >= 6 for r in local_motion)
            from app.services.jump_projection import extract_projection
            assert len(extract_projection(revision.result["pose"],revision.result["motion"])["segments"])==1
        await other.dispose()
    asyncio.run(reopen())
    if origin==9. and scale==1.:
        save("get-chain",dict(source_get=candidate_get,preview=preview,submitted=submitted,detail=detail,pose=pose,images=images,image_bytes=image_bytes,
            synthetic_detection=True,synthetic_landmarks=True,zero_real_model=True,sqlite_reopened=True,get_writes=0))
    duplicate = c.client.post(c.base+"/confirm", json=body); assert duplicate.status_code == 202
    assert duplicate.json()["revision"] == 1 and duplicate.json()["status"] == "success"
    changed = copy.deepcopy(body); changed["selection"]["candidate_index"] = 1
    assert c.client.post(c.base+"/confirm", json=changed).status_code == 409


@pytest.mark.parametrize("damage", ["source_hash","image_hash","analysis","segment","pts","timebase","origin","scale","bbox","geometry","binding","receipt","bool_pts","bool_revision","bool_bbox","nan"])
def test_invalid_selection_rejected(tmp_path, monkeypatch, damage):
    c=case(tmp_path,monkeypatch); selected,_=choose(c)
    key={"source_hash":"source_sha256","image_hash":"image_sha256","analysis":"analysis_id","segment":"segment","pts":"source_pts","timebase":"source_time_base","origin":"source_origin_sec","scale":"slow_motion_scale","bbox":"bbox","geometry":"geometry_digest","binding":"binding_digest","receipt":"receipt_digest","bool_pts":"source_pts","bool_revision":"expected_revision","bool_bbox":"bbox","nan":"slow_motion_scale"}[damage]
    if damage in ("source_hash","image_hash","geometry","binding","receipt"): selected[key]="0"*64
    elif damage=="analysis": selected[key]="other-analysis"
    elif damage=="timebase": selected[key]="1/30"
    elif damage=="bbox": selected[key]=[-1.,0.,900.,500.]
    elif damage in ("bool_pts","bool_revision"): selected[key]=True
    elif damage=="bool_bbox": selected[key]=[True,0.,1.,2.]
    elif damage=="nan":
        # Raw JSON is deliberate: ensure server rejects nonfinite before DB work.
        raw=json.dumps({**selected,key:float("nan")})
        assert c.client.post(c.base+"/preview",content=raw,headers={"Content-Type":"application/json"}).status_code==422
        return
    else: selected[key]+=1
    assert c.client.post(c.base+"/preview",json=selected).status_code==422
    assert c.client.get(c.base).json()["revisions"]==[]


@pytest.mark.parametrize("kind,expected",[("ambiguous",[False]*6),("alternating",[False]*6),("after_switch",[False,False,True,True,False,False]),("different",[False,False,True,True,True,True])])
def test_identity_controls(tmp_path,monkeypatch,kind,expected):
    c=case(tmp_path,monkeypatch,kind); submit(c); detail,pose=read(c)
    actual=[bool(f["keypoints"]) for f in pose["frames"]]
    assert actual==expected,(actual,detail)
    if not any(expected): assert detail["status"]=="insufficient"
    save("negative-"+kind,dict(detail=detail,pose=pose,synthetic_detection=True,synthetic_landmarks=True))


@pytest.mark.parametrize("expected",[1,5])
def test_server_version_jump_rejected(tmp_path,monkeypatch,expected):
    c=case(tmp_path,monkeypatch); selected,_=choose(c); selected["expected_revision"]=expected
    assert c.client.post(c.base+"/preview",json=selected).status_code==409


@pytest.mark.parametrize("same_key",[False,True])
def test_concurrent_confirm_one_winner_and_failure_readback(tmp_path,monkeypatch,same_key):
    c=case(tmp_path,monkeypatch); selected,_=choose(c)
    token=c.client.post(c.base+"/preview",json=selected).json()["preview_digest"]
    executions=[]
    def fail(*args): executions.append(1); raise RuntimeError("synthetic processing fault")
    monkeypatch.setattr(service,"execute_local",fail)
    async def concurrent():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=c.app),base_url="http://offline") as client:
            return await asyncio.gather(*[client.post(c.base+"/confirm",json=dict(selection=selected,preview_digest=token,idempotency_key=f"concurrent-key-{0 if same_key else i}",confirmation="confirm_manual_segment_target")) for i in range(2)])
    responses=asyncio.run(concurrent())
    assert sorted(r.status_code for r in responses)==([202,202] if same_key else [202,409])
    assert len(executions)==1
    detail,pose=read(c); assert detail["status"]=="failed" and "synthetic processing fault" in detail["error"] and pose["frames"]==[]
    selected,_=choose(c); assert selected["expected_revision"]==1
    # Reanchoring same segment invalidates prior auxiliary result but never parent.
    submit(c,selected,key="next-anchor-key")
    assert read(c,1)[0]["superseded"] is True
    save("concurrency-and-failure-"+str(same_key),dict(statuses=[r.status_code for r in responses],executions=len(executions),detail=detail,readback=read(c,1)[0]))


def test_missing_or_corrupt_receipt_no_fallback(tmp_path,monkeypatch):
    c=case(tmp_path,monkeypatch)
    async def damage():
        async with c.sessions() as session:
            row=await session.get(models.Analysis,"synthetic-segment"); lock=copy.deepcopy(row.target_lock)
            lock["continuous_tracking_summary"]["detection_receipts"]=[r for r in lock["continuous_tracking_summary"]["detection_receipts"] if r["observation_index"]!=7]
            row.target_lock=lock; await session.commit()
    asyncio.run(damage())
    selected,data=choose(c); assert any(r["observation_index"]==7 for r in data["unavailable"])
    assert c.client.post(c.base+"/preview",json=selected).status_code==422
    assert c.client.get(c.base+"/images/7?saved_only=true").status_code==404


@pytest.mark.parametrize("kind,candidate",[("support_missing",0),("wrong_target",1),("nested",0)])
def test_manual_selection_cannot_force_pose(tmp_path,monkeypatch,kind,candidate):
    c=case(tmp_path,monkeypatch,kind); selected,_=choose(c,candidate=candidate)
    submit(c,selected); detail,pose=read(c)
    assert detail["status"]=="insufficient",detail
    assert not any(f["keypoints"] for f in pose["frames"])
    save("refusal-"+kind,dict(detail=detail,pose=pose,synthetic_detection=True,synthetic_landmarks=True))


@pytest.mark.parametrize("damage",["jpeg","source","clock_bool","clock_mapping","receipt_bbox_bool","receipt_pts_bool","parent_binding","geometry","missing_file","path"])
def test_stored_evidence_corruption_unavailable(tmp_path,monkeypatch,damage):
    c=case(tmp_path,monkeypatch); selected,_=choose(c)
    async def corrupt():
        async with c.sessions() as session:
            row=await session.get(models.Analysis,"synthetic-segment")
            m=copy.deepcopy(row.frame_motion_scores); lock=copy.deepcopy(row.target_lock)
            manifest=m["continuous_tracking"]
            if damage=="jpeg": (c.pool/manifest["observations"][6]["file"]).write_bytes(b"changed")
            elif damage=="source": Path(row.video_path).write_bytes(b"changed source")
            elif damage=="clock_bool": manifest["observations"][6]["source_pts"]=True
            elif damage=="clock_mapping": manifest["observations"][6]["timestamp"]+=.01
            elif damage=="receipt_bbox_bool": lock["continuous_tracking_summary"]["detection_receipts"][6]["candidates"][0][0]=True
            elif damage=="receipt_pts_bool": lock["continuous_tracking_summary"]["detection_receipts"][6]["source_pts"]=True
            elif damage=="parent_binding": manifest["pose_bindings"][6]["sha256"]="0"*64
            elif damage=="geometry": manifest["geometry"]["pad_left"]=True
            elif damage=="missing_file": (c.pool/manifest["observations"][6]["file"]).unlink()
            elif damage=="path": manifest["observations"][6]["file"]="../synthetic-never-decode.mp4"
            row.frame_motion_scores=m; row.target_lock=lock; await session.commit()
    asyncio.run(corrupt())
    response=c.client.post(c.base+"/preview",json=selected)
    assert response.status_code==422,response.text
    data=c.client.get(c.base).json(); assert data["unavailable"] and data["revisions"]==[]


def test_preview_snapshot_changed_and_parent_gate(tmp_path,monkeypatch):
    c=case(tmp_path,monkeypatch); selected,_=choose(c)
    preview=c.client.post(c.base+"/preview",json=selected).json()
    body=dict(selection=selected,preview_digest="0"*64,idempotency_key="preview-conflict",confirmation="confirm_manual_segment_target")
    assert c.client.post(c.base+"/confirm",json=body).status_code==409
    # Before worker execution, the same digest is checked against all saved inputs.
    with pytest.raises(service.EvidenceUnavailable,match="preview_evidence_changed"):
        service.execute_local(models.Analysis(**c.original), selected, 1, "0"*64)
    from fastapi import HTTPException
    async def denied(*args): raise HTTPException(403,"parent_pin_required")
    monkeypatch.setattr(routes,"require_parent_pin",denied)
    assert c.client.get(c.base).status_code==403
    assert c.client.post(c.base+"/preview",json=selected).status_code==403
    body["preview_digest"]=preview["preview_digest"]
    assert c.client.post(c.base+"/confirm",json=body).status_code==403


@pytest.mark.parametrize("profile",["web-preview","legacy-analysis-preview"])
def test_existing_trial_gate_remains_closed(tmp_path,monkeypatch,profile):
    c=case(tmp_path,monkeypatch); selected,_=choose(c)
    monkeypatch.setenv("SKATING_TRIAL_PROFILE",profile)
    monkeypatch.setattr(service,"load_source",lambda *a: (_ for _ in ()).throw(AssertionError("trial accessed evidence")))
    assert c.client.get(c.base).status_code==403
    assert c.client.post(c.base+"/preview",json=selected).status_code==403



def test_anchor_at_segment_tail_has_no_three_frame_support(tmp_path,monkeypatch):
    c=case(tmp_path,monkeypatch); selected,_=choose(c,index=11)
    submit(c,selected); detail,pose=read(c)
    assert detail["status"]=="insufficient" and len(pose["frames"])==1
    assert not pose["frames"][0]["keypoints"]
