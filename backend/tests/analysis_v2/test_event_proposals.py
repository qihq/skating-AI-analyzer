from __future__ import annotations

from pathlib import Path

import pytest

from app.analysis_v2.event_proposals import ProposalEvidenceSample, generate_event_proposals, merge_proposals, set_proposal_outcome, split_proposal
from app.analysis_v2.evaluation.pilot12_event_proposals import evaluate_pilot12_event_proposals


def sample(frame: int, pts: float, *, motion: float = 0, pose: float = 0, contact: float = 0, periodicity: float = 0, camera: float = 1, semantic: float = 0) -> ProposalEvidenceSample:
    return ProposalEvidenceSample(source_frame_index=frame, pts_sec=pts, camera_compensated_track_motion=motion, pose_dynamics=pose, ice_contact_proxy=contact, periodicity=periodicity, semantic_hints={"jump": semantic}, camera_reliability=camera, pose_observable=pose > 0, provenance=("fixture",))


def generate(samples: list[ProposalEvidenceSample], duration: float = 8):
    return generate_event_proposals(source_video_hash="sha256:video", source_duration_sec=duration, samples=samples, pipeline_fingerprint="sha256:pipeline")


def test_multiple_jumps_remain_distinct_and_stable() -> None:
    samples = [sample(index, index * .2, motion=.05) for index in range(40)]
    for index in (6, 7, 8, 24, 25, 26):
        samples[index] = sample(index, index * .2, motion=.8, pose=.8, contact=.7)
    first = generate(samples)
    second = generate(samples)
    assert len(first.proposals) == 2
    assert [item.event_id for item in first.proposals] == [item.event_id for item in second.proposals]
    assert first.proposals[0].end_pts < first.proposals[1].start_pts
    assert all(item.proposed_profile == "unknown" for item in first.proposals)


def test_jump_followed_by_spin_is_not_collapsed() -> None:
    samples = [sample(index, index * .1) for index in range(60)]
    for index in range(10, 15): samples[index] = sample(index, index * .1, motion=.8, pose=.8, contact=.8)
    for index in range(23, 31): samples[index] = sample(index, index * .1, motion=.5, pose=.5, periodicity=.9)
    proposals = generate(samples, 6).proposals
    assert len(proposals) == 2
    assert proposals[0].candidate_profile_scores["jump"] > proposals[0].candidate_profile_scores["spin"]
    assert proposals[1].candidate_profile_scores["spin"] > proposals[1].candidate_profile_scores["jump"]


def test_interrupted_action_and_overlapping_evidence_merge_without_hiding_valley() -> None:
    samples = [sample(index, index * .1) for index in range(40)]
    for index in list(range(8, 12)) + list(range(14, 18)): samples[index] = sample(index, index * .1, motion=.7, pose=.6)
    proposals = generate(samples, 4).proposals
    assert len(proposals) == 1
    assert "multi_signal_cluster" in proposals[0].evidence_sources


def test_ordinary_skating_camera_pan_and_weak_semantics_do_not_force_step() -> None:
    pan = [sample(index, index * .2, motion=.8, camera=0.02) for index in range(30)]
    weak = [sample(index, index * .2, semantic=.3) for index in range(30)]
    assert generate(pan, 6).proposals == ()
    assert generate(weak, 6).proposals == ()


def test_merge_split_outcomes_keep_pts_ids_and_revisions() -> None:
    samples = [sample(index, index * .2) for index in range(30)]
    for index in (5, 6, 18, 19): samples[index] = sample(index, index * .2, motion=.9, pose=.7)
    collection = generate(samples, 6)
    original_ids = [item.event_id for item in collection.proposals]
    merged = merge_proposals(collection, original_ids)
    assert merged.proposals[0].event_id == original_ids[0]
    assert merged.proposals[0].start_pts == collection.proposals[0].start_pts
    assert merged.proposals[0].end_pts == collection.proposals[1].end_pts
    split = split_proposal(merged, original_ids[0], 3.0)
    assert len(split.proposals) == 2
    assert split.proposals[0].event_id == original_ids[0]
    assert split.proposals[0].end_pts == split.proposals[1].start_pts == 3.0
    reviewed = set_proposal_outcome(split, original_ids[0], "ordinary_skating")
    assert reviewed.proposals[0].status == "ordinary_skating"
    assert reviewed.revision == split.revision + 1


def test_pilot12_reports_recall_ci_strata_and_no_label_leakage() -> None:
    root = Path(r"C:\Users\qihq\Documents\skating-analyzer-v2-runtime\test-data\pilot-12-run-20260801")
    if not root.exists():
        pytest.skip("private pilot runtime is unavailable")
    result = evaluate_pilot12_event_proposals(root / "api-analysis-index-live.json", root / "snapshot-manifest.json")
    assert result["diagnostic_only"] is True
    assert result["release_claim"] is False
    assert result["classifier_labels_consumed"] is False
    assert result["raw_n"] == 8
    assert result["proposal_recall"]["rate"] >= .98
    assert result["proposal_recall"]["wilson_95_ci"]
    assert result["strata"]
    assert result["false_proposals_per_minute_upper_bound"] is not None


def test_g6_pilot_payload_is_policy_scoped(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot.json"
    labels = tmp_path / "labels.json"
    snapshot.write_text("{}", encoding="utf-8")
    labels.write_text('{"events": []}', encoding="utf-8")
    result = evaluate_pilot12_event_proposals(snapshot, labels)
    assert result["gate"] == "G6"
    assert result["gate_policy_version"] == "golden-gate-policy.v2"
    assert result["evidence_scope"] == "limited_sample"
    assert result["release_claim"] is False
