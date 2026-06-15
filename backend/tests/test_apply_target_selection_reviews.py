from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.apply_target_selection_reviews import apply_target_selection_reviews, validate_target_selection_reviews


class ApplyTargetSelectionReviewsTests(unittest.TestCase):
    def test_skips_unfilled_template_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            review = base / "review.json"
            selection = base / "selection.json"
            review.write_text(
                json.dumps({"rows": [{"video": "a.mp4", "analysis_id": "analysis-a", "candidates": [{"id": "candidate-1"}]}]}),
                encoding="utf-8",
            )
            selection.write_text(
                json.dumps({"videos": {"a.mp4": {"candidate_id": "", "_analysis_id": "analysis-a"}}}),
                encoding="utf-8",
            )

            with patch("scripts.apply_target_selection_reviews.BatchClient") as client_cls:
                client = client_cls.return_value
                payload = apply_target_selection_reviews(
                    review_json=review,
                    target_selection_json=selection,
                    base_url="http://example.test",
                    output_dir=base,
                    label="apply",
                    video_dir=None,
                    timeout=1.0,
                    poll_seconds=0.0,
                    max_wait_seconds=1.0,
                )

        self.assertEqual(payload["total_selections"], 0)
        self.assertEqual(payload["applied_count"], 0)
        client.post_json.assert_not_called()

    def test_applies_candidate_selection_and_writes_batch_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            review = base / "review.json"
            selection = base / "selection.json"
            review.write_text(
                json.dumps(
                    {
                        "rows": [
                            {
                                "video": "a.mp4",
                                "analysis_id": "analysis-a",
                                "status": "awaiting_target_selection",
                                "candidates": [{"id": "candidate-1"}],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            selection.write_text(
                json.dumps({"videos": {"a.mp4": {"candidate_id": "candidate-1", "_analysis_id": "analysis-a"}}}),
                encoding="utf-8",
            )
            completed = {
                "id": "analysis-a",
                "status": "completed",
                "analysis_profile": "step",
                "force_score": 70,
                "action_type": "自由滑",
                "action_subtype": "节目片段",
                "pipeline_version": "test",
                "target_lock": {
                    "status": "locked",
                    "selected_candidate_id": "candidate-1",
                    "manual_override": True,
                    "selected_bbox": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4},
                },
                "pose_data": {
                    "pose_diagnostics": {
                        "total_frames": 1,
                        "tracked_frames": 1,
                        "lost_frames": 0,
                        "low_confidence_frames": 0,
                        "frames": [{"tracking_state": "tracked"}],
                    }
                },
                "bio_data": {
                    "key_frames": {"步法序列": "semantic_0001"},
                    "key_frame_timestamps": {"步法序列": 1.0},
                    "key_frame_candidates": {},
                },
                "video_temporal_diagnostics": {},
                "cross_validation": {},
                "vision_structured": {},
            }

            with patch("scripts.apply_target_selection_reviews.BatchClient") as client_cls:
                client = client_cls.return_value
                client.get_json.return_value = completed
                client.post_json.return_value = {"status": "pending"}
                client.close.return_value = None

                payload = apply_target_selection_reviews(
                    review_json=review,
                    target_selection_json=selection,
                    base_url="http://example.test",
                    output_dir=base,
                    label="apply",
                    video_dir=base,
                    timeout=1.0,
                    poll_seconds=0.0,
                    max_wait_seconds=1.0,
                )

            output = json.loads((base / "apply.json").read_text(encoding="utf-8"))

        client.post_json.assert_called_once_with("/api/analysis/analysis-a/target-lock", {"candidate_id": "candidate-1"})
        self.assertEqual(payload["applied_count"], 1)
        self.assertEqual(payload["status_counts"], {"completed": 1})
        self.assertEqual(output["videos"][0]["analysis_id"], "analysis-a")
        self.assertEqual(output["videos"][0]["status"], "completed")

    def test_apply_fails_if_confirmed_target_does_not_enable_manual_identity_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            review = base / "review.json"
            selection = base / "selection.json"
            review.write_text(
                json.dumps(
                    {
                        "rows": [
                            {
                                "video": "a.mp4",
                                "analysis_id": "analysis-a",
                                "status": "awaiting_target_selection",
                                "candidates": [{"id": "candidate-1"}],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            selection.write_text(
                json.dumps({"videos": {"a.mp4": {"candidate_id": "candidate-1", "_analysis_id": "analysis-a"}}}),
                encoding="utf-8",
            )
            completed = {
                "id": "analysis-a",
                "status": "completed",
                "analysis_profile": "step",
                "force_score": 70,
                "pipeline_version": "test",
                "target_lock": {"status": "locked", "selected_candidate_id": "candidate-1"},
            }

            with patch("scripts.apply_target_selection_reviews.BatchClient") as client_cls:
                client = client_cls.return_value
                client.get_json.return_value = completed
                client.post_json.return_value = {"status": "pending"}
                client.close.return_value = None

                payload = apply_target_selection_reviews(
                    review_json=review,
                    target_selection_json=selection,
                    base_url="http://example.test",
                    output_dir=base,
                    label="apply",
                    video_dir=base,
                    timeout=1.0,
                    poll_seconds=0.0,
                    max_wait_seconds=1.0,
                )

        self.assertEqual(payload["applied_count"], 0)
        self.assertEqual(len(payload["failures"]), 1)
        self.assertEqual(payload["failures"][0]["video"], "a.mp4")
        self.assertIn("manual target identity lock was not confirmed", payload["failures"][0]["error"])

    def test_apply_can_require_completed_status_after_manual_identity_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            review = base / "review.json"
            selection = base / "selection.json"
            review.write_text(
                json.dumps(
                    {
                        "rows": [
                            {
                                "video": "a.mp4",
                                "analysis_id": "analysis-a",
                                "status": "awaiting_target_selection",
                                "candidates": [{"id": "candidate-1"}],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            selection.write_text(
                json.dumps({"videos": {"a.mp4": {"candidate_id": "candidate-1", "_analysis_id": "analysis-a"}}}),
                encoding="utf-8",
            )
            still_waiting = {
                "id": "analysis-a",
                "status": "awaiting_target_selection",
                "analysis_profile": "unknown",
                "pipeline_version": "test",
                "target_lock": {
                    "status": "locked",
                    "selected_candidate_id": "candidate-1",
                    "manual_override": True,
                    "selected_bbox": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4},
                },
            }

            with patch("scripts.apply_target_selection_reviews.BatchClient") as client_cls:
                client = client_cls.return_value
                client.get_json.return_value = still_waiting
                client.post_json.return_value = {"status": "pending"}
                client.close.return_value = None

                payload = apply_target_selection_reviews(
                    review_json=review,
                    target_selection_json=selection,
                    base_url="http://example.test",
                    output_dir=base,
                    label="apply",
                    video_dir=base,
                    timeout=1.0,
                    poll_seconds=0.0,
                    max_wait_seconds=1.0,
                    require_completed=True,
                )

        self.assertEqual(payload["applied_count"], 0)
        self.assertEqual(len(payload["failures"]), 1)
        self.assertEqual(payload["failures"][0]["video"], "a.mp4")
        self.assertIn("analysis did not complete after applying manual target identity lock", payload["failures"][0]["error"])

    def test_validate_target_selection_reviews_reports_missing_and_invalid_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            review = base / "review.json"
            selection = base / "selection.json"
            review.write_text(
                json.dumps(
                    {
                        "rows": [
                            {"video": "a.mp4", "analysis_id": "analysis-a", "candidates": [{"id": "candidate-1"}]},
                            {"video": "b.mp4", "analysis_id": "analysis-b", "candidates": [{"id": "candidate-2"}]},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            selection.write_text(
                json.dumps({"videos": {"a.mp4": {"candidate_id": "missing"}, "other.mp4": {"candidate_id": "candidate-x"}}}),
                encoding="utf-8",
            )

            payload = validate_target_selection_reviews(
                review_json=review,
                target_selection_json=selection,
            )

        self.assertEqual(payload["review_row_count"], 2)
        self.assertEqual(payload["total_selections"], 2)
        self.assertEqual(payload["matched_selections"], 0)
        self.assertEqual(payload["missing_selection_count"], 1)
        self.assertEqual(
            payload["validation_failures"],
            [
                {"video": "a.mp4", "error": "candidate_id_not_in_review"},
                {"video": "other.mp4", "error": "video_not_found_in_review"},
            ],
        )

    def test_validate_target_selection_reviews_can_require_complete_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            review = base / "review.json"
            selection = base / "selection.json"
            review.write_text(
                json.dumps(
                    {
                        "rows": [
                            {"video": "a.mp4", "analysis_id": "analysis-a", "candidates": [{"id": "candidate-1"}]},
                            {"video": "b.mp4", "analysis_id": "analysis-b", "candidates": [{"id": "candidate-2"}]},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            selection.write_text(
                json.dumps({"videos": {"a.mp4": {"candidate_id": "candidate-1"}}}),
                encoding="utf-8",
            )

            payload = validate_target_selection_reviews(
                review_json=review,
                target_selection_json=selection,
                require_complete=True,
            )

        self.assertTrue(payload["require_complete"])
        self.assertEqual(payload["matched_selections"], 1)
        self.assertEqual(payload["missing_selection_count"], 1)
        self.assertEqual(payload["missing_selection_samples"], ["b.mp4"])
        self.assertEqual(payload["validation_failures"], [{"video": "b.mp4", "error": "missing_required_selection"}])

    def test_validate_target_selection_reviews_reports_html_completion_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            review = base / "review.json"
            selection = base / "selection.json"
            review.write_text(
                json.dumps(
                    {
                        "rows": [
                            {"video": "a.mp4", "analysis_id": "analysis-a", "candidates": [{"id": "candidate-1"}]},
                            {"video": "b.mp4", "analysis_id": "analysis-b", "candidates": [{"id": "candidate-2"}]},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            selection.write_text(
                json.dumps(
                    {
                        "_review_label": "review-2",
                        "_review_row_count": 2,
                        "_selected_count": 1,
                        "_missing_count": 1,
                        "_complete": False,
                        "_source": "target-preview-review-html",
                        "videos": {"a.mp4": {"candidate_id": "candidate-1"}},
                    }
                ),
                encoding="utf-8",
            )

            payload = validate_target_selection_reviews(
                review_json=review,
                target_selection_json=selection,
                require_complete=True,
            )

        self.assertEqual(
            payload["selection_review_metadata"],
            {
                "review_label": "review-2",
                "review_row_count": 2,
                "selected_count": 1,
                "missing_count": 1,
                "complete": False,
                "source": "target-preview-review-html",
            },
        )
        self.assertEqual(payload["validation_failures"], [{"video": "b.mp4", "error": "missing_required_selection"}])

    def test_apply_stops_before_posting_when_complete_selection_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            review = base / "review.json"
            selection = base / "selection.json"
            review.write_text(
                json.dumps(
                    {
                        "rows": [
                            {"video": "a.mp4", "analysis_id": "analysis-a", "candidates": [{"id": "candidate-1"}]},
                            {"video": "b.mp4", "analysis_id": "analysis-b", "candidates": [{"id": "candidate-2"}]},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            selection.write_text(
                json.dumps({"videos": {"a.mp4": {"candidate_id": "candidate-1", "_analysis_id": "analysis-a"}}}),
                encoding="utf-8",
            )

            with patch("scripts.apply_target_selection_reviews.BatchClient") as client_cls:
                client = client_cls.return_value
                payload = apply_target_selection_reviews(
                    review_json=review,
                    target_selection_json=selection,
                    base_url="http://example.test",
                    output_dir=base,
                    label="apply",
                    video_dir=None,
                    timeout=1.0,
                    poll_seconds=0.0,
                    max_wait_seconds=1.0,
                    require_complete=True,
                )

        self.assertEqual(payload["applied_count"], 0)
        self.assertEqual(payload["failures"], [{"video": "b.mp4", "error": "missing_required_selection"}])
        client.post_json.assert_not_called()

    def test_apply_stops_before_posting_when_validation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            review = base / "review.json"
            selection = base / "selection.json"
            review.write_text(
                json.dumps({"rows": [{"video": "a.mp4", "analysis_id": "analysis-a", "candidates": [{"id": "candidate-1"}]}]}),
                encoding="utf-8",
            )
            selection.write_text(
                json.dumps({"videos": {"a.mp4": {"candidate_id": "missing", "_analysis_id": "analysis-a"}}}),
                encoding="utf-8",
            )

            with patch("scripts.apply_target_selection_reviews.BatchClient") as client_cls:
                client = client_cls.return_value
                payload = apply_target_selection_reviews(
                    review_json=review,
                    target_selection_json=selection,
                    base_url="http://example.test",
                    output_dir=base,
                    label="apply",
                    video_dir=None,
                    timeout=1.0,
                    poll_seconds=0.0,
                    max_wait_seconds=1.0,
                )

        self.assertEqual(payload["applied_count"], 0)
        self.assertEqual(payload["failures"], [{"video": "a.mp4", "error": "candidate_id_not_in_review"}])
        client.post_json.assert_not_called()


if __name__ == "__main__":
    unittest.main()
