"""Bounded decoded observations and exact pose-image/box binding.

The pool lives beside (never inside) the pose directory. PTS is the integer
source timestamp, not an fps-filter clock. Legacy payloads are never upgraded.
"""
from __future__ import annotations

import asyncio
from bisect import bisect_left
from collections import OrderedDict
import hashlib
import json
import math
import re
import shutil
import statistics
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any

from app.services.person_tracker import (
    PersonBBoxTracker, RecoverableTrackingError, TrackingSequenceError,
)

DEFAULT_HZ = 12.0
MAX_OBSERVATIONS = 240
MAX_WINDOW_SECONDS = 20.0


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _probe(path: Path) -> dict:
    result = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                             "-show_streams", "-of", "json", str(path)],
                            capture_output=True, text=True, check=True, timeout=30)
    return json.loads(result.stdout)["streams"][0]


async def extract_tracking_pool(video_path: Path, pool_dir: Path, start: float, end: float,
                                *, nominal_hz: float = DEFAULT_HZ,
                                max_frames: int = MAX_OBSERVATIONS) -> dict:
    from app.services.video import _frame_dimensions, _run_ffmpeg
    if (not all(math.isfinite(v) for v in (start, end, nominal_hz)) or
            start < 0 or end <= start or nominal_hz <= 0 or nominal_hz > 30 or
            not 1 <= max_frames <= MAX_OBSERVATIONS):
        raise ValueError("invalid bounded tracking window/rate/cap")
    pool_dir.mkdir(parents=True, exist_ok=True)
    if any(pool_dir.iterdir()):
        raise ValueError("tracking pool must be new and empty")
    stream = await asyncio.to_thread(_probe, video_path)
    tb = Fraction(stream["time_base"])
    if stream.get("start_pts") is None:
        raise ValueError("source origin PTS unavailable; cannot bind source clock")
    origin = float(int(stream["start_pts"]) * tb)
    requested_end = end
    end = min(end, start + MAX_WINDOW_SECONDS)
    width, height = map(int, _frame_dimensions())
    seek = max(0., start - .5)
    filters = (f"trim=start={origin+start:.9f}:end={origin+end:.9f},"
               f"select='isnan(prev_selected_t)+gte(t-prev_selected_t,{1/nominal_hz:.9f})',"
               f"scale={width}:{height}:force_original_aspect_ratio=decrease,showinfo,"
               f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black")
    log = await _run_ffmpeg([
        "-hide_banner", "-loglevel", "info", "-y", "-copyts",
        "-ss", f"{seek:.9f}", "-t", f"{end-seek+.5:.9f}", "-i", str(video_path),
        "-map", "0:v:0", "-an", "-vf", filters, "-vsync", "0",
        "-frames:v", str(max_frames), "-pix_fmt", "yuvj420p",
        str(pool_dir / "observation_%04d.jpg"),
    ])
    times = re.findall(r"config in time_base:\s*(\d+/\d+)", log)
    if not times:
        raise ValueError("decoded source time base missing")
    decoded_tb = Fraction(times[-1])
    pattern = r"\[Parsed_showinfo[^\]]*\]\s+n:\s*(\d+)\s+pts:\s*(-?\d+).*?pts_time:([^\s]+).*?\bs:(\d+)x(\d+)"
    matches = re.findall(pattern, log)
    observations = []
    content_w = content_h = None
    for ordinal, pts, _printed, content_width, content_height in matches:
        index = int(ordinal)
        image = pool_dir / f"observation_{index+1:04d}.jpg"
        if not image.is_file():
            continue  # showinfo may process one lookahead that was not written
        source_time = float(int(pts) * decoded_tb)
        playback_time = source_time - origin
        if not start - 1e-8 <= playback_time < end:
            raise ValueError("decoded observation outside requested source window")
        content_w, content_h = int(content_width), int(content_height)
        observations.append({"index": len(observations), "file": image.name,
            "sha256": file_sha256(image), "source_pts": int(pts),
            "source_time_base": str(decoded_tb), "source_pts_time": source_time,
            "timestamp": playback_time})
    if not observations:
        raise ValueError("no observations with verifiable source PTS")
    intervals = [b["timestamp"]-a["timestamp"] for a,b in zip(observations, observations[1:])]
    period = statistics.median(intervals) if intervals else 1/nominal_hz
    if period <= 0:
        raise ValueError("non-monotonic decoded PTS")
    # Fixed-step association is allowed only on a regular segment. At most 25%
    # cadence jitter; a dropped observation creates a barrier, never a new lock.
    cap = len(observations) == max_frames or requested_end != end
    return {"version": 1, "pool_directory": pool_dir.name, "nominal_hz": nominal_hz, "period_sec": period,
        "gap_tolerance_sec": .25 * period, "window_start": start,
        "window_end": end, "requested_window_end": requested_end,
        "source_origin_sec": origin, "source_stream_time_base": str(tb),
        "source_sha256": await asyncio.to_thread(file_sha256, video_path),
        "cap_reached": cap, "coverage_end": observations[-1]["timestamp"],
        "canvas": {"width": width, "height": height},
        "geometry": {"content_width": content_w, "content_height": content_h,
            "pad_left": ((width-content_w)//2)//2*2, "pad_top": ((height-content_h)//2)//2*2,
            "source_width": stream["width"], "source_height": stream["height"],
            "sample_aspect_ratio": stream.get("sample_aspect_ratio"),
            "rotation": [s.get("rotation") for s in stream.get("side_data_list",[]) if "rotation" in s],
            "autorotate": True, "filter": filters},
        "observations": observations, "pose_bindings": []}


def bind_pose_frames(pool_dir: Path, pose_dir: Path, manifest: dict,
                     observation_indexes: list[int]) -> list[Path]:
    """Select new pose inputs BEFORE target preview; never transfer old bboxes."""
    if observation_indexes != sorted(set(observation_indexes)):
        raise ValueError("pose indexes must be unique and chronological")
    records = manifest["observations"]
    pose_dir.mkdir(parents=True, exist_ok=True)
    bindings = []
    frames = []
    for pose_index, observation_index in enumerate(observation_indexes):
        if not 0 <= observation_index < len(records):
            raise ValueError("pose observation index outside pool")
        record = records[observation_index]
        source = pool_dir / record["file"]
        if source.name != record["file"] or file_sha256(source) != record["sha256"]:
            raise ValueError("pool image changed before pose binding")
        destination = pose_dir / f"frame_{pose_index+1:04d}.jpg"
        shutil.copyfile(source, destination)
        bindings.append({"frame": destination.name, "frame_id": destination.stem,
                         "observation_index": observation_index, "sha256": record["sha256"],
                         "source_pts": record["source_pts"], "source_time_base": record["source_time_base"],
                         "source_origin_sec": manifest["source_origin_sec"]})
        frames.append(destination)
    manifest["pose_bindings"] = bindings
    return frames


def bound_motion_records(pool_dir: Path, manifest: dict, slow_motion_scale: float) -> list[dict]:
    """Adjacent decoded-image difference, not velocity or a sparse-list index.

    Both endpoints carry exact pixel/PTS identity. The first sample, an invalid
    image/clock and intervals crossing a tracking gap have no motion evidence.
    Playback seconds exclude stream origin; analysis seconds additionally divide
    by slow_motion_scale. Irregular PTS retain their actual interval duration.
    """
    import cv2

    slow_motion_scale = _finite_clock(slow_motion_scale)
    if slow_motion_scale <= 0:
        raise ValueError("invalid slow motion scale")
    files, states = _observation_states(pool_dir, manifest)
    output = []
    previous_image = None
    previous_endpoint = None
    for i, (path, state, record) in enumerate(zip(files, states, manifest["observations"])):
        error = state["identity_error"]
        endpoint = {key: record.get(key) for key in
                    ("index", "sha256", "source_pts", "source_time_base", "source_pts_time", "timestamp")}
        timestamp = record.get("timestamp") if error is None else None
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE) if error is None else None
        reason = error or ("unreadable_motion_image" if image is None else None)
        row = {"motion_signal_version": 2, "source_sample_index": i,
               "sha256": record.get("sha256"), "source_pts": record.get("source_pts"),
               "source_time_base": record.get("source_time_base"),
               "source_pts_time": record.get("source_pts_time"), "timestamp": timestamp,
               "analysis_timestamp": timestamp / slow_motion_scale if timestamp is not None else None,
               "motion_score": None, "motion_status": reason or "no_previous_observation",
               "motion_interval": None, **state}
        if reason is None and state["continuity_reason"] is not None:
            row["motion_status"] = state["continuity_reason"]
        elif reason is None and previous_image is not None:
            if image.shape != previous_image.shape:
                row["motion_status"] = "motion_canvas_changed"
            else:
                duration = timestamp - previous_endpoint["timestamp"]
                row.update(motion_score=min(float(cv2.absdiff(previous_image, image).mean()) / 64., 1.),
                           motion_status="valid", motion_interval={
                               "previous": previous_endpoint, "current": endpoint,
                               "source_duration_sec": duration,
                               "analysis_duration_sec": duration / slow_motion_scale})
        output.append(row)
        previous_image = image if reason is None else None
        previous_endpoint = endpoint if reason is None else None
    return output


async def prepare_continuous_pose_inputs(video_path: Path, pose_dir: Path, pool_dir: Path,
                                         sampled_frames: list[Path], motion_scores: dict,
                                         sampling_metadata: Any) -> tuple[list[Path], dict]:
    """Production extraction stage: choose sparse pose images from retained pool."""
    start, end = (_finite_clock(motion_scores[k]) for k in ("window_start", "window_end"))
    scale = _finite_clock(motion_scores.get("slow_motion_scale", 1.))
    if start < 0 or end <= start or scale <= 0:
        raise ValueError("invalid pose preparation window or scale")
    manifest = await extract_tracking_pool(video_path, pool_dir, start, end)
    records = manifest["observations"]
    signals = bound_motion_records(pool_dir, manifest, scale)
    if any(not r["observation_valid"] or r["timestamp"] is None for r in signals):
        raise ValueError("unverifiable motion pool identity or source time")
    wanted = [_finite_clock(r["timestamp"]) for r in motion_scores.get("selected", [])]
    if len(wanted) != len(sampled_frames) or not all(math.isfinite(t) for t in wanted):
        raise ValueError("pose selection timestamps unavailable")
    # Only interpolate the selection support inside one validated segment. The
    # chosen image always keeps its own PTS, never the requested target's time.
    times = [r["timestamp"] for r in signals]
    selections = []
    indexes = set()
    for t in wanted:
        pos = bisect_left(times, t)
        exact = next((i for i in (pos, pos-1) if 0 <= i < len(times)
                      and abs(times[i]-t) <= 1e-8), None)
        index, reason = exact, None
        if index is None:
            if not times[0] <= t <= times[-1]:
                reason = "outside_observation_coverage"
            elif signals[pos-1]["continuity_segment"] != signals[pos]["continuity_segment"]:
                reason = signals[pos]["continuity_reason"] or "observation_continuity_gap"
            else:
                index = min((pos-1, pos), key=lambda i: (abs(times[i]-t), i))
        selection = {"requested_timestamp": t, "status": "unrepresented" if reason else "represented",
                     "reason": reason, "observation_index": index,
                     "selected_timestamp": times[index] if index is not None else None}
        if index is not None:
            indexes.add(index)
            selection.update({k: records[index][k] for k in
                              ("sha256", "source_pts", "source_time_base")})
        selections.append(selection)
    indexes = sorted(indexes)
    manifest["observation_validation"] = [
        {"index": i, **{k: r[k] for k in ("observation_valid", "identity_error",
            "continuity_segment", "continuity_reason")}} for i, r in enumerate(signals)]
    if not indexes:
        raise ValueError("no pose images inside bounded tracking window: " + json.dumps(selections))
    for image in sampled_frames:
        image.unlink(missing_ok=True)
    frames = bind_pose_frames(pool_dir, pose_dir, manifest, indexes)
    payload = dict(motion_scores)
    payload.update({"motion_signal_version": 2, "motion_signal_basis": "adjacent_pool_grayscale_absdiff_mean_div64",
        "motion_records": signals, "scores": [r["motion_score"] for r in signals if r["motion_score"] is not None],
        # No uniform series clock: video consumers use explicit selected playback times.
        "frame_rate": None, "total_thumb_frames": len(records),
        "top_motion_peaks": sorted((r for r in signals if r["motion_score"] is not None),
                                   key=lambda r: (-r["motion_score"], r["timestamp"]))[:6],
        "unrepresented_pose_targets": [r["requested_timestamp"] for r in selections if r["status"] == "unrepresented"],
        "pose_target_selections": selections,
        "continuous_tracking": manifest, "timestamp_basis": "decoded_source_pts_time",
        "timestamp_precision": "integer_pts_rational_time_base", "source_index_basis": "tracking_observation_index",
        "selection_strategy": "motion_targets_bound_to_decoded_pool", "sample_count": len(frames),
        "resolved_sample_count": len(frames), "selected": [
            {**signals[i], "frame_id": frame.stem, "source_thumb_index": i}
             for frame,i in zip(frames,indexes)]})
    duration = (manifest["window_end"]-manifest["window_start"]) / float(payload.get("slow_motion_scale") or 1.)
    sampling_metadata.effective_fps = len(frames)/duration
    payload["effective_fps"] = sampling_metadata.effective_fps
    return frames, payload


def _finite_clock(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("nonfinite_or_invalid_clock")
    return float(value)


def _observation_states(pool_dir: Path, manifest: dict) -> tuple[list[Path], list[dict]]:
    """Validate each identity/clock separately from the preceding edge.

    Positive irregular intervals beyond the existing 25% bound split segments;
    duplicate/backward clocks never become valid endpoints of such segments.
    Canvas changes split both motion and tracker propagation, even at valid PTS.
    """
    import cv2

    records = manifest.get("observations", [])
    if not records or len(records) > MAX_OBSERVATIONS or manifest.get("version") != 1:
        raise ValueError("invalid continuous tracking manifest")
    origin = _finite_clock(manifest["source_origin_sec"])
    period = _finite_clock(manifest["period_sec"])
    start, end = (_finite_clock(manifest[k]) for k in ("window_start", "window_end"))
    if period <= 0 or start < 0 or end <= start:
        raise ValueError("invalid tracking period or window")
    if "coverage_end" in manifest:
        coverage = _finite_clock(manifest["coverage_end"])
        if not start <= coverage < end or abs(coverage-_finite_clock(records[-1]["timestamp"])) > 1e-8:
            raise ValueError("invalid tracking coverage")
    files, states, seen = [], [], set()
    previous_time = previous_shape = None
    previous_valid = False
    segment = -1
    for i, r in enumerate(records):
        error = continuity = None
        path = pool_dir / str(r.get("file", ""))
        shape = None
        try:
            if path.name != r["file"] or type(r["index"]) is not int or r["index"] != i:
                raise ValueError("invalid_observation_index")
            if not path.is_file() or file_sha256(path) != r["sha256"]:
                raise ValueError("observation_image_missing_or_changed")
            if type(r["source_pts"]) is not int:
                raise ValueError("source_pts_missing")
            if not isinstance(r["source_time_base"], str) or Fraction(r["source_time_base"]) <= 0:
                raise ValueError("invalid_source_time_base")
            time = _finite_clock(float(r["source_pts"] * Fraction(r["source_time_base"])))
            pts_time, timestamp = (_finite_clock(r[k]) for k in ("source_pts_time", "timestamp"))
            if time in seen or (previous_time is not None and time <= previous_time):
                raise ValueError("source_pts_invalid_or_nonincreasing")
            if abs(time-pts_time) > 1e-8 or abs(time-origin-timestamp) > 1e-8:
                raise ValueError("source_clock_mapping_mismatch")
            if not start <= timestamp < end:
                raise ValueError("source_pts_out_of_window")
            image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if image is None:
                raise ValueError("unreadable_motion_image")
            shape = image.shape
            if previous_valid:
                if abs(time-previous_time-period) > .25*period + 1e-8:
                    continuity = "tracking_clock_gap"
                elif shape != previous_shape:
                    continuity = "motion_canvas_changed"
            elif i:
                continuity = "previous_observation_invalid"
            if not previous_valid or continuity:
                segment += 1
            seen.add(time)
            previous_time = time
        except (KeyError, ValueError, TypeError, OSError, ZeroDivisionError, OverflowError) as exc:
            error = str(exc) or "invalid_observation"
        files.append(path)
        states.append({"observation_valid": error is None, "identity_error": error,
                       "continuity_reason": continuity,
                       "continuity_segment": segment if error is None else None})
        previous_valid, previous_shape = error is None, shape
    return files, states


def _validated_observations(pool_dir: Path, manifest: dict) -> tuple[list[Path], list[str | None]]:
    """Compatibility diagnostics; production decisions use the separate states."""
    files, states = _observation_states(pool_dir, manifest)
    return files, [s["identity_error"] or s["continuity_reason"] for s in states]



# Identity evidence is deliberately frozen before searching any other segment.
# This is a conservative clothing-appearance gate, not biometric recognition.
_SEGMENT_SUPPORT = 3
_SEGMENT_SEARCH_LIMIT = 12
_SEGMENT_CANDIDATE_LIMIT = 16
_SEGMENT_SIMILARITY = .90


def _confirm_independent_segments(files, states, manifest, anchor, diagnostics,
                                  tracker_type, cached_detect, detector, branch_errors, invalid_selected, *, local_anchor=False, local_anchor_box=None):
    import numpy as np

    width, height = manifest["canvas"]["width"], manifest["canvas"]["height"]
    origin_segment = states[anchor]["continuity_segment"]
    if not local_anchor and len({s["continuity_segment"] for s in states if s["observation_valid"]}) < 2:
        return []

    def provenance(index):
        row = manifest["observations"][index]
        return {"observation_index": index, "frame": files[index].name,
                "sha256": row["sha256"], "source_pts": row["source_pts"],
                "source_time_base": row["source_time_base"],
                "source_origin_sec": manifest["source_origin_sec"],
                "playback_timestamp": row["timestamp"],
                "continuity_segment": states[index]["continuity_segment"],
                "image_binding_valid": True}

    def xyxy(box):
        return (box["x"]*width, box["y"]*height,
                (box["x"]+box["width"])*width, (box["y"]+box["height"])*height)

    def normalized(box):
        return dict(x=box[0]/width, y=box[1]/height,
                    width=(box[2]-box[0])/width, height=(box[3]-box[1])/height)

    def overlap(a, b):
        intersection = max(0., min(a[2], b[2])-max(a[0], b[0])) * max(0., min(a[3], b[3])-max(a[1], b[1]))
        union = (a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection
        return intersection/union if union > 0 else 0.

    def signature(image, box):
        return detector._independent_identity_signature(image, box[:4])

    def similarity(a, b):
        return float(np.dot(a["pooled"], b["pooled"]))

    feature_cache = OrderedDict()
    pair_cache = OrderedDict()
    detected_candidate_counts = {}
    feature_cost = {"computations": 0, "cache_hits": 0, "cache_limit": 64,
                    "cache_entries_peak": 0, "pair_computations": 0, "pair_cache_hits": 0,
                    "pair_cache_limit": 256, "variants_per_feature_max": 49,
                    "comparisons_per_pair_max": 97}

    def spatial_scores(a, b):
        key = tuple(sorted((a["feature_token"], b["feature_token"])))
        if key in pair_cache:
            feature_cost["pair_cache_hits"] += 1
            pair_cache.move_to_end(key)
            return pair_cache[key]
        feature_cost["pair_computations"] += 1
        result = detector._independent_identity_scores(a, b)
        pair_cache[key] = result
        if len(pair_cache) > feature_cost["pair_cache_limit"]:
            pair_cache.popitem(last=False)
        return result

    def consistent(a, b):
        scores = spatial_scores(a, b)
        return (similarity(a, b) >= _SEGMENT_SIMILARITY and
                scores["pooled_cosine"] >= _SEGMENT_SIMILARITY and
                scores["layout_mean"] >= .90 and
                scores["layout_lower_quartile"] >= .75 and
                scores["structure_correlation"] >= .85)

    def score_evidence(sig, references):
        comparisons = [spatial_scores(sig, ref) for ref in references]
        return {**{key: min(s[key] for s in comparisons)
                   for key in ("layout_mean", "layout_lower_quartile", "structure_correlation")},
                "comparisons": comparisons}

    def candidates(index):
        if index in invalid_selected:
            raise RecoverableTrackingError("selected_pose_binding_invalid")
        image = detector._read_frame(files[index])
        boxes = cached_detect(image, .4)
        if len(boxes) > _SEGMENT_CANDIDATE_LIMIT:
            raise RecoverableTrackingError("identity_candidate_limit")
        valid = [b for b in boxes if len(b) >= 5 and
                 all(math.isfinite(float(v)) for v in b[:5]) and b[4] >= .4 and
                 0 <= b[0] < b[2] <= width and 0 <= b[1] < b[3] <= height]
        detected_candidate_counts[index] = len(boxes)
        result = []
        for box in valid:
            key = (index, tuple(box[:4]))
            if key not in feature_cache:
                feature_cost["computations"] += 1
                feature_cache[key] = signature(image, box)
                if feature_cache[key] is not None:
                    feature_cache[key]["feature_token"] = feature_cost["computations"]
                if len(feature_cache) > feature_cost["cache_limit"]:
                    feature_cache.popitem(last=False)
                feature_cost["cache_entries_peak"] = max(feature_cost["cache_entries_peak"], len(feature_cache))
            else:
                feature_cost["cache_hits"] += 1
                feature_cache.move_to_end(key)
            result.append((box, feature_cache[key]))
        return result

    reference, signatures, reference_checks = [], [], []
    reference_error = "identity_reference_missing"
    original = [i for i in range(len(files)) if states[i]["continuity_segment"] == origin_segment]
    reliable = [i for i in original if states[i]["observation_valid"] and
                diagnostics.get(i, {}).get("state") == "tracked"]
    # Include the selected anchor, never a later independently confirmed person.
    runs = [reliable[j:j+_SEGMENT_SUPPORT] for j in range(len(reliable)-_SEGMENT_SUPPORT+1)]
    runs = [r for r in runs if r[-1]-r[0] == _SEGMENT_SUPPORT-1 and anchor in r
            and (not local_anchor or r[0] == anchor)]
    if runs:
        selected = min(runs, key=lambda r: (sum(abs(i-anchor) for i in r), r[0]))
        try:
            for index in selected:
                options = candidates(index)
                if local_anchor and index == anchor:
                    selected_box = xyxy(local_anchor_box)
                    matches = [(b, sig) for b, sig in options
                               if all(abs(b[k]-selected_box[k]) <= 1e-6 for k in range(4))]
                else:
                    matches = [(b, sig) for b, sig in options if overlap(b, xyxy(diagnostics[index]["bbox"])) >= .7]
                if len(matches) != 1 or matches[0][1] is None:
                    raise RecoverableTrackingError("identity_reference_uninformative")
                sig = matches[0][1]
                reference_checks.append({"observation_index": index,
                    "comparisons": [spatial_scores(sig, previous) for previous in signatures]})
                if any(not consistent(sig, previous) for previous in signatures):
                    raise RecoverableTrackingError("identity_reference_conflict")
                # A second similar person in the reference image is ambiguous too.
                if (any(s is None for _, s in options) or
                        sum(similarity(sig, s) >= .80 for _, s in options) != 1):
                    raise RecoverableTrackingError("identity_reference_ambiguous")
                reference.append({**provenance(index), "spatial_diversity": sig["spatial_diversity"],
                                  "luminance_contrast": sig["luminance_contrast"],
                                  "feature_geometry": sig.get("geometry")}); signatures.append(sig)
            reference_error = None
        except Exception as exc:
            reference_error = "identity_reference_rejected: " + str(exc)
    policies = []
    for segment in sorted({s["continuity_segment"] for s in states if s["observation_valid"]}):
        if (segment == origin_segment) != local_anchor:
            continue
        indexes = [i for i in range(len(files)) if states[i]["continuity_segment"] == segment and states[i]["observation_valid"]
                   and (not local_anchor or anchor <= i < anchor + _SEGMENT_SEARCH_LIMIT)]
        audit = {"method": "frozen_body_span_reliable_colour_v6", "evidence_version": "body_span_reliable_colour_v6",
                 "spatial_policy": {"geometry": "candidate_image_body_span_v6",
                    "detector_center_preserved": True, "raw_box_pooled_gate_preserved": True,
                    "grid": [4,4], "structure": [16,16], "layout_mean_min": .90,
                    "layout_lower_quartile_min": .75, "structure_correlation_min": .85,
                    "diversity_min": .08, "contrast_min": 6., "support_pairwise_check": True,
                    "colour": {"encoding": "reliable_hs_plus_soft_luminance",
                        "chroma_reliability_ramp": [8.,32.],
                        "neutral_luminance_centres": [0.,85.,170.,255.],
                        "neutral_bin_width": 85.},
                    "alignment": "whole_crop_translation_only", "translation_torso_max": 1/16,
                    "translation_steps": [-1., -.5, 0., .5, 1.],
                    "reject_sentinel_torso_max": 1/8, "reference_checks": reference_checks},
                 **({"identity_source": "manual_segment_selection", "automatic_cross_gap_identity": False} if local_anchor else {}),
                 "feature_cost": feature_cost, "reference": reference,
                 "reference_segment": origin_segment, "segment": segment,
                 "required_support": _SEGMENT_SUPPORT, "search_limit": _SEGMENT_SEARCH_LIMIT,
                 "candidate_limit": _SEGMENT_CANDIDATE_LIMIT, "similarity_min": _SEGMENT_SIMILARITY,
                 "support": [], "anchor": None, "attempts": [], "reason": reference_error,
                 "search_outcome": "reference_rejected" if reference_error else "searching"}
        policies.append(audit)
        for i in indexes:
            diagnostics[i]["segment_identity"] = audit
        if reference_error:
            continue
        support, previous, support_signatures = [], None, []
        confirmed = None
        for index in indexes[:_SEGMENT_SEARCH_LIMIT]:
            attempt = {**provenance(index), "candidate_count": 0, "outcome": "local_rejection"}
            audit["attempts"].append(attempt)
            try:
                options = candidates(index)
                scores = [min(similarity(sig, ref) for ref in signatures) if sig is not None else None for _, sig in options]
                attempt.update(candidate_count=len(options), candidates=[
                    {"bbox": normalized(b), "similarity": score,
                     "spatial": score_evidence(sig, signatures) if sig is not None else None,
                     "feature_geometry": sig.get("geometry") if sig is not None else None,
                     "feature_information_available": sig is not None}
                    for (b, sig), score in zip(options, scores)])
                possible = [j for j, score in enumerate(scores) if score is not None and score >= .80]
                # Only complete, finite evidence for every original candidate can
                # establish zero matches. Missing/invalid evidence is not rejection.
                if len(possible) > 1:
                    def finite_evidence(value):
                        if isinstance(value, dict):
                            return all(finite_evidence(v) for v in value.values())
                        if isinstance(value, (list, tuple)):
                            return all(finite_evidence(v) for v in value)
                        if isinstance(value, (int, float, np.number, np.ndarray)):
                            return bool(np.size(value) and np.isfinite(value).all())
                        return value is None or isinstance(value, str)

                    complete = (len(options) == detected_candidate_counts[index] and
                        all(sig is not None and finite_evidence(sig) and
                            all(np.size(sig[key]) and np.isfinite(sig[key]).all()
                                for key in ("pooled", "layout", "structure",
                                            "spatial_diversity", "luminance_contrast")) and
                            finite_evidence(candidate["spatial"]) and
                            all(all(math.isfinite(comparison[key]) for key in
                                    ("pooled_cosine", "layout_mean", "layout_lower_quartile",
                                     "structure_correlation"))
                                for comparison in candidate["spatial"]["comparisons"])
                            for (_, sig), candidate in zip(options, attempt["candidates"])))
                    if complete:
                        matches = [all(consistent(sig, ref) for ref in signatures)
                                   for _, sig in options]
                        attempt.update(fully_evaluated_candidate_count=len(options),
                                       full_match_count=sum(matches))
                        if not any(matches):
                            attempt["reason"] = "identity_all_candidates_rejected"
                            support, previous, support_signatures = [], None, []
                            continue
                    # A complete match plus a coarse competitor, or any missing
                    # evidence among multiple possibilities, remains terminal.
                    attempt["reason"] = audit["reason"] = "identity_ambiguous"
                    attempt["outcome"] = audit["search_outcome"] = "hard_stop"
                    break
                if len(options) > 1 and any(sig is None for _, sig in options):
                    attempt["reason"] = "identity_ambiguous_evidence_missing"
                    support, previous, support_signatures = [], None, []
                    continue
                if not possible or scores[possible[0]] < _SEGMENT_SIMILARITY:
                    attempt["reason"] = ("identity_evidence_unavailable"
                        if options and all(sig is None for _, sig in options) else "identity_no_match")
                    support, previous, support_signatures = [], None, []
                    continue
                box, sig = options[possible[0]]
                if not all(consistent(sig, ref) for ref in signatures):
                    attempt["reason"] = "identity_spatial_conflict"
                    support, previous, support_signatures = [], None, []
                    continue
                if previous is not None and (index != support[-1]["observation_index"]+1 or overlap(box, previous) < .35):
                    support, support_signatures = [], []
                attempt["support_spatial"] = score_evidence(sig, support_signatures) if support_signatures else None
                if not all(consistent(sig, prior) for prior in support_signatures):
                    attempt["reason"] = "identity_support_conflict"
                    support, previous, support_signatures = [], None, []
                    continue
                support_signatures.append(sig)
                support.append({**provenance(index), "bbox": normalized(box), "similarity": scores[possible[0]]})
                previous = box
                attempt["reason"] = "identity_support_pending"
                attempt["outcome"] = "support_pending"
                if len(support) == _SEGMENT_SUPPORT:
                    confirmed = index
                    attempt["outcome"] = "confirmed"
                    audit.update(support=support[:], anchor=support[-1], reason="identity_confirmed",
                                 search_outcome="confirmed")
                    break
            except RecoverableTrackingError as exc:
                attempt["reason"] = str(exc); support, previous, support_signatures = [], None, []
            except Exception as exc:
                attempt["reason"] = "identity_search_aborted: " + str(exc)
                audit["reason"] = attempt["reason"]
                attempt["outcome"] = audit["search_outcome"] = "hard_stop"
                break
        if confirmed is None:
            if audit["search_outcome"] == "searching":
                audit["search_outcome"] = "window_exhausted"
            audit["reason"] = audit["reason"] or "identity_support_insufficient"
            continue
        # No retrospective promotion. Fresh ByteTrack/Kalman starts at the third
        # supported observation, using only its box, never the old segment seed.
        allowed = [i for i in indexes if i >= confirmed]
        tracker = tracker_type(effective_fps=1/float(manifest["period_sec"]),
                               full_frame_only=True, isolate_frame_failures=True)
        seed = audit["anchor"]["bbox"]
        try:
            boxes, _, tracked = tracker.track_sequence_detailed([files[i] for i in allowed], seed)
        except Exception as exc:
            branch_errors[f"segment_{segment}_forward"] = str(exc)
            boxes = exc.boxes if isinstance(exc, TrackingSequenceError) else []
            tracked = exc.diagnostics if isinstance(exc, TrackingSequenceError) else []
        lost = False
        for index, box, item in zip(allowed, boxes, tracked):
            try:
                options = candidates(index)
                matching = [(b, sig) for b, sig in options if sig is not None and
                            min(similarity(sig, ref) for ref in signatures) >= .80]
                trusted = (not lost and all(sig is not None for _, sig in options) and item.get("state") == "tracked" and len(matching) == 1 and
                           all(consistent(matching[0][1], ref) for ref in signatures + support_signatures) and
                           overlap(matching[0][0], xyxy(box)) >= .7)
            except Exception:
                trusted = False
            if not trusted:
                lost = True
                diagnostics[index]["identity_rejected_reason"] = "independent_identity_lost"
                continue
            item.update(bbox=box, input_binding_valid=True, image_binding_valid=True,
                        identity_status="identity_confirmed", segment_identity=audit,
                        tracking_direction="independent_forward", anchor_observation_index=confirmed)
            diagnostics[index] = item
    return policies


def track_bound_pose_frames(frames: list[Path], target_lock: dict, manifest: dict,
                           pool_dir: Path, *, detection_provider=None, local_anchor=False, record_receipts=False) -> tuple[list[dict], list[dict], dict]:
    """Independent directional state; one full-frame detector cache per pool."""
    seed = target_lock["selected_bbox"]
    empty = lambda i, reason: {"frame_index": i, "frame": frames[i].name,
        "state": "input_unreliable", "input_binding_valid": False,
        "image_binding_valid": False, "identity_status": "identity_unconfirmed",
        "rejected_reasons": [reason], "bbox": seed}
    try:
        files, states = _observation_states(pool_dir,manifest)
        bindings = manifest["pose_bindings"]
        if len(bindings) != len(frames):
            raise ValueError("pose_binding_count_mismatch")
        mapping = []
        for i,(p,b) in enumerate(zip(frames,bindings)):
            index=b.get("observation_index")
            valid = (type(index) is int and 0<=index<len(files) and
                b.get("frame")==p.name and b.get("frame_id")==p.stem and
                b.get("sha256")==manifest["observations"][index].get("sha256") and
                b.get("source_pts")==manifest["observations"][index].get("source_pts") and
                b.get("source_time_base")==manifest["observations"][index].get("source_time_base") and
                b.get("source_origin_sec", manifest["source_origin_sec"])==manifest["source_origin_sec"] and
                p.is_file() and file_sha256(p)==b.get("sha256"))
            mapping.append(index if valid else None)
        valid_indexes=[i for i in mapping if i is not None]
        if valid_indexes != sorted(set(valid_indexes)):
            raise ValueError("pose_binding_order_or_duplicate")
        pose_anchor = int(target_lock.get("preview_frame_index") or 0)
        if not 0<=pose_anchor<len(mapping) or mapping[pose_anchor] is None:
            raise ValueError("anchor_binding_invalid")
        anchor = mapping[pose_anchor]
        if not states[anchor]["observation_valid"]:
            raise ValueError(states[anchor]["identity_error"])
    except (KeyError, ValueError, TypeError, OSError, ZeroDivisionError) as exc:
        return [seed for _ in frames], [empty(i,str(exc)) for i in range(len(frames))], {"detector_calls":0,"error":str(exc)}

    # Only decoded pixels of validated pool JPEGs may enter this cache. Include
    # the saved image identity and detector configuration, not just pixel bytes.
    detector = PersonBBoxTracker()
    pixel_identities = {}
    for path, state, observation in zip(files, states, manifest["observations"]):
        if state["observation_valid"]:
            try:
                image = detector._read_frame(path)
            except Exception as exc:
                state.update(observation_valid=False, identity_error="image_read_failed: " + type(exc).__name__)
                continue
            signature = hashlib.sha256(image.tobytes()).hexdigest()
            pixel_identities.setdefault(signature, set()).add(observation["sha256"])
    cache = {}
    cache_audit = []
    detection_receipts = []
    detector_calls = 0
    def cached_detect(image, conf_threshold=.4):
        nonlocal detector_calls
        if (conf_threshold != .4 or image.shape != (
                manifest["canvas"]["height"], manifest["canvas"]["width"], 3)
                or str(image.dtype) != "uint8"):
            cache_audit.append({"result": "unsupported_request", "confidence": conf_threshold})
            raise RecoverableTrackingError("uncached_crop_or_detector_config_rejected")
        signature = hashlib.sha256(image.tobytes()).hexdigest()
        identities = tuple(sorted(pixel_identities.get(signature, ())))
        if not identities:
            cache_audit.append({"result": "unknown_image"})
            raise RecoverableTrackingError("uncached_image_identity_rejected")
        key = (identities, image.shape, str(image.dtype), (0,), conf_threshold)
        hit = key in cache
        if not hit:
            detector_calls += 1
            try:
                values = (detection_provider(identities, conf_threshold) if detection_provider is not None
                          else detector._detect(image, conf_threshold=conf_threshold))
                cache[key] = (values, None)
                if record_receipts:
                    for observation in manifest["observations"]:
                        if observation["sha256"] in identities:
                            detection_receipts.append({"observation_index": observation["index"],
                                "image_sha256": observation["sha256"], "source_sha256": manifest.get("source_sha256"),
                                "source_pts": observation["source_pts"], "source_time_base": observation["source_time_base"],
                                "detector_config": {"classes": [0], "confidence": .4, "scope": "full_frame_only"},
                                "candidates": [[float(v) for v in b] for b in values], "complete": True})
            except OSError as exc:
                cache[key] = (None, RecoverableTrackingError(
                    f"cached_detector_failure: {type(exc).__name__}: {exc}"))
            except Exception as exc:
                # Unknown faults stop a direction. Cache them as failures so the
                # other direction cannot silently spend the same request twice.
                cache[key] = (None, exc)
        values, error = cache[key]
        cache_audit.append({"image_sha256": list(identities), "confidence": conf_threshold,
            "cache_hit": hit, "result": "failure" if error is not None else "success",
            "error_type": type(error).__name__ if error is not None else None})
        if error is not None:
            raise error
        return values

    class CachedTracker(PersonBBoxTracker):
        def _detect(self, image, *, conf_threshold=.4):
            return cached_detect(image,conf_threshold)

    by_observation = {}
    branch_errors = {}
    for direction, indexes in (("backward",list(range(anchor,-1,-1))),
                               ("forward",list(range(anchor,len(files))))):
        if local_anchor and direction == "backward":
            continue
        if local_anchor:
            indexes = indexes[:_SEGMENT_SEARCH_LIMIT]
        allowed=[]
        barrier=None
        for index in indexes:
            state = states[index]
            # The anchor is allowed at a gap's right endpoint, but propagation
            # in either direction stays in exactly that endpoint's segment.
            reason = state["identity_error"]
            if index != anchor:
                edge = index+1 if direction == "backward" else index
                reason = reason or states[edge]["continuity_reason"]
            if state["continuity_segment"] != states[anchor]["continuity_segment"]:
                reason = reason or "outside_anchor_continuity_segment"
            if reason or barrier:
                barrier=barrier or reason
                if index!=anchor or index not in by_observation:
                    by_observation[index]={"state":"input_unreliable", "input_binding_valid":False,
                        "rejected_reasons":[barrier], "tracking_direction":direction, "bbox":seed}
            else:
                allowed.append(index)
        if not allowed:
            continue
        tracker=CachedTracker(effective_fps=1/float(manifest["period_sec"]),
                              manual_lock_mode=bool(target_lock.get("manual_override")),
                              full_frame_only=True, isolate_frame_failures=True)
        try:
            boxes,flags,diagnostics=tracker.track_sequence_detailed([files[i] for i in allowed],seed)
        except Exception as exc:
            branch_errors[direction]=str(exc)
            boxes = exc.boxes if isinstance(exc, TrackingSequenceError) else []
            diagnostics = exc.diagnostics if isinstance(exc, TrackingSequenceError) else []
            for index in allowed[len(diagnostics):]:
                if index != anchor or direction == "forward":
                    by_observation[index]={"state":"lost_reused", "input_binding_valid":True,
                        "rejected_reasons":["tracking_branch_aborted: " + str(exc)],
                        "bbox":seed,"tracking_direction":direction}
        for index,box,d in zip(allowed,boxes,diagnostics):
            d.update({"bbox":box,"input_binding_valid":True,"tracking_direction":direction,
                      "anchor_observation_index":anchor})
            if index!=anchor or direction=="forward": by_observation[index]=d
    identities = _confirm_independent_segments(files, states, manifest, anchor,
        by_observation, CachedTracker, cached_detect, detector, branch_errors,
        {b.get("observation_index") for b, index in zip(bindings, mapping)
         if index is None and type(b.get("observation_index")) is int}, local_anchor=local_anchor, local_anchor_box=seed if local_anchor else None)
    if local_anchor:
        # Diagnostic tracker states are not identity permission. Only the local
        # support policy can promote the third observation and its verified suffix.
        for diagnostic in by_observation.values():
            if diagnostic.get("tracking_direction") != "independent_forward":
                diagnostic["identity_status"] = "identity_unconfirmed"
    for index, diagnostic in by_observation.items():
        diagnostic.update(states[index])
        diagnostic["image_binding_valid"] = bool(states[index]["observation_valid"])
        diagnostic.setdefault("identity_status", "identity_confirmed" if
            diagnostic.get("input_binding_valid") and diagnostic.get("state") in
            ("tracked", "relocked", "detector_relocked", "support_anchor_recovered")
            else "identity_unconfirmed")
    output=[]
    boxes=[]
    for i,index in enumerate(mapping):
        d=dict(by_observation.get(index) or empty(i,"pose_image_binding_invalid"))
        d.update({"frame_index":i,"frame":frames[i].name,"observation_index":index,
                  "source_pts":manifest["observations"][index].get("source_pts") if index is not None else None,
                  "timestamp":manifest["observations"][index].get("timestamp") if index is not None else None})
        output.append(d); boxes.append(d.get("bbox",seed))
    return boxes,output,{"detector_calls":detector_calls,"cache_audit":cache_audit,"observation_count":len(files),
        "pose_count":len(frames),"cap_reached":bool(manifest.get("cap_reached")),
        **({"detection_receipts": detection_receipts} if record_receipts else {}),
        "period_sec":manifest["period_sec"],"branch_errors":branch_errors,
        "segment_identities": identities, "cache_hits": sum(a.get("cache_hit", False) for a in cache_audit),
        "detector_config": {"classes":[0],"confidence":.4,"scope":"full_frame_only"},
        "observation_states": [{"index":i,"source_pts":manifest["observations"][i].get("source_pts"),
            "timestamp":manifest["observations"][i].get("timestamp"),
            **{k:d.get(k) for k in ("state","tracking_direction","tracker_id","bbox","input_binding_valid","rejected_reasons",
                "observation_valid","identity_error","continuity_segment","continuity_reason",
                "image_binding_valid","identity_status","segment_identity","identity_rejected_reason")}}
            for i,d in sorted(by_observation.items())]}


def pose_input_binding_valid(frame: Path, index: int, target_lock: dict | None,
                             diagnostic: dict | None) -> bool:
    if not isinstance(target_lock,dict) or "pose_frame_bindings" not in target_lock:
        return not (isinstance(diagnostic,dict) and diagnostic.get("input_binding_valid") is False)
    bindings=target_lock["pose_frame_bindings"]
    if not isinstance(bindings,list) or not 0<=index<len(bindings) or not isinstance(diagnostic,dict):
        return False
    binding=bindings[index]
    try:
        return (diagnostic.get("input_binding_valid") is True and
            binding["frame"]==frame.name and binding["frame_id"]==frame.stem and
            binding["observation_index"]==diagnostic.get("observation_index") and
            binding["source_pts"]==diagnostic.get("source_pts") and
            file_sha256(frame)==binding["sha256"])
    except (KeyError,TypeError,OSError):
        return False
