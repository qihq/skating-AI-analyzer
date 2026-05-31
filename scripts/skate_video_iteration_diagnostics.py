from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import math
import os
import shutil
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any


VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
DEFAULT_VIDEO_DIR = Path(r"C:\Users\qihq\Pictures\skate testing video")
DEFAULT_OUTPUT_DIR = Path("tmp") / "skate-video-iteration"


def _repo_root(path: Path) -> Path:
    path = path.resolve()
    return path if (path / "backend" / "app").exists() else Path.cwd().resolve()


def _install_backend(repo: Path, model_root: Path) -> None:
    backend = repo / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))

    yolo = model_root / "models" / "yolov8n.pt"
    pose = model_root / "models" / "pose_landmarker_heavy.task"
    if yolo.exists():
        os.environ.setdefault("YOLO_PERSON_MODEL_PATH", str(yolo))
    if pose.exists():
        os.environ.setdefault("MEDIAPIPE_POSE_TASK_PATH", str(pose))
        os.environ.setdefault("POSE_NUM_POSES", "4")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(numeric) or math.isinf(numeric):
        return default
    return numeric


def _bbox_area(bbox: dict[str, Any] | None) -> float:
    if not isinstance(bbox, dict):
        return 0.0
    return max(0.0, _safe_float(bbox.get("width"))) * max(0.0, _safe_float(bbox.get("height")))


def _frame_names(frame_paths: list[Path]) -> list[str]:
    return [path.name for path in frame_paths]


