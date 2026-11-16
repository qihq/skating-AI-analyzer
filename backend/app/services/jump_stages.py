"""Validated TAL anchors and the persisted five-node jump result contract.

Candidate selection is authoritative when present. Legacy labels are accepted
only on the compatibility path, never as a repair for a rejected new candidate.
"""
from __future__ import annotations
from copy import deepcopy
from .jump_projection import extract_projection, extract_pull_in
from .jump_rotation import extract_rotation
from typing import Any
from .pose_quality import analysis_point, finite_number
from .pose_observations import frame_usable, _frame_key, observation_time_error, verified_source_time, verified_playback_time, observation_slots

ROLES = {"takeoff": "T", "apex": "A", "landing": "L"}


# Shared with public candidate segmentation and every saved support observation.
_source_time = verified_source_time

def resolve_anchor(pose_data: Any, anchors: Any, role: str = "T") -> dict:
    anchors = anchors if isinstance(anchors, dict) else {}
    raw = anchors.get(role)
    candidate = raw if isinstance(raw, dict) else {"frame_id": raw}
    key = _frame_key(candidate.get("frame_id"))
    source = candidate.get("source", "legacy_key_frames")
    result = {"status": "unavailable", "frame_id": None, "pose_index": None,
              "timestamp": None, "source": source, "quality_flags": [],
              "evidence": deepcopy(candidate.get("evidence", {})), "warnings": list(candidate.get("warnings", []))}
    def reject(reason):
        result["quality_flags"].append(reason)
        return result
    if candidate.get("status") in ("unavailable", "not_applicable"):
        return reject(candidate.get("reason", "stage_anchor_unavailable"))
    if key is None: return reject("stage_anchor_missing")
    frames = pose_data.get("frames", []) if isinstance(pose_data, dict) else []
    matches = [(i,f) for i,f in enumerate(frames) if isinstance(f,dict) and _frame_key(f.get("frame") or f.get("frame_id")) == key]
    if len(matches) != 1: return reject("stage_anchor_ambiguous" if matches else "stage_anchor_not_found")
    index, frame = matches[0]
    if not frame_usable(frame): return reject("stage_anchor_frame_unusable")
    temporal = frame.get("temporal") or {}
    stamp = finite_number(temporal.get("analysis_timestamp", frame.get("analysis_timestamp", frame.get("timestamp"))))
    expected = finite_number(candidate.get("timestamp"))
    if observation_time_error(frame):
        return reject("stage_anchor_bound_time_invalid")
    if temporal.get("time_source") == "bound_source_pts":
        playback_time = verified_playback_time(temporal)
        scale = finite_number(temporal.get("slow_motion_scale"))
        if playback_time is None or scale is None or scale <= 0 or stamp is None or abs(playback_time/scale-stamp) > .002:
            return reject("stage_anchor_bound_time_invalid")
    legacy_time = (candidate.get("status") == "available" and "legacy_anchor_without_source_time" in candidate.get("quality_flags", []))
    if "timestamp" in candidate and not legacy_time and (expected is None or (stamp is not None and abs(stamp-expected) > .002)):
        return reject("stage_anchor_time_mismatch")
    if any(k in frame for k in ("timestamp", "analysis_timestamp", "temporal")) and (stamp is None or stamp < 0):
        return reject("stage_anchor_time_unavailable")
    if stamp is not None:
        for offset in (-1, 1):
            neighbor_index = index + offset
            if 0 <= neighbor_index < len(frames) and isinstance(frames[neighbor_index], dict):
                neighbor = frames[neighbor_index]
                nt = neighbor.get("temporal") or {}
                neighbor_time = finite_number(nt.get("analysis_timestamp", neighbor.get("analysis_timestamp", neighbor.get("timestamp"))))
                if neighbor_time is not None and (neighbor_time - stamp) * offset <= 0:
                    return reject("stage_anchor_time_not_monotonic")
    support = result["evidence"].get("support_frames")
    if support is not None:
        if not isinstance(support, list) or not support:
            return reject("stage_anchor_support_invalid")
        previous_index = None
        # Re-use the production continuity policy, including invalid middle
        # observations, identity, binding, PTS, scale and explicit time gaps.
        run_by_frame = {}
        run = 0
        for observation in observation_slots(pose_data):
            if observation is None:
                run += 1
            else:
                run_by_frame[id(observation)] = run
        anchor_run = run_by_frame.get(id(frame))
        for ref in support:
            ref_key = _frame_key(ref.get("frame_id")) if isinstance(ref, dict) else None
            found = [(i, f) for i, f in enumerate(frames) if isinstance(f, dict) and _frame_key(f.get("frame") or f.get("frame_id")) == ref_key]
            if len(found) != 1:
                return reject("stage_anchor_support_invalid")
            si, sf = found[0]
            st = sf.get("temporal") or {}
            actual = finite_number(st.get("analysis_timestamp", sf.get("analysis_timestamp", sf.get("timestamp"))))
            ref_time = finite_number(ref.get("timestamp"))
            if (not frame_usable(sf) or observation_time_error(sf)
                or anchor_run is None or run_by_frame.get(id(sf)) != anchor_run
                or (previous_index is not None and si != previous_index + 1)
                or (actual is not None and (ref_time is None or abs(actual-ref_time) > .002))
                or (sf.get("identity_id"), sf.get("tracker_id"), st.get("segment_id")) != (frame.get("identity_id"), frame.get("tracker_id"), temporal.get("segment_id"))
                or (previous_index is not None and st.get("continuous") is False)):
                return reject("stage_anchor_support_invalid")
            previous_index = si
        if key not in {_frame_key(ref.get("frame_id")) for ref in support}:
            return reject("stage_anchor_not_in_support")
    required = (11,12,23,24) if role == "A" else (11,12,23,24,27,28)
    if any(analysis_point(frame.get("keypoints"), k, .3) is None for k in required):
        return reject("stage_anchor_pose_unusable")
    if candidate.get("evidence", {}).get("signal_source") == "motion_only" or candidate.get("evidence", {}).get("motion_fallback"):
        return reject("motion_only_not_pose_anchor")
    result.update(status="available", frame_id=key, pose_index=index, timestamp=stamp if stamp is not None else expected)
    if stamp is None: result["quality_flags"].append("legacy_anchor_without_source_time")
    return result


