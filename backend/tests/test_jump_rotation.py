"""Label-free synthetic projection changes, checked through the production builder."""
import copy
import math
import pytest
from test_jump_projection import projection_pose, build


def rotation_pose():
    pose, motion = projection_pose()
    for i, f in enumerate(pose['frames']):
        s = i / 8
        k = f['keypoints']
        sy = (k[11]['y'] + k[12]['y']) / 2
        hy = (k[23]['y'] + k[24]['y']) / 2
        for left, right, y, width in [(11,12,sy,.16*(1-.55*s)), (23,24,hy,.12*(1-.55*s)),
                                      (7,8,sy-.075,.10*(1-.4*s)), (2,5,sy-.08,.05*(1-.4*s))]:
            center = .5 + (.004*s if left == 2 else 0)
            for j,x in [(left,center-width/2),(right,center+width/2)]:
                k[j].update(x=x,y=y,visibility=.95)
        k[0].update(x=.5+.03*s,y=sy-.05,visibility=.95)
    return pose, motion


def test_rotation_positive_uses_real_builder_with_supported_endpoint():
    pose,motion=rotation_pose()
    bio=build(pose,motion)
    r=bio['jump_stages']['rotation']
    assert r['status']=='candidate', r
    support=r['evidence']['support_frames']
    assert len(support)>=4
    assert r['frame_id']==support[-1]['frame_id']
    assert r['image_ref']==support[-1]['image_ref']
    assert r['timestamp']==support[-1]['analysis_timestamp']
    assert r['playback_timestamp']==pytest.approx(r['timestamp']*2)
    assert r['evidence']['interval_basis']=='takeoff_landing_candidates_not_confirmed_airborne'
    assert all(bio['jump_stages']['takeoff']['timestamp'] <= p['analysis_timestamp'] <= bio['jump_stages']['landing']['timestamp'] for p in support)
    assert len({p['segment_id'] for p in support})==1
    assert bio['jump_measurements']['rotation_count']['value'] is None
    assert bio['jump_metrics'] is None


def fixed_bounds(pose, motion):
    # Existing candidate authority is still revalidated against these frames.
    # This isolates the turn signals from the separate jump-routing heuristic.
    from app.services.jump_stages import attach_jump_stages
    baseline,meta=rotation_pose()
    selected=build(baseline,meta)['key_frame_candidates']
    return attach_jump_stages({'key_frame_candidates':selected},pose,motion,'jump')


@pytest.mark.parametrize('mode',['translation_scale','tilt_only','camera_roll','shoulder_only','face_only','width_only','side_view','left_right','incompatible_face','viewpoint_ratio'])
def test_no_candidate_from_ambiguous_or_rigid_changes(mode):
    pose,motion=rotation_pose()
    base=copy.deepcopy(pose['frames'][0]['keypoints'])
    for i,f in enumerate(pose['frames']):
        k=f['keypoints']
        if mode in ('translation_scale','tilt_only','camera_roll'):
            # Constant relative pose, moved as a rigid body/image.
            current_y=k[11]['y']; base_y=base[11]['y']
            for j,p in enumerate(k):
                p.update(x=base[j]['x'],y=base[j]['y']+current_y-base_y)
            angle=(i*.06 if mode!='translation_scale' else 0)
            scale=.8+i*.025
            for p in k:
                x,y=p['x']-.5,p['y']-.5
                p.update(x=.5+scale*(x*math.cos(angle)-y*math.sin(angle))+i*.002,
                         y=.5+scale*(x*math.sin(angle)+y*math.cos(angle)))
        elif mode=='shoulder_only':
            for j in (0,2,5,7,8,23,24): k[j]['x']=base[j]['x']
        elif mode=='face_only':
            for j in (11,12,23,24): k[j]['x']=base[j]['x']
        elif mode=='width_only':
            for j in (0,2,5,7,8): k[j]['x']=base[j]['x']
        elif mode=='side_view':
            k[11]['x']=.499; k[12]['x']=.501
        elif mode=='left_right' and i%2:
            for a,b in ((11,12),(23,24),(2,5),(7,8)):
                k[a]['x'],k[b]['x']=k[b]['x'],k[a]['x']
        elif mode=='incompatible_face':
            # Opposing nose-eye / nose-ear changes cannot resolve direction.
            for j in (2,5): k[j]['x']+=i*.008
        elif mode=='viewpoint_ratio':
            for j in (23,24): k[j]['x']=base[j]['x']
    r=fixed_bounds(pose,motion)['jump_stages']['rotation']
    assert r['status']=='unavailable', (mode,r)
    assert r['frame_id'] is None


