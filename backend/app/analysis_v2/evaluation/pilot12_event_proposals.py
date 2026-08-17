from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from app.analysis_v2.event_proposals import (
    EventProposalCollection,
    PROFILE_KEYS,
    ProposalEvidenceSample,
    generate_event_proposals,
    interval_union_coverage,
)
from app.analysis_v2.action_classification import classify_proposal
from app.analysis_v2.evaluation.gate_policy import GOLDEN_GATE_POLICY
from app.analysis_v2.evaluation.legacy_event_proposal_adapter import evidence_from_legacy_analysis as _legacy_evidence


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if result == result and abs(result) != float("inf") else default
    except (TypeError, ValueError):
        return default


def evidence_from_legacy_analysis(source_hash: str, analysis: Mapping[str, Any]):
    return _legacy_evidence(source_hash, analysis)


def proposal_collections_from_snapshot(snapshot: Mapping[str, Any], *, pipeline_fingerprint: str) -> dict[str, EventProposalCollection]:
    collections: dict[str, EventProposalCollection] = {}
    for source_hash, analysis in sorted(snapshot.items()):
        if not isinstance(analysis, Mapping):
            continue
        duration, samples = evidence_from_legacy_analysis(source_hash, analysis)
        collections[source_hash] = generate_event_proposals(source_video_hash=source_hash, source_duration_sec=duration, samples=samples, pipeline_fingerprint=pipeline_fingerprint)
    return collections


def _wilson(numerator: int, denominator: int) -> list[float] | None:
    if denominator == 0:
        return None
    z = 1.959963984540054
    p = numerator / denominator
    center = (p + z * z / (2 * denominator)) / (1 + z * z / denominator)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * denominator)) / denominator) / (1 + z * z / denominator)
    return [round(max(0.0, center - margin), 6), round(min(1.0, center + margin), 6)]


