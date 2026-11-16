"""Offline projection tests use generated landmarks, never decoded media."""
import copy
import pytest
from test_tal_evidence_chain import timed_pose
from app.services.biomechanics import attach_key_frame_candidates


def projection_pose():
    pose, motion = timed_pose()
    for i, f in enumerate(pose['frames']):
        f.update(tracker_id=1, input_binding_valid=True, projection_geometry={
            'schema_version':'pose-projection.v1', 'coordinate_space':'full_image_normalized',
            'image_width':640, 'image_height':640, 'provenance':'landmarks_mapped_to_full_image'})
        # Bilateral wrists and elbows close toward the torso over several frames.
        spread = .30 - min(i, 6)*.035
        sy = f['keypoints'][11]['y']
        for joint, x, y in [(13,.5-spread,sy+.08),(14,.5+spread,sy+.08),
                            (15,.5-spread,sy+.16),(16,.5+spread,sy+.16)]:
            f['keypoints'][joint].update(x=x,y=y,visibility=.95)
    return pose, motion


def build(pose, motion):
    return attach_key_frame_candidates({},pose,motion,'jump',20.)


def test_projection_and_pull_in_are_real_production_outputs():
    pose, motion=projection_pose()
    result=build(pose,motion)
    trajectory=result['jump_measurements']['trajectory']
    assert trajectory['status']=='available'
    assert len(trajectory['points'])==9 and len(trajectory['segments'])==1
    assert trajectory['points'][0]['x']==pytest.approx(.5)
    assert trajectory['points'][0]['y']==pytest.approx(.78)
    pull=result['jump_stages']['pull-in']
    assert pull['status']=='candidate'
    assert pull['image_ref']['frame_id']==pull['frame_id']
    assert len(pull['evidence']['support_frames'])>=3
    assert pull['playback_timestamp']==pytest.approx(pull['timestamp']*2)
    assert result['jump_measurements']['physical_height']['value'] is None


@pytest.mark.parametrize('defect', ['hip','interpolation','binding','binding_name','pts','timebase','scale','lost','geometry','duplicate','identity','event','segment','gap'])
def test_projection_preserves_holes_and_boundaries(defect):
    pose,motion=projection_pose(); f=pose['frames'][4]
    if defect=='hip': f['keypoints'][23]['visibility']=.1
    elif defect=='interpolation': f['keypoints'][24]['interpolated']=True
    elif defect=='binding': f['input_binding_valid']=False
    elif defect=='binding_name': f['temporal']['binding']['frame_id']='wrong'
    elif defect=='pts': f['temporal']['binding']['source_pts']+=100
    elif defect=='timebase': f['temporal']['binding']['source_time_base']='0/0'
    elif defect=='scale': f['temporal']['slow_motion_scale']=3
    elif defect=='lost': f['tracking_state']='lost'
    elif defect=='geometry': del f['projection_geometry']
    elif defect=='duplicate': f['frame']=pose['frames'][3]['frame']
    elif defect=='identity': f['tracker_id']=2
    elif defect=='event': f['event_id']='other-event'
    elif defect=='segment': f['temporal']['segment_id']=2
    elif defect=='gap': f['temporal']['continuous']=False
    result=build(pose,motion); tr=result['jump_measurements']['trajectory']
    assert len(tr['segments'])>=2
    assert len(tr['slots'])==len(pose['frames'])
    for segment in tr['segments']:
        indices=[tr['points'][i]['pose_index'] for i in segment['point_indices']]
        assert not (3 in indices and 5 in indices)
    candidate=result['jump_stages']['pull-in']
    if candidate['status']=='candidate':
        assert len({p['segment_id'] for p in candidate['evidence']['support_frames']})==1


def test_verified_crop_maps_to_full_image_and_missing_transform_rejects():
    pose,motion=projection_pose(); expected=build(pose,motion)['jump_measurements']['trajectory']['points']
    for f in pose['frames']:
        f['projection_geometry'].update(coordinate_space='crop_normalized',provenance='verified_crop_to_full_image',
            crop_rect={'x':64,'y':32,'width':512,'height':576})
        for p in f['keypoints']:
            p['x']=(p['x']*640-64)/512; p['y']=(p['y']*640-32)/576
    result=build(pose,motion)['jump_measurements']['trajectory']
    assert len(result['points'])==len(expected)
    for a,b in zip(expected,result['points']):
        assert (a['x'],a['y'])==pytest.approx((b['x'],b['y']))
    for f in pose['frames']: del f['projection_geometry']['crop_rect']
    assert build(pose,motion)['jump_measurements']['trajectory']['status']=='unavailable'


