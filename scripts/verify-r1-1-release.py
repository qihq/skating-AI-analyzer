import sys, pathlib, json, subprocess, time, hashlib, re, traceback
import httpx
sys.stdout.reconfigure(encoding='utf-8')
import argparse
parser=argparse.ArgumentParser(description='R1.1 local Docker acceptance; never contacts NAS')
parser.add_argument('--release', required=True)
parser.add_argument('--evidence', required=True)
parser.add_argument('--container', required=True)
args=parser.parse_args()
R=pathlib.Path(args.release).resolve()
D=pathlib.Path(args.evidence).resolve()
D.mkdir(parents=True, exist_ok=False)
IMAGE=json.loads((R/'build-inputs.json').read_text(encoding='utf-8'))['tag']
C=args.container
assert C.startswith('skating-r11-'), 'only this release test namespace is permitted'
result = {'status':'running','container':C,'image':IMAGE,'target_nas_verified':False,'test_probes':False,'checks':[]}
created = False

def save(name, obj):
    (D/name).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')
def docker(*args, input=None):
    p=subprocess.run(['docker',*args], input=input, text=True, encoding='utf-8', capture_output=True, timeout=90)
    if p.returncode: raise RuntimeError(f'docker {args[:2]}: {p.stderr}')
    return p.stdout

def check(name, **fields):
    result['checks'].append({'name':name,'passed':True,**fields}); save('production-smoke.json',result)
    print(name, fields, flush=True)

def health():
    start=time.monotonic()
    while time.monotonic()-start<120:
        try:
            response=client.get('/api/health')
            if response.status_code==200:return response.json()
        except httpx.HTTPError:pass
        time.sleep(.5)
    raise AssertionError('startup timeout')

def terminal(ident):
    start=time.monotonic(); transitions=[]
    while time.monotonic()-start<180:
        response=client.get('/api/analysis/'+ident);response.raise_for_status(); detail=response.json()
        if not transitions or transitions[-1]!=detail['status']:transitions.append(detail['status'])
        if detail['status'] in ('completed','failed','awaiting_target_selection'):
            return detail,round(time.monotonic()-start,3),transitions
        time.sleep(.5)
    raise AssertionError('analysis timeout')

