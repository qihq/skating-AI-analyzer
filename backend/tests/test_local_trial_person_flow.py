"""Synthetic control-flow regressions for the legacy single-person local analysis path.

Scope and mock boundaries
-------------------------
Real production entry points exercised here:

* ``process_analysis`` (legacy ``legacy-analysis-preview`` profile), including the real
  ``build_target_preview`` / ``build_target_lock_payload`` / ``select_stable_target_candidate``
  target decision, the real ``_save_local_analysis_result`` + ``local_fallback_report``
  report construction and the real SQLite ``Analysis`` persistence.
* ``confirm_target_lock`` (real manual target confirmation and background enqueue).
* ``retry_analysis`` (real retry endpoint, same analysis id) plus execution of the real
  queued ``process_analysis_with_media_renditions`` background callable.
* ``get_analysis`` / ``get_analysis_pose`` / ``get_target_preview`` read-backs.

Deterministic injected fixtures (no model, video, network, NAS sample or external AI):

* video decode: ``precheck_video``, ``extract_motion_sampled_frames``, ``build_video_input_window``;
* person detector: ``detect_person_candidates`` (the production candidate selection in
  ``_formal_target_preview_candidates`` / ``select_stable_target_candidate`` still runs);
* native tracker: ``track_person_bbox_detailed``;
* pose model: ``extract_pose``;
* compute-heavy biomechanics/profile inference: ``analyze_biomechanics``,
  ``attach_key_frame_candidates``, ``infer_analysis_profile``, ``infer_jump_subtype_evidence``;
* media manifest/renditions and local runtime preflight are stubbed so no ffmpeg/ffprobe or
  model file is touched.

``external_ai_allowed()`` stays false in this profile and every test asserts that the
router-level external AI entry points were never called.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Mirrors app.services.pose._KEYPOINT_VISIBILITY_THRESHOLD.
KEYPOINT_VISIBILITY_THRESHOLD = 0.35
FRAME_RATE = 5.0

# Single stable zoomed target: confidence 0.9, area 0.036 (<= 0.04 stable zoomed auto-lock area).
AUTO_LOCK_BBOX = {"x": 0.42, "y": 0.22, "width": 0.09, "height": 0.40}
# Same shape but below TARGET_LOCK_AUTO_THRESHOLD (0.72) -> manual confirmation required.
LOW_CONFIDENCE_BBOX = {"x": 0.42, "y": 0.25, "width": 0.10, "height": 0.38}
# Two same-scale people; area 0.128 keeps every "stable zoomed" auto-lock path disabled.
SAME_SCALE_PERSON_A = {"x": 0.08, "y": 0.10, "width": 0.16, "height": 0.80}
SAME_SCALE_PERSON_B = {"x": 0.76, "y": 0.10, "width": 0.16, "height": 0.80}

_AI_GUARD_NAMES = (
    "get_active_provider",
    "request_text_completion",
    "start_video_temporal_task",
    "generate_report",
    "analyze_frames_dual",
    "analyze_video_temporal",
    "run_semantic_keyframe_pipeline",
    "suggest_memory_updates",
)

# Mirrors app.services.pose._POSE_LOW_CONFIDENCE_THRESHOLD.
POSE_LOW_CONFIDENCE_THRESHOLD = 0.2

_RELOAD_MODULES = (
    "app.database",
    "app.models",
    "app.schemas",
    "app.routers.analysis",
    "app.services.analysis_corrections",
    "app.services.local_runtime",
    "app.services.pipeline_version",
    "app.services.pose",
    "app.services.report",
    "app.services.target_lock",
    "app.services.video",
)


def _pop_reload_modules() -> None:
    for module_name in _RELOAD_MODULES:
        sys.modules.pop(module_name, None)
        parent_name, attribute = module_name.rsplit(".", 1)
        parent = sys.modules.get(parent_name)
        if parent is not None and hasattr(parent, attribute):
            delattr(parent, attribute)


def _isolate_application_modules():
    """Restore both import caches so later suites see a consistent class graph."""
    original_modules = {name: sys.modules[name] for name in _RELOAD_MODULES if name in sys.modules}
    original_attributes = {}
    for name in _RELOAD_MODULES:
        parent_name, attribute = name.rsplit(".", 1)
        parent = sys.modules.get(parent_name)
        if parent is not None and hasattr(parent, attribute):
            original_attributes[name] = getattr(parent, attribute)

    def restore() -> None:
        _pop_reload_modules()
        sys.modules.update(original_modules)
        for name, module in original_attributes.items():
            parent_name, attribute = name.rsplit(".", 1)
            parent = sys.modules.get(parent_name)
            if parent is not None:
                setattr(parent, attribute, module)

    _pop_reload_modules()
    return restore


class _BackgroundTasksStub:
    """Records FastAPI BackgroundTasks calls instead of scheduling them."""

    def __init__(self) -> None:
        self.queued: list[tuple[object, tuple[object, ...], dict[str, object]]] = []

    def add_task(self, func: object, *args: object, **kwargs: object) -> None:
        self.queued.append((func, args, kwargs))


def _write_frames(directory: Path, count: int) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for index in range(1, count + 1):
        path = directory / f"frame_{index:04d}.jpg"
        path.write_bytes(b"\xff\xd8\xff\xe0synthetic-frame")
        paths.append(path)
    return paths


def _motion_payload(frame_paths: list[Path], *, frame_rate: float = FRAME_RATE) -> dict[str, object]:
    """Faithful subset of extract_motion_sampled_frames' motion payload schema."""
    selected: list[dict[str, object]] = []
    scores: list[float] = []
    for index, path in enumerate(frame_paths):
        score = round(0.5 + index * 0.01, 4)
        selected.append(
            {
                "frame_id": path.stem,
                "source_thumb_index": index,
                "timestamp": round(index / frame_rate, 3),
                "motion_score": score,
            }
        )
        scores.append(score)
    duration = round(len(frame_paths) / frame_rate, 3)
    return {
        "frame_rate": frame_rate,
        "thumb_size": None,
        "full_size": None,
        "window_start": 0.0,
        "window_end": duration,
        "window_start_sec": 0.0,
        "window_end_sec": duration,
        "effective_fps": frame_rate,
        "source_fps": 30.0,
        "is_slow_motion": False,
        "slow_motion_scale": 1.0,
        "total_thumb_frames": len(frame_paths),
        "sample_count": len(frame_paths),
        "selected": selected,
        "scores": scores,
    }


