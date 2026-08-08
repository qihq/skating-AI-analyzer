from __future__ import annotations

from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.analysis_v2.facts import AnalysisFactV2, AnalysisFactsV2, Authority, Observability
from app.analysis_v2.contracts import EventMomentSet, IdentityTimeline, PoseAvailabilitySummary, PoseDetailResource, PoseObservation, RotationEstimate


class AuthorityMismatchError(ValueError):
    pass


class EventV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    profile: str
    subtype: str | None = None
    state: Literal["confirmed", "ambiguous", "unknown"] = "unknown"
    start_pts: float | None = None
    end_pts: float | None = None
    status: Literal["confirmed", "uncertain", "unobservable"] = "confirmed"
    observability: Observability = "observable"
    pose: PoseAvailabilitySummary | None = None
    candidate_profile_scores: dict[str, float] = Field(default_factory=dict)
    proposal_status: Literal["legacy", "pending_confirmation", "confirmed_window", "ignored", "ordinary_skating", "unknown"] = "legacy"
    tracking_coverage: float | None = Field(default=None, ge=0, le=1)
    pose_coverage: float | None = Field(default=None, ge=0, le=1)
    provenance_fingerprint: str | None = None
    revision: int = Field(default=1, ge=1)
    evidence_summary: dict[str, Any] = Field(default_factory=dict)
    confirmation_task: str | None = None
    definition_version: str = "action-event.v1"
    moments: EventMomentSet | None = None
    moment_definition_version: str | None = None
    moment_completeness: Literal["complete", "incomplete", "ambiguous", "unobservable"] | None = None
    rotation: RotationEstimate | None = None


class ReviewTaskV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str
    authority: Authority
    kind: str
    event_id: str | None = None
    start_pts: float | None = Field(default=None, ge=0)
    end_pts: float | None = Field(default=None, ge=0)
    definition_version: str | None = None
    convention: str | None = None

    @model_validator(mode="after")
    def _ordered_review_interval(self) -> "ReviewTaskV2":
        if self.start_pts is not None and self.end_pts is not None and self.end_pts < self.start_pts:
            raise ValueError("review task end PTS must not precede start PTS")
        return self


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
    pose: PoseAvailabilitySummary | None = None

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
    pose: PoseAvailabilitySummary | dict[str, Any] | None = None,
    event_pose: Mapping[str, PoseAvailabilitySummary | dict[str, Any]] | None = None,
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
    normalized_events_list: list[EventV2] = []
    for event in events:
        normalized = event if isinstance(event, EventV2) else EventV2.model_validate(event)
        if event_pose and normalized.event_id in event_pose:
            detail = event_pose[normalized.event_id]
            normalized = normalized.model_copy(update={"pose": PoseAvailabilitySummary.model_validate(detail) if isinstance(detail, dict) else detail})
        normalized_events_list.append(normalized)
    normalized_events = tuple(normalized_events_list)
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
        pose=PoseAvailabilitySummary.model_validate(pose) if isinstance(pose, dict) else pose,
    )


