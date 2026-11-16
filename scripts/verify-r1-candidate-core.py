"""Formal R1 image HTTP acceptance; only synthetic empty video, no human accuracy claims."""
import json,time,re,hashlib,subprocess
from pathlib import Path
import httpx
E=Path('.r1-current-evidence').read_text().strip(); E=Path(E)
C='skating-r1-candidate-20261015-19'; client=httpx.Client(base_url='http://127.0.0.1:27916',timeout=90,trust_env=False)
video=E/'synthetic-no-person.mp4'
checks=[]
def record(name,**e):
 checks.append(dict(name=name,status='passed',**e));(E/'core-api-results.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8');print(name,e,flush=True)
def upload():
 with video.open('rb') as f:r=client.post('/api/analysis/upload',files={'file':('empty.mp4',f,'video/mp4')},data={'action_type':'跳跃'})
 assert r.status_code==202,(r.status_code,r.text)
 return r.json()['id']
def wait(ident):
 for _ in range(150):
  r=client.get('/api/analysis/'+ident);r.raise_for_status();d=r.json()
  if d['status'] in ['completed','failed','awaiting_target_selection']:
   (E/(ident+'.json')).write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8');return d
  time.sleep(1)
 raise AssertionError('task timeout')
def healthy():
 for _ in range(90):
  try:
   if client.get('/api/health').status_code==200:return
  except httpx.HTTPError:pass
  time.sleep(1)
 raise AssertionError('startup timeout')
def docker(*args):subprocess.run(['docker',*args],check=True,capture_output=True)
healthy()
r=client.get('/');assert r.status_code==200 and '<html' in r.text
asset=re.search(r'src="(/assets/[^"]+\.js)"',r.text).group(1);assert client.get(asset).status_code==200
record('formal_nginx_frontend_static_same_origin_health',asset=asset)
r=client.post('/api/analysis/upload',files={'file':('bad.mp4',b'not video','video/mp4')},data={'action_type':'跳跃'});assert r.status_code==400,r.text
record('bad_video_readable_400',response=r.json())
ident=upload();d=wait(ident);assert d['status']=='completed',d
assert d['force_score'] is None and d['report']['subscores']=={},d['report']
assert d['report']['local_execution']==dict(decode=True,detection=True,tracking=False,pose=False,external_ai=False)
assert client.get('/api/analysis/'+ident).json()['report']==d['report']
record('real_upload_pretrained_empty_video_saved_reopened',id=ident,execution=d['report']['local_execution'],scores_empty=True)
(E/'control.txt').write_text('fail');failed=upload();f=wait(failed);assert f['status']=='failed' and f['error_message'] and f['retry_from_stage'],f
record('actual_background_controlled_failure',id=failed,error=f['error_message'])
(E/'control.txt').write_text('normal');r=client.post('/api/analysis/'+failed+'/retry');assert r.status_code==200,r.text
f=wait(failed);assert f['status']=='completed',f
record('failed_lock_released_same_id_retry',id=failed)
(E/'control.txt').write_text('delay');interrupted=upload()
for _ in range(30):
 if client.get('/api/analysis/'+interrupted).json()['status']=='extracting_frames':break
 time.sleep(.2)
r=client.post('/api/analysis/upload',files={'file':('empty.mp4',video.read_bytes(),'video/mp4')},data={'action_type':'跳跃'});assert r.status_code==429,r.text
record('single_actual_background_task_429',id=interrupted,response=r.json())
docker('kill',C);(E/'control.txt').write_text('normal');docker('start',C);healthy()
f=wait(interrupted);assert f['status']=='failed' and f['retry_from_stage'],f
record('interrupted_real_task_restart_recovery',id=interrupted,error=f['error_message'])
r=client.post('/api/analysis/'+interrupted+'/retry');assert r.status_code==200,r.text
assert wait(interrupted)['status']=='completed'
record('recovered_same_id_retry',id=interrupted)
(E/'control.txt').write_text('candidate');ident=upload();assert wait(ident)['status']=='awaiting_target_selection'
(E/'control.txt').write_text('normal')
r=client.post('/api/analysis/'+ident+'/target-lock',json={'manual_bbox':{'x':.1,'y':.1,'width':.8,'height':.8}});assert r.status_code==200,r.text
manual=wait(ident);assert manual['status']=='completed',manual
assert client.get('/api/analysis/'+ident).json()['report']==manual['report']
record('synthetic_manual_bbox_confirmation_continue_save_reopen',id=ident,execution=manual['report']['local_execution'],limitation='empty video synthetic rectangle; not detected person or positive pose')
docker('stop','--time','20',C)
exitcode=subprocess.check_output(['docker','inspect','-f','{{.State.ExitCode}}',C],text=True).strip();assert exitcode=='0',exitcode
record('formal_sigterm_clean_exit',exit_code=0)
docker('start',C);healthy()
for item in [ident,failed,interrupted]:
 d=client.get('/api/analysis/'+item).json();assert d['status']=='completed',d
 r=client.get('/api/analysis/'+item+'/video');assert r.status_code==200
 assert hashlib.sha256(r.content).digest()==hashlib.sha256(video.read_bytes()).digest()
assert client.get('/api/analysis/'+ident).json()['report']==manual['report']
record('actual_video_and_results_survive_restart',ids=[ident,failed,interrupted])
events=[json.loads(x) for x in (E/'network.jsonl').read_text().splitlines()]
external=[x for x in events if x.get('local') is False];assert not external,external
record('python_outbound_observer_full_exercised_background',external_attempts=0,observer_starts=sum(x['event']=='observer_started' for x in events),limitation='Python audit only; native and subprocess system calls not captured; no human positive path')
(E/'core-state.json').write_text(json.dumps({'ids':[ident,failed,interrupted]}))

