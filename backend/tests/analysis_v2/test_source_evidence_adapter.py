from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np

from app.analysis_v2.action_classification import classify_action
from app.analysis_v2.evaluation.legacy_event_proposal_adapter import evidence_from_legacy_analysis
from app.analysis_v2.event_proposals import EventProposal, generate_event_proposals
from app.analysis_v2.profile_moments import localize_profile_moments
from app.analysis_v2.evaluation.source_evidence_adapter import (
    build_action_classification_evidence,
    build_source_evidence,
)


SOURCE_HASH = "a" * 64


def _pose_frame(index: int, angle: float) -> dict[str, object]:
    center_x, center_y = .5, .5

    def point(point_id: int, radius: float, offset: float, y_offset: float = 0) -> dict[str, float | int]:
        return {
            "id": point_id,
            "x": center_x + radius * math.cos(angle + offset),
            "y": center_y + y_offset + radius * math.sin(angle + offset),
            "visibility": .98,
        }

    return {
        "frame": f"frame_{index + 1:04d}.jpg",
        "tracking_state": "tracked",
        "keypoints": [
            {"id": 0, "x": center_x, "y": .28, "visibility": .98},
            point(11, .16, math.pi, -.08),
            point(12, .16, 0, -.08),
            point(23, .10, math.pi, .05),
            point(24, .10, 0, .05),
            {"id": 15, "x": .22, "y": .50, "visibility": .98},
            {"id": 16, "x": .78, "y": .50, "visibility": .98},
            {"id": 27, "x": .43, "y": .82, "visibility": .98},
            {"id": 28, "x": .57, "y": .82, "visibility": .98},
        ],
        "target_bbox": {"x": .25, "y": .20, "width": .50, "height": .68},
    }


def _analysis(tmp_path: Path, *, pose_angles: list[float], image_angles: list[float]) -> dict[str, object]:
    rng = np.random.default_rng(7)
    base = np.zeros((160, 160), dtype=np.uint8)
    for x, y in rng.integers(38, 122, size=(90, 2)):
        cv2.circle(base, (int(x), int(y)), 1, 220, -1)
    cv2.rectangle(base, (70, 35), (90, 125), 160, -1)

    frame_paths: list[str] = []
    selected: list[dict[str, object]] = []
    for index, angle in enumerate(image_angles):
        matrix = cv2.getRotationMatrix2D((80, 80), -math.degrees(angle), 1)
        image = cv2.warpAffine(base, matrix, (160, 160))
        path = tmp_path / f"frame_{index + 1:04d}.jpg"
        assert cv2.imwrite(str(path), image)
        frame_paths.append(str(path))
        selected.append({
            "frame_id": path.stem,
            "source_thumb_index": index,
            "timestamp": index / 10,
            "motion_score": .45,
        })

    return {
        "frame_paths": frame_paths,
        "sampling": {"source_fps": 10, "effective_fps": 10, "action_window_end": (len(frame_paths) - 1) / 10},
        "motion_scores": {"selected": selected, "scores": [.45 for _ in selected], "source_duration_sec": len(frame_paths) / 10},
        "bbox_per_frame": [{"x": .25, "y": .20, "width": .50, "height": .68} for _ in selected],
        "pose_data": {"frames": [_pose_frame(index, angle) for index, angle in enumerate(pose_angles)]},
    }


def _translated_scene_analysis(tmp_path: Path, *, camera_pan: bool) -> dict[str, object]:
    rng = np.random.default_rng(19)
    height, width = 180, 260
    background = rng.integers(0, 90, size=(height, width), dtype=np.uint8)
    for x, y in rng.integers((0, 0), (width, height), size=(180, 2)):
        cv2.circle(background, (int(x), int(y)), 1, 180, -1)

    frame_paths: list[str] = []
    selected: list[dict[str, object]] = []
    poses: list[dict[str, object]] = []
    bboxes: list[dict[str, float]] = []
    for index in range(12):
        offset_px = index * 3
        if camera_pan:
            matrix = np.float32([[1, 0, offset_px], [0, 1, 0]])
            image = cv2.warpAffine(background, matrix, (width, height))
            target_x = 100 + offset_px
        else:
            image = background.copy()
            target_x = 100 + max(0, index - 3) * 6
        cv2.rectangle(image, (target_x, 48), (target_x + 34, 148), 230, -1)
        cv2.line(image, (target_x + 17, 60), (target_x + 4, 115), 120, 3)
        cv2.line(image, (target_x + 17, 60), (target_x + 30, 115), 120, 3)
        path = tmp_path / f"translated_{index + 1:04d}.jpg"
        assert cv2.imwrite(str(path), image)
        frame_paths.append(str(path))
        selected.append({
            "frame_id": path.stem,
            "source_thumb_index": index,
            "timestamp": index / 10,
            "motion_score": .85,
        })

        center_x = (target_x + 17) / width
        poses.append({
            "frame": path.name,
            "tracking_state": "tracked",
            "keypoints": [
                {"id": 0, "x": center_x, "y": .27, "visibility": .98},
                {"id": 11, "x": center_x - .045, "y": .39, "visibility": .98},
                {"id": 12, "x": center_x + .045, "y": .39, "visibility": .98},
                {"id": 23, "x": center_x - .035, "y": .58, "visibility": .98},
                {"id": 24, "x": center_x + .035, "y": .58, "visibility": .98},
                {"id": 27, "x": center_x - .025, "y": .82, "visibility": .98},
                {"id": 28, "x": center_x + .025, "y": .82, "visibility": .98},
            ],
        })
        bboxes.append({"x": target_x / width, "y": 48 / height, "width": 34 / width, "height": 100 / height})

    return {
        "frame_paths": frame_paths,
        "sampling": {"source_fps": 10, "effective_fps": 10, "action_window_end": 1.1},
        "motion_scores": {"selected": selected, "scores": [.85] * len(selected), "source_duration_sec": 1.2},
        "bbox_per_frame": bboxes,
        "pose_data": {"frames": poses},
    }


