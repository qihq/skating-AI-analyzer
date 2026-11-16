"""POSE-06 synthetic truth is fixed before implementation; saved people are not labels."""
import copy
import math
import json
import sys
import types
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest
from app.services.smoothing import smooth_keypoint_sequence
from app.services import jump_features as jump


def body(n=11, times=None):
    coordinates = {11:(.43,.2),12:(.57,.2),13:(.35,.3),14:(.65,.3),
        15:(.3,.4),16:(.7,.4),23:(.46,.45),24:(.54,.45),
        25:(.42,.64),26:(.58,.64),27:(.4,.83),28:(.6,.83),
        29:(.39,.85),30:(.59,.85),31:(.43,.87),32:(.63,.87)}
    return [{'frame':f'frame_{i+1:04d}.jpg','timestamp':times[i] if times is not None else i/15,
             'tracking_state':'tracked','tracker_id':7,
             'keypoints':[{'id':k,'name':f'joint_{k}','x':x,'y':y,'z':0.,'visibility':.99} for k,(x,y) in coordinates.items()]}
            for i in range(n)]


def point(frames,i,k): return next(p for p in frames[i]['keypoints'] if p['id']==k)
def swap(frames,i,ids):
    for left in ids:
        a,b=point(frames,i,left),point(frames,i,left+1)
        for axis in ('x','y','z'): a[axis],b[axis]=b[axis],a[axis]


@pytest.mark.parametrize('ids',[(27,),(25,27,29,31),(23,25,27,29,31),(13,15)])
def test_one_frame_side_confusion_is_quarantined_before_smoothing(ids):
    frames=body(); pristine=copy.deepcopy(frames);swap(frames,5,ids);source=copy.deepcopy(frames)
    out=smooth_keypoint_sequence(frames,15.)
    for left in ids:
        for k in (left,left+1):
            q=point(out,5,k)['quality']
            assert q['analysis_usable'] is False
            assert q['limb_consistency']['status']=='uncertain'
            assert q['source']=='limb_uncertain'
            assert q['raw_coordinates']['x']==point(source,5,k)['x']
            assert point(out,5,k)['x']==point(source,5,k)['x']  # visible raw, never silent relabel
            assert jump._keypoint(out[5]['keypoints'],k) is None
            for i in range(11):
                if i==5: continue
                p=point(out,i,k)
                assert p['x']==pytest.approx(point(pristine,i,k)['x'],abs=1e-10)
                assert p['quality']['analysis_usable'] is True
                assert 5 not in p['quality'].get('support_frame_indices',[])
    assert frames==source


@pytest.mark.parametrize('joint',[13,15,23,25,27,29,31])
def test_non_swap_chain_outlier_cannot_pollute_neighbors(joint):
    frames=body();expected=copy.deepcopy(frames)
    point(frames,5,joint)['x']+=.4;point(frames,5,joint)['y']-=.25
    out=smooth_keypoint_sequence(frames,15.)
    q=point(out,5,joint)['quality']
    assert q['analysis_usable'] is False
    assert 'geometry' in q['limb_consistency']['reason']
    for i in range(11):
        if i!=5: assert point(out,i,joint)['x']==pytest.approx(point(expected,i,joint)['x'])


@pytest.mark.parametrize('kind',['crossing','turn','fast_arc','translation','scale','noise'])
def test_legal_motion_is_retained_without_ordering_left_and_right(kind):
    frames=body(41);rng=np.random.default_rng(601)
    for i,f in enumerate(frames):
        t=(i-20)/15
        for p in f['keypoints']:
            if kind=='crossing' and p['id']>=25:
                p['x']+= (.17*math.sin(t*2))*(1 if p['id']%2 else -1)
            elif kind=='turn':
                x,y=p['x']-.5,p['y']-.5;angle=t*2
                p['x'],p['y']=.5+x*math.cos(angle)-y*math.sin(angle),.5+x*math.sin(angle)+y*math.cos(angle)
            elif kind=='translation': p['x']+=t*.6;p['y']-=t*.2
            elif kind=='scale': p['x']=.5+(p['x']-.5)*(1+.2*t);p['y']=.5+(p['y']-.5)*(1+.2*t)
            elif kind=='noise': p['x']+=rng.normal(0,.0005);p['y']+=rng.normal(0,.0005)
        if kind=='fast_arc':
            # Large legitimate one-frame ankle excursion, fixed shin length.
            angle=1.1 if i==20 else 0.
            knee=point(frames,i,25);ankle=point(frames,i,27)
            length=math.hypot(.02,.19)
            ankle['x']=knee['x']+length*math.sin(angle);ankle['y']=knee['y']+length*math.cos(angle)
            for k,dx,dy in [(29,-.01,.02),(31,.03,.04)]:
                point(frames,i,k).update(x=ankle['x']+dx,y=ankle['y']+dy)
    out=smooth_keypoint_sequence(frames,15.)
    assert sum(p['quality']['analysis_usable'] is False for f in out for p in f['keypoints'])==0
    if kind=='crossing':
        assert any(point(out,i,27)['x']>point(out,i,28)['x'] for i in range(41))
    if kind=='fast_arc': assert point(out,20,27)['quality']['analysis_usable'] is True


