from pathlib import Path
import shutil, hashlib, json, argparse
parser=argparse.ArgumentParser()
parser.add_argument('--profile', choices=['web-preview','legacy-analysis-preview'], default='web-preview')
args=parser.parse_args()
root=Path.cwd(); out=Path((root/'.trial-release-path').read_text().strip()).resolve()
if (out/'manifest.json').exists() or list(out.glob('*.tar')):
    raise SystemExit('Refusing to overwrite a released directory; create a new release and update .trial-release-path')
if args.profile == 'legacy-analysis-preview':
    required = [root/'backend/requirements-trial-analysis.lock', out/'wheelhouse-manifest.json', out/'model-source.json', out/'models/yolov8n.pt']
    missing = [str(p) for p in required if not p.is_file()]
    if missing:
        raise SystemExit('R1 prerequisites missing; no staging files written: ' + ', '.join(missing))
stage=out/('analysis-context' if args.profile == 'legacy-analysis-preview' else 'web-context'); stage.mkdir(exist_ok=True)
files=[]
for base,exts in [('backend/app',{'.py','.json','.ttf','.otf','.ttc'}),('frontend/src',{'.ts','.tsx','.css'}),('frontend/public',{'.png','.ico','.webmanifest','.js','.jpg','.svg','.webp'})]:
    files += [p for p in (root/base).rglob('*') if p.is_file() and p.suffix in exts and '__pycache__' not in p.parts]
files += [root/'frontend'/p for p in ['package.json','package-lock.json','index.html','postcss.config.js','tailwind.config.js','tsconfig.json','vite.config.ts']]
files += [root/'backend/requirements-trial-web.txt',root/'backend/requirements-trial-web.lock',root/'docker/allinone/Dockerfile.trial',root/'docker/allinone/nginx.conf',root/'docker/allinone/start-trial.sh',root/'docker/allinone/trial.env.example']
if args.profile == 'legacy-analysis-preview':
    files += [root/p for p in ['backend/requirements.txt', 'backend/requirements-trial-analysis.txt', 'backend/requirements-trial-analysis.lock', 'docker/allinone/Dockerfile.analysis', 'scripts/build-model-manifest.py']]
manifest=[]
for p in sorted(files):
    rel=p.relative_to(root); dest=stage/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
    manifest.append({'path':rel.as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size})
(out/'source-files.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
print(len(files),hashlib.sha256((out/'source-files.json').read_bytes()).hexdigest())

# Official-PyPI dependency artifacts are separate from the dirty-source manifest.
wheel_manifest = json.loads((out/'wheelhouse-manifest.json').read_text(encoding='utf-8'))
(stage/'wheelhouse').mkdir(exist_ok=True)
for wheel in wheel_manifest:
    src=out/'wheelhouse'/wheel['filename']
    assert hashlib.sha256(src.read_bytes()).hexdigest()==wheel['sha256'], src
    shutil.copy2(src, stage/'wheelhouse'/wheel['filename'])
print('Verified official wheel hashes:',len(wheel_manifest))

if args.profile == 'legacy-analysis-preview':
    provenance=json.loads((out/'model-source.json').read_text(encoding='utf-8'))
    model=out/'models/yolov8n.pt'
    assert hashlib.sha256(model.read_bytes()).hexdigest() == provenance['sha256']
    (stage/'models').mkdir(exist_ok=True)
    shutil.copy2(model, stage/'models/yolov8n.pt')
    shutil.copy2(out/'model-source.json', stage/'models/source.json')
