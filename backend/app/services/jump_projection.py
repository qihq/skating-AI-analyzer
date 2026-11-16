"""Validated image projection; no interpolation, camera compensation or model IO."""
from __future__ import annotations
from collections import Counter
from copy import deepcopy
import math
from .pose_quality import analysis_point, finite_number
from .pose_observations import observation_slots, observation_time_error, frame_usable, verified_source_time, _frame_key

LIMITATIONS = ['camera_motion_not_removed', '2d_projection_viewpoint_ambiguity',
               'not_physical_center_of_mass', 'not_confirmed_airborne']


def _geometry(frame):
    g = frame.get('projection_geometry') or {}
    if not isinstance(g, dict): return None, 'missing_verified_image_transform'
    if g.get('schema_version') != 'pose-projection.v1':
        return None, 'missing_verified_image_transform'
    w, h = (finite_number(g.get(k)) for k in ('image_width','image_height'))
    if w is None or h is None or w <= 0 or h <= 0:
        return None, 'invalid_image_dimensions'
    g = {**g, 'image_width':w, 'image_height':h}
    space = g.get('coordinate_space')
    if space == 'full_image_normalized' and g.get('provenance') == 'landmarks_mapped_to_full_image':
        return g, None
    rect = g.get('crop_rect') or {}
    if not isinstance(rect, dict): return None, 'missing_verified_image_transform'
    values = [finite_number(rect.get(k)) for k in ('x','y','width','height')]
    if (space == 'crop_normalized' and g.get('provenance') == 'verified_crop_to_full_image'
            and all(v is not None for v in values)):
        x,y,cw,ch = values
        if x >= 0 and y >= 0 and cw > 0 and ch > 0 and x+cw <= w and y+ch <= h:
            return {**g, 'crop_rect':dict(zip(('x','y','width','height'),values))}, None
    return None, 'missing_verified_image_transform'


def _point(frame, joint, geometry):
    p = analysis_point(frame.get('keypoints'), joint, .5)
    if p is None or p.get('usable') is False or (frame.get('usable_joint_mask') or {}).get(str(joint)) is False:
        return None
    if p.get('provenance') in ('interpolated-display-only','missing','clipped','identity-blocked'):
        return None
    x,y = float(p['x']), float(p['y'])
    if not 0 <= x <= 1 or not 0 <= y <= 1:
        return None
    if geometry['coordinate_space'] == 'crop_normalized':
        r=geometry['crop_rect']
        x=(r['x']+x*r['width'])/geometry['image_width']
        y=(r['y']+y*r['height'])/geometry['image_height']
    return x,y


def _trace(frame, index, segment):
    t=frame.get('temporal') or {}; binding=t.get('binding') or {}
    key=_frame_key(frame.get('frame') or frame.get('frame_id'))
    return {'frame_id':key, 'pose_index':index, 'image_ref':{'kind':'analysis_frame','frame_id':key},
            'source_pts':binding.get('source_pts'), 'source_time_base':binding.get('source_time_base'),
            'source_timestamp':verified_source_time(t), 'playback_timestamp':finite_number(t.get('playback_timestamp')),
            'analysis_timestamp':finite_number(t.get('analysis_timestamp',frame.get('analysis_timestamp',frame.get('timestamp')))),
            'time_source':t.get('time_source','legacy_or_sampling_time_unverified'),
            'slow_motion_scale':finite_number(t.get('slow_motion_scale')),
            'identity_id':frame.get('identity_id'), 'tracker_id':frame.get('tracker_id'),
            'event_id':frame.get('event_id'), 'continuous_segment':t.get('segment_id'),
            'segment_id':segment, 'input_binding':deepcopy(binding),
            'quality':{'tracking_state':frame.get('tracking_state'), 'input_binding_valid':frame.get('input_binding_valid'),
                       'points':'both_hips_analysis_usable_visibility_at_least_0.5'},
            'quality_flags':[], 'coordinate_space':'full_image_normalized',
            'geometry':deepcopy(frame.get('projection_geometry'))}


