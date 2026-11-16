"""Build-time inventory: official person artifact and MediaPipe wheel-bundled models."""
from pathlib import Path
import hashlib
import json
import mediapipe
base = Path(mediapipe.__file__).parent
source = json.loads(Path('/models/source.json').read_text())
models = []
for role, path, origin in [
    ('person', Path('/models/yolov8n.pt'), source['source']),
    ('pose', base/'modules/pose_landmark/pose_landmark_full.tflite', 'mediapipe==0.10.14 official PyPI wheel'),
    ('pose_detection', base/'modules/pose_detection/pose_detection.tflite', 'mediapipe==0.10.14 official PyPI wheel'),
]:
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if role == 'person':
        assert digest == source['sha256']
    models.append({'role': role, 'path': str(path), 'source': origin, 'sha256': digest, 'bytes': path.stat().st_size})
Path('/models/manifest.json').write_text(json.dumps(models, indent=2))
print(json.dumps(models, indent=2))
