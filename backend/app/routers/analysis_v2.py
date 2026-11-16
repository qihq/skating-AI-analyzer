from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.analysis_v2.presentation import AnalysisExperienceV2, EventV2, ReviewTaskV2, build_pose_detail_resource, present_analysis_experience as build_analysis_experience
from app.database import get_session
from app.models import Analysis
from app.services.parent_access import require_parent_pin
from app.analysis_v2.evaluation.source_media import SourceMediaError, extract_source_frame_bytes, probe_source, source_frame_index
from app.analysis_v2.contracts import DetectionProposalDiagnostics, EventMomentSet, IdentityAnchor, IdentityAnchorRevision, IdentityTimeline, PoseAvailabilitySummary, PoseDetailResource, PoseObservation, RotationEstimate
from app.analysis_v2.identity import create_anchor_revision, immutable_template_fingerprint, replace_causal_interval
from app.analysis_v2.detection import build_proposal_diagnostics, resolve_provider_config
from app.analysis_v2.evaluation.pilot12_detection import evaluate_pilot12_detection
from app.analysis_v2.evaluation.pilot12_event_proposals import evaluate_pilot12_event_proposals, evaluate_pilot14_action_classification, evidence_from_legacy_analysis
from app.analysis_v2.event_proposals import EventProposalCollection, merge_proposals, set_proposal_outcome, split_proposal
from app.analysis_v2.action_classification import classify_proposal
from app.analysis_v2.event_label_facts import EventLabelFactRevision, apply_event_label_fact, dismiss_event_label_fact, latest_applied_event_label_fact, propose_event_label_fact
from app.analysis_v2.facts import AnalysisFactV2, AnalysisFactsV2, FactPermission
from app.analysis_v2.profile_eligibility import growth_admission
from app.analysis_v2.profile_moments import MomentEvidenceSample, localize_profile_moments
from app.analysis_v2.event_moment_facts import EventMomentProposalRevision, apply_event_moments, dismiss_event_moments, latest_applied_event_moments, propose_event_moments
from app.analysis_v2.rotation import RotationEvidenceSample, estimate_rotation
from app.analysis_v2.rotation_facts import rotation_fact_from_estimate
from app.routers.capabilities import get_runtime_config
from app.analysis_v2.config import RuntimeConfig
from pathlib import Path

router = APIRouter(prefix="/api/analysis", tags=["analysis-v2"])


class IdentityAnchorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_frame_index: int = Field(ge=0)
    pts_sec: float = Field(ge=0)
    bbox: tuple[float, float, float, float]
    annotator: str = Field(min_length=1, max_length=160)
    quality_score: float = Field(ge=0, le=1)
    expected_revision: int = Field(default=1, ge=1)
    invalidated_interval: tuple[float, float] | None = None


class IdentityRevisionPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["identity-revision-preview.v1"] = "identity-revision-preview.v1"
    analysis_id: str
    current_revision: int
    next_revision: int
    invalidated_intervals: tuple[tuple[float, float], ...] = ()
    anchor: IdentityAnchor
    identity: IdentityTimeline | None = None
    diagnostic_only: Literal[True] = True


class IdentityAnchorConfirmRequest(IdentityAnchorRequest):
    preview_revision: int = Field(ge=2)
    confirmation: Literal["confirm_identity_anchor_revision"]


class EventProposalMutationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["merge", "split", "ignore", "ordinary_skating", "unknown", "confirm"]
    event_id: str | None = None
    event_ids: tuple[str, ...] = ()
    split_pts: float | None = Field(default=None, ge=0)
    expected_revision: int = Field(ge=1)
    scope: Literal["event", "analysis"]
    confirmation: Literal["confirm_event_proposal_revision"]


class EventLabelFactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: Literal["jump", "spin", "step", "spiral"] | None = None
    subtype: str | None = Field(default=None, max_length=160)
    state: Literal["confirmed", "ambiguous", "unknown"] = "ambiguous"
    reviewer: str = Field(min_length=1, max_length=160)
    expected_revision: int = Field(default=0, ge=0)
    confirmation: Literal["propose_event_label_fact"]

    @model_validator(mode="after")
    def profile_matches_state(self) -> "EventLabelFactRequest":
        if self.state == "unknown" and self.profile is not None:
            raise ValueError("unknown event label cannot carry a profile")
        if self.state != "unknown" and self.profile is None:
            raise ValueError("confirmed or ambiguous event label requires a profile")
        return self


class GrowthAdmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    analysis_ids: tuple[str, ...] = Field(min_length=1, max_length=48)


class GrowthAdmissionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["growth-profile-admission.v1"] = "growth-profile-admission.v1"
    included_count: int = Field(ge=0)
    excluded_count: int = Field(ge=0)
    excluded_reasons: dict[str, int] = Field(default_factory=dict)
    diagnostic_only: Literal[True] = True


class EventMomentProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    after: EventMomentSet
    reviewer: str = Field(min_length=1, max_length=160)
    expected_revision: int = Field(default=0, ge=0)
    confirmation: Literal["propose_event_moments"]