def extract_projection(pose, motion=None):
    frames=pose.get('frames',[]) if isinstance(pose,dict) else []
    counts=Counter(_frame_key(f.get('frame') or f.get('frame_id')) for f in frames if isinstance(f,dict))
    runs={}; run=0
    for f in observation_slots(pose, motion):
        if f is None: run+=1
        else: runs[id(f)]=run
    points=[]; slots=[]; segments=[]; previous=None; segment=-1
    for i,f in enumerate(frames):
        if not isinstance(f,dict):
            slots.append({'pose_index':i,'status':'unavailable','reason':'invalid_frame'}); previous=None; continue
        key=_frame_key(f.get('frame') or f.get('frame_id'))
        t=f.get('temporal') or {}; b=t.get('binding') or {}
        g,reason=_geometry(f)
        if not frame_usable(f): reason='frame_quality_or_binding_rejected'
        elif observation_time_error(f): reason=observation_time_error(f)
        elif id(f) not in runs: reason='shared_observation_rejected'
        elif not key or counts[key]!=1: reason='duplicate_or_missing_frame_identity'
        elif f.get('identity_id') is None and f.get('tracker_id') is None: reason='person_identity_unavailable'
        elif any(_frame_key(b[k])!=key for k in ('frame','frame_id') if k in b): reason='input_frame_binding_mismatch'
        elif f.get('identity_state')=='lost' or f.get('pose_provenance') in ('missing','identity-blocked','interpolated-display-only'): reason='identity_or_pose_rejected'
        hips=[_point(f,j,g) for j in (23,24)] if g else [None,None]
        if reason is None and any(p is None for p in hips): reason='both_valid_hips_required'
        stamp=finite_number(t.get('analysis_timestamp',f.get('analysis_timestamp',f.get('timestamp'))))
        if reason is None and (stamp is None or stamp<0): reason='analysis_time_unavailable'
        if reason:
            slots.append({'pose_index':i,'frame_id':key,'status':'unavailable','reason':reason})
            previous=None; continue
        signature=(runs[id(f)],f.get('event_id'),f.get('identity_id'),f.get('tracker_id'),
                   t.get('time_source'),t.get('slow_motion_scale'),g['image_width'],g['image_height'],g['coordinate_space'],g['provenance'])
        if previous != signature:
            segment+=1
            segments.append({'segment_id':segment,'point_indices':[], 'reason':'validated_contiguous_observations'})
        point=_trace(f,i,segment)
        point.update(x=(hips[0][0]+hips[1][0])/2,y=(hips[0][1]+hips[1][1])/2)
        segments[-1]['point_indices'].append(len(points))
        slots.append({'pose_index':i,'frame_id':key,'status':'available','point_index':len(points),'segment_id':segment})
        points.append(point); previous=signature
    return {'value':None,'status':'available' if points else 'unavailable',
            'object':'left_right_hip_midpoint_2d_projection','unit':'normalized_full_image',
            'method':'validated_bilateral_hip_midpoint.v1','reason':'camera_motion_not_removed' if points else 'no_valid_projection_points',
            'support_interval':None,'coordinate_space':'full_image_normalized',
            'normalization':'x / original_saved_image_width; y / original_saved_image_height',
            'axes':{'x':'right','y':'down'},'calibration':None,'uncertainty':'unknown_camera_and_projection_error',
            'limitations':LIMITATIONS.copy(),'points':points,'segments':segments,'slots':slots}


