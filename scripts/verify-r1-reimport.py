import httpx,json,time,subprocess,hashlib
from pathlib import Path
E=Path(Path('.r1-current-evidence').read_text().strip());c=httpx.Client(base_url='http://127.0.0.1:27917',timeout=60,trust_env=False)
for _ in range(90):
 try:
  if c.get('/api/health').status_code==200:break
 except httpx.HTTPError:pass
 time.sleep(1)
assert c.get('/').status_code==200
before=c.get('/api/analysis/').json();assert before==[],before
v=(E/'synthetic-no-person.mp4').read_bytes()
r=c.post('/api/analysis/upload',files={'file':('no-person.mp4',v,'video/mp4')},data={'action_type':'跳跃'});assert r.status_code==202,r.text
ident=r.json()['id']
def wait():
 for _ in range(150):
  d=c.get('/api/analysis/'+ident).json()
  if d['status'] in ('completed','failed'):return d
  time.sleep(1)
 raise AssertionError('timeout')
d=wait();assert d['status']=='completed',d
assert d['report']['subscores']=={} and d['force_score'] is None
count=len(c.get('/api/analysis/').json());r=c.post('/api/analysis/'+ident+'/retry');assert r.status_code==200,r.text
assert wait()['status']=='completed';assert len(c.get('/api/analysis/').json())==count
subprocess.run(['docker','restart','skating-r1-reimport-20261015-1730'],check=True,capture_output=True)
for _ in range(90):
 try:
  if c.get('/api/health').status_code==200:break
 except httpx.HTTPError:pass
 time.sleep(1)
assert c.get('/api/analysis/'+ident).json()['report']==d['report']
assert hashlib.sha256(c.get('/api/analysis/'+ident+'/video').content).digest()==hashlib.sha256(v).digest()
inspection=json.loads(subprocess.check_output(['docker','inspect','skating-r1-reimport-20261015-1730']))[0]
assert not any('probe' in m['Destination'] or 'evidence' in m['Destination'] for m in inspection['Mounts'])
out={'status':'passed','container':inspection['Name'],'id':ident,'fresh_volume_initial_rows':0,'upload_real_inference_completed':True,'retry_no_duplicate_rows':True,'restart_report_and_video_retained':True,'test_probes':False,'image_id':inspection['Image'],'result':d}
(E/'tar-reimport-smoke.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in out.items() if k!='result'}))
subprocess.run(['docker','stop','skating-r1-reimport-20261015-1730'],check=True)
