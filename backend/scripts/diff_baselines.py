"""Diff two eval_against_gt.py baseline reports.

Phase 0.4 of the iteration roadmap (see
plans/codex-multi-pose-allinone-fixes-eventual-lagoon.md).

Usage::

    python -m scripts.diff_baselines baseline_a.json baseline_b.json
    # or
    python scripts/diff_baselines.py baseline_off.json baseline_on.json

Compares the top-level ``summary`` and each ``stratum_summary`` entry, plus the
``failures`` and ``top_quality_flags`` lists. Prints a per-metric delta table
(absolute change, percent change) and lists newly-introduced / resolved failure
samples. Exit code is 0 even if metrics regress —— the caller decides
significance (roadmap rule: any stratum regressing >10% blocks a merge).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


# Metrics where "lower is better" — for these, a positive delta means regression.
_LOWER_IS_BETTER = {
    "keyframe_mean_error_sec",
    "keyframe_median_error_sec",
    "keyframe_max_error_sec",
    "identity_switches",
    "failure_count",
}
# Metrics where "higher is better" — a negative delta means regression.
_HIGHER_IS_BETTER = {
    "identity_accuracy",
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _fmt_num(value: float | None) -> str:
    if value is None:
        return "  -  "
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _delta(old: float | None, new: float | None) -> tuple[float | None, float | None]:
    """Return (absolute delta, percent delta). None when undefined."""

    if old is None or new is None:
        return None, None
    abs_delta = new - old
    pct = None
    if old != 0:
        pct = (abs_delta / old) * 100.0
    return abs_delta, pct


def _direction(metric: str, abs_delta: float | None) -> str:
    """Tag a delta as good/bad/flat based on whether lower or higher is better."""

    if abs_delta is None or abs_delta == 0:
        return "flat"
    if metric in _LOWER_IS_BETTER:
        return "good" if abs_delta < 0 else "bad"
    if metric in _HIGHER_IS_BETTER:
        return "good" if abs_delta > 0 else "bad"
    return "neutral"


def _print_summary_diff(title: str, old: dict[str, Any], new: dict[str, Any]) -> None:
    print(f"\n== {title} ==")
    keys = list(old.keys())
    # include any new keys in `new`
    for key in new.keys():
        if key not in keys:
            keys.append(key)
    print(f"  {'metric':<32} {'baseline':>10} {'new':>10} {'delta':>10} {'pct':>9}  dir")
    for key in keys:
        old_v = old.get(key)
        new_v = new.get(key)
        if isinstance(old_v, (int, float)) or isinstance(new_v, (int, float)):
            abs_d, pct = _delta(
                old_v if isinstance(old_v, (int, float)) else None,
                new_v if isinstance(new_v, (int, float)) else None,
            )
            dir_tag = _direction(key, abs_d)
            pct_str = f"{pct:+.1f}%" if pct is not None else "   -   "
            print(
                f"  {key:<32} {_fmt_num(old_v):>10} {_fmt_num(new_v):>10} "
                f"{(_fmt_num(abs_d) if abs_d is not None else '  -  '):>10} {pct_str:>9}  {dir_tag}"
            )
        else:
            print(f"  {key:<32} {str(old_v):>10} {str(new_v):>10}")


def _print_failures_diff(old: dict[str, Any], new: dict[str, Any]) -> None:
    old_fails = {f.get("sample_id"): f for f in old.get("failures", [])}
    new_fails = {f.get("sample_id"): f for f in new.get("failures", [])}
    resolved = sorted(set(old_fails) - set(new_fails))
    introduced = sorted(set(new_fails) - set(old_fails))

    if resolved:
        print("\n-- Resolved failures (in baseline, gone in new) --")
        for sample_id in resolved:
            print(f"  + {sample_id}: {old_fails[sample_id].get('failure_reasons')}")
    if introduced:
        print("\n-- Introduced failures (in new, not in baseline) --")
        for sample_id in introduced:
            print(f"  - {sample_id}: {new_fails[sample_id].get('failure_reasons')}")
    if not resolved and not introduced:
        print("\n-- Failures: identical set --")


def _print_quality_flags_diff(old: dict[str, Any], new: dict[str, Any]) -> None:
    old_flags = {f.get("flag"): f.get("count", 0) for f in old.get("top_quality_flags", [])}
    new_flags = {f.get("flag"): f.get("count", 0) for f in new.get("top_quality_flags", [])}
    all_flags = sorted(set(old_flags) | set(new_flags))
    changed = []
    for flag in all_flags:
        old_c = old_flags.get(flag, 0)
        new_c = new_flags.get(flag, 0)
        if old_c != new_c:
            changed.append((flag, old_c, new_c))
    if not changed:
        print("\n-- Quality flags: unchanged --")
        return
    print("\n-- Quality flag count changes --")
    print(f"  {'flag':<55} {'baseline':>9} {'new':>9} {'delta':>7}")
    for flag, old_c, new_c in changed:
        print(f"  {str(flag):<55} {old_c:>9} {new_c:>9} {new_c - old_c:>+7}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Diff two eval_against_gt baseline reports.")
    parser.add_argument("baseline", type=Path, help="Earlier baseline JSON.")
    parser.add_argument("new", type=Path, help="New baseline JSON to compare against the earlier one.")
    args = parser.parse_args()

    old = _load_json(args.baseline)
    new = _load_json(args.new)

    print(f"baseline: {args.baseline}")
    print(f"new:      {args.new}")

    _print_summary_diff("Overall summary", old.get("summary", {}), new.get("summary", {}))

    old_strata = old.get("stratum_summary", {}) or {}
    new_strata = new.get("stratum_summary", {}) or {}
    for stratum in sorted(set(old_strata) | set(new_strata)):
        _print_summary_diff(
            f"Stratum: {stratum}",
            old_strata.get(stratum, {}),
            new_strata.get(stratum, {}),
        )

    _print_failures_diff(old, new)
    _print_quality_flags_diff(old, new)
    return 0


if __name__ == "__main__":
    sys.exit(main())