try:
    assert docker('context','show').strip()=='desktop-linux'
    for name in ('data','backups'):(D/name).mkdir(exist_ok=False)
    cmd=['run','-d','--name',C,'-p','127.0.0.1::80','--mount',f'type=bind,source={D/"data"},target=/data','--mount',f'type=bind,source={D/"backups"},target=/backups',IMAGE]
    save('production-command.json',['docker',*cmd]);docker(*cmd);created=True
    info=json.loads(docker('inspect',C))[0];save('production-initial-inspect.json',info)
    assert info['Image']==json.loads(docker('image','inspect',IMAGE))[0]['Id']
    assert {m['Destination'] for m in info['Mounts']}=={'/data','/backups'}
    port=info['NetworkSettings']['Ports']['80/tcp'][0]['HostPort']
    client=httpx.Client(base_url='http://127.0.0.1:'+port,timeout=30,trust_env=False)
    result['url']='http://127.0.0.1:'+port
    h=health();save('health.json',h);check('formal_start_fresh_data',port=port)
    source=json.loads((R/'source-files.json').read_text(encoding='utf-8-sig'))
    files=source['files'] if isinstance(source,dict) else source
    expected={x['path']:x['sha256'] for x in files if x['path'].startswith('backend/app/')}
    code='''import pathlib,json,hashlib,importlib.util
expected=json.loads(EXPECTED)
mismatch=[]
for name,sha in expected.items():
 p=pathlib.Path('/workspace')/name
 if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=sha:mismatch.append(name)
print(json.dumps({'backend_files_checked':len(expected),'mismatches':mismatch,'model_sha256':hashlib.sha256(pathlib.Path('/models/yolov8n.pt').read_bytes()).hexdigest(),'profile':pathlib.Path('/etc/skating-trial-profile').read_text().strip(),'sitecustomize':str(importlib.util.find_spec('sitecustomize')),'usercustomize':str(importlib.util.find_spec('usercustomize')),'model_manifest':json.loads(pathlib.Path('/models/manifest.json').read_text())}))
'''.replace('EXPECTED',repr(json.dumps(expected)))
    integrity=json.loads(docker('exec','-i',C,'python','-',input=code));save('image-content-verification.json',integrity)
    assert not integrity['mismatches']
    assert integrity['model_sha256']=='f59b3d833e2ff32e194b5bb8e08d211dc7c5bdf144b90d2c8412c47ccfc83b36'
    assert integrity['profile']=='legacy-analysis-preview'
    assert integrity['sitecustomize']==integrity['usercustomize']=='None'
    check('published_app_model_and_fixed_profile_match',backend_files=integrity['backend_files_checked'])
    page=client.get('/');assert page.status_code==200 and '<html' in page.text
    asset=re.search(r'src="(/assets/[^\"]+\.js)"',page.text).group(1);assert client.get(asset).status_code==200
    check('nginx_home_static_same_origin_health',asset=asset)
    gates=json.loads((R/'formal-gate-paths.json').read_text(encoding='utf-8')); outcomes=[]
    route_code = "from app.main import app; import json; print('ROUTES_JSON'+json.dumps({r.path:sorted(r.methods) for r in app.routes if hasattr(r,'methods')}))"
    route_stdout=docker('exec',C,'python','-c',route_code)
    routes=json.loads(next(line[len('ROUTES_JSON'):] for line in route_stdout.splitlines() if line.startswith('ROUTES_JSON')))
    save('declared-route-methods.json',routes)
    for gate in gates:
        path=re.sub(r'\{[^}]+\}','review-placeholder',gate['path'])
        methods=routes[gate['path']];method='GET' if 'GET' in methods else next(m for m in ('POST','PUT','PATCH','DELETE') if m in methods)
        response=client.request(method,path)
        outcomes.append({'path':path,'method':method,'status':response.status_code});assert response.status_code==403,(path,response.status_code)
    save('formal-gates-recheck.json',outcomes);check('formal_closed_routes_declared_methods',count=len(outcomes))
    assert client.get('/api/analysis/').json()==[]
    docker('exec',C,'ffmpeg','-hide_banner','-loglevel','error','-y','-f','lavfi','-i',
           'testsrc2=duration=4:size=320x240:rate=10','-c:v','libx264','-pix_fmt','yuv420p','/data/tmp/synthetic-no-person.mp4')
    docker('cp',C+':/data/tmp/synthetic-no-person.mp4',str(D/'synthetic-no-person.mp4'))
    video=(D/'synthetic-no-person.mp4').read_bytes();upload_start=time.monotonic()
    response=client.post('/api/analysis/upload',files={'file':('synthetic-no-person.mp4',video,'video/mp4')},data={'action_type':'跳跃','manual_action_window_start_sec':'2','manual_action_window_end_sec':'4'})
    assert response.status_code==202,response.text
    ident=response.json()['id'];detail,elapsed,transitions=terminal(ident);save('first-analysis-detail.json',detail)
    assert detail['status']=='completed',detail.get('error_message')
    assert detail['force_score'] is None and detail['report']['subscores']=={}
    assert detail['report']['local_execution']==dict(decode=True,detection=True,tracking=False,pose=False,external_ai=False)
    check('real_upload_decode_pretrained_detection_unscored_report',id=ident,elapsed_sec=round(time.monotonic()-upload_start,3),transitions=transitions)
    sampling=detail['frame_motion_scores']
    assert sampling['selection_strategy']=='uniform_window_fallback',sampling
    assert sampling['timestamp_basis']=='decoded_source_pts_time'
    assert sampling['window_start']==2. and sampling['window_end']==4.
    assert len(sampling['selected'])==20
    assert all(2. <= r['timestamp'] < 4. for r in sampling['selected'])
    assert sampling['selected'][-1]['timestamp']==3.9
    check('final_image_manual_window_timeline_in_real_upload',last_time=3.9,frames=20)
    response=client.post('/api/analysis/'+ident+'/retry');assert response.status_code==200,response.text
    detail,elapsed,transitions=terminal(ident);save('retry-analysis-detail.json',detail)
    assert detail['status']=='completed';rows=client.get('/api/analysis/').json();assert len(rows)==1 and rows[0]['id']==ident
    check('same_id_retry_no_duplicate_rows',id=ident,elapsed_sec=elapsed,transitions=transitions)
    report=detail['report'];docker('restart','--time','30',C)
    restarted=json.loads(docker('inspect',C))[0]
    restart_port=restarted['NetworkSettings']['Ports']['80/tcp'][0]['HostPort']
    client.close()
    client=httpx.Client(base_url='http://127.0.0.1:'+restart_port,timeout=30,trust_env=False)
    result['restart_port']=restart_port
    health()
    reopened=client.get('/api/analysis/'+ident).json();save('restart-analysis-detail.json',reopened)
    assert reopened['status']=='completed' and reopened['report']==report
    response=client.get('/api/analysis/'+ident+'/video');assert response.status_code==200
    assert hashlib.sha256(response.content).digest()==hashlib.sha256(video).digest()
    check('restart_retains_report_and_exact_source_video',video_sha256=hashlib.sha256(video).hexdigest())
    result['status']='passed'
except Exception as exc:
    result['status']='failed';result['error']=repr(exc);(D/'production-error.txt').write_text(traceback.format_exc(),encoding='utf-8');print(traceback.format_exc(),flush=True)
finally:
    if created:
        try:
            docker('stop','--time','30',C)
            final=json.loads(docker('inspect',C))[0];save('production-final-inspect.json',final)
            logs=subprocess.run(['docker','logs',C],capture_output=True,text=True,encoding='utf-8');(D/'production.log').write_text(logs.stdout+'\n'+logs.stderr,encoding='utf-8')
            result['final_state']=final['State']['Status'];result['final_exit_code']=final['State']['ExitCode']
            if result['final_state']!='exited' or result['final_exit_code']!=0:result['status']='failed'
        except Exception as exc:result['cleanup_error']=repr(exc);result['status']='failed'
    save('production-smoke.json',result);print(json.dumps(result,ensure_ascii=False),flush=True)
if result['status']!='passed':
    raise SystemExit(1)