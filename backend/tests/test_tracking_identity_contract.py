"""Offline identity contracts: encoded JPEGs, actual evidence and saved consumers."""
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
import cv2
import numpy as np
import pytest
from app.services import continuous_tracking as ct, pose as poses
from app.services.person_tracker import PersonBBoxTracker
from app.services.action_profiles import infer_analysis_profile
from app.services.jump_projection import extract_projection
from test_tracking_clock_contract import offline, run_prepare
from test_analysis_keyframe_candidates import _keypoints
from test_tal_persistence import consume_contract


def make_case(tmp_path, monkeypatch, kind, origin=7.):
    pool=tmp_path/'pool';pool.mkdir();selected=tmp_path/'selected';selected.mkdir()
    rows=[];detections={};calls=[]
    for i in range(12):
        post=i>=6
        w,h=(86,152) if post and kind in ('scale','combined') else (80,144)
        x,y=(112+(i-6)*2,46) if post and kind in ('translation','combined') else (96,48)
        image=np.zeros((240,640,3),np.uint8);image[:8,:8]=i*8
        image[y:y+h,x:x+w]=40
        left,right=round(x+w*.18),round(x+w*.82)
        top,bottom=round(y+h*.18),round(y+h*.62)
        yy,xx=np.mgrid[0:bottom-top,0:right-left]
        u=(xx+.5)/(right-left);v=(yy+.5)/(bottom-top)
        reference_diagonal=kind=='diagonal_swap'
        red=(u+v<1) if reference_diagonal else (v<.5)
        if post and kind=='vertical_swap':red=u<.5
        if post and kind=='support_drift':red=v<(.5+(4. if i%2 else -4.)/(bottom-top))
        if kind=='reference_layout_conflict' and i==1:red=u<.5
        if post and kind=='scrambled':red=(xx+yy)%2==0
        if post and kind=='diagonal_swap':red=u>v
        if post and kind=='alternating' and i%2==0:red=u<.5
        if post and kind=='late_swap' and i>=10:red=u<.5
        patch=np.where(red[:,:,None],np.array([0,0,230]),np.array([0,210,0])).astype(np.uint8)
        if post and kind in ('brightness','combined'):patch=(patch.astype(float)*.82).astype(np.uint8)
        if post and kind=='occluded':patch[:,:(right-left)//2]=60
        image[top:bottom,left:right]=patch
        dx,dy=(1,1) if post and kind in ('crop','combined') else (0,0)
        detections[i]=[(float(x+dx),float(y+dy),float(x+w+dx),float(y+h+dy),.95)]
        f=pool/f'observation_{i:04d}.jpg';assert cv2.imwrite(str(f),image,[cv2.IMWRITE_JPEG_QUALITY,100])
        t=(i//6)*1.4+(i%6)*.1;pts=round((origin+t)*600)
        rows.append(dict(index=i,file=f.name,sha256=ct.file_sha256(f),source_pts=pts,source_time_base='1/600',source_pts_time=pts/600.,timestamp=t))
    manifest=dict(version=1,source_origin_sec=origin,period_sec=.1,window_start=0.,window_end=2.,coverage_end=1.9,canvas=dict(width=640,height=240),pose_bindings=[],observations=rows)
    frames,motion=run_prepare(tmp_path,monkeypatch,manifest,pool,selected,scale=4.)
    def detect(self,image,*,conf_threshold=.4):
        assert conf_threshold==.4
        i=round(float(image[:8,:8].mean())/8);calls.append(i)
        return detections[i]
    monkeypatch.setattr(PersonBBoxTracker,'_detect',detect)
    lock=dict(selected_bbox=dict(x=96/640,y=48/240,width=80/640,height=144/240),manual_override=False,preview_frame_index=0)
    return pool,frames,motion,lock,calls


POSITIVE={'same','translation','scale','brightness','crop','combined'}
@pytest.mark.parametrize('kind',['same','translation','scale','brightness','crop','combined','vertical_swap','diagonal_swap','alternating','occluded','late_swap','support_drift','reference_layout_conflict','scrambled'])
def test_spatial_identity_saved_chain(tmp_path,monkeypatch,kind):
    from app.routers import analysis
    origin=-7. if kind=='combined' else 7.
    pool,frames,motion,lock,calls=make_case(tmp_path,monkeypatch,kind,origin)
    boxes=analysis._build_bbox_per_frame(frames,lock,10.,tracking_manifest=motion['continuous_tracking'],tracking_dir=pool)
    class SyntheticPose:
        def __init__(self,**kw):pass
        def process(self,image):
            ps=_keypoints(com_y=.4,knee_state='straight')
            return SimpleNamespace(pose_landmarks=SimpleNamespace(landmark=[SimpleNamespace(**{k:p[k] for k in ('x','y','z','visibility')}) for p in ps]))
        def close(self):pass
    monkeypatch.setitem(sys.modules,'mediapipe',SimpleNamespace(solutions=SimpleNamespace(pose=SimpleNamespace(Pose=SyntheticPose))))
    monkeypatch.setattr(poses,'_resolve_tasks_landmarker',lambda:None)
    pose=poses.extract_pose(str(frames[0].parent),lock,boxes,10.,frame_times=motion['selected'],slow_motion_scale=4.)
    profile,route=infer_analysis_profile('free skating','segment',pose,motion)
    rb=consume_contract(tmp_path,pose,motion,profile,name='identity-'+kind,fps=10.,saved_images={p.name:p.read_bytes() for p in frames})
    projection=extract_projection(pose,motion)
    out=Path(os.environ['SEGMENT_EVIDENCE']);out.mkdir(exist_ok=True,parents=True)
    (out/('identity-'+kind+'.json')).write_text(json.dumps(dict(synthetic_detection=True,synthetic_landmarks=True,actual_identity_features=True,calls=calls,pose=pose,readback=rb,projection=projection,motion=motion,profile=profile),indent=2),encoding='utf8')
    assert all(f['keypoints'] for f in rb['pose']['frames'][:6])
    assert all(not f['keypoints'] for f in rb['pose']['frames'][6:8])
    end=12 if kind in POSITIVE else 10 if kind=='late_swap' else 8
    assert all(f['keypoints'] for f in rb['pose']['frames'][8:end])
    assert all(not f['keypoints'] for f in rb['pose']['frames'][max(6,end):])
    assert len(projection['segments'])==(2 if kind in POSITIVE or kind=='late_swap' else 1)
    assert len(calls)==len(set(calls))<=12
    assert profile=='step'
    assert not rb['detail']['bio_data']['jump_measurements']['rotation_count']['value']
    for i,f in enumerate(rb['pose']['frames']):
        assert f['temporal']['tracking_continuity_segment']==i//6
        t=f['temporal'];expected=(i//6)*1.4+(i%6)*.1
        assert t['binding']['source_pts']/600.-origin==pytest.approx(expected)
        if f['keypoints']:
            assert t['playback_timestamp']==pytest.approx(expected)
            assert t['analysis_timestamp']==pytest.approx(expected/4.)
        else:
            # Untrusted observations retain source binding but do not grant seek.
            assert t['playback_timestamp'] is None and t['analysis_timestamp'] is None
        if i>=6:
            evidence=f['temporal']['segment_identity']
            assert evidence['evidence_version']=='body_span_reliable_colour_v6'
            assert evidence['spatial_policy']['raw_box_pooled_gate_preserved'] is True
            assert evidence['spatial_policy']['detector_center_preserved'] is True
            assert evidence['reason']
            if kind=='support_drift':
                assert any(a.get('reason')=='identity_support_conflict' for a in evidence['attempts'])
            if kind=='reference_layout_conflict':
                assert 'identity_reference_conflict' in evidence['reason']
            if kind=='scrambled':
                assert any(a.get('reason')=='identity_evidence_unavailable' for a in evidence['attempts'])
            for ref in evidence['reference']+evidence['support']:
                original=motion['continuous_tracking']['observations'][ref['observation_index']]
                assert ref['sha256']==original['sha256'] and ref['source_pts']==original['source_pts']


@pytest.mark.parametrize('kind',['vertical_swap','diagonal_swap'])
def test_global_color_does_not_prove_spatial_identity(tmp_path,monkeypatch,kind):
    pool,frames,motion,lock,calls=make_case(tmp_path,monkeypatch,kind)
    tracker=PersonBBoxTracker()
    a,b=[cv2.imread(str(pool/f'observation_{i:04d}.jpg')) for i in (0,6)]
    box=(96.,48.,176.,192.)
    ga,gb=[tracker._appearance_signature(im,box,independent=True) for im in (a,b)]
    assert float(np.dot(ga,gb))>.98 # pooled colors hide the visible structure
    _,ds,_=ct.track_bound_pose_frames(frames,lock,motion['continuous_tracking'],pool)
    assert not any(d['identity_status']=='identity_confirmed' for d in ds[6:])
