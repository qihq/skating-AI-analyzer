"""Offline production build -> report -> SQLite -> HTTP GET -> jump replay."""
import asyncio
import copy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from test_analysis_keyframe_candidates import _pose_data, _motion_scores
from test_tal_evidence_chain import timed_pose


def consume_contract(tmp_path, pose, motion, profile, *, name="tal", fps=10., saved_images=None, missing_image_names=(), pipeline_version=None):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from app import models
    from app.routers import analysis as router
    from app.services import report as reports
    from app.services.jump_features import compute_jump_evidence
    from app.services.pipeline_version import CURRENT_PIPELINE_VERSION
    from app.analysis_v2.presentation import present_legacy_record

    for filename, content in (saved_images or {}).items():
        folder = tmp_path / "frames"
        folder.mkdir(exist_ok=True)
        (folder / filename).write_bytes(content)
    calls = []
    real = router.infer_jump_subtype_evidence
    def capture(p, anchors, rate):
        calls.append(copy.deepcopy(anchors))
        return real(p, anchors, rate)
    sampling = SimpleNamespace(effective_fps=fps, source_fps=30., window_start_sec=0., window_end_sec=2.)
    with patch.object(router, "infer_jump_subtype_evidence", side_effect=capture):
        bio = router._build_bio_data_for_profile(pose_data=pose, motion_scores=motion,
            action_type="unlabelled motion", analysis_profile=profile, sampling_metadata=sampling,
            profile_evidence={"profile_route_only": True, "negative_constraints": ["jump_type_unconfirmed"]}, target_lock={})
    if profile == "jump":
        assert calls and calls[0] == bio["jump_stage_anchors"]
    with patch("app.trial.external_ai_allowed", return_value=False):
        report = asyncio.run(reports.generate_report("unlabelled motion", {}, bio))
    assert report["jump_stages"] == bio["jump_stages"]
    assert report["jump_measurements"] == bio["jump_measurements"]
    engine = create_async_engine("sqlite+aiosqlite:///"+str(tmp_path/(name+".db")))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async def seed():
        async with engine.begin() as connection:
            await connection.run_sync(models.Analysis.metadata.create_all)
        async with sessions() as session:
            row = models.Analysis(id=name, action_type="unlabelled motion", analysis_profile=profile,
                status="completed", pipeline_version=pipeline_version or CURRENT_PIPELINE_VERSION,
                video_path=str(tmp_path/"absent-source.mp4"), pose_data=pose,
                frame_motion_scores=motion, bio_data=bio, report=report)
            session.add(row)
            await session.commit()
    asyncio.run(seed())
    async def session_override():
        async with sessions() as session:
            yield session
    app = FastAPI()
    app.include_router(router.router)
    app.include_router(router.frames_router)
    app.dependency_overrides[router.get_session] = session_override
    forbidden = AssertionError("GET may not infer, decode, restore or write")
    with (patch.object(router, "extract_pose", side_effect=forbidden),
          patch.object(router, "_restore_missing_analysis_frames", AsyncMock(side_effect=forbidden)),
          patch.object(router, "_restore_completed_report_save_failure", AsyncMock(side_effect=forbidden)),
          patch.object(router, "_backfill_frame_if_needed", AsyncMock(side_effect=forbidden)),
          patch.object(AsyncSession, "commit", AsyncMock(side_effect=forbidden)) as commit,
          patch.object(AsyncSession, "flush", AsyncMock(side_effect=forbidden)),
          TestClient(app) as client):
        detail = client.get("/api/analysis/"+name)
        saved_pose = client.get("/api/analysis/"+name+"/pose")
        assert detail.status_code == saved_pose.status_code == 200, (detail.text, saved_pose.text)
        detail = detail.json()
        saved_pose = saved_pose.json()
        assert client.get("/api/analysis/"+name).json() == detail
        assert client.get("/api/analysis/"+name+"/pose").json() == saved_pose
        import hashlib
        image_reads = {}
        for filename, content in (saved_images or {}).items():
            image = client.get("/api/frames/"+name+"/"+filename+"?saved_only=true")
            assert image.status_code == 200 and image.content == content
            image_reads[filename] = hashlib.sha256(image.content).hexdigest()
        for filename in missing_image_names:
            assert client.get("/api/frames/"+name+"/"+filename+"?saved_only=true").status_code == 404
        assert client.get("/api/frames/"+name+"/frame_absent.jpg?saved_only=true").status_code == 404
        assert detail["bio_data"] == bio
        # Existing GET adds score provenance to its response without rewriting storage.
        response_report = copy.deepcopy(detail["report"])
        assert response_report.pop("subscores_source") == "unscored_local"
        assert response_report == report
        assert len(saved_pose["frames"]) == len(pose["frames"])
        for a,b in zip(pose["frames"],saved_pose["frames"],strict=True):
            assert a.get("temporal") == b.get("temporal")
            assert a.get("projection_geometry") == b.get("projection_geometry")
            assert a.get("identity_id") == b.get("identity_id")
            assert a.get("event_id") == b.get("event_id")
            for x,y in zip(a["keypoints"],b["keypoints"],strict=True):
                for field in ("id","x","y","z","visibility","quality","interpolated"):
                    assert x.get(field) == y.get(field)
        commit.assert_not_awaited()
    replay = compute_jump_evidence(saved_pose, detail["bio_data"]["jump_stage_anchors"], fps)
    direct = compute_jump_evidence(pose, bio["jump_stage_anchors"], fps)
    assert replay == direct
    async def readback():
        async with sessions() as session:
            row = await session.get(models.Analysis, name)
            assert row.bio_data == bio and row.report == report and row.pose_data == pose
            experience = present_legacy_record(row).model_dump(mode="json")
        await engine.dispose()
        return experience
    experience = asyncio.run(readback())
    return {"experience":experience, "detail":detail, "pose":saved_pose, "image_reads":image_reads, "jump_evidence":replay, "production_jump_calls":calls,
            "missing_image_names": list(missing_image_names), "database":name+".db", "http":{"detail":200,"pose":200,"commit_calls":0}}


@pytest.mark.parametrize("profile", ["jump", "step"])
def test_production_result_report_and_http_roundtrip(tmp_path, profile):
    pose, motion = timed_pose()
    result = consume_contract(tmp_path, pose, motion, profile, fps=20.)
    stages = result["detail"]["bio_data"]["jump_stages"]
    if profile == "jump":
        assert stages["takeoff"]["status"] == stages["apex"]["status"] == stages["landing"]["status"] == "candidate"
        assert stages["pull-in"]["status"] == "unavailable"
        assert stages["rotation"]["status"] == "unavailable"
        assert result["jump_evidence"]["anchor"]["source"] == "key_frame_candidates"
    else:
        assert all(s["status"] == "not_applicable" for s in stages.values())


def test_invalid_anchor_and_null_measurements_survive_actual_http(tmp_path):
    pose, motion = timed_pose()
    for f in pose["frames"]:
        for p in f["keypoints"]:
            p["quality"] = {"analysis_usable": False, "source": "display_interpolation"}
    result = consume_contract(tmp_path, pose, motion, "jump", fps=20.)
    assert result["jump_evidence"]["anchor"]["status"] == "unavailable"
    assert result["jump_evidence"]["toe_pick_pulse"] is None
    measurements = result["detail"]["report"]["jump_measurements"]
    assert all(m["value"] is None for m in measurements.values())
