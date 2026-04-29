# Skating Analyzer

AI-powered figure skating training analysis system built with React, FastAPI, and Docker.

[中文说明](./README.zh.md)

[Contributing](./CONTRIBUTING.md) · [License](./LICENSE) · [Screenshot Guide](./SCREENSHOT_GUIDE.md)

## Banner

Add your repository social preview or hero banner here after screenshots are ready.

```md
![Skating Analyzer banner](./docs/banner-placeholder.png)
```

## Overview

Skating Analyzer is a full-stack application for uploading training videos, extracting motion frames, running pose estimation, generating biomechanics metrics, creating AI-assisted reports, and tracking athlete progress through plans, archives, and skill trees.

## Features

- Video upload with async analysis pipeline
- Motion frame sampling and MediaPipe pose detection
- Biomechanics metrics and structured scoring
- AI-generated training reports
- Child mode and parent mode experiences
- Skill tree, training plan, archive, and progress tracking
- Docker all-in-one deployment

## Screenshots

Replace these placeholders with actual product screenshots.

```md
![Skill tree](./docs/screenshots/skill-tree.png)
![Review upload flow](./docs/screenshots/review-flow.png)
![Report page](./docs/screenshots/report-page.png)
![Archive](./docs/screenshots/archive.png)
```

## Tech Stack

- Frontend: React 18, TypeScript, Vite, Tailwind CSS, React Router, Recharts
- Backend: FastAPI, SQLAlchemy Async, SQLite
- Vision and media: FFmpeg, OpenCV, MediaPipe
- AI integration: OpenAI SDK-compatible providers for vision and text
- Deployment: Docker, nginx

## Project Structure

```text
skating-analyzer/
├─ backend/                  # FastAPI backend
│  ├─ app/
│  │  ├─ routers/            # API routes
│  │  ├─ services/           # analysis, report, provider, skill services
│  │  ├─ main.py
│  │  ├─ models.py
│  │  └─ schemas.py
│  └─ requirements.txt
├─ frontend/                 # React frontend
│  ├─ src/
│  └─ public/
├─ docker/
│  └─ allinone/              # all-in-one image build config
├─ data/                     # runtime data (ignored)
├─ backups/                  # backups (db files ignored)
├─ .env.example
├─ docker-compose.yml
└─ README.md
```

## Environment Variables

Copy `.env.example` to `.env` and fill in your own credentials:

```bash
cp .env.example .env
```

Example:

```bash
QWEN_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
SECRET_KEY=replace-with-a-random-32-char-secret
# Optional: enable phase-2 multi-pose tracking
# MEDIAPIPE_POSE_TASK_PATH=/models/pose_landmarker_heavy.task
# POSE_NUM_POSES=4
```

Notes:

- `.env` is not tracked by Git
- `.env.example` keeps placeholders only
- Runtime databases, uploaded videos, and backups are not committed

## Phase 2 Pose Model

Phase-2 multi-pose tracking is enabled through a host-mounted MediaPipe `.task` model file.

- Put the model file under `./models`, for example `./models/pose_landmarker_heavy.task`
- Set `MEDIAPIPE_POSE_TASK_PATH=/models/pose_landmarker_heavy.task` in `.env`
- Optionally set `POSE_NUM_POSES=4`
- The `.task` file is not committed to this repository
- If the model is missing or cannot be loaded, the backend automatically falls back to the phase-1 single-person pose pipeline

## Local Development

### Backend

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --no-use-colors
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Default URLs:

- Frontend: `http://localhost:5173`
- Backend: `http://localhost:8000`

## Docker

### docker-compose

```bash
docker compose up --build
```

If you want to enable phase-2 multi-pose tracking, place the model file under `./models` before starting Docker Compose.

Default URLs:

- App: `http://localhost:8080`
- Health: `http://localhost:8080/api/health`

### All-in-one Image

Build:

```bash
docker build -f docker/allinone/Dockerfile -t skating-analyzer-allinone:latest .
```

Run:

```bash
docker run -d \
  --name skating-allinone \
  -p 8080:80 \
  -v "$(pwd)/data:/data" \
  -v "$(pwd)/backups:/backups" \
  -v "$(pwd)/models:/models:ro" \
  -v "$(pwd)/.env:/workspace/.env:ro" \
  skating-analyzer-allinone:latest
```

Notes:

- If you run all-in-one with a mounted `.env`, make sure it contains `MEDIAPIPE_POSE_TASK_PATH=/models/pose_landmarker_heavy.task`
- If you configure environment variables directly in NAS / Container Manager, mounting `.env` is optional, but you still need the same environment variable and the mounted `models` directory
- Older analysis rows that still store Windows absolute paths automatically fall back to `/data/uploads/<analysis_id>/source.*` when the all-in-one container resolves the original video

Export:

```bash
docker save -o skating-analyzer-allinone-latest.tar skating-analyzer-allinone:latest
```

## Main Screens

- `/path`: skill tree and learning path
- `/review`: upload and analyze training videos
- `/report/:id`: analysis report
- `/archive`: training archive and progress
- `/plan/:plan_id`: training plan
- `/snowball`: assistant chat and memory suggestions
- `/settings`: settings, PIN, backups, provider management

## Privacy

- Runtime data is stored under `./data`
- Uploaded videos and extracted frames are not committed
- API keys are stored through in-app encryption
- Only `.env.example` should be shared publicly

## Repository Notes

This repository does not include:

- Real API keys
- Local databases
- Training videos or extracted media assets
- Exported Docker tar archives

## Open Source Extras

- Cover copy: [REPO_COVER_COPY.md](./REPO_COVER_COPY.md)
- GitHub about/topics copy: [GITHUB_PROFILE_COPY.md](./GITHUB_PROFILE_COPY.md)
- Screenshot planning: [SCREENSHOT_GUIDE.md](./SCREENSHOT_GUIDE.md)
- Release body draft: [RELEASE_BODY_v1.0.0.md](./RELEASE_BODY_v1.0.0.md)

## License

MIT
