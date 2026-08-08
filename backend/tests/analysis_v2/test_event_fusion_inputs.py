from __future__ import annotations

from app.analysis_v2.fusion_inputs import (
    build_event_candidate_claims,
    build_event_window_claims,
    canonicalize_single_event_scope,
    derive_event_scopes_from_motion,
    normalize_event_scopes,
    scope_claims_to_events,
    claims_from_payload,
)
from app.analysis_v2.contracts import EvidenceClaim
from app.analysis_v2.path_review import build_path_a_v2_prompt, validate_path_a_prompt


def test_motion_proposals_become_ordered_event_window_claims_without_family_classification() -> None:
    motion = {
        "window_end": 8.0,
        "selected": [
            {"frame_id": "f1", "source_thumb_index": 1, "timestamp": 1.0, "motion_score": 0.9},
            {"frame_id": "f2", "source_thumb_index": 2, "timestamp": 1.2, "motion_score": 0.8},
            {"frame_id": "f3", "source_thumb_index": 20, "timestamp": 4.0, "motion_score": 0.95},
            {"frame_id": "f4", "source_thumb_index": 21, "timestamp": 4.2, "motion_score": 0.85},
        ],
    }
    scopes = derive_event_scopes_from_motion(
        analysis_id="analysis-1",
        source_video_hash="sha256:video",
        motion_scores=motion,
        pipeline_fingerprint="sha256:pipeline",
    )
    assert len(scopes) == 2
    assert scopes[0]["start_pts_sec"] < scopes[1]["start_pts_sec"]
    claims = build_event_window_claims(
        analysis_id="analysis-1",
        scopes=scopes,
        pipeline_fingerprint="sha256:pipeline",
    )
    assert [claim.event_id for claim in claims] == [scope["event_id"] for scope in scopes]
    assert all(claim.claim_type == "event_window" for claim in claims)
    assert all(claim.value["proposal_status"] == "pending_confirmation" for claim in claims)
    assert all(claim.status == "uncertain" for claim in claims)
    candidates = build_event_candidate_claims(
        analysis_id="analysis-1",
        scopes=scopes,
        pipeline_fingerprint="sha256:pipeline",
    )
    assert [claim.event_id for claim in candidates] == [scope["event_id"] for scope in scopes]
    assert all(claim.claim_type == "action_candidate" and claim.status == "uncertain" for claim in candidates)


def test_persisted_proposal_envelope_takes_precedence_over_motion_fallback() -> None:
    motion = {
        "event_proposals": {"proposals": [{
            "event_id": "persisted-event", "start_pts": 0.2, "end_pts": 0.9,
            "status": "confirmed_window", "observability": "observable",
        }]},
        "selected": [
            {"frame_id": "f1", "source_thumb_index": 1, "timestamp": 4.0, "motion_score": 0.9},
            {"frame_id": "f2", "source_thumb_index": 2, "timestamp": 4.2, "motion_score": 0.8},
        ],
        "window_end": 8.0,
    }
    scopes = derive_event_scopes_from_motion(
        analysis_id="analysis-1", source_video_hash="sha256:v", motion_scores=motion, pipeline_fingerprint="sha256:p"
    )
    assert [item["event_id"] for item in scopes] == ["persisted-event"]


def test_malformed_event_proposals_are_ignored_and_duplicate_ids_deduped() -> None:
    scopes = normalize_event_scopes(
        {
            "proposals": [
                {"event_id": "e2", "start_pts": 2, "end_pts": 3, "observability": "observable"},
                {"event_id": "e1", "start_pts": 0, "end_pts": 1, "observability": "observable"},
                {"event_id": "e1", "start_pts": 0, "end_pts": 1, "observability": "observable"},
                {"event_id": "bad", "start_pts": "not-a-number", "end_pts": 1},
                {"event_id": "zero", "start_pts": 2, "end_pts": 2, "observability": "observable"},
            ]
        },
        analysis_id="analysis-1",
    )
    assert [item["event_id"] for item in scopes] == ["e1", "e2"]


def test_generated_path_a_v2_prompt_passes_leakage_boundary() -> None:
    system, user = build_path_a_v2_prompt(
        action_family="jump",
        target_policy={
            "identity_state": "confirmed",
            "crop_bbox": (0.1, 0.1, 0.5, 0.9),
            "context_before_sec": 0.5,
            "context_after_sec": 0.5,
            "includes_travel_context": True,
            "includes_ice_contact_context": True,
            "target_marking": "tracked_bbox_overlay",
        },
    )
    assert validate_path_a_prompt(system, user) == ()
    assert "computed values" in user
    assert "exact time markers" in user


