from __future__ import annotations

from typing import Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.analysis_v2.facts import AnalysisFactV2, AnalysisFactsV2, Authority, Observability
from app.analysis_v2.contracts import IdentityTimeline


class AuthorityMismatchError(ValueError):
    pass


class EventV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    profile: str
    start_pts: float | None = None
    end_pts: float | None = None
    status: Literal["confirmed", "uncertain", "unobservable"] = "confirmed"
    observability: Observability = "observable"


class ReviewTaskV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str
    authority: Authority
    kind: str
    event_id: str | None = None


class AnalysisExperienceV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["analysis-experience.v2"] = "analysis-experience.v2"
    analysis_id: str
    authority: Authority
    pipeline_mode: Literal["legacy", "shadow", "v2"]
    source_pipeline_fingerprint: str
    diagnostic_only: bool = False
    family_usable: bool = True
    events: tuple[EventV2, ...] = ()
    claims: tuple[AnalysisFactV2, ...] = ()
    review_tasks: tuple[ReviewTaskV2, ...] = ()
    source_timeline: dict[str, Any] | None = None
    identity: IdentityTimeline | None = None

    def __init__(self, **data: Any) -> None:
        authority = data.get("authority")
        for claim in data.get("claims") or ():
            claim_authority = claim.authority if isinstance(claim, AnalysisFactV2) else claim.get("authority")
            if authority is not None and claim_authority != authority:
                raise AuthorityMismatchError("claims must use the experience authority")
        for task in data.get("review_tasks") or ():
            task_authority = task.authority if isinstance(task, ReviewTaskV2) else task.get("authority")
            if authority is not None and task_authority != authority:
                raise AuthorityMismatchError("review tasks must use the experience authority")
        super().__init__(**data)

    @model_validator(mode="after")
    def _single_authority(self) -> "AnalysisExperienceV2":
        if any(claim.authority != self.authority for claim in self.claims):
            raise AuthorityMismatchError("experience claims must use its rendering authority")
        if any(task.authority != self.authority for task in self.review_tasks):
            raise AuthorityMismatchError("review tasks must use its rendering authority")
        if self.pipeline_mode == "shadow" and (self.authority != "legacy" or not self.diagnostic_only or self.family_usable):
            raise AuthorityMismatchError("shadow family experience must remain legacy-authoritative and diagnostic-only")
        return self


def _coerce_claims(claims: Sequence[AnalysisFactV2 | dict[str, Any]], *, analysis_id: str, authority: Authority, fingerprint: str) -> list[AnalysisFactV2]:
    result: list[AnalysisFactV2] = []
    for claim in claims:
        item = claim if isinstance(claim, AnalysisFactV2) else AnalysisFactV2.model_validate(claim)
        if item.analysis_id != analysis_id or item.authority != authority:
            raise AuthorityMismatchError("all claims must use the experience authority")
        if item.source_pipeline_fingerprint != fingerprint:
            raise AuthorityMismatchError("all claims must use the experience fingerprint")
        result.append(item)
    return result


def build_experience_v2(
    *,
    analysis_id: str,
    pipeline_mode: Literal["legacy", "shadow", "v2"],
    source_pipeline_fingerprint: str,
    events: Sequence[EventV2 | dict[str, Any]],
    claims: Sequence[AnalysisFactV2 | dict[str, Any]],
    review_tasks: Sequence[ReviewTaskV2 | dict[str, Any]] = (),
    requested_claim_types: Sequence[str] = (),
    source_timeline: dict[str, Any] | None = None,
    identity: IdentityTimeline | dict[str, Any] | None = None,
) -> AnalysisExperienceV2:
    authority: Authority = "legacy" if pipeline_mode in ("legacy", "shadow") else "v2"
    if pipeline_mode == "shadow":
        # Shadow evidence is exposed only through the parent diagnostic surface;
        # the ordinary experience remains a complete legacy-authoritative read model.
        claims = tuple(claim for claim in claims if (claim.authority if isinstance(claim, AnalysisFactV2) else claim.get("authority")) == "legacy")
    normalized_claims = _coerce_claims(claims, analysis_id=analysis_id, authority=authority, fingerprint=source_pipeline_fingerprint)
    if pipeline_mode == "v2":
        present = {claim.claim_type for claim in normalized_claims}
        for claim_type in requested_claim_types:
            if claim_type not in present:
                normalized_claims.append(
                    AnalysisFactV2(
                        analysis_id=analysis_id,
                        claim_type=claim_type,
                        authority="v2",
                        source_pipeline_fingerprint=source_pipeline_fingerprint,
                        definition_version="unavailable.v1",
                        status="unobservable",
                        observability="unobservable",
                    )
                )
    normalized_events = tuple(event if isinstance(event, EventV2) else EventV2.model_validate(event) for event in events)
    normalized_tasks = tuple(task if isinstance(task, ReviewTaskV2) else ReviewTaskV2.model_validate(task) for task in review_tasks)
    if pipeline_mode == "shadow":
        normalized_tasks = tuple(task for task in normalized_tasks if task.authority == "legacy")
    return AnalysisExperienceV2(
        analysis_id=analysis_id,
        authority=authority,
        pipeline_mode=pipeline_mode,
        source_pipeline_fingerprint=source_pipeline_fingerprint,
        diagnostic_only=pipeline_mode == "shadow",
        family_usable=pipeline_mode != "shadow",
        events=normalized_events,
        claims=tuple(normalized_claims),
        review_tasks=normalized_tasks,
        source_timeline=source_timeline,
        identity=IdentityTimeline.model_validate(identity) if isinstance(identity, dict) else identity,
    )