def _event_moment_history(analysis: Any, event_id: str) -> list[EventMomentProposalRevision]:
    history: list[EventMomentProposalRevision] = []
    stored = getattr(analysis, "processing_logs", None)
    for item in stored if isinstance(stored, list) else ():
        if isinstance(item, dict) and isinstance(item.get("event_moment_proposal"), dict):
            proposal = EventMomentProposalRevision.model_validate(item["event_moment_proposal"])
            if proposal.event_id == event_id:
                history.append(proposal)
    return sorted(history, key=lambda item: item.revision)


def _append_event_moment_proposal(analysis: Any, proposal: EventMomentProposalRevision, *, action: str) -> None:
    stored = getattr(analysis, "processing_logs", None)
    logs = list(stored) if isinstance(stored, list) else []
    logs.append({
        "event_moment_proposal": proposal.model_dump(mode="json"),
        "event_moment_audit": {
            "action": action,
            "event_id": proposal.event_id,
            "revision": proposal.revision,
            "report_regeneration_required": proposal.report_regeneration_required,
            "invalidates": list(proposal.invalidates),
            "legacy_mutation": False,
        },
    })
    analysis.processing_logs = logs


def _stored_moment_samples(analysis: Any, event_id: str) -> tuple[MomentEvidenceSample, ...]:
    stored = getattr(analysis, "processing_logs", None)
    if isinstance(stored, list):
        for item in reversed(stored):
            if not isinstance(item, dict):
                continue
            payload = item.get("moment_evidence")
            if isinstance(payload, dict) and payload.get("event_id") == event_id and isinstance(payload.get("samples"), list):
                return tuple(MomentEvidenceSample.model_validate(sample) for sample in payload["samples"])
    return ()


def _stored_rotation_samples(analysis: Any, event_id: str) -> tuple[RotationEvidenceSample, ...]:
    stored = getattr(analysis, "processing_logs", None)
    if isinstance(stored, list):
        for item in reversed(stored):
            if not isinstance(item, dict):
                continue
            payload = item.get("rotation_evidence")
            if isinstance(payload, dict) and payload.get("event_id") == event_id and isinstance(payload.get("samples"), list):
                return tuple(RotationEvidenceSample.model_validate(sample) for sample in payload["samples"])
    return ()


def _stored_rotation_estimate(analysis: Any, event_id: str, source_timeline_fingerprint: str) -> RotationEstimate | None:
    stored = getattr(analysis, "processing_logs", None)
    if isinstance(stored, list):
        for item in reversed(stored):
            if not isinstance(item, dict) or not isinstance(item.get("rotation_estimate"), dict):
                continue
            estimate = RotationEstimate.model_validate(item["rotation_estimate"])
            if estimate.event_id == event_id and estimate.source_timeline_fingerprint == source_timeline_fingerprint:
                return estimate
    return None


def _event_label_fact_history(analysis: Any, event_id: str) -> list[EventLabelFactRevision]:
    history: list[EventLabelFactRevision] = []
    stored = getattr(analysis, "processing_logs", None)
    for item in stored if isinstance(stored, list) else ():
        if isinstance(item, dict) and isinstance(item.get("event_label_fact"), dict):
            fact = EventLabelFactRevision.model_validate(item["event_label_fact"])
            if fact.event_id == event_id:
                history.append(fact)
    return sorted(history, key=lambda item: item.revision)


def _append_event_label_fact(analysis: Any, fact: EventLabelFactRevision, *, action: str) -> None:
    stored = getattr(analysis, "processing_logs", None)
    logs = list(stored) if isinstance(stored, list) else []
    logs.append({"event_label_fact": fact.model_dump(mode="json"), "event_label_fact_audit": {"action": action, "human_provenance": True, "legacy_mutation": False}})
    analysis.processing_logs = logs


