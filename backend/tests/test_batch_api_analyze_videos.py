from __future__ import annotations

import sys
import tempfile
import time
import unittest
import json
from pathlib import Path
from unittest.mock import Mock, patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.batch_api_analyze_videos import (
    BatchClient,
    _explicit_target_payload,
    _find_existing_by_note,
    _aggregate,
    _keyframe_progress_label,
    _keyframe_summary,
    _load_completed_batch_results,
    _load_target_selection_map,
    _pick_target_candidate,
    _poll_until_done,
    _resolve_upload_action,
    main,
)
from app.services.pipeline_version import CURRENT_PIPELINE_VERSION


class BatchApiAnalyzeVideosTests(unittest.TestCase):
    def test_resolve_upload_action_accepts_profile_aliases(self) -> None:
        self.assertEqual(_resolve_upload_action("jump", ""), ("跳跃", "未指定"))
        self.assertEqual(_resolve_upload_action("spin", "直立旋转"), ("旋转", "直立旋转"))
        self.assertEqual(_resolve_upload_action("step", ""), ("步法", "未指定"))
        self.assertEqual(_resolve_upload_action("spiral", ""), ("步法", "燕式滑行"))

    def test_batch_client_retries_transient_get_disconnects(self) -> None:
        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, str]:
                return {"status": "ok"}

        client = BatchClient("http://example.test", timeout=1.0, retry_attempts=2, retry_delay_seconds=0.0)
        fake_http = Mock()
        fake_http.request.side_effect = [httpx.ReadError("disconnect"), FakeResponse()]
        fake_http.close.return_value = None
        client.client = fake_http

        try:
            payload = client.get_json("/api/analysis/1", is_parent_request="true")
        finally:
            client.close()

        self.assertEqual(payload, {"status": "ok"})
        self.assertEqual(fake_http.request.call_count, 2)

    def test_batch_client_retries_transient_upload_disconnects(self) -> None:
        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, str]:
                return {"id": "analysis-1"}

        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = Path(tmpdir) / "clip.mp4"
            video_path.write_bytes(b"fake-video")
            client = BatchClient("http://example.test", timeout=1.0, retry_attempts=2, retry_delay_seconds=0.0)
            fake_http = Mock()
            fake_http.post.side_effect = [httpx.ReadError("disconnect"), FakeResponse()]
            fake_http.close.return_value = None
            client.client = fake_http

            try:
                payload = client.upload(video_path, {"action_type": "jump"})
            finally:
                client.close()

        self.assertEqual(payload, {"id": "analysis-1"})
        self.assertEqual(fake_http.post.call_count, 2)

    def test_main_passes_configured_api_retry_options_to_batch_client(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            argv = [
                "batch_api_analyze_videos.py",
                "--video-dir",
                tmpdir,
                "--api-retry-attempts",
                "9",
                "--api-retry-delay-seconds",
                "4.5",
            ]
            with patch.object(sys, "argv", argv), patch("scripts.batch_api_analyze_videos.BatchClient") as client_cls:
                client = client_cls.return_value
                client.get_json.side_effect = [[{"id": "skater-1", "is_default": True}], []]
                client.close.return_value = None

                self.assertEqual(main(), 0)

        client_cls.assert_called_once_with(
            "http://127.0.0.1:8000",
            120.0,
            retry_attempts=9,
            retry_delay_seconds=4.5,
        )
        client.close.assert_called_once()

    def test_find_existing_by_note_prefers_current_pipeline_completed_analysis(self) -> None:
        selected = _find_existing_by_note(
            [
                {
                    "id": "old-completed",
                    "note": "same",
                    "status": "completed",
                    "pipeline_version": "v5.2.291",
                    "updated_at": "2026-06-13T01:00:00Z",
                },
                {
                    "id": "current-completed",
                    "note": "same",
                    "status": "completed",
                    "pipeline_version": CURRENT_PIPELINE_VERSION,
                    "updated_at": "2026-06-13T00:30:00Z",
                },
                {
                    "id": "current-awaiting",
                    "note": "same",
                    "status": "awaiting_target_selection",
                    "pipeline_version": CURRENT_PIPELINE_VERSION,
                    "updated_at": "2026-06-13T02:00:00Z",
                },
            ],
            "same",
        )

        self.assertIsNotNone(selected)
        self.assertEqual(selected["id"], "current-completed")

    def test_concurrent_stop_on_failure_does_not_submit_later_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            video_dir = Path(tmpdir) / "videos"
            output_dir = Path(tmpdir) / "out"
            video_dir.mkdir()
            for name in ("a.mp4", "b.mp4", "c.mp4"):
                (video_dir / name).write_bytes(b"fake")

            calls: list[str] = []

            def fake_process_video_job(**kwargs: object) -> dict[str, object]:
                video_path = kwargs["video_path"]
                assert isinstance(video_path, Path)
                calls.append(video_path.name)
                if video_path.name == "b.mp4":
                    time.sleep(0.2)
                status = "failed" if video_path.name == "a.mp4" else "completed"
                return {
                    "video": video_path.name,
                    "video_path": str(video_path),
                    "analysis_id": video_path.stem,
                    "report_url": None,
                    "created_by_batch": True,
                    "status": status,
                    "force_score": 80 if status == "completed" else None,
                    "action_type": "jump",
                    "action_subtype": "single",
                    "analysis_profile": "jump",
                    "pipeline_version": "test",
                    "note": "test",
                    "target": {},
                    "pose": {"tracked_ratio": 1.0, "lost_ratio": 0.0, "low_confidence_ratio": 0.0},
                    "keyframes": {"coverage_score": 1.0, "average_confidence": 0.8, "complete": True},
                    "video_temporal": {"available": False},
                    "auto_eval": {},
                    "quality_flags": [],
                    "processing_timings": None,
                    "created_at": None,
                    "updated_at": None,
                    "error_code": None,
                    "error_message": None,
                    "error_detail": None,
                }

            argv = [
                "batch_api_analyze_videos.py",
                "--video-dir",
                str(video_dir),
                "--output-dir",
                str(output_dir),
                "--label",
                "bounded",
                "--force",
                "--concurrency",
                "2",
                "--stop-on-failure",
            ]
            with (
                patch.object(sys, "argv", argv),
                patch("scripts.batch_api_analyze_videos.BatchClient") as client_cls,
                patch("scripts.batch_api_analyze_videos._process_video_job", side_effect=fake_process_video_job),
            ):
                client = client_cls.return_value
                client.get_json.return_value = [{"id": "skater-1", "is_default": True}]
                client.close.return_value = None

                self.assertEqual(main(), 0)

        self.assertEqual(set(calls), {"a.mp4", "b.mp4"})
        self.assertNotIn("c.mp4", calls)

    def test_aggregate_tal_rates_only_count_jump_profiles(self) -> None:
        aggregate = _aggregate(
            [
                {
                    "status": "completed",
                    "analysis_profile": "jump",
                    "keyframes": {
                        "complete": True,
                        "tal_order_valid": True,
                        "profile_keyframe_complete": True,
                        "profile_keyframe_coverage_score": 1.0,
                        "coverage_score": 1.0,
                        "average_confidence": 0.8,
                    },
                    "pose": {},
                    "quality_flags": [],
                },
                {
                    "status": "completed",
                    "analysis_profile": "spin",
                    "keyframes": {
                        "complete": False,
                        "tal_order_valid": False,
                        "profile_keyframe_complete": True,
                        "profile_keyframe_coverage_score": 1.0,
                        "coverage_score": 0.0,
                        "average_confidence": 0.0,
                    },
                    "pose": {},
                    "quality_flags": [],
                },
            ]
        )

        self.assertEqual(aggregate["tal_metric_completed_count"], 1)
        self.assertEqual(aggregate["tal_complete_rate"], 1.0)
        self.assertEqual(aggregate["tal_order_valid_rate"], 1.0)
        self.assertEqual(aggregate["profile_keyframe_complete_rate"], 1.0)
        self.assertEqual(aggregate["average_keyframe_coverage"], 1.0)
        self.assertEqual(aggregate["average_tal_keyframe_coverage"], 1.0)
        self.assertEqual(aggregate["average_keyframe_confidence"], 0.8)
        self.assertEqual(aggregate["average_tal_keyframe_confidence"], 0.8)

    def test_keyframe_progress_label_hides_tal_for_non_jump_profiles(self) -> None:
        jump = {
            "analysis_profile": "jump",
            "keyframes": {"coverage_score": 1.0, "profile_keyframe_coverage_score": 1.0},
        }
        spin = {
            "analysis_profile": "spin",
            "keyframes": {"coverage_score": 0.0, "profile_keyframe_coverage_score": 1.0},
        }

        self.assertEqual(_keyframe_progress_label(jump), "profile_keyframes=100.00% TAL=100.00%")
        self.assertEqual(_keyframe_progress_label(spin), "profile_keyframes=100.00% TAL=n/a")

    def test_main_skips_resumable_rows_from_resume_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            video_dir = Path(tmpdir) / "videos"
            output_dir = Path(tmpdir) / "out"
            resume_path = Path(tmpdir) / "resume.json"
            video_dir.mkdir()
            for name in ("a.mp4", "b.mp4", "c.mp4"):
                (video_dir / name).write_bytes(b"fake")
            resume_row = {
                "video": "a.mp4",
                "video_path": str(video_dir / "a.mp4"),
                "analysis_id": "a",
                "status": "completed",
                "force_score": 80,
                "analysis_profile": "jump",
                "target": {},
                "pose": {"tracked_ratio": 1.0, "lost_ratio": 0.0, "low_confidence_ratio": 0.0},
                "keyframes": {
                    "coverage_score": 1.0,
                    "complete": True,
                    "tal_order_valid": True,
                    "profile_keyframe_complete": True,
                    "profile_keyframe_coverage_score": 1.0,
                    "average_confidence": 0.8,
                },
                "video_temporal": {"available": False},
                "auto_eval": {},
                "quality_flags": [],
            }
            awaiting_row = {
                **resume_row,
                "video": "b.mp4",
                "video_path": str(video_dir / "b.mp4"),
                "analysis_id": "b",
                "status": "awaiting_target_selection",
                "force_score": None,
                "analysis_profile": None,
            }
            resume_path.write_text(json.dumps({"videos": [resume_row, awaiting_row]}), encoding="utf-8")
            calls: list[str] = []

            def fake_process_video_job(**kwargs: object) -> dict[str, object]:
                video_path = kwargs["video_path"]
                assert isinstance(video_path, Path)
                calls.append(video_path.name)
                return {
                    "video": video_path.name,
                    "video_path": str(video_path),
                    "analysis_id": video_path.stem,
                    "report_url": None,
                    "created_by_batch": True,
                    "status": "completed",
                    "force_score": 70,
                    "action_type": "自由滑",
                    "action_subtype": "节目片段",
                    "analysis_profile": "spin",
                    "pipeline_version": "test",
                    "note": "test",
                    "target": {},
                    "pose": {"tracked_ratio": 1.0, "lost_ratio": 0.0, "low_confidence_ratio": 0.0},
                    "keyframes": {
                        "coverage_score": 0.0,
                        "average_confidence": 0.0,
                        "complete": False,
                        "tal_order_valid": False,
                        "profile_keyframe_complete": True,
                        "profile_keyframe_coverage_score": 1.0,
                    },
                    "video_temporal": {"available": False},
                    "auto_eval": {},
                    "quality_flags": [],
                    "processing_timings": None,
                    "created_at": None,
                    "updated_at": None,
                    "error_code": None,
                    "error_message": None,
                    "error_detail": None,
                }

            argv = [
                "batch_api_analyze_videos.py",
                "--video-dir",
                str(video_dir),
                "--output-dir",
                str(output_dir),
                "--label",
                "resume",
                "--force",
                "--skip-completed-from",
                str(resume_path),
            ]
            with (
                patch.object(sys, "argv", argv),
                patch("scripts.batch_api_analyze_videos.BatchClient") as client_cls,
                patch("scripts.batch_api_analyze_videos._process_video_job", side_effect=fake_process_video_job),
            ):
                client = client_cls.return_value
                client.get_json.return_value = [{"id": "skater-1", "is_default": True}]
                client.close.return_value = None

                self.assertEqual(main(), 0)

            output = json.loads((output_dir / "resume.json").read_text(encoding="utf-8"))

        self.assertEqual(calls, ["c.mp4"])
        self.assertEqual({item["video"] for item in output["videos"]}, {"a.mp4", "b.mp4", "c.mp4"})
        self.assertEqual(output["aggregate"]["completed"], 2)
        self.assertEqual(output["aggregate"]["awaiting_target_selection"], 1)

    def test_load_completed_batch_results_does_not_skip_awaiting_rows_with_target_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "resume.json"
            path.write_text(
                json.dumps(
                    {
                        "videos": [
                            {"video": "completed.mp4", "status": "completed", "analysis_id": "completed"},
                            {"video": "awaiting-filled.mp4", "status": "awaiting_target_selection", "analysis_id": "filled"},
                            {"video": "awaiting-empty.mp4", "status": "awaiting_target_selection", "analysis_id": "empty"},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            rows = _load_completed_batch_results(
                path,
                target_selection_video_names={"awaiting-filled.mp4"},
            )

        self.assertEqual({row["video"] for row in rows}, {"completed.mp4", "awaiting-empty.mp4"})

    def test_load_completed_batch_results_accepts_diagnostics_unique_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "diagnostics.json"
            path.write_text(
                json.dumps(
                    {
                        "unique_by_video_rows": [
                            {"video": "latest.mp4", "status": "completed", "analysis_id": "latest"}
                        ],
                        "rows": [
                            {"video": "older.mp4", "status": "completed", "analysis_id": "older"}
                        ],
                    }
                ),
                encoding="utf-8",
            )

            rows = _load_completed_batch_results(path)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["video"], "latest.mp4")

    def test_load_completed_batch_results_merges_multiple_inputs_by_latest_video_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            first = Path(tmpdir) / "old.json"
            second = Path(tmpdir) / "new.json"
            first.write_text(
                json.dumps(
                    {
                        "videos": [
                            {
                                "video": "same.mp4",
                                "status": "awaiting_target_selection",
                                "analysis_id": "same-analysis",
                                "pipeline_version": "v5.2.291",
                                "updated_at": "2026-06-12T00:00:00Z",
                            },
                            {"video": "other.mp4", "status": "completed", "analysis_id": "other"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            second.write_text(
                json.dumps(
                    {
                        "unique_by_video_rows": [
                            {
                                "video": "same.mp4",
                                "status": "completed",
                                "analysis_id": "same-analysis",
                                "pipeline_version": "v5.2.296",
                                "updated_at": "2026-06-13T00:00:00Z",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            rows = _load_completed_batch_results([first, second])

        self.assertEqual({row["video"] for row in rows}, {"same.mp4", "other.mp4"})
        same = next(row for row in rows if row["video"] == "same.mp4")
        self.assertEqual(same["status"], "completed")
        self.assertEqual(same["pipeline_version"], "v5.2.296")

    def test_poll_until_done_retries_transient_server_error(self) -> None:
        request = httpx.Request("GET", "http://example.test/api/analysis/1")
        response = httpx.Response(500, request=request)
        transient = httpx.HTTPStatusError("server error", request=request, response=response)
        api = Mock()
        api.get_json.side_effect = [transient, {"status": "completed", "id": "1"}]

        result = _poll_until_done(
            api,
            "1",
            poll_seconds=0.0,
            max_wait_seconds=10.0,
            auto_confirm_target=False,
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(api.get_json.call_count, 2)

    def test_poll_until_done_does_not_retry_not_found(self) -> None:
        request = httpx.Request("GET", "http://example.test/api/analysis/1")
        response = httpx.Response(404, request=request)
        not_found = httpx.HTTPStatusError("not found", request=request, response=response)
        api = Mock()
        api.get_json.side_effect = not_found

        with self.assertRaises(httpx.HTTPStatusError):
            _poll_until_done(
                api,
                "1",
                poll_seconds=0.0,
                max_wait_seconds=10.0,
                auto_confirm_target=False,
            )

        self.assertEqual(api.get_json.call_count, 1)

    def test_pick_target_candidate_does_not_auto_confirm_manual_review_auto_candidate(self) -> None:
        preview = {
            "target_lock_status": "auto_locked",
            "auto_candidate_id": "candidate_auto_stable",
            "candidates": [
                {
                    "id": "candidate_auto_stable",
                    "confidence": 0.91,
                    "bbox": {"x": 0.48, "y": 0.46, "width": 0.05, "height": 0.11},
                    "quality_flags": ["target_lock_zoomed_multiperson_manual_review"],
                }
            ],
        }

        self.assertIsNone(_pick_target_candidate(preview))
        self.assertEqual(
            _pick_target_candidate(preview, confirm_manual_review_auto_candidate=True),
            "candidate_auto_stable",
        )

    def test_pick_target_candidate_does_not_auto_confirm_awaiting_manual_preview(self) -> None:
        preview = {
            "target_lock_status": "awaiting_manual",
            "auto_candidate_id": "candidate_auto_stable",
            "candidates": [
                {
                    "id": "candidate_auto_stable",
                    "confidence": 0.91,
                    "bbox": {"x": 0.48, "y": 0.46, "width": 0.05, "height": 0.11},
                }
            ],
        }

        self.assertIsNone(_pick_target_candidate(preview))
        self.assertEqual(
            _pick_target_candidate(preview, confirm_manual_review_auto_candidate=True),
            "candidate_auto_stable",
        )

    def test_pick_target_candidate_filters_manual_review_candidates_when_no_auto_id(self) -> None:
        preview = {
            "target_lock_status": "auto_locked",
            "candidates": [
                {
                    "id": "ambiguous",
                    "confidence": 0.95,
                    "bbox": {"x": 0.48, "y": 0.46, "width": 0.05, "height": 0.11},
                    "quality_flags": ["target_lock_zoomed_multiperson_manual_review"],
                },
                {
                    "id": "safe",
                    "confidence": 0.82,
                    "bbox": {"x": 0.42, "y": 0.20, "width": 0.12, "height": 0.36},
                },
            ],
        }

        self.assertEqual(_pick_target_candidate(preview), "safe")

    def test_load_target_selection_map_accepts_candidate_and_manual_bbox(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "targets.json"
            path.write_text(
                """
                {
                  "videos": {
                    "a.mp4": {"candidate_id": "candidate_1"},
                    "b.mp4": {"manual_bbox": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}},
                    "c.mp4": {"x": 0.2, "y": 0.3, "w": 0.1, "h": 0.2}
                  }
                }
                """,
                encoding="utf-8",
            )

            selections = _load_target_selection_map(path)

        self.assertEqual(selections["a.mp4"], {"candidate_id": "candidate_1"})
        self.assertEqual(selections["b.mp4"]["manual_bbox"]["width"], 0.3)
        self.assertEqual(selections["c.mp4"]["manual_bbox"], {"x": 0.2, "y": 0.3, "width": 0.1, "height": 0.2})

    def test_load_target_selection_map_skips_unfilled_template_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "targets.json"
            path.write_text(
                """
                {
                  "videos": {
                    "a.mp4": {
                      "candidate_id": "",
                      "_suggested_auto_candidate_id": "candidate_1",
                      "_note": "Fill this later"
                    },
                    "b.mp4": {"candidate_id": "candidate_2"}
                  }
                }
                """,
                encoding="utf-8",
            )

            selections = _load_target_selection_map(path)

        self.assertNotIn("a.mp4", selections)
        self.assertEqual(selections["b.mp4"], {"candidate_id": "candidate_2"})

    def test_explicit_target_payload_allows_manual_review_candidate_only_when_mapped(self) -> None:
        preview = {
            "target_lock_status": "awaiting_manual",
            "candidates": [
                {
                    "id": "ambiguous",
                    "confidence": 0.95,
                    "quality_flags": ["target_lock_zoomed_multiperson_manual_review"],
                }
            ],
        }

        self.assertEqual(_explicit_target_payload(preview, {"candidate_id": "ambiguous"}), {"candidate_id": "ambiguous"})

    def test_explicit_target_payload_rejects_missing_candidate_id(self) -> None:
        preview = {"candidates": [{"id": "candidate_1"}]}

        with self.assertRaises(ValueError):
            _explicit_target_payload(preview, {"candidate_id": "missing"})

    def test_explicit_target_payload_posts_manual_bbox(self) -> None:
        manual_bbox = {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}

        self.assertEqual(_explicit_target_payload({}, {"manual_bbox": manual_bbox}), {"manual_bbox": manual_bbox})

    def test_keyframe_summary_reports_final_keyframes_separately_from_candidates(self) -> None:
        summary = _keyframe_summary(
            {
                "bio_data": {
                    "key_frames": {"T": "semantic_0001", "A": "semantic_0002", "L": "semantic_0003"},
                    "key_frame_timestamps": {"T": 1.2, "A": 1.5, "L": 1.8},
                    "key_frame_source": "video_ai_refined",
                    "key_frame_confidence": 0.87,
                    "key_frame_candidates": {
                        "T": {"frame_id": "frame_0030", "timestamp": 6.25, "confidence": 0.35},
                        "A": {"frame_id": "frame_0031", "timestamp": 6.31, "confidence": 0.46},
                        "L": {"frame_id": "frame_0032", "timestamp": 6.38, "confidence": 0.48},
                    },
                }
            }
        )

        self.assertTrue(summary["complete"])
        self.assertTrue(summary["tal_order_valid"])
        self.assertEqual(summary["source"], "video_ai_refined")
        self.assertEqual(summary["T"]["frame_id"], "semantic_0001")
        self.assertEqual(summary["T"]["timestamp"], 1.2)
        self.assertEqual(summary["T_candidate_evidence"]["frame_id"], "frame_0030")
        self.assertEqual(summary["T_candidate_evidence"]["timestamp"], 6.25)


if __name__ == "__main__":
    unittest.main()
