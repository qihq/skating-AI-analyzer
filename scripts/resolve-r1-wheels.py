"""Resolve hashes for completed PyPI downloads; this is not a complete dependency lock.

CPU Torch artifacts use a separate official index and require independent verification.
An optional prior wheel cache is read only. Never emits wheelhouse-manifest.json.
"""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from packaging.utils import parse_wheel_filename

parser = argparse.ArgumentParser()
parser.add_argument('--release', type=Path)
parser.add_argument('--cache', type=Path)
args = parser.parse_args()
out = (args.release or Path(Path('.trial-release-path').read_text().strip())).resolve()
metadata = out / 'pypi-metadata'
metadata.mkdir(exist_ok=True)
wheelhouse = out / 'wheelhouse'
wheelhouse.mkdir(exist_ok=True)
files = {p.name for p in wheelhouse.glob('*.whl')}
if args.cache:
    files.update(p.name for p in args.cache.glob('*.whl'))

def lookup(filename):
    name, version, _, _ = parse_wheel_filename(filename)
    url = f'https://pypi.org/pypi/{name}/{version}/json'
    meta = metadata / f'{name}-{version}.json'
    try:
        if version.local:
            raise ValueError('Non-PyPI local version; verify against the official CPU Torch index separately')
        try:
            data = json.loads(meta.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            pending = meta.with_suffix('.pending.json')
            subprocess.run(['curl.exe', '--silent', '--show-error', '--fail', '--retry', '1', '--connect-timeout', '10', '--max-time', '30', url, '-o', str(pending)], check=True)
            data = json.loads(pending.read_text(encoding='utf-8'))
            pending.replace(meta)
        artifact = next(f for f in data['urls'] if f['filename'] == filename)
        digest = artifact['digests']['sha256']
        cached = args.cache / filename if args.cache else None
        if cached and cached.is_file() and hashlib.sha256(cached.read_bytes()).hexdigest() == digest:
            shutil.copy2(cached, wheelhouse / filename)
        local = wheelhouse / filename
        verified = local.is_file() and hashlib.sha256(local.read_bytes()).hexdigest() == digest
        return {'filename': filename, 'url': artifact['url'], 'sha256': digest, 'size': artifact['size'], 'metadata_url': url, 'verified': verified}
    except Exception as exc:
        return {'filename': filename, 'verified': False, 'error': str(exc), 'metadata_url': url}

with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    results = list(pool.map(lookup, sorted(files)))
(out / 'partial-wheel-verification.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
print(f'{sum(item["verified"] for item in results)}/{len(results)} cached wheels verified; dependency closure is NOT established')
