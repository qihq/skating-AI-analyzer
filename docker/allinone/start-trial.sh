#!/bin/sh
set -eu
mkdir -p /data/uploads /data/archive /data/cache /data/tmp /data/analysis-assets /data/golden /data/model-outputs /data/test-data /data/temp-frames /backups /var/log/nginx
cd /workspace/backend
uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 &
BACKEND=$!
nginx -g 'daemon off;' &
FRONTEND=$!
cleanup() {
  kill -TERM "$BACKEND" "$FRONTEND" 2>/dev/null || true
  wait "$BACKEND" 2>/dev/null || true
  wait "$FRONTEND" 2>/dev/null || true
}
trap 'cleanup; exit 0' TERM INT
while kill -0 "$BACKEND" 2>/dev/null && kill -0 "$FRONTEND" 2>/dev/null; do
  sleep 1 &
  wait $! || true
done
cleanup
exit 1