def _pose_payload(
    pose_service: object,
    frame_paths: list[Path],
    *,
    valid: bool = True,
    keypoint_x: float = 0.5,
    bbox: dict[str, float] | None = None,
    states: list[str] | None = None,
) -> dict[str, object]:
    """extract_pose-shaped payload for tracked / interpolated / lost frames.

    ``states`` mirrors what ``extract_pose`` returns after
    ``_apply_short_gap_interpolation``: interpolated display keypoints are marked
    ``interpolated=True`` with ``visibility=0.0`` (so they can never be counted as
    observed landmarks), while ``lost`` frames keep an empty keypoint list.
    ``valid=False`` is the all-lost shorthand used by the empty-pose case.
    """
    if states is None:
        states = ["tracked"] * len(frame_paths) if valid else ["lost"] * len(frame_paths)
    if len(states) != len(frame_paths):
        raise ValueError("pose fixture requires one state per frame")
    landmark_names = pose_service.LANDMARK_NAMES
    frames: list[dict[str, object]] = []
    diagnostics: list[dict[str, object]] = []
    for index, path in enumerate(frame_paths):
        state = states[index]
        if state == "tracked":
            keypoints = [
                {
                    "id": landmark_id,
                    "name": name,
                    "x": round(keypoint_x + landmark_id * 0.001, 4),
                    "y": round(0.30 + (landmark_id % 7) * 0.01, 4),
                    "z": 0.0,
                    "visibility": 0.95,
                }
                for landmark_id, name in enumerate(landmark_names)
            ]
            tracking_confidence = 0.9
            candidate_count = 1
            reason = None
            selected_source = "single_pose_crop"
        elif state == "interpolated":
            keypoints = [
                {
                    "id": landmark_id,
                    "name": name,
                    "x": round(keypoint_x + landmark_id * 0.001 + 0.004, 4),
                    "y": round(0.30 + (landmark_id % 7) * 0.01, 4),
                    "z": 0.0,
                    "visibility": 0.0,
                    "interpolated": True,
                }
                for landmark_id, name in enumerate(landmark_names)
            ]
            tracking_confidence = 0.05
            candidate_count = 0
            reason = "pose_interpolated"
            selected_source = "interpolated"
        else:
            keypoints = []
            tracking_confidence = 0.0
            candidate_count = 0
            reason = "pose_low_confidence"
            selected_source = None
        frames.append(
            {
                "frame": path.name,
                "keypoints": keypoints,
                "target_bbox": dict(bbox) if isinstance(bbox, dict) else None,
                "tracking_confidence": tracking_confidence,
                "tracking_state": state,
                "tracker_state": "tracked",
                "tracker_lost_frames": 0,
                "pose_candidates": [],
            }
        )
        diagnostics.append(
            {
                "frame": path.name,
                "frame_index": index,
                "tracker_state": "tracked",
                "selected_bbox": dict(bbox) if isinstance(bbox, dict) else None,
                "output_bbox": dict(bbox) if isinstance(bbox, dict) else None,
                "tracking_state": state,
                "tracking_confidence": tracking_confidence,
                "candidate_count": candidate_count,
                "scored_candidate_count": candidate_count,
                "rejected_candidate_count": 0,
                "selected_source": selected_source,
                "reason": reason,
            }
        )
    tracked_frames = sum(1 for state in states if state == "tracked")
    interpolated_frames = sum(1 for state in states if state == "interpolated")
    lost_frames = sum(1 for state in states if state == "lost")
    # Same rule as services/pose.py: interpolated (0.05) and lost (0.0) frames also
    # count as low confidence; this is not a measure of valid observations.
    low_confidence_frames = sum(
        1
        for frame in frames
        if frame["tracking_state"] == "low_confidence"
        or float(frame["tracking_confidence"]) <= POSE_LOW_CONFIDENCE_THRESHOLD
    )
    return {
        "connections": [list(pair) for pair in pose_service.POSE_CONNECTIONS],
        "frames": frames,
        "pose_diagnostics": {
            "mode": "single_pose_crop" if frames else "empty",
            "total_frames": len(frames),
            "tracked_frames": tracked_frames,
            "lost_frames": lost_frames,
            "interpolated_frames": interpolated_frames,
            "low_confidence_frames": low_confidence_frames,
            "multi_pose_frames": 0,
            "single_pose_crop_frames": tracked_frames,
            "candidate_count_histogram": {"1": tracked_frames, "0": interpolated_frames + lost_frames},
            "frames": diagnostics,
        },
    }


def _biomechanics_fixture() -> dict[str, object]:
    # No subscores / measurements: the local fallback report must not invent scores.
    return {"key_frames": {}, "key_frame_candidates": {}, "quality_flags": []}


def _attach_key_frame_candidates_stub(
    bio_data: dict[str, object],
    pose_data: object,
    motion_scores: object,
    analysis_profile: object,
    effective_fps: object,
) -> dict[str, object]:
    return {**bio_data, "key_frame_candidates": {}}


def _tracker_result(sampled_frames: list[Path], bbox: dict[str, float]) -> tuple[list[dict[str, float]], list[str], list[dict[str, object]]]:
    bboxes = [dict(bbox) for _ in sampled_frames]
    diagnostics = [{"frame_index": index, "state": "tracked"} for index in range(len(sampled_frames))]
    return bboxes, [], diagnostics


def _visible_keypoint_count(pose_data: dict[str, object] | None) -> int:
    if not isinstance(pose_data, dict):
        return 0
    total = 0
    for frame in pose_data.get("frames", []):
        if not isinstance(frame, dict):
            continue
        for keypoint in frame.get("keypoints", []):
            if not isinstance(keypoint, dict):
                continue
            try:
                visibility = float(keypoint.get("visibility", 0.0) or 0.0)
            except (TypeError, ValueError):
                visibility = 0.0
            if visibility >= KEYPOINT_VISIBILITY_THRESHOLD and keypoint.get("x") is not None and keypoint.get("y") is not None:
                total += 1
    return total


def _observed_keypoint_count(pose_data: dict[str, object] | None) -> int:
    """Valid landmarks from real observations only (tracked frames, not interpolated)."""
    if not isinstance(pose_data, dict):
        return 0
    total = 0
    for frame in pose_data.get("frames", []):
        if not isinstance(frame, dict) or frame.get("tracking_state") != "tracked":
            continue
        for keypoint in frame.get("keypoints", []):
            if not isinstance(keypoint, dict) or keypoint.get("interpolated") is True:
                continue
            try:
                visibility = float(keypoint.get("visibility", 0.0) or 0.0)
            except (TypeError, ValueError):
                visibility = 0.0
            if visibility >= KEYPOINT_VISIBILITY_THRESHOLD:
                total += 1
    return total


