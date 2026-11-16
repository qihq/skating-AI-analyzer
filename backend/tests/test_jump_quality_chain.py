"""Offline quality-contract regressions through the actual action router."""
import copy
import math

import pytest

from app.services import action_profiles as route
from app.services import jump_features as jump
from app.services import biomechanics as bio


def sequence(ys=(.9,.9,.9,.6,.6,.9,.9), facing=None):
    frames=[]
    for i,y in enumerate(ys):
        sign=facing[i] if facing else 1
        points=[{'id': k,'name':f'joint_{k}','x':x,'y':v,'z':0.,'visibility':.99}
                for k,x,v in ((0,.5,.1),(11,.5-sign*.1,.4),(12,.5+sign*.1,.4),
                               (23,.5-sign*.06,.5),(24,.5+sign*.06,.5),
                               (27,.4,y),(28,.6,y))]
        frames.append({'frame':f'frame_{i+1:04d}.jpg','timestamp':i/15,
                       'tracking_state':'tracked','keypoints':points})
    return {'frames':frames}


def metadata(data):
    return {'frame_rate':15.,'scores':[.08]*len(data['frames']),
            'selected':[{'frame_id':f['frame'],'timestamp':f['timestamp']} for f in data['frames']]}


def routed(data):
    return route.infer_analysis_profile('自由滑','节目片段',data,metadata(data))


def mark(data, indices, ids, **fields):
    for i in indices:
        for p in data['frames'][i]['keypoints']:
            if p['id'] in ids:p.update(copy.deepcopy(fields))


REJECTIONS=[
    {'quality':{'analysis_usable':False}},
    {'quality':{'analysis_usable':True,'limb_consistency':{'status':'uncertain'}}},
    {'interpolated':True},
    {'quality':{'analysis_usable':True,'source':'display_interpolation'}},
    {'x':None}, {'y':float('nan')}, {'z':float('inf')},
    {'visibility':None},
]


@pytest.mark.parametrize('fields',REJECTIONS)
@pytest.mark.parametrize('indices',[(3,),(3,4)])
def test_rejected_ankles_match_empty_slot_control(fields,indices):
    data=sequence(); mark(data,indices,(27,28),**fields)
    empty=copy.deepcopy(data)
    for i in indices:empty['frames'][i]['keypoints']=[]
    _,e=routed(data);_,control=routed(empty)
    assert e['airborne_frames_detected']==control['airborne_frames_detected']==0
    assert e['jump_gate_passed'] is False


@pytest.mark.parametrize('quality',[None,{'source':'native_observation','analysis_usable':True}])
def test_valid_and_legacy_motion_still_route_to_candidate(quality):
    data=sequence()
    if quality is not None:mark(data,range(7),range(33),quality=quality)
    profile,e=routed(data)
    assert profile=='jump' and e['jump_gate_passed'] is True
    assert e['profile_route_only'] is True and e['negative_constraints']


@pytest.mark.parametrize('missing',[27,28])
def test_one_ankle_cannot_supply_bilateral_contact(missing):
    data=sequence()
    for i in (3,4):data['frames'][i]['keypoints']=[p for p in data['frames'][i]['keypoints'] if p['id']!=missing]
    assert routed(data)[1]['jump_gate_passed'] is False


@pytest.mark.parametrize('fields',REJECTIONS)
def test_rejected_torso_has_no_rotation_or_vertical_range(fields):
    data=sequence(facing=(-1,-1,1,1,-1,-1,1))
    for i,f in enumerate(data['frames']):
        for p in f['keypoints']:
            if p['id'] in (11,12,23,24):p['y']+=i*.07
    mark(data,range(7),(11,12,23,24),**fields)
    assert route._detect_rotation_signal(data)==0
    assert route._max_vertical_range(data)==0


def test_invalid_torso_slots_do_not_join_rotation_transitions():
    data=sequence(ys=(.9,)*9,facing=(-1,-1,1,1,-1,-1,1,1,-1))
    mark(data,(2,5),(11,12,23,24),quality={'analysis_usable':False})
    assert route._detect_rotation_signal(data)==0


@pytest.mark.parametrize('fields',REJECTIONS)
def test_height_requires_valid_nose_and_both_ankles(fields):
    data=sequence();mark(data,range(7),(27,),**fields)
    assert route._person_height_normalized(data)==0


def test_unattributed_com_cache_cannot_override_rejected_observations():
    data=sequence();mark(data,range(7),(11,12,23,24),quality={'analysis_usable':False})
    data['com_trajectory']={'vertical_range':.7,'points':[{'y':.2},{'y':.9}]}
    assert route._max_vertical_range(data)==0


