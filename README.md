# Skating Analyzer

AI-powered figure skating training analysis system built with React, FastAPI, MediaPipe, YOLO/ByteTrack, and Docker.

[Chinese README](./README.zh.md) | [Contributing](./CONTRIBUTING.md) | [License](./LICENSE) | [Screenshot Guide](./SCREENSHOT_GUIDE.md)

## Overview

Skating Analyzer helps skaters, parents, and coaches review training videos with a repeatable analysis pipeline. The app uploads a video, samples motion frames, locks onto the target skater, runs pose and person tracking, resolves takeoff/apex/landing moments, calls AI vision models when configured, and turns the results into reports, plans, archives, and progress views.

The current pipeline version is `v5.2.315`.

## Recent Updates

Current branch updates focus on the Golden labeling workspace, direct progress/archive labeling entry points, versioned release discipline, golden-set evaluation, safer target relock behavior, keyframe arbitration diagnostics, and the debug review loop:

- Exported all-in-one Docker image from `codex/face-identity-target-lock` with face identity model layer, skater face profile API, target diagnostics, parent UI, and profile deletion.
- Completed archive/progress records now expose a direct Golden labeling action that opens `/golden?analysis_id=...`, preselects the matching analysis, and leaves the debug-run panel empty when no replay exists yet.
- Golden entry links now prepare a labelable local-pose debug run automatically: existing runs are reused, and missing runs are created once so parents land directly in the Golden Label panel instead of a setup form.
- Golden sample creation from a historical analysis can now manually override the AI input/keyframe time range; the form preloads the saved manual or detected action window and validates it against the source duration.
- Golden/debug history cards and action controls were tightened for phone, tablet, and desktop so long notes, flags, status chips, and the new labeling entry do not overflow compact screens.
- A standalone `/golden` workspace now gives Golden labeling its own parent-mode entry with labeling history, sample status counts, direct sample selection, and new debug sample creation.
- Golden bbox drawing now works on sampled, semantic, and partial debug frames, disables native image dragging, and uses a natural-aspect overlay coordinate space so target boxes and pose overlays do not drift from the image without stretching portrait or landscape frames.
- Golden labels remain incremental: reopening a sample loads the existing `golden_label.json`, so users can mark keyframes first, return later to add bbox/notes/review flags, and save back into the same manifest entry.
- Development rules now require every GitHub update that ships code, docs, or an all-in-one image to bump `CURRENT_PIPELINE_VERSION`, update README release notes, use versioned commit wording, export with the standard all-in-one script, and start/verify the freshly built local image.
- Debug runs now include a Golden Label tab for marking skater ID, action/profile, stratum, T/A/L or profile-specific keyframes, target bboxes, review flags, and notes from one place.
- Saving a golden label writes `golden_label.json`, a matching prediction snapshot, and a shared `golden_manifest.json` so future algorithm changes can be compared against the exact prediction that existed when the sample was labeled.
- Golden manifests advertise the recommended strata: `single_skater`, `multi_skater`, `small_target`, `occlusion`, and `known_bad_keyframes`; non-recommended or incomplete labels are kept but marked with `label_quality_flags`.
- `backend/scripts/eval_against_gt.py` evaluates manifests with overall and per-stratum summaries, failures, top quality flags, keyframe deltas, bbox IoU identity accuracy, identity switches, and fixed failure tags such as `identity_switch`, `target_lost`, `takeoff_early`, `apex_drift`, and `landing_glideout`.
- Person tracker appearance relock remains opt-in through `PERSON_TRACKER_APPEARANCE_RELOCK=1`; when enabled it records similarity, threshold, decision, candidate bbox, and rejection reasons, and fails closed when no appearance anchor or usable signature is available.
- Jump keyframe resolution now keeps proposal diagnostics across video AI, skeleton candidates, vertical extrema, and motion evidence; vertical extrema are accepted only inside the phase range with enough confidence.
- Final jump T/A/L output is guarded so invalid ordering cannot remain high-confidence: conflicting T/A/L records are marked unreliable, confidence is lowered, and review flags are preserved for downstream UI/report hints.
- The Debug page shows Prediction vs Golden keyframe deltas and target bbox IoU, plus fixed review-flag chips for repeatable error triage.

