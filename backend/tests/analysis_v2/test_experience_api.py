from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.routers import analysis_v2


def _analysis() -> SimpleNamespace:
    return SimpleNamespace(id="a1", status="completed")


def test_experience_endpoint_adapts_historical_legacy_record_without_shadow() -> None:
    session = AsyncMock()
    session.add = lambda *_args, **_kwargs: None
    session.get = AsyncMock(return_value=_analysis())
    payload = {
        "schema_version": "analysis-experience.v2",
        "analysis_id": "a1",
        "authority": "legacy",
        "pipeline_mode": "shadow",
        "source_pipeline_fingerprint": "legacy:a1",
        "diagnostic_only": True,
        "family_usable": False,
        "review_tasks": [],
        "events": [],
        "claims": [],
    }
    with patch.object(analysis_v2, "present_analysis_experience", return_value=payload):
        result = asyncio.run(analysis_v2.get_analysis_experience_v2("a1", session))
    assert result.authority == "legacy"
    assert result.pipeline_mode == "shadow"
    assert result.diagnostic_only is True
    assert result.family_usable is False


def test_experience_endpoint_uses_whole_record_presenter_without_keyword_mismatch() -> None:
    session = AsyncMock()
    session.get = AsyncMock(return_value=SimpleNamespace(
        id="a1",
        status="completed",
        action_type="jump",
        pipeline_version="legacy-2026",
        report={"summary": "Good landing"},
    ))

    result = asyncio.run(analysis_v2.get_analysis_experience_v2("a1", session))

    assert result.authority == "legacy"
    assert result.pipeline_mode == "legacy"
    assert {claim.claim_type for claim in result.claims} >= {"action_profile", "report_summary"}


def test_diagnostic_endpoint_requires_parent_and_keeps_authority_consistent() -> None:
    session = AsyncMock()
    session.get = AsyncMock(return_value=_analysis())

    async def reject(*_args: object, **_kwargs: object) -> None:
        raise HTTPException(status_code=403, detail="parent required")

    with patch.object(analysis_v2, "require_parent_pin", new=reject):
        with pytest.raises(HTTPException) as error:
            asyncio.run(analysis_v2.get_analysis_experience_v2_diagnostic("a1", None, session))
    assert error.value.status_code == 403

    with patch.object(analysis_v2, "require_parent_pin", new=AsyncMock(return_value=None)), patch.object(
        analysis_v2,
        "present_analysis_experience",
        return_value={"schema_version": "analysis-experience.v2", "analysis_id": "a1", "authority": "legacy", "pipeline_mode": "shadow", "source_pipeline_fingerprint": "legacy:a1", "diagnostic_only": True, "family_usable": False, "events": [], "claims": [], "review_tasks": []},
    ):
        result = asyncio.run(analysis_v2.get_analysis_experience_v2_diagnostic("a1", "1234", session))
    assert result.authority == "legacy"
    assert result.diagnostic_only is True


def test_identity_revision_preview_requires_parent_and_preserves_causal_scope() -> None:
    session = AsyncMock()
    session.get = AsyncMock(return_value=_analysis())
    with patch.object(analysis_v2, "require_parent_pin", new=AsyncMock(return_value=None)):
        result = asyncio.run(analysis_v2.preview_identity_anchor_revision(
            "a1",
            analysis_v2.IdentityAnchorRequest(source_frame_index=10, pts_sec=.33, bbox=(.1, .1, .2, .3), annotator="parent", quality_score=.9, expected_revision=2, invalidated_interval=(1.0, 2.0)),
            None,
            session,
        ))
    assert result.diagnostic_only is True
    assert result.next_revision == 3
    assert result.invalidated_intervals == ((1.0, 2.0),)