@pytest.mark.parametrize('defect',['missing_face','missing_hip','interpolated','uncertain','binding','binding_name','pts','timebase','duplicate','identity','event','segment','explicit_gap','time_reversal','unverified_time'])
def test_never_accumulates_across_rejected_support(defect):
    pose,motion=rotation_pose(); f=pose['frames'][5]
    if defect=='missing_face': f['keypoints'][7]['visibility']=.1
    elif defect=='missing_hip': f['keypoints'][23]['visibility']=.1
    elif defect=='interpolated': f['keypoints'][5]['interpolated']=True
    elif defect=='uncertain': f['keypoints'][7]['quality']={'analysis_usable':False}
    elif defect=='binding': f['input_binding_valid']=False
    elif defect=='binding_name': f['temporal']['binding']['frame_id']='wrong-frame'
    elif defect=='pts': f['temporal']['binding']['source_pts']+=100
    elif defect=='timebase': f['temporal']['binding']['source_time_base']='0/0'
    elif defect=='duplicate': f['frame']=pose['frames'][4]['frame']
    elif defect=='identity': f['tracker_id']=2
    elif defect=='event': f['event_id']='other-event'
    elif defect=='segment': f['temporal']['segment_id']=2
    elif defect=='explicit_gap': f['temporal']['continuous']=False
    elif defect=='time_reversal': f['temporal']['analysis_timestamp']=.05
    elif defect=='unverified_time': f['temporal']['time_source']='sampling_estimate'
    r=fixed_bounds(pose,motion)['jump_stages']['rotation']
    assert r['status']=='unavailable'
    assert r['frame_id'] is None
    production=build(pose,motion)['jump_stages']['rotation']
    if production['status']=='candidate':
        refs=production['evidence']['support_frames']
        assert len({(p['segment_id'],p['event_id'],p['tracker_id']) for p in refs})==1
        assert all(b['pose_index']==a['pose_index']+1 for a,b in zip(refs,refs[1:]))
        assert not (refs[0]['pose_index']<5<refs[-1]['pose_index'])
    for run in r['evidence']['observation_sequences']:
        refs=run['support_frames']
        assert len({(p['segment_id'],p['event_id'],p['tracker_id']) for p in refs})==1
        assert all(b['pose_index']==a['pose_index']+1 for a,b in zip(refs,refs[1:]))
        assert not (refs[0]['pose_index']<5<refs[-1]['pose_index'])


def test_irregular_pts_slow_motion_and_overlapping_nodes():
    pose,motion=rotation_pose()
    times=[0,.09,.21,.30,.41,.49,.60,.72,.81]
    for f,t,m in zip(pose['frames'],times,motion['selected']):
        f['timestamp']=t
        f['temporal'].update(playback_timestamp=t,analysis_timestamp=t/2)
        f['temporal']['binding'].update(source_pts=round(t*100),source_time_base='1/100')
        m['timestamp']=t
    bio=build(pose,motion);r=bio['jump_stages']['rotation']
    assert r['status']=='candidate'
    refs=r['evidence']['support_frames']
    assert [p['playback_timestamp'] for p in refs]==[times[p['pose_index']] for p in refs]
    assert all(p['analysis_timestamp']==p['playback_timestamp']/2 for p in refs)
    assert r['evidence']['support_interval']['end']==refs[-1]['analysis_timestamp']
    assert bio['jump_stages']['apex']['frame_id'] in [p['frame_id'] for p in refs]


def test_partial_window_retains_only_observations_and_nonjump_is_not_applicable():
    from app.services.jump_stages import attach_jump_stages
    pose,motion=rotation_pose()
    bio=attach_jump_stages({'key_frame_candidates':{}},pose,motion,'jump')
    r=bio['jump_stages']['rotation']
    assert r['status']=='unavailable' and r['evidence']['observation_sequences']
    assert r['evidence']['support_frames']==[]
    assert r['reason']=='compatible_takeoff_landing_candidate_support_required'
    nonjump=attach_jump_stages({},pose,motion,'step')
    assert nonjump['jump_stages']['rotation']['status']=='not_applicable'