def present_legacy_record(record: Any) -> AnalysisExperienceV2:
    """Adapt one historical record wholesale; never mutate or merge with V2 evidence."""
    get = record.get if isinstance(record, dict) else lambda key, default=None: getattr(record, key, default)
    analysis_id = str(get("id", "unknown"))
    fingerprint = f"legacy:{get('pipeline_version', 'unknown')}"
    action = str(get("action_type", "unknown"))
    events = [EventV2(event_id=f"{analysis_id}:event:0", profile=action)]
    permissions = {
        "family_display": True,
        "aggregation": True,
        "comparison": True,
        "coaching": True,
        "correction": True,
        "automation": False,
        "share": True,
        "export": True,
    }
    claims: list[AnalysisFactV2] = [
        AnalysisFactV2(
            analysis_id=analysis_id,
            event_id=f"{analysis_id}:event:0",
            claim_type="action_profile",
            value=action,
            authority="legacy",
            source_pipeline_fingerprint=fingerprint,
            definition_version="legacy-action-profile.v1",
            compatibility_group="action-profile/family",
            provenance=("legacy.action_type",),
            permissions=permissions,
        )
    ]
    report = get("report")
    if isinstance(report, dict) and report.get("summary") is not None:
        claims.append(
            AnalysisFactV2(
                analysis_id=analysis_id,
                claim_type="report_summary",
                value=report["summary"],
                authority="legacy",
                source_pipeline_fingerprint=fingerprint,
                definition_version="legacy-report.v1",
                compatibility_group="report-summary/legacy",
                provenance=("legacy.report.summary",),
                permissions=permissions,
            )
        )
    subscores = report.get("subscores") if isinstance(report, dict) else None
    force_score = get("force_score")
    if force_score is None and isinstance(subscores, dict):
        force_score = subscores.get("force")
    if isinstance(force_score, (int, float)):
        claims.append(
            AnalysisFactV2(
                analysis_id=analysis_id,
                event_id=f"{analysis_id}:event:0",
                claim_type="force_score",
                value=float(force_score),
                authority="legacy",
                source_pipeline_fingerprint=fingerprint,
                definition_version="legacy-force-score.v1",
                compatibility_group="force-score/legacy-100",
                unit="score_100",
                confidence=1.0,
                provenance=("legacy.force_score",),
                permissions=permissions,
            )
        )
    return build_experience_v2(
        analysis_id=analysis_id,
        pipeline_mode="legacy",
        source_pipeline_fingerprint=fingerprint,
        events=events,
        claims=claims,
        source_timeline=get("source_timeline") if isinstance(get("source_timeline"), dict) else None,
    )


def present_analysis_experience(record: Any, *, pipeline_mode: Literal["legacy", "shadow", "v2"] = "legacy", source_pipeline_fingerprint: str | None = None, source_timeline: dict[str, Any] | None = None, identity: IdentityTimeline | dict[str, Any] | None = None) -> AnalysisExperienceV2:
    if pipeline_mode == "legacy":
        rendered = present_legacy_record(record)
        return rendered.model_copy(update={"source_timeline": source_timeline}) if source_timeline is not None else rendered
    analysis_id = str(record.get("id") if isinstance(record, dict) else getattr(record, "id"))
    get = record.get if isinstance(record, dict) else lambda key, default=None: getattr(record, key, default)
    return build_experience_v2(
        analysis_id=analysis_id,
        pipeline_mode=pipeline_mode,
        source_pipeline_fingerprint=source_pipeline_fingerprint or f"{pipeline_mode}:unfingerprinted",
        events=(),
        claims=(),
        identity=identity,
        source_timeline=source_timeline if source_timeline is not None else (get("source_timeline") if isinstance(get("source_timeline"), dict) else None),
    )


def project_analysis_facts(
    record: Any,
    *,
    pipeline_mode: Literal["legacy", "shadow", "v2"] = "legacy",
    source_pipeline_fingerprint: str | None = None,
) -> AnalysisFactsV2:
    experience = present_analysis_experience(
        record,
        pipeline_mode=pipeline_mode,
        source_pipeline_fingerprint=source_pipeline_fingerprint,
    )
    return AnalysisFactsV2(
        analysis_id=experience.analysis_id,
        authority=experience.authority,
        facts=experience.claims,
    )
