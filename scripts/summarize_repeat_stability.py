from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


WINDOWS_1252_CONTROL_CHARS = {
    0x80: "\u20ac",
    0x82: "\u201a",
    0x83: "\u0192",
    0x84: "\u201e",
    0x85: "\u2026",
    0x86: "\u2020",
    0x87: "\u2021",
    0x88: "\u02c6",
    0x89: "\u2030",
    0x8A: "\u0160",
    0x8B: "\u2039",
    0x8C: "\u0152",
    0x8E: "\u017d",
    0x91: "\u2018",
    0x92: "\u2019",
    0x93: "\u201c",
    0x94: "\u201d",
    0x95: "\u2022",
    0x96: "\u2013",
    0x97: "\u2014",
    0x98: "\u02dc",
    0x99: "\u2122",
    0x9A: "\u0161",
    0x9B: "\u203a",
    0x9C: "\u0153",
    0x9E: "\u017e",
    0x9F: "\u0178",
}


def _windows_1252_mojibake(value: str) -> str:
    return "".join(
        WINDOWS_1252_CONTROL_CHARS.get(byte, chr(byte))
        for byte in value.encode("utf-8")
    )


def _legacy_text_aliases(*values: str) -> tuple[str, ...]:
    aliases: list[str] = []
    for value in values:
        variants = (
            value,
            value.encode("utf-8").decode("latin-1"),
            _windows_1252_mojibake(value),
        )
        for variant in variants:
            if variant not in aliases:
                aliases.append(variant)
    return tuple(aliases)


