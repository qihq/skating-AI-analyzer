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
    ProposalEvidenceSample,
    generate_event_proposals,
    interval_union_coverage,
)
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