def _proposal(bundle) -> EventProposal:
    collection = generate_event_proposals(
        source_video_hash=SOURCE_HASH,
        source_duration_sec=bundle.source_duration_sec,
        samples=bundle.proposal_samples,
        pipeline_fingerprint="source-only-test.v1",
    )
    assert collection.proposals
    return max(collection.proposals, key=lambda item: item.end_pts - item.start_pts)


def test_pose_left_right_flips_without_crop_agreement_do_not_create_spin_evidence(tmp_path: Path) -> None:
    pose_angles = [0, 0, math.pi, math.pi, 0, 0, math.pi, math.pi, 0, 0, math.pi, math.pi, 0]
    analysis = _analysis(tmp_path, pose_angles=pose_angles, image_angles=[0.0] * len(pose_angles))

    bundle = build_source_evidence(SOURCE_HASH, analysis)
    collection = generate_event_proposals(
        source_video_hash=SOURCE_HASH,
        source_duration_sec=bundle.source_duration_sec,
        samples=bundle.proposal_samples,
        pipeline_fingerprint="source-only-test.v1",
    )

    assert max(sample.periodicity for sample in bundle.proposal_samples) == 0
    assert max((sample.rotation_periodicity or 0) for sample in bundle.moment_samples) == 0
    assert not collection.proposals
    assert "rotation_consensus_absent" in bundle.warnings


def test_sustained_pose_and_crop_rotation_create_shared_event_evidence(tmp_path: Path) -> None:
    angles = [index * 2 * math.pi / 20 for index in range(21)]
    analysis = _analysis(tmp_path, pose_angles=angles, image_angles=angles)

    bundle = build_source_evidence(SOURCE_HASH, analysis)
    proposal = _proposal(bundle)
    evidence = build_action_classification_evidence(bundle, proposal)
    classification = classify_action(evidence)
    moments = localize_profile_moments(
        event_id=proposal.event_id,
        profile="spin",
        event_start_pts=proposal.start_pts,
        event_end_pts=proposal.end_pts,
        samples=bundle.moment_samples,
        source_timeline_fingerprint=bundle.source_timeline_fingerprint,
    )

    assert max(sample.periodicity for sample in bundle.proposal_samples) >= .55
    assert evidence.temporal_features["periodicity"] >= .18
    assert evidence.identity_confirmed is True
    assert classification.profile == "spin"
    assert classification.state == "confirmed"
    assert next(item for item in moments.moments if item.semantic_key == "spin_main").status != "unavailable"


def test_legacy_motion_oscillation_no_longer_fabricates_periodicity() -> None:
    selected = [
        {"frame_id": f"frame_{index:04d}", "source_thumb_index": index, "timestamp": index / 5, "motion_score": .9 if index % 2 else .1}
        for index in range(12)
    ]

    _duration, samples = evidence_from_legacy_analysis(
        SOURCE_HASH,
        {"frame_motion_scores": {"selected": selected, "source_duration_sec": 2.4}},
    )

    assert samples
    assert all(sample.periodicity == 0 for sample in samples)
    assert all("rotation_consensus_absent" in sample.provenance for sample in samples)


def test_pose_frames_without_source_pts_do_not_reconstruct_time_from_sampling_fps() -> None:
    analysis = {
        "sampling": {"source_fps": 30, "effective_fps": 5},
        "pose_data": {"frames": [_pose_frame(index, 0.0) for index in range(4)]},
    }

    bundle = build_source_evidence(SOURCE_HASH, analysis)

    assert bundle.proposal_samples == ()
    assert bundle.moment_samples == ()
    assert "source_observations_absent" in bundle.warnings


def test_global_camera_pan_is_removed_from_target_track_motion(tmp_path: Path) -> None:
    bundle = build_source_evidence(SOURCE_HASH, _translated_scene_analysis(tmp_path, camera_pan=True))

    compensated = [sample.camera_compensated_track_motion for sample in bundle.proposal_samples[1:]]

    assert max(compensated) < .18
    assert all("global_camera_motion_compensated" in sample.provenance for sample in bundle.proposal_samples[1:])


def test_target_motion_against_static_background_is_preserved(tmp_path: Path) -> None:
    bundle = build_source_evidence(SOURCE_HASH, _translated_scene_analysis(tmp_path, camera_pan=False))

    compensated = [sample.camera_compensated_track_motion for sample in bundle.proposal_samples[1:]]

    assert max(compensated) > .35
    assert max(compensated[6:]) < .18


def test_dense_source_timeline_does_not_pad_a_short_motion_change_into_a_broad_event(tmp_path: Path) -> None:
    bundle = build_source_evidence(SOURCE_HASH, _translated_scene_analysis(tmp_path, camera_pan=False))

    collection = generate_event_proposals(
        source_video_hash=SOURCE_HASH,
        source_duration_sec=bundle.source_duration_sec,
        samples=bundle.proposal_samples,
        pipeline_fingerprint="source-only-test.v1",
    )

    assert all(proposal.end_pts - proposal.start_pts < .6 for proposal in collection.proposals)


def test_arm_span_without_a_raised_extended_leg_is_not_spiral_evidence(tmp_path: Path) -> None:
    analysis = _analysis(tmp_path, pose_angles=[0.0] * 12, image_angles=[0.0] * 12)

    bundle = build_source_evidence(SOURCE_HASH, analysis)

    assert max(sample.extension or 0 for sample in bundle.moment_samples) == 0
    assert max(sample.extension_hold for sample in bundle.proposal_samples) == 0
