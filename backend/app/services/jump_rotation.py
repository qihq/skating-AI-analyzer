"""Conservative multi-cue *projected turn* candidates, not a 3-D angle estimator.

Shoulder/hip widths are measured perpendicular to the torso axis, in pixels /
torso length. Nose offsets from bilateral ears AND eyes are measured on that
same lateral axis / their signed widths. Coherent torso foreshortening plus
independent face-direction change over >=4 contiguous validated observations
may support a rotation candidate. A shoulder-line angle alone never does.
Translation, uniform scaling and image-plane rotation leave the ratios fixed.
No z coordinates, legacy rotation_rps, labels, frame-index time or unwrap.
Camera orbit, pose deformation and head/body articulation remain unresolved;
a candidate is NOT confirmed axial/airborne rotation, a direction or turns.
"""
from copy import deepcopy
import math

from .jump_projection import _geometry, _point

METHOD = 'bilateral_torso_face_projected_turn.v1'
LIMITATIONS = ['2d_projection_not_3d_body_angle', 'camera_viewpoint_change_not_excluded',
               'head_body_articulation_not_excluded', 'not_confirmed_airborne',
               'left_right_correspondence_model_dependent', 'no_rotation_count_or_direction']
JOINTS = (0, 2, 5, 7, 8, 11, 12, 23, 24)


def _signals(frame):
    g, reason = _geometry(frame)
    if reason:
        return None, reason
    points = {j: _point(frame, j, g) for j in JOINTS}
    if any(p is None for p in points.values()):
        return None, 'bilateral_face_shoulder_hip_support_required'
    p = {j: (v[0]*g['image_width'], v[1]*g['image_height']) for j,v in points.items()}
    mid = lambda a,b: tuple((p[a][k]+p[b][k])/2 for k in (0,1))
    shoulder, hip = mid(11,12), mid(23,24)
    axis = (hip[0]-shoulder[0], hip[1]-shoulder[1])
    length = math.hypot(*axis)
    if length < 1:
        return None, 'degenerate_torso_projection'
    lateral = lambda v: (v[0]*axis[1]-v[1]*axis[0])/length**2
    width = lambda a,b: lateral((p[b][0]-p[a][0],p[b][1]-p[a][1]))
    widths = {'shoulder_width': width(11,12), 'hip_width': width(23,24),
              'ear_width': width(7,8), 'eye_width': width(2,5)}
    sign = 1 if widths['shoulder_width'] > 0 else -1
    if any(sign*v < threshold for v,threshold in zip(widths.values(),(.18,.12,.12,.06))):
        return None, 'side_view_or_left_right_ambiguity'
    # Very oblique bilateral lines do not provide comparable lateral widths.
    for a,b in ((11,12),(23,24),(7,8),(2,5)):
        dy = ((p[b][0]-p[a][0])*axis[0]+(p[b][1]-p[a][1])*axis[1])/length**2
        if abs(dy) > abs(width(a,b))*.35:
            return None, 'bilateral_axis_or_viewpoint_inconsistent'
    offsets = {}
    for name,a,b in (('nose_ear_offset',7,8),('nose_eye_offset',2,5)):
        center = mid(a,b)
        offsets[name] = lateral((p[0][0]-center[0],p[0][1]-center[1])) / width(a,b)
    if abs(offsets['nose_ear_offset']) > .48 or abs(offsets['nose_eye_offset']) > .9:
        return None, 'face_correspondence_or_side_view_ambiguous'
    if offsets['nose_ear_offset']*offsets['nose_eye_offset'] < 0 and min(abs(v) for v in offsets.values()) > .04:
        return None, 'incompatible_face_direction'
    return {**widths, **offsets, 'laterality': sign,
            'torso_axis_radians': math.atan2(axis[1],axis[0]),
            'units': 'torso_relative_widths_and_bilateral_face_relative_offsets'}, None


def _view_error(first, current):
    angle = abs(math.atan2(math.sin(current['torso_axis_radians']-first['torso_axis_radians']),
                          math.cos(current['torso_axis_radians']-first['torso_axis_radians'])))
    if first['laterality'] != current['laterality']:
        return 'left_right_correspondence_changed'
    if angle > math.radians(15):
        return 'torso_axis_or_camera_roll_change'
    for a,b in (('shoulder_width','hip_width'),('ear_width','eye_width')):
        if abs((current[a]/current[b])/(first[a]/first[b])-1) > .25:
            return 'incompatible_bilateral_viewpoint_change'
    return None


def _change(first, last):
    return {k:last[k]-first[k] for k in ('shoulder_width','hip_width','nose_ear_offset','nose_eye_offset')}


