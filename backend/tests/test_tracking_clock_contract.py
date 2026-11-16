"""Offline production clock contract; only saved/synthetic JPEGs and detector stubs."""
import asyncio
import copy
import json
import os
import shutil
import socket
import subprocess
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from app.services import continuous_tracking as ct
from app.services.person_tracker import PersonBBoxTracker


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    loop = asyncio.new_event_loop()
    portal_loop = asyncio.new_event_loop()  # Windows self-pipe before network guards.
    monkeypatch.setattr(asyncio.get_event_loop_policy(), 'new_event_loop', lambda: portal_loop)
    monkeypatch.setattr(asyncio, 'run', lambda coro: loop.run_until_complete(coro))
    def forbidden(*args, **kwargs):
        raise AssertionError('TRACK-CLOCK: decode/network/model forbidden')
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(PersonBBoxTracker, '_get_yolo_model', forbidden)
    from app.services import pose, video
    monkeypatch.setattr(pose, '_resolve_tasks_landmarker', forbidden)
    monkeypatch.setattr(video, '_run_ffmpeg', forbidden)
    monkeypatch.setattr(ct, '_probe', forbidden)
    yield
    loop.close()
    if not portal_loop.is_closed(): portal_loop.close()


def fixture_pool(tmp_path, pts=(0,60,120,200,260), *, origin=0., scale=1.):
    pool=tmp_path/'pool'; pool.mkdir()
    pose=tmp_path/'pose'; pose.mkdir()
    rows=[]
    for i,p in enumerate(pts):
        image=pool/f'observation_{i:04d}.jpg'
        cv2.imwrite(str(image), np.full((240,640,3), i*10, np.uint8))
        rows.append(dict(index=i,file=image.name,sha256=ct.file_sha256(image),
            source_pts=p,source_time_base='1/600',source_pts_time=p/600.,timestamp=p/600.-origin))
    m=dict(version=1,source_origin_sec=origin,period_sec=.1,window_start=rows[0]['timestamp'],
        window_end=rows[-1]['timestamp']+.1,coverage_end=rows[-1]['timestamp'],
        canvas=dict(width=640,height=240),pose_bindings=[],observations=rows)
    return pool,pose,m


def run_prepare(tmp_path, monkeypatch, m, pool, pose, wanted=None, scale=1.):
    if wanted is None: wanted=[r['timestamp'] for r in m['observations']]
    old=[]
    for i in range(len(wanted)):
        p=pose/f'frame_{i+1:04d}.jpg'; p.write_bytes(b'old-unbound-image'); old.append(p)
    async def extract(*a,**kw): return copy.deepcopy(m)
    monkeypatch.setattr(ct,'extract_tracking_pool',extract)
    return asyncio.run(ct.prepare_continuous_pose_inputs(tmp_path/'never-open.mp4',pose,pool,old,
        dict(window_start=m['window_start'],window_end=m['window_end'],slow_motion_scale=scale,
             selected=[dict(timestamp=t) for t in wanted]),SimpleNamespace(effective_fps=1.)))


@pytest.mark.parametrize('pts',[(0,60,120,180,240),(0,60,120,200,260)])
def test_actual_prepare_accepts_trusted_clock(tmp_path,monkeypatch,pts):
    pool,pose,m=fixture_pool(tmp_path,pts)
    frames,motion=run_prepare(tmp_path,monkeypatch,m,pool,pose)
    assert len(frames)==5
    assert [r['timestamp'] for r in motion['selected']]==[p/600 for p in pts]
    if pts[3]==200:
        gap=motion['motion_records'][3]
        assert gap['observation_valid'] is True
        assert gap['continuity_reason']=='tracking_clock_gap'
        assert gap['motion_interval'] is None and gap['motion_score'] is None
        assert motion['motion_records'][4]['motion_status']=='valid'