def _interpolated_keypoint_count(pose_data: dict[str, object] | None) -> int:
    """Count display points by frame state, which survives the PoseResponse schema."""
    if not isinstance(pose_data, dict):
        return 0
    return sum(
        len(frame.get("keypoints", []))
        for frame in pose_data.get("frames", [])
        if isinstance(frame, dict) and frame.get("tracking_state") == "interpolated"
    )


def _pose_response_payload(pose_response: object) -> dict[str, object]:
    """Read-back view of PoseResponse in the same shape as persisted pose_data."""
    return {
        "frames": [frame.model_dump() for frame in pose_response.frames],
        "pose_diagnostics": pose_response.pose_diagnostics,
    }


def _timestamp_by_frame(motion_scores: dict[str, object] | None) -> dict[str, float]:
    """frame stem -> source timestamp, from the real frame_motion_scores.selected schema."""
    output: dict[str, float] = {}
    selected = motion_scores.get("selected") if isinstance(motion_scores, dict) else None
    if not isinstance(selected, list):
        return output
    for item in selected:
        if not isinstance(item, dict):
            continue
        frame_id = item.get("frame_id")
        timestamp = item.get("timestamp")
        if isinstance(frame_id, str) and isinstance(timestamp, (int, float)):
            output[frame_id.removesuffix(".jpg")] = float(timestamp)
    return output


def _bbox_area(bbox: dict[str, object]) -> float:
    return float(bbox.get("width", 0.0) or 0.0) * float(bbox.get("height", 0.0) or 0.0)