The previous release focused on mobile target selection, action-aware keyframe handling, clearer share cards, and reliable subscores:

- Mobile manual target selection now supports two-finger pinch zoom up to 4x, panning while zoomed, and one-tap view reset while still saving the original normalized bbox expected by the backend.
- Manual action-window retry can pass `manual_action_window_start_sec` and `manual_action_window_end_sec`; manual windows use denser action-specific sampling for jumps, spins, steps, and spirals, while automatic jump windows keep extra pre-takeoff and landing padding.
- Keyframe evidence is profile-aware: jumps show T/A/L, spins show entry/main/exit, spirals show the hold frame, and step sequences show coverage frames without forcing jump-style keyframe labels.
- Report subscores are now normalized server-side from effective report data, biomechanics subscores, or fallback references, and the UI shows valid subscores regardless of `data_quality` with source labels and `--` for unavailable items.
- Compare pages fall back from report subscores to biomechanics subscores so the "subscore changes" section stays populated when one report lacks fused scores.
- Report and progress-detail share cards include upload comments, the AI response to those comments, and compact subscore bars; comparison share cards intentionally stay comment-free.
- Follow-up share cards now render a concise multi-turn timeline with up to four Q&A/correction-state entries instead of only the latest question and answer.
- Comparison generation now starts as a background task and immediately saves an `analysis_comparisons` record with pending, processing, completed, and failed states.
- The comparison workbench sends the two full source videos only to the active `vision` provider. When `vision=mimo`, it uses the currently active vision model, such as `mimo-v2.5`; when `vision=qwen`, it uses the configured Qwen video model instead of a hidden hard-coded default.
- The `report` provider now receives only structured comparison JSON and writes the parent-readable summary from text data. It is not asked to process videos or use multimodal features.
- Comparison results fuse video AI output with saved scores, reports, biomechanics, keyframes, and synchronized playback metadata before generating the final structured result.
- History now has separate tabs for analysis records and comparison results, with comparison detail, polling, failed-state retry, and status-aware entry points.
- The comparison page now has the same share flow as regular analysis: generated share image preview, copy image, download, and system share where supported.
- Synchronized comparison playback waits for both video metadata tracks, seeks both sides together, plays/pauses both sides together, and keeps both videos muted/inline so mobile browsers can start both sides from one tap. The playback controls are grouped more cleanly on desktop.
- Training plan creation and renewal now return safe fallback plans when AI fails, JSON is incomplete, a report has an unexpected structure, or only minimal action context is available.
- Follow-up chat now detects requests to re-identify keyframes with video AI only, or users can click "Video AI re-identify keyframes"; this reruns full-source video keyframe localization and creates a proposed keyframes correction card without resetting target lock, rerunning pose/biomechanics/Path A/B, auto-applying data, or overwriting reports.
- Follow-up chat still distinguishes full-video reanalysis requests and offers an explicit confirmation that resets the target lock before rerunning the full pipeline.
- Analysis retry calls can request `reset_target_lock=true`, so archive/history retries and chat-triggered full reanalysis start again from target selection instead of reusing a stale skater lock.
- Report and follow-up share cards now support long summaries, questions, answers, and correction notes with dynamic card height and compressed JPEG output for easier clipboard/file sharing.
- Reports and the standalone `/analysis-chat` workspace now support persisted multi-turn AI follow-up for any completed analysis.
- AI or manual corrections for action labels, action confirmation, keyframes, report notes, and regenerated reports are stored as auditable correction cards before they are applied.
- Report reads, exports, chat context, and sharing use the effective overlay of original analysis data plus applied corrections while preserving the original raw analysis JSON.
- Follow-up sharing now returns copyable text plus a generated image-card payload covering the latest Q&A, applied corrections, pending corrections, and the report link.
- The follow-up UI is responsive across phone, tablet, and desktop: compact mobile selector and sticky input, tablet mixed layout, and desktop list/chat/evidence columns.
- Review uploads now allow broad action categories when the exact action name is unknown, and pre-submit comments are included in the earliest action-recognition prompt.
- Training plan generation now records whether a plan came from AI or from a safe fallback, and fallback plans are clearly labeled in the UI.
- Parent report sharing now generates a visual share card with the most important report information instead of only copying text.
- Pose Replay playback no longer stops after one frame when the report page mirrors the active frame back into the viewer.
- Archive now uses a compact responsive stats strip plus one record toolbar for skater, action, date range, list view, and calendar view. Timelines load the first page quickly with `limit`/`offset` pagination and a "load more" affordance while preserving total-count stats.
- Report now keeps the main page focused on Force Score, conclusion, training focus, issues, subscores, Quality Check, and common actions. Pose Replay, Evidence, Diagnostics, and Follow-up moved into `/report/:id/workspace?tab=pose|evidence|diagnostics|followup`.
- Debug logs repair known mojibake messages such as the pipeline-complete status for clearer diagnostics.

