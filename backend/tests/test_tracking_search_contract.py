"""Pre-confirmation search boundaries; synthetic JPEGs and detector receipts only."""
import copy
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from app.services import continuous_tracking as ct
from app.services.person_tracker import PersonBBoxTracker
from app.services.pose import _tracker_bbox_is_reliable
from test_tracking_clock_contract import offline, run_prepare
from test_tracking_segment_contract import save


def search_case(tmp_path, monkeypatch, *, total=14, missing=(), ambiguous=(),
                spatial=(), alternating=False, unknown=None, gap=None, loss=None):
    pool=tmp_path/'pool'; pool.mkdir()
    pose=tmp_path/'pose'; pose.mkdir()
    rows=[]; detections={}
    for i in range(total):
        local=i if i<6 else i-6
        x=100+local*2 if i<6 else 340+local*2
        image=np.zeros((240,640,3),np.uint8); image[:8,:8]=i*8
        colors=((0,0,230),(0,210,0))
        if i in spatial or (alternating and i>=6 and i%2): colors=colors[::-1]
        boxes=[]
        for xx in ([x,480] if i in ambiguous else [x]):
            image[50:105,xx:xx+80]=colors[0]
            image[105:190,xx:xx+80]=colors[1]
            boxes.append((float(xx),50.,float(xx+80),190.,.95))
        if i in missing: boxes.append((550.,30.,620.,150.,.8))
        if i==loss: boxes=[]
        p=pool/f'observation_{i:04d}.jpg'; assert cv2.imwrite(str(p),image)
        t=(i*.1 if i<6 else 1.4+(i-6)*.1)+(1. if gap is not None and i>=gap else 0.)
        pts=round((7.+t)*600)
        rows.append(dict(index=i,file=p.name,sha256=ct.file_sha256(p),source_pts=pts,
            source_time_base='1/600',source_pts_time=pts/600.,timestamp=t))
        detections[i]=boxes
    manifest=dict(version=1,source_origin_sec=7.,period_sec=.1,window_start=0.,
        window_end=rows[-1]['timestamp']+.1,coverage_end=rows[-1]['timestamp'],
        canvas=dict(width=640,height=240),pose_bindings=[],observations=rows)
    frames,motion=run_prepare(tmp_path,monkeypatch,manifest,pool,pose,scale=4.)
    calls=[]
    def detect(self,image,*,conf_threshold=.4):
        assert conf_threshold==.4
        i=round(float(image[:8,:8].mean())/8); calls.append(i)
        if i==unknown: raise RuntimeError('synthetic unknown detector failure')
        if i in missing:
            assert self._independent_identity_signature(image,detections[i][-1][:4]) is None
        return copy.deepcopy(detections[i])
    monkeypatch.setattr(PersonBBoxTracker,'_detect',detect)
    lock=dict(selected_bbox=dict(x=100/640,y=50/240,width=80/640,height=140/240),
        manual_override=False,preview_frame_index=0)
    return pool,frames,motion,lock,calls


def execute(case):
    pool,frames,motion,lock,calls=case
    boxes,ds,summary=ct.track_bound_pose_frames(frames,lock,motion['continuous_tracking'],pool)
    assert len(calls)==len(set(calls)), calls
    assert all(_tracker_bbox_is_reliable(d) for d in ds[:6])
    return boxes,ds,summary['segment_identities'],calls


