"""Stage support integrity, authoritative evaluation and replay data contracts."""
import copy
import pytest
from test_tal_evidence_chain import timed_pose
from app.services.biomechanics import attach_key_frame_candidates
from app.services.jump_features import compute_jump_evidence
from app.services.auto_eval import build_auto_eval_payload

@pytest.mark.parametrize('defect',['pts','timebase','scale','explicit_invalid','identity','binding','irregular'])
def test_middle_support_must_be_revalidated(defect):
    pose,motion=timed_pose()
    before=attach_key_frame_candidates({},pose,motion,'jump',20.)
    assert all(a['status']=='available' for a in before['jump_stage_anchors'].values())
    middle=len(pose['frames'])//2
    frame=pose['frames'][middle]
    if defect=='pts': frame['temporal']['binding']['source_pts']+=100
    if defect=='timebase': frame['temporal']['binding']['source_time_base']='0/0'
    if defect=='scale': frame['temporal']['slow_motion_scale']=3.
    if defect=='explicit_invalid': frame['temporal']['time_valid']=False
    if defect=='identity': frame['identity_id']='other'
    if defect=='binding': frame['input_binding_valid']=False
    if defect=='irregular':
        frame['timestamp']+=.02
        frame['temporal']['analysis_timestamp']+=.01
        frame['temporal']['playback_timestamp']+=.02
        frame['temporal']['binding']['source_pts']+=.2
    evidence=compute_jump_evidence(pose,before['jump_stage_anchors'],20.)
    assert evidence['anchor']['status']=='unavailable'
    assert evidence['toe_pick_pulse'] is None
    current=attach_key_frame_candidates({},pose,motion,'jump',20.)
    for a in current['jump_stage_anchors'].values():
        if a['status']=='available':
            indices=[r['pose_index'] for r in a['evidence']['support_frames']]
            if defect!='irregular': assert middle not in indices
            assert not min(indices)<middle<max(indices)

@pytest.mark.parametrize('scale',[1.,2.,4.])
def test_valid_source_time_and_irregular_spacing_remain_usable(scale):
    pose,motion=timed_pose(scale)
    # A regular sequence and a small consistent PTS perturbation are both valid.
    for perturb in (False,True):
        p=copy.deepcopy(pose)
        if perturb:
            f=p['frames'][4]; t=f['temporal']
            t['binding']['source_pts']+=.01
            t['playback_timestamp']+=.001
            t['analysis_timestamp']+=.001/scale
            f['timestamp']+=.001
        b=attach_key_frame_candidates({},p,None,'jump',20.)
        assert any(a['status']=='available' for a in b['jump_stage_anchors'].values())
        for a in b['jump_stage_anchors'].values():
            if a['status']=='available': assert compute_jump_evidence(p,{'T':a},20.)['anchor']['status']=='available'


def test_auto_eval_rejected_authority_does_not_resurrect_candidates():
    pose,motion=timed_pose()
    b=attach_key_frame_candidates({},pose,motion,'jump',20.)
    for a in b['jump_stage_anchors'].values():
        a.update(status='unavailable',reason='stage_anchor_bound_time_invalid')
        a['quality_flags'].append('stage_anchor_bound_time_invalid')
    result=build_auto_eval_payload(b,{},motion,'jump')
    assert result['key_frame_order_valid'] is None
    assert result['key_frame_signature_source']=='jump_stage_anchors'
    assert 'frame_' not in result['key_frame_signature']
    assert not result['high_confidence_conflicts']
    assert 'stage_anchor_bound_time_invalid' in str(result['stage_anchor_rejections'])
    assert 'frame_' in result['candidate_key_frame_signature']  # diagnostic only

def test_saved_only_frame_read_never_restores_or_backfills(tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from fastapi import HTTPException
    from app.routers import analysis as router
    frames = tmp_path / "frames"
    frames.mkdir()
    (frames / "frame_0001.jpg").write_bytes(b"saved-image-bytes-no-decode")
    row = SimpleNamespace(id="generic", video_path=str(tmp_path / "source.mp4"))
    session = SimpleNamespace(get=AsyncMock(return_value=row))
    restore = AsyncMock(side_effect=AssertionError("saved-only read may not restore"))
    backfill = AsyncMock(side_effect=AssertionError("saved-only read may not backfill"))
    monkeypatch.setattr(router, "_restore_missing_analysis_frames", restore)
    monkeypatch.setattr(router, "_backfill_frame_if_needed", backfill)
    response = asyncio.run(router.get_frame("generic", "frame_0001.jpg", session=session, saved_only=True))
    assert response.path == frames / "frame_0001.jpg"
    with pytest.raises(HTTPException) as error:
        asyncio.run(router.get_frame("generic", "frame_missing.jpg", session=session, saved_only=True))
    assert error.value.status_code == 404
    restore.assert_not_awaited()
    backfill.assert_not_awaited()


def test_motion_only_diagnostic_cannot_be_current_replay_stage():
    pose,motion=timed_pose()
    for frame in pose['frames']:
        for point in frame['keypoints']: point['quality']={'analysis_usable':False}
    bio=attach_key_frame_candidates({},pose,motion,'jump',20.)
    assert any(bio['key_frame_candidates'][key]['frame_id'] for key in ('T','A','L'))
    assert all(a['status']=='unavailable' for a in bio['jump_stage_anchors'].values())
    for key in ('takeoff','apex','landing'):
        assert bio['jump_stages'][key]['status']=='unavailable'
        assert bio['jump_stages'][key]['image_ref'] is None
        assert 'stage_anchor_pose_unusable' in bio['jump_stages'][key]['reason']