PROFILE_ALIASES = {
    "step_sequence": "step",
}
PROFILE_KEYFRAME_KEYS = {
    "jump": ("T", "A", "L"),
    "spin": ("\u65cb\u8f6c\u5165", "\u65cb\u8f6c\u4e2d", "\u65cb\u8f6c\u51fa"),
    "spiral": ("\u5cf0\u503c",),
    "step": ("\u6b65\u6cd5\u5e8f\u5217",),
}
PROFILE_KEYFRAME_ALIASES = {
    "\u65cb\u8f6c\u5165": _legacy_text_aliases("\u65cb\u8f6c\u5165"),
    "\u65cb\u8f6c\u4e2d": _legacy_text_aliases("\u65cb\u8f6c\u4e2d"),
    "\u65cb\u8f6c\u51fa": _legacy_text_aliases("\u65cb\u8f6c\u51fa"),
    "\u5cf0\u503c": _legacy_text_aliases("\u5cf0\u503c"),
    "\u6b65\u6cd5\u5e8f\u5217": _legacy_text_aliases("\u6b65\u6cd5\u5e8f\u5217", "\u5cf0\u503c"),
}
TRACKING_FLAG_PREFIXES = (
    "person_tracker_",
    "target_lock_",
    "pose_",
)
SEMANTIC_FLAG_PREFIXES = (
    "semantic_keyframe",
    "video_temporal",
    "mixed_action_profile",
    "mixed_action_video_ai",
)
KEYFRAME_CANDIDATE_FLAG_PREFIXES = (
    "keyframe_candidates_",
    "tal_candidate_",
)
NON_RISK_KEYFRAME_FLAGS = {
    "keyframe_candidates_not_applicable_for_profile",
}
KEYFRAME_STABILITY_THRESHOLD_SEC = 0.1
FORCE_SCORE_STABILITY_THRESHOLD = 2.0


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _batch_items(paths: list[Path], skipped_files: list[dict[str, str]] | None = None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in paths:
        try:
            payload = _read_json(path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            if skipped_files is not None:
                skipped_files.append({"path": str(path), "error": str(exc)})
            continue
        rows = payload.get("videos") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            item = dict(row)
            item["_batch_file"] = path.name
            items.append(item)
    return items


def _analysis_profile(row: dict[str, Any]) -> str:
    raw = str(row.get("analysis_profile") or "unknown").strip().lower() or "unknown"
    return PROFILE_ALIASES.get(raw, raw)


def _profile_keyframe_keys(profile: str) -> tuple[str, ...]:
    return PROFILE_KEYFRAME_KEYS.get(profile, ("T", "A", "L"))


def _profile_keyframe_aliases(key: str) -> tuple[str, ...]:
    return PROFILE_KEYFRAME_ALIASES.get(key, (key,))


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _video_name(row: dict[str, Any]) -> str:
    raw = str(row.get("video") or "").strip()
    if raw:
        return Path(raw).name
    return Path(str(row.get("video_path") or "")).name


def _timestamp_from_map(source: Any, key: str) -> float | None:
    if not isinstance(source, dict):
        return None
    for alias in _profile_keyframe_aliases(key):
        value = source.get(alias)
        if isinstance(value, dict):
            timestamp = _safe_float(value.get("timestamp"))
            if timestamp is not None:
                return timestamp
        else:
            timestamp = _safe_float(value)
            if timestamp is not None:
                return timestamp
    return None


def _timestamp_for_key(row: dict[str, Any], key: str) -> float | None:
    keyframes = row.get("keyframes") if isinstance(row.get("keyframes"), dict) else {}
    direct = _timestamp_from_map(keyframes, key)
    if direct is not None:
        return direct
    profile_keyframes = keyframes.get("profile_keyframes") if isinstance(keyframes.get("profile_keyframes"), dict) else {}
    return _timestamp_from_map(profile_keyframes, key)


def _range(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    return round(max(values) - min(values), 3)


def _run_summary(row: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    keyframes = row.get("keyframes") if isinstance(row.get("keyframes"), dict) else {}
    return {
        "analysis_id": row.get("analysis_id"),
        "batch_file": row.get("_batch_file"),
        "force_score": row.get("force_score"),
        "keyframe_source": keyframes.get("source"),
        "timestamps": {key: _timestamp_for_key(row, key) for key in keys},
        "quality_flags": keyframes.get("quality_flags") if isinstance(keyframes.get("quality_flags"), list) else [],
    }


def _profile_run_summary(row: dict[str, Any]) -> dict[str, Any]:
    keyframes = row.get("keyframes") if isinstance(row.get("keyframes"), dict) else {}
    row_flags = row.get("quality_flags") if isinstance(row.get("quality_flags"), list) else []
    keyframe_flags = keyframes.get("quality_flags") if isinstance(keyframes.get("quality_flags"), list) else []
    return {
        "analysis_id": row.get("analysis_id"),
        "batch_file": row.get("_batch_file"),
        "analysis_profile": _analysis_profile(row),
        "force_score": row.get("force_score"),
        "keyframe_source": keyframes.get("source"),
        "quality_flags": list(dict.fromkeys([*row_flags, *keyframe_flags])),
    }


def _flag_prefix_match(flags: set[str], prefixes: tuple[str, ...]) -> bool:
    return any(flag.startswith(prefixes) for flag in flags)


def _risk_hints_for_repeat_group(
    *,
    flags: set[str],
    keyframe_ranges: dict[str, float | None],
    force_score_range: float | None,
) -> list[str]:
    hints: list[str] = []
    numeric_ranges = [value for value in keyframe_ranges.values() if value is not None]
    keyframe_unstable = bool(numeric_ranges) and max(numeric_ranges) > KEYFRAME_STABILITY_THRESHOLD_SEC
    force_unstable = force_score_range is not None and force_score_range > FORCE_SCORE_STABILITY_THRESHOLD
    if keyframe_unstable:
        hints.append("keyframe_time_unstable")
    if force_unstable:
        hints.append("force_score_unstable")
    if _flag_prefix_match(flags, TRACKING_FLAG_PREFIXES):
        hints.append("tracking_or_pose_signal")
    if _flag_prefix_match(flags, SEMANTIC_FLAG_PREFIXES):
        hints.append("semantic_or_profile_signal")
    risk_keyframe_flags = {flag for flag in flags if flag not in NON_RISK_KEYFRAME_FLAGS}
    if _flag_prefix_match(risk_keyframe_flags, KEYFRAME_CANDIDATE_FLAG_PREFIXES):
        hints.append("keyframe_candidate_or_fusion_signal")
    if keyframe_unstable and _flag_prefix_match(flags, TRACKING_FLAG_PREFIXES):
        hints.append("keyframe_instability_with_tracking_signal")
    if keyframe_unstable and _flag_prefix_match(flags, SEMANTIC_FLAG_PREFIXES):
        hints.append("keyframe_instability_with_semantic_signal")
    return hints


def _risk_hints_for_profile_drift(runs: list[dict[str, Any]]) -> list[str]:
    flags = {
        str(flag)
        for run in runs
        for flag in run.get("quality_flags", [])
        if str(flag).strip()
    }
    hints = ["profile_drift"]
    if "jump" in {str(run.get("analysis_profile") or "") for run in runs}:
        hints.append("tal_membership_unstable")
    if _flag_prefix_match(flags, SEMANTIC_FLAG_PREFIXES):
        hints.append("semantic_or_profile_signal")
    if _flag_prefix_match(flags, TRACKING_FLAG_PREFIXES):
        hints.append("tracking_or_pose_signal")
    return hints


def _compare_url(analysis_id_a: Any, analysis_id_b: Any, frontend_url: str) -> str | None:
    id_a = str(analysis_id_a or "").strip()
    id_b = str(analysis_id_b or "").strip()
    if not id_a or not id_b:
        return None
    return f"{frontend_url.rstrip('/')}/compare/{id_a}/{id_b}"


def _pairwise_comparisons(
    runs: list[dict[str, Any]],
    keys: tuple[str, ...],
    *,
    frontend_url: str,
) -> list[dict[str, Any]]:
    comparisons: list[dict[str, Any]] = []
    for left_index in range(len(runs)):
        for right_index in range(left_index + 1, len(runs)):
            left = runs[left_index]
            right = runs[right_index]
            keyframe_delta = {}
            for key in keys:
                left_ts = _safe_float(left.get("timestamps", {}).get(key) if isinstance(left.get("timestamps"), dict) else None)
                right_ts = _safe_float(right.get("timestamps", {}).get(key) if isinstance(right.get("timestamps"), dict) else None)
                keyframe_delta[key] = (
                    round(right_ts - left_ts, 3)
                    if left_ts is not None and right_ts is not None
                    else None
                )
            left_score = _safe_float(left.get("force_score"))
            right_score = _safe_float(right.get("force_score"))
            comparisons.append(
                {
                    "analysis_id_a": left.get("analysis_id"),
                    "analysis_id_b": right.get("analysis_id"),
                    "compare_url": _compare_url(left.get("analysis_id"), right.get("analysis_id"), frontend_url),
                    "keyframe_delta_sec": keyframe_delta,
                    "max_abs_keyframe_delta_sec": max(
                        (abs(value) for value in keyframe_delta.values() if value is not None),
                        default=None,
                    ),
                    "force_score_delta": (
                        round(right_score - left_score, 3)
                        if left_score is not None and right_score is not None
                        else None
                    ),
                }
            )
    return comparisons


def summarize_repeat_stability(
    paths: list[Path],
    *,
    profile: str | None = None,
    min_runs: int = 2,
    frontend_url: str = "http://localhost:8080",
) -> dict[str, Any]:
    deduped: dict[str, dict[str, Any]] = {}
    skipped_files: list[dict[str, str]] = []
    for row in _batch_items(paths, skipped_files=skipped_files):
        if row.get("status") != "completed":
            continue
        analysis_id = str(row.get("analysis_id") or "").strip()
        video = _video_name(row)
        if not video:
            continue
        key = analysis_id or f"{row.get('_batch_file')}::{video}"
        deduped.setdefault(key, row)

    requested_profile = str(profile or "").strip().lower()
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in deduped.values():
        row_profile = _analysis_profile(row)
        if requested_profile and row_profile != requested_profile:
            continue
        grouped[(_video_name(row), row_profile)].append(row)

    by_video: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in deduped.values():
        by_video[_video_name(row)].append(row)

    profile_drift_groups: list[dict[str, Any]] = []
    for video, rows in by_video.items():
        if len(rows) < max(2, int(min_runs)):
            continue
        profile_counts = Counter(_analysis_profile(row) for row in rows)
        if len(profile_counts) <= 1:
            continue
        runs = [_profile_run_summary(row) for row in rows]
        hints = _risk_hints_for_profile_drift(runs)
        profile_drift_groups.append(
            {
                "video": video,
                "run_count": len(rows),
                "profile_counts": dict(profile_counts),
                "unstable_tal_membership": "jump" in profile_counts and any(
                    profile != "jump" for profile in profile_counts
                ),
                "stability_risk_hints": hints,
                "runs": runs,
            }
        )

    profile_drift_groups.sort(
        key=lambda item: (
            bool(item.get("unstable_tal_membership")),
            item.get("run_count") or 0,
            item.get("video") or "",
        ),
        reverse=True,
    )

    repeat_groups: list[dict[str, Any]] = []
    flag_counts: Counter[str] = Counter()
    min_runs = max(2, int(min_runs))
    for (video, row_profile), rows in grouped.items():
        if len(rows) < min_runs:
            continue
        keys = _profile_keyframe_keys(row_profile)
        runs = [_run_summary(row, keys) for row in rows]
        for run in runs:
            flag_counts.update(str(flag) for flag in run.get("quality_flags", []))
        keyframe_ranges = {
            key: _range([timestamp for run in runs if (timestamp := run["timestamps"].get(key)) is not None])
            for key in keys
        }
        force_scores = [
            score
            for run in runs
            if (score := _safe_float(run.get("force_score"))) is not None
        ]
        numeric_ranges = [value for value in keyframe_ranges.values() if value is not None]
        force_score_range = _range(force_scores)
        flags = {
            str(flag)
            for run in runs
            for flag in run.get("quality_flags", [])
            if str(flag).strip()
        }
        pairwise = _pairwise_comparisons(runs, keys, frontend_url=frontend_url)
        repeat_groups.append(
            {
                "video": video,
                "analysis_profile": row_profile,
                "run_count": len(runs),
                "keyframe_keys": list(keys),
                "keyframe_ranges_sec": keyframe_ranges,
                "max_keyframe_range_sec": max(numeric_ranges) if numeric_ranges else None,
                "within_0_1_sec": bool(numeric_ranges) and max(numeric_ranges) <= 0.1,
                "force_score_range": force_score_range,
                "stability_risk_hints": _risk_hints_for_repeat_group(
                    flags=flags,
                    keyframe_ranges=keyframe_ranges,
                    force_score_range=force_score_range,
                ),
                "pairwise_comparisons": pairwise,
                "compare_url": pairwise[0].get("compare_url") if pairwise else None,
                "runs": runs,
            }
        )

    repeat_groups.sort(
        key=lambda item: (
            item.get("max_keyframe_range_sec") if item.get("max_keyframe_range_sec") is not None else -1,
            item.get("force_score_range") if item.get("force_score_range") is not None else -1,
            item.get("video") or "",
        ),
        reverse=True,
    )
    risk_hint_counts: Counter[str] = Counter()
    for group in repeat_groups:
        risk_hint_counts.update(str(hint) for hint in group.get("stability_risk_hints", []))
    for group in profile_drift_groups:
        risk_hint_counts.update(str(hint) for hint in group.get("stability_risk_hints", []))

    return {
        "input_files": [str(path) for path in paths],
        "completed_unique_analysis_count": len(deduped),
        "repeat_group_count": len(repeat_groups),
        "profile_drift_group_count": len(profile_drift_groups),
        "profile_filter": requested_profile or None,
        "frontend_url": frontend_url,
        "repeat_groups": repeat_groups,
        "profile_drift_groups": profile_drift_groups,
        "stability_risk_hint_counts": dict(risk_hint_counts.most_common()),
        "top_keyframe_flags": dict(flag_counts.most_common(20)),
        "skipped_input_files": skipped_files,
    }


def _write_markdown(summary: dict[str, Any], path: Path) -> None:
    lines = [
        "# Repeat Stability Summary",
        "",
        f"- Completed unique analyses: {summary['completed_unique_analysis_count']}",
        f"- Repeat groups: {summary['repeat_group_count']}",
        f"- Profile drift groups: {summary['profile_drift_group_count']}",
        f"- Profile filter: {summary.get('profile_filter') or 'all'}",
        f"- Skipped input files: {len(summary.get('skipped_input_files', []))}",
        (
            "- Keyframe ranges use profile-specific keys: "
            "jump=T/A/L, "
            "spin=\u65cb\u8f6c\u5165/\u65cb\u8f6c\u4e2d/\u65cb\u8f6c\u51fa, "
            "step=\u6b65\u6cd5\u5e8f\u5217, "
            "spiral=\u5cf0\u503c."
        ),
        "",
        "## Groups",
        "",
    ]
    if summary.get("profile_drift_groups"):
        lines.extend(["## Profile Drift", ""])
        for group in summary.get("profile_drift_groups", []):
            lines.extend(
                [
                    f"### {group['video']}",
                    "",
                    f"- Runs: {group['run_count']}",
                    f"- Profile counts: {json.dumps(group['profile_counts'], ensure_ascii=False, sort_keys=True)}",
                    f"- Unstable T/A/L membership: {group['unstable_tal_membership']}",
                    f"- Stability risk hints: {json.dumps(group.get('stability_risk_hints', []), ensure_ascii=False)}",
                    "",
                ]
            )
    if summary.get("skipped_input_files"):
        lines.extend(["## Skipped Input Files", ""])
        for item in summary.get("skipped_input_files", []):
            lines.extend(
                [
                    f"- `{item.get('path')}`: {item.get('error')}",
                ]
            )
        lines.append("")
    for group in summary.get("repeat_groups", []):
        lines.extend(
            [
                f"### {group['video']} ({group['analysis_profile']})",
                "",
                f"- Runs: {group['run_count']}",
                f"- Keyframe ranges sec: {json.dumps(group['keyframe_ranges_sec'], ensure_ascii=False, sort_keys=True)}",
                f"- Max keyframe range sec: {group['max_keyframe_range_sec']}",
                f"- Within 0.1 sec: {group['within_0_1_sec']}",
                f"- Force score range: {group['force_score_range']}",
                f"- Stability risk hints: {json.dumps(group.get('stability_risk_hints', []), ensure_ascii=False)}",
                f"- Compare URL: {group.get('compare_url')}",
                "",
            ]
        )
        if group.get("pairwise_comparisons"):
            lines.extend(
                [
                    "Pairwise comparisons:",
                    "",
                    json.dumps(group.get("pairwise_comparisons"), ensure_ascii=False, indent=2),
                    "",
                ]
            )
    lines.extend(
        [
            "## Stability Risk Hints",
            "",
            json.dumps(summary.get("stability_risk_hint_counts", {}), ensure_ascii=False, indent=2),
            "",
            "## Top Keyframe Flags",
            "",
            json.dumps(summary.get("top_keyframe_flags", {}), ensure_ascii=False, indent=2),
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _resolve_input_paths(args: argparse.Namespace) -> list[Path]:
    paths = [Path(path) for path in args.batch_json]
    for pattern in args.glob:
        paths.extend(sorted(Path().glob(pattern)))
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize repeat-analysis stability from batch JSON files.")
    parser.add_argument("batch_json", nargs="*", type=Path)
    parser.add_argument("--glob", action="append", default=[], help="Additional glob pattern for batch JSON files.")
    parser.add_argument("--profile", default=None, help="Optional analysis profile filter, for example jump or spin.")
    parser.add_argument("--min-runs", type=int, default=2)
    parser.add_argument("--frontend-url", default="http://localhost:8080")
    parser.add_argument("--output-json", type=Path, default=None)
    parser.add_argument("--output-md", type=Path, default=None)
    args = parser.parse_args()

    paths = _resolve_input_paths(args)
    if not paths:
        parser.error("provide at least one batch JSON path or --glob pattern")
    summary = summarize_repeat_stability(
        paths,
        profile=args.profile,
        min_runs=args.min_runs,
        frontend_url=args.frontend_url,
    )
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.output_md:
        _write_markdown(summary, args.output_md)
    if not args.output_json and not args.output_md:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(
            json.dumps(
                {
                    "repeat_group_count": summary["repeat_group_count"],
                    "profile_drift_group_count": summary["profile_drift_group_count"],
                    "completed_unique_analysis_count": summary["completed_unique_analysis_count"],
                    "output_json": str(args.output_json) if args.output_json else None,
                    "output_md": str(args.output_md) if args.output_md else None,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