def present_legacy_record(record: Any) -> AnalysisExperienceV2:
    """Adapt one historical record wholesale; never mutate or merge with V2 evidence."""
    get = record.get if isinstance(record, dict) else lambda key, default=None: getattr(record, key, default)
    analysis_id = str(get("id", "unknown"))
    fingerprint = f"legacy:{get('pipeline_version', 'unknown')}"
    action = str(get("action_type", "unknown"))
    action_lower = action.lower()
    profile_aliases = {
        "jump": ("jump", "跳", "跳跃"),
        "spin": ("spin", "旋转"),
        "step": ("step", "步法"),
        "spiral": ("spiral", "螺旋", "燕式"),
    }
    classified_profile = next(
        (profile for profile, aliases in profile_aliases.items() if any(alias in action_lower or alias in action for alias in aliases)),
        None,
    )
    action_claim_value = classified_profile or action
    events = [
        EventV2(
            event_id=f"{analysis_id}:event:0",
            profile=action,
            state="ambiguous" if classified_profile is not None else "unknown",
        )
    ]
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
            value=action_claim_value,
            authority="legacy",
            source_pipeline_fingerprint=fingerprint,
            definition_version="legacy-action-profile.v1",
            compatibility_group="action-profile/family",
            provenance=("legacy.action_type",),
            # Only deterministic action-family and score claims preserve the
            # legacy automatic-skill behavior. Narrative/report claims remain
            # automation-ineligible.
            permissions={**permissions, "automation": True},
        )
    ]
    report = get("report")
    # User-provided comments and the saved response are first-class, bounded
    # context for chat/coaching.  Keep them as claims at the authority
    # boundary so downstream consumers never need to reach back into the raw
    # ``note`` or ``report`` dictionaries.  They are deliberately excluded
    # from aggregation/comparison/automation because they are not measured
    # technical evidence.
    note_value = get("note")
    if not isinstance(note_value, str) or not note_value.strip():
        note_value = report.get("user_note") if isinstance(report, dict) else None
    if isinstance(note_value, str) and note_value.strip():
        claims.append(
            AnalysisFactV2(
                analysis_id=analysis_id,
                claim_type="user_note",
                value=note_value.strip(),
                authority="legacy",
                source_pipeline_fingerprint=fingerprint,
                definition_version="legacy-user-note.v1",
                compatibility_group="user-note/legacy",
                provenance=("legacy.analysis.note",),
                source_references=("legacy.analysis.note",),
                permissions={**permissions, "aggregation": False, "comparison": False, "coaching": True, "automation": False},
            )
        )
    if isinstance(report, dict):
        response_value = report.get("user_note_response")
        if isinstance(response_value, str) and response_value.strip():
            claims.append(
                AnalysisFactV2(
                    analysis_id=analysis_id,
                    claim_type="user_note_response",
                    value=response_value.strip(),
                    authority="legacy",
                    source_pipeline_fingerprint=fingerprint,
                    definition_version="legacy-user-note-response.v1",
                    compatibility_group="user-note-response/legacy",
                    provenance=("legacy.report.user_note_response",),
                    source_references=("legacy.report.user_note_response",),
                    permissions={**permissions, "aggregation": False, "comparison": False, "coaching": True, "automation": False},
                )
            )
    if isinstance(report, dict):
        quality = str(report.get("data_quality") or "unknown").strip().lower()
        if quality not in {"good", "partial", "poor", "unknown"}:
            quality = "unknown"
        claims.append(
            AnalysisFactV2(
                analysis_id=analysis_id,
                event_id=f"{analysis_id}:event:0",
                claim_type="data_quality",
                value=quality,
                authority="legacy",
                source_pipeline_fingerprint=fingerprint,
                definition_version="legacy-data-quality.v1",
                compatibility_group="data-quality/legacy",
                status="confirmed",
                provenance=("legacy.report.data_quality",),
                permissions={**permissions, "aggregation": quality != "poor", "comparison": quality != "poor", "coaching": quality != "poor", "automation": False},
            )
        )
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
    # Preserve bounded action naming/confirmation context for follow-up chat
    # and correction proposals.  These are family-safe semantic claims, not
    # raw provider payloads, and remain in the legacy authority projection.
    action_subtype = get("action_subtype")
    action_confirmation = report.get("action_confirmation") if isinstance(report, dict) else None
    if not isinstance(action_confirmation, dict):
        motion_scores = get("frame_motion_scores")
        temporal = motion_scores.get("video_temporal") if isinstance(motion_scores, dict) else None
        action_confirmation = temporal.get("action_confirmation") if isinstance(temporal, dict) else None
    if isinstance(action_subtype, str) and action_subtype.strip():
        claims.append(
            AnalysisFactV2(
                analysis_id=analysis_id,
                event_id=f"{analysis_id}:event:0",
                claim_type="action_label",
                value=action_subtype.strip(),
                authority="legacy",
                source_pipeline_fingerprint=fingerprint,
                definition_version="legacy-action-label.v1",
                compatibility_group="action-label/legacy",
                provenance=("legacy.action_subtype",),
                permissions={**permissions, "aggregation": False, "comparison": False, "coaching": True, "automation": False},
            )
        )
    if isinstance(action_confirmation, dict) and action_confirmation:
        claims.append(
            AnalysisFactV2(
                analysis_id=analysis_id,
                event_id=f"{analysis_id}:event:0",
                claim_type="action_confirmation",
                value={key: action_confirmation.get(key) for key in ("action_family", "confirmed_action", "confidence", "notes") if action_confirmation.get(key) is not None},
                authority="legacy",
                source_pipeline_fingerprint=fingerprint,
                definition_version="legacy-action-confirmation.v1",
                compatibility_group="action-confirmation/legacy",
                status="uncertain" if float(action_confirmation.get("confidence") or 0) < 0.8 else "confirmed",
                confidence=float(action_confirmation.get("confidence")) if isinstance(action_confirmation.get("confidence"), (int, float)) else None,
                provenance=("legacy.report.action_confirmation",),
                permissions={**permissions, "aggregation": False, "comparison": False, "coaching": True, "automation": False},
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
                permissions={**permissions, "automation": True},
            )
        )
    # Preserve the bounded legacy jump metrics as family-safe claims.  The
    # monthly/growth consumers can therefore use the same authority adapter
    # without reaching back into ``bio_data`` themselves.  Unknown metrics or
    # non-numeric values are intentionally ignored.
    bio_data = get("bio_data")
    if isinstance(bio_data, dict):
        metrics = bio_data.get("jump_metrics")
        metrics_status = str(bio_data.get("jump_metrics_status") or "").strip().lower()
        if isinstance(metrics, dict) and metrics_status in {"ok", "valid", "good"}:
            metric_units = {
                "air_time_seconds": "s",
                "estimated_height_cm": "cm",
                "takeoff_speed_mps": "m/s",
                "rotation_rps": "rps",
                "estimated_rotations": "rotations",
            }
            subtype = str(get("action_subtype", "") or "").strip() or "unknown"
            for metric, value in sorted(metrics.items()):
                if metric not in metric_units or not isinstance(value, (int, float)) or isinstance(value, bool):
                    continue
                claims.append(
                    AnalysisFactV2(
                        analysis_id=analysis_id,
                        event_id=f"{analysis_id}:event:0",
                        claim_type="metric",
                        value=float(value),
                        authority="legacy",
                        source_pipeline_fingerprint=fingerprint,
                        definition_version="legacy-jump-metric.v1",
                        compatibility_group=f"metric/{subtype}/{metric}/{metric_units[metric]}",
                        unit=metric_units[metric],
                        confidence=1.0,
                        provenance=("legacy.bio_data.jump_metrics",),
                        source_references=(f"metric:{metric}", f"action_subtype:{subtype}"),
                        permissions={**permissions, "coaching": True, "automation": False},
                    )
                )

    # Historical records are adapted wholesale once at the authority boundary.
    # Downstream services may therefore use these family-safe claims without
    # reaching into legacy report/biomechanics dictionaries themselves.
    issue_permissions = {**permissions, "automation": False}
    if isinstance(report, dict):
        issues = report.get("issues") if isinstance(report.get("issues"), list) else []
        for index, issue in enumerate(issues[:12]):
            if not isinstance(issue, dict):
                continue
            description = str(issue.get("description") or "").strip()
            category = str(issue.get("category") or "").strip()
            if not (description or category):
                continue
            claims.append(
                AnalysisFactV2(
                    analysis_id=analysis_id,
                    event_id=f"{analysis_id}:event:0",
                    claim_type="technical_issue",
                    value={
                        "category": category or "general",
                        "description": description,
                        "severity": str(issue.get("severity") or "low"),
                        "phase": issue.get("phase"),
                    },
                    authority="legacy",
                    source_pipeline_fingerprint=fingerprint,
                    definition_version="legacy-report-issue.v1",
                    compatibility_group="technical-issue/legacy",
                    provenance=("legacy.report.issues",),
                    permissions=issue_permissions,
                    source_references=(f"legacy-report-issue:{index}",),
                )
            )
    # Keep partial/selected semantic frame candidates and bounded alternate
    # action evidence available to chat.  They are explicitly candidates, not
    # confirmed moments or technical measurements.
    motion_scores = get("frame_motion_scores")
    resolved = motion_scores.get("resolved_keyframes") if isinstance(motion_scores, dict) else None
    if isinstance(resolved, dict):
        for field, value in (("selected", resolved.get("selected")), ("partial", resolved.get("partial_selected"))):
            if isinstance(value, list) and value:
                claims.append(
                    AnalysisFactV2(
                        analysis_id=analysis_id,
                        event_id=f"{analysis_id}:event:0",
                        claim_type="key_moment_candidate",
                        value={"kind": field, "items": value[:8]},
                        authority="legacy",
                        source_pipeline_fingerprint=fingerprint,
                        definition_version="legacy-key-moment-candidate.v1",
                        compatibility_group="key-moment-candidate/legacy",
                        status="uncertain",
                        observability="partially_observable",
                        provenance=("legacy.frame_motion_scores.resolved_keyframes",),
                        permissions={**permissions, "aggregation": False, "comparison": False, "coaching": True, "automation": False},
                    )
                )
    cross_validation = get("cross_validation")
    path_b_evidence = cross_validation.get("path_b_evidence") if isinstance(cross_validation, dict) else None
    if isinstance(path_b_evidence, dict) and path_b_evidence:
        claims.append(
            AnalysisFactV2(
                analysis_id=analysis_id,
                event_id=f"{analysis_id}:event:0",
                claim_type="action_candidate",
                value=path_b_evidence,
                authority="legacy",
                source_pipeline_fingerprint=fingerprint,
                definition_version="legacy-action-candidate.v1",
                compatibility_group="action-candidate/legacy",
                status="uncertain",
                observability="partially_observable",
                provenance=("legacy.cross_validation.path_b_evidence",),
                permissions={**permissions, "aggregation": False, "comparison": False, "coaching": True, "automation": False},
            )
        )
    if isinstance(report, dict):
        focus = str(report.get("training_focus") or "").strip()
        if focus:
            claims.append(
                AnalysisFactV2(
                    analysis_id=analysis_id,
                    event_id=f"{analysis_id}:event:0",
                    claim_type="training_focus",
                    value=focus,
                    authority="legacy",
                    source_pipeline_fingerprint=fingerprint,
                    definition_version="legacy-training-focus.v1",
                    compatibility_group="training-focus/legacy",
                    provenance=("legacy.report.training_focus",),
                    permissions={**permissions, "aggregation": True, "coaching": True},
                )
            )
    quote = str(get("highlight_quote", "") or "").strip()
    if quote:
        claims.append(
            AnalysisFactV2(
                analysis_id=analysis_id,
                event_id=f"{analysis_id}:event:0",
                claim_type="quote",
                value={"text": quote, "speaker": str(get("quote_speaker", "") or "").strip() or None},
                authority="legacy",
                source_pipeline_fingerprint=fingerprint,
                definition_version="legacy-quote.v1",
                compatibility_group="quote/legacy",
                provenance=("legacy.highlight_quote",),
                source_references=(f"legacy-quote:{analysis_id}",),
                permissions={**permissions, "aggregation": True, "coaching": False, "automation": False},
            )
        )
    bio_data = get("bio_data")
    if isinstance(bio_data, dict):
        key_frames = bio_data.get("key_frames") if isinstance(bio_data.get("key_frames"), dict) else {}
        timestamps = bio_data.get("key_frame_timestamps") if isinstance(bio_data.get("key_frame_timestamps"), dict) else {}
        for phase in ("T", "A", "L"):
            frame = key_frames.get(phase)
            if frame in (None, ""):
                continue
            claims.append(
                AnalysisFactV2(
                    analysis_id=analysis_id,
                    event_id=f"{analysis_id}:event:0",
                    claim_type="key_moment",
                    value={"phase": phase, "frame": frame, "timestamp": timestamps.get(phase)},
                    authority="legacy",
                    source_pipeline_fingerprint=fingerprint,
                    definition_version="legacy-key-moment.v1",
                    compatibility_group="key-moment/legacy",
                    provenance=("legacy.bio_data.key_frames",),
                    source_references=(f"legacy-keyframe:{phase}",),
                    permissions={**permissions, "aggregation": False, "comparison": True, "coaching": True},
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


def present_analysis_experience(record: Any, *, pipeline_mode: Literal["legacy", "shadow", "v2"] = "legacy", source_pipeline_fingerprint: str | None = None, source_timeline: dict[str, Any] | None = None, identity: IdentityTimeline | dict[str, Any] | None = None, pose: PoseAvailabilitySummary | dict[str, Any] | None = None) -> AnalysisExperienceV2:
    if pipeline_mode == "legacy":
        # Ordinary routes use the persisted family authority when an Iteration
        # 14 envelope exists.  The compatibility slots remain available only
        # to legacy records and parent diagnostics; they must not be mixed
        # into a V2 experience.
        stored = _persisted_v2_facts(record)
        if stored is not None:
            fingerprint = str(source_pipeline_fingerprint or next(
                (fact.source_pipeline_fingerprint for fact in stored.facts if fact.source_pipeline_fingerprint),
                "v2:empty",
            ))
            events: list[EventV2] = []
            event_ids = tuple(dict.fromkeys(fact.event_id for fact in stored.facts if fact.event_id))
            for event_id in event_ids:
                event_facts = [fact for fact in stored.facts if fact.event_id == event_id]
                profile_fact = next((fact for fact in event_facts if fact.claim_type in {"action_profile", "action_family", "action_family_support"}), None)
                window_fact = next((fact for fact in event_facts if fact.claim_type == "event_window"), None)
                candidate_fact = next((fact for fact in event_facts if fact.claim_type == "action_candidate"), None)
                profile = str(profile_fact.value) if profile_fact is not None and isinstance(profile_fact.value, str) else "unknown"
                if profile not in {"jump", "spin", "step", "spiral"}:
                    profile = "unknown"
                # Event localization and family classification are separate
                # claims.  A confirmed profile must not make a pending or
                # conflicting event window look settled in the family UI.
                if profile_fact is None:
                    status = (
                        "unobservable"
                        if (window_fact is None and candidate_fact is None)
                        or (window_fact is not None and window_fact.status == "unobservable")
                        else "uncertain"
                    )
                elif profile_fact.status == "unobservable":
                    status = "unobservable"
                else:
                    status = "confirmed" if profile_fact.status == "confirmed" and profile_fact.observability == "observable" else "uncertain"
                if any(fact.status == "unobservable" or fact.observability == "unobservable" for fact in event_facts):
                    observability = "unobservable"
                elif any(fact.observability != "observable" for fact in event_facts):
                    observability = "partially_observable"
                else:
                    observability = "observable"
                if any(fact.status != "confirmed" or fact.conflicts for fact in event_facts) and status == "confirmed":
                    status = "uncertain"
                if observability == "unobservable" and profile_fact is None:
                    status = "unobservable"
                window_value = window_fact.value if window_fact is not None and isinstance(window_fact.value, Mapping) else {}
                candidate_value = candidate_fact.value if candidate_fact is not None and isinstance(candidate_fact.value, Mapping) else {}
                raw_scores = candidate_value.get("candidate_profile_scores", window_value.get("candidate_profile_scores", {}))
                candidate_scores = {
                    str(key): max(0.0, min(1.0, float(value)))
                    for key, value in (raw_scores.items() if isinstance(raw_scores, Mapping) else ())
                    if isinstance(value, (int, float)) and not isinstance(value, bool)
                }
                proposal_status = str(window_value.get("proposal_status") or "legacy")
                if proposal_status not in {"legacy", "pending_confirmation", "confirmed_window", "ignored", "ordinary_skating", "unknown"}:
                    proposal_status = "unknown"
                start_pts = window_value.get("start_pts_sec", window_value.get("start_pts"))
                end_pts = window_value.get("end_pts_sec", window_value.get("end_pts"))
                try:
                    start_pts = float(start_pts) if start_pts is not None else None
                    end_pts = float(end_pts) if end_pts is not None else None
                except (TypeError, ValueError):
                    start_pts, end_pts = None, None
                if start_pts is not None and end_pts is not None and end_pts < start_pts:
                    start_pts, end_pts = end_pts, start_pts
                review_fact = next((fact for fact in event_facts if fact.status != "confirmed" or fact.observability != "observable" or fact.conflicts), None)
                review_task = None
                if review_fact is not None and status != "confirmed":
                    review_task = f"{event_id}:review:{review_fact.claim_type}"
                events.append(EventV2(
                    event_id=str(event_id),
                    profile=profile,
                    # ``ambiguous`` is only valid when a family candidate is
                    # present.  An event window/candidate without a supported
                    # family must remain ``unknown`` so the frontend contract
                    # cannot accidentally render an unclassified event.
                    state="confirmed" if status == "confirmed" and profile != "unknown" else "ambiguous" if profile != "unknown" and status != "unobservable" else "unknown",
                    start_pts=start_pts,
                    end_pts=end_pts,
                    status=status,
                    observability=observability,
                    candidate_profile_scores=candidate_scores,
                    proposal_status=proposal_status,  # type: ignore[arg-type]
                    provenance_fingerprint=fingerprint,
                    evidence_summary={
                        "fact_count": len(event_facts),
                        "conflict_count": sum(1 for fact in event_facts if fact.conflicts),
                        "proposal_status": proposal_status,
                    },
                    confirmation_task=review_task or (f"{event_id}:review" if status != "confirmed" else None),
                ))
            tasks = tuple(
                ReviewTaskV2(
                    task_id=f"{fact.event_id or stored.analysis_id}:review:{fact.claim_type}",
                    authority="v2",
                    kind="review_conflict" if fact.conflicts else "review_observability",
                    event_id=fact.event_id,
                    definition_version=fact.definition_version,
                    convention=fact.convention,
                )
                for fact in stored.facts
                if fact.status != "confirmed" or fact.observability != "observable" or fact.conflicts
            )
            return build_experience_v2(
                analysis_id=stored.analysis_id,
                pipeline_mode="v2",
                source_pipeline_fingerprint=fingerprint,
                events=events,
                claims=stored.facts,
                review_tasks=tasks,
                source_timeline=source_timeline,
                identity=identity,
                pose=pose,
            )
        rendered = present_legacy_record(record)
        updates = {}
        if source_timeline is not None:
            updates["source_timeline"] = source_timeline
        if pose is not None:
            updates["pose"] = PoseAvailabilitySummary.model_validate(pose) if isinstance(pose, dict) else pose
        return rendered.model_copy(update=updates) if updates else rendered
    analysis_id = str(record.get("id") if isinstance(record, dict) else getattr(record, "id"))
    get = record.get if isinstance(record, dict) else lambda key, default=None: getattr(record, key, default)
    return build_experience_v2(
        analysis_id=analysis_id,
        pipeline_mode=pipeline_mode,
        source_pipeline_fingerprint=source_pipeline_fingerprint or f"{pipeline_mode}:unfingerprinted",
        events=(),
        claims=(),
        identity=identity,
        pose=pose,
        source_timeline=source_timeline if source_timeline is not None else (get("source_timeline") if isinstance(get("source_timeline"), dict) else None),
    )


def _persisted_v2_facts(record: Any) -> AnalysisFactsV2 | None:
    get = record.get if isinstance(record, dict) else lambda key, default=None: getattr(record, key, default)
    if str(get("facts_authority", "") or "").strip().lower() != "v2":
        return None
    analysis_id = str(get("id", "unknown"))
    fallback_fingerprint = str(get("source_pipeline_fingerprint", "") or "v2:invalid-envelope")
    payload = get("analysis_facts")
    if not isinstance(payload, Mapping):
        return AnalysisFactsV2(
            analysis_id=analysis_id,
            authority="v2",
            facts=(AnalysisFactV2(
                analysis_id=analysis_id,
                claim_type="authority_unavailable",
                authority="v2",
                source_pipeline_fingerprint=fallback_fingerprint,
                definition_version="authority-unavailable.v1",
                status="unobservable",
                observability="unobservable",
            ),),
        )
    raw = dict(payload)
    raw.pop("schema_version", None)
    try:
        facts = AnalysisFactsV2.model_validate(raw)
    except Exception:  # noqa: BLE001
        return AnalysisFactsV2(
            analysis_id=analysis_id,
            authority="v2",
            facts=(AnalysisFactV2(
                analysis_id=analysis_id,
                claim_type="authority_unavailable",
                authority="v2",
                source_pipeline_fingerprint=fallback_fingerprint,
                definition_version="authority-unavailable.v1",
                status="unobservable",
                observability="unobservable",
            ),),
        )
    declared_hash = get("source_fact_hash")
    if declared_hash and declared_hash != facts.source_fact_hash:
        return AnalysisFactsV2(
            analysis_id=analysis_id,
            authority="v2",
            facts=(AnalysisFactV2(
                analysis_id=analysis_id,
                claim_type="authority_unavailable",
                authority="v2",
                source_pipeline_fingerprint=fallback_fingerprint,
                definition_version="authority-hash-mismatch.v1",
                status="unobservable",
                observability="unobservable",
            ),),
        )
    return facts if facts.authority == "v2" and (not analysis_id or facts.analysis_id == analysis_id) else AnalysisFactsV2(
        analysis_id=analysis_id,
        authority="v2",
        facts=(AnalysisFactV2(
            analysis_id=analysis_id,
            claim_type="authority_unavailable",
            authority="v2",
            source_pipeline_fingerprint=fallback_fingerprint,
            definition_version="authority-mismatch.v1",
            status="unobservable",
            observability="unobservable",
        ),),
    )


def build_pose_detail_resource(
    *,
    analysis_id: str,
    source_pipeline_fingerprint: str,
    observations: Sequence[PoseObservation],
    summary: PoseAvailabilitySummary,
    authority: Authority = "v2",
) -> PoseDetailResource:
    """Parent-authorized raw joint detail; ordinary experience only carries summary."""
    return PoseDetailResource(
        analysis_id=analysis_id,
        authority=authority,
        diagnostic_only=True,
        source_pipeline_fingerprint=source_pipeline_fingerprint,
        summary=summary,
        observations=tuple(observations),
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
