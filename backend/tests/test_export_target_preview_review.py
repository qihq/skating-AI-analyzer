from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.export_target_preview_review import (
    _batch_items,
    _bbox_pixel_rect,
    _latest_items_by_video,
    _matches_only_filters,
    _open_image_from_frames_root,
    _review_row,
    _review_summary,
    _save_candidate_crops,
    _top_candidates,
    _write_html_index,
    _write_markdown,
    _write_selection_template,
)


class ExportTargetPreviewReviewTests(unittest.TestCase):
    def test_batch_items_prefers_unique_by_video_rows_from_diagnostics_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "diagnostics.json"
            path.write_text(
                json.dumps(
                    {
                        "unique_by_video_rows": [
                            {
                                "video": "latest.mp4",
                                "analysis_id": "analysis-latest",
                                "status": "awaiting_target_selection",
                            }
                        ],
                        "rows": [
                            {
                                "video": "older.mp4",
                                "analysis_id": "analysis-older",
                                "status": "completed",
                            }
                        ],
                        "videos": [
                            {
                                "video": "batch.mp4",
                                "analysis_id": "analysis-batch",
                                "status": "completed",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            items = _batch_items([path])

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["video"], "latest.mp4")
        self.assertEqual(items[0]["status"], "awaiting_target_selection")
        self.assertEqual(items[0]["_batch_file"], "diagnostics.json")

    def test_batch_items_reads_rows_when_videos_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "diagnostics.json"
            path.write_text(
                json.dumps(
                    {
                        "rows": [
                            {
                                "video": "sample.mp4",
                                "analysis_id": "analysis-1",
                                "status": "awaiting_target_selection",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            items = _batch_items([path])

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["analysis_id"], "analysis-1")
        self.assertEqual(items[0]["video"], "sample.mp4")

    def test_batch_items_deduplicates_by_analysis_id_and_video(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "diagnostics.json"
            path.write_text(
                json.dumps(
                    {
                        "rows": [
                            {
                                "video": "same.mp4",
                                "analysis_id": "analysis-1",
                                "status": "awaiting_target_selection",
                                "updated_at": "2026-06-12T00:00:00Z",
                            },
                            {
                                "video": "same.mp4",
                                "analysis_id": "analysis-1",
                                "status": "completed",
                                "updated_at": "2026-06-13T00:00:00Z",
                            },
                            {
                                "video": "same.mp4",
                                "analysis_id": "analysis-2",
                                "status": "awaiting_target_selection",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            items = _batch_items([path])

        self.assertEqual(
            [(item["analysis_id"], item["video"], item["status"]) for item in items],
            [("analysis-1", "same.mp4", "completed"), ("analysis-2", "same.mp4", "awaiting_target_selection")],
        )

    def test_latest_items_by_video_prefers_newer_completed_current_version_row(self) -> None:
        items = [
            {
                "video": "same.mp4",
                "analysis_id": "old-awaiting",
                "status": "awaiting_target_selection",
                "pipeline_version": "v5.2.291",
                "updated_at": "2026-06-12T00:00:00Z",
                "_source_index": 0,
            },
            {
                "video": "same.mp4",
                "analysis_id": "new-completed",
                "status": "completed",
                "pipeline_version": "v5.2.296",
                "updated_at": "2026-06-13T00:00:00Z",
                "_source_index": 1,
            },
        ]

        latest = _latest_items_by_video(items)

        self.assertEqual(len(latest), 1)
        self.assertEqual(latest[0]["analysis_id"], "new-completed")

    def test_top_candidates_prioritizes_auto_candidate(self) -> None:
        preview = {
            "auto_candidate_id": "auto",
            "candidates": [
                {"id": "high", "confidence": 0.95, "bbox": {"width": 0.1, "height": 0.1}},
                {"id": "auto", "confidence": 0.80, "bbox": {"width": 0.05, "height": 0.2}},
            ],
        }

        candidates = _top_candidates(preview, 2)

        self.assertEqual(candidates[0]["id"], "auto")

    def test_bbox_pixel_rect_clamps_padded_crop_to_image(self) -> None:
        rect = _bbox_pixel_rect(
            {"x": 0.0, "y": 0.1, "width": 0.3, "height": 0.4},
            image_width=200,
            image_height=100,
            padding_ratio=0.2,
        )

        self.assertEqual(rect, (0, 2, 72, 58))

    def test_open_image_from_frames_root_reads_local_upload_frame(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            frame_dir = root / "analysis-1" / "frames"
            frame_dir.mkdir(parents=True)
            Image.new("RGB", (9, 7), (1, 2, 3)).save(frame_dir / "frame_0001.jpg")

            image = _open_image_from_frames_root(root, "analysis-1", "frame_0001.jpg")

        self.assertIsNotNone(image)
        self.assertEqual(image.size, (9, 7))

    def test_save_candidate_crops_and_review_row_include_crop_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            preview = {
                "target_lock_status": "awaiting_manual",
                "auto_candidate_id": "candidate_1",
                "preview_frame": "frame_0001.jpg",
                "candidates": [
                    {
                        "id": "candidate_1",
                        "confidence": 0.87,
                        "bbox": {"x": 0.25, "y": 0.2, "width": 0.5, "height": 0.6},
                        "source": "yolo_preview",
                        "anchor_frame": "frame_0003.jpg",
                        "anchor_index": 2,
                        "support_anchor_frames": ["frame_0001.jpg", "frame_0003.jpg"],
                    }
                ],
            }
            preview_image = Image.new("RGB", (200, 100), (255, 255, 255))
            anchor_image = Image.new("RGB", (200, 100), (10, 20, 30))

            crop_paths = _save_candidate_crops(
                preview_image,
                preview,
                crop_dir=base / "crops",
                video_or_analysis="sample.mp4",
                candidate_limit=3,
                anchor_images={"frame_0003.jpg": anchor_image},
            )
            row = _review_row(
                {"video": "sample.mp4", "analysis_id": "analysis-1", "status": "awaiting_target_selection"},
                preview,
                image_path=Path("overlay.jpg"),
                candidate_limit=3,
                candidate_crop_paths=crop_paths,
            )

            crop_path = crop_paths["candidate_1"]
            self.assertTrue(crop_path["path"].exists())
            crop = Image.open(crop_path["path"])
            self.assertLessEqual(crop.width, 260)
            self.assertEqual(crop.getpixel((0, 0)), (10, 20, 30))
            self.assertEqual(row["candidates"][0]["crop_image"], str(crop_path["path"]))
            self.assertEqual(row["candidates"][0]["crop_source_frame"], "frame_0003.jpg")
            self.assertEqual(row["candidates"][0]["source"], "yolo_preview")
            self.assertEqual(row["candidates"][0]["anchor_frame"], "frame_0003.jpg")
            self.assertEqual(row["candidates"][0]["anchor_index"], 2)
            self.assertEqual(row["candidates"][0]["support_anchor_frames"], ["frame_0001.jpg", "frame_0003.jpg"])

    def test_review_row_includes_candidate_diagnostics(self) -> None:
        preview = {
            "target_lock_status": "awaiting_manual",
            "auto_candidate_id": "candidate_1",
            "preview_frame": "frame_0001.jpg",
            "preview_frame_url": "/api/frames/a/frame_0001.jpg",
            "candidates": [
                {
                    "id": "candidate_1",
                    "confidence": 0.87,
                    "bbox": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4},
                    "support_frame_count": 5,
                    "multiperson_ambiguous_frame_count": 2,
                    "quality_flags": ["target_lock_zoomed_multiperson_manual_review"],
                }
            ],
        }

        row = _review_row(
            {"video": "sample.mp4", "analysis_id": "analysis-1", "status": "awaiting_target_selection"},
            preview,
            image_path=Path("overlay.jpg"),
            candidate_limit=3,
        )

        self.assertEqual(row["auto_candidate_id"], "candidate_1")
        self.assertEqual(row["candidates"][0]["label"], "C1*")
        self.assertEqual(row["candidates"][0]["multiperson_ambiguous_frame_count"], 2)
        self.assertIn("zoomed_multiperson", row["review_risk_tags"])

    def test_review_row_adds_target_risk_tags(self) -> None:
        preview = {
            "target_lock_status": "awaiting_manual",
            "auto_candidate_id": "candidate_1",
            "preview_frame": "frame_0001.jpg",
            "preview_frame_url": "/api/frames/a/frame_0001.jpg",
            "candidates": [
                {
                    "id": "candidate_1",
                    "confidence": 0.87,
                    "bbox": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4},
                    "multiperson_selected_pair_frame_count": 1,
                    "multiperson_same_anchor_competitor_count": 1,
                    "multiperson_competitor_count": 25,
                    "quality_flags": [
                        "target_lock_zoomed_multiperson_manual_review",
                        "target_lock_compact_motion_review_candidate_preferred_over_tall_multiperson_risk",
                    ],
                },
                {
                    "id": "candidate_2",
                    "confidence": 0.86,
                    "bbox": {"x": 0.2, "y": 0.3, "width": 0.2, "height": 0.3},
                    "quality_flags": ["target_lock_zoomed_foreground_deprioritized_for_stable_small_target"],
                },
            ],
        }

        row = _review_row(
            {"video": "sample.mp4", "analysis_id": "analysis-1", "status": "awaiting_target_selection"},
            preview,
            image_path=None,
            candidate_limit=3,
        )

        self.assertEqual(
            row["review_risk_tags"],
            [
                "compact_motion_reselected",
                "zoomed_multiperson",
                "selected_pair_competitor",
                "same_anchor_competitor",
                "high_competitor_load",
                "foreground_deprioritized_alternative",
            ],
        )

    def test_write_selection_template_uses_blank_candidate_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "template.json"
            _write_selection_template(
                [
                    {
                        "video": "sample.mp4",
                        "analysis_id": "analysis-1",
                        "auto_candidate_id": "candidate_1",
                        "overlay_image": "overlay.jpg",
                    }
                ],
                path,
            )
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["videos"]["sample.mp4"]["candidate_id"], "")
        self.assertEqual(payload["videos"]["sample.mp4"]["_suggested_auto_candidate_id"], "candidate_1")

    def test_review_summary_counts_target_risks_and_candidate_rank(self) -> None:
        rows = [
            {
                "target_lock_status": "awaiting_manual",
                "auto_candidate_id": "candidate_1",
                "review_risk_tags": ["zoomed_multiperson", "same_anchor_competitor"],
                "candidates": [
                    {
                        "id": "candidate_1",
                        "quality_flags": [
                            "target_lock_zoomed_multiperson_background_auto_lock_allowed",
                            "target_lock_zoomed_multiperson_manual_review",
                            "target_lock_auto_lock_blocked_by_manual_review",
                        ],
                    },
                    {"id": "candidate_2", "quality_flags": ["other_flag"]},
                ],
            },
            {
                "target_lock_status": "auto_locked",
                "auto_candidate_id": "candidate_2",
                "review_risk_tags": ["zoomed_multiperson"],
                "candidates": [
                    {"id": "candidate_1", "quality_flags": ["target_lock_zoomed_multiperson_background_auto_lock_allowed"]},
                    {"id": "candidate_2", "quality_flags": []},
                ],
            },
        ]

        summary = _review_summary(rows)

        self.assertEqual(summary["target_lock_status_counts"], {"awaiting_manual": 1, "auto_locked": 1})
        self.assertEqual(summary["risk_tag_counts"]["zoomed_multiperson"], 2)
        self.assertEqual(summary["risk_tag_counts"]["same_anchor_competitor"], 1)
        self.assertEqual(summary["candidate_count_distribution"], {"2": 2})
        self.assertEqual(summary["auto_candidate_rank_counts"], {"1": 1, "2": 1})
        self.assertEqual(summary["background_auto_lock_allowed_with_manual_review_count"], 1)

    def test_write_markdown_includes_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            markdown_path = base / "review.md"
            _write_markdown(
                [
                    {
                        "video": "sample.mp4",
                        "analysis_id": "analysis-1",
                        "target_lock_status": "awaiting_manual",
                        "auto_candidate_id": "candidate_1",
                        "overlay_image": "overlay.jpg",
                        "review_risk_tags": ["zoomed_multiperson"],
                        "candidates": [
                            {
                                "label": "C1*",
                                "id": "candidate_1",
                                "confidence": 0.87,
                                "support_count": 3,
                                "support_frame_count": 5,
                                "quality_flags": [
                                    "target_lock_zoomed_multiperson_background_auto_lock_allowed",
                                    "target_lock_auto_lock_blocked_by_manual_review",
                                ],
                            }
                        ],
                    }
                ],
                markdown_path,
                label="review",
                template_path=base / "target-selection-template.json",
            )

            markdown = markdown_path.read_text(encoding="utf-8")

        self.assertIn("## Summary", markdown)
        self.assertIn('"awaiting_manual": 1', markdown)
        self.assertIn("Background auto-lock allowed with manual-review count: 1", markdown)

    def test_write_html_index_includes_frontend_target_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            overlay_dir = base / "overlays"
            overlay_dir.mkdir()
            overlay_path = overlay_dir / "sample.jpg"
            overlay_path.write_bytes(b"fake")
            crop_dir = overlay_dir / "crops"
            crop_dir.mkdir()
            crop_path = crop_dir / "sample_C1_candidate_1.jpg"
            crop_path.write_bytes(b"fake")
            index_path = base / "index.html"
            _write_html_index(
                [
                    {
                        "video": "sample.mp4",
                        "analysis_id": "analysis-1",
                        "target_lock_status": "awaiting_manual",
                        "auto_candidate_id": "candidate_1",
                        "overlay_image": str(overlay_path),
                        "review_risk_tags": ["zoomed_multiperson"],
                        "candidates": [
                            {
                                "label": "C1*",
                                "id": "candidate_1",
                                "confidence": 0.87,
                                "crop_image": str(crop_path),
                                "crop_source_frame": "frame_0003.jpg",
                                "anchor_frame": "frame_0003.jpg",
                                "multiperson_ambiguous_frame_count": 2,
                                "multiperson_selected_pair_frame_count": 1,
                                "multiperson_competitor_count": 12,
                                "multiperson_max_competitor_confidence": 0.91,
                            }
                        ],
                    }
                ],
                index_path,
                label="review",
                frontend_url="http://localhost:8080",
                template_path=base / "target-selection-template.json",
                review_json_path=base / "target-preview-review.json",
                review_md_path=base / "target-preview-review.md",
            )

            html = index_path.read_text(encoding="utf-8")

        self.assertIn("overlays/sample.jpg", html)
        self.assertIn("overlays/crops/sample_C1_candidate_1.jpg", html)
        self.assertIn("<th class=\"crop\">Crop</th>", html)
        self.assertIn("<th>Anchor</th>", html)
        self.assertIn("frame_0003.jpg", html)
        self.assertIn("crop: frame_0003.jpg", html)
        self.assertIn("http://localhost:8080/report/analysis-1/target", html)
        self.assertIn("candidate_1", html)
        self.assertIn("Allowed+Manual", html)
        self.assertIn('id="selectionOutput"', html)
        self.assertIn('id="downloadSelection"', html)
        self.assertIn('id="selectedCount"', html)
        self.assertIn("Selected: 0 / 1", html)
        self.assertIn('id="missingCount"', html)
        self.assertIn("Missing: 1", html)
        self.assertIn('id="completionStatus"', html)
        self.assertIn("_review_row_count", html)
        self.assertIn("_selected_count", html)
        self.assertIn("_missing_count", html)
        self.assertIn("_complete", html)
        self.assertIn('id="prevUnselected"', html)
        self.assertIn('id="nextUnselected"', html)
        self.assertIn('id="reviewSearch"', html)
        self.assertIn('id="riskFilter"', html)
        self.assertIn('id="sortMode"', html)
        self.assertIn('Risk first', html)
        self.assertIn('id="showUnselectedOnly"', html)
        self.assertIn('id="visibleCount"', html)
        self.assertIn('data-risk-score="50"', html)
        self.assertIn('data-original-index="0"', html)
        self.assertIn("sortArticles", html)
        self.assertIn("articleSortValue", html)
        self.assertIn("chooseCandidateByNumber", html)
        self.assertIn('event.key === "j"', html)
        self.assertIn('event.key === "k"', html)
        self.assertIn('closest("tr")', html)
        self.assertIn('type="radio"', html)
        self.assertIn('data-video="sample.mp4"', html)
        self.assertIn('data-tags="zoomed_multiperson"', html)
        self.assertIn('candidate_id', html)

    def test_matches_only_filters_accepts_video_stem_name_or_analysis_id(self) -> None:
        item = {
            "video": "Sample Video.mp4",
            "video_path": "C:/videos/Sample Video.mp4",
            "analysis_id": "analysis-1",
        }

        self.assertTrue(_matches_only_filters(item, set()))
        self.assertTrue(_matches_only_filters(item, {"sample video"}))
        self.assertTrue(_matches_only_filters(item, {"sample video.mp4"}))
        self.assertTrue(_matches_only_filters(item, {"analysis-1"}))
        self.assertFalse(_matches_only_filters(item, {"other"}))


if __name__ == "__main__":
    unittest.main()