@pytest.mark.parametrize('damage',[
    'hash','missing_image','index_bool','missing_pts','bool_pts','duplicate_pts','backward_pts',
    'bad_timebase','zero_timebase','negative_timebase','bool_timebase',
    'timestamp_nan','timestamp_inf','source_pts_time_nan','source_pts_time_inf',
    'origin_nan','origin_inf','period_nan','period_inf','window_start_nan','window_end_inf',
    'coverage_nan','clock_mismatch','out_of_window','scale_nan','scale_inf','scale_zero'])
def test_actual_prepare_rejects_untrusted_inputs_before_unlink(tmp_path,monkeypatch,damage):
    pool,pose,m=fixture_pool(tmp_path,(0,60,120,180,240)); r=m['observations'][2]; scale=1.
    if damage=='hash': r['sha256']='0'*64
    elif damage=='missing_image': (pool/r['file']).unlink()
    elif damage=='index_bool': m['observations'][1]['index']=True
    elif damage=='missing_pts': r.pop('source_pts')
    elif damage=='bool_pts': r['source_pts']=True
    elif damage in ('duplicate_pts','backward_pts'):
        r['source_pts']=60 if damage=='duplicate_pts' else 30
        r['source_pts_time']=r['timestamp']=r['source_pts']/600.
    elif damage.endswith('timebase'):
        r['source_time_base']={'bad_timebase':'bad','zero_timebase':'0/600',
            'negative_timebase':'-1/600','bool_timebase':True}[damage]
    elif damage in ('origin_nan','origin_inf'): m['source_origin_sec']=float(damage.split('_')[1])
    elif damage.startswith('period_'): m['period_sec']=float(damage.split('_')[1])
    elif damage=='window_start_nan': m['window_start']=float('nan')
    elif damage=='window_end_inf': m['window_end']=float('inf')
    elif damage=='coverage_nan': m['coverage_end']=float('nan')
    elif damage.startswith('scale_'): scale=0. if damage=='scale_zero' else float(damage.split('_')[1])
    elif damage=='clock_mismatch': r['timestamp']+=.01
    elif damage=='out_of_window': m['window_end']=.3
    else:
        field,kind=damage.rsplit('_',1); r[field]=float(kind)
    with pytest.raises((ValueError,TypeError,OverflowError)):
        run_prepare(tmp_path,monkeypatch,m,pool,pose,scale=scale)
    assert (pose/'frame_0001.jpg').read_bytes()==b'old-unbound-image'


def test_gap_selection_has_bounded_support(tmp_path,monkeypatch):
    pool,pose,m=fixture_pool(tmp_path)
    wanted=[-.01,0.,.15,.2,.25,200/600,.4,260/600,.44,.55]
    frames,motion=run_prepare(tmp_path,monkeypatch,m,pool,pose,wanted)
    assert motion['unrepresented_pose_targets']==[-.01,.25,.44,.55]
    assert [r['reason'] for r in motion['pose_target_selections'] if r['status']=='unrepresented']==[
        'outside_observation_coverage','tracking_clock_gap','outside_observation_coverage','outside_observation_coverage']
    for f,r,b in zip(frames,motion['selected'],motion['continuous_tracking']['pose_bindings']):
        assert ct.file_sha256(f)==r['sha256']==b['sha256']
        assert r['source_pts']==b['source_pts']


@pytest.mark.parametrize('scale',[1.,4.])
def test_multiple_segments_irregular_nonzero_clock(tmp_path,monkeypatch,scale):
    pts=(5400,5460,5526,5606,5666,5786,5846)
    pool,pose,m=fixture_pool(tmp_path,pts,origin=7.)
    frames,motion=run_prepare(tmp_path,monkeypatch,m,pool,pose,scale=scale)
    rows=motion['motion_records']
    assert [r['continuity_segment'] for r in rows]==[0,0,0,1,1,2,2]
    assert rows[2]['motion_interval']['source_duration_sec']==pytest.approx(.11)
    assert rows[3]['analysis_timestamp']==pytest.approx(m['observations'][3]['timestamp']/scale)
    assert rows[4]['motion_interval']['analysis_duration_sec']==pytest.approx(.1/scale)