@pytest.mark.parametrize('prior_support',[0,1,2])
def test_missing_signature_resets_every_pending_state(tmp_path,monkeypatch,prior_support):
    missing=6+prior_support; anchor=missing+3
    _,ds,policies,calls=execute(search_case(tmp_path,monkeypatch,missing=[missing]))
    p=policies[0]
    assert p['anchor']['observation_index']==anchor
    assert [s['observation_index'] for s in p['support']]==list(range(missing+1,anchor+1))
    assert p['reason']=='identity_confirmed' and p['search_outcome']=='confirmed'
    first_fresh=next(a for a in p['attempts'] if a['observation_index']==missing+1)
    assert first_fresh['support_spatial'] is None
    rejected=next(a for a in p['attempts'] if a['observation_index']==missing)
    assert rejected['reason']=='identity_ambiguous_evidence_missing'
    assert rejected['outcome']=='local_rejection'
    assert all(not _tracker_bbox_is_reliable(d) for d in ds[6:anchor])
    assert all(_tracker_bbox_is_reliable(d) for d in ds[anchor:])
    save('search-reset-'+str(prior_support),dict(diagnostics=ds,policy=p,calls=calls))


def test_fixed_twelve_observation_window_never_slides(tmp_path,monkeypatch):
    _,ds,policies,calls=execute(search_case(tmp_path,monkeypatch,total=21,missing=range(6,18)))
    p=policies[0]
    assert [a['observation_index'] for a in p['attempts']]==list(range(6,18))
    assert p['search_limit']==12 and max(calls)==17 and 18 not in calls
    assert p['search_outcome']=='window_exhausted'
    assert p['reason']=='identity_support_insufficient' and p['anchor'] is None and p['support']==[]
    assert all(not _tracker_bbox_is_reliable(d) for d in ds[6:])


@pytest.mark.parametrize('decoy',[False,True])
def test_informative_ambiguity_stops_even_with_missing_decoy(tmp_path,monkeypatch,decoy):
    _,ds,policies,calls=execute(search_case(tmp_path,monkeypatch,ambiguous=[7],missing=[7] if decoy else []))
    p=policies[0]
    assert p['reason']=='identity_ambiguous' and p['search_outcome']=='hard_stop'
    assert p['attempts'][-1]['outcome']=='hard_stop' and max(calls)==7
    assert p['support']==[] and p['anchor'] is None
    assert all(not _tracker_bbox_is_reliable(d) for d in ds[6:])


@pytest.mark.parametrize('kind',['spatial','alternating','binding','gap','unknown'])
def test_invalid_evidence_cannot_form_a_fresh_triple(tmp_path,monkeypatch,kind):
    kw=dict(total=10,missing=[6])
    if kind=='spatial': kw['spatial']=[7,8,9]
    if kind=='alternating': kw['alternating']=True
    if kind=='gap': kw['gap']=8
    if kind=='unknown': kw['unknown']=7
    case=search_case(tmp_path,monkeypatch,**kw)
    if kind=='binding':case[2]['continuous_tracking']['pose_bindings'][8]['sha256']='0'*64
    _,ds,policies,calls=execute(case)
    assert all(p['anchor'] is None for p in policies)
    assert all(not _tracker_bbox_is_reliable(d) for d in ds[6:])
    if kind=='unknown':
        assert max(calls)==7 and policies[0]['search_outcome']=='hard_stop'
        assert policies[0]['reason'].startswith('identity_search_aborted:')
    if kind=='spatial':
        assert all(a['reason']=='identity_spatial_conflict' for a in policies[0]['attempts'][1:])


@pytest.mark.parametrize('loss_kind',['absent','replacement','missing_signature'])
def test_confirmed_loss_never_recovers_the_trusted_suffix(tmp_path,monkeypatch,loss_kind):
    kw=dict(missing=[6])
    if loss_kind=='absent':kw['loss']=11
    if loss_kind=='replacement':kw['spatial']=[11]
    if loss_kind=='missing_signature':kw['missing']=[6,11]
    _,ds,policies,calls=execute(search_case(tmp_path,monkeypatch,**kw))
    assert policies[0]['anchor']['observation_index']==9
    assert all(_tracker_bbox_is_reliable(d) for d in ds[9:11])
    assert all(not _tracker_bbox_is_reliable(d) for d in ds[11:])
    assert all(d.get('identity_rejected_reason')=='independent_identity_lost' for d in ds[11:])