def present_analysis_experience(analysis: Any, *, diagnostic: bool = False) -> dict[str, Any]:
    timeline = None
    stored = getattr(analysis, "processing_logs", None)
    video_path = getattr(analysis, "video_path", None)
    if video_path:
        try:
            path = Path(str(video_path))
            if path.exists():
                timeline = source_frame_index(path, metadata=probe_source(path)).to_timeline()
        except (OSError, SourceMediaError, RuntimeError, ValueError):
            timeline = {"schema_version": "source-timeline.v1", "source_video_hash": "", "duration_sec": None, "width": 1, "height": 1, "rotation_degrees": 0, "timebase": {"numerator": 1, "denominator": 1, "is_vfr": False}, "timestamp_status": "unavailable", "frames": [], "decode_gaps": [], "pts_discontinuities": [], "fingerprint": "unavailable"}
    if timeline is None and isinstance(stored, list):
        for item in reversed(stored):
            if isinstance(item, dict) and isinstance(item.get("source_timeline"), dict):
                timeline = item["source_timeline"]
                break
    identity = None
    pose_summary = None
    event_proposals = None
    if diagnostic and isinstance(stored, list):
        for item in reversed(stored):
            if isinstance(item, dict) and isinstance(item.get("identity_timeline"), dict):
                identity = IdentityTimeline.model_validate(item["identity_timeline"])
            if isinstance(item, dict) and isinstance(item.get("pose_summary"), dict):
                pose_summary = PoseAvailabilitySummary.model_validate(item["pose_summary"])
            if isinstance(item, dict) and isinstance(item.get("event_proposals"), dict):
                event_proposals = EventProposalCollection.model_validate(item["event_proposals"])
            if identity is not None and pose_summary is not None and event_proposals is not None:
                break
    if diagnostic and event_proposals is None:
        try:
            event_proposals = _generate_event_proposals_for_analysis(analysis)
        except (TypeError, ValueError, KeyError):
            event_proposals = None
    rendered = build_analysis_experience(analysis, pipeline_mode="shadow" if diagnostic else "legacy", source_timeline=timeline, identity=identity, pose=pose_summary)
    if diagnostic and event_proposals is not None:
        mapping = {key: getattr(analysis, key, None) for key in ("frame_motion_scores", "pose_data", "vision_path_a", "vision_path_b", "cross_validation", "source_duration_sec")}
        try:
            _duration, all_samples = evidence_from_legacy_analysis(str(event_proposals.source_video_hash), mapping)
        except (TypeError, ValueError, KeyError):
            all_samples = ()

        def classify(item: Any) -> Any:
            event_samples = tuple(sample for sample in all_samples if item.start_pts <= sample.pts_sec <= item.end_pts)
            return classify_proposal(item, analysis=mapping, samples=event_samples)

        classified = tuple((item, classify(item), latest_applied_event_label_fact(_event_label_fact_history(analysis, item.event_id))) for item in event_proposals.proposals)

        def effective_event(item: Any, result: Any, correction: EventLabelFactRevision | None) -> EventV2:
            profile = result.profile
            subtype = result.subtype.subtype
            state = result.state
            confirmation_task = result.confirmation_task
            fingerprint = result.classifier_fingerprint
            definition_version = result.definition_version
            evidence_summary = dict(result.evidence_summary)
            if correction is not None:
                state = correction.state
                profile = correction.profile if correction.profile is not None and state != "unknown" else "unknown"
                subtype = correction.subtype if profile != "unknown" else None
                confirmation_task = None if state == "confirmed" else f"{item.event_id}:confirm_action_profile"
                fingerprint = f"event-label-fact:{correction.revision}:{result.classifier_fingerprint}"
                definition_version = correction.schema_version
                evidence_summary.update({
                    "classifier_profile": result.profile,
                    "classifier_state": result.state,
                    "applied_event_label_revision": correction.revision,
                    "human_provenance": True,
                })
            applied_moments = latest_applied_event_moments(_event_moment_history(analysis, item.event_id))
            moment_set = applied_moments.after if applied_moments is not None else None
            if moment_set is None and profile in {"jump", "spin", "step", "spiral"}:
                samples = _stored_moment_samples(analysis, item.event_id)
                if samples:
                    timeline_fingerprint = str((rendered.source_timeline or {}).get("fingerprint") or "source-timeline:unavailable")
                    moment_set = localize_profile_moments(
                        event_id=item.event_id,
                        profile=profile,
                        event_start_pts=item.start_pts,
                        event_end_pts=item.end_pts,
                        samples=samples,
                        source_timeline_fingerprint=timeline_fingerprint,
                    )
            rotation = None
            if profile in {"jump", "spin"}:
                timeline_fingerprint = str((rendered.source_timeline or {}).get("fingerprint") or "source-timeline:unavailable")
                rotation = _stored_rotation_estimate(analysis, item.event_id, timeline_fingerprint)
                if rotation is None:
                    subtype_support = 1.0 if correction is not None and correction.state == "confirmed" and subtype else float(getattr(result.subtype, "confidence", 0.0))
                    rotation = estimate_rotation(
                        event_id=item.event_id,
                        profile=profile,
                        event_start_pts=item.start_pts,
                        event_end_pts=item.end_pts,
                        samples=_stored_rotation_samples(analysis, item.event_id),
                        source_timeline_fingerprint=timeline_fingerprint,
                        subtype=subtype,
                        subtype_support=subtype_support,
                    )
            return EventV2(
                event_id=item.event_id, profile=profile, subtype=subtype,
                state=state, start_pts=item.start_pts, end_pts=item.end_pts,
                status="unobservable" if state == "unknown" and item.observability == "unobservable" else "uncertain" if state != "confirmed" else "confirmed",
                observability=item.observability,
                candidate_profile_scores=item.candidate_profile_scores, proposal_status=item.status,
                tracking_coverage=item.tracking_coverage, pose_coverage=item.pose_coverage,
                provenance_fingerprint=fingerprint, revision=correction.revision if correction is not None else item.revision,
                evidence_summary=evidence_summary, confirmation_task=confirmation_task,
                definition_version=definition_version,
                moments=moment_set,
                moment_definition_version=moment_set.definition_version if moment_set else None,
                moment_completeness=moment_set.completeness if moment_set else None,
                rotation=rotation,
            )

        effective_events = tuple(effective_event(item, result, correction) for item, result, correction in classified)
        review_tasks = tuple(ReviewTaskV2(
            task_id=(None if correction is not None and correction.state == "confirmed" else result.confirmation_task) or f"{item.event_id}:window",
            authority="v2",
            kind="confirm_action_profile" if not (correction is not None and correction.state == "confirmed") and result.confirmation_task else "confirm_action_window",
            event_id=item.event_id,
        ) for item, result, correction in classified if not (correction is not None and correction.state == "confirmed") and (result.confirmation_task or item.status == "pending_confirmation")) + tuple(ReviewTaskV2(
            task_id=f"{event.event_id}:moment:{moment.semantic_key}",
            authority="v2",
            kind="confirm_event_moment" if moment.kind != "interval" else "confirm_event_interval",
            event_id=event.event_id,
        ) for event in effective_events if event.moments is not None for moment in event.moments.moments if moment.review_resolvable)
        review_tasks += tuple(ReviewTaskV2(
            task_id=f"{event.event_id}:rotation",
            authority="v2",
            kind="confirm_rotation_estimate",
            event_id=event.event_id,
            start_pts=next((moment.pts_sec for moment in event.moments.moments if moment.semantic_key in {"takeoff", "spin_main"} and moment.pts_sec is not None), event.start_pts) if event.moments else event.start_pts,
            end_pts=next((moment.pts_sec if moment.end_pts_sec is None else moment.end_pts_sec for moment in reversed(event.moments.moments) if moment.semantic_key in {"landing", "spin_main"} and (moment.pts_sec is not None or moment.end_pts_sec is not None)), event.end_pts) if event.moments else event.end_pts,
            definition_version=event.rotation.definition_version,
            convention=event.rotation.value_convention,
        ) for event in effective_events if event.rotation is not None and event.rotation.review_required)
        rotation_claims = tuple(
            rotation_fact_from_estimate(
                analysis_id=str(getattr(analysis, "id", "unknown")),
                estimate=event.rotation,
                source_pipeline_fingerprint=event_proposals.pipeline_fingerprint,
                diagnostic_only=True,
            )
            for event in effective_events
            if event.rotation is not None
        )
        rendered = rendered.model_copy(update={
            "authority": "v2", "pipeline_mode": "v2", "diagnostic_only": True, "family_usable": False,
            "source_pipeline_fingerprint": event_proposals.pipeline_fingerprint,
            "claims": rotation_claims,
            "events": effective_events,
            "review_tasks": review_tasks,
        })
    return rendered.model_dump(mode="json")