The latest release makes Golden labeling reachable directly from completed analysis history and lets parents choose the exact keyframe window before creating a labelable sample.

- `v5.2.314`: progress/archive Golden links now call an idempotent backend entry that finds or creates one local-pose debug run for the selected analysis, then opens the Golden Label panel automatically; repeated clicks reuse the same run instead of creating duplicates.
- `v5.2.313`: completed archive/progress records now link straight into `/golden?analysis_id=...`; the Golden workspace preselects URL-requested analyses without forcing an unrelated debug run; historical-analysis sample creation exposes manual AI input/keyframe start/end controls prefilled from the saved action window; Golden/debug cards were adjusted for phone, tablet, and desktop overflow safety.
- `v5.2.312`: merged the Golden labeling workspace into `master`, kept the compact JSON-object training-plan prompt, and restored the one-pass malformed-JSON repair guard so AI plan generation remains robust after the merge.
- `v5.2.311`: `/golden` adds a standalone parent-mode Golden labeling workspace with history and new sample creation; Golden bbox drawing now works across sampled, semantic, and partial frames with natural-aspect aligned overlays and native image dragging disabled; saved labels can be reopened and completed incrementally without rerunning scripts.
- `v5.2.310`: development documentation now requires every pushed GitHub update and exported all-in-one image to keep pipeline version, README release notes, commit wording, export filename, and local started image in sync.
- `v5.2.309`: Debug golden labels now save label/prediction/manifest artifacts; the eval script reports overall and per-stratum metrics, failure lists, quality flags, keyframe deltas, and fixed failure tags; appearance relock is opt-in with fail-closed diagnostics; vertical-extrema keyframe proposals and final T/A/L order guards prevent high-confidence invalid jump keyframes.
- `v5.2.308`: mobile target bbox selection supports pinch zoom/pan/reset; manual action windows trigger denser sampling and padded jump coverage; keyframe evidence adapts to jump/spin/step/spiral profiles; subscores are normalized with source labels and compare fallbacks; report/progress share cards add comments and subscore bars while follow-up sharing uses a short multi-turn timeline.
- `v5.2.307`: comparison generation is persisted in `analysis_comparisons` background tasks; full source videos go only through the active `vision` model while the `report` provider summarizes structured JSON text; comparison result history, retry, sharing, mobile-muted synchronized playback, cleaner compare-page layout, and training-plan fallbacks were hardened.
- `v5.2.306`: follow-up chat detects multiple questions in user notes and answers each explicitly with what can/cannot be confirmed; training plan generation uses child-safe low-impact prompts with strict JSON schema and `generation_status`; report user-note response parses questions from upload notes into per-question Q&A; KeyframeEvidencePanel logic extracted to `keyframeEvidence.ts` utility with responsive layout; archive page adds aggregate `fetchArchiveSummary` API for parent mode, clickable calendar day detail modal, and jump-to-latest-month navigation; backfill frame tests added.
- `v5.2.305`: follow-up can run a video-AI-only full-source keyframe rerun that produces a proposed keyframes correction card; it does not reset target lock, rerun pose/biomechanics/visual reports, auto-apply data, or overwrite reports.
- `v5.2.304`: follow-up chat can queue full-video reanalysis with target-lock reset, retry confirmations explain when the skater lock will be rebuilt, and report/chat share images resize for long text while exporting compressed JPEGs.
- `v5.2.303`: review uploads no longer require a precise action subtype or skill node; "unknown / broad category only" is accepted, and user comments are passed into video-temporal action recognition before keyframe and report generation.
- `v5.2.302`: manual target locks fail closed when tracker diagnostics are missing, preventing pose backfills from redrawing the wrong skater's skeleton.
- `v5.2.11`: videos use full-context AI input by default, optional manual start/end windows are supported in review and debug flows, reports/debug views show the actual AI input range, Path A consumes the generated AI clip, and review-flagged multi-person target locks require manual selection.
- `v5.2.10`: startup no longer seeds AI provider rows; configure model instances from `/settings/api`, and legacy duplicate provider rows no longer block container startup.
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

