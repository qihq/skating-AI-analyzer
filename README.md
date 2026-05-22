# Skating Analyzer

AI-powered figure skating training analysis system built with React, FastAPI, and Docker.

[Chinese README](./README.zh.md) | [Contributing](./CONTRIBUTING.md) | [License](./LICENSE) | [Screenshot Guide](./SCREENSHOT_GUIDE.md)

## Overview

Skating Analyzer helps skaters and coaches upload training videos, extract motion frames, run pose estimation, generate biomechanics metrics, create AI-assisted reports, and track training progress through plans, archives, and skill trees.

## Current Video Analysis Pipeline

The system implements a 10-stage end-to-end pipeline from raw video to structured ISU-aligned report:

```
Video Upload → Precheck → Video AI Temporal Localization → Action Window Detection
    → Motion-Weighted Frame Sampling → Target Lock → Pose Estimation
    → Profile Inference → Biomechanics → Timestamp Arbitration + Semantic Keyframe Extraction
    → Dual-Path Vision Analysis → LLM Report Fusion → Score Fusion
```

### Stage 1-1A: Upload & Video AI Semantic Temporal Localization

- Accepts mp4/mov/avi, validates magic bytes, codec, resolution, and blank-frame check
- **Video AI** (`qwen3.6-plus`) analyzes the full video to produce `phase_segments` (approach/preparation/takeoff/air/landing/glide_out), action confirmation, T/A/L timestamp hints, and macro assessment
- Cost-controlled via daily budget (`QWEN_VISION_DAILY_COST_LIMIT_CNY`) and per-call estimate

### Stage 2-3: Action Window Detection & Motion-Weighted Sampling

- 2fps thumbnail extraction → frame-difference motion density curve
- Profile-aware sliding window: jump=3s, spin=5s, step=8s, spiral=6s (stability-optimized)
- Motion-weighted sampling: top-3 local peak neighborhoods protected, remaining quota distributed by segment motion weight
- Slow-motion videos (≥60fps) are scaled back to real-time timeline before window selection

### Stage 4-5: Target Lock & Pose Estimation

- Multi-person detection via motion-based bbox candidates with IoU/center-distance/scale continuity scoring
- Confidence ≥0.72 auto-locks; below triggers manual selection on frontend
- MediaPipe 33-point 3D pose extraction (single or multi-pose mode with `.task` model)
- Pose smoothing, phase voting, and cross-validation between skeleton signals and AI vision

### Stage 6-7: Profile Inference & Biomechanics

- Automatic profile inference (jump/spin/step/spiral) from COM vertical range, motion scores, and user hint
- Knee angles, trunk tilt, arm symmetry, jump height (`h=0.5g(t/2)²`), rotation speed
- Sub-scores: takeoff_power, rotation_axis, arm_coordination, landing_absorption, core_stability

### Stage 7A: Timestamp Arbitration & Semantic Keyframe Extraction

- Three-way arbitration: video AI phase intervals + motion density peaks + skeleton T/A/L candidates
- Confidence-gated: ≥0.80 use video timestamps (refined), ≥0.55 blended, <0.55 skeleton fallback
- FFmpeg precise extraction at resolved timestamps → `semantic_0001.jpg` etc.
- Local motion-peak refinement for T/L frames (±0.18s window at source fps)

### Stage 8: Dual-Path Vision Analysis

- **Path A** (frame-based): semantic keyframes → multimodal LLM with `video_context` per frame → phase verification
- **Path B** (video-aware): action-window clip → native video model → structured output
- Cross-validation fusion with configurable blend weights; conflict detection between paths
- Per-frame output includes `phase_verification` (agree/shifted/disagree/uncertain) against video AI context

### Stage 9-10: Report Generation & Score Fusion

- LLM synthesizes vision analysis + biomechanics + athlete memory → structured training report
- Force Score: `ai_score × 0.4 + bio_score × 0.6`, weighted by sub-component importance
- Full debug trace: pipeline timing, provider metrics, quality flags, frame annotations

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Video AI as semantic layer, not frame judge | Avoids hallucinated per-frame labels; provides phase intervals for arbitration |
| Motion-peak neighborhood protection | Ensures takeoff/landing frames are never sampled away |
| Dual-path with cross-validation | Single-path LLM analysis is unreliable; fusion catches errors |
| Confidence-gated timestamp arbitration | Prevents low-quality video AI from corrupting frame extraction |
| Profile-aware sampling rates | Jumps need 16fps (fast motion), spirals need 8fps (slow sustained) |

See [docs/ai-analysis-flow.md](./docs/ai-analysis-flow.md) for the full 10-stage pipeline documentation.

## Recent Updates

The latest update expands the video analysis pipeline and deployment configuration:

