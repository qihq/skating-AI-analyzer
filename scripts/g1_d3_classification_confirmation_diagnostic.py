from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.analysis_v2.action_classification import (
    SOURCE_ONLY_PHYSICAL_CONFIRMATION_VERSION,
    ActionClassificationEvidence,
    classify_action,
)
from app.analysis_v2.event_proposals import (
    EventProposal,
    ProposalEvidenceSample,
    generate_event_proposals,
)


SCHEMA_VERSION = "g1-d3-classification-confirmation-diagnostic.v1"
CLASSIFICATION_POLICY = SOURCE_ONLY_PHYSICAL_CONFIRMATION_VERSION
PIPELINE_FINGERPRINT = "g1-d3-label-agnostic-classification-confirmation.v1"


def _canonical_fingerprint(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _records(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _is_localized(proposal: EventProposal) -> bool:
    return "unlocalized_observability_envelope" not in proposal.evidence_sources


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _classification_evidence(
    source_hash: str,
    proposal: EventProposal,
    samples: Sequence[ProposalEvidenceSample],
) -> ActionClassificationEvidence:
    local = tuple(
        item
        for item in samples
        if proposal.start_pts <= item.pts_sec <= proposal.end_pts
    )
    motion = _mean([
        item.camera_compensated_track_motion * item.camera_reliability
        for item in local
    ])
    pose_dynamics = _mean([item.pose_dynamics for item in local])
    contact = max((item.ice_contact_proxy for item in local), default=0.0)
    periodicity = max((item.periodicity for item in local), default=0.0)
    extension = _mean([item.extension_hold for item in local]) * (1 - .8 * periodicity)
    step_complexity = _mean([item.edge_complexity for item in local])
    return ActionClassificationEvidence(
        source_video_hash=source_hash,
        event_id=proposal.event_id,
        samples=local,
        temporal_features={
            "motion": motion,
            "pose_dynamics": pose_dynamics,
            "ice_contact_proxy": contact,
            "periodicity": periodicity,
            "horizontal_motion": motion * (1 - contact),
            "vertical_excursion": contact,
            "airborne_proxy": contact,
            "turning_motion": periodicity,
            "contact_pattern": contact,
            "extension_proxy": extension,
            "step_complexity": step_complexity,
        },
        tracking_coverage=proposal.tracking_coverage,
        pose_coverage=proposal.pose_coverage,
        observability=proposal.observability,
        evidence_sources=tuple(sorted({*proposal.evidence_sources, "source_only_adapter"})),
        identity_confirmed=proposal.tracking_coverage >= .8,
    )


def _recorded_classifications(
    source: Mapping[str, Any],
) -> tuple[int, int, list[tuple[tuple[float, float], ActionClassificationEvidence]]]:
    recorded = 0
    matched = 0
    evidence_by_interval: list[tuple[tuple[float, float], ActionClassificationEvidence]] = []
    for row in _records(source.get("events")):
        raw_proposal = row.get("proposal")
        raw_evidence = row.get("classification_evidence")
        raw_classification = row.get("classification")
        if (
            not isinstance(raw_proposal, Mapping)
            or not isinstance(raw_evidence, Mapping)
            or not isinstance(raw_classification, Mapping)
        ):
            continue
        evidence = ActionClassificationEvidence.model_validate(raw_evidence)
        generated = classify_action(
            evidence,
            classification_confirmation_upgrade=False,
        ).model_dump(mode="json")
        recorded += 1
        matched += generated == dict(raw_classification)
        interval = (
            round(float(raw_proposal.get("start_pts") or 0), 6),
            round(float(raw_proposal.get("end_pts") or 0), 6),
        )
        evidence_by_interval.append((interval, evidence))
    return recorded, matched, evidence_by_interval


def _aligned_recorded_evidence(
    proposal: EventProposal,
    recorded: Sequence[tuple[tuple[float, float], ActionClassificationEvidence]],
) -> ActionClassificationEvidence | None:
    candidates: list[tuple[float, float, ActionClassificationEvidence]] = []
    for (start, end), evidence in recorded:
        overlap = max(0.0, min(proposal.end_pts, end) - max(proposal.start_pts, start))
        recorded_duration = max(0.0, end - start)
        proposal_duration = max(0.0, proposal.end_pts - proposal.start_pts)
        if overlap <= 0 or recorded_duration <= 0 or proposal_duration <= 0:
            continue
        recorded_coverage = overlap / recorded_duration
        proposal_coverage = overlap / proposal_duration
        if recorded_coverage < .50 or proposal_coverage < .35:
            continue
        candidates.append((recorded_coverage, proposal_coverage, evidence))
    if not candidates:
        return None
    _recorded_coverage, _proposal_coverage, selected = max(
        candidates,
        key=lambda item: (item[0], item[1], item[2].event_id),
    )
    return selected.model_copy(update={
        "event_id": proposal.event_id,
        "tracking_coverage": proposal.tracking_coverage,
        "pose_coverage": proposal.pose_coverage,
        "observability": proposal.observability,
        "evidence_sources": tuple(sorted({*selected.evidence_sources, *proposal.evidence_sources})),
        "identity_confirmed": selected.identity_confirmed and proposal.tracking_coverage >= .8,
    })


def _source_result(source: Mapping[str, Any]) -> dict[str, Any] | None:
    samples = tuple(
        ProposalEvidenceSample.model_validate(item)
        for item in _records(source.get("proposal_samples"))
    )
    try:
        duration = float(source.get("source_duration_sec") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    source_hash = str(source.get("source_video_hash") or "")
    if not source_hash or not samples or duration <= 0:
        return None

    proposals = generate_event_proposals(
        source_video_hash=source_hash,
        source_duration_sec=duration,
        samples=samples,
        pipeline_fingerprint=PIPELINE_FINGERPRINT,
        source_only_localization_upgrade=True,
    ).proposals
    recorded, recorded_matches, recorded_evidence = _recorded_classifications(source)
    before: Counter[str] = Counter()
    after: Counter[str] = Counter()
    upgrades = 0
    aligned_recorded_evidence = 0
    localized_rows: list[dict[str, Any]] = []
    unlocalized_refusals = 0
    for proposal in proposals:
        if not _is_localized(proposal):
            unlocalized_refusals += 1
            continue
        evidence = _aligned_recorded_evidence(proposal, recorded_evidence)
        if evidence is not None:
            aligned_recorded_evidence += 1
        else:
            evidence = _classification_evidence(source_hash, proposal, samples)
        legacy = classify_action(evidence, classification_confirmation_upgrade=False)
        upgraded = classify_action(evidence, classification_confirmation_upgrade=True)
        before[legacy.state] += 1
        after[upgraded.state] += 1
        contributed = bool(upgraded.evidence_summary.get("confirmation_upgrade_contributed"))
        upgrades += contributed
        localized_rows.append({
            "interval": [
                proposal.anchor_start_frame,
                proposal.anchor_end_frame,
                proposal.start_pts,
                proposal.end_pts,
            ],
            "before": [legacy.profile, legacy.state],
            "after": [upgraded.profile, upgraded.state],
            "decision": upgraded.evidence_summary.get("confirmation_decision_reason"),
            "upgraded": contributed,
        })
    return {
        "recorded": recorded,
        "recorded_matches": recorded_matches,
        "localized": len(localized_rows),
        "unlocalized_refusals": unlocalized_refusals,
        "before": before,
        "after": after,
        "upgrades": upgrades,
        "aligned_recorded_evidence": aligned_recorded_evidence,
        "canonical": {
            "source": source_hash,
            "localized": sorted(localized_rows, key=lambda item: item["interval"]),
            "unlocalized_refusals": unlocalized_refusals,
        },
    }


def _counter_payload(counter: Counter[str]) -> dict[str, int]:
    return {key: counter[key] for key in sorted(counter) if counter[key]}


def analyze_diagnostic(diagnostic: Mapping[str, Any]) -> dict[str, Any]:
    videos = _records(diagnostic.get("videos"))
    source_results: list[dict[str, Any]] = []
    runtime_ok_sources = 0
    for video in videos:
        if video.get("status") != "ok":
            continue
        runtime_ok_sources += 1
        raw = video.get("raw_diagnostics")
        raw = raw if isinstance(raw, Mapping) else {}
        source = raw.get("source_evidence")
        source = source if isinstance(source, Mapping) else {}
        result = _source_result(source)
        if result is not None:
            source_results.append(result)

    before: Counter[str] = Counter()
    after: Counter[str] = Counter()
    for item in source_results:
        before.update(item["before"])
        after.update(item["after"])
    aggregate = {
        "input_video_count": len(videos),
        "runtime_ok_source_count": runtime_ok_sources,
        "source_evidence_count": len(source_results),
        "recorded_classification_count": sum(item["recorded"] for item in source_results),
        "baseline_matches_recorded_classification_count": sum(item["recorded_matches"] for item in source_results),
        "recorded_evidence_aligned_proposal_count": sum(item["aligned_recorded_evidence"] for item in source_results),
        "localized_proposal_count_after": sum(item["localized"] for item in source_results),
        "sources_with_localized_after": sum(item["localized"] > 0 for item in source_results),
        "multi_localized_source_count_after": sum(item["localized"] > 1 for item in source_results),
        "classification_state_before": _counter_payload(before),
        "classification_state_after": _counter_payload(after),
        "confirmation_upgrade_count": sum(item["upgrades"] for item in source_results),
        "unlocalized_refusal_count": sum(item["unlocalized_refusals"] for item in source_results),
    }
    canonical_sources = sorted(
        (item["canonical"] for item in source_results),
        key=lambda item: item["source"],
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "classification_policy": CLASSIFICATION_POLICY,
        "pipeline_fingerprint": PIPELINE_FINGERPRINT,
        "diagnostic_only": True,
        "release_claim": False,
        "golden_labels_consumed": False,
        "classification_invoked": True,
        "moments_invoked": False,
        "rotation_invoked": False,
        "formal_pilot_invoked": False,
        "aggregate": aggregate,
        "deterministic_fingerprint": _canonical_fingerprint({
            "schema_version": SCHEMA_VERSION,
            "classification_policy": CLASSIFICATION_POLICY,
            "aggregate": aggregate,
            "sources": canonical_sources,
        }),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare G1-D3 proposal-local classifications without Golden labels or downstream execution.",
    )
    parser.add_argument("--diagnostic", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    diagnostic = json.loads(args.diagnostic.read_text(encoding="utf-8"))
    result = analyze_diagnostic(diagnostic)
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)


if __name__ == "__main__":
    main()
