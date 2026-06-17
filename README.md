# Skating Analyzer

AI-assisted figure skating training review for skaters, parents, and coaches. The app combines video prechecks, target tracking, pose estimation, video-temporal AI, dual-path vision analysis, and structured reports into a local-first training workflow.

[中文说明](./README.zh.md) | [Contributing](./CONTRIBUTING.md) | [License](./LICENSE) | [Screenshot Guide](./SCREENSHOT_GUIDE.md)

## Current Status

- Current analysis pipeline: `v5.2.303`.
- Primary branch: `master`.
- Runtime data, uploads, extracted frames, backups, local models, and exported Docker archives are intentionally excluded from Git.
- AI keys are optional at startup. Configure providers in the app at `/settings/api` after setting `SECRET_KEY`.

## What It Does

- Upload and analyze skating videos from `/review`.
- Accept broad action categories when the exact element is unknown; skill category is optional.
- Carry user notes into the earliest video-temporal action-recognition prompt.
- Let parents manually choose an AI input window for longer videos.
- Lock onto the target skater with preview candidates, manual bbox selection, YOLO/ByteTrack tracking, and identity-safety gates.
- Extract MediaPipe pose, smooth signals, compute biomechanics, and estimate jump/rotation evidence.
- Use Qwen-compatible video temporal localization for action family and semantic phase timing.
- Extract semantic keyframes with FFmpeg when they pass reliability checks.
- Run dual-path vision analysis:
  - Path A: pure visual/video-aware analysis.
  - Path B: skeleton-overlaid frames and biomechanics grounding.
- Generate structured reports, Force Score, training plans, skill progress, archive timelines, debug logs, and shareable parent report images.

## Video Analysis Pipeline

The current pipeline is organized around source-video timestamps and a clearly recorded AI input window:

```text
upload
  -> video precheck and input-window resolution
  -> motion sampling and action-window metadata
  -> target preview or manual target selection
  -> YOLO/ByteTrack tracking and MediaPipe pose extraction
  -> biomechanics, jump features, and keyframe candidates
  -> video-temporal AI with user notes
  -> semantic keyframe arbitration, retry, repair, and FFmpeg extraction
  -> Path A / Path B vision analysis
  -> report fusion, score fusion, training plan, archive, and debug output
```

Important behavior:

- Manual start/end seconds are used when provided; otherwise the backend keeps full-context input where possible and records any system truncation.
- Video AI provides semantic timing and macro interpretation. It does not become a trusted frame judge by itself.
- Semantic keyframes are rejected or downgraded when T/A/L order, visibility, motion support, skeleton candidates, or retry checks are unreliable.
- Manual target locks are identity-authoritative. If tracker diagnostics cannot support the selected skater, the pipeline fails closed instead of drawing a wrong skeleton.

Full module details live in [docs/ai-analysis-flow.md](./docs/ai-analysis-flow.md). Design tradeoffs and next iteration priorities live in [docs/video-analysis-deep-review.md](./docs/video-analysis-deep-review.md).

## Project Structure

```text
skating-analyzer/
|-- backend/                  # FastAPI app, analysis orchestration, tests
|-- frontend/                 # React + Vite UI
|-- docker/allinone/          # single-container Docker image files
|-- docs/                     # current pipeline and review docs
|-- skating_vision/           # standalone vision-analysis package
|-- ai_skating_analysis_pack/ # reference pack and experiments
|-- scripts/                  # diagnostics, batch analysis, exports, backups
|-- data/                     # runtime data, ignored by Git
|-- backups/                  # runtime backups, ignored by Git
|-- models/                   # local MediaPipe/YOLO weights, ignored by Git
|-- deliverables/             # exported images/tars, ignored by Git
|-- .env.example
|-- docker-compose.yml
`-- README.md
```

## Configuration

Copy `.env.example` to `.env` and set at least `SECRET_KEY`:

```bash
cp .env.example .env
```

Common variables:

```bash
SECRET_KEY=replace-with-a-random-32-char-secret

# Optional AI provider defaults or environment-key fallback.
# Prefer configuring model instances in /settings/api after startup.
# QWEN_API_KEY=sk-...
# DASHSCOPE_API_KEY=sk-...
QWEN_VISION_MODEL=qwen3.6-plus
QWEN_VISION_DAILY_COST_LIMIT_CNY=30
QWEN_VISION_VIDEO_ESTIMATED_COST_CNY=0.6
# VIDEO_TEMPORAL_MAX_FRAMES=12

# Optional local model mounts.
# MEDIAPIPE_POSE_TASK_PATH=/models/pose_landmarker_heavy.task
# POSE_NUM_POSES=4
# YOLO_PERSON_MODEL_PATH=/models/yolov8n.pt
```

Provider notes:

- Backend startup no longer seeds provider rows automatically.
- Use `/settings/api` to create and activate providers for `report`, `vision`, `vision_path_a`, and `vision_path_b`.
- Existing NAS databases with legacy provider rows can keep working; duplicate old rows should not block startup.
- `SECRET_KEY` is required because saved provider keys are encrypted in the app database.

## Local Development

Backend:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
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

## Docker

Compose:

```bash
docker compose up --build
```

All-in-one image:

```bash
docker build -f docker/allinone/Dockerfile -t skating-analyzer-allinone:latest .
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

Keep `data`, `backups`, and `models` mounted on the host so runtime data and model files do not get baked into images.

## Testing

Backend:

```bash
cd backend
pytest tests
```

Frontend:

```bash
cd frontend
npm run build
```

The regression suite covers stage retry, profile inference, broad-category uploads, user notes in prompts, video temporal resolution, semantic keyframes, target lock, person tracking, pose smoothing, dual-path vision, provider fallback, report fusion, training plans, and debug flows.

## Main Screens

- `/review`: upload video, choose skater/action context, optionally set manual AI input window.
- `/report/:id`: report, score, issues, improvements, plan entry, share image, retry/delete controls.
- `/report/:id/pose-debug`: skeleton replay and tracker diagnostics.
- `/archive`: training archive and paginated timeline.
- `/plan/:plan_id`: training plan.
- `/settings/api`: provider slots and API key management.
- `/debug`: debug-run replay, pipeline logs, semantic frames, AI input windows, and raw diagnostics.

## Privacy

- Runtime data defaults to `./data`.
- Uploaded videos and extracted media are not committed.
- API keys are encrypted in the app database.
- Only `.env.example` should be shared publicly.

## License

MIT
