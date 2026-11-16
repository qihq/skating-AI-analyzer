"""Bounded candidate qualification; synthetic JPEGs/receipts, real identity features.
Fault injection only tests unavailable/invalid evidence, never grants identity.
"""
import copy
import cv2
import numpy as np
import pytest
from app.services import continuous_tracking as ct
from app.services.person_tracker import PersonBBoxTracker
from app.services.pose import _tracker_bbox_is_reliable
from test_tracking_clock_contract import offline, run_prepare

def prepare_qualification_case(tmp_path,monkeypatch,styles_by_index,*,total=12,reverse=False):
 pool=tmp_path/'pool';pool.mkdir();selected=tmp_path/'selected';selected.mkdir()
 rows=[];detections={};calls=[]
 for i in range(total):
  image=np.zeros((240,640,3),np.uint8);image[:8,:8]=i*8
  styles=list(styles_by_index.get(i,['reference']))
  if reverse: styles.reverse()
  boxes=[]
  for j,style in enumerate(styles):
   x,y,w,h=96+160*j,48,80,144
   if style=='missing':
    boxes.append((float(x),float(y),float(x+w),float(y+h),.95));continue
   image[y:y+h,x:x+w]=40
   l,r=round(x+w*.18),round(x+w*.82);t,b=round(y+h*.18),round(y+h*.62)
   yy,xx=np.mgrid[0:b-t,0:r-l];u=(xx+.5)/(r-l);v=(yy+.5)/(b-t)
   red=v<.5 if style=='reference' else u<.5
   image[t:b,l:r]=np.where(red[:,:,None],np.array([0,0,230]),np.array([0,210,0])).astype(np.uint8)
   boxes.append((float(x),float(y),float(x+w),float(y+h),.95))
  f=pool/f'observation_{i:04d}.jpg';assert cv2.imwrite(str(f),image,[cv2.IMWRITE_JPEG_QUALITY,100])
  time=i*.1 if i<6 else 1.4+(i-6)*.1;pts=round((7+time)*600)
  rows.append(dict(index=i,file=f.name,sha256=ct.file_sha256(f),source_pts=pts,source_time_base='1/600',source_pts_time=pts/600.,timestamp=time));detections[i]=boxes
 manifest=dict(version=1,source_origin_sec=7.,period_sec=.1,window_start=0.,window_end=rows[-1]['timestamp']+.1,coverage_end=rows[-1]['timestamp'],canvas=dict(width=640,height=240),pose_bindings=[],observations=rows)
 frames,motion=run_prepare(tmp_path,monkeypatch,manifest,pool,selected,scale=4.)
 def detect(self,image,*,conf_threshold=.4):
  assert conf_threshold==.4;i=round(float(image[:8,:8].mean())/8);calls.append(i);return detections[i]
 monkeypatch.setattr(PersonBBoxTracker,'_detect',detect)
 lock=dict(selected_bbox=dict(x=96/640,y=48/240,width=80/640,height=144/240),manual_override=False,preview_frame_index=0)
 return pool,frames,motion,lock,calls


def execute(case):
 pool,frames,motion,lock,calls=case
 boxes,diagnostics,summary=ct.track_bound_pose_frames(frames,lock,motion['continuous_tracking'],pool)
 return diagnostics,summary['segment_identities'][0],calls

@pytest.mark.parametrize('prior',[1,2])
@pytest.mark.parametrize('reverse',[False,True])
def test_zero_full_matches_reset_support_and_require_fresh_triple(tmp_path,monkeypatch,prior,reverse):
 reject=6+prior
 ds,p,calls=execute(prepare_qualification_case(tmp_path,monkeypatch,{reject:['swapped','swapped']},reverse=reverse))
 attempt=next(a for a in p['attempts'] if a['observation_index']==reject)
 assert attempt['outcome']=='local_rejection' and attempt['reason']=='identity_all_candidates_rejected'
 assert attempt['fully_evaluated_candidate_count']==2 and attempt['full_match_count']==0
 assert p['anchor']['observation_index']==reject+3
 assert [r['observation_index'] for r in p['support']]==list(range(reject+1,reject+4))
 assert next(a for a in p['attempts'] if a['observation_index']==reject+1)['support_spatial'] is None
 assert all(_tracker_bbox_is_reliable(d) for d in ds[:6]+ds[reject+3:])
 assert all(not _tracker_bbox_is_reliable(d) for d in ds[6:reject+3])
 assert len(calls)==len(set(calls))

@pytest.mark.parametrize('styles',[['reference','swapped'],['reference','reference']])
@pytest.mark.parametrize('reverse',[False,True])
def test_matches_with_competitors_remain_terminal_in_either_order(tmp_path,monkeypatch,styles,reverse):
 ds,p,calls=execute(prepare_qualification_case(tmp_path,monkeypatch,{6:styles},reverse=reverse))
 assert p['reason']=='identity_ambiguous' and p['search_outcome']=='hard_stop'
 assert p['attempts'][0]['full_match_count']==styles.count('reference')
 assert p['support']==[] and p['anchor'] is None and max(calls)==6
 assert all(not _tracker_bbox_is_reliable(d) for d in ds[6:])

