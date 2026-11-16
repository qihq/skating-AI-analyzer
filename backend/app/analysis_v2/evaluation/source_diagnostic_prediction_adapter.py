from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.analysis_v2.evaluation.golden_schema import GoldenDatasetV2
from app.analysis_v2.evaluation.pilot_evaluator import EventPrediction, PilotPredictionBundle, SourceProposal
from app.analysis_v2.profile_moments import MomentEvidenceSample, localize_profile_moments
from app.analysis_v2.rotation import RotationEvidenceSample, estimate_rotation


_PROFILES = {"jump", "spin", "step", "spiral"}
_STATE_RANK = {"confirmed": 2, "ambiguous": 1, "unknown": 0}


@dataclass(frozen=True)
class SourceDiagnosticAdapterResult:
    bundle: PilotPredictionBundle
    diagnostics: dict[str, Any]


def build_source_diagnostic_prediction_bundle(
    dataset: GoldenDatasetV2,
    diagnostic: Mapping[str, Any],
    *,
    pipeline_fingerprint: str,
    evaluation_masks: Sequence[str],
) -> PilotPredictionBundle:
    """Adapt source-only diagnostic evidence into the formal pilot wire contract.

    Golden data supplies only the opaque source hash and event ID required by
    the evaluator alignment contract. Prediction values are selected entirely
    from source-only proposals, classifications, moments and rotation samples.
    """

    return build_source_diagnostic_prediction_result(
        dataset,
        diagnostic,
        pipeline_fingerprint=pipeline_fingerprint,
        evaluation_masks=evaluation_masks,
    ).bundle


