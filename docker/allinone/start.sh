#!/bin/sh
set -eu

mkdir -p /data/uploads /data/archive /backups /var/log/nginx

cd /workspace/backend

if [ -f /workspace/.env ]; then
  set -a
  . /workspace/.env
  set +a
fi

uvicorn app.main:app --host 127.0.0.1 --port 8000 &
UVICORN_PID=$!

cleanup() {
  if kill -0 "$UVICORN_PID" 2>/dev/null; then
    kill "$UVICORN_PID"
    wait "$UVICORN_PID" || true
  fi
}

trap cleanup INT TERM

nginx -g 'daemon off;' &
NGINX_PID=$!

STATUS=0
while kill -0 "$UVICORN_PID" 2>/dev/null && kill -0 "$NGINX_PID" 2>/dev/null; do
  sleep 2
done

if ! kill -0 "$UVICORN_PID" 2>/dev/null; then
  wait "$UVICORN_PID" || STATUS=$?
else
  STATUS=1
fi

cleanup
if kill -0 "$NGINX_PID" 2>/dev/null; then
  kill "$NGINX_PID"
  wait "$NGINX_PID" || true
fi

exit "$STATUS"