def test_identity_anchor_confirmation_is_parent_authorized_and_audited() -> None:
    analysis = _analysis()
    analysis.processing_logs = []
    session = AsyncMock()
    session.add = lambda *_args, **_kwargs: None
    session.get = AsyncMock(return_value=analysis)
    session.commit = AsyncMock()
    with patch.object(analysis_v2, "require_parent_pin", new=AsyncMock(return_value=None)):
        result = asyncio.run(analysis_v2.confirm_identity_anchor_revision(
            "a1",
            analysis_v2.IdentityAnchorConfirmRequest(source_frame_index=10, pts_sec=.33, bbox=(.1, .1, .2, .3), annotator="parent", quality_score=.9, expected_revision=1, preview_revision=2, confirmation="confirm_identity_anchor_revision", invalidated_interval=(1.0, 2.0)),
            None,
            session,
        ))
    assert result.next_revision == 2
    assert analysis.processing_logs[-1]["identity_audit"]["legacy_mutation"] is False
    session.commit.assert_awaited_once()


def test_pose_detail_resource_is_parent_authorized_and_raw_joints_stay_out_of_experience() -> None:
    analysis = _analysis()
    analysis.processing_logs = [{
        "pose_v2_detail": {
            "source_pipeline_fingerprint": "v2:pose",
            "summary": {
                "status": "available",
                "frame_count": 1,
                "authoritative_frame_count": 1,
                "measured_joint_count": 1,
                "usable_joint_mask": {"nose": True},
                "source_method": "test",
            },
            "observations": [{
                "source_video_hash": "sha256:v",
                "source_frame_index": 0,
                "pts_sec": 0.0,
                "track_state": {"state": "confirmed", "bbox": [0.1, 0.1, 0.3, 0.8], "identity_score": 0.9, "bbox_source": "measured"},
                "identity_state": "confirmed",
                "joints": {"nose": {"x": 0.2, "y": 0.3, "confidence": 0.9, "visibility": 0.9, "provenance": "measured", "source": "measured"}},
            }],
        }
    }]
    session = AsyncMock()
    session.get = AsyncMock(return_value=analysis)
    with patch.object(analysis_v2, "require_parent_pin", new=AsyncMock(return_value=None)):
        result = asyncio.run(analysis_v2.get_pose_v2_detail("a1", "1234", session))
    assert result.diagnostic_only is True
    assert result.observations[0].joints["nose"].provenance == "measured"


def test_event_label_fact_routes_keep_revision_and_legacy_snapshot() -> None:
    analysis = SimpleNamespace(id="a1", status="completed", action_type="自由滑", action_subtype="节目片段", analysis_profile="step", pipeline_version="legacy", processing_logs=[])
    session = AsyncMock()
    session.add = lambda *_args, **_kwargs: None
    session.get = AsyncMock(return_value=analysis)
    session.commit = AsyncMock()
    request = analysis_v2.EventLabelFactRequest(profile="jump", subtype=None, state="confirmed", reviewer="parent", expected_revision=0, confirmation="propose_event_label_fact")
    with patch.object(analysis_v2, "require_parent_pin", new=AsyncMock(return_value=None)):
        proposed = asyncio.run(analysis_v2.propose_event_label_fact_route("a1", "e1", request, "1234", session))
        applied = asyncio.run(analysis_v2.apply_event_label_fact_route("a1", "e1", proposed.revision, "1234", session))
    assert proposed.revision == 1
    assert proposed.legacy_snapshot["analysis_profile"] == "step"
    assert applied.status == "applied"
    assert analysis.processing_logs[-1]["event_label_fact_audit"]["legacy_mutation"] is False


def test_growth_admission_excludes_shadow_events_with_reason() -> None:
    analysis = SimpleNamespace(id="a1")
    session = AsyncMock()
    session.execute = AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [analysis])))
    experience = {
        "schema_version": "analysis-experience.v2",
        "analysis_id": "a1",
        "authority": "v2",
        "pipeline_mode": "v2",
        "source_pipeline_fingerprint": "v2:fp",
        "diagnostic_only": True,
        "family_usable": False,
        "events": [{"event_id": "e1", "profile": "jump", "state": "confirmed", "status": "confirmed", "observability": "observable"}],
        "claims": [],
        "review_tasks": [],
    }
    with patch.object(analysis_v2, "require_parent_pin", new=AsyncMock(return_value=None)), patch.object(analysis_v2, "present_analysis_experience", return_value=experience):
        report = asyncio.run(analysis_v2.get_growth_admission(analysis_v2.GrowthAdmissionRequest(analysis_ids=("a1",)), "1234", session))
    assert report.included_count == 0
    assert report.excluded_count == 1
    assert report.excluded_reasons == {"shadow_diagnostic": 1}