@pytest.mark.parametrize('barrier',['identity','lost','binding','unknown','duplicate','backward','gap','low_visibility'])
def test_limb_evidence_never_crosses_untrusted_boundaries(barrier):
    frames=body();swap(frames,5,(27,))
    if barrier=='identity':frames[5]['tracker_id']=8
    elif barrier=='lost':frames[4]['tracking_state']='lost'
    elif barrier=='binding':frames[4]['input_binding_valid']=False
    elif barrier=='unknown':frames[4]['timestamp']=None
    elif barrier=='duplicate':frames[5]['timestamp']=frames[4]['timestamp']
    elif barrier=='backward':frames[5]['timestamp']=0.
    elif barrier=='gap':
        for f in frames[5:]:f['timestamp']+=2
    else:point(frames,4,27)['visibility']=0.
    out=smooth_keypoint_sequence(frames,15.)
    q=point(out,5,27)['quality']
    assert q.get('limb_consistency',{}).get('status')!='uncertain'
    assert point(out,5,27)['x']==point(frames,5,27)['x']


@pytest.mark.parametrize('n,i',[(1,0),(2,1),(4,2),(11,0),(11,10)])
def test_boundaries_do_not_invent_corrected_observations(n,i):
    frames=body(n);swap(frames,i,(27,))
    out=smooth_keypoint_sequence(frames,15.)
    p=point(out,i,27)
    assert p['x']==point(frames,i,27)['x']
    assert p['quality']['limb_consistency']['status']=='insufficient_context'


def test_rejected_ankle_stays_a_jump_gap_and_biomechanics_rejects_it():
    from app.services.biomechanics import _point
    frames=body();swap(frames,5,(27,));out=smooth_keypoint_sequence(frames,15.)
    assert jump._ankle_series(list(enumerate(out)),27)[5] is None
    # _point has a legacy positional interface; pass a full ID array.
    full=[{'id':k,'x':.5,'y':.5,'z':0.,'visibility':.99} for k in range(33)]
    full[27]=point(out,5,27)
    assert _point(full,27) is None
    evidence=jump.compute_jump_evidence({'frames':out},{'T':out[5]['frame']},15.)
    assert evidence['contact_evidence_status']=='uncertain'
    assert evidence['toe_pick_pulse'] is False
    assert evidence['point_quality']['excluded_limb_uncertain']>=2


def test_side_confusion_with_noisy_accelerating_flanks_uses_both_raw_sides():
    frames=body()
    # Known stationary paired ankles with bounded nuisance noise on flanking
    # observations. Velocity extrapolation alone overstates disagreement.
    for i,dx in ((3,-.018),(4,.008),(6,-.006),(7,.017)):
        for k in (27,28):point(frames,i,k)['x']+=dx
    swap(frames,5,(27,))
    out=smooth_keypoint_sequence(frames,15.)
    assert all(point(out,5,k)['quality']['analysis_usable'] is False for k in (27,28))
    assert all(point(out,i,k)['quality']['analysis_usable'] is True for i in (3,4,6,7) for k in (27,28))


def test_collapsed_knees_during_distal_label_bounce_are_not_rescued_as_native():
    frames=body();swap(frames,5,(27,29,31))
    for k in (25,26):point(frames,5,k)['x']=.5
    out=smooth_keypoint_sequence(frames,15.)
    assert all(point(out,5,k)['quality']['analysis_usable'] is False for k in range(25,33))
    assert all(point(out,5,k)['quality']['analysis_usable'] is True for k in (23,24))


@pytest.mark.parametrize('scale,angle,offset',[(.3,.8,(-.2,.7)),(2.5,-1.1,(1.,-.8))])
def test_assignment_gate_is_invariant_to_canvas_translation_scale_and_rotation(scale,angle,offset):
    frames=body();swap(frames,5,(27,))
    for f in frames:
        for p in f['keypoints']:
            x,y=p['x'],p['y']
            p['x']=offset[0]+scale*(x*math.cos(angle)-y*math.sin(angle))
            p['y']=offset[1]+scale*(x*math.sin(angle)+y*math.cos(angle))
    out=smooth_keypoint_sequence(frames,15.)
    assert all(point(out,5,k)['quality']['analysis_usable'] is False for k in (27,28))
    assert sum(p['quality']['analysis_usable'] is False for f in out for p in f['keypoints'])==6


def test_nonuniform_time_with_known_motion_and_isolated_label_bounce():
    times=[0.,.02,.06,.1,.19,.22,.29,.34,.4,.46,.52]
    frames=body(times=times)
    for i,f in enumerate(frames):
        for p in f['keypoints']:p['x']+=times[i]*.07
    swap(frames,5,(27,));out=smooth_keypoint_sequence(frames,999.)
    assert all(point(out,5,k)['quality']['analysis_usable'] is False for k in (27,28))
    for i in range(11):
        if i!=5:assert point(out,i,27)['x']==pytest.approx(.4+times[i]*.07)


