# Skating Analyzer

AI-powered figure skating training analysis system built with React, FastAPI, and Docker.

[Chinese README](./README.zh.md) | [Contributing](./CONTRIBUTING.md) | [License](./LICENSE) | [Screenshot Guide](./SCREENSHOT_GUIDE.md)

## Overview

Skating Analyzer helps skaters and coaches upload training videos, extract motion frames, run pose estimation, generate biomechanics metrics, create AI-assisted reports, and track training progress through plans, archives, and skill trees.

## Recent Updates

The latest update expands the video analysis pipeline and deployment configuration:

- Dual-path vision analysis with frame-based and video-aware provider flows
- Target lock and bounding-box tracking for more stable skater selection
- Pose smoothing, phase voting, and cross-validation between pose signals and AI vision results
- Jump feature extraction with FPS-aware timing and rotation unwrap handling
- Frame annotation output for clearer review and debugging
- Provider retry handling, vision content normalization, and cost-limit settings
- Video precheck and nginx upload limits for larger review files
- Expanded backend regression tests for tracking, smoothing, dual-path vision, reports, provider retry, and plan generation

## Features

- Video upload with async analysis pipeline
- Motion frame sampling and MediaPipe pose detection
- Optional phase-2 multi-pose tracking with MediaPipe task models
- Biomechanics metrics, phase smoothing, and structured scoring
- Dual-path AI vision analysis with fallback handling
- AI-generated training reports and training plan generation
- Stage-aware retry flow with cached frame reuse
- Processing logs, pipeline timing, and in-report debug visibility
- Automatic stale-task recovery and safer failure handling
- Blur filtering and video precheck before vision encoding
- Child mode and parent mode experiences
- Skill tree, training plan, archive, and progress tracking
- Docker all-in-one deployment

## Tech Stack

- Frontend: React 18, TypeScript, Vite, Tailwind CSS, React Router, Recharts
- Backend: FastAPI, SQLAlchemy Async, SQLite
- Vision and media: FFmpeg, OpenCV, MediaPipe
- AI integration: OpenAI SDK-compatible providers for vision and text
- Deployment: Docker, nginx

## Project Structure

```text
skating-analyzer/
|-- backend/                  # FastAPI backend
|   |-- app/
|   |   |-- configs/          # action profile and prompt configuration
|   |   |-- routers/          # API routes
|   |   |-- services/         # analysis, report, provider, vision, pose services
|   |   |-- main.py
|   |   |-- models.py
|   |   `-- schemas.py
|   |-- tests/                # backend regression tests
|   `-- requirements.txt
|-- frontend/                 # React frontend
|   |-- src/
|   `-- public/
|-- docker/
|   `-- allinone/             # all-in-one image build config
|-- ai_skating_analysis_pack/ # standalone analysis reference pack
|-- data/                     # runtime data, ignored by Git
|-- backups/                  # backup db files, ignored by Git
|-- models/                   # local model files, ignored by Git
|-- .env.example
|-- docker-compose.yml
`-- README.md
```

## Environment Variables

Copy `.env.example` to `.env` and fill in your own credentials:

```bash
cp .env.example .env
```

Example:

```bash
QWEN_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
QWEN_VISION_MODEL=qwen-vl-max-latest
QWEN_VISION_DAILY_COST_LIMIT_CNY=30
QWEN_VISION_VIDEO_ESTIMATED_COST_CNY=0.6
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
SECRET_KEY=replace-with-a-random-32-char-secret

# Optional: enable phase-2 multi-pose tracking
# MEDIAPIPE_POSE_TASK_PATH=/models/pose_landmarker_heavy.task
# POSE_NUM_POSES=4
```

Notes:

- `.env` is not tracked by Git.
- `.env.example` keeps placeholders only.
- Runtime databases, uploaded videos, backups, Docker tar archives, and local model files are not committed.

## Phase-2 Pose Model

Phase-2 multi-pose tracking is enabled through a host-mounted MediaPipe `.task` model file.

- Put the model file under `./models`, for example `./models/pose_landmarker_heavy.task`.
- Set `MEDIAPIPE_POSE_TASK_PATH=/models/pose_landmarker_heavy.task` in `.env`.
- Optionally set `POSE_NUM_POSES=4`.
- The `.task` file is not committed to this repository.
- If the model is missing or cannot be loaded, the backend automatically falls back to the phase-1 single-person pose pipeline.

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

## Testing

Backend regression tests cover the newer pipeline and heuristics, including:

- analysis profile inference from user input
- stage retry and pipeline version behavior
- blur filtering, video precheck, and vision fallback handling
- bbox tracking, target lock, pose smoothing, and phase voting
- dual-path vision and report generation
- provider retry and vision content normalization
- biomechanics normalization, jump timing, and rotation estimation
- training plan generation

Run backend tests:

```bash
cd backend
pytest tests
```

Build the frontend:

```bash
cd frontend
npm run build
```

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

- If you run all-in-one with a mounted `.env`, make sure it contains `MEDIAPIPE_POSE_TASK_PATH=/models/pose_landmarker_heavy.task`.
- If you configure environment variables directly in NAS or Container Manager, mounting `.env` is optional, but you still need the same environment variable and the mounted `models` directory.
- Older analysis rows that still store Windows absolute paths automatically fall back to `/data/uploads/<analysis_id>/source.*` when the all-in-one container resolves the original video.

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

- Runtime data is stored under `./data`.
- Uploaded videos and extracted frames are not committed.
- API keys are stored through in-app encryption.
- Only `.env.example` should be shared publicly.

## Repository Notes

This repository does not include:

- Real API keys
- Local databases
- Training videos or extracted media assets
- Exported Docker tar archives
- Local model weights
- Local worktree metadata such as `.claude/`
- Deliverable packaging artifacts

## Open Source Extras

- Cover copy: [REPO_COVER_COPY.md](./REPO_COVER_COPY.md)
- GitHub about/topics copy: [GITHUB_PROFILE_COPY.md](./GITHUB_PROFILE_COPY.md)
- Screenshot planning: [SCREENSHOT_GUIDE.md](./SCREENSHOT_GUIDE.md)
- Release body draft: [RELEASE_BODY_v1.0.0.md](./RELEASE_BODY_v1.0.0.md)

## License

MIT