def _stored_event_proposals(analysis: Any) -> EventProposalCollection | None:
    stored = getattr(analysis, "processing_logs", None)
    if isinstance(stored, list):
        for item in reversed(stored):
            if isinstance(item, dict) and isinstance(item.get("event_proposals"), dict):
                return EventProposalCollection.model_validate(item["event_proposals"])
    return None


def _generate_event_proposals_for_analysis(analysis: Any) -> EventProposalCollection:
    source_hash = f"sha256:analysis:{getattr(analysis, 'id', 'unknown')}"
    timeline = getattr(analysis, "processing_logs", None)
    if isinstance(timeline, list):
        for item in reversed(timeline):
            if isinstance(item, dict) and isinstance(item.get("source_timeline"), dict) and item["source_timeline"].get("source_video_hash"):
                source_hash = str(item["source_timeline"]["source_video_hash"])
                break
    mapping = {key: getattr(analysis, key, None) for key in ("frame_motion_scores", "pose_data", "video_temporal_diagnostics", "source_duration_sec")}
    duration, samples = evidence_from_legacy_analysis(source_hash, mapping)
    from app.analysis_v2.event_proposals import generate_event_proposals
    return generate_event_proposals(source_video_hash=source_hash, source_duration_sec=duration, samples=samples, pipeline_fingerprint=f"v2:iteration10:{getattr(analysis, 'pipeline_version', 'unknown')}")


async def _load_analysis(analysis_id: str, session: AsyncSession) -> Analysis:
    analysis = await session.get(Analysis, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="未找到该分析记录。")
    return analysis


@router.get("/{analysis_id}/experience-v2", response_model=AnalysisExperienceV2)
async def get_analysis_experience_v2(
    analysis_id: str,
    session: AsyncSession = Depends(get_session),
) -> AnalysisExperienceV2:
    analysis = await _load_analysis(analysis_id, session)
    return AnalysisExperienceV2.model_validate(present_analysis_experience(analysis, diagnostic=False))


@router.get("/{analysis_id}/experience-v2/diagnostic", response_model=AnalysisExperienceV2)
async def get_analysis_experience_v2_diagnostic(
    analysis_id: str,
    x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"),
    session: AsyncSession = Depends(get_session),
) -> AnalysisExperienceV2:
    await require_parent_pin(session, x_parent_pin)
    analysis = await _load_analysis(analysis_id, session)
    return AnalysisExperienceV2.model_validate(present_analysis_experience(analysis, diagnostic=True))