- Video upload with asynchronous analysis, stage-aware retry, optional skill category, and broad action-category fallback when the exact element name is unknown.
- Motion sampling, video precheck, blur filtering, and larger nginx upload limits.
- Target preview, hidden-by-default candidate boxes, manual target bbox selection, YOLO + ByteTrack person tracking, and per-frame bbox diagnostics.
- MediaPipe pose extraction with smoothing, multi-candidate handling, and crop fallback logic.
- Biomechanics metrics for phase timing, jump evidence, rotation estimation, and pose quality.
- Qwen 3.6 Plus video temporal localization for action-family recognition and semantic takeoff/apex/landing intervals, grounded by user comments when provided.
- Semantic keyframe extraction with timestamp arbitration across video AI, motion density, and skeleton candidates.
- Dual-path vision analysis with video-aware context, provider fallback, malformed-JSON recovery, retry handling, and cost limits.
- AI-assisted reports, training plans, skill tree, archive, progress tracking, child mode, and parent mode, with Path B-grounded fallback issues and action-specific drills.
- Background comparison workbench with persisted comparison history, full-source video AI comparison through the `vision` slot, text-only parent summaries through the `report` slot, synchronized playback, retry, and share-image export.
- Persisted AI follow-up for completed videos, with evidence-grounded answers, manual/AI-suggested correction cards, video-AI-only keyframe rerun cards, explicit apply/dismiss actions, and report regeneration from applied corrections.
- Standalone `/analysis-chat` workspace for selecting any completed analysis, reviewing effective recognition/keyframes, checking partial semantic candidates, applying corrections, and sharing text/image recap content.
- Responsive archive and report workspaces: paginated archive list with calendar tab, compact report summary, and advanced report workspace tabs for pose, evidence, diagnostics, and follow-up.
- Pose Debug and Debug pages for replay, tracker thumbnails, candidate counts, pose diagnostics, AI input windows, timings, and logs.
- Docker Compose and all-in-one Docker deployment for NAS or local single-container use.

## Analysis Pipeline