def build_source_diagnostic_prediction_result(
    dataset: GoldenDatasetV2,
    diagnostic: Mapping[str, Any],
    *,
    pipeline_fingerprint: str,
    evaluation_masks: Sequence[str],
) -> SourceDiagnosticAdapterResult:
    """Build predictions plus a label-agnostic alignment diagnostic summary.

    A source with multiple Golden events is intentionally omitted because a
    source-only diagnostic currently selects only one primary proposal. Using
    Golden intervals or profiles to choose which event receives that proposal
    would leak the evaluated target. The evaluator therefore sees every event
    on that source as a missing prediction and keeps it in the denominator.
    """

    event_ids_by_source: dict[str, list[str]] = defaultdict(list)
    for event in dataset.events:
        event_ids_by_source[event.source_sha256].append(event.event_id)

    dataset_source_hashes = {source.source_sha256 for source in dataset.sources}
    single_event_sources = {
        source_hash for source_hash in dataset_source_hashes if len(event_ids_by_source[source_hash]) == 1
    }
    multi_event_sources = {
        source_hash for source_hash in dataset_source_hashes if len(event_ids_by_source[source_hash]) > 1
    }
    zero_event_sources = dataset_source_hashes - single_event_sources - multi_event_sources

    predictions: list[EventPrediction] = []
    proposals: list[SourceProposal] = []
    seen_sources: set[str] = set()
    ok_diagnostic_sources: set[str] = set()
    videos = diagnostic.get("videos")
    if not isinstance(videos, Sequence) or isinstance(videos, (str, bytes)):
        videos = ()
    for video in videos:
        if not isinstance(video, Mapping) or video.get("status") != "ok":
            continue
        raw = video.get("raw_diagnostics")
        raw = raw if isinstance(raw, Mapping) else {}
        source = raw.get("source_evidence")
        source = source if isinstance(source, Mapping) else {}
        source_hash = str(source.get("source_video_hash") or "")
        if source_hash in seen_sources:
            raise ValueError("source diagnostic contains duplicate source evidence")
        seen_sources.add(source_hash)
        if source_hash in dataset_source_hashes:
            ok_diagnostic_sources.add(source_hash)
        rows = [item for item in source.get("events", ()) if isinstance(item, Mapping)]
        collection_proposals = source.get("proposal_collection", {}).get("proposals") if isinstance(source.get("proposal_collection"), Mapping) else None
        raw_proposals = [item for item in collection_proposals if isinstance(item, Mapping)] if isinstance(collection_proposals, Sequence) else []
        if not raw_proposals:
            raw_proposals = [item.get("proposal") for item in rows if isinstance(item.get("proposal"), Mapping)]
        observation_envelope = _source_observation_envelope(source)
        localized_coverage = _interval_coverage(raw_proposals, _number(source.get("source_duration_sec")))
        if observation_envelope is not None and localized_coverage < .8:
            raw_proposals = [
                {
                    "event_id": f"unlocalized-{source_hash[:16]}",
                    "start_pts": observation_envelope[0],
                    "end_pts": observation_envelope[1],
                    "evidence_sources": ["unlocalized_observability_envelope"],
                },
                *raw_proposals,
            ]
        for raw_proposal in raw_proposals:
            try:
                proposal = SourceProposal(
                    source_sha256=source_hash,
                    proposal_id=str(raw_proposal.get("event_id") or raw_proposal.get("provenance_fingerprint") or ""),
                    start_pts=float(raw_proposal.get("start_pts")),
                    end_pts=float(raw_proposal.get("end_pts")),
                    localization=(
                        "unlocalized"
                        if "unlocalized_observability_envelope" in raw_proposal.get("evidence_sources", ())
                        else "localized"
                    ),
                )
            except (TypeError, ValueError):
                continue
            proposals.append(proposal)
        event_ids = event_ids_by_source.get(source_hash, [])
        if len(event_ids) != 1:
            continue

        collection = source.get("proposal_collection")
        collection = collection if isinstance(collection, Mapping) else {}
        if collection.get("classifier_labels_consumed") is not False:
            raise ValueError("source diagnostic proposal generation consumed classifier labels")

        selected = max(rows, key=_row_rank, default=None)
        prediction = _prediction_from_row(
            source_hash=source_hash,
            event_id=event_ids[0],
            selected=selected,
            source=source,
            profile_evidence=raw.get("profile_evidence"),
            identity_anchor_source=(raw.get("target_lock") or {}).get("identity_anchor_source")
            if isinstance(raw.get("target_lock"), Mapping)
            else None,
        )
        predictions.append(EventPrediction.model_validate(prediction))

    bundle = PilotPredictionBundle.model_validate({
        "pipeline_fingerprint": pipeline_fingerprint,
        "evaluation_masks": list(evaluation_masks),
        "proposals": [item.model_dump(mode="json") for item in proposals],
        "predictions": [item.model_dump(mode="json") for item in predictions],
    })
    diagnostics = {
        "schema_version": "source-diagnostic-adapter-report.v1",
        "alignment_policy": "single-event-source-only.v1",
        "golden_target_fields_used_for_selection": False,
        "dataset_source_count": len(dataset_source_hashes),
        "dataset_event_count": len(dataset.events),
        "single_event_source_count": len(single_event_sources),
        "multi_event_source_count": len(multi_event_sources),
        "multi_event_event_count": sum(len(event_ids_by_source[item]) for item in multi_event_sources),
        "zero_event_source_count": len(zero_event_sources),
        "ok_diagnostic_source_count": len(ok_diagnostic_sources),
        "missing_or_failed_diagnostic_source_count": len(dataset_source_hashes - ok_diagnostic_sources),
        "prediction_count": len(predictions),
        "proposal_count": len(proposals),
        "localized_proposal_count": sum(
            1
            for item in proposals
            if item.localization == "localized"
        ),
        "unlocalized_proposal_count": sum(1 for item in proposals if item.localization == "unlocalized"),
        "skipped_multi_event_sources": len(multi_event_sources & ok_diagnostic_sources),
        "skipped_zero_event_sources": len(zero_event_sources & ok_diagnostic_sources),
    }
    return SourceDiagnosticAdapterResult(bundle=bundle, diagnostics=diagnostics)


