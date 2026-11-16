"""Synthetic policy/lifecycle tests; no claims about person accuracy."""
import asyncio
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch
import httpx
from fastapi import BackgroundTasks, FastAPI
from app.trial import TrialGate


class LocalPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_sinks_refuse_before_client_construction(self):
        from app.services import providers as p
        config = p.ActiveProviderConfig('synthetic', 'vision', 'fake', 'qwen', 'https://invalid.example', 'fake', 'fake', 'synthetic-key', None)
        for profile in ('web-preview', 'legacy-analysis-preview'):
            for configured in (False, True):
                with self.subTest(profile=profile, configured=configured), patch.dict(os.environ, SKATING_TRIAL_PROFILE=profile), patch.object(p, 'AsyncOpenAI') as openai, patch.object(p.httpx, 'AsyncClient') as client:
                    provider = config if configured else None
                    calls = [
                        p.request_text_completion(provider, messages=[], temperature=0, max_tokens=1),
                        *[fn(provider, video_path=Path('missing.mp4'), system_prompt='', user_prompt='', temperature=0, max_tokens=1) for fn in (p.request_dashscope_video_completion, p.request_doubao_vision_completion, p.request_mimo_video_completion)],
                        p.get_active_provider('report'), p.get_vision_providers(), p.test_provider_connectivity(provider),
                    ]
                    for call in calls:
                        with self.assertRaisesRegex(RuntimeError, 'external_ai_disabled'):
                            await call
                    openai.assert_not_called()
                    client.assert_not_called()

    async def test_report_fallback_never_resolves_provider_or_invents_scores(self):
        from app.services import report as r
        for configured in (False, True):
            with patch.dict(os.environ, SKATING_TRIAL_PROFILE='legacy-analysis-preview', QWEN_API_KEY='synthetic' if configured else ''), patch.object(r, 'get_active_provider', new_callable=AsyncMock) as provider:
                report = await r.generate_report('跳跃', {}, {'bio_subscores': {'balance': 75}})
                provider.assert_not_called()
                self.assertEqual(report['source'], 'legacy/local')
                self.assertEqual(report['subscores'], {})
                self.assertIsNone(report['technical_conclusion'])
                self.assertEqual(r.ensure_report_subscores(report, {})['subscores'], {})

    async def test_pending_or_failed_local_report_never_invents_reference_scores(self):
        from app.services.report import ensure_report_subscores
        with patch.dict(os.environ, SKATING_TRIAL_PROFILE='legacy-analysis-preview'):
            for report in (None, {}, {'subscores': {'takeoff_power': 75}}):
                self.assertEqual(ensure_report_subscores(report, {})['subscores'], {})

    async def test_busy_until_background_finishes_and_releases_on_error(self):
        app = FastAPI()
        entered, release = asyncio.Event(), asyncio.Event()
        async def work():
            entered.set()
            await release.wait()
            raise RuntimeError('synthetic task failure')
        async def upload(background_tasks: BackgroundTasks):
            background_tasks.add_task(work)
            return {'accepted': True}
        upload.__module__ = 'app.routers.analysis'
        upload.__name__ = 'upload_analysis'
        app.add_api_route('/upload', upload, methods=['POST'])
        app.add_middleware(TrialGate, routes=app.router.routes)
        with patch.dict(os.environ, SKATING_TRIAL_PROFILE='legacy-analysis-preview'), patch('app.services.local_runtime.require_local_runtime'):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                first = asyncio.create_task(client.post('/upload'))
                await asyncio.wait_for(entered.wait(), 5)
                self.assertEqual((await client.post('/upload')).status_code, 429)
                release.set()
                with self.assertRaisesRegex(RuntimeError, 'synthetic task failure'):
                    await first
                # Request reaches its background again: busy flag was released.
                with self.assertRaisesRegex(RuntimeError, 'synthetic task failure'):
                    await client.post('/upload')

    async def test_restart_recovery_keeps_waiting_and_completed_results(self):
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        from app.models import Analysis, Base
        from app.services.local_runtime import recover_interrupted_local_analyses
        engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        statuses = ['pending', 'processing', 'extracting_frames', 'analyzing', 'generating_report', 'completed', 'awaiting_target_selection', 'failed']
        async with factory() as session:
            for state in statuses:
                session.add(Analysis(id=state, action_type='跳跃', status=state, video_path='/data/uploads/test.mp4', report={'summary': 'saved fact'}))
            await session.commit()
        with patch.dict(os.environ, SKATING_TRIAL_PROFILE='legacy-analysis-preview'):
            self.assertEqual(await recover_interrupted_local_analyses(factory), 5)
            self.assertEqual(await recover_interrupted_local_analyses(factory), 0)
        async with factory() as session:
            for state in statuses:
                row = await session.get(Analysis, state)
                self.assertEqual(row.status, 'failed' if state in statuses[:5] else state)
                self.assertEqual(row.report, {'summary': 'saved fact'})
                self.assertEqual(row.video_path, '/data/uploads/test.mp4')
        await engine.dispose()

    async def test_missing_model_rejected_before_upload_side_effects(self):
        from app.services.local_runtime import require_local_runtime
        from fastapi import HTTPException
        with patch.dict(os.environ, SKATING_TRIAL_PROFILE='legacy-analysis-preview', LOCAL_MODEL_MANIFEST='/missing/manifest.json'):
            with self.assertRaises(HTTPException) as caught:
                require_local_runtime()
            self.assertEqual(caught.exception.status_code, 503)

    async def test_local_save_has_no_stale_pose_or_default_score(self):
        from app.routers import analysis as a
        import time
        with patch.object(a, '_save_analysis_fields_with_retry', new_callable=AsyncMock) as save:
            await a._save_local_analysis_result('synthetic', '跳跃', {}, time.perf_counter(), pose_ran=False)
            fields = save.call_args.args[1]
            self.assertEqual(fields['status'], 'completed')
            for key in ('force_score', 'pose_data', 'bio_data', 'target_lock'):
                self.assertIsNone(fields[key])
            self.assertFalse(fields['report']['local_execution']['pose'])
            self.assertEqual(fields['report']['subscores'], {})

    async def test_open_local_result_does_not_backfill_pose(self):
        from app.routers import analysis as a
        from types import SimpleNamespace
        row = SimpleNamespace(report={'source': 'legacy/local'})
        with patch.dict(os.environ, SKATING_TRIAL_PROFILE='legacy-analysis-preview'):
            self.assertIs(await a._ensure_phase3_artifacts(None, row), row)

    async def test_worker_exception_persists_retryable_failure(self):
        from app.routers import analysis as a
        from types import SimpleNamespace
        session = AsyncMock()
        session.get.return_value = SimpleNamespace()
        manager = AsyncMock()
        manager.__aenter__.return_value = session
        with patch.dict(os.environ, SKATING_TRIAL_PROFILE='legacy-analysis-preview'), patch.object(a, 'AsyncSessionLocal', return_value=manager), patch.object(a, '_safe_video_response_path', return_value=None), patch.object(a, 'process_analysis', new_callable=AsyncMock, side_effect=RuntimeError('synthetic failure')), patch.object(a, '_save_analysis_fields_with_retry', new_callable=AsyncMock) as save:
            await a.process_analysis_with_media_renditions('synthetic')
            fields = save.call_args.args[1]
            self.assertEqual(fields['status'], 'failed')
            self.assertEqual(fields['retry_from_stage'], 'extract_frames')
            self.assertEqual(save.call_args.args[0], 'synthetic')

    async def test_tracker_failure_is_not_reported_as_successful_local_tracking(self):
        from app.routers import analysis as a
        with patch.dict(os.environ, SKATING_TRIAL_PROFILE='legacy-analysis-preview'), patch.object(a, 'track_person_bbox_detailed', side_effect=a.PersonTrackerUnavailable('synthetic missing tracker')), patch.object(a, 'track_bbox') as fallback:
            with self.assertRaises(a.PersonTrackerUnavailable):
                a._build_bbox_per_frame([], {'selected_bbox': {'x': 0, 'y': 0, 'w': 1, 'h': 1}})
            fallback.assert_not_called()

    async def test_empty_pose_input_is_not_reported_as_executed(self):
        from app.services.pose import extract_pose
        import tempfile
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, SKATING_TRIAL_PROFILE='legacy-analysis-preview'):
            with self.assertRaisesRegex(RuntimeError, 'no decoded frames'):
                extract_pose(folder)

    async def test_preview_get_does_not_start_uncached_detection(self):
        from app.routers import analysis as a
        from types import SimpleNamespace
        from fastapi import HTTPException
        row = SimpleNamespace(id='synthetic', target_lock_status=None, status='completed', target_lock=None)
        with patch.dict(os.environ, SKATING_TRIAL_PROFILE='legacy-analysis-preview'), patch.object(a, '_target_preview_detected_candidates_from_frames') as detect:
            with self.assertRaises(HTTPException) as caught:
                a._build_target_preview_cached_first(row, [], None)
            self.assertEqual(caught.exception.status_code, 409)
            detect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