@pytest.mark.parametrize('boundary',['identity','binding','segment','time_gap','reverse_time','tracking'])
def test_explicit_frame_boundaries_break_airborne_and_rotation(boundary):
    data=sequence();rot=sequence(ys=(.9,)*7,facing=(-1,-1,1,1,-1,-1,1))
    for d in (data,rot):
        for i,f in enumerate(d['frames']):
            f['temporal']={'analysis_timestamp':f['timestamp'],'segment_id':0,'continuous':i>0}
            if boundary=='identity':f['identity_id']=0 if i<4 else 1
            if boundary=='binding' and i==4:f['input_binding_valid']=False
            if boundary=='segment' and i>=4:f['temporal']['segment_id']=1
            if boundary=='time_gap' and i>=4:f['timestamp']+=1;f['temporal']['analysis_timestamp']+=1
            if boundary=='reverse_time' and i==4:f['timestamp']=0;f['temporal']['analysis_timestamp']=0
            if boundary=='tracking' and i==4:f['tracking_state']='lost'
    assert routed(data)[1]['jump_gate_passed'] is False
    # No segment has two orientation transitions.
    assert route._detect_rotation_signal(rot)==0


@pytest.mark.parametrize('fields',REJECTIONS[:4])
def test_all_three_point_consumers_honor_explicit_rejection(fields):
    data=sequence();mark(data,(0,),range(33),**fields)
    sparse=data['frames'][0]['keypoints']
    dense=[{'x':.5,'y':.5,'z':0.,'visibility':.99} for _ in range(33)]
    dense[27]=next(p for p in sparse if p['id']==27)
    assert route._trusted_ankle_y(data['frames'][0]) is None
    assert jump._keypoint(sparse,27) is None
    assert bio._point(dense,27) is None


@pytest.mark.parametrize('transform',['translation','zoom','crossing','single_turn'])
def test_ordinary_motion_remains_route_only_without_jump_facts(transform):
    data=sequence(ys=(.9,)*7)
    for i,f in enumerate(data['frames']):
        for p in f['keypoints']:
            if transform=='translation':p['x']+=i*.07
            if transform=='zoom':p['x']=.5+(p['x']-.5)*(1+i*.03);p['y']=.9+(p['y']-.9)*(1+i*.03)
            if transform=='crossing' and p['id'] in (27,28):p['x']=.5+(p['x']-.5)*math.cos(i*.7)
            if transform=='single_turn' and i>=3:p['x']=1-p['x']
    _,e=routed(data)
    assert not e['jump_gate_passed'] and e['hip_rotation_signal']==0
    assert e['profile_route_only'] and e['negative_constraints']


@pytest.mark.parametrize('kind',['missing_time','selected_gap','selected_reverse','selected_missing'])
def test_persisted_times_cannot_override_explicit_selected_gaps(kind):
    data=sequence(); meta=metadata(data)
    if kind=='missing_time':data['frames'][4]['timestamp']=None
    if kind=='selected_gap':
        for item in meta['selected'][4:]:item['timestamp']+=2
    if kind=='selected_reverse':meta['selected'][4]['timestamp']=0
    if kind=='selected_missing':meta['selected'][4]['frame_id']='unbound'
    assert not route.infer_analysis_profile('自由滑','节目片段',data,meta)[1]['jump_gate_passed']


def test_sparse_reordered_points_remain_compatible_and_duplicate_ids_fail_closed():
    data=sequence()
    for f in data['frames']:f['keypoints'].reverse()
    assert routed(data)[1]['jump_gate_passed']
    for i in (3,4):
        data['frames'][i]['keypoints'].append(copy.deepcopy(data['frames'][i]['keypoints'][0]))
    assert not routed(data)[1]['jump_gate_passed']


def test_vertical_range_cannot_span_an_unusable_middle_frame():
    data=sequence(ys=(.9,)*7)
    for i in range(4,7):
        for p in data['frames'][i]['keypoints']:p['y']+=.3
    mark(data,(3,),(11,12,23,24),quality={'analysis_usable':False})
    assert route._max_vertical_range(data)==pytest.approx(0.)


