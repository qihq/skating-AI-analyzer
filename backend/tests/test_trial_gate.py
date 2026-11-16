"""Synthetic-only middleware tests: no database, model, real video or diagnostic runner."""
import os
import unittest
from unittest.mock import Mock, patch
from fastapi import FastAPI, BackgroundTasks, Depends
from fastapi.testclient import TestClient
from app.trial import TrialGate, trial_profile

class TrialGateTests(unittest.TestCase):
    def test_baked_profile_cannot_be_overridden(self):
        with patch('app.trial.Path.is_file', return_value=True), patch('app.trial.Path.read_text', return_value='web-preview'):
            for value in ['off', 'legacy-analysis-preview']:
                with patch.dict(os.environ, SKATING_TRIAL_PROFILE=value):
                    with self.assertRaises(RuntimeError): trial_profile()
            with patch.dict(os.environ, SKATING_TRIAL_PROFILE='web-preview'):
                self.assertEqual(trial_profile(), 'web-preview')

    def make(self, module, name, path, method='POST'):
        app=FastAPI(); spy=Mock(); dependency=Mock(return_value=None)
        def dep(): dependency()
        async def endpoint(tasks: BackgroundTasks, unused=Depends(dep)):
            spy('handler');tasks.add_task(spy,'background');return {'ok':True}
        endpoint.__module__=module;endpoint.__name__=name
        app.add_api_route(path,endpoint,methods=[method]);app.add_middleware(TrialGate,routes=app.router.routes)
        return TestClient(app),spy,dependency
    def test_web_blocks_all_analysis_triggers_before_dependencies(self):
        names=['upload_analysis','retry_analysis','create_analysis_comparison','retry_analysis_comparison','rerun_video_ai_keyframes','regenerate_report_from_corrections','confirm_target_lock']
        with patch.dict(os.environ,SKATING_TRIAL_PROFILE='web-preview'):
            for name in names:
                with self.subTest(name=name):
                    client,spy,dep=self.make('app.routers.analysis',name,'/api/test')
                    self.assertEqual(client.post('/api/test',content=b'invalid').status_code,403)
                    spy.assert_not_called();dep.assert_not_called()
    def test_both_profiles_block_new_diagnostics(self):
        for profile in ['web-preview','legacy-analysis-preview']:
            with patch.dict(os.environ,SKATING_TRIAL_PROFILE=profile):
                for module,name in [('app.routers.shadow','create_run'),('app.routers.golden_v2','run_evaluator'),('app.routers.analysis_v2','get_analysis_experience_v2_diagnostic'),('app.routers.debug','local_pose')]:
                    for method in ['GET','POST']:
                        with self.subTest(profile=profile,module=module,method=method):
                            client,spy,dep=self.make(module,name,'/api/test',method)
                            self.assertEqual(client.request(method,'/api/test').status_code,403)
                            spy.assert_not_called();dep.assert_not_called()
    def test_safe_session_write_passes(self):
        with patch.dict(os.environ,SKATING_TRIAL_PROFILE='web-preview'):
            client,spy,dep=self.make('app.routers.skaters','create_training_session','/api/skaters/sessions')
            self.assertEqual(client.post('/api/skaters/sessions').status_code,200);self.assertEqual(spy.call_count,2)
    def test_off_preserves_existing_behavior(self):
        with patch.dict(os.environ,SKATING_TRIAL_PROFILE='off'):
            client,spy,dep=self.make('app.routers.analysis','upload_analysis','/api/test')
            self.assertEqual(client.post('/api/test').status_code,200)
    def test_get_connection_test_is_blocked_before_dependencies(self):
        for profile in ['web-preview', 'legacy-analysis-preview']:
            with patch.dict(os.environ, SKATING_TRIAL_PROFILE=profile):
                client, spy, dep = self.make('app.routers.settings', 'test_api_connection', '/api/settings/test-api', 'GET')
                self.assertEqual(client.get('/api/settings/test-api').status_code, 403)
                spy.assert_not_called()
                dep.assert_not_called()

    def test_provider_write_refused(self):
        with patch.dict(os.environ,SKATING_TRIAL_PROFILE='legacy-analysis-preview'):
            client,spy,dep=self.make('app.routers.providers','save_provider','/api/providers')
            self.assertEqual(client.post('/api/providers').status_code,403);spy.assert_not_called();dep.assert_not_called()


    def test_missing_local_runtime_blocks_before_dependencies(self):
        from fastapi import HTTPException
        with patch.dict(os.environ, SKATING_TRIAL_PROFILE='legacy-analysis-preview'), patch('app.services.local_runtime.require_local_runtime', side_effect=HTTPException(503, 'missing runtime')):
            client, spy, dep = self.make('app.routers.analysis', 'upload_analysis', '/api/test')
            self.assertEqual(client.post('/api/test', content=b'invalid').status_code, 503)
            spy.assert_not_called()
            dep.assert_not_called()

if __name__=='__main__': unittest.main(verbosity=2)