def _row_rank(row: Mapping[str, Any]) -> tuple[float, float, float, float]:
    classification = row.get("classification")
    classification = classification if isinstance(classification, Mapping) else {}
    proposal = row.get("proposal")
    proposal = proposal if isinstance(proposal, Mapping) else {}
    state = str(classification.get("state") or "unknown")
    start = _number(proposal.get("start_pts"))
    end = _number(proposal.get("end_pts"))
    return (
        float(_STATE_RANK.get(state, 0)),
        _number(classification.get("confidence")),
        _number(classification.get("margin")),
        max(0.0, end - start),
    )


def _prediction_from_row(
    *,
    source_hash: str,
    event_id: str,
    selected: Mapping[str, Any] | None,
    source: Mapping[str, Any],
    profile_evidence: Any,
    identity_anchor_source: Any,
) -> dict[str, Any]:
    input_fields = [
        "source_evidence.proposals",
        "source_evidence.pose_dynamics",
        "source_evidence.camera_compensated_motion",
        "source_evidence.rotation_signals",
        "source_evidence.source_family_peaks",
    ]
    if str(identity_anchor_source or "") == "parent_confirmed":
        input_fields.append("upstream.parent_confirmed_identity_anchor")
    payload: dict[str, Any] = {
        "source_sha256": source_hash,
        "event_id": event_id,
        "predicted_profile": "unknown",
        "predicted_profile_state": "unknown",
        "confidence": 0.0,
        "input_fields": input_fields,
        "input_payload": {
            "source_evidence_schema": _safe_text(source.get("schema_version")),
            "source_timeline_fingerprint": _safe_text(source.get("source_timeline_fingerprint")),
            "prediction_policy": "source-only-primary-candidate.v1",
            "proposal_policy": "single-event-source-observation-envelope.v1",
            "source_profile_policy": "limited-sample-source-family.v1",
            "classifier_labels_consumed": False,
            "semantic_labels_consumed": False,
            "identity_anchor_source": _safe_text(identity_anchor_source),
        },
    }
    observation_envelope = _source_observation_envelope(source)
    calibrated = _source_family_profile(source, profile_evidence)
    if observation_envelope is not None:
        payload["proposal_start_pts"], payload["proposal_end_pts"] = observation_envelope
    if selected is None:
        if calibrated is not None:
            payload["predicted_profile"] = calibrated
            payload["predicted_profile_state"] = "ambiguous"
            payload["moments"] = _source_family_moments(calibrated, source, observation_envelope)
            rotation = _source_family_rotation(calibrated, source, observation_envelope, payload["moments"])
            if rotation is not None:
                payload["rotation"] = rotation
        return payload

    proposal = selected.get("proposal")
    proposal = proposal if isinstance(proposal, Mapping) else {}
    start = _number(proposal.get("start_pts"), default=None)
    end = _number(proposal.get("end_pts"), default=None)

    classification = selected.get("classification")
    classification = classification if isinstance(classification, Mapping) else {}
    profile = str(classification.get("profile") or "unknown")
    state = str(classification.get("state") or "unknown")
    if profile in _PROFILES:
        payload["predicted_profile"] = profile
    if state in _STATE_RANK:
        payload["predicted_profile_state"] = state
    if calibrated is not None:
        payload["predicted_profile"] = calibrated
        payload["predicted_profile_state"] = "confirmed" if state == "confirmed" and profile == calibrated else "ambiguous"
    payload["confidence"] = max(0.0, min(1.0, _number(classification.get("confidence"))))

    moments = selected.get("moments")
    moments = moments if isinstance(moments, Mapping) else {}
    if moments.get("semantic_labels_consumed") is not False:
        raise ValueError("source diagnostic moment generation consumed semantic labels")
    final_profile = calibrated or profile
    payload["moments"] = (
        _source_family_moments(final_profile, source, observation_envelope)
        if calibrated is not None
        else _moment_predictions(profile, moments.get("moments"))
    )

    source_rotation = _source_family_rotation(final_profile, source, observation_envelope, payload["moments"])
    rotation = selected.get("rotation")
    if source_rotation is not None and calibrated is not None:
        payload["rotation"] = source_rotation
    elif isinstance(rotation, Mapping):
        payload["rotation"] = _rotation_prediction(rotation)
    elif profile in {"jump", "spin"} and start is not None and end is not None:
        samples = [
            RotationEvidenceSample.model_validate(item)
            for item in source.get("rotation_samples", ())
            if isinstance(item, Mapping)
        ]
        estimate = estimate_rotation(
            event_id=str(proposal.get("event_id") or "source-event"),
            profile=profile,
            event_start_pts=start,
            event_end_pts=end,
            samples=samples,
            source_timeline_fingerprint=str(source.get("source_timeline_fingerprint") or "unavailable"),
        )
        payload["rotation"] = _rotation_prediction(estimate.model_dump(mode="json"))
    return payload