def consume_saved_pose(tmp_path, data, meta, *, name='quality-chain'):
    """Actual SQLite rows -> actual saved-pose GET -> all three consumers."""
    import json
    from unittest.mock import AsyncMock, patch
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from app import models
    from app.routers import analysis as router
    engine=create_engine('sqlite:///'+str(tmp_path/(name+'.db')))
    models.Analysis.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(models.Analysis(id=name,action_type='自由滑',status='completed',
                                   video_path='forbidden-video.mp4',pose_data=data,
                                   frame_motion_scores=meta))
        session.commit()
    with Session(engine) as session:
        row=session.scalar(select(models.Analysis).where(models.Analysis.id==name))
        assert row.pose_data==data
        original=copy.deepcopy(row.pose_data)
        db=AsyncMock();db.get.return_value=row
        async def session_override():yield db
        app=FastAPI();app.include_router(router.router)
        app.dependency_overrides[router.get_session]=session_override
        with patch.object(router,'trial_profile',return_value='legacy-analysis-preview'), \
             patch.object(router,'extract_pose',side_effect=AssertionError('inference forbidden')), \
             patch.object(router,'_restore_missing_analysis_frames',side_effect=AssertionError('backfill forbidden')),TestClient(app) as client:
            response=client.get('/api/analysis/'+name+'/pose')
            assert response.status_code==200,response.text
            saved=response.json()
        for expected,actual in zip(data['frames'],saved['frames'],strict=True):
            assert actual.get('temporal')==expected.get('temporal')
            assert len(actual['keypoints'])==len(expected['keypoints'])
            for a,b in zip(expected['keypoints'],actual['keypoints'],strict=True):
                for field in ('id','x','y','z','visibility','interpolated','quality'):
                    assert a.get(field)==b.get(field),field
        profile,evidence=route.infer_analysis_profile('自由滑','节目片段',saved,meta)
        bio_data=bio.analyze_biomechanics(saved,'自由滑',profile,effective_fps=15.)
        bio_data=bio.attach_key_frame_candidates(bio_data,saved,meta,profile,15.)
        # Existing candidate contract is preserved, including its uncertainty.
        candidates=bio_data.get('key_frame_candidates',{})
        key_frames=bio_data.get('key_frames',{})
        jump_evidence=jump.compute_jump_evidence(saved,key_frames,15.)
        db.commit.assert_not_awaited()
        assert row.pose_data==original
    engine.dispose()
    report={'profile':profile,'profile_evidence':evidence,'biomechanics':bio_data,
            'key_frame_candidates':candidates,'jump_evidence':jump_evidence,
            'jump_evidence_context':{'requested_key_frames':key_frames,'has_takeoff_candidate':bool(key_frames.get('T')),
                                     'direct_consumer_probe':True,'fallback_without_T_is_not_stage_evidence':not bool(key_frames.get('T'))},
            'frame_count':len(saved['frames']),'point_count':sum(len(f['keypoints']) for f in saved['frames'])}
    (tmp_path/(name+'-consumers.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return saved,report


def test_fake_production_extraction_sqlite_get_and_actual_consumers(tmp_path,monkeypatch):
    import sys
    import types
    import numpy as np
    from app.services import pose
    from test_limb_consistency import body,swap
    frames=body();swap(frames,5,(27,))
    records=[]
    for i in range(len(frames)):
        (tmp_path/f'frame_{i+1:04d}.jpg').write_bytes(b'fake image; never decode')
        records.append({'frame_id':f'frame_{i+1:04d}','timestamp':i/15})
    class FakePose:
        def __init__(self,**kwargs):self.i=0
        def close(self):pass
        def process(self,image):
            pmap={p['id']:p for p in frames[self.i]['keypoints']};self.i+=1
            landmarks=[types.SimpleNamespace(**{axis:pmap.get(k,{'x':.5,'y':.1,'z':0.,'visibility':.99})[axis]
                                               for axis in ('x','y','z','visibility')}) for k in range(33)]
            return types.SimpleNamespace(pose_landmarks=types.SimpleNamespace(landmark=landmarks))
    monkeypatch.setitem(sys.modules,'mediapipe',types.SimpleNamespace(solutions=types.SimpleNamespace(pose=types.SimpleNamespace(Pose=FakePose))))
    monkeypatch.setattr(pose,'_resolve_tasks_landmarker',lambda:None)
    import cv2
    monkeypatch.setattr(cv2,'imread',lambda _:np.zeros((100,100,3),dtype=np.uint8))
    monkeypatch.setattr(pose,'_candidate_rejection_reasons',lambda *a,**k:[])
    payload=pose.extract_pose(str(tmp_path),effective_fps=15.,frame_times=records)
    point=next(p for p in payload['frames'][5]['keypoints'] if p['id']==27)
    assert point['quality']['analysis_usable'] is False
    meta={'frame_rate':15.,'selected':records,'scores':[.08]*len(frames)}
    saved,report=consume_saved_pose(tmp_path,payload,meta)
    assert route._trusted_ankle_y(saved['frames'][5]) is None
    assert not report['profile_evidence']['jump_gate_passed']
    assert jump._ankle_series(list(enumerate(saved['frames'])),27)[5] is None
    assert bio._point(saved['frames'][5]['keypoints'],27) is None
    diagnostic=jump.compute_jump_evidence(saved,{'T':saved['frames'][5]['frame']},15.)
    assert diagnostic['contact_evidence_status']=='uncertain' and diagnostic['takeoff_foot']=='unknown'
    assert diagnostic['point_quality']['excluded_limb_uncertain']>=2


def test_rejected_torso_cannot_reenter_through_persistence_or_other_consumers(tmp_path):
    from app.services.smoothing import smooth_keypoint_sequence
    data=sequence(ys=(.9,)*7,facing=(-1,-1,1,1,-1,-1,1))
    data['frames']=smooth_keypoint_sequence(data['frames'],15.)
    mark(data,range(7),(11,12,23,24),quality={'analysis_usable':True,
         'source':'native_observation','limb_consistency':{'status':'uncertain'}})
    saved,report=consume_saved_pose(tmp_path,data,metadata(data),name='torso-quality')
    assert report['profile_evidence']['hip_rotation_signal']==0
    assert report['profile_evidence']['com_vertical_range']==0
    assert not bio.calc_center_of_mass_trajectory(saved)['points']
    assert all(jump._com(f) is None for f in saved['frames'])


@pytest.mark.parametrize('consumer',['swing','approach','edge','rotation'])
def test_downstream_motion_does_not_bridge_rejected_middle(consumer):
    data=sequence(ys=(.9,)*3)
    for i,f in enumerate(data['frames']):
        for p in f['keypoints']:
            p['x']+=i*.05
            p['y']+= (.08 if i==1 else 0.)
        if i==2:
            for p in f['keypoints']:
                if p['id']==27:p['x']+=.3
                if p['id']==28:p['x']-=.3
                if p['id']==11:p['y']-=.1
                if p['id']==12:p['y']+=.1
    mark(data,(1,),(11,12,23,24,27,28),quality={'analysis_usable':False})
    window=list(enumerate(data['frames']))
    if consumer=='swing':assert jump._free_leg_swing(window)==(0.,0.)
    if consumer=='approach':assert jump._approach_direction(window)==('unknown',0.)
    if consumer=='edge':assert jump._edge_score(window)==(.5,'unknown',0.)
    if consumer=='rotation':assert bio._rotation_rps(data,1,3,15.)==0.


def test_partial_torso_cannot_shift_jump_center_by_changing_point_set():
    data=sequence();mark(data,(0,),(23,),quality={'analysis_usable':False})
    assert jump._com(data['frames'][0]) is None


@pytest.mark.parametrize('boundary',['time_gap','reverse_time','identity','binding','relock'])
def test_actual_jump_window_respects_explicit_continuity(boundary):
    data=sequence(ys=(.8,.9,.8))
    for i,f in enumerate(data['frames']):
        f['temporal']={'analysis_timestamp':f['timestamp'],'segment_id':0,'continuous':i>0}
        if boundary=='time_gap' and i==2:f['temporal']['analysis_timestamp']+=1
        if boundary=='reverse_time' and i==2:f['temporal']['analysis_timestamp']=0.
        if boundary=='identity':f['identity_id']=0 if i<2 else 1
        if boundary=='binding' and i==2:f['input_binding_valid']=False
        if boundary=='relock' and i==2:f['tracker_state']='relock_pending'
    evidence=jump.compute_jump_evidence(data,{'T':data['frames'][2]['frame']},15.)
    if boundary in ('binding', 'relock', 'reverse_time'):
        assert evidence['anchor']['status'] == 'unavailable'
        assert evidence['toe_pick_pulse'] is None  # unknown is not a negative observation
    else:
        assert evidence['toe_pick_pulse'] is False
    assert bio._rotation_rps(data,1,3,15.)==0.


def test_relocking_frame_cannot_supply_router_contact():
    data=sequence();data['frames'][4]['tracker_state']='relock_pending'
    assert routed(data)[1]['jump_gate_passed'] is False


def test_edge_does_not_join_curve_across_rejected_middle():
    data=sequence(ys=(.9,)*5)
    for i,f in enumerate(data['frames']):
        for p in f['keypoints']:
            p['x']+=i*.05
            p['y']+= (.08 if i in (1,2) else 0.)
    mark(data,(2,),(11,12,23,24),quality={'analysis_usable':False})
    assert jump._edge_score(list(enumerate(data['frames'])))==(.5,'unknown',0.)


def test_rotation_uses_saved_elapsed_time_instead_of_filtered_sample_count():
    data=sequence(ys=(.9,)*3)
    for i,f in enumerate(data['frames']):
        f['timestamp']=i*.2
        for p in f['keypoints']:
            if p['id'] in (11,12):
                sign=-1 if p['id']==11 else 1
                p['x']=.5+sign*.1*math.cos(i*math.pi/4)
                p['y']=.4+sign*.1*math.sin(i*math.pi/4)
    assert bio._rotation_rps(data,1,3,100.)==.62
