from __future__ import annotations

import argparse
import json
import mimetypes
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

import httpx


VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
DEFAULT_VIDEO_DIR = Path(r"C:\Users\qihq\Pictures\skate testing video")
DEFAULT_OUTPUT_DIR = Path("tmp") / "api-batch-skate-analysis"
DEFAULT_NOTE_PREFIX = "codex api full coverage 2026-05-30"
IN_PROGRESS_STATUSES = {"pending", "processing", "extracting_frames", "analyzing", "generating_report"}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _quality_flags(*payloads: Any) -> list[str]:
    flags: list[str] = []
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        values = payload.get("quality_flags")
        if isinstance(values, list):
            for value in values:
                text = str(value).strip()
                if text and text not in flags:
                    flags.append(text)
    return flags


def _bbox_area(bbox: Any) -> float:
    if not isinstance(bbox, dict):
        return 0.0
    return max(0.0, _safe_float(bbox.get("width"))) * max(0.0, _safe_float(bbox.get("height")))


def _state_counts(items: Any, key: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                counts[str(item.get(key) or "unknown")] += 1
    return dict(counts)


def _pose_summary(analysis: dict[str, Any]) -> dict[str, Any]:
    pose_data = analysis.get("pose_data") if isinstance(analysis.get("pose_data"), dict) else {}
    diagnostics = pose_data.get("pose_diagnostics") if isinstance(pose_data.get("pose_diagnostics"), dict) else {}
    frames = diagnostics.get("frames") if isinstance(diagnostics.get("frames"), list) else []
    total = int(diagnostics.get("total_frames") or len(frames) or 0)
    tracked = int(diagnostics.get("tracked_frames") or 0)
    lost = int(diagnostics.get("lost_frames") or 0)
    low_conf = int(diagnostics.get("low_confidence_frames") or 0)
    interpolated = int(diagnostics.get("interpolated_frames") or 0)
    return {
        "mode": diagnostics.get("mode"),
        "total_frames": total,
        "tracked_frames": tracked,
        "lost_frames": lost,
        "low_confidence_frames": low_conf,
        "interpolated_frames": interpolated,
        "tracked_ratio": round(tracked / max(total, 1), 4),
        "lost_ratio": round(lost / max(total, 1), 4),
        "low_confidence_ratio": round(low_conf / max(total, 1), 4),
        "state_counts": _state_counts(frames, "tracking_state"),
    }


def _keyframe_summary(analysis: dict[str, Any]) -> dict[str, Any]:
    bio_data = analysis.get("bio_data") if isinstance(analysis.get("bio_data"), dict) else {}
    candidates = bio_data.get("key_frame_candidates") if isinstance(bio_data.get("key_frame_candidates"), dict) else {}
    key_frames = bio_data.get("key_frames") if isinstance(bio_data.get("key_frames"), dict) else {}
    timestamps: list[float] = []
    confidences: list[float] = []
    result: dict[str, Any] = {
        "key_frames": {key: key_frames.get(key) for key in ("T", "A", "L")},
        "complete": False,
        "tal_order_valid": False,
        "coverage_score": 0.0,
        "average_confidence": 0.0,
        "quality_flags": candidates.get("quality_flags") if isinstance(candidates.get("quality_flags"), list) else [],
    }
    for key in ("T", "A", "L"):
        item = candidates.get(key) if isinstance(candidates.get(key), dict) else {}
        confidence = _safe_float(item.get("confidence"))
        timestamp = item.get("timestamp")
        result[key] = {
            "frame_id": item.get("frame_id"),
            "timestamp": timestamp,
            "confidence": round(confidence, 4),
            "warnings": item.get("warnings") if isinstance(item.get("warnings"), list) else [],
        }
        if item.get("frame_id") and confidence >= 0.35:
            confidences.append(confidence)
        if timestamp is not None:
            timestamps.append(_safe_float(timestamp))
    result["complete"] = len(confidences) == 3
    result["coverage_score"] = round(len(confidences) / 3.0, 4)
    result["average_confidence"] = round(sum(confidences) / len(confidences), 4) if confidences else 0.0
    result["tal_order_valid"] = len(timestamps) == 3 and timestamps[0] < timestamps[1] < timestamps[2]
    return result


def _target_summary(analysis: dict[str, Any]) -> dict[str, Any]:
    target_lock = analysis.get("target_lock") if isinstance(analysis.get("target_lock"), dict) else {}
    diagnostics = target_lock.get("person_tracker_diagnostics")
    return {
        "status": target_lock.get("status") or analysis.get("target_lock_status"),
        "lock_confidence": round(_safe_float(target_lock.get("lock_confidence")), 4),
        "selected_candidate_id": target_lock.get("selected_candidate_id"),
        "selected_bbox_area": round(_bbox_area(target_lock.get("selected_bbox")), 6),
        "quality_flags": target_lock.get("quality_flags") if isinstance(target_lock.get("quality_flags"), list) else [],
        "tracker_state_counts": _state_counts(diagnostics, "state"),
    }


def _video_temporal_summary(analysis: dict[str, Any]) -> dict[str, Any]:
    vt = analysis.get("video_temporal_diagnostics")
    if not isinstance(vt, dict):
        return {"available": False}
    selected = vt.get("selected_semantic_frames") if isinstance(vt.get("selected_semantic_frames"), list) else []
    return {
        "available": True,
        "provider": vt.get("video_ai_provider"),
        "model": vt.get("video_ai_model"),
        "confidence": vt.get("video_ai_confidence"),
        "timestamp_source": vt.get("timestamp_source"),
        "resolver_source": vt.get("resolver_source"),
        "used_semantic_frames": bool(vt.get("used_semantic_frames")),
        "used_legacy_sampled_frames": bool(vt.get("used_legacy_sampled_frames")),
        "selected_count": len(selected),
        "quality_flags": vt.get("quality_flags") if isinstance(vt.get("quality_flags"), list) else [],
        "retry_rejection_flags": vt.get("retry_rejection_flags") if isinstance(vt.get("retry_rejection_flags"), list) else [],
    }


def _analysis_summary(video_path: Path, analysis: dict[str, Any], *, created: bool) -> dict[str, Any]:
    cross_validation = analysis.get("cross_validation") if isinstance(analysis.get("cross_validation"), dict) else {}
    vision = analysis.get("vision_structured") if isinstance(analysis.get("vision_structured"), dict) else {}
    auto_eval = cross_validation.get("auto_eval") if isinstance(cross_validation.get("auto_eval"), dict) else {}
    pose = _pose_summary(analysis)
    keyframes = _keyframe_summary(analysis)
    target = _target_summary(analysis)
    video_temporal = _video_temporal_summary(analysis)
    return {
        "video": video_path.name,
        "video_path": str(video_path),
        "analysis_id": analysis.get("id"),
        "report_url": f"http://localhost:5173/report/{analysis.get('id')}" if analysis.get("id") else None,
        "created_by_batch": created,
        "status": analysis.get("status"),
        "force_score": analysis.get("force_score"),
        "action_type": analysis.get("action_type"),
        "action_subtype": analysis.get("action_subtype"),
        "analysis_profile": analysis.get("analysis_profile"),
        "pipeline_version": analysis.get("pipeline_version"),
        "note": analysis.get("note"),
        "target": target,
        "pose": pose,
        "keyframes": keyframes,
        "video_temporal": video_temporal,
        "auto_eval": auto_eval,
        "quality_flags": _quality_flags(target, keyframes, video_temporal, vision, auto_eval),
        "processing_timings": analysis.get("processing_timings"),
        "created_at": analysis.get("created_at"),
        "updated_at": analysis.get("updated_at"),
        "error_code": analysis.get("error_code"),
        "error_message": analysis.get("error_message"),
        "error_detail": analysis.get("error_detail"),
    }


def _aggregate(items: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [item for item in items if item.get("status") == "completed"]
    failed = [item for item in items if item.get("status") == "failed"]
    awaiting = [item for item in items if item.get("status") == "awaiting_target_selection"]

    def avg(path: tuple[str, ...]) -> float:
        values: list[float] = []
        for item in completed:
            current: Any = item
            for key in path:
                current = current.get(key) if isinstance(current, dict) else None
            if isinstance(current, (int, float)):
                values.append(float(current))
        return round(sum(values) / len(values), 4) if values else 0.0

    flag_counts: Counter[str] = Counter()
    profile_counts: Counter[str] = Counter()
    for item in completed:
        profile_counts[str(item.get("analysis_profile") or "unknown")] += 1
        for flag in item.get("quality_flags", []):
            flag_counts[str(flag)] += 1

    return {
        "videos_total": len(items),
        "completed": len(completed),
        "failed": len(failed),
        "awaiting_target_selection": len(awaiting),
        "average_force_score": avg(("force_score",)),
        "average_pose_tracked_ratio": avg(("pose", "tracked_ratio")),
        "average_pose_lost_ratio": avg(("pose", "lost_ratio")),
        "average_pose_low_confidence_ratio": avg(("pose", "low_confidence_ratio")),
        "average_keyframe_coverage": avg(("keyframes", "coverage_score")),
        "average_keyframe_confidence": avg(("keyframes", "average_confidence")),
        "tal_complete_rate": round(
            sum(1 for item in completed if item.get("keyframes", {}).get("complete")) / max(len(completed), 1),
            4,
        ),
        "tal_order_valid_rate": round(
            sum(1 for item in completed if item.get("keyframes", {}).get("tal_order_valid")) / max(len(completed), 1),
            4,
        ),
        "semantic_frame_usage_rate": round(
            sum(1 for item in completed if item.get("video_temporal", {}).get("used_semantic_frames")) / max(len(completed), 1),
            4,
        ),
        "profile_counts": dict(profile_counts),
        "top_quality_flags": flag_counts.most_common(20),
        "failed_videos": [
            {
                "video": item.get("video"),
                "analysis_id": item.get("analysis_id"),
                "error_code": item.get("error_code"),
                "error_message": item.get("error_message"),
            }
            for item in failed
        ],
    }


def _write_outputs(output_dir: Path, label: str, payload: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{label}.json"
    md_path = output_dir / f"{label}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    aggregate = payload["aggregate"]
    lines = [
        "# API Batch Skate Analysis",
        "",
        f"- Label: {payload['label']}",
        f"- Generated: {payload['generated_at']}",
        f"- Completed: {aggregate['completed']}/{aggregate['videos_total']}",
        f"- Failed: {aggregate['failed']}",
        f"- Awaiting target selection: {aggregate['awaiting_target_selection']}",
        f"- Avg Force Score: {aggregate['average_force_score']:.2f}",
        f"- Avg pose tracked ratio: {aggregate['average_pose_tracked_ratio']:.2%}",
        f"- Avg pose lost ratio: {aggregate['average_pose_lost_ratio']:.2%}",
        f"- Avg pose low-confidence ratio: {aggregate['average_pose_low_confidence_ratio']:.2%}",
        f"- T/A/L complete rate: {aggregate['tal_complete_rate']:.2%}",
        f"- T/A/L order-valid rate: {aggregate['tal_order_valid_rate']:.2%}",
        f"- Semantic frame usage rate: {aggregate['semantic_frame_usage_rate']:.2%}",
        "",
        "## Profile Counts",
        "",
        json.dumps(aggregate["profile_counts"], ensure_ascii=False, indent=2),
        "",
        "## Top Quality Flags",
        "",
        json.dumps(aggregate["top_quality_flags"], ensure_ascii=False, indent=2),
        "",
    ]
    if aggregate["failed_videos"]:
        lines.extend(["## Failed Videos", "", json.dumps(aggregate["failed_videos"], ensure_ascii=False, indent=2), ""])
    md_path.write_text("\n".join(lines), encoding="utf-8")


class BatchClient:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=httpx.Timeout(timeout, connect=20.0), follow_redirects=True)

    def close(self) -> None:
        self.client.close()

    def get_json(self, path: str, **params: Any) -> Any:
        response = self.client.get(f"{self.base_url}{path}", params={k: v for k, v in params.items() if v is not None})
        response.raise_for_status()
        return response.json()

    def post_json(self, path: str, payload: dict[str, Any] | None = None, **params: Any) -> Any:
        response = self.client.post(
            f"{self.base_url}{path}",
            json=payload,
            params={k: v for k, v in params.items() if v is not None},
        )
        response.raise_for_status()
        return response.json()

    def upload(self, video_path: Path, data: dict[str, str]) -> dict[str, Any]:
        mime_type = mimetypes.guess_type(video_path.name)[0] or "video/mp4"
        with video_path.open("rb") as handle:
            files = {"file": (video_path.name, handle, mime_type)}
            response = self.client.post(f"{self.base_url}/api/analysis/upload", data=data, files=files)
        response.raise_for_status()
        return response.json()


def _find_existing_by_note(analyses: list[dict[str, Any]], note: str) -> dict[str, Any] | None:
    for item in analyses:
        if item.get("note") == note and item.get("status") == "completed":
            return item
    for item in analyses:
        if item.get("note") == note:
            return item
    return None


def _pick_target_candidate(preview: dict[str, Any]) -> str | None:
    auto_id = preview.get("auto_candidate_id")
    if auto_id:
        return str(auto_id)
    candidates = preview.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return None
    candidates = [item for item in candidates if isinstance(item, dict) and item.get("id")]
    if not candidates:
        return None
    candidates.sort(key=lambda item: (_safe_float(item.get("confidence")), _bbox_area(item.get("bbox"))), reverse=True)
    return str(candidates[0].get("id"))


def _poll_until_done(
    api: BatchClient,
    analysis_id: str,
    *,
    poll_seconds: float,
    max_wait_seconds: float,
    auto_confirm_target: bool,
) -> dict[str, Any]:
    started = time.monotonic()
    target_confirm_attempted = False
    while True:
        analysis = api.get_json(f"/api/analysis/{analysis_id}", is_parent_request="true")
        status = str(analysis.get("status") or "")
        if status == "awaiting_target_selection" and auto_confirm_target and not target_confirm_attempted:
            target_confirm_attempted = True
            preview = api.get_json(f"/api/analysis/{analysis_id}/target-preview")
            candidate_id = _pick_target_candidate(preview)
            if candidate_id:
                api.post_json(f"/api/analysis/{analysis_id}/target-lock", {"candidate_id": candidate_id})
                time.sleep(max(poll_seconds, 2.0))
                continue
        if status not in IN_PROGRESS_STATUSES:
            return analysis
        if time.monotonic() - started > max_wait_seconds:
            raise TimeoutError(f"analysis {analysis_id} did not finish within {max_wait_seconds:.0f}s")
        time.sleep(poll_seconds)


def _process_video_job(
    *,
    base_url: str,
    timeout: float,
    video_path: Path,
    note: str,
    action_type: str,
    action_subtype: str,
    skill_category: str,
    skater_id: str,
    existing_match: dict[str, Any] | None,
    poll_seconds: float,
    max_wait_seconds: float,
    auto_confirm_target: bool,
) -> dict[str, Any]:
    api = BatchClient(base_url, timeout)
    try:
        created = False
        if existing_match and existing_match.get("id"):
            analysis_id = str(existing_match["id"])
            print(f"  reuse {analysis_id} status={existing_match.get('status')}", flush=True)
            analysis = api.get_json(f"/api/analysis/{analysis_id}", is_parent_request="true")
            status = str(analysis.get("status") or "")
            if status in IN_PROGRESS_STATUSES or status == "awaiting_target_selection":
                analysis = _poll_until_done(
                    api,
                    analysis_id,
                    poll_seconds=poll_seconds,
                    max_wait_seconds=max_wait_seconds,
                    auto_confirm_target=auto_confirm_target,
                )
        else:
            data = {
                "action_type": action_type,
                "action_subtype": action_subtype,
                "note": note,
            }
            if skater_id:
                data["skater_id"] = skater_id
            if skill_category.strip():
                data["skill_category"] = skill_category.strip()
            uploaded = api.upload(video_path, data)
            analysis_id = str(uploaded["id"])
            created = True
            print(f"  uploaded {analysis_id}", flush=True)
            analysis = _poll_until_done(
                api,
                analysis_id,
                poll_seconds=poll_seconds,
                max_wait_seconds=max_wait_seconds,
                auto_confirm_target=auto_confirm_target,
            )
        return _analysis_summary(video_path, analysis, created=created)
    finally:
        api.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload local skating videos through the running API and wait for full analyses.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--video-dir", type=Path, default=DEFAULT_VIDEO_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--label", default=datetime.now().strftime("run-%Y%m%d-%H%M%S"))
    parser.add_argument("--note-prefix", default=DEFAULT_NOTE_PREFIX)
    parser.add_argument("--action-type", default="跳跃")
    parser.add_argument("--action-subtype", default="单跳")
    parser.add_argument("--skill-category", default="")
    parser.add_argument("--skater-id", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="Analyze only videos whose file name matches one of these exact names. Can be passed multiple times.",
    )
    parser.add_argument("--poll-seconds", type=float, default=8.0)
    parser.add_argument("--max-wait-seconds", type=float, default=900.0)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--force", action="store_true", help="Create new analyses even when a completed matching note exists.")
    parser.add_argument("--no-auto-confirm-target", action="store_true")
    args = parser.parse_args()

    only_names = {str(name).strip() for name in args.only if str(name).strip()}
    video_paths = sorted(path for path in args.video_dir.iterdir() if path.suffix.lower() in VIDEO_SUFFIXES)
    if only_names:
        video_paths = [path for path in video_paths if path.name in only_names]
        missing_names = sorted(only_names - {path.name for path in video_paths})
        if missing_names:
            parser.error(f"--only names not found in {args.video_dir}: {', '.join(missing_names)}")
    if args.limit > 0:
        video_paths = video_paths[: args.limit]

    api = BatchClient(args.base_url, args.timeout)
    results: list[dict[str, Any]] = []
    try:
        skaters = api.get_json("/api/skaters")
        skater_id = args.skater_id.strip()
        if not skater_id and isinstance(skaters, list):
            default_skater = next((item for item in skaters if isinstance(item, dict) and item.get("is_default")), None)
            if isinstance(default_skater, dict):
                skater_id = str(default_skater.get("id") or "")

        existing = api.get_json("/api/analysis/", limit=500)
        existing_items = existing if isinstance(existing, list) else []

        jobs = []
        for index, video_path in enumerate(video_paths, start=1):
            note = f"{args.note_prefix} {video_path.name}"
            existing_match = None if args.force else _find_existing_by_note(existing_items, note)
            jobs.append((index, video_path, note, existing_match))

        output_lock = Lock()

        def persist_progress(summary: dict[str, Any]) -> None:
            with output_lock:
                existing_index = next(
                    (idx for idx, item in enumerate(results) if item.get("video") == summary.get("video")),
                    None,
                )
                if existing_index is None:
                    results.append(summary)
                else:
                    results[existing_index] = summary
                results.sort(key=lambda item: str(item.get("video") or ""))
                payload = {
                    "label": args.label,
                    "generated_at": datetime.now().isoformat(timespec="seconds"),
                    "base_url": args.base_url,
                    "video_dir": str(args.video_dir),
                    "note_prefix": args.note_prefix,
                    "aggregate": _aggregate(results),
                    "videos": results,
                }
                _write_outputs(args.output_dir, args.label, payload)

        if max(1, args.concurrency) == 1:
            for index, video_path, note, existing_match in jobs:
                print(f"[{index}/{len(video_paths)}] {video_path.name}", flush=True)
                summary = _process_video_job(
                    base_url=args.base_url,
                    timeout=args.timeout,
                    video_path=video_path,
                    note=note,
                    action_type=args.action_type,
                    action_subtype=args.action_subtype,
                    skill_category=args.skill_category,
                    skater_id=skater_id,
                    existing_match=existing_match,
                    poll_seconds=args.poll_seconds,
                    max_wait_seconds=args.max_wait_seconds,
                    auto_confirm_target=not args.no_auto_confirm_target,
                )
                persist_progress(summary)
                print(
                    f"  done status={summary['status']} score={summary.get('force_score')} "
                    f"pose={summary['pose']['tracked_ratio']:.2%} keyframes={summary['keyframes']['coverage_score']:.2%}",
                    flush=True,
                )
        else:
            worker_count = max(1, args.concurrency)
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                future_map = {}
                for index, video_path, note, existing_match in jobs:
                    print(f"[{index}/{len(video_paths)}] queued {video_path.name}", flush=True)
                    future = executor.submit(
                        _process_video_job,
                        base_url=args.base_url,
                        timeout=args.timeout,
                        video_path=video_path,
                        note=note,
                        action_type=args.action_type,
                        action_subtype=args.action_subtype,
                        skill_category=args.skill_category,
                        skater_id=skater_id,
                        existing_match=existing_match,
                        poll_seconds=args.poll_seconds,
                        max_wait_seconds=args.max_wait_seconds,
                        auto_confirm_target=not args.no_auto_confirm_target,
                    )
                    future_map[future] = (index, video_path)
                for future in as_completed(future_map):
                    index, video_path = future_map[future]
                    try:
                        summary = future.result()
                    except Exception as exc:  # noqa: BLE001
                        summary = {
                            "video": video_path.name,
                            "video_path": str(video_path),
                            "analysis_id": None,
                            "report_url": None,
                            "created_by_batch": False,
                            "status": "failed",
                            "force_score": None,
                            "action_type": args.action_type,
                            "action_subtype": args.action_subtype,
                            "analysis_profile": None,
                            "pipeline_version": None,
                            "note": f"{args.note_prefix} {video_path.name}",
                            "target": {},
                            "pose": {"tracked_ratio": 0.0, "lost_ratio": 0.0, "low_confidence_ratio": 0.0},
                            "keyframes": {"coverage_score": 0.0, "average_confidence": 0.0, "complete": False},
                            "video_temporal": {"available": False},
                            "auto_eval": {},
                            "quality_flags": ["batch_job_exception"],
                            "processing_timings": None,
                            "created_at": None,
                            "updated_at": None,
                            "error_code": "BATCH_JOB_EXCEPTION",
                            "error_message": f"{type(exc).__name__}: {exc}",
                            "error_detail": str(exc),
                        }
                    persist_progress(summary)
                    print(
                        f"[{index}/{len(video_paths)}] done {video_path.name} status={summary['status']} "
                        f"score={summary.get('force_score')} pose={summary['pose'].get('tracked_ratio', 0.0):.2%} "
                        f"keyframes={summary['keyframes'].get('coverage_score', 0.0):.2%}",
                        flush=True,
                    )
    finally:
        api.close()

    print(json.dumps(_aggregate(results), ensure_ascii=True, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