def test_applied_event_label_fact_projects_without_mutating_legacy_fields() -> None:
    from app.analysis_v2.event_proposals import EventProposal, EventProposalCollection

    proposed = analysis_v2.propose_event_label_fact(
        analysis_id="a1",
        event_id="e1",
        profile="jump",
        subtype="toe_loop",
        state="confirmed",
        legacy_snapshot={"analysis_profile": "step"},
        reviewer="parent",
    )
    applied = analysis_v2.apply_event_label_fact(proposed)
    analysis = SimpleNamespace(
        id="a1",
        action_type="step",
        analysis_profile="step",
        pipeline_version="legacy",
        video_path=None,
        processing_logs=[
            {"event_proposals": EventProposalCollection(
                source_video_hash="sha256:v",
                source_duration_sec=2,
                pipeline_fingerprint="v2:proposal",
                proposals=(EventProposal(
                    event_id="e1",
                    source_video_hash="sha256:v",
                    start_pts=0,
                    end_pts=1,
                    anchor_start_frame=0,
                    anchor_end_frame=10,
                    candidate_profile_scores={"jump": 0, "spin": 0, "step": 0, "spiral": 0},
                    tracking_coverage=1,
                    pose_coverage=1,
                    observability="observable",
                    evidence_sources=("motion",),
                    provenance_fingerprint="proposal:fp",
                ),),
            ).model_dump(mode="json")},
            {"event_label_fact": proposed.model_dump(mode="json")},
            {"event_label_fact": applied.model_dump(mode="json")},
        ],
        frame_motion_scores={},
        pose_data={},
        vision_path_a={},
        vision_path_b={},
        cross_validation={},
        source_duration_sec=2,
    )
    with patch.object(analysis_v2, "evidence_from_legacy_analysis", return_value=(2, ())) :
        rendered = analysis_v2.present_analysis_experience(analysis, diagnostic=True)
    event = rendered["events"][0]
    assert event["profile"] == "jump"
    assert event["subtype"] == "toe_loop"
    assert event["state"] == "confirmed"
    assert event["evidence_summary"]["classifier_state"] in {"ambiguous", "unknown"}
    assert analysis.analysis_profile == "step"


def _jump_moment_set(event_id: str = "e1"):
    from app.analysis_v2.profile_moments import MomentEvidenceSample, localize_profile_moments
    samples = [
        MomentEvidenceSample(source_frame_index=0, pts_sec=0, ice_contact=.8, airborne=.1, body_center_y=.5),
        MomentEvidenceSample(source_frame_index=1, pts_sec=.1, ice_contact=.2, airborne=.8, body_center_y=.4),
        MomentEvidenceSample(source_frame_index=2, pts_sec=.2, ice_contact=.1, airborne=.9, body_center_y=.2),
        MomentEvidenceSample(source_frame_index=3, pts_sec=.3, ice_contact=.9, airborne=.1, body_center_y=.4),
    ]
    return localize_profile_moments(event_id=event_id, profile="jump", event_start_pts=0, event_end_pts=.5, samples=samples, source_timeline_fingerprint="timeline")


def test_event_moment_proposal_routes_keep_snapshots_invalidation_and_regeneration_trigger() -> None:
    analysis = SimpleNamespace(id="a1", status="completed", processing_logs=[])
    session = AsyncMock()
    session.add = lambda *_args, **_kwargs: None
    session.get = AsyncMock(return_value=analysis)
    session.commit = AsyncMock()
    request = analysis_v2.EventMomentProposalRequest(after=_jump_moment_set(), reviewer="parent", expected_revision=0, confirmation="propose_event_moments")
    with patch.object(analysis_v2, "require_parent_pin", new=AsyncMock(return_value=None)):
        proposed = asyncio.run(analysis_v2.propose_event_moment_route("a1", "e1", request, "1234", session))
        applied = asyncio.run(analysis_v2.apply_event_moment_route("a1", "e1", proposed.revision, "1234", session))
        dismissed = asyncio.run(analysis_v2.dismiss_event_moment_route("a1", "e1", proposed.revision, "1234", session))
    assert proposed.before is None
    assert proposed.after.event_id == "e1"
    assert proposed.report_regeneration_required is True
    assert "report" in proposed.invalidates
    assert applied.status == "applied"
    assert dismissed.status == "dismissed"
    assert analysis.processing_logs[-1]["event_moment_audit"]["legacy_mutation"] is False


