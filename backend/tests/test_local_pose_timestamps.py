"""Local regression tests for GET /analysis/{id}/pose source timestamps.

The tests call the real ``get_analysis_pose`` endpoint with an ``AsyncMock``
session and a real ``Analysis`` row.  The fixed ``_build_pose_response`` helper
is never mocked, so the core repro assertion fails on the pre-fix router
(``frame_timestamps == {}`` / ``effective_fps is None``) and passes after the
fix.
"""
import copy
import json
import unittest
from unittest.mock import AsyncMock


ANALYSIS_ID = "analysis-pose-time"


def _pose_frame(name):
    return {
        "frame": name,
        "keypoints": [
            {"id": 0, "name": "nose", "x": 1.0, "y": 2.0, "z": 0.0, "visibility": 0.9},
        ],
    }


def _pose_data(frame_names, *, connections=None, **extra):
    return {
        "connections": connections if connections is not None else [[0, 1]],
        "frames": [_pose_frame(name) for name in frame_names],
        **extra,
    }


def _selected(*items):
    return {"selected": list(items)}


class PoseTimestampsEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def _fetch_pose(self, pose_data, frame_motion_scores, *, source_fps=None):
        from app.models import Analysis
        from app.routers import analysis as analysis_router

        analysis = Analysis(
            id=ANALYSIS_ID,
            action_type="跳跃",
            video_path="/tmp/synthetic_pose_time.mp4",
            status="awaiting_target_selection",
            source_fps=source_fps,
            pose_data=pose_data,
            frame_motion_scores=frame_motion_scores,
        )
        session = AsyncMock()
        session.get = AsyncMock(return_value=analysis)
        response = await analysis_router.get_analysis_pose(ANALYSIS_ID, session=session)
        session.get.assert_awaited_once_with(Analysis, ANALYSIS_ID)
        return analysis, response

    async def test_saved_interpolation_quality_survives_real_endpoint_without_backfill(self):
        from unittest.mock import patch
        from app.models import Analysis
        from app.routers import analysis as router
        from app.schemas import PoseResponse

        data = _pose_data(["frame_0001.jpg"])
        original = data["frames"][0]["keypoints"][0]
        data["frames"][0]["keypoints"] = [
            {**original, "interpolated": True},
            {**original, "id": 1, "interpolated": False},
            {**original, "id": 2},
        ]
        snapshot = copy.deepcopy(data)
        for frames in (data, {"frames": [], "connections": []}):
            with self.subTest(empty=not frames["frames"]):
                row = Analysis(id=ANALYSIS_ID, status="completed", action_type="跳跃",
                               video_path="/tmp/synthetic.mp4", pose_data=frames)
                session = AsyncMock()
                session.get.return_value = row
                with patch.object(router, "trial_profile", return_value="legacy-analysis-preview"), \
                     patch.object(router, "extract_pose", side_effect=AssertionError("inference forbidden")), \
                     patch.object(router, "_restore_missing_analysis_frames", side_effect=AssertionError("backfill forbidden")):
                    response = await router.get_analysis_pose(ANALYSIS_ID, session=session)
                # Real response model and endpoint, including a second serialization roundtrip.
                payload = PoseResponse.model_validate(response.model_dump()).model_dump()
                if frames["frames"]:
                    points = payload["frames"][0]["keypoints"]
                    self.assertIs(points[0].get("interpolated"), True)
                    self.assertIs(points[1].get("interpolated"), False)
                    self.assertIsNone(points[2].get("interpolated"))
                else:
                    self.assertEqual(payload["frames"], [])
                session.commit.assert_not_awaited()
        self.assertEqual(data, snapshot)

    async def test_core_repro_get_analysis_pose_returns_saved_source_times(self):
        # Mirrors inputs/pose-time-before.log: persisted frame_0001@2.0 / frame_0002@2.4
        # must survive the real endpoint instead of coming back as {}.
        pose_data = _pose_data(["frame_0001.jpg", "frame_0002.jpg"])
        frame_motion_scores = _selected(
            {"frame_id": "frame_0001", "timestamp": 2.0},
            {"frame_id": "frame_0002", "timestamp": 2.4},
        )

        _, response = await self._fetch_pose(pose_data, frame_motion_scores)

        self.assertEqual(response.frame_timestamps, {"frame_0001.jpg": 2.0, "frame_0002.jpg": 2.4})
        # Same lookup shape as the reproduced assertion.
        self.assertEqual(
            response.frame_timestamps.get("frame_0001.jpg", response.frame_timestamps.get("frame_0001")),
            2.0,
        )
        self.assertEqual(
            response.frame_timestamps.get("frame_0002.jpg", response.frame_timestamps.get("frame_0002")),
            2.4,
        )

    async def test_uneven_non_zero_source_times_map_one_to_one(self):
        pose_data = _pose_data(["frame_0001.jpg", "frame_0002.jpg", "frame_0003.jpg"])
        frame_motion_scores = _selected(
            {"frame_id": "frame_0003.jpg", "timestamp": 2.9},
            {"frame_id": "frame_0001.jpg", "timestamp": 2.0},
            {"frame_id": "frame_0002", "timestamp": 2.4},
        )

        _, response = await self._fetch_pose(pose_data, frame_motion_scores)

        self.assertEqual(
            response.frame_timestamps,
            {"frame_0001.jpg": 2.0, "frame_0002.jpg": 2.4, "frame_0003.jpg": 2.9},
        )
        # No index/fps interpolation between the uneven saved samples.
        self.assertNotIn(2.2, response.frame_timestamps.values())
        self.assertNotIn(2.65, response.frame_timestamps.values())

    async def test_saved_full_frame_id_matches_stem_pose_frame_name(self):
        pose_data = _pose_data(["frame_0001"])
        frame_motion_scores = _selected({"frame_id": "frame_0001.jpg", "timestamp": 2.0})

        _, response = await self._fetch_pose(pose_data, frame_motion_scores)

        self.assertEqual(response.frame_timestamps, {"frame_0001": 2.0})

    async def test_zero_timestamp_is_kept(self):
        pose_data = _pose_data(["frame_0001.jpg"])
        frame_motion_scores = _selected({"frame_id": "frame_0001", "timestamp": 0})

        _, response = await self._fetch_pose(pose_data, frame_motion_scores)

        self.assertIn("frame_0001.jpg", response.frame_timestamps)
        self.assertEqual(response.frame_timestamps["frame_0001.jpg"], 0.0)
        self.assertEqual(
            json.loads(json.dumps(response.frame_timestamps, allow_nan=False)),
            {"frame_0001.jpg": 0.0},
        )

    async def test_missing_or_absent_times_stay_unknown(self):
        pose_data = _pose_data(["frame_0001.jpg", "frame_0002.jpg", "frame_0003.jpg"])
        frame_motion_scores = _selected(
            {"frame_id": "frame_0001", "timestamp": 2.0},
            {"frame_id": "frame_0002"},
            {"frame_id": "frame_0003", "timestamp": None},
        )

        _, response = await self._fetch_pose(pose_data, frame_motion_scores)

        self.assertEqual(response.frame_timestamps, {"frame_0001.jpg": 2.0})

    async def test_absent_or_malformed_motion_scores_leave_times_unknown(self):
        pose_data = _pose_data(["frame_0001.jpg"])
        for frame_motion_scores in (None, {}, {"selected": []}, {"selected": None}, "malformed"):
            with self.subTest(frame_motion_scores=frame_motion_scores):
                _, response = await self._fetch_pose(pose_data, frame_motion_scores)
                self.assertEqual(response.frame_timestamps, {})

    async def test_invalid_timestamps_are_filtered_even_for_existing_frames(self):
        pose_data = _pose_data([f"frame_{index:04d}.jpg" for index in range(1, 10)])
        frame_motion_scores = _selected(
            {"frame_id": "frame_0001", "timestamp": -1.0},
            {"frame_id": "frame_0002", "timestamp": float("-inf")},
            {"frame_id": "frame_0003", "timestamp": float("nan")},
            {"frame_id": "frame_0004", "timestamp": float("inf")},
            {"frame_id": "frame_0005", "timestamp": True},
            {"frame_id": "frame_0006", "timestamp": "2.0"},
            {"frame_id": "frame_0007", "timestamp": []},
            {"frame_id": "frame_0008", "timestamp": {}},
            {"frame_id": "frame_0009", "timestamp": 10 ** 400},
            {"frame_id": "", "timestamp": 1.0},
            "not-a-dict",
            None,
        )

        _, response = await self._fetch_pose(pose_data, frame_motion_scores)

        self.assertEqual(response.frame_timestamps, {})
        # NaN/Infinity must never be able to reach the HTTP JSON payload.
        json.dumps(response.frame_timestamps, allow_nan=False)

    async def test_malformed_selected_payload_does_not_crash(self):
        pose_data = _pose_data(["frame_0001.jpg"])
        for frame_motion_scores in (
            {"selected": "frame_0001"},
            {"selected": {"frame_id": "frame_0001", "timestamp": 2.0}},
            {"selected": [{"frame_id": 1, "timestamp": 2.0}]},
            {"selected": [[], None]},
        ):
            with self.subTest(frame_motion_scores=frame_motion_scores):
                _, response = await self._fetch_pose(pose_data, frame_motion_scores)
                self.assertEqual(response.frame_timestamps, {})

    async def test_unrelated_saved_frames_do_not_get_timestamps(self):
        pose_data = _pose_data(["frame_0001.jpg", "frame_0002.jpg"])
        frame_motion_scores = _selected(
            {"frame_id": "frame_0001", "timestamp": 2.0},
            {"frame_id": "frame_0002", "timestamp": 2.4},
            {"frame_id": "frame_9999", "timestamp": 9.9},
        )

        _, response = await self._fetch_pose(pose_data, frame_motion_scores)

        self.assertEqual(response.frame_timestamps, {"frame_0001.jpg": 2.0, "frame_0002.jpg": 2.4})
        self.assertNotIn("frame_9999", response.frame_timestamps)
        self.assertNotIn("frame_9999.jpg", response.frame_timestamps)

    async def test_saved_source_payloads_are_not_mutated(self):
        pose_data = _pose_data(
            ["frame_0001.jpg", "frame_0002.jpg"],
            pose_diagnostics={"mode": "tracked", "total_frames": 2},
            source_timeline={"frames": [{"source_frame_index": 0, "pts_sec": 2.0}]},
        )
        frame_motion_scores = _selected(
            {"frame_id": "frame_0001", "timestamp": 2.0},
            {"frame_id": "frame_0002", "timestamp": 2.4},
        )
        pose_data_before = copy.deepcopy(pose_data)
        frame_motion_scores_before = copy.deepcopy(frame_motion_scores)

        analysis, response = await self._fetch_pose(pose_data, frame_motion_scores)

        self.assertEqual(pose_data, pose_data_before)
        self.assertEqual(frame_motion_scores, frame_motion_scores_before)
        self.assertIs(analysis.pose_data, pose_data)
        self.assertEqual(analysis.frame_motion_scores, frame_motion_scores_before)
        self.assertEqual(response.frame_timestamps, {"frame_0001.jpg": 2.0, "frame_0002.jpg": 2.4})

    async def test_pose_diagnostics_source_timeline_and_frame_urls_are_preserved(self):
        pose_diagnostics = {"mode": "tracked", "total_frames": 1, "tracked_frames": 1}
        source_timeline = {
            "source_fps": 120.0,
            "frames": [{"source_frame_index": 0, "pts_sec": 2.0}],
        }
        pose_data = _pose_data(
            ["frame_0001.jpg"],
            connections=[[0, 1], [1, 2]],
            pose_diagnostics=pose_diagnostics,
            source_timeline=source_timeline,
        )
        frame_motion_scores = _selected({"frame_id": "frame_0001", "timestamp": 2.0})

        _, response = await self._fetch_pose(pose_data, frame_motion_scores)

        self.assertEqual(response.connections, [[0, 1], [1, 2]])
        self.assertEqual(response.pose_diagnostics, pose_diagnostics)
        self.assertEqual(response.source_timeline, source_timeline)
        self.assertEqual(response.frame_urls, {"frame_0001.jpg": f"/api/frames/{ANALYSIS_ID}/frame_0001.jpg"})
        self.assertEqual([frame.frame for frame in response.frames], ["frame_0001.jpg"])
        self.assertEqual(response.frame_timestamps, {"frame_0001.jpg": 2.0})

    async def test_missing_pose_data_returns_empty_timestamps(self):
        _, response = await self._fetch_pose(
            None,
            _selected({"frame_id": "frame_0001", "timestamp": 2.0}),
        )

        self.assertEqual(response.frames, [])
        self.assertEqual(response.frame_timestamps, {})
        self.assertIsNone(response.effective_fps)

    async def test_effective_fps_requires_a_saved_finite_positive_value(self):
        pose_data = _pose_data(["frame_0001.jpg"])
        selected = _selected({"frame_id": "frame_0001", "timestamp": 2.0})

        _, response = await self._fetch_pose(pose_data, {**selected, "effective_fps": 4.5})
        self.assertEqual(response.effective_fps, 4.5)

        for saved in (
            0,
            0.0,
            -4.5,
            float("nan"),
            float("inf"),
            float("-inf"),
            True,
            False,
            "4.5",
            [],
            {},
            10 ** 400,
        ):
            with self.subTest(saved=saved):
                _, response = await self._fetch_pose(pose_data, {**selected, "effective_fps": saved})
                self.assertIsNone(response.effective_fps)

        _, response = await self._fetch_pose(pose_data, selected)
        self.assertIsNone(response.effective_fps)

    async def test_source_fps_is_not_reused_as_effective_fps(self):
        pose_data = _pose_data(["frame_0001.jpg"])
        selected = _selected({"frame_id": "frame_0001", "timestamp": 2.0})

        _, response = await self._fetch_pose(pose_data, selected, source_fps=120.0)

        self.assertIsNone(response.effective_fps)

    async def test_pose_envelope_is_not_a_sampling_metadata_source(self):
        pose_data = _pose_data(["frame_0001.jpg"], effective_fps=6.25)
        selected = _selected({"frame_id": "frame_0001", "timestamp": 2.0})

        _, response = await self._fetch_pose(pose_data, selected)

        self.assertIsNone(response.effective_fps)

    async def test_pose_diagnostics_is_not_a_sampling_metadata_source(self):
        pose_data = _pose_data(["frame_0001.jpg"], pose_diagnostics={"effective_fps": 6.5})
        selected = _selected({"frame_id": "frame_0001", "timestamp": 2.0})

        _, response = await self._fetch_pose(pose_data, selected)

        self.assertIsNone(response.effective_fps)

    async def test_motion_payload_effective_fps_takes_precedence(self):
        pose_data = _pose_data(["frame_0001.jpg"], effective_fps=6.25)
        frame_motion_scores = {
            **_selected({"frame_id": "frame_0001", "timestamp": 2.0}),
            "effective_fps": 4.5,
        }

        _, response = await self._fetch_pose(pose_data, frame_motion_scores)

        self.assertEqual(response.effective_fps, 4.5)

    async def test_two_argument_build_pose_response_stays_compatible(self):
        from app.routers import analysis as analysis_router

        pose_data = _pose_data(
            ["frame_0001.jpg"],
            pose_diagnostics={"mode": "tracked"},
            source_timeline={"frames": []},
        )

        response = analysis_router._build_pose_response(ANALYSIS_ID, pose_data)

        self.assertEqual(response.frame_timestamps, {})
        self.assertIsNone(response.effective_fps)
        self.assertEqual(response.pose_diagnostics, {"mode": "tracked"})
        self.assertEqual(response.source_timeline, {"frames": []})
        self.assertEqual(response.frames[0].frame, "frame_0001.jpg")

    async def test_helper_ignores_non_mapping_pose_frames(self):
        from app.routers import analysis as analysis_router

        timestamps = analysis_router._saved_pose_frame_timestamps(
            ["frame_0001.jpg", None, {"frame": ""}, {"frame": 7}],
            _selected({"frame_id": "frame_0001", "timestamp": 2.0}),
        )

        self.assertEqual(timestamps, {})


if __name__ == "__main__":
    unittest.main()
