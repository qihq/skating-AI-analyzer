"""Adapters that turn bounded Path A/Path B and deterministic output into claims.

This module is intentionally the only place where the legacy biomechanics/pose
payloads are translated into the V2 claim vocabulary.  Downstream consumers
must use the persisted ``AnalysisFactsV2`` envelope instead of these raw
payloads.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.analysis_v2.contracts import EvidenceClaim
from app.analysis_v2.event_proposals import ProposalEvidenceSample, generate_event_proposals


def _event_scope_from_mapping(value: Mapping[str, Any], *, analysis_id: str) -> dict[str, Any] | None:
    """Normalize a bounded event proposal without classifying it."""

    event_id = str(value.get("event_id") or "").strip()
    if not event_id:
        return None
    start = value.get("start_pts_sec", value.get("start_pts"))
    end = value.get("end_pts_sec", value.get("end_pts"))
    try:
        start_value = max(0.0, float(start))
        end_value = max(0.0, float(end))
    except (TypeError, ValueError):
        return None
    if end_value <= start_value:
        return None
    scores = value.get("candidate_profile_scores")
    normalized_scores = {
        str(key): max(0.0, min(1.0, float(raw)))
        for key, raw in (scores.items() if isinstance(scores, Mapping) else ())
        if isinstance(raw, (int, float)) and not isinstance(raw, bool)
    }
    return {
        "analysis_id": analysis_id,
        "event_id": event_id,
        # Preserve the proposal identifier when an ordinary single-event
        # envelope is mapped onto the canonical ``analysis:event:0`` ID.  The
        # canonical ID keeps deterministic/Path A/Path B claims in one event;
        # this field keeps the source proposal lineage auditable.
        "proposal_event_id": str(value.get("proposal_event_id") or event_id),
        "start_pts_sec": round(start_value, 6),
        "end_pts_sec": round(end_value, 6),
        "candidate_profile_scores": normalized_scores,
        "status": str(value.get("status") or "pending_confirmation"),
        "observability": str(value.get("observability") or "unobservable"),
        "provenance_fingerprint": str(value.get("provenance_fingerprint") or ""),
    }


def normalize_event_scopes(
    scopes: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
    *,
    analysis_id: str,
) -> tuple[dict[str, Any], ...]:
    """Return stable, source-ordered proposal scopes.

    This helper deliberately consumes only persisted proposal metadata.  It
    never infers an action family and it returns an empty tuple when the
    proposal envelope is absent or malformed.
    """

    raw_items: Sequence[Any]
    if isinstance(scopes, Mapping):
        proposals = scopes.get("proposals")
        raw_items = proposals if isinstance(proposals, Sequence) and not isinstance(proposals, (str, bytes, bytearray)) else (scopes,)
    elif isinstance(scopes, Sequence) and not isinstance(scopes, (str, bytes, bytearray)):
        raw_items = scopes
    else:
        raw_items = ()
    normalized = [
        item
        for raw in raw_items
        if isinstance(raw, Mapping)
        for item in [_event_scope_from_mapping(raw, analysis_id=analysis_id)]
        if item is not None
    ]
    return tuple(sorted({item["event_id"]: item for item in normalized}.values(), key=lambda item: (item["start_pts_sec"], item["end_pts_sec"], item["event_id"])))


def canonicalize_single_event_scope(
    scopes: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
    *,
    analysis_id: str,
    canonical_event_id: str | None,
) -> tuple[dict[str, Any], ...]:
    """Map the sole proposal to the ordinary canonical event ID.

    Event proposals use a content-derived ``evt-*`` ID, while the historical
    one-event fusion path uses ``analysis:event:0``.  If exactly one proposal
    exists, retaining both IDs would make the family presenter render a phantom
    second event.  Preserve the proposal ID separately for provenance and only
    change the semantic scope ID.
    """

    normalized = normalize_event_scopes(scopes, analysis_id=analysis_id)
    canonical = str(canonical_event_id or "").strip()
    if len(normalized) != 1 or not canonical:
        return normalized
    item = dict(normalized[0])
    item["proposal_event_id"] = str(item.get("proposal_event_id") or item["event_id"])
    item["event_id"] = canonical
    return (item,)


def _claim_source_pts_interval(claim: EvidenceClaim) -> tuple[float, float] | None:
    """Read an exact source-PTS point/interval from a bounded claim."""

    # A provider/model claim is not a timing authority.  Only deterministic or
    # source-linked measurement producers may contribute an interval for event
    # localization; Path A/B prose remains whole-analysis unless it is paired
    # with one of these explicit sources upstream.
    timing_sources = {
        "deterministic", "deterministic_measurement", "key_moment",
        "rotation_estimator", "action_classifier", "identity",
    }
    if not timing_sources.intersection(claim.sources):
        return None
    value = claim.value
    if isinstance(value, Mapping):
        starts = (
            value.get("start_pts_sec"), value.get("start_pts"),
            value.get("pts_sec"), value.get("source_pts"), value.get("timestamp"),
        )
        ends = (
            value.get("end_pts_sec"), value.get("end_pts"),
            value.get("pts_sec"), value.get("source_pts"), value.get("timestamp"),
        )
        start = next((item for item in starts if isinstance(item, (int, float)) and not isinstance(item, bool)), None)
        end = next((item for item in ends if isinstance(item, (int, float)) and not isinstance(item, bool)), start)
        if start is not None and end is not None:
            return float(start), float(end)
    refs = " ".join(str(ref) for ref in claim.source_references)
    match = re.search(r"(?:pts(?:_sec)?|source_pts|timestamp|time)[:=_-]([0-9]+(?:\.[0-9]+)?)", refs, re.IGNORECASE)
    if match:
        point = float(match.group(1))
        return point, point
    return None


def scope_claims_to_events(
    claims: Sequence[EvidenceClaim],
    *,
    scopes: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
    analysis_id: str,
) -> tuple[EvidenceClaim, ...]:
    """Attach event IDs only when a claim's exact source interval is unique.

    Path A intentionally has no source timing, and aggregate measurements may
    span the whole analysis; those claims remain whole-analysis.  A point or
    interval wholly contained by exactly one deterministic proposal can be
    safely scoped, which enables event-specific key moments without guessing.
    """

    normalized = normalize_event_scopes(scopes, analysis_id=analysis_id)
    if not normalized:
        return tuple(claims)
    output: list[EvidenceClaim] = []
    for claim in claims:
        if claim.event_id is not None:
            output.append(claim)
            continue
        interval = _claim_source_pts_interval(claim)
        if interval is None:
            output.append(claim)
            continue
        start, end = interval
        matches = [
            scope for scope in normalized
            if start >= float(scope["start_pts_sec"]) and end <= float(scope["end_pts_sec"])
        ]
        if len(matches) == 1:
            output.append(claim.model_copy(update={"event_id": str(matches[0]["event_id"])}))
        else:
            output.append(claim)
    return tuple(output)


def event_scopes_from_analysis(record: Any, motion_scores: Mapping[str, Any] | None = None) -> tuple[dict[str, Any], ...]:
    """Read persisted proposal scopes for the ordinary V2 fusion boundary."""

    if isinstance(record, Mapping):
        analysis_id = str(record.get("id") or "unknown")
    else:
        analysis_id = str(getattr(record, "id", "unknown") or "unknown")
    candidates: list[Any] = []
    motion = motion_scores if isinstance(motion_scores, Mapping) else None
    if motion is not None:
        candidates.append(motion.get("event_proposals"))
    logs = record.get("processing_logs") if isinstance(record, Mapping) else getattr(record, "processing_logs", None)
    if isinstance(logs, Sequence):
        for entry in logs:
            if isinstance(entry, Mapping) and entry.get("event_proposals") is not None:
                candidates.append(entry.get("event_proposals"))
    for candidate in candidates:
        scopes = normalize_event_scopes(candidate, analysis_id=analysis_id)
        if scopes:
            return scopes
    return ()


def build_event_window_claims(
    *,
    analysis_id: str,
    scopes: Sequence[Mapping[str, Any]],
    pipeline_fingerprint: str,
) -> tuple[EvidenceClaim, ...]:
    """Create family-safe event windows without forcing a profile label."""

    claims: list[EvidenceClaim] = []
    for scope in normalize_event_scopes(scopes, analysis_id=analysis_id):
        value = {
            "start_pts_sec": scope["start_pts_sec"],
            "end_pts_sec": scope["end_pts_sec"],
            "candidate_profile_scores": scope["candidate_profile_scores"],
            "proposal_status": scope["status"],
        }
        observability = scope["observability"]
        mapped_observability = "observed" if observability == "observable" else "partial" if observability == "partially_observable" else "unobservable"
        # A proposal is not a confirmed event window until a parent (or an
        # equivalent source-linked reviewer) explicitly confirms it.  Even
        # when deterministic tracking makes the interval observable, keeping
        # ``pending_confirmation`` uncertain prevents growth/skills/coaching
        # consumers from treating a high-recall proposal as settled evidence.
        proposal_status = scope["status"]
        # A pending/ignored/ordinary proposal is not an authoritative window,
        # even when the tracker can see it.  Mark it partial before fusion so
        # the claim-fusion confidence combiner cannot promote it back to
        # ``confirmed`` merely because it has one deterministic source.
        claim_observability = (
            mapped_observability
            if proposal_status == "confirmed_window"
            else "partial"
            if mapped_observability != "unobservable"
            else "unobservable"
        )
        claim_status = (
            "confirmed"
            if proposal_status == "confirmed_window" and claim_observability == "observed"
            else "unobservable"
            if claim_observability == "unobservable"
            else "uncertain"
        )
        claims.append(EvidenceClaim(
            analysis_id=analysis_id,
            event_id=scope["event_id"],
            claim_type="event_window",
            value=value if mapped_observability != "unobservable" else None,
            definition_version="action-event-proposal.v1",
            compatibility_group="action-event/source-pts/v1",
            unit="source_pts",
            sources=("deterministic", "action_event_proposal"),
            source_references=(f"event_proposal:{scope.get('proposal_event_id', scope['event_id'])}",),
            source_fingerprints={"deterministic": pipeline_fingerprint, **({"proposal": scope["provenance_fingerprint"]} if scope["provenance_fingerprint"] else {})},
            confidence=0.85 if claim_observability == "observed" else 0.35 if claim_observability == "partial" else 0.0,
            observability=claim_observability,
            status=claim_status,
            refusal_reason=(
                "event_window_unobservable"
                if mapped_observability == "unobservable"
                else "event_window_pending_confirmation"
                if proposal_status != "confirmed_window"
                else None
            ),
            review_task=(
                None
                if claim_status == "confirmed"
                else f"{scope['event_id']}:review_event_window"
            ),
            provenance=("measured",),
        ))
    return tuple(claims)


def build_event_candidate_claims(
    *,
    analysis_id: str,
    scopes: Sequence[Mapping[str, Any]],
    pipeline_fingerprint: str,
) -> tuple[EvidenceClaim, ...]:
    """Expose proposal family scores as uncertain, event-scoped evidence."""

    claims: list[EvidenceClaim] = []
    for scope in normalize_event_scopes(scopes, analysis_id=analysis_id):
        scores = scope["candidate_profile_scores"]
        observability = scope["observability"]
        mapped_observability = "observed" if observability == "observable" else "partial" if observability == "partially_observable" else "unobservable"
        claims.append(EvidenceClaim(
            analysis_id=analysis_id,
            event_id=scope["event_id"],
            claim_type="action_candidate",
            value={"candidate_profile_scores": scores} if mapped_observability != "unobservable" else None,
            definition_version="action-event-proposal.v1",
            compatibility_group="action-profile-candidate/family/v1",
            sources=("deterministic", "action_event_proposal"),
            source_references=(f"event_proposal:{scope.get('proposal_event_id', scope['event_id'])}",),
            source_fingerprints={"deterministic": pipeline_fingerprint, **({"proposal": scope["provenance_fingerprint"]} if scope["provenance_fingerprint"] else {})},
            confidence=0.45 if mapped_observability == "observed" else 0.2 if mapped_observability == "partial" else 0.0,
            observability=mapped_observability,
            status="uncertain" if mapped_observability != "unobservable" else "unobservable",
            refusal_reason=None if mapped_observability != "unobservable" else "action_candidate_unobservable",
            review_task=f"{scope['event_id']}:confirm_action_profile",
            provenance=("measured",),
        ))
    return tuple(claims)


def derive_event_scopes_from_motion(
    *,
    analysis_id: str,
    source_video_hash: str,
    motion_scores: Mapping[str, Any] | None,
    pipeline_fingerprint: str,
    camera_reliability: float = 0.65,
) -> tuple[dict[str, Any], ...]:
    """Derive high-recall event windows from bounded deterministic motion.

    This is intentionally a proposal-only adapter: no family is selected and
    sparse/weak evidence remains absent.  Callers may add richer pose/contact
    samples in later stages without changing the event-window contract.
    """

    motion = motion_scores if isinstance(motion_scores, Mapping) else {}
    # Prefer a persisted source-linked proposal envelope when present.  The
    # selected-motion fallback below is intentionally lower-fidelity and only
    # exists for analyses produced before proposal persistence was enabled.
    persisted = normalize_event_scopes(motion.get("event_proposals"), analysis_id=analysis_id)
    if persisted:
        return persisted
    selected = motion.get("selected")
    if not isinstance(selected, Sequence) or isinstance(selected, (str, bytes, bytearray)):
        return ()
    records = [item for item in selected if isinstance(item, Mapping)]
    if not records:
        return ()
    values = [float(item.get("motion_score")) for item in records if isinstance(item.get("motion_score"), (int, float)) and not isinstance(item.get("motion_score"), bool)]
    peak = max(values, default=0.0)
    if peak <= 0:
        return ()
    samples: list[ProposalEvidenceSample] = []
    for index, item in enumerate(records):
        timestamp = item.get("timestamp")
        score = item.get("motion_score")
        if not isinstance(timestamp, (int, float)) or not isinstance(score, (int, float)):
            continue
        samples.append(ProposalEvidenceSample(
            source_frame_index=max(0, int(item.get("source_thumb_index", index) or index)),
            pts_sec=max(0.0, float(timestamp)),
            camera_compensated_track_motion=max(0.0, min(1.0, float(score) / peak)),
            camera_reliability=max(0.0, min(1.0, float(camera_reliability))),
            tracking_observable=True,
            pose_observable=False,
            provenance=("motion_sample", "deterministic_proposal"),
        ))
    duration_raw = motion.get("window_end", motion.get("source_duration_sec"))
    try:
        duration = max(float(duration_raw), max(item.pts_sec for item in samples) if samples else 0.0, 0.001)
    except (TypeError, ValueError):
        duration = max((item.pts_sec for item in samples), default=0.001)
    proposals = generate_event_proposals(
        source_video_hash=source_video_hash,
        source_duration_sec=duration,
        samples=samples,
        pipeline_fingerprint=pipeline_fingerprint,
    )
    return normalize_event_scopes(proposals.model_dump(mode="json"), analysis_id=analysis_id)


def v2_pipeline_fingerprint(*, analysis_id: str, provider_fingerprints: Mapping[str, str] | None = None, configuration: Mapping[str, Any] | None = None) -> str:
    payload = {
        "schema": "analysis-v2-iter14",
        "analysis_id": analysis_id,
        "providers": dict(provider_fingerprints or {}),
        "configuration": dict(configuration or {}),
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _confidence(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _source_refs(*values: Any) -> tuple[str, ...]:
    return tuple(str(value) for value in values if value not in (None, ""))


def _measurement_claim(
    *,
    analysis_id: str,
    event_id: str,
    claim_type: str,
    value: Any,
    provenance: str,
    confidence: float,
    source_reference: str,
    fingerprint: str,
    unit: str | None = None,
    definition_version: str = "deterministic-measurement.v2",
    compatibility_group: str | None = None,
) -> EvidenceClaim:
    supported = provenance in {"measured", "smoothed"} and value is not None
    return EvidenceClaim(
        analysis_id=analysis_id,
        event_id=event_id,
        claim_type=claim_type,
        value=value if supported else None,
        definition_version=definition_version,
        compatibility_group=compatibility_group or f"measurement/{claim_type}",
        unit=unit,
        sources=("deterministic_measurement",),
        source_references=(source_reference,),
        source_fingerprints={"deterministic": fingerprint},
        confidence=confidence if supported else 0.0,
        observability="observed" if supported and provenance == "measured" else "partial" if supported else "unobservable",
        status="confirmed" if supported else "unobservable",
        refusal_reason=None if supported else f"unsupported_provenance:{provenance}",
        review_task=None if supported else "review_source_measurement",
    )


def build_deterministic_claims(
    *,
    analysis_id: str,
    action_profile: str | None,
    bio_data: Mapping[str, Any] | None,
    pose_data: Mapping[str, Any] | None,
    target_lock: Mapping[str, Any] | None,
    pipeline_fingerprint: str,
    event_id: str | None = None,
    whole_analysis: bool = False,
) -> tuple[EvidenceClaim, ...]:
    """Build source-linked deterministic claims without exposing raw fields."""

    event = None if whole_analysis else (event_id or f"{analysis_id}:event:0")
    claims: list[EvidenceClaim] = []
    normalized_profile = str(action_profile or "").strip().lower()
    if normalized_profile in {"jump", "spin", "step", "spiral"}:
        # The profile is deterministic only when the target lock is confirmed;
        # otherwise it remains a reviewable candidate and cannot automate.
        identity_confirmed = bool(isinstance(target_lock, Mapping) and str(target_lock.get("status", "")).lower() in {"auto_locked", "manual", "confirmed"})
        claims.append(EvidenceClaim(
            analysis_id=analysis_id,
            event_id=event,
            claim_type="action_profile",
            value=normalized_profile,
            definition_version="deterministic-action-profile.v2",
            compatibility_group="action-profile/family/v2",
            sources=("action_classifier", "deterministic"),
            source_fingerprints={"deterministic": pipeline_fingerprint},
            confidence=0.9 if identity_confirmed else 0.55,
            observability="observed" if identity_confirmed else "partial",
            status="confirmed" if identity_confirmed else "uncertain",
            refusal_reason=None if identity_confirmed else "target_identity_not_confirmed",
            review_task=None if identity_confirmed else "confirm_target_identity",
        ))
    bio = bio_data if isinstance(bio_data, Mapping) else {}
    metrics = bio.get("jump_metrics")
    metrics_ok = str(bio.get("jump_metrics_status", "")).lower() in {"ok", "valid", "good"}
    metric_units = {
        "air_time_seconds": "s",
        "estimated_height_cm": "cm",
        "takeoff_speed_mps": "m/s",
        "rotation_rps": "rps",
        "estimated_rotations": "turns",
    }
    if isinstance(metrics, Mapping) and metrics_ok:
        for name, raw in metrics.items():
            if name not in metric_units or isinstance(raw, bool) or not isinstance(raw, (int, float)):
                continue
            claims.append(_measurement_claim(
                analysis_id=analysis_id,
                event_id=event,
                claim_type=f"metric_{name}",
                value=float(raw),
                provenance="measured",
                confidence=0.9,
                source_reference=f"bio_data.jump_metrics:{name}",
                fingerprint=pipeline_fingerprint,
                unit=metric_units[name],
                definition_version="deterministic-jump-metric.v2",
                compatibility_group=f"jump-metric/{name}/{metric_units[name]}",
            ))
    # Key moments are deterministic source-linked observations.  They may be
    # displayed and reviewed, but are not inferred by either language model.
    key_frames = bio.get("key_frames") if isinstance(bio.get("key_frames"), Mapping) else {}
    timestamps = bio.get("key_frame_timestamps") if isinstance(bio.get("key_frame_timestamps"), Mapping) else {}
    for phase in ("T", "A", "L"):
        frame = key_frames.get(phase)
        if not frame:
            continue
        claims.append(EvidenceClaim(
            analysis_id=analysis_id,
            event_id=event,
            claim_type="key_moment",
            value={"phase": phase, "frame": str(frame), "timestamp": timestamps.get(phase)},
            definition_version="deterministic-key-moment.v2",
            compatibility_group="key-moment/source-pts/v2",
            unit="source_pts",
            sources=("key_moment", "deterministic"),
            source_references=_source_refs(f"bio_data.key_frames:{phase}", timestamps.get(phase)),
            source_fingerprints={"deterministic": pipeline_fingerprint},
            confidence=0.85 if timestamps.get(phase) is not None else 0.65,
            observability="observed" if timestamps.get(phase) is not None else "partial",
            status="confirmed" if timestamps.get(phase) is not None else "uncertain",
            review_task=None if timestamps.get(phase) is not None else "confirm_key_moment",
        ))
    # A compact pose-availability claim lets the family presenter explain why
    # technical details may be absent without leaking joint arrays.
    pose = pose_data if isinstance(pose_data, Mapping) else {}
    diagnostics = pose.get("pose_diagnostics") if isinstance(pose.get("pose_diagnostics"), Mapping) else {}
    if diagnostics:
        tracked = int(diagnostics.get("tracked_frames", 0) or 0)
        total = int(diagnostics.get("total_frames", 0) or 0)
        if total:
            claims.append(EvidenceClaim(
                analysis_id=analysis_id,
                event_id=event,
                claim_type="pose_observability",
                value={"tracked_frames": tracked, "total_frames": total},
                definition_version="deterministic-pose-availability.v2",
                compatibility_group="pose-availability/v2",
                sources=("deterministic",),
                source_references=("pose.pose_diagnostics",),
                source_fingerprints={"deterministic": pipeline_fingerprint},
                confidence=1.0,
                observability="observed" if tracked == total else "partial",
                status="confirmed" if tracked == total else "uncertain",
            ))
    return tuple(claims)


def claims_from_payload(
    payload: Mapping[str, Any] | None,
    *,
    analysis_id: str,
    source: str,
    event_id: str | None = None,
    fingerprint: str | None = None,
    whole_analysis: bool = False,
) -> tuple[EvidenceClaim, ...]:
    raw = payload if isinstance(payload, Mapping) else {}
    values = raw.get("evidence_claims")
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        return ()
    output: list[EvidenceClaim] = []
    for value in values:
        if not isinstance(value, Mapping):
            continue
        item = dict(value)
        item.setdefault("analysis_id", analysis_id)
        # A model payload is not an event-localization authority.  In a
        # multi-event analysis force Path A/Path B claims to whole-analysis
        # scope even if a provider echoes or invents an ``event_id`` field;
        # deterministic source-PTS localization happens only after parsing.
        if whole_analysis:
            item["event_id"] = None
        elif "event_id" not in item:
            item["event_id"] = event_id or f"{analysis_id}:event:0"
        # Provider JSON cannot self-attest as deterministic/identity evidence.
        # Path B may carry the explicit deterministic_measurement source only
        # inside the post-parse structured-measurement adapter envelope; Path
        # A is always reduced to the bounded visual source.
        raw_sources = item.get("sources")
        if source == "path_a":
            item["sources"] = ("path_a",)
        elif source == "path_b":
            candidate_sources = raw_sources if isinstance(raw_sources, Sequence) and not isinstance(raw_sources, (str, bytes, bytearray)) else ()
            # A provider payload cannot self-attest as deterministic evidence.
            # The Path B service replaces model ``evidence_claims`` with claims
            # emitted by ``normalize_path_b_measurements``; that adapter marks
            # its provenance explicitly.  Only those locally-produced claims
            # may retain the deterministic_measurement source in fusion.
            adapter_envelope = raw.get("evidence_claims_origin") == "structured_measurement_adapter.v1"
            item["sources"] = tuple(dict.fromkeys(
                value for value in ("path_b", *candidate_sources)
                if str(value) == "path_b" or (str(value) == "deterministic_measurement" and adapter_envelope)
            ))
        else:
            item.setdefault("sources", (source,))
        fps = dict(item.get("source_fingerprints") or {})
        if fingerprint:
            fps.setdefault(source, fingerprint)
        item["source_fingerprints"] = fps
        try:
            output.append(EvidenceClaim.model_validate(item))
        except Exception:
            continue
    return tuple(output)


__all__ = [
    "v2_pipeline_fingerprint",
    "build_deterministic_claims",
    "claims_from_payload",
    "normalize_event_scopes",
    "canonicalize_single_event_scope",
    "scope_claims_to_events",
    "event_scopes_from_analysis",
    "build_event_window_claims",
    "build_event_candidate_claims",
    "derive_event_scopes_from_motion",
]
