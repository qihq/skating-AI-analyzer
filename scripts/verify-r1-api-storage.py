"""Real HTTP acceptance for model-independent gates and volume lifecycle.
Deliberately does not claim upload/inference completion: the pretrained model is missing.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time
import httpx

p=argparse.ArgumentParser();p.add_argument('--base-url',default='http://127.0.0.1:27915');p.add_argument('--output',type=Path,required=True);p.add_argument('--phase',choices=['before','after'],required=True);a=p.parse_args()
assert a.base_url.startswith('http://127.0.0.1:'), 'local isolated acceptance only'
checks=[]
def check(name,fn):
    try:
        result=fn();checks.append({'name':name,'status':'passed','evidence':result})
    except Exception as exc:
        checks.append({'name':name,'status':'failed','error':repr(exc)})
    print(json.dumps(checks[-1],ensure_ascii=False),flush=True)
    (a.output/('api-'+a.phase+'.json')).write_text(json.dumps({'scope':'real HTTP; synthetic seeded lifecycle rows, not inference outputs','checks':checks},ensure_ascii=False,indent=2),encoding='utf-8')

with httpx.Client(base_url=a.base_url,timeout=30,follow_redirects=True,trust_env=False) as client:
    for attempt in range(40):
        try:
            if client.get('/api/health').status_code==200:break
        except httpx.HTTPError:pass
        time.sleep(1)
    else:raise RuntimeError('isolated server never became healthy')
    def guards():
        schema=client.get('/openapi.json').json();tested=[]
        for path,operations in schema['paths'].items():
            if path=='/api/settings/test-api' or path.startswith(('/api/shadow/','/api/golden/v2/','/api/debug/')):
                method=next((m for m in ['get','post'] if m in operations),None)
                if method:
                    response=client.request(method,path)
                    assert response.status_code==403,(path,response.status_code,response.text[:100])
                    tested.append({'path':path,'method':method,'status':403})
        assert any(x['path']=='/api/settings/test-api' for x in tested)
        return tested
    def blocked_upload():
        before=client.get('/api/analysis/').json()
        with (a.output/'empty.mp4').open('rb') as stream:
            response=client.post('/api/analysis/upload',files={'file':('empty.mp4',stream,'video/mp4')},data={'action_type':'jump'})
        assert response.status_code==503,response.text
        assert response.json()['detail']['code']=='local_runtime_unavailable'
        assert before==client.get('/api/analysis/').json()
        return {'status':503,'no_record_created':True,'detail':response.json(),'limitation':'fail-closed preflight only; no upload/inference task executed'}
    if a.phase=='before':
        check('rv01_diagnostic_shadow_golden_http_gates',guards)
        check('missing_model_upload_preflight',blocked_upload)
        def training():
            skaters=client.get('/api/skaters/').json();assert skaters
            sid=skaters[0]['id']
            response=client.post(f'/api/skaters/{sid}/sessions',json={'session_date':'2026-10-15','duration_minutes':12,'note':'R1 synthetic acceptance'})
            assert response.status_code==200,response.text
            session=response.json()['id']
            response=client.patch(f'/api/sessions/{session}',json={'note':'R1 persisted after update','duration_minutes':15})
            assert response.status_code==200,response.text
            assert client.get(f'/api/sessions/{session}').json()['duration_minutes']==15
            (a.output/'api-state.json').write_text(json.dumps({'session':session,'skater':sid}))
            return {'session':session,'create_read_update':True,'delete':'after restart'}
        check('training_create_read_update',training)
    else:
        def training_after():
            state=json.loads((a.output/'api-state.json').read_text());sid=state['session']
            response=client.get(f'/api/sessions/{sid}');assert response.status_code==200,response.text
            assert response.json()['note']=='R1 persisted after update'
            assert response.json()['duration_minutes']==15
            assert client.delete(f'/api/sessions/{sid}').json()['success'] is True
            assert client.get(f'/api/sessions/{sid}').status_code==404
            return {'persisted_across_container_restart':True,'delete_verified':True}
        check('training_restart_persistence_delete',training_after)
        def lifecycle():
            rows=[]
            for prior in ['processing','completed','awaiting_target_selection','failed']:
                ident='r1-fixture-'+prior
                response=client.get('/api/analysis/'+ident);assert response.status_code==200,response.text
                data=response.json();expected='failed' if prior=='processing' else prior
                assert data['status']==expected,(prior,data['status'])
                if prior=='processing':assert data['retry_from_stage']=='extract_frames'
                if prior=='completed':
                    assert data['report']['subscores']=={}
                    assert data['report'].get('technical_conclusion') is None
                    assert data['force_score'] is None
                    again=client.get('/api/analysis/'+ident).json()
                    assert again['report']==data['report']
                video=client.get('/api/analysis/'+ident+'/video');assert video.status_code==200,video.text[:100]
                assert hashlib.sha256(video.content).hexdigest()==hashlib.sha256((a.output/'empty.mp4').read_bytes()).hexdigest()
                rows.append({'fixture_prior':prior,'after_restart':expected,'video_sha256_matches':True})
            return {'rows':rows,'limitation':'directly seeded synthetic records; not a task interrupted during actual inference'}
        check('seeded_lifecycle_and_video_result_persistence',lifecycle)
        check('rv01_gates_after_restart',guards)
raise SystemExit(1 if any(c['status']!='passed' for c in checks) else 0)
