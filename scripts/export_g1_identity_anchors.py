from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a private one-anchor-per-source G1 identity manifest.")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo / "backend"))
    from app.analysis_v2.evaluation.identity_anchor import build_parent_identity_anchor_manifest

    workspace = json.loads(args.workspace.read_text(encoding="utf-8"))
    manifest = build_parent_identity_anchor_manifest(workspace)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({
        "schema_version": manifest.schema_version,
        "anchor_count": len(manifest.anchors),
        "evaluated_targets_consumed": manifest.evaluated_targets_consumed,
        "release_claim": manifest.release_claim,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
