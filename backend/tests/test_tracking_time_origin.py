"""Three distinct clocks across bound inputs and saved jump evidence, offline only."""
from fractions import Fraction
import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from app.services.person_tracker import PersonBBoxTracker
from app.services.pose_observations import verified_source_time, observation_time_error
from test_tracking_clock_contract import offline, fixture_pool, run_prepare


def assert_clocks(point, origin, scale, *, stage=False):
    source = float(point['source_pts'] * Fraction(point['source_time_base']))
    assert point['source_timestamp'] == pytest.approx(source, abs=1e-8), point
    assert point['playback_timestamp'] == pytest.approx(source-origin, abs=1e-8), point
    assert point['timestamp' if stage else 'analysis_timestamp'] == pytest.approx((source-origin)/scale, abs=1e-8), point
    assert point['input_binding']['source_origin_sec'] == origin
    assert point['input_binding']['source_pts'] == point['source_pts']
    assert point['input_binding']['source_time_base'] == point['source_time_base']


def temporal(origin=7., scale=4., playback=.1):
    return dict(time_source='bound_source_pts', playback_timestamp=playback,
                analysis_timestamp=playback/scale, slow_motion_scale=scale,
                binding=dict(source_pts=round((origin+playback)*600),
                             source_time_base='1/600', source_origin_sec=origin))


@pytest.mark.parametrize('origin', [0., 7., -7.])
@pytest.mark.parametrize('scale', [1., 4.])
@pytest.mark.parametrize('window', [0., 2.])
def test_bound_three_clock_mapping(origin, scale, window):
    t = temporal(origin, scale, window+.1)
    assert observation_time_error({'temporal':t}) is None
    assert verified_source_time(t) == pytest.approx(origin+window+.1, abs=1e-8)


@pytest.mark.parametrize('field,value', [
    ('source_pts', None), ('source_pts', True), ('source_pts', 4260.5),
    ('source_pts', 4260.), ('source_pts', '4260'), ('source_pts', float('nan')),
    ('source_pts', float('inf')), ('source_pts', 10**400),
    ('source_time_base', '0/600'), ('source_time_base', '-1/600'),
    ('source_time_base', '1/0'), ('source_time_base', True),
    ('source_time_base', None), ('source_time_base', '1e400'), ('source_time_base', '1e-400'),
    ('source_origin_sec', None), ('source_origin_sec', True),
    ('source_origin_sec', float('nan')), ('source_origin_sec', float('inf')),
    ('source_origin_sec', 8.),
])
def test_invalid_bound_source_is_not_repaired(field, value):
    t = temporal(); t['binding'][field] = value
    assert verified_source_time(t) is None
    assert observation_time_error({'temporal':t}) == 'bound_source_time_invalid'


@pytest.mark.parametrize('field,value', [
    ('playback_timestamp', -.1), ('playback_timestamp', float('nan')),
    ('playback_timestamp', float('inf')), ('playback_timestamp', True),
    ('playback_timestamp', .5), ('slow_motion_scale', 0), ('slow_motion_scale', -1),
    ('slow_motion_scale', True), ('slow_motion_scale', float('nan')),
    ('slow_motion_scale', float('inf')), ('slow_motion_scale', None),
    ('analysis_timestamp', float('nan')), ('analysis_timestamp', float('inf')),
    ('analysis_timestamp', True), ('analysis_timestamp', -.1), ('analysis_timestamp', .1),
])
def test_invalid_playback_or_analysis_still_rejected(field, value):
    t = temporal(); t[field] = value
    expected = 'bound_source_time_invalid' if field == 'playback_timestamp' else 'bound_analysis_time_or_scale_invalid'
    assert observation_time_error({'temporal':t}) == expected


def test_missing_historical_origin_keeps_zero_origin_and_no_mapping_is_invented():
    t = temporal(0.); del t['binding']['source_origin_sec']
    before = copy.deepcopy(t)
    assert observation_time_error({'temporal':t}) is None
    assert verified_source_time(t) == pytest.approx(.1)
    assert t == before and 'source_origin_sec' not in t['binding']
    t['time_source'] = 'legacy_or_sampling_time_unverified'
    assert verified_source_time(t) is None
    assert observation_time_error({'temporal':t}) is None


