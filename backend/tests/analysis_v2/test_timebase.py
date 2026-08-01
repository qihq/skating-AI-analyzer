from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.analysis_v2.contracts import (
    FrameObservation,
    PhysicalMetricInput,
    ObservationStream,
    reject_legacy_physical_payload,
    observation_stream_from_source_index,
)
from app.analysis_v2.timebase import (
    MediaGeometry,
    SourceBox,
    SourceFrameIndex,
    SourcePoint,
    Timebase,
    build_source_frame_index,
    display_to_source,
    source_to_display,
    source_to_target_crop,
    target_crop_to_source,
)


def _index(records):
    return build_source_frame_index(
        records,
        source_video_hash="sha256:source",
        width=1920,
        height=1080,
        duration_sec=2.0,
        timebase=Timebase(numerator=1, denominator=90000, nominal_fps=30, average_fps=30),
        rotation_degrees=90,
    )


def test_source_index_preserves_vfr_duplicate_and_gap_without_sorting() -> None:
    index = _index([
        {"pts_sec": 0.0, "duration_sec": .033},
        {"pts_sec": .033, "duration_sec": .033},
        {"pts_sec": .033, "duration_sec": .033},
        {"pts_sec": .120, "duration_sec": .033},
        {"pts_sec": .100, "duration_sec": .033},
    ])
    assert [frame.source_frame_index for frame in index.frames] == [0, 1, 2, 3, 4]
    assert index.frames[2].status == "duplicate_pts"
    assert index.frames[3].status == "gap_after_previous"
    assert index.frames[4].status == "discontinuity"
    assert index.pts_discontinuities == (4,)
    assert len(index.decode_gaps) == 2
    assert index.frame_at_pts(.119).source_frame_index == 3


def test_coordinate_round_trip_for_all_rotations() -> None:
    point = SourcePoint(x=321, y=777)
    for rotation in (0, 90, 180, 270):
        geometry = MediaGeometry(source_width=1920, source_height=1080, display_rotation_degrees=rotation)
        display = source_to_display(point, geometry)
        restored = display_to_source(display, geometry)
        assert restored.x == pytest.approx(point.x, abs=1e-9)
        assert restored.y == pytest.approx(point.y, abs=1e-9)


def test_target_crop_round_trip() -> None:
    crop = SourceBox(left=.2, top=.1, right=.8, bottom=.9)
    point = SourcePoint(x=.55, y=.4)
    cropped = source_to_target_crop(point, crop)
    restored = target_crop_to_source(cropped, crop)
    assert restored.x == pytest.approx(point.x)
    assert restored.y == pytest.approx(point.y)


def test_physical_metric_contract_rejects_effective_fps_and_approximate_frames() -> None:
    with pytest.raises(ValueError):
        reject_legacy_physical_payload({"effective_fps": 30})
    approximate = FrameObservation(
        source_video_hash="sha256:source", source_frame_index=0, pts_sec=0, duration_sec=.033,
        image_size=(10, 10), pipeline_version="v2", timing_provenance="legacy_approximate",
    )
    with pytest.raises(ValidationError):
        PhysicalMetricInput(observations=(approximate,))


def test_exact_observation_stream_rejects_approximate_frames() -> None:
    approximate = FrameObservation(
        source_video_hash="sha256:source", source_frame_index=0, pts_sec=0, duration_sec=.033,
        image_size=(10, 10), pipeline_version="v2", timing_provenance="legacy_approximate",
    )
    with pytest.raises(ValidationError):
        ObservationStream(source_video_hash="sha256:source", source_index_fingerprint="fp", observations=(approximate,), exact_timestamps=True)


def test_source_index_payload_is_fingerprintable_and_strict() -> None:
    index = _index([{"pts_sec": 0.0, "duration_sec": .033}])
    payload = index.to_timeline()
    assert payload["schema_version"] == "source-timeline.v1"
    assert payload["fingerprint"] == index.fingerprint()
    assert SourceFrameIndex.model_validate(index.model_dump()).fingerprint() == index.fingerprint()


def test_dense_and_sparse_lookup_keep_the_same_source_identity() -> None:
    index = _index([{"pts_sec": 0.0, "duration_sec": .033}, {"pts_sec": .041, "duration_sec": .041}, {"pts_sec": .083, "duration_sec": .042}])
    stream = observation_stream_from_source_index(index, pipeline_version="v2", proxy_size=(480, 270))
    sparse = index.frame_at_pts(.08)
    dense = next(item for item in stream.observations if item.source_frame_index == sparse.source_frame_index)
    assert dense.pts_sec == sparse.pts_sec
    assert dense.source_video_hash == index.source_video_hash


def test_equivalent_container_timeline_stays_within_one_source_frame() -> None:
    original = _index([{"pts_sec": 0.0, "duration_sec": .04}, {"pts_sec": .04, "duration_sec": .04}, {"pts_sec": .08, "duration_sec": .04}])
    transcoded = build_source_frame_index(
        [{"pts_sec": 0.001, "duration_sec": .033}, {"pts_sec": .041, "duration_sec": .033}, {"pts_sec": .081, "duration_sec": .033}],
        source_video_hash="sha256:equivalent", width=1920, height=1080, duration_sec=2,
        timebase=Timebase(numerator=1, denominator=60000, nominal_fps=60, average_fps=60), rotation_degrees=90,
    )
    failures = [abs(original.frame_at_index(i).pts_sec - transcoded.frame_at_index(i).pts_sec) for i in range(3)]
    assert max(failures) <= .04