def _source_observation_envelope(source: Mapping[str, Any]) -> tuple[float, float] | None:
    samples = [item for item in source.get("proposal_samples", ()) if isinstance(item, Mapping)]
    pts = [_number(item.get("pts_sec"), default=None) for item in samples]
    present = sorted(value for value in pts if value is not None and value >= 0)
    if not present:
        return None
    start = present[0]
    duration = _number(source.get("source_duration_sec"), default=None)
    end = duration if duration is not None and duration > present[-1] else present[-1]
    if end <= start:
        return None
    return round(start, 6), round(end, 6)


def _interval_coverage(raw_proposals: Sequence[Any], duration: float) -> float:
    if duration <= 0:
        return 0.0
    intervals = []
    for item in raw_proposals:
        if not isinstance(item, Mapping):
            continue
        start = _number(item.get("start_pts"), default=None)
        end = _number(item.get("end_pts"), default=None)
        if start is not None and end is not None and end > start:
            intervals.append((start, end))
    merged: list[list[float]] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return min(1.0, sum(end - start for start, end in merged) / duration)


def _source_family_profile(source: Mapping[str, Any], raw_profile_evidence: Any) -> str | None:
    profile_evidence = raw_profile_evidence if isinstance(raw_profile_evidence, Mapping) else {}
    moment_samples = [item for item in source.get("moment_samples", ()) if isinstance(item, Mapping)]
    proposal_samples = [item for item in source.get("proposal_samples", ()) if isinstance(item, Mapping)]
    edge_peak = max((_number(item.get("step_complexity")) for item in moment_samples), default=0.0)
    airborne_samples = sum(_number(item.get("ice_contact_proxy")) >= .55 for item in proposal_samples)
    pose_turns = 0.0
    pose_reliability = 0.0
    for item in source.get("rotation_diagnostics", ()):
        if not isinstance(item, Mapping):
            continue
        families = item.get("families")
        families = families if isinstance(families, Mapping) else {}
        pose = families.get("pose_orientation")
        if not isinstance(pose, Mapping):
            continue
        pose_turns = max(pose_turns, _number(pose.get("turns")))
        pose_reliability = max(pose_reliability, _number(pose.get("reliability")))
    average_motion = _number(profile_evidence.get("avg_motion_score"))

    if edge_peak >= .47 and pose_turns < .25:
        return "spiral"
    if pose_turns >= 1.15 and pose_reliability >= .60:
        return "spin"
    if airborne_samples >= 2 or (average_motion >= .05 and edge_peak < .45):
        return "jump"
    return None


def _source_family_moments(
    profile: str,
    source: Mapping[str, Any],
    envelope: tuple[float, float] | None,
) -> list[dict[str, Any]]:
    if profile not in _PROFILES or envelope is None:
        return []
    samples = [
        MomentEvidenceSample.model_validate(item)
        for item in source.get("moment_samples", ())
        if isinstance(item, Mapping)
    ]
    if not samples:
        return []
    localized = localize_profile_moments(
        event_id="source-family-event",
        profile=profile,  # type: ignore[arg-type]
        event_start_pts=envelope[0],
        event_end_pts=envelope[1],
        samples=samples,
        source_timeline_fingerprint=str(source.get("source_timeline_fingerprint") or "unavailable"),
    )
    return _moment_predictions(profile, [item.model_dump(mode="json") for item in localized.moments])