@router.post("/growth-admission", response_model=GrowthAdmissionReport)
async def get_growth_admission(
    payload: GrowthAdmissionRequest,
    x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"),
    session: AsyncSession = Depends(get_session),
) -> GrowthAdmissionReport:
    await require_parent_pin(session, x_parent_pin)
    result = await session.execute(select(Analysis).where(Analysis.id.in_(tuple(dict.fromkeys(payload.analysis_ids)))))
    fact_sets: list[AnalysisFactsV2] = []
    diagnostic_ids: list[str] = []
    for analysis in result.scalars().all():
        experience = AnalysisExperienceV2.model_validate(present_analysis_experience(analysis, diagnostic=True))
        for event in experience.events:
            fact_set_id = f"{experience.analysis_id}:{event.event_id}"
            recognized = event.profile if event.profile in {"jump", "spin", "step", "spiral"} else None
            if event.state == "unknown" or recognized is None:
                value, fact_status, observability = None, "unobservable", "unobservable"
            else:
                value = recognized
                fact_status = "confirmed" if event.state == "confirmed" else "uncertain"
                observability = "observable"
            fact = AnalysisFactV2(
                analysis_id=fact_set_id,
                event_id=event.event_id,
                claim_type="action_profile",
                value=value,
                authority="v2",
                source_pipeline_fingerprint=experience.source_pipeline_fingerprint,
                definition_version=event.definition_version,
                status=fact_status,
                observability=observability,
                provenance=("measured",),
                permissions=FactPermission(family_display=True, aggregation=not experience.diagnostic_only),
            )
            fact_sets.append(AnalysisFactsV2(analysis_id=fact_set_id, authority="v2", facts=(fact,)))
            if experience.diagnostic_only:
                diagnostic_ids.append(fact_set_id)
    admission = growth_admission(fact_sets, diagnostic_fact_set_ids=diagnostic_ids)
    return GrowthAdmissionReport(
        included_count=int(admission["included_count"]),
        excluded_count=int(admission["excluded_count"]),
        excluded_reasons=dict(admission["excluded_reasons"]),
    )


@router.get("/{analysis_id}/event-proposals", response_model=EventProposalCollection)
async def get_event_proposals(
    analysis_id: str,
    x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"),
    session: AsyncSession = Depends(get_session),
) -> EventProposalCollection:
    await require_parent_pin(session, x_parent_pin)
    analysis = await _load_analysis(analysis_id, session)
    collection = _stored_event_proposals(analysis)
    if collection is None:
        collection = _generate_event_proposals_for_analysis(analysis)
    return collection


@router.post("/{analysis_id}/event-proposals/mutate", response_model=EventProposalCollection)
async def mutate_event_proposals(
    analysis_id: str,
    payload: EventProposalMutationRequest,
    x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"),
    session: AsyncSession = Depends(get_session),
) -> EventProposalCollection:
    await require_parent_pin(session, x_parent_pin)
    analysis = await _load_analysis(analysis_id, session)
    collection = _stored_event_proposals(analysis)
    if collection is None:
        collection = _generate_event_proposals_for_analysis(analysis)
    if payload.expected_revision != collection.revision:
        raise HTTPException(status_code=409, detail={"code": "event_proposal_revision_conflict", "current_revision": collection.revision})
    if payload.scope == "event" and payload.operation == "merge":
        raise HTTPException(status_code=400, detail="merge requires explicit analysis scope")
    try:
        if payload.operation == "merge":
            updated = merge_proposals(collection, payload.event_ids)
        elif payload.operation == "split":
            if payload.event_id is None or payload.split_pts is None:
                raise ValueError("split requires event_id and split_pts")
            updated = split_proposal(collection, payload.event_id, payload.split_pts)
        else:
            if payload.event_id is None:
                raise ValueError("event-scoped outcome requires event_id")
            outcome = {"ignore": "ignored", "ordinary_skating": "ordinary_skating", "unknown": "unknown", "confirm": "confirmed_window"}[payload.operation]
            updated = set_proposal_outcome(collection, payload.event_id, outcome)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logs = list(analysis.processing_logs) if isinstance(analysis.processing_logs, list) else []
    logs.append({"event_proposals": updated.model_dump(mode="json"), "event_proposal_audit": {"operation": payload.operation, "scope": payload.scope, "event_id": payload.event_id, "event_ids": list(payload.event_ids), "parent_revision": collection.revision, "revision": updated.revision, "legacy_mutation": False}})
    analysis.processing_logs = logs
    session.add(analysis)
    await session.commit()
    return updated


@router.get("/{analysis_id}/events/{event_id}/label-facts", response_model=tuple[EventLabelFactRevision, ...])
async def get_event_label_facts(
    analysis_id: str,
    event_id: str,
    x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"),
    session: AsyncSession = Depends(get_session),
) -> tuple[EventLabelFactRevision, ...]:
    await require_parent_pin(session, x_parent_pin)
    analysis = await _load_analysis(analysis_id, session)
    return tuple(_event_label_fact_history(analysis, event_id))


@router.post("/{analysis_id}/events/{event_id}/label-facts", response_model=EventLabelFactRevision)
async def propose_event_label_fact_route(
    analysis_id: str,
    event_id: str,
    payload: EventLabelFactRequest,
    x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"),
    session: AsyncSession = Depends(get_session),
) -> EventLabelFactRevision:
    await require_parent_pin(session, x_parent_pin)
    analysis = await _load_analysis(analysis_id, session)
    history = _event_label_fact_history(analysis, event_id)
    latest = history[-1] if history else None
    if payload.expected_revision != (latest.revision if latest else 0):
        raise HTTPException(status_code=409, detail="event label fact revision changed")
    legacy_snapshot = {
        key: getattr(analysis, key, None)
        for key in ("action_type", "action_subtype", "analysis_profile", "pipeline_version")
    }
    fact = propose_event_label_fact(
        analysis_id=analysis_id, event_id=event_id, profile=payload.profile, subtype=payload.subtype,
        state=payload.state, parent=latest, legacy_snapshot=legacy_snapshot, reviewer=payload.reviewer,
    )
    _append_event_label_fact(analysis, fact, action="propose")
    session.add(analysis)
    await session.commit()
    return fact


