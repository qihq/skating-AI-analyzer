"""Raw-only, offline limb consistency checks before any smoothing.

This is an ambiguity gate, not an anatomical ground-truth estimator. A bilateral
assignment hypothesis may reject an isolated label bounce; it never relabels
points. A non-assignment spike additionally needs local bone-length distortion.
All distances use the existing normalized canvas metric, ratios are unitless.
"""
from __future__ import annotations

import math
import statistics
from typing import Any, Callable

VERSION = "limb-consistency.v1"
# Frozen dimensionless oracles; independent of person, pixel size or cadence.
ASSIGNMENT_COST_RATIO = .35
PREDICTION_DISAGREEMENT_RATIO = .25
MIN_BONE_RESIDUAL = .5
BONE_LENGTH_RATIO = 1.8
PAIRS = ((11,12),(13,14),(15,16),(23,24),(25,26),(27,28),(29,30),(31,32))
EDGES = ((11,13),(13,15),(12,14),(14,16),(11,23),(12,24),
         (23,25),(24,26),(25,27),(26,28),(27,29),(28,30),(27,31),(28,32))
LIMB_IDS = frozenset(k for pair in PAIRS for k in pair)


def distance(a, b): return math.hypot(a[0]-b[0], a[1]-b[1])
def xy(p): return (float(p['x']), float(p['y']))


def assess_limb_consistency(frames: list[dict[str, Any]], segments: list[int | None],
                            native: Callable[[dict[str, Any]], bool]) -> dict[tuple[int,int], dict[str, Any]]:
    """Use four *raw* same-person anchors; never use smoothed/corrected output."""
    points = [{p['id']:p for p in f.get('keypoints',[]) if isinstance(p.get('id'),int)} for f in frames]
    result = {}
    predictions = {}
    for i, current in enumerate(points):
        support = [i-2,i-1,i+1,i+2]
        time_ok = (segments[i] is not None and all(0<=j<len(frames) and segments[j]==segments[i] for j in support))
        for k,p in current.items():
            if k not in LIMB_IDS: continue
            q = {'version':VERSION, 'status':'insufficient_context', 'reason':'four_native_same_segment_anchors_required',
                 'raw_point_id':k, 'coordinate_action':'retain_raw', 'support_frame_indices':[]}
            result[i,k] = q
            if not time_ok or not native(p) or not all(k in points[j] and native(points[j][k]) for j in support):
                continue
            ts = [frames[j]['temporal']['analysis_timestamp'] for j in support]
            t = frames[i]['temporal']['analysis_timestamp']
            def predict(a,b,ta,tb):
                return tuple(a[d]+(b[d]-a[d])*(t-ta)/(tb-ta) for d in (0,1))
            forward = predict(xy(points[i-2][k]),xy(points[i-1][k]),ts[0],ts[1])
            backward = predict(xy(points[i+1][k]),xy(points[i+2][k]),ts[2],ts[3])
            expected = tuple((a+b)/2 for a,b in zip(forward,backward))
            error, disagreement = distance(xy(p),expected),distance(forward,backward)
            # Adjacent bone evidence must itself have native raw endpoints.
            lengths = []
            distortion = 1.
            for a,b in EDGES:
                if k not in (a,b): continue
                other = b if k==a else a
                if other not in current or not native(current[other]): continue
                anchors = [distance(xy(points[j][k]),xy(points[j][other])) for j in support
                           if other in points[j] and native(points[j][other])]
                if len(anchors)!=4: continue
                length = statistics.median(anchors)
                if length<=1e-8: continue
                lengths.append(length)
                now = distance(xy(p),xy(current[other]))
                distortion = max(distortion,now/length,length/max(now,1e-8))
            scale = max(lengths,default=0.)
            q.update(status='no_anomaly_detected',reason='raw_temporal_and_available_geometry_checked',
                     support_frame_indices=support, residual=error, prediction_disagreement=disagreement,
                     local_bone_scale=scale, max_bone_length_ratio=distortion)
            predictions[i,k] = expected
            # Require raw return on both sides AND geometry, not speed alone.
            if (scale>0 and error>MIN_BONE_RESIDUAL*scale and
                    disagreement<PREDICTION_DISAGREEMENT_RATIO*error and distortion>BONE_LENGTH_RATIO):
                q.update(status='uncertain',reason='isolated_raw_spike_with_bone_geometry_change')
        for left,right in PAIRS:
            if (i,left) not in predictions or (i,right) not in predictions: continue
            a,b=xy(current[left]),xy(current[right])
            ea,eb=predictions[i,left],predictions[i,right]
            qa,qb=result[i,left],result[i,right]
            own=distance(a,ea)+distance(b,eb)
            swapped=distance(a,eb)+distance(b,ea)
            separation=statistics.median(distance(xy(points[j][left]),xy(points[j][right])) for j in support)
            # Each adjacent raw frame independently prefers the alternate
            # assignment. This tolerates noisy raw velocities without relaxing
            # the cost-ratio threshold or consulting any processed output.
            side_ratios = []
            for j in (i-1,i+1):
                aj,bj=xy(points[j][left]),xy(points[j][right])
                direct=distance(a,aj)+distance(b,bj)
                alternate=distance(a,bj)+distance(b,aj)
                side_ratios.append(alternate/direct if direct>1e-8 else 1.)
            if (separation>1e-8 and own>0 and swapped<ASSIGNMENT_COST_RATIO*own and
                    all(r<ASSIGNMENT_COST_RATIO for r in side_ratios) and
                    all(q['residual']>.5*separation for q in (qa,qb))):
                for q in (qa,qb):
                    q.update(status='uncertain',reason='isolated_bilateral_assignment_ambiguity',
                             assignment_cost_ratio=swapped/own, adjacent_raw_cost_ratios=side_ratios,
                             bilateral_separation=separation)
        # A coincident knee pair during a distal ambiguity is not rescued by
        # swapping ankles. Quarantine only knees with independent raw deviation.
        distal = any(result.get((i,k),{}).get('status')=='uncertain' for k in range(27,33))
        if distal and all((i,k) in predictions for k in (25,26)):
            separation=statistics.median(distance(xy(points[j][25]),xy(points[j][26])) for j in support)
            if separation>1e-8 and distance(xy(current[25]),xy(current[26]))<.5*separation:
                for k in (25,26):
                    q=result[i,k]
                    if q['local_bone_scale']>0 and q['residual']>.25*q['local_bone_scale']:
                        q.update(status='uncertain',reason='knee_collapse_with_distal_assignment_ambiguity')
        # Heel/toe contact belongs to the same foot chain as its ankle. Raw
        # foot coordinates stay visible, but cannot independently validate an
        # ambiguous ankle assignment at this frame.
        for ankle,foot_ids in ((27,(29,31)),(28,(30,32))):
            if result.get((i,ankle),{}).get('status') != 'uncertain': continue
            for k in foot_ids:
                q=result.get((i,k))
                if q is not None and native(current[k]):
                    q.update(status='uncertain', reason='foot_contact_dependency_on_uncertain_ankle',
                             dependency_point_id=ankle, dependency_reason=result[i,ankle]['reason'])
    return result
