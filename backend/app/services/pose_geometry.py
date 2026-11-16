"""Recover padding geometry using saved evidence only. Never probe/backfill or infer pose."""
from __future__ import annotations
import json
import hashlib
import math
from fractions import Fraction
import re
from pathlib import Path
from PIL import Image


def recover_pose_geometry(analysis, frames_dir: Path) -> tuple[dict | None, str | None]:
    # This audited pipeline maps crop landmarks back to the whole sampled canvas and
    # uses ffmpeg scale(decrease), centered pad, yuvj420p. Other pipelines need their
    # own persisted transform contract; current environment settings are not evidence.
    def unavailable(reason):
        return None, reason
    if analysis.pipeline_version != 'legacy/local-r1':
        return unavailable('unsupported_saved_pipeline')
    scores = analysis.frame_motion_scores
    if isinstance(scores, dict) and scores.get('selection_strategy') == 'motion_targets_bound_to_decoded_pool':
        return _recover_continuous_geometry(analysis, frames_dir, scores)
    if not isinstance(scores, dict) or scores.get('selection_strategy') != 'motion_weighted':
        return unavailable('missing_saved_sampling_metadata')
    match = re.fullmatch(r'([1-9][0-9]*)x([1-9][0-9]*)', str(scores.get('full_size', '')))
    if not match:
        return unavailable('missing_saved_sample_size')
    sw, sh = map(int, match.groups())
    try:
        manifest = json.loads((Path(analysis.video_path).parent / 'media-manifest.json').read_text(encoding='utf-8'))
        timeline = manifest['source_timeline']
        identity = scores['video_identity']['sha256']
        if manifest.get('schema_version') != 'analysis_media.v1' or timeline.get('schema_version') != 'source-timeline.v1' or not re.fullmatch('[0-9a-f]{64}', identity) or identity != timeline.get('source_video_hash'):
            return unavailable('unverified_saved_source_identity')
        vw, vh = timeline['width'], timeline['height']
        if any(type(v) is not int or v <= 0 for v in (vw, vh)) or timeline.get('rotation_degrees') != 0:
            return unavailable('unsupported_source_geometry')
        # ffmpeg integer scale uses nearest rounding; 4:2:0 pad offsets are aligned
        # down to chroma samples. Odd scaled sizes have format-dependent conversion,
        # so this legacy recovery deliberately declines that ambiguous case.
        if sw * vh <= sh * vw:
            w, h = sw, (vh * sw + vw // 2) // vw
        else:
            w, h = (vw * sh + vh // 2) // vh, sh
        if any(v <= 0 or v % 2 for v in (sw, sh, w, h)) or w > sw or h > sh:
            return unavailable('unsupported_legacy_scale_rounding')
        x, y = ((sw-w)//2)//2*2, ((sh-h)//2)//2*2
        frames = analysis.pose_data.get('frames', []) if isinstance(analysis.pose_data, dict) else []
        if not frames:
            return unavailable('missing_saved_frames')
        for frame in frames:
            name = frame.get('frame') if isinstance(frame, dict) else None
            if not isinstance(name, str) or Path(name).name != name or '/' in name or '\\' in name:
                return unavailable('invalid_saved_frame_name')
            with Image.open(frames_dir / name) as image:
                if image.size != (sw, sh):
                    return unavailable('saved_frame_size_mismatch')
    except (OSError, ValueError, KeyError, TypeError, AttributeError, Image.DecompressionBombError):
        return unavailable('missing_or_invalid_saved_geometry_evidence')
    return {'schema_version':'pose-geometry.v1','coordinate_space':'sample_normalized',
            'sample_width':sw,'sample_height':sh,'content_rect':{'x':x,'y':y,'width':w,'height':h},
            'source_width':vw,'source_height':vh,'rotation_degrees':0,'crop':'none',
            'provenance':'saved_metadata_verified_frames'}, None


class _GeometryEvidenceError(ValueError):
    pass


def _require(condition, reason):
    if not condition:
        raise _GeometryEvidenceError(reason)


def _number(value):
    _require(type(value) in (int, float) and math.isfinite(value), "invalid_saved_geometry_number")
    return value


def _integer(value, minimum=0):
    _require(type(value) is int and value >= minimum, "invalid_saved_geometry_number")
    return value


def _base(value):
    _require(isinstance(value, str), "invalid_saved_geometry_clock")
    try:
        result = Fraction(value)
        _require(result > 0 and math.isfinite(float(result)), "invalid_saved_geometry_clock")
        return result
    except (ValueError, ZeroDivisionError, OverflowError):
        raise _GeometryEvidenceError("invalid_saved_geometry_clock") from None


def _same_time(value, expected):
    _require(abs(_number(value) - expected) <= 1e-6, "saved_geometry_clock_mismatch")


def _recover_continuous_geometry(analysis, frames_dir, scores):
    """Read-only v1 decoded-pool contract, not a strategy-name allowlist.

    Only square-pixel, unrotated scale(decrease)/420-centered-pad is supported.
    The saved filter is compared as inert text to the known producer; it is never
    executed. Source, measured content, per-pose mapping, JPEG and all redundant
    clocks must agree. A missing SAR is unknown, including in historical records.
    Geometry does not promote tracking states or manufacture absent landmarks.
    """
    try:
        media = json.loads((Path(analysis.video_path).parent / "media-manifest.json").read_text(encoding="utf-8"))
        timeline = media["source_timeline"]
        c = scores["continuous_tracking"]
        _require(media.get("schema_version") == "analysis_media.v1" and
                 timeline.get("schema_version") == "source-timeline.v1" and
                 type(c.get("version")) is int and c["version"] == 1,
                 "unsupported_saved_geometry_schema")
        identity = scores["video_identity"]["sha256"]
        _require(isinstance(identity, str) and re.fullmatch("[0-9a-f]{64}", identity) and
                 identity == c.get("source_sha256") == timeline.get("source_video_hash"),
                 "unverified_saved_source_identity")
        g = c["geometry"]
        sw, sh = (_integer(c["canvas"][key], 1) for key in ("width", "height"))
        vw, vh = (_integer(timeline[key], 1) for key in ("width", "height"))
        _require(scores.get("full_size") == f"{sw}x{sh}" and
                 _integer(g["source_width"], 1) == vw and _integer(g["source_height"], 1) == vh,
                 "saved_geometry_dimension_mismatch")
        _require(type(timeline.get("rotation_degrees")) in (int, float) and
                 _number(timeline["rotation_degrees"]) == 0 and
                 isinstance(g.get("rotation"), list) and
                 all(type(v) in (int, float) and _number(v) == 0 for v in g["rotation"]) and
                 g.get("autorotate") is True, "unsupported_saved_source_orientation")
        _require(g.get("sample_aspect_ratio") in ("1:1", "1/1"), "unsupported_or_unknown_saved_sar")
        w, h = (_integer(g[key], 1) for key in ("content_width", "content_height"))
        x, y = (_integer(g[key]) for key in ("pad_left", "pad_top"))
        if sw * vh <= sh * vw:
            expected_w, expected_h = sw, (vh * sw + vw // 2) // vw
        else:
            expected_w, expected_h = (vw * sh + vh // 2) // vh, sh
        _require(all(v % 2 == 0 for v in (sw, sh, w, h)) and
                 (w, h) == (expected_w, expected_h) and w <= sw and h <= sh and
                 (x, y) == (((sw-w)//2)//2*2, ((sh-h)//2)//2*2),
                 "unsupported_saved_content_rect")
        origin = _number(c["source_origin_sec"])
        scale = _number(scores["slow_motion_scale"])
        start, end, hz = (_number(c[key]) for key in ("window_start", "window_end", "nominal_hz"))
        _require(scale > 0 and 0 <= start < end and 0 < hz <= 30, "invalid_saved_geometry_clock")
        expected_filter = (f"trim=start={origin+start:.9f}:end={origin+end:.9f},"
                           f"select='isnan(prev_selected_t)+gte(t-prev_selected_t,{1/hz:.9f})',"
                           f"scale={sw}:{sh}:force_original_aspect_ratio=decrease,showinfo,"
                           f"pad={sw}:{sh}:(ow-iw)/2:(oh-ih)/2:black")
        _require(g.get("filter") == expected_filter, "unsupported_saved_transform")
        timebase = timeline["timebase"]
        source_base = Fraction(_integer(timebase["numerator"], 1), _integer(timebase["denominator"], 1))
        _require(source_base == _base(c["source_stream_time_base"]) and timeline.get("timestamp_status") == "exact",
                 "invalid_saved_geometry_clock")
        source_times = [_number(f["pts_sec"]) for f in timeline["frames"]]
        _require(source_times and all(b > a for a, b in zip(source_times, source_times[1:])),
                 "invalid_saved_geometry_clock")
        _same_time(source_times[0], origin)
        observations = c["observations"]
        previous = None
        for i, o in enumerate(observations):
            _require(_integer(o["index"]) == i and type(o["source_pts"]) is int, "invalid_saved_geometry_binding")
            source = float(o["source_pts"] * _base(o["source_time_base"]))
            _same_time(o["source_pts_time"], source)
            _same_time(o["timestamp"], source-origin)
            _require(start-1e-8 <= source-origin < end and (previous is None or source > previous) and
                     any(abs(t-source) <= 1e-6 for t in source_times), "saved_geometry_clock_mismatch")
            previous = source
        bindings = c["pose_bindings"]
        frames = analysis.pose_data["frames"]
        selected = scores["selected"]
        _require(frames and len(frames) == len(bindings) == len(selected), "missing_saved_geometry_bindings")
        seen_names = set()
        previous_index = -1
        for frame, b, s in zip(frames, bindings, selected):
            name = frame["frame"]
            _require(isinstance(name, str) and name and Path(name).name == name and
                     "/" not in name and "\\" not in name and name not in seen_names,
                     "invalid_saved_frame_name")
            seen_names.add(name)
            i = _integer(b["observation_index"])
            _require(previous_index < i < len(observations), "invalid_saved_geometry_binding")
            previous_index = i
            o = observations[i]
            _require(b["frame"] == name and b["frame_id"] == Path(name).stem == s["frame_id"] and
                     _integer(s["source_sample_index"]) == i and
                     isinstance(b["sha256"], str) and re.fullmatch("[0-9a-f]{64}", b["sha256"]) and
                     b["sha256"] == o["sha256"] == s["sha256"], "saved_geometry_binding_mismatch")
            for record in (b, s):
                _require(type(record["source_pts"]) is int and record["source_pts"] == o["source_pts"] and
                         record["source_time_base"] == o["source_time_base"], "saved_geometry_binding_mismatch")
            _same_time(b["source_origin_sec"], origin)
            _same_time(s["source_pts_time"], o["source_pts_time"])
            _same_time(s["timestamp"], o["timestamp"])
            _same_time(s["analysis_timestamp"], o["timestamp"]/scale)
            temporal = frame["temporal"]
            _require(temporal["binding"] == b, "saved_geometry_binding_mismatch")
            # Validate even redundant fields on frames without pose, when present.
            tbinding = temporal["binding"]
            _require(type(tbinding["source_pts"]) is int and type(tbinding["observation_index"]) is int,
                     "invalid_saved_geometry_binding")
            _same_time(tbinding["source_origin_sec"], origin)
            _same_time(temporal["slow_motion_scale"], scale)
            for field, expected in (("playback_timestamp", o["timestamp"]), ("analysis_timestamp", o["timestamp"]/scale)):
                if temporal.get(field) is not None:
                    _same_time(temporal[field], expected)
            if frame["keypoints"]:
                _require(temporal.get("time_source") == "bound_source_pts" and
                         temporal.get("playback_timestamp") is not None and temporal.get("analysis_timestamp") is not None,
                         "invalid_saved_geometry_clock")
                projection = frame["projection_geometry"]
                _require(projection.get("schema_version") == "pose-projection.v1" and
                         projection.get("coordinate_space") == "full_image_normalized" and
                         projection.get("provenance") == "landmarks_mapped_to_full_image" and
                         _integer(projection["image_width"], 1) == sw and _integer(projection["image_height"], 1) == sh,
                         "unverified_saved_projection_geometry")
            path = frames_dir / name
            _require(path.resolve().parent == frames_dir.resolve(), "invalid_saved_frame_name")
            _require(hashlib.sha256(path.read_bytes()).hexdigest() == b["sha256"], "saved_frame_hash_mismatch")
            with Image.open(path) as image:
                _require(image.format == "JPEG" and image.size == (sw, sh), "saved_frame_size_mismatch")
                image.verify()
        return {"schema_version": "pose-geometry.v1", "coordinate_space": "sample_normalized",
                "sample_width": sw, "sample_height": sh,
                "content_rect": {"x": x, "y": y, "width": w, "height": h},
                "source_width": vw, "source_height": vh, "rotation_degrees": 0, "crop": "none",
                "provenance": "saved_metadata_verified_frames"}, None
    except _GeometryEvidenceError as exc:
        return None, str(exc)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, OverflowError, Image.DecompressionBombError):
        return None, "missing_or_invalid_saved_geometry_evidence"
