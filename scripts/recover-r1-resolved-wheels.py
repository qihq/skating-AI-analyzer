"""Recover pip's downloaded wheels by official resolution hashes; emit a hashed lock.
The pip report must come from the target Linux/Python resolver. Never trusts cache names.
"""
import argparse,hashlib,json,shutil
from pathlib import Path
from urllib.parse import urlsplit,unquote
p=argparse.ArgumentParser();p.add_argument('--release',type=Path,required=True);a=p.parse_args();r=a.release
assert not (r/'manifest.json').exists() and not list(r.glob('*.tar')), 'released directory is immutable'
report=json.loads((r/'acceptance-20261015/pip-resolution.json').read_text())
items=[]
for x in report['install']:
 d=x['download_info'];u=d['url'];h=d['archive_info']['hashes']['sha256']
 assert urlsplit(u).hostname in {'files.pythonhosted.org','download.pytorch.org','download-r2.pytorch.org'},u
 name=unquote(urlsplit(u).path.rsplit('/',1)[1]);assert name.endswith('.whl'),name
 items.append(dict(filename=name,url=u,sha256=h,name=x['metadata']['name'],version=x['metadata']['version']))
w=r/'wheelhouse';w.mkdir(exist_ok=True);needed={x['sha256']:x for x in items if not (w/x['filename']).exists() or hashlib.sha256((w/x['filename']).read_bytes()).hexdigest()!=x['sha256']}
for f in (r/'acceptance-20261015/pip-cache').rglob('*.body'):
 if not needed:break
 with f.open('rb') as stream:
  if stream.read(4)!=b'PK\x03\x04':continue
 digest=hashlib.sha256(f.read_bytes()).hexdigest()
 if digest in needed:
  item=needed.pop(digest);shutil.copy2(f,w/item['filename'])
missing=[]
for x in items:
 f=w/x['filename'];x['verified']=f.exists() and hashlib.sha256(f.read_bytes()).hexdigest()==x['sha256'];x['size']=f.stat().st_size if f.exists() else None
 if not x['verified']:missing.append(x['filename'])
(r/'acceptance-20261015/resolved-wheel-verification.json').write_text(json.dumps(items,indent=2))
assert not missing,missing
(r/'wheelhouse-manifest.json').write_text(json.dumps(items,indent=2))
Path('backend/requirements-trial-analysis.lock').write_text('# Linux amd64 CPython 3.11; official pip resolver report + artifact SHA256 verification.\n'+'\n'.join(f"{x['name']}=={x['version']} --hash=sha256:{x['sha256']}" for x in sorted(items,key=lambda v:v['name'].lower()))+'\n')
print('PASS',len(items),'resolved wheels verified; offline install and pip check remain required')
