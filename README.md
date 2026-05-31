# Skating Analyzer

AI-powered figure skating training analysis system built with React, FastAPI, MediaPipe, YOLO/ByteTrack, and Docker.

[Chinese README](./README.zh.md) | [Contributing](./CONTRIBUTING.md) | [License](./LICENSE) | [Screenshot Guide](./SCREENSHOT_GUIDE.md)

## Overview

Skating Analyzer helps skaters, parents, and coaches review training videos with a repeatable analysis pipeline. The app uploads a video, samples motion frames, locks onto the target skater, runs pose and person tracking, resolves takeoff/apex/landing moments, calls AI vision models when configured, and turns the results into reports, plans, archives, and progress views.

The current pipeline version is `v5.2.9`.

## Recent Updates

The latest release focuses on making dual-path AI output more resilient and keeping reports actionable when one AI path returns malformed JSON.

- `v5.2.9`: Path A now requests stricter JSON, recovers malformed model output, retries a JSON-only repair pass, and reports fall back to Path B/top-issue evidence with action-specific drills.
- `v5.2.8`: reused lost tracker boxes can be used as padded pose crop hints for distant tiny skaters.
- `v5.2.7`: tracker-style crop padding is applied to overlap-safe rejected tracker hints when they become reference boxes.
- `v5.2.6`: overlap-safe continuity-rejected tracker boxes can be reused as pose crop hints without accepting identity switches.
- `v5.2.5`: regular pose crops are validated against their actual reference bbox when motion-predicted crops are attempted.
- `v5.2.4`: ordered visible T/A/L candidates are kept complete while preserving low-confidence warnings.
- `v5.2.3`: unconfirmed but gated tracker relock boxes can guide pose crops without switching the target identity.
- `v5.2.2`: tracker-aligned crop poses are preserved during fast target motion instead of over-penalizing seed-bbox drift.
- `v5.2.1`: jump action-window padding is tighter and target preview anchors prefer high-motion sampled frames.
- `v5.2.0`: debug replay mirrors the formal sampling pipeline and excludes unreliable pose frames from keyframe scoring.

## Core Features

- Video upload with asynchronous analysis and stage-aware retry.
- Motion sampling, video precheck, blur filtering, and larger nginx upload limits.
- Target preview, manual target lock, YOLO + ByteTrack person tracking, and per-frame bbox diagnostics.
- MediaPipe pose extraction with smoothing, multi-candidate handling, and crop fallback logic.
- Biomechanics metrics for phase timing, jump evidence, rotation estimation, and pose quality.
- Qwen 3.6 Plus video temporal localization for semantic takeoff/apex/landing intervals.
- Semantic keyframe extraction with timestamp arbitration across video AI, motion density, and skeleton candidates.
- Dual-path vision analysis with video-aware context, provider fallback, malformed-JSON recovery, retry handling, and cost limits.
- AI-assisted reports, training plans, skill tree, archive, progress tracking, child mode, and parent mode, with Path B-grounded fallback issues and action-specific drills.
- Pose Debug and Debug pages for replay, tracker thumbnails, candidate counts, pose diagnostics, timings, and logs.
- Docker Compose and all-in-one Docker deployment for NAS or local single-container use.

## Analysis Pipeline

1. Upload the source video and create an analysis record.
2. Run video precheck, motion sampling, and action-window detection.
3. Build target preview candidates and wait for manual selection when confidence is low.
4. Track the selected skater with YOLO/ByteTrack and per-frame bbox continuity checks.
5. Extract pose landmarks from regular, tracker-guided, and fallback crops.
6. Smooth pose signals and compute biomechanics, jump features, and keyframe candidates.
7. Run video-temporal AI when configured and resolve semantic T/A/L timestamps.
8. Extract semantic keyframes with FFmpeg and pass video context to image AI.
9. Fuse pose, biomechanics, video AI, Path A pure vision, and Path B skeleton-grounded evidence into structured report data.
10. Persist frames, logs, timings, debug summaries, and retry checkpoints.

## Tech Stack

- Frontend: React 18, TypeScript, Vite, Tailwind CSS, React Router, Recharts.
- Backend: FastAPI, SQLAlchemy Async, SQLite, APScheduler.
- Vision and media: FFmpeg, OpenCV, MediaPipe, YOLO/ByteTrack, PyTorch CPU.
- AI integration: OpenAI SDK-compatible providers for text, image, and video-aware vision flows.
- Deployment: Docker, nginx, Docker Compose, all-in-one container image.

## Project Structure

