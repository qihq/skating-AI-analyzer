from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.analysis_v2.event_proposals import (
    SOURCE_ONLY_PHYSICAL_LOCALIZATION_VERSION,
    ProposalEvidenceSample,
    generate_event_proposals,
)


SCHEMA_VERSION = "g1-d2-localized-proposal-diagnostic.v1"
PROPOSAL_POLICY = SOURCE_ONLY_PHYSICAL_LOCALIZATION_VERSION
PIPELINE_FINGERPRINT = "g1-d2-label-agnostic-localized-proposal.v1"


def _canonical_fingerprint(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _records(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _is_localized(proposal: Any) -> bool:
    return "unlocalized_observability_envelope" not in proposal.evidence_sources


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

    common = {
        "source_video_hash": source_hash,
        "source_duration_sec": duration,
        "samples": samples,
        "pipeline_fingerprint": PIPELINE_FINGERPRINT,
    }
    baseline = generate_event_proposals(
        **common,
        source_only_localization_upgrade=False,
    )
    upgraded = generate_event_proposals(
        **common,
        source_only_localization_upgrade=True,
    )
    baseline_localized = [item for item in baseline.proposals if _is_localized(item)]
    upgraded_localized = [item for item in upgraded.proposals if _is_localized(item)]
    physical_upgrade = [
        item
        for item in upgraded_localized
        if SOURCE_ONLY_PHYSICAL_LOCALIZATION_VERSION in item.evidence_sources
    ]
    collection = source.get("proposal_collection")
    collection = collection if isinstance(collection, Mapping) else {}
    raw_recorded_proposals = collection.get("proposals")
    recorded_available = isinstance(raw_recorded_proposals, Sequence) and not isinstance(
        raw_recorded_proposals,
        (str, bytes, bytearray),
    )
    recorded_proposals = _records(raw_recorded_proposals)
    recorded_localized = [
        item
        for item in recorded_proposals
        if "unlocalized_observability_envelope" not in item.get("evidence_sources", ())
    ]
    recorded_payloads = [dict(item) for item in recorded_proposals]
    generated_payloads = [item.model_dump(mode="json") for item in baseline.proposals]
    recorded_intervals = [
        [
            int(item.get("anchor_start_frame") or 0),
            int(item.get("anchor_end_frame") or 0),
            float(item.get("start_pts") or 0),
            float(item.get("end_pts") or 0),
        ]
        for item in recorded_localized
    ]
    baseline_intervals = [
        [item.anchor_start_frame, item.anchor_end_frame, item.start_pts, item.end_pts]
        for item in baseline_localized
    ]
    canonical = {
        "source": source_hash,
        "recorded": recorded_intervals,
        "baseline": baseline_intervals,
        "upgraded": [
            [item.anchor_start_frame, item.anchor_end_frame, item.start_pts, item.end_pts]
            for item in upgraded_localized
        ],
    }
    return {
        "baseline_localized": len(baseline_localized),
        "upgraded_localized": len(upgraded_localized),
        "physical_upgrade": len(physical_upgrade),
        "baseline_unlocalized": sum(not _is_localized(item) for item in baseline.proposals),
        "upgraded_unlocalized": sum(not _is_localized(item) for item in upgraded.proposals),
        "recorded_available": recorded_available,
        "recorded_localized": len(recorded_localized),
        "baseline_matches_recorded": recorded_available and generated_payloads == recorded_payloads,
        "canonical": canonical,
    }


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

    canonical_sources = sorted(
        (item["canonical"] for item in source_results),
        key=lambda item: item["source"],
    )
    aggregate = {
        "input_video_count": len(videos),
        "runtime_ok_source_count": runtime_ok_sources,
        "source_evidence_count": len(source_results),
        "recorded_collection_source_count": sum(item["recorded_available"] for item in source_results),
        "recorded_localized_proposal_count": sum(item["recorded_localized"] for item in source_results),
        "baseline_matches_recorded_source_count": sum(item["baseline_matches_recorded"] for item in source_results),
        "localized_proposal_count_before": sum(item["baseline_localized"] for item in source_results),
        "localized_proposal_count_after": sum(item["upgraded_localized"] for item in source_results),
        "net_new_localized_proposal_count": sum(
            item["upgraded_localized"] - item["baseline_localized"]
            for item in source_results
        ),
        "physical_upgrade_proposal_count": sum(item["physical_upgrade"] for item in source_results),
        "sources_with_localized_before": sum(item["baseline_localized"] > 0 for item in source_results),
        "sources_with_localized_after": sum(item["upgraded_localized"] > 0 for item in source_results),
        "sources_gaining_localized": sum(
            item["baseline_localized"] == 0 and item["upgraded_localized"] > 0
            for item in source_results
        ),
        "sources_with_changed_localized_output": sum(
            item["canonical"]["baseline"] != item["canonical"]["upgraded"]
            for item in source_results
        ),
        "multi_localized_source_count_after": sum(item["upgraded_localized"] > 1 for item in source_results),
        "unlocalized_proposal_count_before": sum(item["baseline_unlocalized"] for item in source_results),
        "unlocalized_proposal_count_after": sum(item["upgraded_unlocalized"] for item in source_results),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "proposal_policy": PROPOSAL_POLICY,
        "pipeline_fingerprint": PIPELINE_FINGERPRINT,
        "diagnostic_only": True,
        "release_claim": False,
        "golden_labels_consumed": False,
        "classification_invoked": False,
        "moments_invoked": False,
        "rotation_invoked": False,
        "formal_pilot_invoked": False,
        "aggregate": aggregate,
        "deterministic_fingerprint": _canonical_fingerprint({
            "schema_version": SCHEMA_VERSION,
            "proposal_policy": PROPOSAL_POLICY,
            "aggregate": aggregate,
            "sources": canonical_sources,
        }),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare G1-D2 localized proposals against the same source-only observation artifact.",
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