class LocalTrialPersonFlowTests(unittest.IsolatedAsyncioTestCase):
    """Synthetic/injected regressions for the legacy single-person control flow."""

    def setUp(self) -> None:
        self._tmpdir_ctx = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self._tmpdir_ctx.name)
        self.addCleanup(self._tmpdir_ctx.cleanup)
        # These directories must exist before app.database is imported: its
        # _resolve_runtime_path() only honours an absolute env path that already exists,
        # otherwise an inherited /data/uploads would win and the retry endpoint would
        # look for the upload under the NAS path.
        for name in ("uploads", "archive", "backups", "processing"):
            (self.tmpdir / name).mkdir(parents=True, exist_ok=True)
        self.uploads_dir = self.tmpdir / "uploads"
        self._env_patcher = patch.dict(
            os.environ,
            {
                "DATA_DIR": str(self.tmpdir),
                "UPLOADS_DIR": str(self.uploads_dir),
                "ARCHIVE_DIR": str(self.tmpdir / "archive"),
                "BACKUPS_DIR": str(self.tmpdir / "backups"),
                "DATABASE_URL": f"sqlite+aiosqlite:///{self.tmpdir / 'trial.db'}",
                "SKATING_TRIAL_PROFILE": "legacy-analysis-preview",
                "VIDEO_PROCESSING_ROOT": str(self.tmpdir / "processing"),
            },
        )
        self._env_patcher.start()
        self.addCleanup(self._env_patcher.stop)
        # Build a temporary module graph for this database, then restore both
        # sys.modules and package attributes. Clearing only sys.modules leaves
        # ``from app.routers import analysis`` bound to a stale model class.
        self.addCleanup(_isolate_application_modules())

        import app.database as database
        import app.models as models
        import app.routers.analysis as router
        import app.schemas as schemas
        import app.services.pose as pose_service

        self.database = database
        self.models = models
        self.router = router
        self.schemas = schemas
        self.pose_service = pose_service

        # Media manifest/renditions would touch ffprobe/ffmpeg; neither is needed for the
        # control flow under test.
        self._patch_router("read_or_create_manifest", side_effect=RuntimeError("synthetic media manifest disabled"))
        self._patch_router("generate_media_renditions", new_callable=AsyncMock)

        # Synthetic byte fixtures have no video metadata; keep real decoding out.
        for target in ("app.services.video.detect_video_duration",
                       "app.services.semantic_keyframe_pipeline.detect_video_duration"):
            metadata = patch(target, return_value=None)
            metadata.start()
            self.addCleanup(metadata.stop)

        # The retry/confirm endpoints resolve uploads from the router's imported
        # UPLOADS_DIR; assert it is the temporary directory, not an inherited one.
        self.uploads_dir = Path(database.UPLOADS_DIR)
        self.assertEqual(self.uploads_dir, Path(router.UPLOADS_DIR))
        self.assertTrue(self.uploads_dir.is_relative_to(self.tmpdir))

    async def asyncSetUp(self) -> None:
        self.database.ensure_storage_dirs()
        await self.database.init_db()

    async def asyncTearDown(self) -> None:
        await self.database.engine.dispose()

    # ------------------------------------------------------------------ helpers

    def _patch_router(self, name: str, **kwargs: object) -> object:
        patcher = patch.object(self.router, name, **kwargs)
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def _spy_router_call(self, name: str) -> object:
        patcher = patch.object(self.router, name, wraps=getattr(self.router, name))
        spy = patcher.start()
        self.addCleanup(patcher.stop)
        return spy

    def _install_ai_guards(self) -> dict[str, object]:
        return {name: self._patch_router(name, new_callable=AsyncMock) for name in _AI_GUARD_NAMES}

    def _assert_no_external_ai(self, guards: dict[str, object]) -> None:
        for name, mock in guards.items():
            with self.subTest(external_ai_entry_point=name):
                mock.assert_not_called()

    def _sampling_metadata(self, frame_count: int) -> object:
        duration = round(frame_count / FRAME_RATE, 3)
        return self.router.VideoSamplingMetadata(
            action_window_start=0.0,
            action_window_end=duration,
            window_start_sec=0.0,
            window_end_sec=duration,
            effective_fps=FRAME_RATE,
            source_fps=30.0,
            is_slow_motion=False,
        )

    async def _create_analysis(self, *, frame_count: int = 9, with_cached_frames: bool = False, **fields: object) -> SimpleNamespace:
        analysis_id = str(uuid4())
        upload_dir = self.uploads_dir / analysis_id
        frames_dir = upload_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        (upload_dir / "source.mp4").write_bytes(b"fake-mp4-fixture")
        fixture_frames = _write_frames(self.tmpdir / "fixture_frames" / analysis_id, frame_count)
        if with_cached_frames:
            for path in fixture_frames:
                (frames_dir / path.name).write_bytes(path.read_bytes())
        async with self.database.AsyncSessionLocal() as session:
            session.add(
                self.models.Analysis(
                    id=analysis_id,
                    action_type="跳跃",
                    video_path=str(upload_dir / "source.mp4"),
                    status=fields.pop("status", "pending"),
                    **fields,
                )
            )
            await session.commit()
        return SimpleNamespace(
            id=analysis_id,
            upload_dir=upload_dir,
            frames_dir=frames_dir,
            fixture_frames=fixture_frames,
        )

    async def _update_analysis(self, analysis_id: str, **fields: object) -> None:
        async with self.database.AsyncSessionLocal() as session:
            row = await session.get(self.models.Analysis, analysis_id)
            self.assertIsNotNone(row)
            for key, value in fields.items():
                setattr(row, key, value)
            await session.commit()

    async def _load_analysis(self, analysis_id: str) -> object:
        async with self.database.AsyncSessionLocal() as session:
            row = await session.get(self.models.Analysis, analysis_id)
        self.assertIsNotNone(row)
        return row

    async def _analysis_count(self, analysis_id: str) -> int:
        async with self.database.AsyncSessionLocal() as session:
            result = await session.execute(
                select(func.count()).select_from(self.models.Analysis).where(self.models.Analysis.id == analysis_id)
            )
            return int(result.scalar_one())

    def _install_local_pipeline(
        self,
        fixture: SimpleNamespace,
        *,
        detector: object,
        pose_valid: bool = True,
        keypoint_x: float = 0.5,
        tracker_error: BaseException | None = None,
        pose_states: list[str] | None = None,
    ) -> SimpleNamespace:
        frame_count = len(fixture.fixture_frames)
        precheck = self._patch_router("precheck_video", new_callable=AsyncMock)

        async def decoder_stub(video_path, frames_dir, action_type, analysis_profile=None, **kwargs):
            """Inject decoded frames into the real frames_dir, mirroring the production decoder."""
            target_dir = Path(frames_dir)
            for existing in target_dir.glob("frame_*.jpg"):
                existing.unlink(missing_ok=True)
            written = _write_frames(target_dir, frame_count)
            return written, _motion_payload(written), self._sampling_metadata(frame_count)

        decode = self._patch_router("extract_motion_sampled_frames", new=AsyncMock(side_effect=decoder_stub))
        self._patch_router("build_video_input_window", return_value=None)
        # This suite injects legacy person-flow inputs. Continuous-pool production
        # binding/decoding is exercised separately in test_continuous_tracking.
        async def continuous_stub(video_path, frames_dir, pool_dir, frames, motion, metadata):
            return frames, motion
        self._patch_router("prepare_continuous_pose_inputs", new=AsyncMock(side_effect=continuous_stub))
        self._patch_router(
            "detect_person_candidates",
            side_effect=lambda frame_path, include_zoomed_small_targets=False: [dict(item) for item in detector(frame_path)],
        )
        if tracker_error is not None:
            tracker = self._patch_router("track_person_bbox_detailed", side_effect=tracker_error)
        else:
            tracker = self._patch_router(
                "track_person_bbox_detailed",
                side_effect=lambda sampled_frames, selected_bbox, **kwargs: _tracker_result(sampled_frames, selected_bbox),
            )
        pose = self._patch_router(
            "extract_pose",
            side_effect=lambda frames_dir, target_lock=None, bbox_per_frame=None, effective_fps=None, *, frame_times=None, slow_motion_scale=1.: _pose_payload(
                self.pose_service,
                sorted(Path(frames_dir).glob("frame_*.jpg")),
                valid=pose_valid,
                keypoint_x=keypoint_x,
                bbox=target_lock.get("selected_bbox") if isinstance(target_lock, dict) else None,
                states=pose_states,
            ),
        )
        self._patch_router("analyze_biomechanics", return_value=_biomechanics_fixture())
        self._patch_router("attach_key_frame_candidates", side_effect=_attach_key_frame_candidates_stub)
        self._patch_router("infer_analysis_profile", return_value=("jump", {"quality_flags": []}))
        self._patch_router("infer_jump_subtype_evidence", return_value={})
        self._patch_router("is_mixed_action_input", return_value=False)
        guards = self._install_ai_guards()
        return SimpleNamespace(precheck=precheck, decode=decode, tracker=tracker, pose=pose, guards=guards)

    async def _seed_completed_analysis(
        self,
        fixture: SimpleNamespace,
        *,
        keypoint_x: float = 0.111,
    ) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
        old_pose = _pose_payload(
            self.pose_service,
            fixture.fixture_frames,
            valid=True,
            keypoint_x=keypoint_x,
            bbox=dict(AUTO_LOCK_BBOX),
        )
        old_report: dict[str, object] = {
            "source": "legacy/local",
            "summary": "OLD_RESULT_MARKER",
            "subscores": {},
            "local_execution": {"decode": True, "detection": True, "tracking": True, "pose": True, "external_ai": False},
            "technical_conclusion": None,
        }
        old_lock: dict[str, object] = {
            "status": "auto_locked",
            "manual_override": False,
            "selected_candidate_id": "candidate_auto_stable",
            "selected_bbox": dict(AUTO_LOCK_BBOX),
            "lock_confidence": 0.9,
            "preview_frame": fixture.fixture_frames[len(fixture.fixture_frames) // 2].name,
            "preview_frame_index": len(fixture.fixture_frames) // 2,
            "candidates": [],
            "quality_flags": [],
            "bbox_per_frame": [dict(AUTO_LOCK_BBOX) for _ in fixture.fixture_frames],
            "person_tracker_diagnostics": [
                {"frame_index": index, "state": "tracked"} for index in range(len(fixture.fixture_frames))
            ],
            "tracker_type": "yolo_bytetrack",
        }
        await self._update_analysis(
            fixture.id,
            status="completed",
            pose_data=old_pose,
            report=old_report,
            target_lock=old_lock,
            target_lock_status="auto_locked",
            frame_motion_scores=_motion_payload(fixture.fixture_frames),
            bio_data={"key_frames": {}, "key_frame_candidates": {}, "quality_flags": []},
            action_window_start=0.0,
            action_window_end=round(len(fixture.fixture_frames) / FRAME_RATE, 3),
            source_fps=30.0,
            is_slow_motion=False,
            force_score=None,
            retry_from_stage=None,
            pipeline_version="legacy/local-r1",
        )
        return old_pose, old_report, old_lock

    # ------------------------------------------------------------------ tests

    async def test_high_confidence_single_target_auto_locks_runs_pose_and_reopens(self) -> None:
        """Category 1: real auto-lock -> tracker -> injected pose -> real local report -> GET."""
        fixture = await self._create_analysis(frame_count=9)
        pipeline = self._install_local_pipeline(
            fixture,
            detector=lambda _path: [
                {
                    "id": "person_1",
                    "bbox": dict(AUTO_LOCK_BBOX),
                    "confidence": 0.9,
                    "source": "yolo_zoomed_content",
                }
            ],
        )
        preview_spy = self._spy_router_call("build_target_preview")
        lock_spy = self._spy_router_call("build_target_lock_payload")

        await self.router.process_analysis(fixture.id)

        saved = await self._load_analysis(fixture.id)
        self.assertEqual(saved.status, "completed")
        self.assertEqual(saved.target_lock_status, "auto_locked")
        target_lock = saved.target_lock
        self.assertEqual(target_lock["status"], "auto_locked")
        self.assertEqual(target_lock["selected_candidate_id"], "candidate_auto_stable")
        self.assertEqual(target_lock["selected_bbox"], AUTO_LOCK_BBOX)
        self.assertGreaterEqual(float(target_lock["lock_confidence"]), 0.72)
        self.assertFalse(target_lock["manual_override"])
        self.assertEqual(len(target_lock["bbox_per_frame"]), 9)
        self.assertEqual(len(target_lock["person_tracker_diagnostics"]), 9)
        self.assertTrue(preview_spy.called)
        self.assertTrue(lock_spy.called)
        self.assertTrue(pipeline.pose.called)
        self.assertEqual(pipeline.pose.call_count, 1)

        report = saved.report
        self.assertEqual(report["source"], "legacy/local")
        self.assertEqual(report["subscores"], {})
        self.assertIsNone(report["technical_conclusion"])
        self.assertEqual(
            report["local_execution"],
            {"decode": True, "detection": True, "tracking": True, "pose": True, "external_ai": False},
        )
        self.assertIsNone(saved.force_score)
        self.assertIsNone(saved.error_code)
        self.assertEqual(saved.pipeline_version, "legacy/local-r1")

        pose_data = saved.pose_data
        self.assertEqual(
            [frame["frame"] for frame in pose_data["frames"]],
            [path.name for path in fixture.fixture_frames],
        )
        self.assertEqual(_visible_keypoint_count(pose_data), 9 * len(self.pose_service.LANDMARK_NAMES))
        self.assertEqual(pose_data["pose_diagnostics"]["interpolated_frames"], 0)
        self.assertEqual(pose_data["pose_diagnostics"]["tracked_frames"], 9)

        timestamps = _timestamp_by_frame(saved.frame_motion_scores)
        self.assertEqual(len(timestamps), 9)
        ordered = [timestamps[frame["frame"].removesuffix(".jpg")] for frame in pose_data["frames"]]
        self.assertEqual(ordered, sorted(ordered))
        for index, frame in enumerate(pose_data["frames"]):
            self.assertEqual(
                timestamps[frame["frame"].removesuffix(".jpg")],
                saved.frame_motion_scores["selected"][index]["timestamp"],
            )

        async with self.database.AsyncSessionLocal() as session:
            detail = await self.router.get_analysis(fixture.id, session=session)
            pose_response = await self.router.get_analysis_pose(fixture.id, session=session)
        self.assertEqual(detail.status, "completed")
        self.assertIsNone(detail.force_score)
        self.assertEqual(detail.report["subscores"], {})
        self.assertEqual(detail.report["local_execution"]["external_ai"], False)
        self.assertEqual(len(detail.pose_data["frames"]), 9)
        self.assertEqual(detail.target_lock["selected_bbox"], AUTO_LOCK_BBOX)
        self.assertEqual(len(pose_response.frames), 9)
        self.assertEqual(set(pose_response.frame_urls), {path.name for path in fixture.fixture_frames})
        self.assertTrue(all(frame.keypoints for frame in pose_response.frames))
        self._assert_no_external_ai(pipeline.guards)

    async def test_low_confidence_target_waits_then_manual_confirm_resumes_same_id(self) -> None:
        """Category 2: low confidence -> awaiting_target_selection -> real confirm_target_lock."""
        fixture = await self._create_analysis(frame_count=9)
        pipeline = self._install_local_pipeline(
            fixture,
            detector=lambda _path: [
                {
                    "id": "person_low",
                    "bbox": dict(LOW_CONFIDENCE_BBOX),
                    "confidence": 0.40,
                    "source": "yolo_zoomed_content",
                }
            ],
        )

        await self.router.process_analysis(fixture.id)

        saved = await self._load_analysis(fixture.id)
        self.assertEqual(saved.status, "awaiting_target_selection")
        self.assertEqual(saved.target_lock_status, "awaiting_manual")
        self.assertEqual(saved.target_lock["status"], "awaiting_manual")
        self.assertIsNone(saved.target_lock["selected_bbox"])
        self.assertFalse(saved.target_lock["manual_override"])
        self.assertIn("target_lock_manual_review_low_confidence", saved.target_lock["quality_flags"])
        self.assertIsNone(saved.pose_data)
        self.assertIsNone(saved.report)
        self.assertIsNone(saved.force_score)
        pipeline.pose.assert_not_called()

        async with self.database.AsyncSessionLocal() as session:
            preview = await self.router.get_target_preview(fixture.id, session=session)
        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        self.assertIsNotNone(preview.preview_frame)

        manual_candidate_id = saved.target_lock["selected_candidate_id"]
        self.assertTrue(manual_candidate_id)
        tasks = _BackgroundTasksStub()
        with patch("app.services.local_runtime.require_local_runtime"):
            async with self.database.AsyncSessionLocal() as session:
                detail = await self.router.confirm_target_lock(
                    fixture.id,
                    self.schemas.TargetLockRequest(candidate_id=manual_candidate_id),
                    tasks,
                    session=session,
                )
        self.assertEqual(detail.status, "pending")
        self.assertEqual(len(tasks.queued), 1)
        queued_func, queued_args, queued_kwargs = tasks.queued[0]
        self.assertIs(queued_func, self.router.process_analysis_with_media_renditions)
        self.assertEqual(queued_args, (fixture.id,))
        self.assertEqual(queued_kwargs, {})
        self.assertEqual(await self._analysis_count(fixture.id), 1)

        await queued_func(*queued_args, **queued_kwargs)

        saved = await self._load_analysis(fixture.id)
        self.assertEqual(saved.status, "completed")
        self.assertEqual(saved.target_lock["status"], "locked")
        self.assertTrue(saved.target_lock["manual_override"])
        self.assertEqual(saved.target_lock["selected_candidate_id"], manual_candidate_id)
        self.assertEqual(saved.target_lock["selected_bbox"], LOW_CONFIDENCE_BBOX)
        self.assertEqual(saved.report["local_execution"]["pose"], True)
        self.assertTrue(pipeline.pose.called)
        self.assertEqual(pipeline.pose.call_args.args[1]["selected_bbox"], LOW_CONFIDENCE_BBOX)
        self.assertEqual(_visible_keypoint_count(saved.pose_data), 9 * len(self.pose_service.LANDMARK_NAMES))
        self.assertEqual(await self._analysis_count(fixture.id), 1)
        self._assert_no_external_ai(pipeline.guards)

    async def test_same_scale_multiperson_waits_without_auto_selection_or_pose(self) -> None:
        """Category 3: same-scale multi-person -> real decision waits for a human, no pose."""
        fixture = await self._create_analysis(frame_count=9)

        def detector(_path: Path) -> list[dict[str, object]]:
            return [
                {"id": "person_a", "bbox": dict(SAME_SCALE_PERSON_A), "confidence": 0.9, "source": "yolo_zoomed_content"},
                {"id": "person_b", "bbox": dict(SAME_SCALE_PERSON_B), "confidence": 0.9, "source": "yolo_zoomed_content"},
            ]

        pipeline = self._install_local_pipeline(fixture, detector=detector)

        await self.router.process_analysis(fixture.id)

        saved = await self._load_analysis(fixture.id)
        self.assertEqual(saved.status, "awaiting_target_selection")
        self.assertEqual(saved.target_lock_status, "awaiting_manual")
        self.assertEqual(saved.target_lock["status"], "awaiting_manual")
        self.assertIsNone(saved.target_lock["selected_bbox"])
        self.assertFalse(saved.target_lock["manual_override"])
        self.assertIn("target_lock_zoomed_multiperson_manual_review", saved.target_lock["quality_flags"])
        yolo_candidates = [item for item in saved.target_lock["candidates"] if item.get("source") == "yolo_zoomed_content"]
        self.assertGreaterEqual(len({item["id"] for item in yolo_candidates}), 2)
        self.assertEqual(len({round(_bbox_area(item["bbox"]), 4) for item in yolo_candidates}), 1)
        self.assertIsNone(saved.pose_data)
        self.assertIsNone(saved.report)
        pipeline.pose.assert_not_called()
        self._assert_no_external_ai(pipeline.guards)

    async def test_detected_person_with_empty_pose_keeps_execution_and_validity_separate(self) -> None:
        """Category 4: person detected, pose executed, but zero valid observations and no scores."""
        fixture = await self._create_analysis(frame_count=9)
        pipeline = self._install_local_pipeline(
            fixture,
            detector=lambda _path: [
                {
                    "id": "person_1",
                    "bbox": dict(AUTO_LOCK_BBOX),
                    "confidence": 0.9,
                    "source": "yolo_zoomed_content",
                }
            ],
            pose_valid=False,
        )

        await self.router.process_analysis(fixture.id)

        saved = await self._load_analysis(fixture.id)
        self.assertEqual(saved.status, "completed")
        self.assertEqual(saved.report["local_execution"]["pose"], True)  # pose stage executed
        self.assertEqual(saved.report["local_execution"]["tracking"], True)  # tracker executed
        self.assertEqual(saved.report["data_quality"], "insufficient")
        self.assertEqual(saved.report["subscores"], {})
        self.assertIsNone(saved.report["technical_conclusion"])
        self.assertIsNone(saved.force_score)
        self.assertIn("证据不足", saved.report["summary"])

        pose_data = saved.pose_data
        self.assertEqual(_visible_keypoint_count(pose_data), 0)  # executed != valid observation
        self.assertTrue(all(frame["keypoints"] == [] for frame in pose_data["frames"]))
        self.assertEqual([frame["tracking_state"] for frame in pose_data["frames"]], ["lost"] * 9)
        self.assertEqual(pose_data["pose_diagnostics"]["tracked_frames"], 0)
        self.assertEqual(pose_data["pose_diagnostics"]["lost_frames"], 9)
        self.assertEqual(pose_data["pose_diagnostics"]["interpolated_frames"], 0)
        # Tracker bboxes are persisted separately from pose validity.
        self.assertEqual(len(saved.target_lock["bbox_per_frame"]), 9)
        self.assertFalse(saved.bio_data.get("bio_subscores"))

        async with self.database.AsyncSessionLocal() as session:
            pose_response = await self.router.get_analysis_pose(fixture.id, session=session)
        self.assertEqual(len(pose_response.frames), 9)
        self.assertTrue(all(frame.keypoints == [] for frame in pose_response.frames))
        self._assert_no_external_ai(pipeline.guards)

    async def test_tracker_unavailable_fails_retryably_without_pose_or_provider(self) -> None:
        """Category 5: PersonTrackerUnavailable -> failed, retryable, never reported as tracking ok."""
        fixture = await self._create_analysis(frame_count=9)
        pipeline = self._install_local_pipeline(
            fixture,
            detector=lambda _path: [
                {
                    "id": "person_1",
                    "bbox": dict(AUTO_LOCK_BBOX),
                    "confidence": 0.9,
                    "source": "yolo_zoomed_content",
                }
            ],
            tracker_error=self.router.PersonTrackerUnavailable("synthetic missing tracker"),
        )

        await self.router.process_analysis(fixture.id)

        saved = await self._load_analysis(fixture.id)
        self.assertEqual(saved.status, "failed")
        self.assertEqual(saved.error_code, self.router.AnalysisErrorCode.UNKNOWN_ERROR.value)
        self.assertEqual(saved.error_detail, "synthetic missing tracker")
        self.assertIsNone(saved.report)  # no successful tracking report
        self.assertIsNone(saved.force_score)
        self.assertEqual(saved.target_lock_status, "auto_locked")  # target decision itself succeeded
        self.assertEqual(pipeline.tracker.call_count, 1)
        pipeline.pose.assert_not_called()
        self._assert_no_external_ai(pipeline.guards)

        tasks = _BackgroundTasksStub()
        with patch("app.services.local_runtime.require_local_runtime"):
            async with self.database.AsyncSessionLocal() as session:
                response = await self.router.retry_analysis(fixture.id, tasks, retry_from=None, session=session)
        self.assertIn("pose", response.message)
        self.assertEqual(len(tasks.queued), 1)
        queued_func, queued_args, queued_kwargs = tasks.queued[0]
        self.assertIs(queued_func, self.router.process_analysis_with_media_renditions)
        self.assertEqual(queued_args, (fixture.id, "pose"))
        self.assertEqual(await self._analysis_count(fixture.id), 1)

        await queued_func(*queued_args, **queued_kwargs)

        saved = await self._load_analysis(fixture.id)
        self.assertEqual(saved.status, "failed")
        self.assertIsNone(saved.report)
        self.assertEqual(saved.error_code, self.router.AnalysisErrorCode.UNKNOWN_ERROR.value)
        self.assertEqual(await self._analysis_count(fixture.id), 1)
        pipeline.pose.assert_not_called()
        self._assert_no_external_ai(pipeline.guards)

    async def test_same_id_retry_replaces_old_pose_and_report_without_duplicate_row(self) -> None:
        """Category 6a: real retry endpoint + real background run, same id, fresh results."""
        fixture = await self._create_analysis(frame_count=9, with_cached_frames=True)
        old_pose, _old_report, _old_lock = await self._seed_completed_analysis(fixture)
        pipeline = self._install_local_pipeline(
            fixture,
            detector=lambda _path: [
                {
                    "id": "person_1",
                    "bbox": dict(AUTO_LOCK_BBOX),
                    "confidence": 0.9,
                    "source": "yolo_zoomed_content",
                }
            ],
            keypoint_x=0.8,
        )
        tasks = _BackgroundTasksStub()
        with patch("app.services.local_runtime.require_local_runtime"):
            async with self.database.AsyncSessionLocal() as session:
                response = await self.router.retry_analysis(fixture.id, tasks, retry_from=None, session=session)
        self.assertEqual(response.message, "已重新提交分析。")
        self.assertEqual(len(tasks.queued), 1)
        queued_func, queued_args, queued_kwargs = tasks.queued[0]
        self.assertIs(queued_func, self.router.process_analysis_with_media_renditions)
        self.assertEqual(queued_args, (fixture.id, None))
        self.assertEqual(queued_kwargs, {"force_keyframe_refresh": False})
        self.assertEqual(await self._analysis_count(fixture.id), 1)

        pending = await self._load_analysis(fixture.id)
        self.assertEqual(pending.status, "pending")  # old result is not a completed new result
        self.assertEqual(pending.report["summary"], "OLD_RESULT_MARKER")  # retained until overwritten
        self.assertEqual(pending.pose_data, old_pose)

        await queued_func(*queued_args, **queued_kwargs)

        saved = await self._load_analysis(fixture.id)
        self.assertEqual(saved.status, "completed")
        self.assertEqual(await self._analysis_count(fixture.id), 1)
        self.assertEqual(saved.pose_data["frames"][0]["keypoints"][0]["x"], 0.8)
        self.assertNotEqual(saved.pose_data, old_pose)
        self.assertNotIn("OLD_RESULT_MARKER", json.dumps(saved.report, ensure_ascii=False))
        self.assertEqual(
            saved.report["summary"],
            "本地处理结果已保存；证据不足以给出技术评分或动作结论。 "
            "当前动作分类仅作为分析路由，不代表已确认具体动作或周数。",
        )
        self.assertEqual(saved.report["local_execution"]["pose"], True)
        self.assertEqual(saved.report["subscores"], {})
        self.assertIsNone(saved.force_score)
        self.assertEqual(saved.target_lock["selected_bbox"], AUTO_LOCK_BBOX)
        self.assertTrue(pipeline.pose.called)
        self._assert_no_external_ai(pipeline.guards)

    async def test_read_after_success_keeps_saved_pose_without_retry(self) -> None:
        """Category 6b: no retry -> reads do not clear the saved pose/report."""
        fixture = await self._create_analysis(frame_count=9, with_cached_frames=True)
        old_pose, old_report, _old_lock = await self._seed_completed_analysis(fixture)

        async with self.database.AsyncSessionLocal() as session:
            detail = await self.router.get_analysis(fixture.id, session=session)
            pose_response = await self.router.get_analysis_pose(fixture.id, session=session)

        self.assertEqual(detail.status, "completed")
        self.assertIsNone(detail.force_score)
        self.assertEqual(detail.report["summary"], old_report["summary"])
        self.assertEqual(pose_response.frames[0].keypoints[0].x, 0.111)
        saved = await self._load_analysis(fixture.id)
        self.assertEqual(saved.pose_data, old_pose)
        self.assertEqual(saved.report, old_report)
        self.assertEqual(await self._analysis_count(fixture.id), 1)

    async def test_failed_retry_after_success_reports_failure_without_new_report(self) -> None:
        """Category 6c: a failed same-id retry must be an explicit failure, not a new result."""
        fixture = await self._create_analysis(frame_count=9, with_cached_frames=True)
        old_pose, old_report, _old_lock = await self._seed_completed_analysis(fixture)
        pipeline = self._install_local_pipeline(
            fixture,
            detector=lambda _path: [],
            tracker_error=self.router.PersonTrackerUnavailable("synthetic missing tracker"),
        )
        tasks = _BackgroundTasksStub()
        with patch("app.services.local_runtime.require_local_runtime"):
            async with self.database.AsyncSessionLocal() as session:
                await self.router.retry_analysis(fixture.id, tasks, retry_from=None, session=session)
        self.assertEqual(len(tasks.queued), 1)
        queued_func, queued_args, queued_kwargs = tasks.queued[0]
        await queued_func(*queued_args, **queued_kwargs)

        saved = await self._load_analysis(fixture.id)
        self.assertEqual(saved.status, "failed")
        self.assertEqual(saved.error_code, self.router.AnalysisErrorCode.UNKNOWN_ERROR.value)
        self.assertEqual(saved.retry_from_stage, "pose")
        self.assertEqual(saved.pose_data, old_pose)
        self.assertEqual(saved.report, old_report)  # no new report fabricated
        self.assertEqual(await self._analysis_count(fixture.id), 1)
        pipeline.pose.assert_not_called()
        self._assert_no_external_ai(pipeline.guards)

    async def test_retry_with_pose_hint_still_restarts_from_extract_frames_locally(self) -> None:
        """Local profile always restarts at extract_frames, even when retry_from=pose."""
        fixture = await self._create_analysis(frame_count=9)
        await self._update_analysis(
            fixture.id,
            status="failed",
            error_code=self.router.AnalysisErrorCode.UNKNOWN_ERROR.value,
            error_message="synthetic failure",
            retry_from_stage="pose",
            pose_data={"connections": [], "frames": []},
            frame_motion_scores=_motion_payload(fixture.fixture_frames),
            target_lock=None,
            target_lock_status="pending",
            report=None,
        )
        pipeline = self._install_local_pipeline(
            fixture,
            detector=lambda _path: [
                {
                    "id": "person_1",
                    "bbox": dict(AUTO_LOCK_BBOX),
                    "confidence": 0.9,
                    "source": "yolo_zoomed_content",
                }
            ],
        )
        tasks = _BackgroundTasksStub()
        with patch("app.services.local_runtime.require_local_runtime"):
            async with self.database.AsyncSessionLocal() as session:
                response = await self.router.retry_analysis(fixture.id, tasks, retry_from="pose", session=session)
        self.assertIn("pose", response.message)
        self.assertEqual(len(tasks.queued), 1)
        queued_func, queued_args, queued_kwargs = tasks.queued[0]
        self.assertEqual(queued_args, (fixture.id, "pose"))

        await queued_func(*queued_args, **queued_kwargs)

        pipeline.precheck.assert_called_once()
        pipeline.decode.assert_called_once()
        saved = await self._load_analysis(fixture.id)
        self.assertEqual(saved.status, "completed")
        self.assertEqual(saved.report["local_execution"]["pose"], True)
        self.assertEqual(await self._analysis_count(fixture.id), 1)
        self._assert_no_external_ai(pipeline.guards)

    async def test_successful_retry_with_target_reset_and_no_person_clears_old_result(self) -> None:
        """Real full retry with explicit target reset must not carry a prior positive result."""
        fixture = await self._create_analysis(frame_count=9, with_cached_frames=True)
        old_pose, old_report, old_lock = await self._seed_completed_analysis(fixture)
        self.assertGreater(_observed_keypoint_count(old_pose), 0)
        pipeline = self._install_local_pipeline(fixture, detector=lambda _path: [])
        tasks = _BackgroundTasksStub()
        with patch("app.services.local_runtime.require_local_runtime"):
            async with self.database.AsyncSessionLocal() as session:
                await self.router.retry_analysis(
                    fixture.id, tasks, retry_from=None, reset_target_lock=True, session=session,
                )
        self.assertEqual(len(tasks.queued), 1)
        func, args, kwargs = tasks.queued[0]
        await func(*args, **kwargs)
        saved = await self._load_analysis(fixture.id)
        self.assertEqual(saved.id, fixture.id)
        self.assertEqual(saved.status, "completed")
        self.assertEqual(await self._analysis_count(fixture.id), 1)
        self.assertIsNone(saved.pose_data)
        self.assertIsNone(saved.bio_data)
        self.assertIsNone(saved.target_lock)
        self.assertIsNone(saved.target_lock_status)
        self.assertIsNone(saved.force_score)
        self.assertEqual(saved.report["subscores"], {})
        self.assertNotIn("OLD_RESULT_MARKER", json.dumps(saved.report))
        self.assertNotEqual(saved.report, old_report)
        self.assertEqual(saved.report["local_execution"], {
            "decode": True, "detection": True, "tracking": False, "pose": False, "external_ai": False,
        })
        self.assertEqual(_observed_keypoint_count(saved.pose_data), 0)
        pipeline.tracker.assert_not_called()
        pipeline.pose.assert_not_called()
        async with self.database.AsyncSessionLocal() as session:
            reopened = await self.router.get_analysis_pose(fixture.id, session=session)
        self.assertEqual(reopened.frames, [])
        self.assertEqual(reopened.frame_timestamps, {})
        self._assert_no_external_ai(pipeline.guards)

    async def test_mixed_pose_observations_remain_distinct_after_save_and_get(self) -> None:
        """Injected observations, interpolation and loss stay distinguishable after persistence."""
        fixture = await self._create_analysis(frame_count=9)
        states = ["tracked", "tracked", "interpolated", "tracked", "lost", "tracked", "tracked", "tracked", "tracked"]
        pipeline = self._install_local_pipeline(
            fixture,
            detector=lambda _path: [{"id": "person_1", "bbox": dict(AUTO_LOCK_BBOX),
                                     "confidence": 0.9, "source": "yolo_zoomed_content"}],
            pose_states=states,
        )
        await self.router.process_analysis(fixture.id)
        saved = await self._load_analysis(fixture.id)
        self.assertEqual(saved.status, "completed")
        self.assertTrue(saved.report["local_execution"]["pose"])
        async with self.database.AsyncSessionLocal() as session:
            reopened = await self.router.get_analysis_pose(fixture.id, session=session)
        landmark_count = len(self.pose_service.LANDMARK_NAMES)
        for payload in [saved.pose_data, _pose_response_payload(reopened)]:
            self.assertEqual([f["tracking_state"] for f in payload["frames"]], states)
            self.assertEqual(_observed_keypoint_count(payload), 7 * landmark_count)
            self.assertEqual(_interpolated_keypoint_count(payload), landmark_count)
            self.assertEqual(payload["frames"][4]["keypoints"], [])
            self.assertTrue(all(k["visibility"] == 0 for k in payload["frames"][2]["keypoints"]))
            diag = payload["pose_diagnostics"]
            self.assertEqual((diag["tracked_frames"], diag["interpolated_frames"], diag["lost_frames"]), (7, 1, 1))
        self.assertEqual(reopened.frame_timestamps, {
            f"frame_{i+1:04d}.jpg": round(i / FRAME_RATE, 3) for i in range(9)
        })
        self.assertEqual(reopened.effective_fps, FRAME_RATE)
        self.assertEqual(saved.report["subscores"], {})
        self.assertIsNone(saved.force_score)
        self._assert_no_external_ai(pipeline.guards)


if __name__ == "__main__":
    unittest.main()