def _source_family_rotation(
    profile: str,
    source: Mapping[str, Any],
    envelope: tuple[float, float] | None,
    moments: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    if profile not in {"jump", "spin"} or envelope is None:
        return None
    samples = [
        RotationEvidenceSample.model_validate(item)
        for item in source.get("rotation_samples", ())
        if isinstance(item, Mapping)
    ]
    if not samples:
        return None
    if profile == "jump":
        by_key = {str(item.get("key")): item for item in moments}
        takeoff = _number((by_key.get("takeoff") or {}).get("pts"), default=None)
        landing = _number((by_key.get("landing") or {}).get("pts"), default=None)
        if takeoff is not None and landing is not None and landing > takeoff:
            samples = [
                item.model_copy(update={
                    "phase": "pre_takeoff" if item.pts_sec < takeoff else "airborne" if item.pts_sec <= landing else "post_landing",
                })
                for item in samples
            ]
    estimate = estimate_rotation(
        event_id="source-family-event",
        profile=profile,  # type: ignore[arg-type]
        event_start_pts=envelope[0],
        event_end_pts=envelope[1],
        samples=samples,
        source_timeline_fingerprint=str(source.get("source_timeline_fingerprint") or "unavailable"),
    )
    return _rotation_prediction(estimate.model_dump(mode="json"))


def _moment_predictions(profile: str, raw_moments: Any) -> list[dict[str, Any]]:
    moments = [item for item in raw_moments or () if isinstance(item, Mapping)]
    confirmed = [item for item in moments if item.get("status") == "confirmed"]
    selected: list[tuple[str, Mapping[str, Any]]] = []
    if profile == "jump":
        selected = [(key, item) for key in ("takeoff", "apex", "landing") for item in confirmed if item.get("semantic_key") == key]
    elif profile == "spin":
        mapping = {"spin_entry": "entry_start", "spin_main": "main_start", "spin_exit": "exit_end"}
        selected = [(mapped, item) for item in confirmed if (mapped := mapping.get(str(item.get("semantic_key"))))]
    elif profile == "spiral":
        item = next((item for item in confirmed if item.get("semantic_key") == "spiral_hold"), None)
        selected = [("representative", item)] if item else []
    elif profile == "step":
        item = next((item for item in confirmed if str(item.get("semantic_key") or "").startswith("step_representative")), None)
        selected = [("representative", item)] if item else []

    output: list[dict[str, Any]] = []
    for key, item in selected:
        pts = item.get("end_pts_sec") if key == "exit_end" else item.get("pts_sec")
        frame = item.get("source_frame_index")
        if pts is None or frame is None:
            continue
        output.append({
            "key": key,
            "source_frame_index": int(frame),
            "pts": float(pts),
            "observability": "observable",
        })
    return output


def _rotation_prediction(raw: Mapping[str, Any]) -> dict[str, Any]:
    status = str(raw.get("status") or "unobservable")
    value = raw.get("value_turns")
    observability = str(raw.get("observability") or ("observable" if status == "exact" else "unobservable"))
    if observability not in {"observable", "uncertain", "unobservable"}:
        observability = "unobservable"
    turns = float(value) if status == "exact" and value is not None else None
    return {
        "turns": turns,
        "rotation_class": f"{round(turns * 2) / 2:g}" if turns is not None else None,
        "observability": observability,
        "confidence": max(0.0, min(1.0, _number(raw.get("confidence")))),
        "refusal_reason": _safe_text(raw.get("refusal_reason") or (None if turns is not None else status)),
    }


def _number(value: Any, default: float | None = 0.0) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number == number and abs(number) != float("inf") else default


def _safe_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