def evaluate_pilot12_event_proposals(snapshot_path: Path, labels_path: Path) -> dict[str, Any]:
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    fingerprint = "iteration10-pilot12-proposals.v1"
    collections = proposal_collections_from_snapshot(snapshot, pipeline_fingerprint=fingerprint)
    events = [item for item in labels.get("events", []) if isinstance(item, Mapping)]
    observable = [item for item in events if item.get("observability") == "observable"]
    hits = 0
    strata: dict[str, list[bool]] = defaultdict(list)
    event_diagnostics: list[dict[str, Any]] = []
    for event in observable:
        proposals = collections.get(str(event.get("source_sha256")), EventProposalCollection(source_video_hash=str(event.get("source_sha256")), source_duration_sec=max(0.001, _number(event.get("end_pts"))), pipeline_fingerprint=fingerprint))
        start, end = _number(event.get("start_pts")), _number(event.get("end_pts"))
        matched = []
        for proposal in proposals.proposals:
            intersection = max(0.0, min(end, proposal.end_pts) - max(start, proposal.start_pts))
            if intersection / max(end - start, 1e-9) >= 0.5:
                matched.append(proposal.event_id)
        hit = bool(matched)
        hits += int(hit)
        keys = {str(event.get("profile", "unknown")), *(str(value) for value in event.get("strata", []))}
        for key in keys:
            strata[key].append(hit)
        event_diagnostics.append({"event_id": event.get("event_id"), "source_alias": str(event.get("source_sha256"))[:8], "matched": hit, "proposal_ids": matched})
    total_minutes = sum(item.source_duration_sec for item in collections.values()) / 60
    proposal_count = sum(len(item.proposals) for item in collections.values())
    result = {
        "schema_version": "iteration10-pilot12-event-proposals.v1",
        "gate": "G6",
        "gate_policy_version": GOLDEN_GATE_POLICY.schema_version,
        "evidence_scope": GOLDEN_GATE_POLICY.evidence_scope,
        "status": "passed_for_pilot_only" if observable and hits / len(observable) >= 0.98 else "failed_for_pilot_only",
        "diagnostic_only": True,
        "release_claim": False,
        "classifier_labels_consumed": False,
        "dataset": "pilot-12-run-20260801",
        "raw_n": len(observable),
        "proposal_recall": {"numerator": hits, "denominator": len(observable), "rate": round(hits / len(observable), 6) if observable else None, "wilson_95_ci": _wilson(hits, len(observable))},
        "false_proposals_per_minute_upper_bound": round(proposal_count / total_minutes, 6) if total_minutes else None,
        "proposal_count": proposal_count,
        "video_minutes": round(total_minutes, 6),
        "proposal_coverage": round(sum(interval_union_coverage(item.proposals, item.source_duration_sec) for item in collections.values()) / len(collections), 6) if collections else None,
        "strata": {key: {"numerator": sum(values), "denominator": len(values), "rate": round(sum(values) / len(values), 6), "wilson_95_ci": _wilson(sum(values), len(values))} for key, values in sorted(strata.items())},
        "events": event_diagnostics,
        "collections": {source[:8]: collection.model_dump(mode="json") for source, collection in collections.items()},
        "known_limitations": [
            "This is the existing 12-video owner-labeled pilot, not a frozen G6 dataset.",
            "False proposals/minute is an upper bound because ordinary-skating negative intervals are not exhaustively labeled.",
            "Legacy sparse motion/pose inputs trigger a broad unknown observability envelope when localization would otherwise miss plausible action.",
        ],
    }
    result["result_fingerprint"] = "sha256:" + hashlib.sha256(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    return result


def evaluate_pilot14_action_classification(
    snapshot_path: Path,
    labels_path: Path,
    *,
    validation_sources: Sequence[str] | None = None,
    development_sources: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Run the temporary 14-video family classifier pilot.

    The split is supplied before evaluation and is recorded in the output. The
    two historical weak-label videos are intentionally excluded from metrics.
    """
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    validation = set(validation_sources or ())
    development = set(development_sources or ())
    fingerprint = "iteration11-pilot14-profile-classifier.v1"
    rows: list[dict[str, Any]] = []
    confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    strata: dict[str, list[bool]] = defaultdict(list)
    for event in labels.get("events", []):
        if not isinstance(event, Mapping) or event.get("observability") == "unobservable":
            continue
        source = str(event.get("source_sha256") or "")
        analysis = snapshot.get(source)
        if not isinstance(analysis, Mapping):
            continue
        duration, samples = evidence_from_legacy_analysis(source, analysis)
        proposals = generate_event_proposals(source_video_hash=source, source_duration_sec=duration, samples=samples, pipeline_fingerprint=fingerprint)
        start, end = _number(event.get("start_pts")), _number(event.get("end_pts"))
        matches = [item for item in proposals.proposals if max(0.0, min(end, item.end_pts) - max(start, item.start_pts)) / max(end - start, 1e-9) >= .5]
        if not matches:
            continue
        proposal = max(matches, key=lambda item: min(end, item.end_pts) - max(start, item.start_pts))
        event_samples = tuple(item for item in samples if proposal.start_pts <= item.pts_sec <= proposal.end_pts)
        classification = classify_proposal(proposal, analysis=analysis, samples=event_samples)
        truth = str(event.get("profile") or "unknown")
        predicted = classification.profile
        evaluation_label = predicted if classification.state == "confirmed" else classification.state
        correct = evaluation_label == truth
        if source in validation:
            confusion[truth][evaluation_label] += 1
            for key in {truth, *(str(value) for value in event.get("strata", []))}:
                strata[key].append(correct)
        rows.append({
            "source_alias": source[:8], "event_id": event.get("event_id"), "truth": truth,
            "predicted": predicted, "evaluation_label": evaluation_label, "state": classification.state, "confidence": classification.confidence,
            "split": "validation" if source in validation else "development" if source in development else "excluded",
            "strata": list(event.get("strata", [])), "subtype_state": classification.subtype.state,
        })
    evaluated = [row for row in rows if row["split"] == "validation"]
    n = len(evaluated)
    macro_f1: dict[str, float] = {}
    for family in PROFILE_KEYS:
        tp = confusion[family].get(family, 0)
        fp = sum(confusion[other].get(family, 0) for other in PROFILE_KEYS if other != family)
        fn = sum(value for predicted, value in confusion[family].items() if predicted != family)
        precision = tp / max(tp + fp, 1)
        recall = tp / max(tp + fn, 1)
        macro_f1[family] = round(2 * precision * recall / max(precision + recall, 1e-9), 6)
    macro = sum(macro_f1.values()) / len(PROFILE_KEYS)
    high_conf = [row for row in evaluated if row["state"] == "confirmed" and row["confidence"] >= .8]
    high_conf_errors = sum(row["predicted"] != row["truth"] for row in high_conf)
    result = {
        "schema_version": "iteration11-pilot14-profile-classification.v1",
        "gate": "G7",
        "gate_policy_version": GOLDEN_GATE_POLICY.schema_version,
        "evidence_scope": GOLDEN_GATE_POLICY.evidence_scope,
        "status": "diagnostic_complete",
        "gate_passed": False,
        "thresholds": {"macro_f1_minimum": .90, "macro_f1_target": .95, "high_confidence_error_maximum": .02},
        "diagnostic_only": True,
        "release_claim": False,
        "pilot_only": True,
        "dataset": "iteration-11-pilot14",
        "classifier_fingerprint": fingerprint,
        "development_sources": sorted(development),
        "validation_sources": sorted(validation),
        "excluded_weak_label_sources": sorted(source for source in snapshot if source not in validation and source not in development),
        "raw_n": n,
        "macro_f1": round(macro, 6),
        "macro_f1_percent": round(macro * 100, 4),
        "confusion_matrix": {key: dict(value) for key, value in sorted(confusion.items())},
        "high_confidence_error_rate": round(high_conf_errors / len(high_conf), 6) if high_conf else None,
        "high_confidence_raw_n": len(high_conf),
        "coverage": round(sum(row["state"] == "confirmed" for row in evaluated) / n, 6) if n else None,
        "confirmed_count": sum(row["state"] == "confirmed" for row in evaluated),
        "decision_coverage": round(sum(row["state"] in {"confirmed", "ambiguous"} for row in evaluated) / n, 6) if n else None,
        "rejection_count": sum(row["state"] == "unknown" for row in evaluated),
        "rejection_rate": round(sum(row["state"] == "unknown" for row in evaluated) / n, 6) if n else None,
        "ambiguous_count": sum(row["state"] == "ambiguous" for row in evaluated),
        "ambiguous_rate": round(sum(row["state"] == "ambiguous" for row in evaluated) / n, 6) if n else None,
        "strata": {key: {"numerator": sum(values), "denominator": len(values), "rate": round(sum(values) / len(values), 6), "wilson_95_ci": _wilson(sum(values), len(values))} for key, values in sorted(strata.items())},
        "events": rows,
        "known_limitations": [
            "Temporary pilot only; owner manifest is not frozen and G2 is not passed.",
            "Validation split is source-grouped and fixed before this evaluation; frozen test was not used.",
            "Subtype labels are underpowered and are not promoted to confirmed automatically.",
            "Path A and Path B semantic cues are bounded support/contradiction only; neither localizes or identifies the skater.",
        ],
    }
    result["result_fingerprint"] = "sha256:" + hashlib.sha256(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    return result