@pytest.mark.parametrize('anchor',[0,2,3,4])
def test_anchor_propagates_only_within_its_segment(tmp_path,monkeypatch,anchor):
    from app.routers import analysis
    pool,pose,m=fixture_pool(tmp_path)
    frames,motion=run_prepare(tmp_path,monkeypatch,m,pool,pose)
    calls=[]
    def detect(self,image,**kw):
        calls.append(1); return [(100.,50.,200.,180.,.95)]
    monkeypatch.setattr(PersonBBoxTracker,'_detect',detect)
    lock=dict(selected_bbox=dict(x=100/640,y=50/240,width=100/640,height=130/240),
              manual_override=True,preview_frame_index=anchor)
    analysis._build_bbox_per_frame(frames,lock,1.,tracking_manifest=motion['continuous_tracking'],tracking_dir=pool)
    diagnostics=lock['person_tracker_diagnostics']
    expected=[i<3 if anchor<3 else i>=3 for i in range(5)]
    assert [d['input_binding_valid'] for d in diagnostics]==expected
    assert len(calls)==sum(expected)
    for i,d in enumerate(diagnostics):
        assert d['continuity_segment']==(0 if i<3 else 1)
        if not expected[i]: assert 'tracking_clock_gap' in d['rejected_reasons']


def test_saved_105_actual_prepare(tmp_path,monkeypatch):
    saved=os.environ.get('TRACK_CLOCK_SAVED_FIXTURE')
    if not saved: pytest.skip('explicit copy of saved 105 JPEG fixture required')
    saved=Path(saved); pool=tmp_path/'pool'; shutil.copytree(saved/'pool',pool)
    pose=tmp_path/'pose'; pose.mkdir()
    m=json.loads((saved/'manifest.json').read_text(encoding='utf8'))
    frames,motion=run_prepare(tmp_path,monkeypatch,m,pool,pose)
    assert len(frames)==105
    rows=motion['motion_records']
    assert [i for i,r in enumerate(rows) if r.get('continuity_reason')=='tracking_clock_gap']==[44]
    assert rows[44]['timestamp']==pytest.approx(2660/600)
    assert rows[44]['motion_score'] is None and rows[45]['motion_score'] is not None
    assert [r['source_pts'] for r in rows]==[r['source_pts'] for r in m['observations']]
    assert [ct.file_sha256(f) for f in frames]==[r['sha256'] for r in m['observations']]

@pytest.mark.parametrize('field',['timestamp','source_pts_time'])
@pytest.mark.parametrize('value',[float('nan'),float('inf'),float('-inf'),True])
def test_nonfinite_redundant_clock_is_an_identity_error(tmp_path,field,value):
    pool,pose,m=fixture_pool(tmp_path)
    m['observations'][2][field]=value
    rows=ct.bound_motion_records(pool,m,1.)
    assert rows[2]['timestamp'] is None
    assert rows[2]['observation_valid'] is False
    assert rows[2]['identity_error']=='nonfinite_or_invalid_clock'


def test_canvas_change_splits_tracking_and_motion(tmp_path,monkeypatch):
    from app.routers import analysis
    pool,pose,m=fixture_pool(tmp_path,(0,60,120,180,240))
    for row in m['observations'][3:]:
        path=pool/row['file']; cv2.imwrite(str(path),np.full((120,320,3),40,np.uint8))
        row['sha256']=ct.file_sha256(path)
    frames,motion=run_prepare(tmp_path,monkeypatch,m,pool,pose)
    rows=motion['motion_records']
    assert rows[3]['timestamp']==.3 and rows[3]['motion_score'] is None
    assert rows[3]['continuity_reason']=='motion_canvas_changed'
    assert rows[4]['motion_score'] is not None
    monkeypatch.setattr(PersonBBoxTracker,'_detect',lambda *a,**kw:[(100.,50.,200.,180.,.95)])
    lock=dict(selected_bbox=dict(x=100/640,y=50/240,width=100/640,height=130/240),manual_override=True)
    analysis._build_bbox_per_frame(frames,lock,1.,tracking_manifest=motion['continuous_tracking'],tracking_dir=pool)
    assert [d['input_binding_valid'] for d in lock['person_tracker_diagnostics']]==[True,True,True,False,False]
    assert 'motion_canvas_changed' in lock['person_tracker_diagnostics'][3]['rejected_reasons']


