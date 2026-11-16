"""Frozen reference translation contracts; JPEGs real, detections/landmarks synthetic."""
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


def patterned_case(tmp_path, monkeypatch, kind, origin=9., *, colours=None, perturb=None, jpeg_quality=100):
    pool=tmp_path/'pool'; pool.mkdir(); selected=tmp_path/'selected'; selected.mkdir()
    rows=[]; boxes={}; calls=[]
    for i in range(12):
        post=i>=6; x,y,w,h=102,44,88,156
        if post and kind=='scale': x,y,w,h=300,38,96,170
        image=np.full((240,640,3),18,np.uint8); image[:8,:8]=i*8
        # An asymmetric three-colour textile independent of earlier two-colour fixtures.
        x0,x1=round(x+w*.18),round(x+w*.82); y0,y1=round(y+h*.18),round(y+h*.62)
        yy,xx=np.mgrid[0:y1-y0,0:x1-x0]; u=(xx+.5)/(x1-x0); v=(yy+.5)/(y1-y0)
        labels=np.where(v<.44,np.where(u<.36,0,1),np.where(u<.72,2,0))
        if post and kind in ('different','after_switch') and (kind!='after_switch' or i==10): labels=np.where(v<.44,np.where(u<.70,1,0),np.where(u<.42,0,2))
        if post and kind=='vertical_swap': labels=labels[::-1]
        if post and kind=='horizontal_swap': labels=labels[:,::-1]
        if post and kind=='alternating' and i%2: labels=labels[:,::-1]
        if post and kind=='permuted': labels=(labels+1)%3
        palette=np.array(colours if colours is not None else [[30,42,224],[38,195,51],[206,58,32]],np.uint8)
        patch=palette[labels].astype(float)
        texture=(1+(.04*((xx//4+yy//5)%2)*2-.04))[:,:,None]; patch*=texture
        if post and kind=='brightness': patch*=.82
        if kind in ('gray','background_only'): patch[:]=95
        if kind=='occluded' and post: patch[:,:patch.shape[1]*3//4]=80
        if post and kind=='pose': patch[:3,-5:]=18 # small edge deformation, no body-side swap
        if perturb is not None: patch=perturb(patch,i)
        image[y0:y1,x0:x1]=np.clip(patch,0,255).astype(np.uint8)
        if kind=='background_only':
            image[y0:y1,x0:x0+2]=[0,0,230] # clothing region has no observable textile
        dx=dy=0.
        if kind=='jitter':
            dx=(-1.5,0.,1.5)[i%3]; dy=(-1.,0.,1.)[i%3]
        if post and kind=='mild_crop': dx,dy=2.,1.
        if post and kind=='large_shift': dx=12.
        if kind=='insufficient_reference' and i in (1,2,3,4,5): ds=[]
        else: ds=[(x+dx,y+dy,x+w+dx,y+h+dy,.95)]
        if post and kind=='ambiguous':
            image[y0:y1,x0+260:x1+260]=image[y0:y1,x0:x1]; ds.append((x+260.,y+0.,x+w+260.,y+h+0.,.95))
        if post and kind=='tiny': ds=[(x+0.,y+0.,x+18.,y+30.,.95)]
        boxes[i]=ds
        path=pool/f'observation_{i:04d}.jpg'; assert cv2.imwrite(str(path),image,[cv2.IMWRITE_JPEG_QUALITY,jpeg_quality])
        t=(i//6)*1.4+(i%6)*.1; pts=round((origin+t)*600)
        rows.append(dict(index=i,file=path.name,sha256=ct.file_sha256(path),source_pts=pts,source_time_base='1/600',source_pts_time=pts/600.,timestamp=t))
    manifest=dict(version=1,source_origin_sec=origin,period_sec=.1,window_start=0.,window_end=2.,coverage_end=1.9,canvas=dict(width=640,height=240),pose_bindings=[],observations=rows)
    frames,motion=run_prepare(tmp_path,monkeypatch,manifest,pool,selected,scale=4.)
    def detect(self,image,*,conf_threshold=.4):
        assert conf_threshold==.4
        index=round(float(image[:8,:8].mean())/8); calls.append(index); return boxes[index]
    monkeypatch.setattr(PersonBBoxTracker,'_detect',detect)
    b=boxes[0][0]; lock=dict(selected_bbox=dict(x=b[0]/640,y=b[1]/240,width=(b[2]-b[0])/640,height=(b[3]-b[1])/240),manual_override=False,preview_frame_index=0)
    return pool,frames,motion,lock,calls,boxes


POSITIVE={'same','jitter','mild_crop','scale','brightness','pose'}
def assert_reference_saved_consumer_chain(tmp_path,monkeypatch,kind,*,case_factory=patterned_case,positives=POSITIVE,evidence_prefix='reference'):
    from app.routers import analysis
    origin=-9. if kind in ('jitter','brightness') else 9.
    pool,frames,motion,lock,calls,detection_records=case_factory(tmp_path,monkeypatch,kind,origin)
    boxes=analysis._build_bbox_per_frame(frames,lock,10.,tracking_manifest=motion['continuous_tracking'],tracking_dir=pool)
    class SyntheticPose:
        def __init__(self,**kw): pass
        def process(self,image):
            ps=_keypoints(com_y=.4,knee_state='straight')
            return SimpleNamespace(pose_landmarks=SimpleNamespace(landmark=[SimpleNamespace(**{k:p[k] for k in ('x','y','z','visibility')}) for p in ps]))
        def close(self): pass
    monkeypatch.setitem(sys.modules,'mediapipe',SimpleNamespace(solutions=SimpleNamespace(pose=SimpleNamespace(Pose=SyntheticPose))))
    monkeypatch.setattr(poses,'_resolve_tasks_landmarker',lambda:None)
    pose=poses.extract_pose(str(frames[0].parent),lock,boxes,10.,frame_times=motion['selected'],slow_motion_scale=4.)
    profile,route=infer_analysis_profile('free skating','segment',pose,motion)
    rb=consume_contract(tmp_path,pose,motion,profile,name=evidence_prefix+'-'+kind,fps=10.,saved_images={p.name:p.read_bytes() for p in frames})
    projection=extract_projection(pose,motion)
    out=Path(os.environ['SEGMENT_EVIDENCE']); out.mkdir(parents=True,exist_ok=True)
    evidence=dict(input_provenance=[{**r,"synthetic_detection_boxes":detection_records[r["index"]]} for r in motion["continuous_tracking"]["observations"]],synthetic_detection=True,synthetic_landmarks=True,actual_jpeg_features=True,calls=calls,pose=pose,readback=rb,projection=projection,motion=motion,profile=profile,route=route)
    (out/(evidence_prefix+'-'+kind+'.json')).write_text(json.dumps(evidence,indent=2),encoding='utf8')
    actual=[bool(f['keypoints']) for f in rb['pose']['frames']]
    assert all(actual[:6]) if kind!='insufficient_reference' else actual[0]
    expected=([False,False]+[True]*4) if kind in positives else ([False,False,True,True,False,False] if kind=='after_switch' else [False]*6)
    assert actual[6:]==expected,(kind,actual,[f['temporal'].get('segment_identity') for f in pose['frames'][6:7]])
    assert len(projection['segments'])==(2 if kind in positives or kind=='after_switch' else 1)
    assert len(calls)==len(set(calls))<=12
    assert profile=='step' and not route['jump_gate_passed']
    for i,f in enumerate(rb['pose']['frames']):
        t=f['temporal']; expected_time=(i//6)*1.4+(i%6)*.1
        assert t['binding']['source_pts']/600-origin==pytest.approx(expected_time)
        assert t['tracking_continuity_segment']==i//6
        if f['keypoints']:
            assert t['playback_timestamp']==pytest.approx(expected_time)
            assert t['analysis_timestamp']==pytest.approx(expected_time/4)
        elif i>=6: assert t['playback_timestamp'] is None and t['analysis_timestamp'] is None
    for name,node in rb['detail']['report']['jump_stages'].items():
        assert node['frame_id'] is None and node['timestamp'] is None
    if kind in positives:
        policy=rb['pose']['frames'][8]['temporal']['segment_identity']
        assert len(policy['reference'])==len(policy['support'])==3
        assert policy['anchor']['observation_index']==8
        assert [r['observation_index'] for r in policy['reference']]==[0,1,2]
        assert all(r['image_binding_valid'] for r in policy['reference']+policy['support'])
        assert policy['feature_cost']['cache_entries_peak'] <= 64
        for check in policy['spatial_policy']['reference_checks']:
            for comparison in check['comparisons']:
                assert max(map(abs,comparison['alignment']['offset_torso'])) <= 1/16
        json.dumps(policy,allow_nan=False)


def test_registration_argument_order_and_large_structure_motion(tmp_path,monkeypatch):
    from test_tracking_identity_contract import make_case
    pool,_,_,_,_=make_case(tmp_path,monkeypatch,'support_drift')
    tracker=PersonBBoxTracker.__new__(PersonBBoxTracker)
    a,b=[tracker._independent_identity_signature(cv2.imread(str(pool/f'observation_{i:04d}.jpg')),
                                                (96,48,176,192)) for i in (6,7)]
    forward=tracker._independent_identity_scores(a,b)
    assert forward == tracker._independent_identity_scores(b,a)
    assert forward['raw']['structure_correlation'] < .85
    assert forward['alignment']['status']=='out_of_bounds'
    assert forward['alignment']['outside_structure'] > forward['alignment']['best_allowed_structure']
    assert forward['structure_correlation'] < .85
    json.dumps(forward,allow_nan=False)


@pytest.mark.parametrize('kind',['same','jitter','mild_crop','scale','brightness','pose','vertical_swap','horizontal_swap','alternating','permuted','different','gray','background_only','occluded','ambiguous','insufficient_reference','after_switch','large_shift','tiny'])
def test_reference_saved_consumer_chain(tmp_path,monkeypatch,kind):
    assert_reference_saved_consumer_chain(tmp_path,monkeypatch,kind)


@pytest.mark.parametrize('kind', ['jitter', 'horizontal_swap', 'large_shift'])
def test_alignment_preserves_frozen_evidence_and_detector_boxes(tmp_path, monkeypatch, kind):
    """Scoring may align a descriptor, but cannot rewrite identity evidence."""
    import copy

    pool, _, _, _, _, detections = patterned_case(tmp_path, monkeypatch, kind)
    tracker = PersonBBoxTracker.__new__(PersonBBoxTracker)
    boxes_before = copy.deepcopy(detections)
    reference, candidate = [
        tracker._independent_identity_signature(
            cv2.imread(str(pool / f'observation_{i:04d}.jpg')), detections[i][0][:4])
        for i in (0, 8)
    ]
    assert reference is not None and candidate is not None
    frozen = copy.deepcopy((reference, candidate))

    def unchanged(actual, expected):
        if isinstance(expected, np.ndarray):
            np.testing.assert_array_equal(actual, expected)
        elif isinstance(expected, dict):
            assert actual.keys() == expected.keys()
            for key in expected:
                unchanged(actual[key], expected[key])
        elif isinstance(expected, (list, tuple)):
            assert len(actual) == len(expected)
            for item, original in zip(actual, expected, strict=True):
                unchanged(item, original)
        else:
            assert actual == expected

    forward = tracker._independent_identity_scores(reference, candidate)
    reverse = tracker._independent_identity_scores(candidate, reference)
    assert forward == reverse
    assert tracker._independent_identity_scores(reference, candidate) == forward
    unchanged((reference, candidate), frozen)
    assert detections == boxes_before
    for signature in (reference, candidate):
        assert 1 + len(signature['alignment_variants']) <= 49
        for variant in signature['alignment_variants']:
            extent = max(map(abs, variant['offset_torso']))
            assert extent <= 1 / 8
            assert variant['in_bounds'] == (extent <= 1 / 16)
    passes = all(forward[key] >= minimum for key, minimum in (
        ('pooled_cosine', .90), ('layout_mean', .90),
        ('layout_lower_quartile', .75), ('structure_correlation', .85)))
    assert passes == (kind == 'jitter')
