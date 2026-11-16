"""Supervisor's proposed pre-confirmation missing-evidence recovery contract.
Synthetic JPEGs/detections only. This adds a requirement; no production patch here.
"""
import pytest
from app.services import continuous_tracking as ct
from app.services.person_tracker import PersonBBoxTracker
from app.services.pose import _tracker_bbox_is_reliable
from test_tracking_segment_contract import segment_case
from test_tracking_clock_contract import offline


def run_case(tmp_path,monkeypatch,kind):
    pool,frames,motion,lock,calls=segment_case(tmp_path,monkeypatch,kind='crossing' if kind=='informative_ambiguity' else 'same')
    original=PersonBBoxTracker._detect
    def detect(self,image,*,conf_threshold=.4):
        rows=original(self,image,conf_threshold=conf_threshold)
        index=round(float(image[:8,:8].mean())/8)
        if (kind=='transient_missing' and index==6) or (kind=='persistent_missing' and index>=6):
            # This second legal detector box covers genuinely uninformative black pixels.
            extra=(500.,50.,580.,190.,.8)
            assert self._independent_identity_signature(image,extra[:4]) is None
            rows=rows+[extra]
        return rows
    monkeypatch.setattr(PersonBBoxTracker,'_detect',detect)
    _,ds,summary=ct.track_bound_pose_frames(frames,lock,motion['continuous_tracking'],pool)
    return ds,summary['segment_identities'][0],calls


def test_transient_missing_evidence_requires_fresh_three_frame_confirmation(tmp_path,monkeypatch):
    ds,policy,calls=run_case(tmp_path,monkeypatch,'transient_missing')
    assert all(_tracker_bbox_is_reliable(d) for d in ds[:6])
    assert all(not _tracker_bbox_is_reliable(d) for d in ds[6:9])
    assert policy['anchor'] is not None, ('single missing signature ended the entire bounded search',policy['reason'],calls)
    assert policy['anchor']['observation_index']==9
    assert [r['observation_index'] for r in policy['support']]==[7,8,9]
    assert all(_tracker_bbox_is_reliable(d) for d in ds[9:])
    assert len(calls)==len(set(calls))


def test_persistent_missing_evidence_never_confirms(tmp_path,monkeypatch):
    ds,policy,calls=run_case(tmp_path,monkeypatch,'persistent_missing')
    assert all(_tracker_bbox_is_reliable(d) for d in ds[:6])
    assert all(not _tracker_bbox_is_reliable(d) for d in ds[6:])
    assert policy['support']==[] and policy['anchor'] is None


def test_two_informative_similar_candidates_keep_terminal_ambiguity(tmp_path,monkeypatch):
    ds,policy,calls=run_case(tmp_path,monkeypatch,'informative_ambiguity')
    assert all(_tracker_bbox_is_reliable(d) for d in ds[:6])
    assert all(not _tracker_bbox_is_reliable(d) for d in ds[6:])
    assert policy['reason']=='identity_ambiguous' and policy['anchor'] is None
    assert max(calls)==7