```text
skating-analyzer/
|-- backend/                  # FastAPI backend
|   |-- app/
|   |   |-- configs/          # action profiles and provider configuration
|   |   |-- routers/          # API routes
|   |   |-- services/         # analysis, pose, tracking, vision, report, skill services
|   |   |-- main.py
|   |   |-- models.py
|   |   `-- schemas.py
|   |-- tests/                # backend regression tests
|   `-- requirements.txt
|-- frontend/                 # React frontend
|   |-- src/
|   `-- public/
|-- docker/
|   `-- allinone/             # all-in-one image Dockerfile, nginx config, start script
|-- docs/                     # pipeline documentation
|-- skating_vision/           # standalone vision-analysis package
|-- ai_skating_analysis_pack/ # standalone reference pack
|-- scripts/                  # diagnostics, batch analysis, image export
|-- data/                     # runtime data, ignored by Git
|-- backups/                  # runtime backups, ignored by Git
|-- models/                   # local model weights, ignored by Git
|-- deliverables/             # exported image files, ignored by Git
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
QWEN_VISION_MODEL=qwen3.6-plus
QWEN_VISION_DAILY_COST_LIMIT_CNY=30
QWEN_VISION_VIDEO_ESTIMATED_COST_CNY=0.6
# VIDEO_TEMPORAL_MAX_FRAMES=12
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
SECRET_KEY=replace-with-a-random-32-char-secret

# Optional: enable phase-2 multi-pose tracking
# MEDIAPIPE_POSE_TASK_PATH=/models/pose_landmarker_heavy.task
# POSE_NUM_POSES=4

# Optional: use a mounted YOLO person detector weight instead of runtime download
# YOLO_PERSON_MODEL_PATH=/models/yolov8n.pt
```

Notes:

- `.env` is not tracked by Git.
- The default vision model is `qwen3.6-plus`; `qwen-vl-max-latest` is only kept as legacy migration input.
- `QWEN_VISION_DAILY_COST_LIMIT_CNY` caps daily vision spend.
- `QWEN_VISION_VIDEO_ESTIMATED_COST_CNY` estimates one video-temporal call.
- `VIDEO_TEMPORAL_MAX_FRAMES` caps semantic frames sent to image AI.
- Runtime databases, uploaded videos, extracted frames, backups, Docker tar archives, and local model files are not committed.

## Dual-Path Report Resilience

The analysis pipeline stores both `vision_path_a` and `vision_path_b` for audit and debugging.

- Path A is pure visual judgment. It now asks providers for JSON-object output, extracts valid JSON from noisy responses, and performs one low-temperature JSON repair pass before marking Path A unavailable.
- Path B uses skeleton-overlaid frames and biomechanics. Its `top_issues`, `top_positives`, phase summary, and frame-level issues are injected into the report context.
- If Path A fails or the report model returns generic items, the backend replaces weak “data quality” placeholders with Path B-grounded issues and action-specific drills for jump, spin, spiral, and step profiles.
- The report still keeps `data_quality=partial` when evidence is incomplete, but the issue list and improvements should remain tied to visible/quantified technical findings.

## Local Models

Phase-2 multi-pose and person tracking use host-mounted model files.

- Put MediaPipe task files under `./models`, for example `./models/pose_landmarker_heavy.task`.
- Set `MEDIAPIPE_POSE_TASK_PATH=/models/pose_landmarker_heavy.task` in `.env`.
- Optionally set `POSE_NUM_POSES=4`.
- Put YOLO weights under `./models`, for example `./models/yolov8n.pt`.
- Optionally set `YOLO_PERSON_MODEL_PATH=/models/yolov8n.pt`.
- If `YOLO_PERSON_MODEL_PATH` is not set, the backend checks `/models/yolov8n.pt` before allowing Ultralytics to download `yolov8n.pt`.
- The Settings page shows pose runtime and YOLO runtime status separately.
- If a model is missing or cannot be loaded, the backend falls back to the safer available pipeline.

## skating_vision Package

The `skating_vision` directory is a standalone Python package that extracts core analysis modules for reuse outside the FastAPI app.

- `video`: frame extraction, motion sampling, action-window detection, blur filtering.
- `pose`: MediaPipe pose extraction with multi-candidate fallback.
- `biomechanics`: geometric metrics and jump rotation estimation.
- `vision`: LLM-based visual analysis.
- `report`: structured report generation and score fusion.
- `providers`: OpenAI SDK-compatible provider abstraction.
- `target_lock`: primary skater candidate locking.
- `action_profiles`: profile inference for jumps, spins, spirals, and step sequences.

```python
from skating_vision.video import extract_motion_sampled_frames
from skating_vision.pose import extract_pose
from skating_vision.biomechanics import analyze_biomechanics
from skating_vision.report import generate_report
```

