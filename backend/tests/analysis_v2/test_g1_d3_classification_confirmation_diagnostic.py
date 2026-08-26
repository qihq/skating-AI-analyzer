from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.analysis_v2.action_classification import ActionClassificationEvidence, classify_action
from app.analysis_v2.event_proposals import ProposalEvidenceSample, generate_event_proposals
from scripts.g1_d3_classification_confirmation_diagnostic import analyze_diagnostic


def _samples(source_offset: int = 0) -> tuple[ProposalEvidenceSample, ...]:
    active = set(range(5, 11)) | set(range(25, 31))
    return tuple(
        ProposalEvidenceSample(
            source_frame_index=source_offset + index,
            pts_sec=index * .1,
            camera_compensated_track_motion=.30 if index in active else .03,
            pose_dynamics=.25 if index in active else .02,
            ice_contact_proxy=.70 if index in active else .05,
            edge_complexity=.10,
            tracking_observable=True,
            pose_observable=index in active,
            provenance=("source_pts", "source_only_adapter"),
        )
        for index in range(40)
    )


def _classification_evidence(source_hash: str, proposal, samples) -> ActionClassificationEvidence:
    local = tuple(item for item in samples if proposal.start_pts <= item.pts_sec <= proposal.end_pts)
    return ActionClassificationEvidence(
        source_video_hash=source_hash,
        event_id=proposal.event_id,
        samples=local,
        temporal_features={
            "airborne_proxy": .70,
            "vertical_excursion": .65,
            "ice_contact_proxy": .70,
            "pose_dynamics": .15,
            "motion": .10,
            "horizontal_motion": .05,
            "periodicity": 0,
            "extension_proxy": 0,
            "step_complexity": .10,
        },
        tracking_coverage=1,
        pose_coverage=1,
        observability="observable",
        identity_confirmed=True,
        evidence_sources=proposal.evidence_sources,
    )


def _source(source_hash: str, source_offset: int = 0) -> dict:
    samples = _samples(source_offset)
    collection = generate_event_proposals(
        source_video_hash=source_hash,
        source_duration_sec=4.0,
        samples=samples,
        pipeline_fingerprint="diagnostic-source-only-evidence.v2",
        source_only_localization_upgrade=False,
    )
    events = []
    for proposal in collection.proposals:
        if "unlocalized_observability_envelope" in proposal.evidence_sources:
            events.append({
                "proposal": proposal.model_dump(mode="json"),
                "classification_evidence": None,
                "classification": {"profile": "unknown", "state": "unknown"},
            })
            continue
        evidence = _classification_evidence(source_hash, proposal, samples)
        events.append({
            "proposal": proposal.model_dump(mode="json"),
            "classification_evidence": evidence.model_dump(mode="json"),
            "classification": classify_action(
                evidence,
                classification_confirmation_upgrade=False,
            ).model_dump(mode="json"),
        })
    return {
        "source_video_hash": source_hash,
        "source_duration_sec": 4.0,
        "proposal_samples": [item.model_dump(mode="json") for item in samples],
        "proposal_collection": collection.model_dump(mode="json"),
        "events": events,
    }


def _diagnostic() -> dict:
    return {
        "videos": [
            {
                "status": "ok",
                "raw_diagnostics": {"source_evidence": _source("sha256:source-a")},
            },
            {
                "status": "ok",
                "raw_diagnostics": {"source_evidence": _source("sha256:source-b", 100)},
            },
        ],
    }


def test_diagnostic_replays_recorded_classifications_and_applies_d3_per_proposal() -> None:
    result = analyze_diagnostic(_diagnostic())

    aggregate = result["aggregate"]
    assert aggregate["recorded_classification_count"] == 4
    assert aggregate["baseline_matches_recorded_classification_count"] == 4
    assert aggregate["recorded_evidence_aligned_proposal_count"] == 4
    assert aggregate["localized_proposal_count_after"] == 4
    assert aggregate["multi_localized_source_count_after"] == 2
    assert aggregate["classification_state_before"] == {"ambiguous": 4}
    assert aggregate["classification_state_after"] == {"confirmed": 4}
    assert aggregate["confirmation_upgrade_count"] == 4
    assert aggregate["unlocalized_refusal_count"] == 2
    assert result["golden_labels_consumed"] is False
    assert result["classification_invoked"] is True
    assert result["moments_invoked"] is False
    assert result["rotation_invoked"] is False
    assert result["formal_pilot_invoked"] is False


def test_diagnostic_is_invariant_to_unread_golden_shaped_fields() -> None:
    baseline = analyze_diagnostic(_diagnostic())
    changed = _diagnostic()
    changed["golden"] = {"profile": "must-not-be-read"}
    changed["videos"][0]["raw_diagnostics"]["golden_labels"] = {
        "events": [{"profile": "spin", "start_pts": 1.0, "end_pts": 2.0}],
        "moments": ["must-not-be-read"],
        "rotation": 9.0,
    }

    assert analyze_diagnostic(changed) == baseline


def test_diagnostic_fingerprint_is_independent_of_source_and_event_order() -> None:
    first = _diagnostic()
    reversed_order = deepcopy(first)
    reversed_order["videos"] = list(reversed(reversed_order["videos"]))
    for video in reversed_order["videos"]:
        source = video["raw_diagnostics"]["source_evidence"]
        source["events"] = list(reversed(source["events"]))
        source["proposal_collection"]["proposals"] = list(reversed(source["proposal_collection"]["proposals"]))

    assert analyze_diagnostic(first) == analyze_diagnostic(reversed_order)


def test_diagnostic_reuses_label_free_evidence_across_a_local_boundary_upgrade() -> None:
    diagnostic = _diagnostic()
    source = diagnostic["videos"][0]["raw_diagnostics"]["source_evidence"]
    row = source["events"][0]
    row["proposal"] = {
        **row["proposal"],
        "anchor_start_frame": row["proposal"]["anchor_start_frame"] + 1,
        "anchor_end_frame": row["proposal"]["anchor_end_frame"] - 1,
        "start_pts": row["proposal"]["start_pts"] + .1,
        "end_pts": row["proposal"]["end_pts"] - .1,
    }

    result = analyze_diagnostic(diagnostic)

    assert result["aggregate"]["baseline_matches_recorded_classification_count"] == 4
    assert result["aggregate"]["recorded_evidence_aligned_proposal_count"] == 4
    assert result["aggregate"]["classification_state_before"] == {"ambiguous": 4}
    assert result["aggregate"]["classification_state_after"] == {"confirmed": 4}