@pytest.mark.parametrize('origin', [0., 7., -7.])
@pytest.mark.parametrize('scale', [1., 4.])
@pytest.mark.parametrize('window', [0., 2.])
def test_three_clocks_through_production_and_saved_get(tmp_path,monkeypatch,origin,scale,window):
    import sys
    from app.services import pose as poses
    from app.services import keyframe_candidates as kc, target_lock as tl
    from app.routers import analysis
    from app.services.action_profiles import infer_analysis_profile
    from app.services.pose_observations import observation_slots, observation_time_error
    from test_analysis_keyframe_candidates import _keypoints
    from test_tal_persistence import consume_contract

    pts=tuple(round((origin+window)*600)+i*60 for i in range(9))+tuple(round((origin+window)*600)+600+i*60 for i in range(3))
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
    artifacts=Path(os.environ['TIME_ORIGIN_EVIDENCE']) if os.environ.get('TIME_ORIGIN_EVIDENCE') else tmp_path
    artifacts.mkdir(parents=True,exist_ok=True)
    prefix=f'chain-origin-{origin}-scale-{scale}'+(f'-window-{window}' if window else '')
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

    assert len(result['image_reads']) == 12
    assert len(tr['points']) == 9
    for point in tr['points']:
        assert_clocks(point, origin, scale)
        assert point['input_binding'] == result['pose']['frames'][point['pose_index']]['temporal']['binding']
    for name in ('takeoff', 'apex', 'landing'):
        assert_clocks(bio['jump_stages'][name], origin, scale, stage=True)
    for frame in result['pose']['frames'][:9]:
        t = frame['temporal']
        assert t['binding']['source_origin_sec'] == origin
        source = float(t['binding']['source_pts'] * Fraction(t['binding']['source_time_base']))
        assert t['playback_timestamp'] == pytest.approx(source-origin, abs=1e-8)
        assert t['analysis_timestamp'] == pytest.approx((source-origin)/scale, abs=1e-8)
    # The gap remains a hard barrier; no fabricated motion or turn support.
    gap = result['detail']['frame_motion_scores']['motion_records'][9]
    assert gap['motion_interval'] is None and gap['motion_score'] is None
    assert bio['jump_stages']['rotation']['status'] == 'unavailable'


@pytest.mark.parametrize('origin', [7., -7.])
@pytest.mark.parametrize('scale', [1., 4.])
def test_rotation_support_and_representative_preserve_source_clock(tmp_path, monkeypatch, origin, scale):
    from test_jump_rotation import rotation_pose
    from test_tal_persistence import consume_contract
    from app.services.action_profiles import infer_analysis_profile
    pose, motion = rotation_pose()
    saved = {}
    window = 2.
    for i, frame in enumerate(pose['frames']):
        playback = window+i/10
        frame['timestamp'] = playback
        frame['temporal'].update(temporal(origin, scale, playback))
        assert observation_time_error(frame) is None
        encoded, image = cv2.imencode('.jpg', np.full((640,640,3), i*10, np.uint8))
        assert encoded
        saved[frame['frame']] = image.tobytes()
    # Reuse the existing rotation-positive fixture under its controlled jump
    # profile. It is not an automatic jump classification or a human label.
    for record, frame in zip(motion['selected'], pose['frames'], strict=True):
        record['timestamp'] = frame['timestamp']
    profile, evidence = infer_analysis_profile('自由滑', '节目片段', pose, motion)
    assert profile == 'step'  # This fixture never established automatic jump routing.
    prefix = f'rotation-origin-{origin}-scale-{scale}'
    result = consume_contract(tmp_path,pose,motion,'jump',name=prefix,fps=10.,saved_images=saved)
    artifacts = Path(os.environ.get('TIME_ORIGIN_EVIDENCE', str(tmp_path)))
    artifacts.mkdir(parents=True,exist_ok=True)
    (artifacts/(prefix+'-readback.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    (artifacts/(prefix+'-inputs.json')).write_text(json.dumps(dict(pose=pose,motion=motion,automatic_profile=profile,automatic_evidence=evidence,controlled_builder_profile='jump'),ensure_ascii=False,indent=2),encoding='utf8')
    bio = result['detail']['bio_data']; r = bio['jump_stages']['rotation']
    assert r['status'] == 'candidate', r
    assert_clocks(r, origin, scale, stage=True)
    for point in r['evidence']['support_frames']:
        assert_clocks(point, origin, scale)
    for sequence in r['evidence']['observation_sequences']:
        for point in sequence['support_frames']:
            assert_clocks(point, origin, scale)
    for name in ('takeoff', 'pull-in', 'apex', 'landing'):
        stage = bio['jump_stages'][name]
        assert stage['status'] == 'candidate'
        assert_clocks(stage, origin, scale, stage=True)
        for point in stage['evidence'].get('support_frames', []):
            if 'source_pts' in point:
                assert_clocks(point, origin, scale)
    assert r['frame_id'] == r['evidence']['support_frames'][-1]['frame_id']
    assert bio['jump_measurements']['rotation_count']['value'] is None
    assert bio['jump_measurements']['air_time']['value'] is None
    assert len(result['image_reads']) == len(pose['frames'])