@router.post("/{analysis_id}/events/{event_id}/label-facts/{revision}/apply", response_model=EventLabelFactRevision)
async def apply_event_label_fact_route(
    analysis_id: str, event_id: str, revision: int,
    x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"),
    session: AsyncSession = Depends(get_session),
) -> EventLabelFactRevision:
    await require_parent_pin(session, x_parent_pin)
    analysis = await _load_analysis(analysis_id, session)
    fact = next((item for item in reversed(_event_label_fact_history(analysis, event_id)) if item.revision == revision), None)
    if fact is None or fact.status == "dismissed":
        raise HTTPException(status_code=400, detail="event label fact cannot be applied")
    applied = apply_event_label_fact(fact)
    _append_event_label_fact(analysis, applied, action="apply")
    session.add(analysis)
    await session.commit()
    return applied


@router.post("/{analysis_id}/events/{event_id}/label-facts/{revision}/dismiss", response_model=EventLabelFactRevision)
async def dismiss_event_label_fact_route(
    analysis_id: str, event_id: str, revision: int,
    x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"),
    session: AsyncSession = Depends(get_session),
) -> EventLabelFactRevision:
    await require_parent_pin(session, x_parent_pin)
    analysis = await _load_analysis(analysis_id, session)
    fact = next((item for item in reversed(_event_label_fact_history(analysis, event_id)) if item.revision == revision), None)
    if fact is None:
        raise HTTPException(status_code=404, detail="event label fact not found")
    dismissed = dismiss_event_label_fact(fact)
    _append_event_label_fact(analysis, dismissed, action="dismiss")
    session.add(analysis)
    await session.commit()
    return dismissed


@router.get("/{analysis_id}/events/{event_id}/moment-proposals", response_model=tuple[EventMomentProposalRevision, ...])
async def get_event_moment_proposals(
    analysis_id: str, event_id: str,
    x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"),
    session: AsyncSession = Depends(get_session),
) -> tuple[EventMomentProposalRevision, ...]:
    await require_parent_pin(session, x_parent_pin)
    analysis = await _load_analysis(analysis_id, session)
    return tuple(_event_moment_history(analysis, event_id))


@router.post("/{analysis_id}/events/{event_id}/moment-proposals", response_model=EventMomentProposalRevision)
async def propose_event_moment_route(
    analysis_id: str, event_id: str, payload: EventMomentProposalRequest,
    x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"),
    session: AsyncSession = Depends(get_session),
) -> EventMomentProposalRevision:
    await require_parent_pin(session, x_parent_pin)
    analysis = await _load_analysis(analysis_id, session)
    if payload.after.event_id != event_id:
        raise HTTPException(status_code=400, detail="moment proposal event ID mismatch")
    history = _event_moment_history(analysis, event_id)
    latest = history[-1] if history else None
    if payload.expected_revision != (latest.revision if latest else 0):
        raise HTTPException(status_code=409, detail="event moment proposal revision changed")
    proposal = propose_event_moments(
        analysis_id=analysis_id,
        event_id=event_id,
        after=payload.after,
        parent=latest,
        before=latest.after if latest else None,
        reviewer=payload.reviewer,
    )
    _append_event_moment_proposal(analysis, proposal, action="propose")
    session.add(analysis)
    await session.commit()
    return proposal


@router.post("/{analysis_id}/events/{event_id}/moment-proposals/{revision}/apply", response_model=EventMomentProposalRevision)
async def apply_event_moment_route(
    analysis_id: str, event_id: str, revision: int,
    x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"),
    session: AsyncSession = Depends(get_session),
) -> EventMomentProposalRevision:
    await require_parent_pin(session, x_parent_pin)
    analysis = await _load_analysis(analysis_id, session)
    proposal = next((item for item in reversed(_event_moment_history(analysis, event_id)) if item.revision == revision), None)
    if proposal is None or proposal.status == "dismissed":
        raise HTTPException(status_code=400, detail="event moment proposal cannot be applied")
    applied = apply_event_moments(proposal)
    _append_event_moment_proposal(analysis, applied, action="apply")
    session.add(analysis)
    await session.commit()
    return applied


@router.post("/{analysis_id}/events/{event_id}/moment-proposals/{revision}/dismiss", response_model=EventMomentProposalRevision)
async def dismiss_event_moment_route(
    analysis_id: str, event_id: str, revision: int,
    x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"),
    session: AsyncSession = Depends(get_session),
) -> EventMomentProposalRevision:
    await require_parent_pin(session, x_parent_pin)
    analysis = await _load_analysis(analysis_id, session)
    proposal = next((item for item in reversed(_event_moment_history(analysis, event_id)) if item.revision == revision), None)
    if proposal is None:
        raise HTTPException(status_code=404, detail="event moment proposal not found")
    dismissed = dismiss_event_moments(proposal)
    _append_event_moment_proposal(analysis, dismissed, action="dismiss")
    session.add(analysis)
    await session.commit()
    return dismissed