def test_limb_quality_reaches_fake_production_extraction(tmp_path,monkeypatch):
    from app.services import pose
    from app.routers.analysis import _build_pose_response
    from app.schemas import PoseResponse
    frames=body();swap(frames,5,(27,));records=[]
    for i in range(11):
        (tmp_path/f'frame_{i+1:04d}.jpg').write_bytes(b'synthetic')
        records.append({'frame_id':f'frame_{i+1:04d}','timestamp':i/15})
    class FakePose:
        def __init__(self,**kwargs):self.i=0
        def close(self):pass
        def process(self,image):
            pmap={p['id']:p for p in frames[self.i]['keypoints']};self.i+=1
            landmarks=[types.SimpleNamespace(**{a:pmap.get(k,{'x':.5,'y':.1,'z':0.,'visibility':.99})[a]
                                               for a in ('x','y','z','visibility')}) for k in range(33)]
            return types.SimpleNamespace(pose_landmarks=types.SimpleNamespace(landmark=landmarks))
    monkeypatch.setitem(sys.modules,'mediapipe',types.SimpleNamespace(solutions=types.SimpleNamespace(pose=types.SimpleNamespace(Pose=FakePose))))
    monkeypatch.setattr(pose,'_resolve_tasks_landmarker',lambda:None)
    import cv2
    monkeypatch.setattr(cv2,'imread',lambda _:np.zeros((100,100,3),dtype=np.uint8))
    monkeypatch.setattr(pose,'_candidate_rejection_reasons',lambda *a,**k:[])
    payload=pose.extract_pose(str(tmp_path),effective_fps=15.,frame_times=records)
    rejected=point(payload['frames'],5,27)
    assert rejected['quality']['source']=='limb_uncertain'
    assert rejected['quality']['raw_coordinates']['x']==.6
    saved=json.loads(json.dumps(payload));response=PoseResponse.model_validate(_build_pose_response('fake',saved,{'selected':records}).model_dump()).model_dump()
    assert point(response['frames'],5,27)['quality']==rejected['quality']
    assert jump._keypoint(response['frames'][5]['keypoints'],27) is None


def test_limb_quality_survives_actual_sqlite_and_saved_pose_get_without_recompute(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine,select
    from sqlalchemy.orm import Session
    from app import models
    from app.routers import analysis as router
    from app.services.biomechanics import _point
    frames=body();swap(frames,5,(27,));data={'connections':[],'frames':smooth_keypoint_sequence(frames,15.)}
    legacy={'connections':[],'frames':body(1)}
    engine=create_engine('sqlite:///'+str(tmp_path/'limb.db'));models.Analysis.metadata.create_all(engine)
    with Session(engine) as session:
        for name,payload in (('limb-saved',data),('legacy',legacy)):
            session.add(models.Analysis(id=name,action_type='jump',status='completed',video_path='never-open.mp4',pose_data=payload))
        session.commit()
    with Session(engine) as session:
        rows={name:session.scalar(select(models.Analysis).where(models.Analysis.id==name)) for name in ('limb-saved','legacy')}
        assert rows['limb-saved'].pose_data==data
        fake=AsyncMock();fake.get.side_effect=lambda model,name:rows[name]
        async def override_db():yield fake
        app=FastAPI();app.include_router(router.router);app.dependency_overrides[router.get_session]=override_db
        with patch.object(router,'trial_profile',return_value='legacy-analysis-preview'), \
             patch.object(router,'extract_pose',side_effect=AssertionError('inference forbidden')), \
             patch.object(router,'_restore_missing_analysis_frames',side_effect=AssertionError('backfill forbidden')),TestClient(app) as client:
            response=client.get('/api/analysis/limb-saved/pose');assert response.status_code==200
            saved=response.json();q=point(saved['frames'],5,27)['quality']
            assert q==point(data['frames'],5,27)['quality']
            assert q['limb_consistency']['raw_point_id']==27
            assert q['raw_visibility']==.99
            assert q['raw_coordinates']['x']==.6
            assert jump._keypoint(saved['frames'][5]['keypoints'],27) is None
            assert jump._ankle_series(list(enumerate(saved['frames'])),27)[5] is None
            evidence=jump.compute_jump_evidence(saved,{'T':saved['frames'][5]['frame']},15.)
            assert evidence['contact_evidence_status']=='uncertain'
            assert evidence['takeoff_foot']=='unknown'
            old=client.get('/api/analysis/legacy/pose').json()
            assert old['frames'][0]['keypoints'][0]['quality'] is None
        fake.commit.assert_not_awaited()
        assert rows['legacy'].pose_data==legacy
    engine.dispose()


def test_native_foot_contact_points_cannot_rescue_an_uncertain_ankle_chain():
    frames=body();swap(frames,5,(27,))
    out=smooth_keypoint_sequence(frames,15.)
    for k in (29,30,31,32):
        q=point(out,5,k)['quality']
        assert q['analysis_usable'] is False
        assert q['limb_consistency']['dependency_point_id'] in (27,28)
        assert point(out,5,k)['x']==point(frames,5,k)['x']
    assert all(point(out,5,k)['quality']['analysis_usable'] is True for k in (23,24,25,26))
