from __future__ import annotations

from types import SimpleNamespace

from scripts.skate_video_iteration_diagnostics import _build_target_lock_payload, _track_bboxes


class _TargetLock:
    @staticmethod
    def build_target_lock_payload(preview):
        return {
            "status": preview.target_lock_status,
            "selected_candidate_id": preview.auto_candidate_id,
            "selected_bbox": None,
            "manual_override": False,
        }


def test_diagnostic_runner_does_not_convert_manual_review_into_a_synthetic_manual_lock() -> None:
    preview = SimpleNamespace(
        target_lock_status="awaiting_manual",
        auto_candidate_id="candidate-1",
        candidates=[{"id": "candidate-1", "bbox": {"x": .1, "y": .2, "width": .3, "height": .6}}],
    )

    payload = _build_target_lock_payload(_TargetLock(), preview)

    assert payload["status"] == "awaiting_manual"
    assert payload["selected_bbox"] is None
    assert payload["manual_override"] is False


class _PersonTracker:
    def __init__(self) -> None:
        self.kwargs = None

    def track_person_bbox_detailed(self, frame_paths, selected_bbox, **kwargs):
        self.kwargs = kwargs
        return [selected_bbox for _ in frame_paths], [], []


def test_parent_confirmed_identity_anchor_preserves_manual_lock_mode_during_tracking() -> None:
    tracker = _PersonTracker()

    _track_bboxes(
        tracker,
        ["frame-001.jpg"],
        {
            "selected_bbox": {"x": .1, "y": .2, "width": .3, "height": .6},
            "preview_frame_index": 0,
            "manual_override": True,
            "identity_anchor_source": "parent_confirmed",
        },
        8.0,
    )

    assert tracker.kwargs["manual_lock_mode"] is True