@router.get("/{analysis_id}/source-frames/{source_frame_index}/image")
async def get_analysis_source_frame_image(
    analysis_id: str, source_frame_index: int,
    x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Parent-authorized exact source-frame thumbnail for V2 moment evidence."""
    await require_parent_pin(session, x_parent_pin)
    analysis = await _load_analysis(analysis_id, session)
    path = Path(str(getattr(analysis, "video_path", "")))
    if not path.exists():
        raise HTTPException(status_code=404, detail="source video unavailable")
    try:
        payload = extract_source_frame_bytes(path, source_frame_index)
    except SourceMediaError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(content=payload, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300", "X-Source-Frame-Index": str(source_frame_index)})


@router.get("/{analysis_id}/observations", response_model=DetectionProposalDiagnostics)
async def get_detection_observations(
    analysis_id: str,
    x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"),
    session: AsyncSession = Depends(get_session),
) -> DetectionProposalDiagnostics:
    await require_parent_pin(session, x_parent_pin)
    analysis = await _load_analysis(analysis_id, session)
    # Shadow diagnostics are intentionally detached from legacy/family fields.
    stored = getattr(analysis, "processing_logs", None)
    if isinstance(stored, list):
        for item in reversed(stored):
            if isinstance(item, dict) and isinstance(item.get("detection_proposals"), dict):
                return DetectionProposalDiagnostics.model_validate(item["detection_proposals"])
    return build_proposal_diagnostics(config=resolve_provider_config(), status="not_run")


@router.get("/{analysis_id}/identity", response_model=IdentityTimeline | None)
async def get_identity_timeline(
    analysis_id: str,
    x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"),
    session: AsyncSession = Depends(get_session),
) -> IdentityTimeline | None:
    await require_parent_pin(session, x_parent_pin)
    analysis = await _load_analysis(analysis_id, session)
    stored = getattr(analysis, "processing_logs", None)
    if isinstance(stored, list):
        for item in reversed(stored):
            if isinstance(item, dict) and isinstance(item.get("identity_timeline"), dict):
                return IdentityTimeline.model_validate(item["identity_timeline"])
    return None


@router.get("/{analysis_id}/pose-v2/detail", response_model=PoseDetailResource)
async def get_pose_v2_detail(
    analysis_id: str,
    x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"),
    session: AsyncSession = Depends(get_session),
) -> PoseDetailResource:
    """Return raw V2 joints only from the parent-authorized diagnostic resource."""
    await require_parent_pin(session, x_parent_pin)
    analysis = await _load_analysis(analysis_id, session)
    stored = getattr(analysis, "processing_logs", None)
    if isinstance(stored, list):
        for item in reversed(stored):
            if not isinstance(item, dict) or not isinstance(item.get("pose_v2_detail"), dict):
                continue
            detail = item["pose_v2_detail"]
            observations = tuple(PoseObservation.model_validate(value) for value in detail.get("observations", ()))
            summary = PoseAvailabilitySummary.model_validate(detail.get("summary", {}))
            return build_pose_detail_resource(
                analysis_id=analysis_id,
                source_pipeline_fingerprint=str(detail.get("source_pipeline_fingerprint", "v2:unfingerprinted")),
                observations=observations,
                summary=summary,
                authority="v2",
            )
    raise HTTPException(status_code=404, detail="V2 pose detail is unavailable")


@router.post("/{analysis_id}/identity/anchors/preview", response_model=IdentityRevisionPreview, status_code=status.HTTP_200_OK)
async def preview_identity_anchor_revision(
    analysis_id: str,
    payload: IdentityAnchorRequest,
    x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"),
    session: AsyncSession = Depends(get_session),
) -> IdentityRevisionPreview:
    await require_parent_pin(session, x_parent_pin)
    analysis = await _load_analysis(analysis_id, session)
    stored = getattr(analysis, "processing_logs", None)
    timeline: IdentityTimeline | None = None
    if isinstance(stored, list):
        for item in reversed(stored):
            if isinstance(item, dict) and isinstance(item.get("identity_timeline"), dict):
                timeline = IdentityTimeline.model_validate(item["identity_timeline"])
                break
    anchor = IdentityAnchor(anchor_id=f"{analysis_id}:anchor:{payload.source_frame_index}:{payload.expected_revision + 1}", source_frame_index=payload.source_frame_index, pts_sec=payload.pts_sec, bbox=payload.bbox, annotator=payload.annotator, quality_score=payload.quality_score, revision=payload.expected_revision + 1, provenance="manual_revision", template_fingerprint="pending")
    anchor = anchor.model_copy(update={"template_fingerprint": immutable_template_fingerprint(anchor)})
    invalidated = (payload.invalidated_interval,) if payload.invalidated_interval else ()
    revision = create_anchor_revision(revision=payload.expected_revision + 1, parent_revision=payload.expected_revision, anchor_ids=(anchor.anchor_id,), invalidated_intervals=invalidated, created_by=payload.annotator)
    return IdentityRevisionPreview(analysis_id=analysis_id, current_revision=payload.expected_revision, next_revision=revision.revision, invalidated_intervals=revision.invalidated_intervals, anchor=anchor, identity=timeline)


@router.post("/{analysis_id}/identity/anchors/confirm", response_model=IdentityRevisionPreview, status_code=status.HTTP_201_CREATED)
async def confirm_identity_anchor_revision(
    analysis_id: str,
    payload: IdentityAnchorConfirmRequest,
    x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"),
    session: AsyncSession = Depends(get_session),
) -> IdentityRevisionPreview:
    await require_parent_pin(session, x_parent_pin)
    analysis = await _load_analysis(analysis_id, session)
    stored = getattr(analysis, "processing_logs", None)
    current_revision = payload.expected_revision
    if isinstance(stored, list):
        revisions = [item.get("identity_anchor_revision", {}).get("revision") for item in stored if isinstance(item, dict) and isinstance(item.get("identity_anchor_revision"), dict)]
        if revisions:
            current_revision = max(current_revision, max(int(value) for value in revisions if value is not None))
    if payload.preview_revision != current_revision + 1:
        raise HTTPException(status_code=409, detail={"code": "identity_revision_conflict", "current_revision": current_revision})
    anchor = IdentityAnchor(anchor_id=f"{analysis_id}:anchor:{payload.source_frame_index}:{payload.preview_revision}", source_frame_index=payload.source_frame_index, pts_sec=payload.pts_sec, bbox=payload.bbox, annotator=payload.annotator, quality_score=payload.quality_score, revision=payload.preview_revision, provenance="manual_revision", template_fingerprint="pending")
    anchor = anchor.model_copy(update={"template_fingerprint": immutable_template_fingerprint(anchor)})
    invalidated = (payload.invalidated_interval,) if payload.invalidated_interval else ()
    revision = create_anchor_revision(revision=payload.preview_revision, parent_revision=current_revision, anchor_ids=(anchor.anchor_id,), invalidated_intervals=invalidated, created_by=payload.annotator, provenance="manual_confirmation")
    logs = list(stored) if isinstance(stored, list) else []
    logs.append({"identity_anchor": anchor.model_dump(mode="json"), "identity_anchor_revision": revision.model_dump(mode="json"), "identity_audit": {"action": "confirm", "legacy_mutation": False, "invalidation_scope": list(invalidated)}})
    analysis.processing_logs = logs
    session.add(analysis)
    await session.commit()
    return IdentityRevisionPreview(analysis_id=analysis_id, current_revision=current_revision, next_revision=revision.revision, invalidated_intervals=revision.invalidated_intervals, anchor=anchor, identity=None)


@router.get("/pilot12-detection", response_model=dict[str, Any])
async def get_pilot12_detection_diagnostics(
    x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"),
    session: AsyncSession = Depends(get_session),
    config: RuntimeConfig = Depends(get_runtime_config),
) -> dict[str, Any]:
    await require_parent_pin(session, x_parent_pin)
    fixture = config.runtime_paths["test_data"] / "pilot-12-run-20260801" / "api-analysis-index-live.json"
    if not fixture.exists():
        return {"schema_version": "iteration7-pilot12-detection-evidence.v1", "status": "unavailable", "analysis_count": 0, "candidate_count": 0, "proposal_count": 0, "diagnostic_only": True, "identity_decisions": False}
    return evaluate_pilot12_detection(fixture)


@router.get("/pilot12-event-proposals", response_model=dict[str, Any])
async def get_pilot12_event_proposal_diagnostics(
    x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"),
    session: AsyncSession = Depends(get_session),
    config: RuntimeConfig = Depends(get_runtime_config),
) -> dict[str, Any]:
    await require_parent_pin(session, x_parent_pin)
    root = config.runtime_paths["test_data"] / "pilot-12-run-20260801"
    snapshot = root / "api-analysis-index-live.json"
    labels = root / "snapshot-manifest.json"
    if not snapshot.exists() or not labels.exists():
        return {"schema_version": "iteration10-pilot12-event-proposals.v1", "status": "unavailable", "diagnostic_only": True, "release_claim": False}
    return evaluate_pilot12_event_proposals(snapshot, labels)


@router.get("/pilot14-action-classification", response_model=dict[str, Any])
async def get_pilot14_action_classification(
    x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"),
    session: AsyncSession = Depends(get_session),
    config: RuntimeConfig = Depends(get_runtime_config),
) -> dict[str, Any]:
    await require_parent_pin(session, x_parent_pin)
    root = config.runtime_paths["test_data"] / "pilot-12-run-20260801"
    snapshot = root / "api-analysis-index-live.json"
    labels = root / "golden" / "v2" / "manifest.json"
    private_split = config.runtime_paths["test_data"] / "iteration-11-pilot14" / "split.json"
    if not snapshot.exists() or not labels.exists() or not private_split.exists():
        return {"schema_version": "iteration11-pilot14-profile-classification.v1", "status": "unavailable", "diagnostic_only": True, "release_claim": False}
    try:
        split = json.loads(private_split.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": "iteration11-pilot14-profile-classification.v1", "status": "unavailable", "diagnostic_only": True, "release_claim": False}
    validation = tuple(str(value) for value in split.get("validation_sources", ()) if isinstance(value, str))
    development = tuple(str(value) for value in split.get("development_sources", ()) if isinstance(value, str))
    if not validation or not development:
        return {"schema_version": "iteration11-pilot14-profile-classification.v1", "status": "unavailable", "diagnostic_only": True, "release_claim": False}
    return evaluate_pilot14_action_classification(snapshot, labels, validation_sources=validation, development_sources=development)

# Auxiliary revisions share the existing application gates and parent PIN.
from app.routers.segment_reanchor import router as segment_reanchor_router
router.include_router(segment_reanchor_router)