def test_review_tasks_exist_only_for_parent_resolvable_moment_ambiguity() -> None:
    from app.analysis_v2.event_proposals import EventProposal, EventProposalCollection
    from app.analysis_v2.profile_moments import MomentEvidenceSample

    proposal = EventProposal(event_id="e1", source_video_hash="sha256:v", start_pts=0, end_pts=1, anchor_start_frame=0, anchor_end_frame=10, candidate_profile_scores={"jump": 1, "spin": 0, "step": 0, "spiral": 0}, tracking_coverage=1, pose_coverage=1, observability="observable", evidence_sources=("motion",), provenance_fingerprint="proposal")
    moments = [
        MomentEvidenceSample(source_frame_index=0, pts_sec=0, ice_contact=.8, airborne=.1, body_center_y=.5),
        MomentEvidenceSample(source_frame_index=1, pts_sec=.1, ice_contact=.2, airborne=.8, body_center_y=.4),
        MomentEvidenceSample(source_frame_index=2, pts_sec=.2, ice_contact=.1, airborne=.9, body_center_y=.2),
        MomentEvidenceSample(source_frame_index=3, pts_sec=.3, ice_contact=.82, airborne=.1, body_center_y=.4),
        MomentEvidenceSample(source_frame_index=4, pts_sec=.4, ice_contact=.2, airborne=.8, body_center_y=.4),
        MomentEvidenceSample(source_frame_index=5, pts_sec=.5, ice_contact=.80, airborne=.1, body_center_y=.4),
    ]
    classification = SimpleNamespace(profile="jump", subtype=SimpleNamespace(subtype=None), state="confirmed", confirmation_task=None, classifier_fingerprint="classifier", definition_version="profile.v1", evidence_summary={})
    analysis = SimpleNamespace(id="a1", action_type="jump", analysis_profile="jump", pipeline_version="legacy", video_path=None, processing_logs=[{"event_proposals": EventProposalCollection(source_video_hash="sha256:v", source_duration_sec=1, pipeline_fingerprint="pipeline", proposals=(proposal,)).model_dump(mode="json")}, {"moment_evidence": {"event_id": "e1", "samples": [item.model_dump(mode="json") for item in moments]}}], frame_motion_scores={}, pose_data={}, vision_path_a={}, vision_path_b={}, cross_validation={}, source_duration_sec=1)
    with patch.object(analysis_v2, "classify_proposal", return_value=classification), patch.object(analysis_v2, "evidence_from_legacy_analysis", return_value=(1, ())):
        rendered = analysis_v2.present_analysis_experience(analysis, diagnostic=True)
    tasks = [item for item in rendered["review_tasks"] if item["kind"].startswith("confirm_event_moment")]
    assert len(tasks) == 1
    assert tasks[0]["event_id"] == "e1"


