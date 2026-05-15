from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Snapshot:
    analysis_id: str
    created_at: str
    pipeline_version: str
    analysis_profile: str | None
    action_type: str
    auto_eval: dict[str, Any]
    key_frame_candidates: dict[str, Any]
    fusion_diagnostics: list[str]


def _load_snapshots(path: Path) -> list[Snapshot]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw.get("snapshots") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ValueError("snapshots JSON must be a list or an object with a 'snapshots' list")

    snapshots: list[Snapshot] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        snapshots.append(
            Snapshot(
                analysis_id=str(item.get("analysis_id") or item.get("id") or ""),
                created_at=str(item.get("created_at") or ""),
                pipeline_version=str(item.get("pipeline_version") or "unknown"),
                analysis_profile=item.get("analysis_profile"),
                action_type=str(item.get("action_type") or ""),
                auto_eval=item.get("auto_eval") if isinstance(item.get("auto_eval"), dict) else {},
                key_frame_candidates=item.get("key_frame_candidates") if isinstance(item.get("key_frame_candidates"), dict) else {},
                fusion_diagnostics=_normalize_fusion_diagnostics(item.get("fusion_diagnostics")),
            )
        )
    return [item for item in snapshots if item.analysis_id]


def _normalize_fusion_diagnostics(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, dict):
        summary: list[str] = []
        for key in ("conflict_level", "downgraded_reasons", "needs_human_review", "key_frame_order_invalid"):
            current = value.get(key)
            if current in (None, [], {}, False):
                continue
            if isinstance(current, list):
                summary.extend(str(item) for item in current if item)
            else:
                summary.append(f"{key}={current}")
        return summary
    return []


def _bool_score(value: object) -> float:
    return 1.0 if value is True else 0.0


def _snapshot_score(snapshot: Snapshot) -> dict[str, float]:
    auto_eval = snapshot.auto_eval
    order_valid = _bool_score(auto_eval.get("key_frame_order_valid"))
    phase_valid = _bool_score(auto_eval.get("phase_sequence_valid"))
    conflict_present = 1.0 if auto_eval.get("high_confidence_conflicts") else 0.0
    proxy_score = ((order_valid + phase_valid) / 2.0) - conflict_present
    return {
        "key_frame_order_valid": order_valid,
        "phase_sequence_valid": phase_valid,
        "high_confidence_conflict": conflict_present,
        "accuracy_proxy": proxy_score,
    }


def _group_by_version(snapshots: list[Snapshot]) -> dict[str, list[Snapshot]]:
    groups: dict[str, list[Snapshot]] = defaultdict(list)
    for snapshot in snapshots:
        groups[snapshot.pipeline_version].append(snapshot)
    return dict(groups)


def _summary_for_version(snapshots: list[Snapshot]) -> dict[str, Any]:
    if not snapshots:
        return {
            "total": 0,
            "key_frame_order_valid_rate": 0.0,
            "phase_sequence_valid_rate": 0.0,
            "high_confidence_conflict_rate": 0.0,
            "accuracy_proxy": 0.0,
        }

    scores = [_snapshot_score(snapshot) for snapshot in snapshots]
    total = len(scores)
    order_rate = round(sum(score["key_frame_order_valid"] for score in scores) / total, 4)
    phase_rate = round(sum(score["phase_sequence_valid"] for score in scores) / total, 4)
    conflict_rate = round(sum(score["high_confidence_conflict"] for score in scores) / total, 4)
    accuracy_proxy = round(((order_rate + phase_rate) / 2.0) - conflict_rate, 4)
    return {
        "total": total,
        "key_frame_order_valid_rate": order_rate,
        "phase_sequence_valid_rate": phase_rate,
        "high_confidence_conflict_rate": conflict_rate,
        "accuracy_proxy": accuracy_proxy,
    }


def _select_versions(
    versions: list[str],
    *,
    baseline_version: str | None,
    candidate_version: str | None,
) -> tuple[str, str]:
    if baseline_version and candidate_version:
        return baseline_version, candidate_version
    if len(versions) < 2:
        raise ValueError("Need at least two pipeline versions to compare")
    if candidate_version and candidate_version in versions:
        candidate_index = versions.index(candidate_version)
        baseline_index = max(0, candidate_index - 1)
        return versions[baseline_index], candidate_version
    if baseline_version and baseline_version in versions:
        baseline_index = versions.index(baseline_version)
        candidate_index = min(len(versions) - 1, baseline_index + 1)
        return baseline_version, versions[candidate_index]
    return versions[-2], versions[-1]