def _signals(frame):
    g,reason=_geometry(frame)
    if reason: return None,reason
    ids=(11,12,23,24,13,14,15,16)
    p={j:_point(frame,j,g) for j in ids}
    if any(p[j] is None for j in ids): return None,'bilateral_shoulder_hip_elbow_wrist_support_required'
    # Pixel metric avoids aspect distortion. Torso-relative ratios remove
    # translation and uniform scaling; bbox/shoulder narrowing is not a signal.
    p={j:(v[0]*g['image_width'],v[1]*g['image_height']) for j,v in p.items()}
    sh=tuple((p[11][k]+p[12][k])/2 for k in (0,1)); hip=tuple((p[23][k]+p[24][k])/2 for k in (0,1))
    axis=(hip[0]-sh[0],hip[1]-sh[1]); length=math.hypot(*axis)
    if length < 1: return None,'degenerate_torso_projection'
    cross=lambda v: (v[0]*axis[1]-v[1]*axis[0])/length**2
    width=cross((p[12][0]-p[11][0],p[12][1]-p[11][1]))
    hip_width=cross((p[24][0]-p[23][0],p[24][1]-p[23][1]))
    if abs(width)<.18 or width*hip_width<=0: return None,'side_view_or_left_right_ambiguity'
    arms={str(j):abs(cross((p[j][0]-sh[0],p[j][1]-sh[1]))) for j in (13,14,15,16)}
    legs=[_point(frame,j,g) for j in (25,26,27,28)]
    return {'arms':arms, 'shoulder_ratio':width,'axis_angle':math.atan2(axis[1],axis[0]),
            'legs_observable':all(v is not None for v in legs)},None


def extract_pull_in(pose, trajectory, stages):
    unavailable={'status':'unavailable','frame_id':None,'image_ref':None,'timestamp':None,'playback_timestamp':None,
                 'source':'projected_bilateral_arm_contraction.v1','reason':'compatible_takeoff_landing_candidate_support_required',
                 'quality_flags':[], 'warnings':LIMITATIONS.copy(),'evidence':{},'contact_evidence_status':'uncertain'}
    start,end=stages['takeoff'],stages['landing']
    points=trajectory['points']; by_key={p['frame_id']:p for p in points}
    first,last=by_key.get(start.get('frame_id')),by_key.get(end.get('frame_id'))
    if (start['status']!='candidate' or end['status']!='candidate' or not first or not last
            or first['segment_id']!=last['segment_id'] or first['pose_index']>=last['pose_index']):
        return unavailable
    support=[p for p in points if first['pose_index']<=p['pose_index']<=last['pose_index']]
    candidates=[]; window=[]; rejects=[]
    for point in support:
        signal,reason=_signals(pose['frames'][point['pose_index']])
        if reason:
            window=[]; rejects.append({'frame_id':point['frame_id'],'reason':reason}); continue
        if window:
            base=window[0][1]
            angle=abs(math.atan2(math.sin(signal['axis_angle']-base['axis_angle']),math.cos(signal['axis_angle']-base['axis_angle'])))
            if (angle>math.radians(25) or signal['shoulder_ratio']*base['shoulder_ratio']<=0
                    or abs(signal['shoulder_ratio']/base['shoulder_ratio']-1)>.20):
                window=[]; rejects.append({'frame_id':point['frame_id'],'reason':'viewpoint_or_left_right_change'})
            elif any(signal['arms'][j]>window[-1][1]['arms'][j]+.03 for j in signal['arms']):
                window=[]
        window.append((point,signal))
        if len(window)>=3:
            base=window[0][1]['arms']; current=signal['arms']
            if all(base[j]-current[j]>=.15 and current[j]<=base[j]*.8 for j in base):
                candidates.append((sum(base[j]-current[j] for j in base),list(window)))
    if not candidates:
        unavailable.update(reason='no_sustained_bilateral_projection_contraction',evidence={'rejected_support':rejects})
        return unavailable
    _,window=max(candidates,key=lambda c:c[0])
    point,signal=window[-1]; refs=[dict(p,signals=s) for p,s in window]
    return {**deepcopy(point),'status':'candidate','timestamp':point['analysis_timestamp'],
            'source':'projected_bilateral_arm_contraction.v1','confidence':None,
            'reason':'projected_arm_contraction_candidate_not_confirmed_airborne_or_whole_body',
            'warnings':LIMITATIONS.copy(),'contact_evidence_status':'uncertain',
            'evidence':{'support_frames':refs,'support_interval':{'start':refs[0]['analysis_timestamp'],
                        'end':refs[-1]['analysis_timestamp'],'time_axis':'analysis'},
                        'interval_basis':'takeoff_landing_candidates_not_confirmed_airborne',
                        'signal':'bilateral_elbow_wrist_distance_to_torso_axis_over_torso_length',
                        'body_scope':'arms_only','legs_observable':signal['legs_observable'],
                        'rejected_support':rejects}}
