from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


RISK_PRIORITY = {
    "same_anchor_competitor": 100,
    "selected_pair_competitor": 90,
    "high_competitor_load": 80,
    "foreground_deprioritized_alternative": 70,
    "foreground_context_small_target": 60,
    "zoomed_multiperson": 50,
    "compact_motion_reselected": 40,
}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _risk_score(tags: list[str]) -> int:
    return sum(RISK_PRIORITY.get(str(tag), 10) for tag in tags)


def _rows(review_json: Path) -> list[dict[str, Any]]:
    payload = _read_json(review_json)
    rows = payload.get("rows") if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return []
    enriched: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        tags = [str(tag) for tag in row.get("review_risk_tags", []) if str(tag)]
        candidates = row.get("candidates") if isinstance(row.get("candidates"), list) else []
        enriched.append(
            {
                "video": str(row.get("video") or ""),
                "analysis_id": str(row.get("analysis_id") or ""),
                "target_lock_status": str(row.get("target_lock_status") or ""),
                "auto_candidate_id": str(row.get("auto_candidate_id") or ""),
                "candidate_count": len(candidates),
                "risk_score": _risk_score(tags),
                "risk_tags": tags,
                "overlay_image": str(row.get("overlay_image") or ""),
            }
        )
    return sorted(enriched, key=lambda item: (-int(item["risk_score"]), item["video"]))


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "video",
                "analysis_id",
                "target_lock_status",
                "auto_candidate_id",
                "candidate_count",
                "risk_score",
                "risk_tags",
                "overlay_image",
            ],
        )
        writer.writeheader()
        for row in rows:
            out = dict(row)
            out["risk_tags"] = ", ".join(row["risk_tags"])
            writer.writerow(out)


def _write_markdown(rows: list[dict[str, Any]], path: Path) -> None:
    tag_counts = Counter(tag for row in rows for tag in row["risk_tags"])
    lines = [
        "# Target Review Priority List",
        "",
        f"- Rows: {len(rows)}",
        f"- Risk tags: {json.dumps(dict(tag_counts), ensure_ascii=False, sort_keys=True)}",
        "",
        "| Priority | Video | Risk Tags | Candidates | Auto Candidate | Analysis |",
        "| ---: | --- | --- | ---: | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["risk_score"]),
                    row["video"],
                    ", ".join(row["risk_tags"]),
                    str(row["candidate_count"]),
                    row["auto_candidate_id"],
                    row["analysis_id"],
                ]
            )
            + " |"
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a priority list for manual target preview review.")
    parser.add_argument("review_json", type=Path)
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()

    rows = _rows(args.review_json)
    _write_csv(rows, args.output_csv)
    _write_markdown(rows, args.output_md)
    print(f"wrote {len(rows)} rows to {args.output_csv} and {args.output_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
