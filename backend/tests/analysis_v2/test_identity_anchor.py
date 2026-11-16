from __future__ import annotations

from app.analysis_v2.evaluation.identity_anchor import (
    ParentIdentityAnchor,
    build_parent_identity_anchor_manifest,
    target_lock_payload_from_parent_anchor,
)


HASH = "a" * 64


def test_manifest_exports_only_the_earliest_confirmed_identity_anchor_per_source() -> None:
    workspace = {
        "tracks": [
            {"source_sha256": HASH, "event_id": "private-event", "source_frame_index": 30, "pts": 1.0, "state": "confirmed", "bbox": {"left": .1, "top": .2, "right": .4, "bottom": .8}},
            {"source_sha256": HASH, "event_id": "private-event", "source_frame_index": 15, "pts": .5, "state": "confirmed", "bbox": {"left": .2, "top": .2, "right": .5, "bottom": .8}},
            {"source_sha256": HASH, "event_id": "private-event", "source_frame_index": 5, "pts": .2, "state": "uncertain", "bbox": {"left": .3, "top": .2, "right": .6, "bottom": .8}},
        ],
        "events": [{"event_id": "private-event", "profile": "jump", "start_pts": 0, "end_pts": 2}],
    }

    manifest = build_parent_identity_anchor_manifest(workspace)
    payload = manifest.model_dump(mode="json")

    assert len(manifest.anchors) == 1
    assert manifest.anchors[0].source_frame_index == 15
    assert manifest.anchors[0].bbox.width == .3
    assert "event_id" not in str(payload)
    assert "profile" not in str(payload)
    assert "start_pts" not in str(payload)
    assert "end_pts" not in str(payload)


def test_parent_anchor_maps_to_the_nearest_source_sample_without_becoming_a_timeline() -> None:
    anchor = ParentIdentityAnchor(
        source_sha256=HASH,
        source_frame_index=32,
        pts_sec=1.067,
        bbox={"x": .1, "y": .2, "width": .3, "height": .6},
    )
    payload = target_lock_payload_from_parent_anchor(
        anchor,
        ["frame_0001.jpg", "frame_0002.jpg", "frame_0003.jpg"],
        [
            {"source_frame_index": 0, "pts_sec": 0.0},
            {"source_frame_index": 30, "pts_sec": 1.0},
            {"source_frame_index": 60, "pts_sec": 2.0},
        ],
    )

    assert payload["preview_frame_index"] == 1
    assert payload["selected_bbox"] == {"x": .1, "y": .2, "width": .3, "height": .6}
    assert payload["identity_anchor_source"] == "parent_confirmed"
    assert payload["manual_override"] is True
    assert "bbox_per_frame" not in payload