@pytest.mark.parametrize('fault',['missing','signature_nan','signature_inf','comparison_nan','comparison_inf','comparison_missing','comparison_exception'])
def test_unavailable_nonfinite_or_exception_is_never_zero_full_matches(tmp_path,monkeypatch,fault):
 styles=['swapped','swapped','missing'] if fault=='missing' else ['swapped','swapped']
 case=prepare_qualification_case(tmp_path,monkeypatch,{6:styles})
 signature=PersonBBoxTracker._independent_identity_signature
 compare=PersonBBoxTracker._independent_identity_scores
 def damaged_signature(self,image,box,**kw):
  sig=signature(self,image,box,**kw)
  if sig is not None and round(float(image[:8,:8].mean())/8)==6 and box[0]>200:
   sig['_injected_invalid_evidence']=True
   if fault.startswith('signature_'):
    sig['structure']=sig['structure'].copy();sig['structure'][0]=float(fault.split('_')[1])
  return sig
 def damaged_comparison(a,b):
  result=copy.deepcopy(compare(a,b))
  if a.get('_injected_invalid_evidence') or b.get('_injected_invalid_evidence'):
   if fault in ('comparison_nan','comparison_inf'):result['layout_lower_quartile']=float(fault.split('_')[1])
   if fault=='comparison_missing':result.pop('pooled_cosine')
   if fault=='comparison_exception':raise RuntimeError('synthetic identity comparison fault')
  return result
 monkeypatch.setattr(PersonBBoxTracker,'_independent_identity_signature',damaged_signature)
 monkeypatch.setattr(PersonBBoxTracker,'_independent_identity_scores',staticmethod(damaged_comparison))
 ds,p,calls=execute(case)
 assert p['search_outcome']=='hard_stop' and p['support']==[] and p['anchor'] is None
 assert max(calls)==6 and 'identity_all_candidates_rejected' not in [a['reason'] for a in p['attempts']]
 assert all(not _tracker_bbox_is_reliable(d) for d in ds[6:])


def test_zero_matches_do_not_slide_the_twelve_observation_window(tmp_path,monkeypatch):
 ds,p,calls=execute(prepare_qualification_case(tmp_path,monkeypatch,{i:['swapped','swapped'] for i in range(6,18)},total=21))
 assert [a['observation_index'] for a in p['attempts']]==list(range(6,18))
 assert all(a['reason']=='identity_all_candidates_rejected' for a in p['attempts'])
 assert p['search_outcome']=='window_exhausted' and max(calls)==17 and 18 not in calls
 assert p['support']==[] and p['anchor'] is None
 assert all(not _tracker_bbox_is_reliable(d) for d in ds[6:])

@pytest.mark.parametrize('fault',['competitor','identity_loss','exception'])
def test_post_confirmation_loss_never_recovers_the_suffix(tmp_path,monkeypatch,fault):
 case=prepare_qualification_case(tmp_path,monkeypatch,{6:['swapped','swapped'],10:['swapped','swapped'] if fault=='identity_loss' else ['reference','swapped']})
 if fault=='exception':
  detect=PersonBBoxTracker._detect
  def broken(self,image,**kw):
   if round(float(image[:8,:8].mean())/8)==10:raise RuntimeError('synthetic post-confirmation detector fault')
   return detect(self,image,**kw)
  monkeypatch.setattr(PersonBBoxTracker,'_detect',broken)
 ds,p,calls=execute(case)
 assert p['anchor']['observation_index']==9
 assert _tracker_bbox_is_reliable(ds[9]) and all(not _tracker_bbox_is_reliable(d) for d in ds[10:])
 assert all(_tracker_bbox_is_reliable(d) for d in ds[:6])


def test_invalid_original_box_cannot_be_filtered_into_zero_matches(tmp_path,monkeypatch):
 case=prepare_qualification_case(tmp_path,monkeypatch,{6:['swapped','swapped']})
 detect=PersonBBoxTracker._detect
 def with_invalid_box(self,image,**kw):
  rows=detect(self,image,**kw)
  if round(float(image[:8,:8].mean())/8)==6:rows=rows+[(-1.,48.,80.,192.,.95)]
  return rows
 monkeypatch.setattr(PersonBBoxTracker,'_detect',with_invalid_box)
 ds,p,calls=execute(case)
 assert p['reason']=='identity_ambiguous' and p['search_outcome']=='hard_stop'
 assert p['anchor'] is None and p['support']==[] and max(calls)==6
 assert 'full_match_count' not in p['attempts'][0]