def _pairwise_degradations(
    baseline: list[Snapshot],
    candidate: list[Snapshot],
) -> tuple[list[dict[str, Any]], list[str], float]:
    baseline_map = {snapshot.analysis_id: snapshot for snapshot in baseline}
    candidate_map = {snapshot.analysis_id: snapshot for snapshot in candidate}
    shared_ids = sorted(set(baseline_map) & set(candidate_map))
    degraded_samples: list[dict[str, Any]] = []
    conflict_delta_sum = 0.0
    proxy_delta_sum = 0.0

    for analysis_id in shared_ids:
        base_score = _snapshot_score(baseline_map[analysis_id])
        cand_score = _snapshot_score(candidate_map[analysis_id])
        proxy_delta = round(cand_score["accuracy_proxy"] - base_score["accuracy_proxy"], 4)
        conflict_delta = round(
            cand_score["high_confidence_conflict"] - base_score["high_confidence_conflict"],
            4,
        )
        proxy_delta_sum += proxy_delta
        conflict_delta_sum += conflict_delta
        if proxy_delta < 0:
            degraded_samples.append(
                {
                    "analysis_id": analysis_id,
                    "baseline_accuracy_proxy": base_score["accuracy_proxy"],
                    "candidate_accuracy_proxy": cand_score["accuracy_proxy"],
                    "accuracy_proxy_delta": proxy_delta,
                    "baseline_conflict_present": bool(base_score["high_confidence_conflict"]),
                    "candidate_conflict_present": bool(cand_score["high_confidence_conflict"]),
                }
            )

    comparison_count = max(1, len(shared_ids))
    return degraded_samples, shared_ids, round(conflict_delta_sum / comparison_count, 4)


def build_report(
    snapshots: list[Snapshot],
    *,
    baseline_version: str | None = None,
    candidate_version: str | None = None,
) -> dict[str, Any]:
    grouped = _group_by_version(snapshots)
    versions = sorted(grouped, key=lambda version: max((snapshot.created_at for snapshot in grouped[version]), default=""))
    baseline_version, candidate_version = _select_versions(
        versions,
        baseline_version=baseline_version,
        candidate_version=candidate_version,
    )

    baseline = grouped.get(baseline_version, [])
    candidate = grouped.get(candidate_version, [])
    baseline_summary = _summary_for_version(baseline)
    candidate_summary = _summary_for_version(candidate)
    degraded_samples, shared_ids, conflict_rate_delta = _pairwise_degradations(baseline, candidate)

    return {
        "baseline_version": baseline_version,
        "candidate_version": candidate_version,
        "baseline_summary": baseline_summary,
        "candidate_summary": candidate_summary,
        "accuracy_proxy_delta": round(candidate_summary["accuracy_proxy"] - baseline_summary["accuracy_proxy"], 4),
        "high_confidence_conflict_rate_delta": round(
            candidate_summary["high_confidence_conflict_rate"] - baseline_summary["high_confidence_conflict_rate"],
            4,
        ),
        "pairwise_conflict_rate_delta": conflict_rate_delta,
        "shared_analysis_ids": shared_ids,
        "degraded_samples": degraded_samples,
        "degraded_sample_ids": [item["analysis_id"] for item in degraded_samples],
        "version_summaries": {
            version: _summary_for_version(items)
            for version, items in grouped.items()
        },
    }


def _format_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Auto Eval Replay",
        "",
        f"- baseline_version: `{report['baseline_version']}`",
        f"- candidate_version: `{report['candidate_version']}`",
        f"- accuracy_proxy_delta: `{report['accuracy_proxy_delta']}`",
        f"- high_confidence_conflict_rate_delta: `{report['high_confidence_conflict_rate_delta']}`",
        f"- degraded_sample_ids: `{', '.join(report['degraded_sample_ids']) or '-'}`",
        "",
        "## Version Summaries",
    ]
    for version, summary in report["version_summaries"].items():
        lines.extend(
            [
                f"- `{version}`: total={summary['total']}, "
                f"order={summary['key_frame_order_valid_rate']}, "
                f"phase={summary['phase_sequence_valid_rate']}, "
                f"conflict={summary['high_confidence_conflict_rate']}, "
                f"proxy={summary['accuracy_proxy']}",
            ]
        )
    if report["degraded_samples"]:
        lines.extend(["", "## Degraded Samples"])
        for item in report["degraded_samples"]:
            lines.append(
                f"- `{item['analysis_id']}`: delta={item['accuracy_proxy_delta']}, "
                f"baseline={item['baseline_accuracy_proxy']}, candidate={item['candidate_accuracy_proxy']}"
            )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay auto-eval snapshots and compare pipeline versions.")
    parser.add_argument("snapshots_json", type=Path, help="Path to exported snapshots JSON file")
    parser.add_argument("--baseline-version", default=None, help="Baseline pipeline version to compare")
    parser.add_argument("--candidate-version", default=None, help="Candidate pipeline version to compare")
    parser.add_argument("--format", choices=("json", "markdown"), default="json", help="Output format")
    args = parser.parse_args()

    snapshots = _load_snapshots(args.snapshots_json)
    report = build_report(
        snapshots,
        baseline_version=args.baseline_version,
        candidate_version=args.candidate_version,
    )

    if args.format == "markdown":
        print(_format_markdown(report))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
