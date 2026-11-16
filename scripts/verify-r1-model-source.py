"""Verify an existing YOLO weight against primary Ultralytics repository metadata.
No weights are deserialized. No release files are created unless source size/hash match.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request

p=argparse.ArgumentParser();p.add_argument('--release',type=Path,required=True);p.add_argument('--model',type=Path,required=True);p.add_argument('--evidence',type=Path,required=True);a=p.parse_args()
assert not (a.release/'manifest.json').exists() and not list(a.release.glob('*.tar')), 'released directory is immutable'
a.evidence.mkdir(exist_ok=True,parents=True)
local_hash=hashlib.sha256(a.model.read_bytes()).hexdigest();size=a.model.stat().st_size
attempts=[];verified=None
urls=[('hf-tree','https://huggingface.co/api/models/Ultralytics/YOLOv8/tree/main'),('github-release','https://api.github.com/repos/ultralytics/assets/releases/tags/v8.3.0')]
for key,url in urls:
    try:
        with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'skating-r1-provenance-check'}),timeout=15) as response:
            body=response.read()
        (a.evidence/(key+'-primary.json')).write_bytes(body)
        metadata=json.loads(body)
        if key=='hf-tree':
            item=next(x for x in metadata if x['path']=='yolov8n.pt')
            digest=item['lfs']['oid'];source_size=item['size']
        else:
            item=next(x for x in metadata['assets'] if x['name']=='yolov8n.pt')
            declared=item.get('digest') or ''
            assert declared.startswith('sha256:'), 'official asset metadata has no SHA256; cannot authenticate cached weights'
            digest=declared.split(':',1)[1];source_size=item['size']
        assert digest==local_hash and source_size==size, 'local model differs from official artifact'
        verified={'source':url,'sha256':local_hash,'bytes':size,'metadata_sha256':hashlib.sha256(body).hexdigest(),'verified_at':datetime.now(timezone.utc).isoformat(),'verification':'primary repository metadata SHA256 and size; no model loading'}
        attempts.append({'url':url,'status':'verified'});break
    except Exception as exc:
        attempts.append({'url':url,'status':'failed','error':repr(exc)})
receipt={'local_model':str(a.model.resolve()),'local_sha256':local_hash,'bytes':size,'attempts':attempts,'verified':verified is not None}
(a.evidence/'model-provenance-attempts.json').write_text(json.dumps(receipt,indent=2))
if verified is None:
    print(json.dumps(receipt,indent=2));raise SystemExit('Model provenance unavailable; no release model or source manifest created')
(a.release/'models').mkdir(exist_ok=True);shutil.copy2(a.model,a.release/'models/yolov8n.pt')
(a.release/'model-source.json').write_text(json.dumps(verified,indent=2))
print(json.dumps(verified,indent=2))