def attach_jump_stages(bio_data, pose_data, motion_scores, profile):
    """Attach to the existing bio payload before subtype/report persistence."""
    bio = dict(bio_data)
    bio["analysis_profile"] = profile
    frames = pose_data.get("frames", []) if isinstance(pose_data, dict) else []
    candidates = bio.get("key_frame_candidates")
    has_candidates = isinstance(candidates, dict)
    selected = candidates if has_candidates else bio.get("key_frames", {})
    source = "key_frame_candidates" if has_candidates else "legacy_key_frames"
    legacy = bio.get("key_frames", {})
    anchors, stages = {}, {}
    not_jump = profile != "jump"
    for node in ("takeoff", "pull-in", "apex", "rotation", "landing"):
        role = ROLES.get(node)
        raw = selected.get(role) if isinstance(selected,dict) and role else None
        c = deepcopy(raw) if isinstance(raw,dict) else {"frame_id":raw}
        c["source"] = source
        if not_jump:
            c.update(status="not_applicable", reason="jump_stages_not_applicable_for_profile")
        anchor = resolve_anchor(pose_data, {role:c}, role) if role else None
        if role: anchors[role] = anchor
        frame_id = _frame_key(c.get("frame_id")) if role and not not_jump else None
        matches = [f for f in frames if isinstance(f,dict) and _frame_key(f.get("frame") or f.get("frame_id")) == frame_id] if frame_id else []
        # Raw motion-only hints remain diagnostics; current replay shares the
        # same validated anchor authority as the analysis consumers.
        displayable = len(matches)==1 and anchor["status"]=="available" if role else False
        frame = matches[0] if displayable else {}
        temporal = frame.get("temporal") or {}
        binding = temporal.get("binding") or {}
        stamp = finite_number(temporal.get("analysis_timestamp", frame.get("analysis_timestamp", frame.get("timestamp"))))
        playback = finite_number(temporal.get("playback_timestamp", frame.get("timestamp")))
        status = "not_applicable" if not_jump else ("not_implemented" if role is None else "candidate" if displayable else "unavailable")
        warnings = list(c.get("warnings", []))
        if role and isinstance(legacy,dict) and legacy.get(role) and _frame_key(legacy[role]) != frame_id:
            warnings.append("legacy_key_frame_conflict_candidate_authoritative")
        stages[node] = {"status":status, "frame_id":frame_id if displayable else None,
            "timestamp":(stamp if stamp is not None else finite_number(c.get("timestamp"))) if displayable else None, "playback_timestamp":playback if displayable else None,
            "source_timestamp":_source_time(temporal),
            "time_source":temporal.get("time_source", "legacy_or_sampling_time_unverified"),
            "slow_motion_scale":finite_number(temporal.get("slow_motion_scale")),
            "source_pts":binding.get("source_pts"), "source_time_base":binding.get("source_time_base"),
            "input_binding":deepcopy(binding),
            "image_ref":{"kind":"analysis_frame", "frame_id":frame_id} if displayable else None,
            "coordinate_space":pose_data.get("coordinate_space", "stored_pose_normalized_transform_unverified") if isinstance(pose_data,dict) else None,
            "identity_id":frame.get("identity_id"), "tracker_id":frame.get("tracker_id"),
            "continuous_segment":c.get("evidence",{}).get("continuous_segment"),
            "source":source if role else None, "confidence":c.get("confidence") if displayable else None,
            "evidence":c.get("evidence",{}) if displayable else {},
            "quality_flags":anchor["quality_flags"] if anchor else [], "warnings":warnings,
            "contact_evidence_status":"uncertain",
            "reason":("jump_stages_not_applicable_for_profile" if not_jump else
                      "stage_evidence_extractor_not_implemented" if role is None else
                      "weak_geometry_candidate_not_confirmed_contact" if displayable else
                      ",".join(anchor["quality_flags"]))}
    tal = [stages[node] for node in ROLES]
    if all(s["status"] == "candidate" for s in tal):
        stamps = [s["timestamp"] for s in tal]
        identities = {(s["identity_id"], s["tracker_id"], s["continuous_segment"]) for s in tal}
        if len(identities) != 1 or (all(t is not None for t in stamps) and not stamps[0] < stamps[1] < stamps[2]):
            for node, role in ROLES.items():
                stages[node].update(status="unavailable", frame_id=None, image_ref=None, reason="stage_order_or_identity_incomparable")
                anchors[role].update(status="unavailable", reason="stage_order_or_identity_incomparable")
                anchors[role]["quality_flags"].append("stage_order_or_identity_incomparable")
    def measurement(obj, unit, method, reason):
        return {"value":None, "status":"not_applicable" if not_jump else "unavailable", "object":obj,
                "unit":unit, "method":method, "reason":reason, "support_interval":None,
                "coordinate_space":None, "calibration":None, "uncertainty":None}
    measurements = {
        "candidate_interval": measurement("takeoff_to_landing_candidate_interval", "s", "analysis_time_difference", "comparable_stage_time_and_speed_required"),
        "air_time": measurement("confirmed_airborne_duration", "s", None, "independent_contact_boundaries_and_speed_required"),
        "projected_rise": measurement("body_center_proxy_projected_rise", "normalized_image", None, "comparable_coordinate_support_and_camera_control_required"),
        "physical_height": measurement("physical_center_of_mass_rise", "cm", None, "calibration_reference_plane_and_method_required"),
        "horizontal_distance": measurement("ground_contact_displacement", "m", None, "ground_mapping_scale_and_camera_control_required"),
        "rotation_count": measurement("complete_rotation_count", "turn", None, "continuous_unambiguous_rotation_evidence_required"),
        "trajectory": measurement("named_reference_point_trajectory", "normalized_image", None, "trajectory_extractor_not_implemented"),
    }
    t,l = stages["takeoff"],stages["landing"]
    if (not not_jump and anchors["T"]["status"] == anchors["L"]["status"] == "available"
        and t["status"]==l["status"]=="candidate" and t["continuous_segment"] is not None
        and t["continuous_segment"]==l["continuous_segment"] and t["source_timestamp"] is not None
        and l["source_timestamp"] is not None and t["slow_motion_scale"] is not None
        and t["slow_motion_scale"]==l["slow_motion_scale"] and t["slow_motion_scale"]>0
        and t["timestamp"] is not None and l["timestamp"] is not None and l["timestamp"]>t["timestamp"]):
        measurements["candidate_interval"].update(value=l["timestamp"]-t["timestamp"], status="candidate",
            reason="candidate_interval_not_confirmed_air_time", coordinate_space="analysis_time",
            support_interval={"start":t["timestamp"],"end":l["timestamp"],"time_axis":"analysis"})
    if not not_jump:
        measurements['trajectory'] = extract_projection(pose_data, motion_scores)
        stages['pull-in'] = extract_pull_in(pose_data, measurements['trajectory'], stages)
        stages['rotation'] = extract_rotation(pose_data, measurements['trajectory'], stages)
    # The old scalar metrics used uncalibrated geometry and legacy key_frames.
    # New results must not expose those as confirmed time/height/rotation.
    if not not_jump:
        bio.update(jump_metrics=None, jump_metrics_status="invalid",
                   jump_metrics_warning="阶段为候选，缺少独立接触、速度解释或物理标定；见jump_measurements")
    bio.update(jump_stage_contract="tal-evidence.v1", jump_stage_anchors=anchors, jump_stages=stages, jump_measurements=measurements)
    return bio


def available_stage_anchors(bio_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Read validated anchors for current results; never repair from audit labels."""
    anchors = bio_data.get("jump_stage_anchors")
    if not isinstance(anchors, dict):
        return {}
    return {role: anchor for role, anchor in anchors.items()
            if role in ROLES.values() and isinstance(anchor, dict)
            and anchor.get("status") == "available" and anchor.get("frame_id")}


def non_jump_frame_references(bio_data: dict[str, Any]) -> dict[str, str]:
    """Preserve each non-jump discipline's own labels, never stale TAL labels."""
    labels = {"spin": ("spin_entry", "spin_main", "spin_exit"),
              "spiral": ("峰值",), "step": ("步法序列",),
              "step_sequence": ("步法序列",)}.get(bio_data.get("analysis_profile"), ())
    frames = bio_data.get("key_frames")
    if not isinstance(frames, dict):
        return {}
    return {key: frames[key] for key in labels
            if isinstance(frames.get(key), str) and frames[key]}
