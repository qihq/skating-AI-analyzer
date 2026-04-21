FROM node:20-alpine AS frontend-build

WORKDIR /build/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg nginx curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace/backend

COPY backend/requirements.txt /workspace/backend/requirements.txt
RUN pip install --no-cache-dir -r /workspace/backend/requirements.txt

COPY backend/app /workspace/backend/app
COPY --from=frontend-build /build/frontend/dist /usr/share/nginx/html
COPY docker/allinone/nginx.conf /etc/nginx/conf.d/default.conf
COPY docker/allinone/start.sh /start.sh

RUN mkdir -p /data/uploads /data/archive /backups /var/log/nginx \
    && rm -f /etc/nginx/sites-enabled/default \
    && rm -f /etc/nginx/sites-available/default \
    && chmod +x /start.sh

EXPOSE 80

CMD ["/start.sh"]
