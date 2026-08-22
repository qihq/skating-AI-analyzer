from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Dry-run the G1 evaluator with source-only diagnostic predictions.")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--diagnostic", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    from app.analysis_v2.evaluation.golden_schema import GoldenDatasetV2
    from app.analysis_v2.evaluation.pilot_evaluator import evaluate_pilot
    from app.analysis_v2.evaluation.source_diagnostic_prediction_adapter import (
        build_source_diagnostic_prediction_result,
    )

    workspace = json.loads(args.workspace.read_text(encoding="utf-8"))
    dataset = GoldenDatasetV2.model_validate(_dataset_payload_from_workspace(workspace))
    diagnostic = json.loads(args.diagnostic.read_text(encoding="utf-8"))
    adapter_result = build_source_diagnostic_prediction_result(
        dataset,
        diagnostic,
        pipeline_fingerprint="source-only-g1-r95.diagnostic-v2",
        evaluation_masks=["action", "key_moments", "rotation"],
    )
    bundle = adapter_result.bundle
    private, sanitized = evaluate_pilot(dataset, bundle)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({
            "adapter_diagnostics": adapter_result.diagnostics,
            "bundle": bundle.model_dump(mode="json"),
            "private": private,
            "sanitized": sanitized,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({
        "prediction_count": len(bundle.predictions),
        "adapter_diagnostics": adapter_result.diagnostics,
        "aggregate": sanitized["aggregate"],
        "failed_event_count": len(sanitized["failed_events"]),
        "deterministic_fingerprint": sanitized["deterministic_fingerprint"],
    }, ensure_ascii=False, indent=2))


def _dataset_payload_from_workspace(workspace: dict) -> dict:
    revision = int(workspace["revision"])
    revision_metadata = {
        "revision": revision,
        "schema_version": "golden-dataset.v2",
        "annotator_alias": "runtime-workspace",
        "provenance": "migration",
        "created_at": "2026-08-22T00:00:00Z",
        "parent_revision": revision - 1 if revision > 1 else None,
        "change_note": "Reconstructed non-semantic metadata for local evaluator dry-run only.",
    }
    sources = []
    for source in workspace.get("sources", []):
        source = dict(source)
        source["private_source_reference"] = f"runtime://{source['source_sha256']}"
        sources.append(source)
    return {
        "schema_version": "golden-dataset.v2",
        "dataset_id": workspace["dataset_id"],
        "revision": revision_metadata,
        "sources": sources,
        "events": workspace.get("events", []),
        "tracks": workspace.get("tracks", []),
        "poses": workspace.get("poses", []),
    }


if __name__ == "__main__":
    main()
