"""Saved-evidence-only manual segment branch. No detector fallback or media restore."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import cv2

from app.services import continuous_tracking as ct


class EvidenceUnavailable(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def finite(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise EvidenceUnavailable("invalid_numeric_evidence")
    return float(value)


def child(directory, name):
    if not isinstance(name, str) or Path(name).name != name or name in ("", ".", ".."):
        raise EvidenceUnavailable("invalid_saved_path")
    path = (directory / name).resolve()
    if path.parent != directory.resolve():
        raise EvidenceUnavailable("invalid_saved_path")
    return path


def load_source(analysis):
    """Revalidate stored source, JPEG/clock/binding and every original candidate."""
    motion = copy.deepcopy(analysis.frame_motion_scores or {})
    manifest = motion.get("continuous_tracking")
    if not isinstance(manifest, dict):
        raise EvidenceUnavailable("saved_tracking_manifest_missing")
    video = Path(analysis.video_path)
    if not video.is_file() or ct.file_sha256(video) != manifest.get("source_sha256"):
        raise EvidenceUnavailable("source_hash_mismatch_or_missing")
    pool = child(video.parent, manifest.get("pool_directory"))
    canvas = manifest.get("canvas", {})
    w, h = canvas.get("width"), canvas.get("height")
    if type(w) is not int or type(h) is not int or min(w, h) <= 0:
        raise EvidenceUnavailable("saved_canvas_invalid")
    geometry = manifest.get("geometry", {})
    for key in ("content_width", "content_height", "source_width", "source_height", "pad_left", "pad_top"):
        finite(geometry.get(key))
    if (min(geometry["content_width"], geometry["content_height"], geometry["source_width"], geometry["source_height"]) <= 0
        or min(geometry["pad_left"], geometry["pad_top"]) < 0
        or geometry["pad_left"] + geometry["content_width"] > w
        or geometry["pad_top"] + geometry["content_height"] > h):
        raise EvidenceUnavailable("saved_geometry_invalid")
    scale = finite(motion.get("slow_motion_scale"))
    if scale <= 0:
        raise EvidenceUnavailable("invalid_scale")
    for row in manifest["observations"]:
        child(pool, row.get("file"))
    files, states = ct._observation_states(pool, manifest)
    summary = (analysis.target_lock or {}).get("continuous_tracking_summary", {})
    receipts = summary.get("detection_receipts", [])
    by_receipt = {}
    for receipt in receipts:
        index = receipt.get("observation_index")
        if type(index) is not int or index in by_receipt:
            raise EvidenceUnavailable("duplicate_or_invalid_receipt")
        by_receipt[index] = receipt
    if (analysis.target_lock or {}).get("pose_frame_bindings") != manifest.get("pose_bindings"):
        raise EvidenceUnavailable("parent_pose_bindings_missing_or_conflicting")
    bindings = {}
    for binding in manifest.get("pose_bindings", []):
        index = binding.get("observation_index")
        if type(index) is not int or index in bindings:
            raise EvidenceUnavailable("duplicate_or_invalid_binding")
        bindings[index] = binding
    originals = {r["index"]: r for r in summary.get("observation_states", [])}
    available = {}
    unavailable = []
    for i, (path, state, row) in enumerate(zip(files, states, manifest["observations"], strict=True)):
        try:
            if not state["observation_valid"]:
                raise EvidenceUnavailable(state["identity_error"])
            image = cv2.imread(str(path))
            if image is None or image.shape != (h, w, 3):
                raise EvidenceUnavailable("saved_jpeg_size_mismatch")
            receipt = by_receipt.get(i)
            if not isinstance(receipt, dict) or receipt.get("complete") is not True:
                raise EvidenceUnavailable("complete_detection_receipt_missing")
            if receipt.get("detector_config") != {"classes": [0], "confidence": .4, "scope": "full_frame_only"}:
                raise EvidenceUnavailable("detector_config_mismatch")
            if any(receipt.get(a) != b for a, b in (("image_sha256", row["sha256"]),
                    ("source_sha256", manifest["source_sha256"]), ("source_pts", row["source_pts"]),
                    ("source_time_base", row["source_time_base"]))):
                raise EvidenceUnavailable("detection_receipt_binding_mismatch")
            if type(receipt.get("source_pts")) is not int:
                raise EvidenceUnavailable("invalid_receipt_pts")
            candidates = receipt.get("candidates")
            if not isinstance(candidates, list):
                raise EvidenceUnavailable("original_candidates_missing")
            for b in candidates:
                if not isinstance(b, (list, tuple)) or len(b) != 5:
                    raise EvidenceUnavailable("invalid_original_candidate")
                x, y, r, t, confidence = [finite(v) for v in b]
                if not (0 <= x < r <= w and 0 <= y < t <= h and .4 <= confidence <= 1):
                    raise EvidenceUnavailable("invalid_original_candidate")
            binding = bindings.get(i)
            if binding is not None:
                if type(binding.get("source_pts")) is not int:
                    raise EvidenceUnavailable("invalid_parent_binding_pts")
                finite(binding.get("source_origin_sec"))
                if any(binding.get(a) != b for a, b in (("sha256", row["sha256"]), ("source_pts", row["source_pts"]),
                        ("source_time_base", row["source_time_base"]), ("source_origin_sec", manifest["source_origin_sec"]))):
                    raise EvidenceUnavailable("parent_pose_binding_mismatch")
                original_image = child(video.parent / "frames", binding.get("frame"))
                if not original_image.is_file() or ct.file_sha256(original_image) != row["sha256"]:
                    raise EvidenceUnavailable("parent_saved_image_missing_or_changed")
            # A pool observation has its own exact image/PTS binding even if not
            # selected into the original sparse pose set. Never borrow another.
            pool_binding = {k: row[k] for k in ("index", "file", "sha256", "source_pts", "source_time_base", "source_pts_time", "timestamp")}
            available[i] = dict(row=row, receipt=receipt, binding=pool_binding,
                segment=state["continuity_segment"],
                lost=originals.get(i, {}).get("identity_status") == "identity_unconfirmed")
        except (EvidenceUnavailable, ValueError, TypeError, KeyError, OSError) as exc:
            unavailable.append(dict(observation_index=i, segment=state["continuity_segment"], reason=str(exc)))
    return dict(motion=motion, manifest=manifest, pool=pool, available=available,
                unavailable=unavailable, scale=scale, states=states, files=files)


def selection_for(analysis, source, index, candidate, revision):
    item = source["available"][index]
    row, receipt = item["row"], item["receipt"]
    return dict(analysis_id=analysis.id, expected_revision=revision, segment=item["segment"],
        observation_index=index, candidate_index=candidate,
        source_sha256=source["manifest"]["source_sha256"], image_sha256=row["sha256"],
        source_pts=row["source_pts"], source_time_base=row["source_time_base"],
        source_origin_sec=source["manifest"]["source_origin_sec"], slow_motion_scale=source["scale"],
        geometry_digest=digest(source["manifest"]["geometry"]), receipt_digest=digest(receipt),
        binding_digest=digest(item["binding"]), bbox=list(receipt["candidates"][candidate][:4]))


def validate_selection(analysis, selection, source):
    index, candidate = selection["observation_index"], selection["candidate_index"]
    item = source["available"].get(index)
    if item is None or not item["lost"]:
        raise EvidenceUnavailable("selected_observation_not_available_or_not_lost")
    if not 0 <= candidate < len(item["receipt"]["candidates"]):
        raise EvidenceUnavailable("candidate_not_in_original_receipt")
    expected = selection_for(analysis, source, index, candidate, selection["expected_revision"])
    if selection != expected:
        raise EvidenceUnavailable("selection_source_binding_mismatch")
    # Local range never spans a barrier or extends the old search. Missing
    # receipts are hard boundaries, not zero detections and not a retry budget.
    segment = item["segment"]
    indexes = [i for i in range(index, min(index + ct._SEGMENT_SEARCH_LIMIT, len(source["files"])))
               if source["states"][i]["continuity_segment"] == segment]
    for i in indexes:
        if i not in source["available"]:
            raise EvidenceUnavailable("local_range_receipt_or_binding_missing_at_" + str(i))
    snapshot = dict(selection=expected, range=indexes,
        evidence=[dict(binding=source["available"][i]["binding"], receipt=source["available"][i]["receipt"])
                  for i in indexes], manifest=source["manifest"])
    return indexes, digest(snapshot)


def execute_local(analysis, selection, revision, preview_digest):
    """Production tracker -> pose -> profile -> bio/report, separate saved files."""
    from app.routers import analysis as builders
    from app.services import pose, report
    from app.services.action_profiles import infer_analysis_profile
    source = load_source(analysis)
    indexes, current_digest = validate_selection(analysis, selection, source)
    if current_digest != preview_digest:
        raise EvidenceUnavailable("preview_evidence_changed_before_processing")
    manifest = source["manifest"]
    directory = Path(analysis.video_path).parent / "segment_reanchors" / str(revision)
    directory.mkdir(parents=True, exist_ok=False)
    frames = ct.bind_pose_frames(source["pool"], directory, manifest, indexes)
    w, h = manifest["canvas"]["width"], manifest["canvas"]["height"]
    x, y, r, t = selection["bbox"]
    lock = dict(selected_bbox=dict(x=x/w, y=y/h, width=(r-x)/w, height=(t-y)/h), preview_frame_index=0,
        manual_override=False, identity_source="manual_segment_selection", automatic_cross_gap_identity=False)
    def cached(identities, confidence):
        values = [item["receipt"]["candidates"] for item in source["available"].values()
                  if item["row"]["sha256"] in identities]
        if not values or any(v != values[0] for v in values):
            raise ct.RecoverableTrackingError("cached_receipt_missing_or_conflicting")
        return values[0]
    boxes, diagnostics, summary = ct.track_bound_pose_frames(frames, lock, manifest, source["pool"],
        detection_provider=cached, local_anchor=True)
    lock.update(pose_frame_bindings=manifest["pose_bindings"], bbox_per_frame=boxes,
        person_tracker_diagnostics=diagnostics, continuous_tracking_summary=summary)
    # Only this local interval is a motion source. The first observation has no
    # incoming motion; no evidence crosses the original gap or manual anchor.
    local_manifest = copy.deepcopy(manifest)
    records = ct.bound_motion_records(source["pool"], local_manifest, source["scale"])
    selected = [{**records[i], "frame_id": frame.stem, "source_thumb_index": i} for i, frame in zip(indexes, frames, strict=True)]
    for j, row in enumerate(selected):
        if j == 0 or any(diagnostics[k].get("identity_status") != "identity_confirmed" for k in (j-1, j)):
            row.update(motion_interval=None, motion_score=None, motion_status="manual_segment_identity_boundary")
    for row in selected:
        row["continuity_segment"] = selection["segment"]
    motion = dict(source["motion"], selected=selected, motion_records=selected,
        scores=[r["motion_score"] for r in selected if r.get("motion_score") is not None],
        continuous_tracking=local_manifest, sample_count=len(frames), effective_fps=1/manifest["period_sec"], top_motion_peaks=[],
        window_start=selected[0]["timestamp"], window_end=selected[-1]["timestamp"] + manifest["period_sec"],
        manual_segment_revision=revision)
    data = pose.extract_pose(str(directory), lock, boxes, 1/manifest["period_sec"],
        frame_times=selected, slow_motion_scale=source["scale"])
    profile, route = infer_analysis_profile("unlabelled motion", None, data, motion)
    sampling = SimpleNamespace(effective_fps=1/manifest["period_sec"], source_fps=analysis.source_fps,
        window_start_sec=motion["window_start"], window_end_sec=motion["window_end"], slow_motion_scale=source["scale"],
        slowed=source["scale"] != 1, slow_motion_source="saved_source_clock", manual_slow_motion_override=False)
    bio = builders._build_bio_data_for_profile(pose_data=data, motion_scores=motion, action_type="unlabelled motion",
        analysis_profile=profile, sampling_metadata=sampling, profile_evidence=route, target_lock=lock)
    # Reanchoring must never contact a provider. Use the report service's local
    # report builder directly, with the same conservative evidence projection.
    result_report = report.local_fallback_report("unlabelled motion", {}, bio)
    return dict(pose=data, motion=motion, target_lock=lock, bio_data=bio, report=result_report,
        analysis_profile=profile, profile_evidence=route, image_directory=str(directory),
        identity_source="manual_segment_selection", automatic_cross_gap_identity=False,
        local_range=indexes, invalidates_segment=selection["segment"],
        video_overlay_allowed=False, saved_image_space=True)