def _supported(window):
    if len(window) < 4:
        return None
    a,b = window[0]['signals'],window[-1]['signals']
    d = _change(a,b)
    # Widths must change together, face offsets independently agree in direction.
    if (d['shoulder_width']*d['hip_width'] <= 0 or
        d['nose_ear_offset']*d['nose_eye_offset'] <= 0 or
        abs(d['shoulder_width']) < .08 or abs(d['hip_width']) < .05 or
        abs(d['shoulder_width']/a['shoulder_width']) < .20 or
        abs(d['hip_width']/a['hip_width']) < .20 or
        abs(d['nose_ear_offset']) < .12 or abs(d['nose_eye_offset']) < .10):
        return None
    # Foreshortening must agree with turning away from/toward a frontal
    # face projection, rather than unrelated head movement in the other sense.
    if any(d['shoulder_width']*a['laterality']*(abs(b[k])-abs(a[k])) >= 0
           for k in ('nose_ear_offset','nose_eye_offset')):
        return None
    # Every adjacent observation participates; a jump, reversal, or gap cannot
    # be turned into net angular displacement. Tolerances are projection ratios.
    for previous,current in zip(window,window[1:]):
        ps,cs = previous['signals'],current['signals']
        for k in d:
            step = cs[k]-ps[k]
            if step*(1 if d[k]>0 else -1) < -.02:
                return None
        if any(abs(cs[k]/ps[k]-1) > .35 for k in ('shoulder_width','hip_width','ear_width','eye_width')):
            return None
        if any(abs(cs[k]-ps[k]) > .30 for k in ('nose_ear_offset','nose_eye_offset')):
            return None
    return sum(abs(v) for v in d.values()), d


def extract_rotation(pose, trajectory, stages):
    result = {'status':'unavailable', 'frame_id':None, 'image_ref':None,
              'timestamp':None, 'playback_timestamp':None, 'confidence':None,
              'source':METHOD, 'reason':'compatible_takeoff_landing_candidate_support_required',
              'quality_flags':[], 'warnings':LIMITATIONS.copy(),
              'contact_evidence_status':'uncertain', 'evidence':{}}
    points = trajectory.get('points',[])
    by_key = {p['frame_id']:p for p in points}
    t,l = stages['takeoff'],stages['landing']
    first,last = by_key.get(t.get('frame_id')),by_key.get(l.get('frame_id'))
    compatible = (t['status']==l['status']=='candidate' and first and last and
                  first['segment_id']==last['segment_id'] and first['pose_index']<last['pose_index'])
    bounds = {'takeoff':deepcopy(t), 'landing':deepcopy(l)}
    evidence = {'candidate_bounds':bounds, 'interval_basis':'takeoff_landing_candidates_not_confirmed_airborne',
                'support_frames':[], 'support_interval':None, 'observation_sequences':[],
                'rejected_support':[], 'measurement':'torso_foreshortening_and_bilateral_face_direction_projection',
                'support_point_ids':list(JOINTS)}
    result['evidence'] = evidence
    # Keep legal observed projections even if the event window lacks compatible
    # candidate boundaries, but never promote them to a rotation candidate.
    selected = [p for p in points if not compatible or first['pose_index'] <= p['pose_index'] <= last['pose_index']]
    runs=[]; run=[]
    for point in selected:
        signal,reason = _signals(pose['frames'][point['pose_index']])
        if signal and (point.get('source_timestamp') is None or point.get('time_source') != 'bound_source_pts'):
            reason='verified_source_pts_required'; signal=None
        if signal and run:
            prev = run[-1]
            if point['segment_id'] != prev['segment_id'] or point['pose_index'] != prev['pose_index']+1:
                runs.append(run); run=[]
            elif _view_error(run[0]['signals'],signal):
                reason=_view_error(run[0]['signals'],signal); signal=None
        if reason:
            if run: runs.append(run); run=[]
            evidence['rejected_support'].append({'frame_id':point['frame_id'],'reason':reason})
            continue
        ref=deepcopy(point)
        ref['signals']=signal
        ref['quality']['points']='bilateral_face_shoulders_hips_analysis_usable_visibility_at_least_0.5'
        run.append(ref)
    if run: runs.append(run)
    evidence['rejected_support'].extend(deepcopy(s) for s in trajectory.get('slots',[]) if s['status']!='available')
    evidence['observation_sequences']=[{'status':'observed_projection_only','support_frames':r,
        'reason':'projected_signals_do_not_alone_establish_rotation'} for r in runs if len(r)>=2]
    if not compatible:
        return result
    candidates=[]
    for run in runs:
        for start in range(len(run)-3):
            for end in range(start+4,len(run)+1):
                window=run[start:end]
                supported=_supported(window)
                if supported:
                    candidates.append((supported[0],window,supported[1]))
    if not candidates:
        result['reason']='no_continuous_multicue_projected_turn_support'
        return result
    score,support,change=max(candidates,key=lambda c:c[0])
    # Endpoint maximizes actual supported signal change; never a midpoint,
    # percentile, arbitrary crossing pose or a label-derived frame.
    representative=support[-1]
    result.update(deepcopy(representative))
    result.update(status='candidate', timestamp=representative['analysis_timestamp'],
                  reason='multicue_projected_turn_candidate_viewpoint_ambiguous')
    evidence.update(support_frames=support,
        support_interval={'start':support[0]['analysis_timestamp'],'end':support[-1]['analysis_timestamp'],
                          'time_axis':'analysis','playback_start':support[0]['playback_timestamp'],
                          'playback_end':support[-1]['playback_timestamp']},
        signal_change=change, representative_basis='endpoint_of_greatest_continuous_multicue_projection_change',
        rotation_direction=None, rotation_angle=None, rotation_count=None)
    return result
