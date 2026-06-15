from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.batch_api_analyze_videos import (
    BatchClient,
    _analysis_summary,
    _load_target_selection_map,
)


DEFAULT_OUTPUT_DIR = Path("tmp") / "api-batch-skate-analysis"
IN_PROGRESS_STATUSES = {"pending", "processing", "extracting_frames", "analyzing", "generating_report"}
MANUAL_LOCK_REQUIRED_FLAG = "manual_override"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _selection_review_metadata(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return {}
    metadata: dict[str, Any] = {}
    for key in ("_review_label", "_review_row_count", "_selected_count", "_missing_count", "_complete", "_source"):
        if key in payload:
            metadata[key.lstrip("_")] = payload.get(key)
    return metadata


def _review_rows(path: Path) -> dict[str, dict[str, Any]]:
    payload = _read_json(path)
    rows = payload.get("rows") if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return {}
    by_video: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        video = str(row.get("video") or "").strip()
        if video:
            by_video[video] = row
    return by_video


def _target_payload(selection: dict[str, Any]) -> dict[str, Any] | None:
    manual_bbox = selection.get("manual_bbox")
    if isinstance(manual_bbox, dict):
        return {"manual_bbox": manual_bbox}
    candidate_id = str(selection.get("candidate_id") or "").strip()
    if candidate_id:
        return {"candidate_id": candidate_id}
    return None


def _review_candidate_ids(row: dict[str, Any]) -> set[str]:
    candidates = row.get("candidates") if isinstance(row.get("candidates"), list) else []
    return {
        str(candidate.get("id") or "").strip()
        for candidate in candidates
        if isinstance(candidate, dict) and str(candidate.get("id") or "").strip()
    }


def _validate_selection(video: str, row: dict[str, Any] | None, selection: dict[str, Any]) -> str | None:
    if row is None:
        return "video_not_found_in_review"
    payload = _target_payload(selection)
    if payload is None:
        return "missing_candidate_id_or_manual_bbox"
    manual_bbox = payload.get("manual_bbox")
    if isinstance(manual_bbox, dict):
        return None
    candidate_id = str(payload.get("candidate_id") or "").strip()
    candidate_ids = _review_candidate_ids(row)
    if candidate_ids and candidate_id not in candidate_ids:
        return "candidate_id_not_in_review"
    return None


def validate_target_selection_reviews(
    *,
    review_json: Path,
    target_selection_json: Path,
    limit: int | None = None,
    require_complete: bool = False,
) -> dict[str, Any]:
    rows_by_video = _review_rows(review_json)
    review_metadata = _selection_review_metadata(target_selection_json)
    selections = _load_target_selection_map(target_selection_json)
    selected_videos = list(selections)
    if limit is not None:
        selected_videos = selected_videos[: max(0, int(limit))]
    failures: list[dict[str, str]] = []
    valid_videos: list[str] = []
    for video in selected_videos:
        reason = _validate_selection(video, rows_by_video.get(video), selections[video])
        if reason:
            failures.append({"video": video, "error": reason})
        else:
            valid_videos.append(video)
    missing_review_videos = [
        video
        for video in rows_by_video
        if video not in selections
    ]
    if require_complete:
        failures.extend(
            {"video": video, "error": "missing_required_selection"}
            for video in missing_review_videos
        )
    return {
        "review_row_count": len(rows_by_video),
        "total_selections": len(selections),
        "matched_selections": len(valid_videos),
        "missing_selection_count": len(missing_review_videos),
        "missing_selection_samples": missing_review_videos[:20],
        "require_complete": require_complete,
        "selection_review_metadata": review_metadata,
        "validation_failures": failures,
        "valid_videos": valid_videos,
    }


def _poll_analysis(
    api: BatchClient,
    analysis_id: str,
    *,
    poll_seconds: float,
    max_wait_seconds: float,
) -> dict[str, Any]:
    started = time.monotonic()
    while True:
        analysis = api.get_json(f"/api/analysis/{analysis_id}", is_parent_request="true")
        status = str(analysis.get("status") or "")
        if status not in IN_PROGRESS_STATUSES:
            return analysis
        if time.monotonic() - started > max_wait_seconds:
            raise TimeoutError(f"analysis {analysis_id} did not finish within {max_wait_seconds:.0f}s")
        time.sleep(poll_seconds)


def _manual_lock_confirmed(analysis: dict[str, Any], payload: dict[str, Any]) -> bool:
    target_lock = analysis.get("target_lock") if isinstance(analysis.get("target_lock"), dict) else {}
    if target_lock.get(MANUAL_LOCK_REQUIRED_FLAG) is not True:
        return False
    if isinstance(payload.get("manual_bbox"), dict):
        return str(target_lock.get("status") or "") == "manual" and isinstance(target_lock.get("selected_bbox"), dict)
    candidate_id = str(payload.get("candidate_id") or "").strip()
    return bool(candidate_id) and str(target_lock.get("selected_candidate_id") or "").strip() == candidate_id


def _video_path_for_row(row: dict[str, Any], video_dir: Path | None) -> Path:
    raw = str(row.get("video_path") or "").strip()
    if raw:
        return Path(raw)
    video = str(row.get("video") or "").strip()
    if video_dir is not None:
        return video_dir / video
    return Path(video)


def _apply_one(
    api: BatchClient,
    *,
    video: str,
    row: dict[str, Any],
    selection: dict[str, Any],
    video_dir: Path | None,
    poll_seconds: float,
    max_wait_seconds: float,
    require_completed: bool = False,
) -> dict[str, Any]:
    analysis_id = str(row.get("analysis_id") or selection.get("_analysis_id") or "").strip()
    if not analysis_id:
        raise ValueError(f"{video} is missing analysis_id")
    payload = _target_payload(selection)
    if payload is None:
        raise ValueError(f"{video} has no candidate_id or manual_bbox")
    api.post_json(f"/api/analysis/{analysis_id}/target-lock", payload)
    analysis = _poll_analysis(
        api,
        analysis_id,
        poll_seconds=poll_seconds,
        max_wait_seconds=max_wait_seconds,
    )
    if not _manual_lock_confirmed(analysis, payload):
        target_lock = analysis.get("target_lock") if isinstance(analysis.get("target_lock"), dict) else {}
        raise RuntimeError(
            "manual target identity lock was not confirmed "
            f"(status={target_lock.get('status')}, manual_override={target_lock.get(MANUAL_LOCK_REQUIRED_FLAG)}, "
            f"selected_candidate_id={target_lock.get('selected_candidate_id')})"
        )
    if require_completed and str(analysis.get("status") or "") != "completed":
        raise RuntimeError(
            "analysis did not complete after applying manual target identity lock "
            f"(status={analysis.get('status')})"
        )
    return _analysis_summary(
        _video_path_for_row(row, video_dir),
        analysis,
        created=False,
        requested_action_type=None,
        requested_action_subtype=None,
    )


def _write_outputs(output_dir: Path, label: str, payload: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{label}.json"
    md_path = output_dir / f"{label}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        f"# Applied Target Selection - {label}",
        "",
        f"- Generated: {payload.get('generated_at')}",
        f"- Total selections: {payload.get('total_selections')}",
        f"- Applied: {payload.get('applied_count')}",
        f"- Failures: {len(payload.get('failures', []))}",
        f"- Status counts: {json.dumps(payload.get('status_counts', {}), ensure_ascii=False, sort_keys=True)}",
        "",
        "## Videos",
        "",
    ]
    for item in payload.get("videos", []):
        lines.append(
            f"- {item.get('video')}: {item.get('status')} profile={item.get('analysis_profile')} "
            f"score={item.get('force_score')} analysis={item.get('analysis_id')}"
        )
    failures = payload.get("failures") if isinstance(payload.get("failures"), list) else []
    if failures:
        lines.extend(["", "## Failures", ""])
        for failure in failures:
            lines.append(f"- {failure.get('video')}: {failure.get('error')}")
    md_path.write_text("\n".join(lines), encoding="utf-8")


def apply_target_selection_reviews(
    *,
    review_json: Path,
    target_selection_json: Path,
    base_url: str,
    output_dir: Path,
    label: str,
    video_dir: Path | None,
    timeout: float,
    poll_seconds: float,
    max_wait_seconds: float,
    limit: int | None = None,
    require_complete: bool = False,
    require_completed: bool = False,
) -> dict[str, Any]:
    rows_by_video = _review_rows(review_json)
    selections = _load_target_selection_map(target_selection_json)
    validation = validate_target_selection_reviews(
        review_json=review_json,
        target_selection_json=target_selection_json,
        limit=limit,
        require_complete=require_complete,
    )
    invalid = validation.get("validation_failures") if isinstance(validation.get("validation_failures"), list) else []
    if invalid:
        payload = {
            "label": label,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "base_url": base_url,
            "review_json": str(review_json),
            "target_selection_json": str(target_selection_json),
            "total_selections": len(selections),
            "matched_selections": 0,
            "applied_count": 0,
            "status_counts": {},
            "videos": [],
            "failures": invalid,
            "validation": validation,
        }
        _write_outputs(output_dir, label, payload)
        return payload
    videos = list(validation.get("valid_videos", []))
    if limit is not None:
        videos = videos[: max(0, int(limit))]

    api = BatchClient(base_url, timeout)
    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    try:
        for index, video in enumerate(videos, start=1):
            print(f"[{index}/{len(videos)}] applying target selection for {video}", flush=True)
            try:
                summary = _apply_one(
                    api,
                    video=video,
                    row=rows_by_video[video],
                    selection=selections[video],
                    video_dir=video_dir,
                    poll_seconds=poll_seconds,
                    max_wait_seconds=max_wait_seconds,
                    require_completed=require_completed,
                )
                results.append(summary)
                print(
                    f"  done status={summary.get('status')} profile={summary.get('analysis_profile')} "
                    f"score={summary.get('force_score')}",
                    flush=True,
                )
            except Exception as exc:  # noqa: BLE001
                failures.append({"video": video, "error": f"{type(exc).__name__}: {exc}"})
                print(f"  failed {type(exc).__name__}: {exc}", flush=True)
    finally:
        api.close()

    status_counts = Counter(str(item.get("status") or "unknown") for item in results)
    payload = {
        "label": label,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "base_url": base_url,
        "review_json": str(review_json),
        "target_selection_json": str(target_selection_json),
        "total_selections": len(selections),
        "matched_selections": len(videos),
        "applied_count": len(results),
        "status_counts": dict(status_counts),
        "videos": results,
        "failures": failures,
        "validation": validation,
    }
    _write_outputs(output_dir, label, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply reviewed target selections to awaiting analyses and wait for completion.")
    parser.add_argument("--review-json", type=Path, required=True)
    parser.add_argument("--target-selection-json", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--label", default=datetime.now().strftime("target-selection-apply-%Y%m%d-%H%M%S"))
    parser.add_argument("--video-dir", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    parser.add_argument("--max-wait-seconds", type=float, default=900.0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true", help="Validate the selection JSON without posting target locks.")
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="Fail validation if any review row is missing a target selection.",
    )
    parser.add_argument(
        "--require-completed",
        action="store_true",
        help="Fail an applied row unless the analysis finishes with status=completed.",
    )
    args = parser.parse_args()

    if args.dry_run:
        payload = validate_target_selection_reviews(
            review_json=args.review_json,
            target_selection_json=args.target_selection_json,
            limit=args.limit,
            require_complete=args.require_complete,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if not payload["validation_failures"] else 1

    payload = apply_target_selection_reviews(
        review_json=args.review_json,
        target_selection_json=args.target_selection_json,
        base_url=args.base_url,
        output_dir=args.output_dir,
        label=args.label,
        video_dir=args.video_dir,
        timeout=args.timeout,
        poll_seconds=args.poll_seconds,
        max_wait_seconds=args.max_wait_seconds,
        limit=args.limit,
        require_complete=args.require_complete,
        require_completed=args.require_completed,
    )
    print(json.dumps({key: payload[key] for key in ("total_selections", "matched_selections", "applied_count", "status_counts", "failures")}, ensure_ascii=False, indent=2))
    return 0 if not payload["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