def _state_counts(items: Any, key: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                counts[str(item.get(key) or "unknown")] += 1
    return dict(counts)


def _quality_flags(*payloads: Any) -> list[str]:
    flags: list[str] = []
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        values = payload.get("quality_flags")
        if isinstance(values, list):
            for value in values:
                flag = str(value)
                if flag and flag not in flags:
                    flags.append(flag)
    return flags


def _candidate_id(candidate: dict[str, Any]) -> str:
    return str(candidate.get("id") or "").strip()


def _target_candidates(
    *,
    person_tracker: Any,
    target_lock: Any,
    frame_paths: list[Path],
    motion_scores: dict[str, Any],
    analysis_profile: str,
) -> list[dict[str, Any]]:
    detect_person_candidates = getattr(person_tracker, "detect_person_candidates", None)
    if detect_person_candidates is None:
        return []

    frame_names = _frame_names(frame_paths)
    anchor_indices_fn = getattr(target_lock, "target_preview_anchor_frame_indices", None)
    if anchor_indices_fn is not None:
        anchor_indices = anchor_indices_fn(frame_names, motion_scores)
    else:
        anchor_indices = []
        for fraction in (0.5, 0.25, 0.75):
            index = round((len(frame_paths) - 1) * fraction)
            if index not in anchor_indices:
                anchor_indices.append(index)

    candidates: list[dict[str, Any]] = []
    for anchor_index in anchor_indices:
        if anchor_index < 0 or anchor_index >= len(frame_paths):
            continue
        frame_path = frame_paths[anchor_index]
        try:
            detected = detect_person_candidates(frame_path, include_zoomed_small_targets=True)
        except TypeError:
            detected = detect_person_candidates(frame_path)
        except Exception:
            continue
        for candidate in detected:
            if not isinstance(candidate, dict):
                continue
            item = dict(candidate)
            item["id"] = f"anchor_{anchor_index}_{candidate.get('id') or len(candidates) + 1}"
            item["anchor_frame"] = frame_path.name
            item["anchor_index"] = anchor_index
            candidates.append(item)

    stable_fn = getattr(target_lock, "select_stable_target_candidate", None)
    if stable_fn is not None:
        selected = stable_fn(candidates)
        if isinstance(selected, dict):
            selected = dict(selected)
            selected["id"] = "candidate_auto_stable"
            selected["source"] = str(selected.get("source") or "yolo_preview_multi_anchor")
            return [selected, *candidates]
    return candidates


def _build_preview(target_lock: Any, *, video_name: str, frame_paths: list[Path], motion_scores: dict[str, Any], candidates: list[dict[str, Any]], analysis_profile: str) -> Any:
    kwargs: dict[str, Any] = {
        "existing_target_lock": None,
        "motion_scores": motion_scores,
    }
    signature = inspect.signature(target_lock.build_target_preview)
    if "detected_candidates" in signature.parameters:
        kwargs["detected_candidates"] = candidates
    if "analysis_profile" in signature.parameters:
        kwargs["analysis_profile"] = analysis_profile
    return target_lock.build_target_preview(video_name, _frame_names(frame_paths), **kwargs)


def _build_target_lock_payload(target_lock: Any, preview: Any) -> dict[str, Any]:
    payload = target_lock.build_target_lock_payload(preview)
    if isinstance(payload.get("selected_bbox"), dict):
        return payload

    candidates = [item for item in getattr(preview, "candidates", []) if isinstance(item, dict)]
    selected = None
    auto_id = getattr(preview, "auto_candidate_id", None)
    if auto_id:
        selected = next((item for item in candidates if _candidate_id(item) == str(auto_id)), None)
    if selected is None and candidates:
        selected = candidates[0]
    if selected is not None:
        try:
            return target_lock.build_target_lock_payload(preview, selected_candidate=selected, manual=True)
        except TypeError:
            payload["selected_bbox"] = selected.get("bbox")
            payload["selected_candidate_id"] = selected.get("id")
    return payload


def _track_bboxes(person_tracker: Any, frame_paths: list[Path], target_payload: dict[str, Any], effective_fps: float) -> tuple[list[dict[str, float]] | None, list[str], list[dict[str, Any]]]:
    selected_bbox = target_payload.get("selected_bbox")
    if not isinstance(selected_bbox, dict):
        return None, ["diagnostic_no_selected_bbox"], []
    anchor_index = int(target_payload.get("preview_frame_index") or 0)
    try:
        tracked, flags, diagnostics = person_tracker.track_person_bbox_detailed(
            frame_paths,
            selected_bbox,
            initial_frame_index=anchor_index,
            effective_fps=effective_fps,
        )
        return tracked, list(flags), list(diagnostics)
    except Exception as exc:
        return [selected_bbox for _ in frame_paths], [f"diagnostic_tracker_failed:{type(exc).__name__}"], []


def _pose_summary(pose_data: dict[str, Any]) -> dict[str, Any]:
    diagnostics = pose_data.get("pose_diagnostics") if isinstance(pose_data, dict) else None
    if isinstance(diagnostics, dict):
        total = int(diagnostics.get("total_frames") or 0)
        tracked = int(diagnostics.get("tracked_frames") or 0)
        lost = int(diagnostics.get("lost_frames") or 0)
        low = int(diagnostics.get("low_confidence_frames") or 0)
        interpolated = int(diagnostics.get("interpolated_frames") or 0)
        return {
            "mode": diagnostics.get("mode"),
            "total_frames": total,
            "tracked_frames": tracked,
            "lost_frames": lost,
            "low_confidence_frames": low,
            "interpolated_frames": interpolated,
            "tracked_ratio": round(tracked / max(total, 1), 4),
            "lost_ratio": round(lost / max(total, 1), 4),
            "low_confidence_ratio": round(low / max(total, 1), 4),
            "state_counts": _state_counts(diagnostics.get("frames"), "tracking_state"),
        }
    frames = pose_data.get("frames") if isinstance(pose_data, dict) else []
    total = len(frames) if isinstance(frames, list) else 0
    tracked = sum(1 for frame in frames if isinstance(frame, dict) and frame.get("tracking_state") == "tracked")
    lost = total - tracked
    return {
        "mode": "legacy",
        "total_frames": total,
        "tracked_frames": tracked,
        "lost_frames": lost,
        "low_confidence_frames": lost,
        "interpolated_frames": 0,
        "tracked_ratio": round(tracked / max(total, 1), 4),
        "lost_ratio": round(lost / max(total, 1), 4),
        "low_confidence_ratio": round(lost / max(total, 1), 4),
        "state_counts": _state_counts(frames, "tracking_state"),
    }


def _keyframe_summary(candidates: dict[str, Any] | None) -> dict[str, Any]:
    result: dict[str, Any] = {"quality_flags": [], "complete": False, "coverage_score": 0.0, "average_confidence": 0.0}
    if not isinstance(candidates, dict):
        result["quality_flags"] = ["missing_keyframe_candidates"]
        return result
    confidences: list[float] = []
    timestamps: list[float] = []
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
    result["quality_flags"] = candidates.get("quality_flags") if isinstance(candidates.get("quality_flags"), list) else []
    result["complete"] = len(confidences) == 3
    result["coverage_score"] = round(len(confidences) / 3.0, 4)
    result["average_confidence"] = round(sum(confidences) / len(confidences), 4) if confidences else 0.0
    result["tal_order_valid"] = len(timestamps) == 3 and timestamps[0] < timestamps[1] < timestamps[2]
    return result


def _failure_notes(pose_data: dict[str, Any], tracker_diagnostics: list[dict[str, Any]], motion_scores: dict[str, Any]) -> list[dict[str, Any]]:
    selected_by_frame = {
        str(item.get("frame_id")): item
        for item in motion_scores.get("selected", [])
        if isinstance(item, dict) and item.get("frame_id")
    }
    notes: list[dict[str, Any]] = []
    pose_frames = ((pose_data.get("pose_diagnostics") or {}).get("frames") if isinstance(pose_data, dict) else []) or []
    for frame in pose_frames:
        if not isinstance(frame, dict):
            continue
        state = str(frame.get("tracking_state") or "")
        if state == "tracked":
            continue
        frame_id = str(frame.get("frame") or "").removesuffix(".jpg")
        motion = _safe_float((selected_by_frame.get(frame_id) or {}).get("motion_score"))
        reason = str(frame.get("reason") or state)
        scene = "pose_low_confidence_or_blur"
        if "lost" in state or "crop_retry" in reason:
            scene = "occlusion_or_detector_loss"
        if motion >= 0.45:
            scene = "fast_motion_or_rotation"
        notes.append(
            {
                "frame": frame.get("frame"),
                "frame_index": frame.get("frame_index"),
                "scene": scene,
                "state": state,
                "reason": reason,
                "motion_score": round(motion, 4),
            }
        )
        if len(notes) >= 8:
            break

    for item in tracker_diagnostics:
        if not isinstance(item, dict):
            continue
        state = str(item.get("state") or "")
        if state in {"tracked", "relocked"}:
            continue
        notes.append(
            {
                "frame": item.get("frame"),
                "frame_index": item.get("frame_index"),
                "scene": "target_bbox_relock_or_reuse",
                "state": state,
                "reason": ",".join(str(value) for value in item.get("rejected_reasons", []) if value),
            }
        )
        if len(notes) >= 12:
            break
    return notes


async def _analyze_one(video_path: Path, output_dir: Path, modules: dict[str, Any], analysis_profile_hint: str) -> dict[str, Any]:
    video_id = video_path.stem
    work_dir = output_dir / "work" / video_id
    frames_dir = work_dir / "frames"
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
    frames_dir.mkdir(parents=True, exist_ok=True)

    video = modules["video"]
    target_lock = modules["target_lock"]
    person_tracker = modules["person_tracker"]
    pose = modules["pose"]
    biomechanics = modules["biomechanics"]
    action_profiles = modules["action_profiles"]

    started = time.perf_counter()
    result: dict[str, Any] = {
        "video": video_path.name,
        "video_path": str(video_path),
        "status": "ok",
    }
    try:
        frame_paths, motion_scores, sampling = await video.extract_motion_sampled_frames(
            video_path,
            frames_dir,
            "jump",
            analysis_profile_hint,
            dense_peak_bursts=True,
        )
        candidates = _target_candidates(
            person_tracker=person_tracker,
            target_lock=target_lock,
            frame_paths=frame_paths,
            motion_scores=motion_scores,
            analysis_profile=analysis_profile_hint,
        )
        preview = _build_preview(
            target_lock,
            video_name=video_id,
            frame_paths=frame_paths,
            motion_scores=motion_scores,
            candidates=candidates,
            analysis_profile=analysis_profile_hint,
        )
        target_payload = _build_target_lock_payload(target_lock, preview)
        bbox_per_frame, tracker_flags, tracker_diagnostics = _track_bboxes(
            person_tracker,
            frame_paths,
            target_payload,
            sampling.effective_fps,
        )
        target_payload["bbox_per_frame"] = bbox_per_frame
        target_payload["person_tracker_diagnostics"] = tracker_diagnostics
        target_payload["quality_flags"] = list(
            dict.fromkeys([*(target_payload.get("quality_flags") if isinstance(target_payload.get("quality_flags"), list) else []), *tracker_flags])
        )
        pose_data = pose.extract_pose(
            str(frames_dir),
            target_payload,
            bbox_per_frame,
            sampling.effective_fps,
        )
        inferred_profile, profile_evidence = action_profiles.infer_analysis_profile(
            "jump",
            None,
            pose_data,
            motion_scores,
        )
        bio_data = biomechanics.analyze_biomechanics(
            pose_data,
            "jump",
            inferred_profile,
            effective_fps=sampling.effective_fps,
            source_fps=sampling.source_fps,
            window_seconds=sampling.window_end_sec - sampling.window_start_sec,
        )
        if hasattr(biomechanics, "attach_key_frame_candidates"):
            bio_data = biomechanics.attach_key_frame_candidates(
                bio_data,
                pose_data,
                motion_scores,
                inferred_profile,
                sampling.effective_fps,
            )

        target_flags = target_payload.get("quality_flags") if isinstance(target_payload.get("quality_flags"), list) else []
        selected_bbox = target_payload.get("selected_bbox") if isinstance(target_payload.get("selected_bbox"), dict) else None
        result.update(
            {
                "sampling": {
                    "frame_count": len(frame_paths),
                    "source_fps": sampling.source_fps,
                    "effective_fps": sampling.effective_fps,
                    "window_start": sampling.action_window_start,
                    "window_end": sampling.action_window_end,
                    "selection_reason": motion_scores.get("window_diagnostics", {}).get("selection_reason")
                    if isinstance(motion_scores.get("window_diagnostics"), dict)
                    else None,
                },
                "target_lock": {
                    "status": target_payload.get("status"),
                    "lock_confidence": round(_safe_float(target_payload.get("lock_confidence")), 4),
                    "candidate_count": len(getattr(preview, "candidates", []) or []),
                    "detected_candidate_count": len(candidates),
                    "selected_candidate_id": target_payload.get("selected_candidate_id"),
                    "selected_bbox_area": round(_bbox_area(selected_bbox), 6),
                    "quality_flags": target_flags,
                    "auto_locked": str(target_payload.get("status")) == "auto_locked",
                },
                "tracker": {
                    "quality_flags": tracker_flags,
                    "states": _state_counts(tracker_diagnostics, "state"),
                    "lost_or_reused_frames": sum(
                        1
                        for item in tracker_diagnostics
                        if isinstance(item, dict) and str(item.get("state") or "") not in {"tracked", "relocked"}
                    ),
                    "relocked_frames": sum(
                        1 for item in tracker_diagnostics if isinstance(item, dict) and str(item.get("state") or "") == "relocked"
                    ),
                },
                "pose": _pose_summary(pose_data),
                "action_recognition": {
                    "profile": inferred_profile,
                    "jump_gate_passed": bool(profile_evidence.get("jump_gate_passed")) if isinstance(profile_evidence, dict) else False,
                    "airborne_frames_detected": profile_evidence.get("airborne_frames_detected") if isinstance(profile_evidence, dict) else None,
                    "hip_rotation_signal": profile_evidence.get("hip_rotation_signal") if isinstance(profile_evidence, dict) else None,
                    "quality_flags": profile_evidence.get("quality_flags") if isinstance(profile_evidence, dict) else [],
                },
                "keyframes": _keyframe_summary(
                    bio_data.get("key_frame_candidates") if isinstance(bio_data, dict) else None
                ),
                "failure_notes": _failure_notes(pose_data, tracker_diagnostics, motion_scores),
                "quality_flags": _quality_flags(target_payload, pose_data, bio_data),
            }
        )
    except Exception as exc:
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        result["elapsed_sec"] = round(time.perf_counter() - started, 3)
    return result


def _aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [item for item in results if item.get("status") == "ok"]
    failures = [item for item in results if item.get("status") != "ok"]

    def avg(path: tuple[str, ...]) -> float:
        values: list[float] = []
        for item in ok:
            current: Any = item
            for key in path:
                current = current.get(key) if isinstance(current, dict) else None
            if isinstance(current, (int, float)):
                values.append(float(current))
        return round(sum(values) / len(values), 4) if values else 0.0

    profile_counts = Counter(str(item.get("action_recognition", {}).get("profile") or "unknown") for item in ok)
    failure_scenes = Counter()
    for item in ok:
        for note in item.get("failure_notes", []):
            if isinstance(note, dict):
                failure_scenes[str(note.get("scene") or "unknown")] += 1

    tal_complete = sum(1 for item in ok if item.get("keyframes", {}).get("complete"))
    return {
        "videos_total": len(results),
        "videos_ok": len(ok),
        "videos_failed": len(failures),
        "auto_lock_rate": round(
            sum(1 for item in ok if item.get("target_lock", {}).get("auto_locked")) / max(len(ok), 1),
            4,
        ),
        "average_pose_tracked_ratio": avg(("pose", "tracked_ratio")),
        "average_pose_lost_ratio": avg(("pose", "lost_ratio")),
        "average_pose_low_confidence_ratio": avg(("pose", "low_confidence_ratio")),
        "average_keyframe_coverage": avg(("keyframes", "coverage_score")),
        "average_keyframe_confidence": avg(("keyframes", "average_confidence")),
        "tal_complete_rate": round(tal_complete / max(len(ok), 1), 4),
        "profile_counts": dict(profile_counts),
        "failure_scene_counts": dict(failure_scenes),
        "failed_videos": [{"video": item.get("video"), "error": item.get("error")} for item in failures],
    }


def _delta(current: float, previous: float) -> float:
    return round(current - previous, 4)


def _write_report(output_path: Path, payload: dict[str, Any], baseline: dict[str, Any] | None) -> None:
    aggregate = payload["aggregate"]
    lines = [
        "# Skate Video Iteration Diagnostics",
        "",
        f"- Label: {payload['label']}",
        f"- Repo: {payload['repo']}",
        f"- Videos: {aggregate['videos_ok']}/{aggregate['videos_total']} ok",
        f"- Auto lock rate: {aggregate['auto_lock_rate']:.2%}",
        f"- Avg pose tracked ratio: {aggregate['average_pose_tracked_ratio']:.2%}",
        f"- Avg pose lost ratio: {aggregate['average_pose_lost_ratio']:.2%}",
        f"- Avg pose low-confidence ratio: {aggregate['average_pose_low_confidence_ratio']:.2%}",
        f"- T/A/L complete rate: {aggregate['tal_complete_rate']:.2%}",
        f"- Avg keyframe coverage: {aggregate['average_keyframe_coverage']:.2%}",
        f"- Avg keyframe confidence: {aggregate['average_keyframe_confidence']:.3f}",
        "",
    ]
    if baseline:
        base = baseline["aggregate"]
        lines.extend(
            [
                "## Comparison",
                "",
                "| Metric | Baseline | Current | Delta |",
                "| --- | ---: | ---: | ---: |",
                f"| videos ok | {base['videos_ok']}/{base['videos_total']} | {aggregate['videos_ok']}/{aggregate['videos_total']} | {_delta(float(aggregate['videos_ok']), float(base['videos_ok'])):.0f} |",
                f"| auto lock rate | {base['auto_lock_rate']:.2%} | {aggregate['auto_lock_rate']:.2%} | {_delta(aggregate['auto_lock_rate'], base['auto_lock_rate']):.2%} |",
                f"| pose tracked ratio | {base['average_pose_tracked_ratio']:.2%} | {aggregate['average_pose_tracked_ratio']:.2%} | {_delta(aggregate['average_pose_tracked_ratio'], base['average_pose_tracked_ratio']):.2%} |",
                f"| pose lost ratio | {base['average_pose_lost_ratio']:.2%} | {aggregate['average_pose_lost_ratio']:.2%} | {_delta(aggregate['average_pose_lost_ratio'], base['average_pose_lost_ratio']):.2%} |",
                f"| pose low-confidence ratio | {base['average_pose_low_confidence_ratio']:.2%} | {aggregate['average_pose_low_confidence_ratio']:.2%} | {_delta(aggregate['average_pose_low_confidence_ratio'], base['average_pose_low_confidence_ratio']):.2%} |",
                f"| T/A/L complete rate | {base['tal_complete_rate']:.2%} | {aggregate['tal_complete_rate']:.2%} | {_delta(aggregate['tal_complete_rate'], base['tal_complete_rate']):.2%} |",
                f"| keyframe coverage | {base['average_keyframe_coverage']:.2%} | {aggregate['average_keyframe_coverage']:.2%} | {_delta(aggregate['average_keyframe_coverage'], base['average_keyframe_coverage']):.2%} |",
                "",
            ]
        )
    lines.extend(
        [
            "## Failure Scenes",
            "",
            json.dumps(aggregate["failure_scene_counts"], ensure_ascii=False, indent=2),
            "",
            "## Profile Counts",
            "",
            json.dumps(aggregate["profile_counts"], ensure_ascii=False, indent=2),
            "",
        ]
    )
    if aggregate["failed_videos"]:
        lines.extend(["## Failed Videos", "", json.dumps(aggregate["failed_videos"], ensure_ascii=False, indent=2), ""])
    output_path.write_text("\n".join(lines), encoding="utf-8")


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Run local skating video diagnostics for iteration comparisons.")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Repository root whose backend services should be imported.")
    parser.add_argument("--model-root", type=Path, default=Path.cwd(), help="Repository root containing local models/.")
    parser.add_argument("--video-dir", type=Path, default=DEFAULT_VIDEO_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--label", default="current")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of videos; 0 means all.")
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="Analyze only videos whose file name matches one of these exact names. Can be passed multiple times.",
    )
    parser.add_argument("--compare", type=Path, default=None, help="Optional baseline JSON to compare against.")
    args = parser.parse_args()

    repo = _repo_root(args.repo)
    model_root = _repo_root(args.model_root)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    _install_backend(repo, model_root)

    from app.services import action_profiles, biomechanics, person_tracker, pose, target_lock, video

    modules = {
        "action_profiles": action_profiles,
        "biomechanics": biomechanics,
        "person_tracker": person_tracker,
        "pose": pose,
        "target_lock": target_lock,
        "video": video,
    }

    only_names = {str(name).strip() for name in args.only if str(name).strip()}
    video_paths = sorted(path for path in args.video_dir.iterdir() if path.suffix.lower() in VIDEO_SUFFIXES)
    if only_names:
        video_paths = [path for path in video_paths if path.name in only_names]
        missing_names = sorted(only_names - {path.name for path in video_paths})
        if missing_names:
            parser.error(f"--only names not found in {args.video_dir}: {', '.join(missing_names)}")
    if args.limit > 0:
        video_paths = video_paths[: args.limit]
    results: list[dict[str, Any]] = []
    for index, video_path in enumerate(video_paths, start=1):
        print(f"[{index}/{len(video_paths)}] {video_path.name}", flush=True)
        results.append(await _analyze_one(video_path, output_dir / args.label, modules, "jump"))

    payload = {
        "label": args.label,
        "repo": str(repo),
        "video_dir": str(args.video_dir),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "aggregate": _aggregate(results),
        "videos": results,
    }
    json_path = output_dir / f"{args.label}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    baseline = None
    if args.compare and args.compare.exists():
        baseline = json.loads(args.compare.read_text(encoding="utf-8"))
    _write_report(output_dir / f"{args.label}.md", payload, baseline)
    print(json.dumps(payload["aggregate"], ensure_ascii=False, indent=2), flush=True)
    print(f"Wrote {json_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