1. Upload the source video and create an analysis record. Users may provide only a broad action category when the exact element name is unknown.
2. Resolve the AI input window: manual start/end when provided, otherwise the full source-video timeline unless a hard provider fallback is explicitly recorded.
3. Run video precheck, motion sampling, and keyframe/action timing on source-video absolute timestamps.
4. Build target preview candidates and wait for manual selection when confidence is low or a multi-person/manual-review flag is present.
5. Track the selected skater with YOLO/ByteTrack and per-frame bbox continuity checks.
6. Extract pose landmarks from regular, tracker-guided, and fallback crops.
7. Smooth pose signals and compute biomechanics, jump features, and keyframe candidates.
8. Run video-temporal AI when configured, including upload comments as context, and resolve semantic action family plus T/A/L timestamps.
9. Extract semantic keyframes with FFmpeg and pass video context or AI clips to vision models.
10. Fuse pose, biomechanics, video AI, Path A pure vision, and Path B skeleton-grounded evidence into structured report data.
11. Persist frames, logs, timings, debug summaries, input-window metadata, and retry checkpoints.

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
# AI keys are optional at startup. Prefer configuring model instances from
# Parent Settings -> API Settings after the app is running.
# QWEN_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
QWEN_VISION_MODEL=qwen3.6-plus
QWEN_VISION_DAILY_COST_LIMIT_CNY=30
QWEN_VISION_VIDEO_ESTIMATED_COST_CNY=0.6
# VIDEO_TEMPORAL_MAX_FRAMES=12
# DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
SECRET_KEY=replace-with-a-random-32-char-secret

# Optional: enable phase-2 multi-pose tracking
# MEDIAPIPE_POSE_TASK_PATH=/models/pose_landmarker_heavy.task
# POSE_NUM_POSES=4

# Optional: use a mounted YOLO person detector weight instead of runtime download
# YOLO_PERSON_MODEL_PATH=/models/yolov8n.pt

# Optional experimental target relock guard. Keep disabled until golden-set
# A/B evaluation shows identity switches improve without keyframe regression.
# PERSON_TRACKER_APPEARANCE_RELOCK=0
# PERSON_TRACKER_APPEARANCE_RELOCK_THRESHOLD=0.55
```

Notes:

- `.env` is not tracked by Git.
- AI provider rows are not auto-seeded on backend startup. Use `/settings/api` to create text, primary vision, Path A, and Path B model instances, then activate the desired provider per slot.
- Existing NAS databases can keep their old provider rows; duplicate legacy rows will not stop the container from starting.
- The default vision model is `qwen3.6-plus`; `qwen-vl-max-latest` is only kept as legacy migration input.
- `QWEN_VISION_DAILY_COST_LIMIT_CNY` caps daily vision spend.
- `QWEN_VISION_VIDEO_ESTIMATED_COST_CNY` estimates one video-temporal call.
- `VIDEO_TEMPORAL_MAX_FRAMES` caps semantic frames sent to image AI.
- `PERSON_TRACKER_APPEARANCE_RELOCK=1` enables the experimental torso HSV appearance relock check. The default remains off.
- `PERSON_TRACKER_APPEARANCE_RELOCK_THRESHOLD` defaults to `0.55` and is clamped to `0.0..1.0`.
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
- broad-category review uploads and user comments in AI prompt context
- stage retry and pipeline version behavior
- debug-run persistence, golden label artifacts, manifest cleanup, and replay flows
- video precheck, precise extraction, and semantic temporal resolution
- bbox tracking, target lock, person tracking, and pose smoothing
- keyframe candidates, proposal diagnostics, vertical extrema, T/A/L ordering, and biomechanics timing
- golden manifest evaluation by stratum, bbox IoU identity metrics, identity switches, and fixed failure tags
- dual-path vision, malformed Path A JSON recovery, provider retry, report fusion, and content normalization
- AI follow-up persistence, prompt context with comments/action confirmation/partial semantic candidates, proposed correction cards, effective correction overlays, and share payload generation

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
- AI provider API keys can be configured after startup from `/settings/api`; only `SECRET_KEY` is required to encrypt saved keys.
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
- `/report/:id`: compact analysis report.
- `/report/:id/workspace?tab=pose|evidence|diagnostics|followup`: report detail workspace for Pose Replay, Evidence, Diagnostics, and Follow-up.
- `/analysis-chat`: standalone parent/coach follow-up workspace for any completed analysis.
- `/report/:id/pose-debug`: expanded skeleton replay and tracker diagnostics.
- `/archive`: paginated training archive with list and calendar views.
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