See [docs/ai-analysis-flow.md](./docs/ai-analysis-flow.md) for the full pipeline documentation.

## Local Development

Backend:

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

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Default URLs:

- Frontend: `http://localhost:5173`
- Backend: `http://localhost:8000`
- Health: `http://localhost:8000/api/health`

## Testing

Backend regression tests cover:

- profile inference from user input
- stage retry and pipeline version behavior
- debug-run persistence and replay flows
- video precheck, precise extraction, and semantic temporal resolution
- bbox tracking, target lock, person tracking, and pose smoothing
- keyframe candidates, T/A/L ordering, and biomechanics timing
- dual-path vision, malformed Path A JSON recovery, provider retry, report fusion, and content normalization

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

## Docker Compose

```bash
docker compose up --build
```

If phase-2 pose or YOLO tracking is needed, place model files under `./models` before starting Docker Compose.

Default URLs:

- App: `http://localhost:8080`
- API health: `http://localhost:8000/api/health`

## All-in-one Image

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

Export:

```powershell
.\scripts\export-allinone-image.ps1
```

The export script rebuilds `skating-analyzer-allinone:latest`, reads the current pipeline version from `backend/app/services/pipeline_version.py`, and writes a timestamped tar file under `./deliverables`.

All-in-one notes:

- If `.env` is mounted, include `MEDIAPIPE_POSE_TASK_PATH=/models/pose_landmarker_heavy.task` when using the MediaPipe task model.
- Include `YOLO_PERSON_MODEL_PATH=/models/yolov8n.pt` when using mounted YOLO weights.
- If environment variables are configured directly in NAS or Container Manager, mounting `.env` is optional.
- `data`, `backups`, and `models` should remain host-mounted volumes so runtime data and model files are not baked into the image.
- Older analysis rows that still store Windows absolute paths fall back to `/data/uploads/<analysis_id>/source.*` inside the all-in-one container.

## Image Size Notes

The all-in-one image is intentionally larger than the split frontend image because it includes the backend, frontend, FFmpeg, nginx, MediaPipe, OpenCV, PyTorch CPU, Ultralytics YOLO, and tracking dependencies.

Recent inspection of `skating-analyzer-allinone:latest` showed:

- Docker image size: about `3.72GB`.
- Largest image layer: Python dependencies from `pip install`, about `2.25GB`.
- System media/server layer: `ffmpeg`, `nginx`, and `curl`, about `467MB`.
- Largest Python packages: `torch` about `724MB`, `jaxlib` about `330MB`, `scipy` about `113MB`, OpenCV packages/libs about `337MB` combined, and `mediapipe` about `66MB`.
- `tmp/` diagnostics can make Docker build context and Git history noisy, but the all-in-one Dockerfile copies only `backend/app`, `backend/requirements.txt`, `frontend`, and `docker/allinone` files into the final image. `tmp/` is now ignored by Git and Docker build context.

## Main Screens

- `/path`: skill tree and learning path.
- `/review`: upload and analyze training videos.
- `/report/:id`: analysis report.
- `/report/:id/pose-debug`: expanded skeleton replay and tracker diagnostics.
- `/archive`: training archive and progress.
- `/plan/:plan_id`: training plan.
- `/snowball`: assistant chat and memory suggestions.
- `/settings`: PIN, backups, providers, cost limits, pose runtime, and YOLO runtime checks.
- `/debug`: analysis debug logs and debug-run replay.

## Privacy

- Runtime data is stored under `./data`.
- Uploaded videos and extracted frames are not committed.
- API keys are stored through in-app encryption.
- Only `.env.example` should be shared publicly.

## Repository Notes

This repository does not include:

- real API keys
- local databases
- training videos or extracted media assets
- exported Docker tar archives
- local model weights
- local worktree metadata
- temporary diagnostics and deliverable packaging artifacts

## Open Source Extras

- Cover copy: [REPO_COVER_COPY.md](./REPO_COVER_COPY.md)
- GitHub about/topics copy: [GITHUB_PROFILE_COPY.md](./GITHUB_PROFILE_COPY.md)
- Screenshot planning: [SCREENSHOT_GUIDE.md](./SCREENSHOT_GUIDE.md)
- Release body draft: [RELEASE_BODY_v1.0.0.md](./RELEASE_BODY_v1.0.0.md)
- AI analysis flow: [docs/ai-analysis-flow.md](./docs/ai-analysis-flow.md)
- Iteration guide: [video-analysis-iteration-guide.md](./video-analysis-iteration-guide%20(1).md)

## License

MIT