def test_rotation_evidence_projects_strict_event_contract_fact_and_exact_pts_review_task() -> None:
    import math
    from app.analysis_v2.event_proposals import EventProposal, EventProposalCollection
    from app.analysis_v2.rotation import RotationEvidenceSample

    proposal = EventProposal(event_id="e1", source_video_hash="sha256:v", start_pts=0, end_pts=1, anchor_start_frame=0, anchor_end_frame=30, candidate_profile_scores={"jump": 1, "spin": 0, "step": 0, "spiral": 0}, tracking_coverage=1, pose_coverage=1, observability="observable", evidence_sources=("motion",), provenance_fingerprint="proposal")
    samples = []
    for index in range(31):
        progress = index / 30
        samples.append(RotationEvidenceSample(source_frame_index=index, pts_sec=progress, phase="airborne", pose_quality=.95, left_right_assignment_confidence=.98, shoulder_orientation_rad=3 * math.pi * progress, hip_orientation_rad=3 * math.pi * progress, torso_appearance_phase_rad=4 * math.pi * progress, silhouette_orientation_rad=4 * math.pi * progress, silhouette_confidence=.9, limb_appearance_phase_rad=4 * math.pi * progress, optical_flow_rotation_rad=0 if index == 0 else 4 * math.pi / 30, optical_flow_confidence=.9))
    classification = SimpleNamespace(profile="jump", subtype=SimpleNamespace(subtype="toe_loop", confidence=.9), state="confirmed", confirmation_task=None, classifier_fingerprint="classifier", definition_version="profile.v1", evidence_summary={})
    source_timeline = {"schema_version": "source-timeline.v1", "source_video_hash": "sha256:v", "duration_sec": 1, "width": 1280, "height": 720, "rotation_degrees": 0, "timebase": {"numerator": 1, "denominator": 30, "is_vfr": False}, "timestamp_status": "exact", "frames": [], "decode_gaps": [], "pts_discontinuities": [], "fingerprint": "timeline"}
    analysis = SimpleNamespace(id="a1", action_type="jump", analysis_profile="jump", pipeline_version="legacy", video_path=None, processing_logs=[{"source_timeline": source_timeline}, {"event_proposals": EventProposalCollection(source_video_hash="sha256:v", source_duration_sec=1, pipeline_fingerprint="pipeline", proposals=(proposal,)).model_dump(mode="json")}, {"rotation_evidence": {"event_id": "e1", "samples": [item.model_dump(mode="json") for item in samples]}}], frame_motion_scores={}, pose_data={}, vision_path_a={}, vision_path_b={}, cross_validation={}, source_duration_sec=1)
    with patch.object(analysis_v2, "classify_proposal", return_value=classification), patch.object(analysis_v2, "evidence_from_legacy_analysis", return_value=(1, ())):
        rendered = analysis_v2.present_analysis_experience(analysis, diagnostic=True)
    rotation = rendered["events"][0]["rotation"]
    assert rotation["status"] == "range"
    assert rotation["refusal_reason"] == "conflicting_turn_hypotheses"
    assert rendered["claims"][0]["claim_type"] == "airborne_body_rotation_turns_v1"
    assert rendered["claims"][0]["status"] == "uncertain"
    review = next(task for task in rendered["review_tasks"] if task["kind"] == "confirm_rotation_estimate")
    assert review["start_pts"] == 0
    assert review["end_pts"] == 1
    assert review["convention"] == "airborne_body_rotation"


def test_exact_source_frame_thumbnail_requires_parent_before_extraction(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"private-source")
    analysis = SimpleNamespace(id="a1", status="completed", video_path=str(source))
    session = AsyncMock()
    session.get = AsyncMock(return_value=analysis)

    async def reject(*_args, **_kwargs):
        raise HTTPException(status_code=403, detail="parent PIN required")

    extractor = AsyncMock()
    with patch.object(analysis_v2, "require_parent_pin", new=reject), patch.object(analysis_v2, "extract_source_frame_bytes", new=extractor):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(analysis_v2.get_analysis_source_frame_image("a1", 42, None, session))
    assert exc.value.status_code == 403
    extractor.assert_not_called()


def test_exact_source_frame_thumbnail_preserves_index_and_private_cache(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"private-source")
    analysis = SimpleNamespace(id="a1", status="completed", video_path=str(source))
    session = AsyncMock()
    session.get = AsyncMock(return_value=analysis)

    with patch.object(analysis_v2, "require_parent_pin", new=AsyncMock(return_value=None)), patch.object(
        analysis_v2, "extract_source_frame_bytes", return_value=b"jpeg-frame"
    ) as extractor:
        response = asyncio.run(analysis_v2.get_analysis_source_frame_image("a1", 42, "1234", session))
    extractor.assert_called_once_with(source, 42)
    assert response.body == b"jpeg-frame"
    assert response.headers["x-source-frame-index"] == "42"
    assert response.headers["cache-control"].startswith("private")