- **Pipeline v5.1.0**: dedicated Pose Debug replay page with responsive mobile, iPad, web, and PWA-safe layouts
- Larger debug-mode skeleton replay with current-frame bbox, tracking confidence, candidate counts, pose diagnostics, tracking thumbnails, and biomechanics key-frame sync
- Settings runtime checks are split: pose model status and YOLO tracker status now have independent refresh buttons, loading states, timestamps, and errors
- Video AI semantic temporal localization with Qwen 3.6 Plus (`qwen3.6-plus`)
- Timestamp arbitration before FFmpeg frame extraction: video phase interval + motion density + skeleton candidates
- Semantic keyframe image analysis with per-frame `video_context`
- Dual-path vision analysis with frame-based and video-aware provider flows
- Target lock and bounding-box tracking for more stable skater selection
- YOLO + ByteTrack person tracking with mounted `yolov8n.pt` support and settings-page runtime status
- In-report Pose Replay can open `/report/:id/pose-debug` for expanded skeleton and tracker debugging
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
- Blur filtering and profile-aware frame sampling for more stable vision input
- Standalone `skating_vision` package for reuse outside the main app
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
├─ skating_vision/           # standalone vision analysis Python package
├─ docs/
│  └─ ai-analysis-flow.md   # full 10-stage pipeline documentation
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
- `.env.example` keeps placeholders only.
- The default vision model is `qwen3.6-plus`. `qwen-vl-max-latest` is kept only as a legacy migration input and is no longer recommended as a default.
- `QWEN_VISION_DAILY_COST_LIMIT_CNY` caps daily vision spend, `QWEN_VISION_VIDEO_ESTIMATED_COST_CNY` estimates one video-temporal call, and `VIDEO_TEMPORAL_MAX_FRAMES` caps semantic frames sent to image AI.
- Runtime databases, uploaded videos, backups, Docker tar archives, and local model files are not committed.

## Phase-2 Pose Model

Phase-2 multi-pose and person tracking use host-mounted model files.

- Put the model file under `./models`, for example `./models/pose_landmarker_heavy.task`.
- Set `MEDIAPIPE_POSE_TASK_PATH=/models/pose_landmarker_heavy.task` in `.env`.
- Optionally set `POSE_NUM_POSES=4`.
- For YOLO person tracking, put `yolov8n.pt` under `./models` and optionally set `YOLO_PERSON_MODEL_PATH=/models/yolov8n.pt`. If the variable is not set, the backend checks `/models/yolov8n.pt` before allowing Ultralytics to download `yolov8n.pt`.
- The Settings page shows pose runtime and YOLO runtime status separately, with independent recheck buttons so one check no longer blocks or reloads the other.
- Model files are not committed to this repository.
- If the model is missing or cannot be loaded, the backend automatically falls back to the phase-1 single-person pose pipeline.

## skating_vision Package

The `skating_vision` directory is a standalone Python package that extracts the core analysis modules for use outside the main FastAPI app. It provides:

- **video** — frame extraction, motion sampling, action window detection, blur filtering
- **pose** — MediaPipe pose extraction with multi-candidate fallback
- **biomechanics** — geometric heuristic metrics, jump rotation estimation
- **vision** — LLM-based frame-by-frame visual analysis
- **report** — structured report generation and score fusion
- **providers** — OpenAI SDK-compatible provider abstraction
- **target_lock** — primary skater candidate locking
- **action_profiles** — profile inference for jump, spin, spiral, and step sequences

Install as a local package or import directly:

```python
from skating_vision.video import extract_motion_sampled_frames
from skating_vision.pose import extract_pose
from skating_vision.biomechanics import analyze_biomechanics
from skating_vision.report import generate_report
```

See [docs/ai-analysis-flow.md](./docs/ai-analysis-flow.md) for the full 10-stage pipeline documentation.

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

- If you run all-in-one with a mounted `.env`, make sure it contains `MEDIAPIPE_POSE_TASK_PATH=/models/pose_landmarker_heavy.task` and, when using mounted YOLO weights, `YOLO_PERSON_MODEL_PATH=/models/yolov8n.pt`.
- If you configure environment variables directly in NAS or Container Manager, mounting `.env` is optional, but you still need the same environment variable and the mounted `models` directory.
- Older analysis rows that still store Windows absolute paths automatically fall back to `/data/uploads/<analysis_id>/source.*` when the all-in-one container resolves the original video.

Export:

```powershell
.\scripts\export-allinone-image.ps1
```

The export script rebuilds `skating-analyzer-allinone:latest` and writes a timestamped `v5.1.0` tar file under `./deliverables`.

## Main Screens

- `/path`: skill tree and learning path
- `/review`: upload and analyze training videos
- `/report/:id`: analysis report
- `/report/:id/pose-debug`: expanded pose replay, tracking diagnostics, and biomechanics debug page
- `/archive`: training archive and progress
- `/plan/:plan_id`: training plan
- `/snowball`: assistant chat and memory suggestions
- `/settings`: settings, PIN, backups, provider management, separate pose and YOLO runtime status checks
- `/debug`: analysis debug logs with auto-refresh for the latest analysis state

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
- AI analysis flow: [docs/ai-analysis-flow.md](./docs/ai-analysis-flow.md)
- Deep review & iteration plan: [docs/video-analysis-deep-review.md](./docs/video-analysis-deep-review.md)
- Iteration guide: [video-analysis-iteration-guide.md](./video-analysis-iteration-guide%20(1).md)

## License

MIT