def test_pending_window_never_becomes_confirmed_from_observability_alone() -> None:
    scope = {
        "event_id": "evt-derived",
        "start_pts": 1.0,
        "end_pts": 2.0,
        "status": "pending_confirmation",
        "observability": "observable",
        "candidate_profile_scores": {"jump": .8, "spin": .1, "step": .1, "spiral": 0},
    }
    claim = build_event_window_claims(
        analysis_id="analysis-1",
        scopes=(scope,),
        pipeline_fingerprint="sha256:pipeline",
    )[0]
    assert claim.status == "uncertain"
    assert claim.refusal_reason == "event_window_pending_confirmation"
    assert claim.review_task == "evt-derived:review_event_window"


def test_single_proposal_maps_to_canonical_event_without_losing_lineage() -> None:
    scopes = canonicalize_single_event_scope(
        ({
            "event_id": "evt-derived",
            "start_pts": 1.0,
            "end_pts": 2.0,
            "status": "pending_confirmation",
            "observability": "partially_observable",
        },),
        analysis_id="analysis-1",
        canonical_event_id="analysis-1:event:0",
    )
    assert len(scopes) == 1
    assert scopes[0]["event_id"] == "analysis-1:event:0"
    assert scopes[0]["proposal_event_id"] == "evt-derived"
    claim = build_event_window_claims(
        analysis_id="analysis-1",
        scopes=scopes,
        pipeline_fingerprint="sha256:pipeline",
    )[0]
    assert claim.event_id == "analysis-1:event:0"
    assert claim.source_references == ("event_proposal:evt-derived",)


def test_only_exact_source_pts_claims_are_event_scoped() -> None:
    scopes = (
        {"event_id": "e1", "start_pts": 0.0, "end_pts": 1.0, "observability": "observable"},
        {"event_id": "e2", "start_pts": 2.0, "end_pts": 3.0, "observability": "observable"},
    )
    claims = (
        EvidenceClaim(
            analysis_id="analysis-1", claim_type="key_moment", value={"pts_sec": .5},
            sources=("key_moment",), source_references=("bio_data.key_frames:T",),
            source_fingerprints={"key_moment": "fp"}, confidence=.8,
            observability="observed", status="confirmed",
        ),
        EvidenceClaim(
            analysis_id="analysis-1", claim_type="visible_observation", value="target enters",
            sources=("path_a",), source_fingerprints={"path_a": "fp"}, confidence=.8,
            observability="observed", status="confirmed",
        ),
        EvidenceClaim(
            analysis_id="analysis-1", claim_type="visible_observation", value={"pts_sec": .5, "text": "target"},
            sources=("path_a",), source_fingerprints={"path_a": "fp"}, confidence=.8,
            observability="observed", status="confirmed",
        ),
        EvidenceClaim(
            analysis_id="analysis-1", claim_type="key_moment", value={"pts_sec": 1.5},
            sources=("key_moment",), source_fingerprints={"key_moment": "fp"}, confidence=.8,
            observability="observed", status="confirmed",
        ),
    )
    scoped = scope_claims_to_events(claims, scopes=scopes, analysis_id="analysis-1")
    assert scoped[0].event_id == "e1"
    assert scoped[1].event_id is None
    assert scoped[2].event_id is None
    assert scoped[3].event_id is None


def test_multi_event_provider_event_id_is_ignored_until_deterministic_scoping() -> None:
    claims = claims_from_payload(
        {
            "evidence_claims": [{
                "event_id": "provider-invented",
                "claim_type": "visible_observation",
                "value": "target visible",
                "confidence": .7,
                "observability": "observed",
                "status": "confirmed",
            }]
        },
        analysis_id="analysis-multi",
        source="path_a",
        whole_analysis=True,
    )
    assert len(claims) == 1
    assert claims[0].event_id is None


def test_path_b_provider_cannot_self_attest_deterministic_measurement_source() -> None:
    untrusted = claims_from_payload(
        {"evidence_claims": [{
            "claim_type": "knee_angle",
            "value": 42,
            "sources": ["path_b", "deterministic_measurement"],
            "provenance": ["measured"],
            "confidence": .8,
            "observability": "observed",
            "status": "confirmed",
        }]},
        analysis_id="analysis-1",
        source="path_b",
    )
    assert untrusted[0].sources == ("path_b",)

    trusted = claims_from_payload(
        {"evidence_claims_origin": "structured_measurement_adapter.v1", "evidence_claims": [{
            "claim_type": "knee_angle",
            "value": 42,
            "sources": ["path_b", "deterministic_measurement"],
            "provenance": ["measured"],
            "confidence": .8,
            "observability": "observed",
            "status": "confirmed",
        }]},
        analysis_id="analysis-1",
        source="path_b",
    )
    assert trusted[0].sources == ("path_b", "deterministic_measurement")