@pytest.mark.parametrize('origin,scale',[(0.,1.),(7.,4.)])
def test_production_consumers_report_sqlite_get_preserve_segments(tmp_path,monkeypatch,origin,scale):
    import sys
    from app.services import pose as poses
    from app.services import keyframe_candidates as kc, target_lock as tl
    from app.routers import analysis
    from app.services.action_profiles import infer_analysis_profile
    from app.services.pose_observations import observation_slots, observation_time_error
    from test_analysis_keyframe_candidates import _keypoints
    from test_tal_persistence import consume_contract

    pts=tuple(round(origin*600)+i*60 for i in range(9))+tuple(round(origin*600)+600+i*60 for i in range(3))
    pool,pose_dir,m=fixture_pool(tmp_path,pts,origin=origin)
    frames,motion=run_prepare(tmp_path,monkeypatch,m,pool,pose_dir,scale=scale)
    detector_calls=[]; landmark_calls=[]
    def detect(self,image,**kwargs):
        detector_calls.append(1); return [(0.,0.,640.,240.,.95)]
    monkeypatch.setattr(PersonBBoxTracker,'_detect',detect)
    lock=dict(selected_bbox=dict(x=0.,y=0.,width=1.,height=1.),manual_override=True)
    boxes=analysis._build_bbox_per_frame(frames,lock,10.,tracking_manifest=motion['continuous_tracking'],tracking_dir=pool)
    class SyntheticPose:
        def __init__(self,**kwargs): pass
        def process(self,image):
            i=round(float(image.mean())/10); landmark_calls.append(i)
            com=[.4,.4,.3,.22,.2,.2,.25,.35,.4][i]
            points=_keypoints(com_y=com,knee_state='straight')
            return SimpleNamespace(pose_landmarks=SimpleNamespace(landmark=[SimpleNamespace(**{k:p[k] for k in ('x','y','z','visibility')}) for p in points]))
        def close(self): pass
    monkeypatch.setitem(sys.modules,'mediapipe',SimpleNamespace(solutions=SimpleNamespace(pose=SimpleNamespace(Pose=SyntheticPose))))
    monkeypatch.setattr(poses,'_resolve_tasks_landmarker',lambda:None)
    pose=poses.extract_pose(str(pose_dir),lock,boxes,10.,frame_times=motion['selected'],slow_motion_scale=scale)
    # The real production temporal attachment, pose selection, quality and
    # smoothing execute; only model process/detection/extraction are stubs.
    profile,evidence=infer_analysis_profile('自由滑','节目片段',pose,motion)
    artifacts=Path(os.environ['TRACK_CLOCK_EVIDENCE']) if os.environ.get('TRACK_CLOCK_EVIDENCE') else tmp_path
    artifacts.mkdir(parents=True,exist_ok=True)
    prefix=f'chain-origin-{origin}-scale-{scale}'
    (artifacts/(prefix+'-inputs.json')).write_text(json.dumps(dict(pose=pose,motion=motion,lock=lock,profile=profile,evidence=evidence),ensure_ascii=False,indent=2),encoding='utf8')
    assert all(f['keypoints'] for f in pose['frames'][:9]),pose['pose_diagnostics']
    assert all(not f['keypoints'] and f['input_binding_valid'] is False for f in pose['frames'][9:])
    assert set(landmark_calls)==set(range(9)) and len(detector_calls)==9
    assert profile=='jump' and evidence['profile_hint']=='mixed_auto' # automatic synthetic route, not a manual label
    assert all(observation_time_error(f) is None for f in pose['frames'][:9])
    assert all(f is None or f['frame'] not in [p.name for p in frames[9:]] for f in observation_slots(pose,motion))
    assert frames[9].name not in tl._motion_anchor_frame_names(motion)
    assert all(r[1]!=frames[9].stem for r in kc._motion_records(motion,10.))
    result=consume_contract(tmp_path,pose,motion,profile,name=prefix,fps=10.,saved_images={f.name:f.read_bytes() for f in frames})
    (artifacts/(prefix+'-readback.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    bio=result['detail']['bio_data']; tr=bio['jump_measurements']['trajectory']
    assert all(bio['jump_stages'][stage]['status']=='candidate' for stage in ('takeoff','apex','landing'))
    assert tr['points'] and all(p['pose_index']<9 for p in tr['points'])
    assert len(tr['segments'])==1 and all(s['status']=='unavailable' for s in tr['slots'][9:])
    assert result['detail']['report']['jump_measurements']==bio['jump_measurements']
    assert result['detail']['frame_motion_scores']['continuous_tracking']['observation_validation'][9]['continuity_reason']=='tracking_clock_gap'
    for f in result['pose']['frames'][9:]:
        assert f['temporal']['tracking_continuity_segment']==1
        assert f['temporal']['tracking_rejected_reasons']==['tracking_clock_gap']
    for stage in bio['jump_stages'].values():
        if not isinstance(stage,dict): continue
        refs=(stage.get('evidence') or {}).get('support_frames') or []
        assert all(int(r['frame_id'].split('_')[-1])<=9 for r in refs)
    assert bio['jump_measurements']['rotation_count']['value'] is None

@pytest.mark.parametrize('wanted',[[.25],[.6],[-.1]])
def test_all_unsupported_requests_explain_rejection_without_removing_images(tmp_path,monkeypatch,wanted):
    pool,pose,m=fixture_pool(tmp_path)
    with pytest.raises(ValueError,match='tracking_clock_gap|outside_observation_coverage'):
        run_prepare(tmp_path,monkeypatch,m,pool,pose,wanted)
    assert (pose/'frame_0001.jpg').read_bytes()==b'old-unbound-image'


@pytest.mark.parametrize('anchor',[0,3,5])
def test_multiple_gaps_stop_both_directions(tmp_path,monkeypatch,anchor):
    from app.routers import analysis
    pool,pose,m=fixture_pool(tmp_path,(0,60,120,240,300,420,480))
    frames,motion=run_prepare(tmp_path,monkeypatch,m,pool,pose)
    monkeypatch.setattr(PersonBBoxTracker,'_detect',lambda *a,**kw:[(100.,50.,200.,180.,.95)])
    lock=dict(selected_bbox=dict(x=100/640,y=50/240,width=100/640,height=130/240),manual_override=True,preview_frame_index=anchor)
    analysis._build_bbox_per_frame(frames,lock,1.,tracking_manifest=motion['continuous_tracking'],tracking_dir=pool)
    segments=[r['continuity_segment'] for r in motion['selected']]
    assert [d['input_binding_valid'] for d in lock['person_tracker_diagnostics']]==[s==segments[anchor] for s in segments]


@pytest.mark.parametrize('value',[True,float('nan'),float('inf'),None])
def test_invalid_request_time_preserves_old_images(tmp_path,monkeypatch,value):
    pool,pose,m=fixture_pool(tmp_path)
    with pytest.raises((ValueError,TypeError)):
        run_prepare(tmp_path,monkeypatch,m,pool,pose,[0.,value])
    assert (pose/'frame_0001.jpg').read_bytes()==b'old-unbound-image'