def test_uniform_translation_and_scale_cannot_create_contraction():
    from app.services.jump_projection import extract_projection, extract_pull_in
    pose,motion=projection_pose()
    reference=copy.deepcopy(pose['frames'][1]['keypoints'])
    for i,f in enumerate(pose['frames']):
        f['keypoints']=copy.deepcopy(reference)
        for p in f['keypoints']:
            p['x']=.5+(p['x']-.5)*(.7+i*.02)+i*.002
            p['y']=.5+(p['y']-.5)*(.7+i*.02)-i*.002
    # Keep external candidate bounds fixed so this tests contraction itself,
    # independently of the jump-routing detector.
    stages={'takeoff':{'status':'candidate','frame_id':'frame_0001'},'landing':{'status':'candidate','frame_id':'frame_0009'}}
    candidate=extract_pull_in(pose,extract_projection(pose,motion),stages)
    assert candidate['status']=='unavailable' and 'no_sustained' in candidate['reason']


@pytest.mark.parametrize('defect',['occlusion','limb_uncertain','side_view','left_right','viewpoint'])
def test_ambiguous_or_occluded_arms_cannot_create_pull_in(defect):
    pose,motion=projection_pose()
    for i,f in enumerate(pose['frames']):
        if defect=='occlusion': f['keypoints'][15]['visibility']=.1
        elif defect=='limb_uncertain': f['keypoints'][13]['quality']={'limb_consistency':{'status':'uncertain'}}
        elif defect=='side_view':
            f['keypoints'][11]['x']=.499; f['keypoints'][12]['x']=.501
        elif defect=='left_right':
            f['keypoints'][11]['x'],f['keypoints'][12]['x']=f['keypoints'][12]['x'],f['keypoints'][11]['x']
        elif defect=='viewpoint':
            f['keypoints'][11]['x']=.5-(.08 if i%2 else .03)
            f['keypoints'][12]['x']=.5+(.08 if i%2 else .03)
    assert build(pose,motion)['jump_stages']['pull-in']['status']=='unavailable'


def test_irregular_pts_and_slow_motion_keep_separate_axes():
    pose,motion=projection_pose()
    times=[0,.09,.21,.30,.41,.49,.60,.72,.81]
    for f,t,m in zip(pose['frames'],times,motion['selected']):
        f['timestamp']=t; f['temporal'].update(playback_timestamp=t,analysis_timestamp=t/2)
        f['temporal']['binding'].update(source_pts=round(t*100),source_time_base='1/100')
        m['timestamp']=t
    tr=build(pose,motion)['jump_measurements']['trajectory']
    assert len(tr['segments'])==1
    assert [p['playback_timestamp'] for p in tr['points']]==times
    assert [p['analysis_timestamp'] for p in tr['points']]==[t/2 for t in times]


def test_single_hip_point_has_no_line_and_legacy_has_no_guessed_geometry():
    pose,motion=projection_pose()
    for f in pose['frames'][1:]: f['keypoints'][23]['visibility']=0
    tr=build(pose,motion)['jump_measurements']['trajectory']
    assert len(tr['points'])==1 and tr['segments'][0]['point_indices']==[0]
    pose,motion=timed_pose()
    tr=build(pose,motion)['jump_measurements']['trajectory']
    assert tr['status']=='unavailable' and not tr['points']


def test_projection_actual_report_sqlite_and_get(tmp_path):
    from test_tal_persistence import consume_contract
    pose,motion=projection_pose()
    result=consume_contract(tmp_path,pose,motion,'jump',name='projection',fps=20.)
    bio=result['detail']['bio_data']
    assert bio['jump_stages']['pull-in']['status']=='candidate'
    assert len(bio['jump_measurements']['trajectory']['points'])==9
    assert result['detail']['report']['jump_measurements']==bio['jump_measurements']


@pytest.mark.parametrize('rect', ['invalid', [0, 0, 1, 1], {'x':0,'y':0,'width':-1,'height':640}])
def test_malformed_crop_metadata_is_a_gap_not_a_crash(rect):
    pose,motion=projection_pose()
    pose['frames'][4]['projection_geometry'].update(coordinate_space='crop_normalized',provenance='verified_crop_to_full_image',crop_rect=rect)
    tr=build(pose,motion)['jump_measurements']['trajectory']
    assert len(tr['points'])==8 and len(tr['segments'])==2
    assert tr['slots'][4]['reason']=='missing_verified_image_transform'


def test_arms_only_candidate_does_not_claim_missing_legs():
    pose,motion=projection_pose()
    # Intermediate legs absent, leaving the independently validated TAL anchors.
    for f in pose['frames'][4:7]:
        for j in (25,26,27,28): f['keypoints'][j]['visibility']=0
    pull=build(pose,motion)['jump_stages']['pull-in']
    assert pull['status']=='candidate'
    assert pull['evidence']['body_scope']=='arms_only'
    assert pull['evidence']['legs_observable'] is False
