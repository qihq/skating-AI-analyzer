# Skating Analyzer

AI-powered figure skating training analysis system built with React, FastAPI, MediaPipe, YOLO/ByteTrack, and Docker.

[Chinese README](./README.zh.md) | [Contributing](./CONTRIBUTING.md) | [License](./LICENSE) | [Screenshot Guide](./SCREENSHOT_GUIDE.md)

## Overview

Skating Analyzer helps skaters, parents, and coaches review training videos with a repeatable analysis pipeline. The app uploads a video, samples motion frames, locks onto the target skater, runs pose and person tracking, resolves takeoff/apex/landing moments, calls AI vision models when configured, and turns the results into reports, plans, archives, and progress views.

The current pipeline version is `v5.2.319`.

## Modern Animal Island UI

The app now includes an optional **Animal Island-inspired modern interface** for family use. The classic interface remains available and unchanged; switch between the two from the top bar at any time.

- **Four clear spaces**: Today Island (`/home`), Start Review / Rink Cabin (`/review`), Growth Islands (`/growth`), and Resident Services (`/me`). Previously scattered screens are grouped into these destinations without breaking legacy URLs.
- **Unified review workspace**: Report summary, key moments, body and pose, follow-up questions, and diagnostics are sections of one analysis detail page. Legacy workspace `tab` links map to the matching modern section.
- **Responsive by design**: Phone PWA uses a safe-area-aware dock fixed to the viewport bottom; iPad portrait keeps the dock and uses a two-column canvas; iPad landscape and desktop use a persistent left rail. Only the current destination is highlighted, including Start Review.
- **Family-friendly atmosphere**: Automatic morning, daytime, sunset, and night themes can be pinned manually. The scene uses Animal Island grass texture, sea, and tree-line artwork with time-aware colour treatment; night mode uses dedicated high-contrast chrome text. Child and parent modes share the same layout while adjusting copy, density, and protected tools.
- **Refined navigation assets**: The four primary destinations use adapted Animal Island map, camera, miles, and design icons. The review action stays neutral outside the review workspace and becomes sun-yellow only when active.
- **PWA support**: The production build registers a same-origin service worker, includes an installable manifest, and provides navigation fallback when the shell is cached. API and write requests are not cached.
- **Integrated growth tools**: Training plans and comparisons now open through dedicated hubs, so routes without IDs no longer lead to invalid-parameter dead ends.
- **Animal Island dialogs and sharing**: Parent PIN prompts, milestone cards, plans, comparisons, monthly stories, and annual collections use the same responsive island dialog language. Long-form posters grow with their content; annual collections pair a compact cover card with the full PDF download.
- **Complete annual PDF runtime**: The all-in-one image includes pinned `reportlab` and `pypdf` dependencies, and missing runtime modules are reported explicitly if an incomplete deployment is detected.

The natural palette, rounded cards, and navigation language are adapted from [guokaigdg/animal-island-ui](https://github.com/guokaigdg/animal-island-ui), licensed under CC BY-NC 4.0. This adaptation is for personal, non-commercial use and retains attribution.

## Recent Updates (P0 — P2)

The current release ships three major tracks: **P0 Growth Home**, **P1 Monthly Story & Sharing**, and **P2 Annual & Event Timeline**, plus golden evaluation tooling, person tracker improvements, and an OpenCode API compatibility fix.

### P0 — Growth Home Dashboard

A parent-facing growth dashboard that gives a panoramic view of a skater's training history:

- **Growth Summary API**: Aggregates lesson count, completed analyses, current-month analysis count, milestone totals, latest analysis with training focus, and KPI trend data — all consumed by the frontend dashboard.
- **GrowthKpiBar**: Radar-style KPI strip showing Force Score trends, session counts, completed analyses, and milestone totals at a glance.
- **MilestoneTimeline**: Chronological milestone list with system-detected / parent-confirmed / coach-confirmed verification badges, unlock timestamps, and source analysis links.
- **ActionPhaseStrip**: Profile-aware keyframe phase display — shows jump T/A/L, spin entry/main/exit, spiral hold, or step sequence coverage frames depending on the analysis profile, with optional video playback.
- **Growth Home Page** (`/home`): Unified dashboard combining KPIs, latest analysis summary, current focus, next action, action phase strip, milestone timeline, and navigation links to all growth tools.

### P1 — Monthly Story & Sharing

Reviewable monthly growth chapters with family highlight quotes and milestone share cards:

- **Family Highlight Quotes**: Optional quote + speaker (skater/parent/coach) fields on the review upload form — `highlight_quote` (max 280 chars) and `quote_speaker`. Persisted on `Analysis` and surfaced in detail views and monthly fact snapshots.
- **Monthly Facts Engine** (`monthly_facts.py`): Deterministic fact aggregation per skater/month — session counts, comparable jump metrics (before/after values, sample count, source analysis IDs), milestone unlocks within the month, recurring observations from report issue categories, training focus tracking, and verbatim quote preservation. All facts ordered deterministically. Quality flags such as `insufficient_comparable_evidence` are set when no reliable trend exists. Up to four representative frame references are selected from milestone-linked or good-quality analyses.
- **Structured Chapter Generation** (`monthly_chapters.py`): Calls the active `report` provider with a deterministic fact snapshot and structured JSON schema. Validates that every highlight references existing fact IDs, the quote text is copied verbatim, the narrative stays under 1600 characters, and forbidden claim phrases (injury, fear, fatigue diagnosis, level prediction, coaching confirmation) are absent unless the exact phrase appears in a supplied fact. Provider failure preserves the `facts_ready` revision — the snapshot is never deleted.
- **Growth API** (`/api/growth`): Six endpoints — `POST facts`, `POST generate`, `GET list`, `GET by ID`, `PATCH final_text`, `POST publish`. Published revisions are immutable; regeneration creates the next revision.
- **Monthly Chapters UI** (`/chapters`): Skater/month selectors, explicit flow buttons (Gather Facts → Generate → Edit → Publish), revision history selector, MonthlyFactPreview grouping facts by count/metric/milestone/observation/quote with source/quality badges, and MonthlyChapterEditor with separate AI-draft and parent-editable final text, character counter, and publish confirmation dialog.
- **Milestone Share Cards** (`milestoneShareCanvas.ts`): 1080×1350 JPEG share image generator with title, date, skater name, verification badge, note quote, optional metric panel, and optional keyframe image. Gradient-themed design; falls back to "no frame" panel when the image is absent. Download, copy-to-clipboard, and native share buttons on each milestone in the timeline.

### P2 — Annual & Event Timeline

Year-end growth collections that compile monthly chapters into a downloadable PDF:

- **Annual Collections API** (`/api/annual`): Preview a collection (snapshot of selected chapters + milestones), create a collection with source hash for reproducibility, list collections per skater/year, and list annual milestones with cover-ready metadata.
- **Annual PDF Export** (`annual_pdf.py`): ReportLab-generated A4 PDF with cover page, table of contents, monthly chapter narratives, milestone timeline, and representative frame images. Background export via `BackgroundTasks` with status tracking (`pending` → `processing` → `completed`/`failed`).
- **Resumable Exports**: Incomplete exports from a crashed/restarted server are automatically recovered on startup. Resumed exports track `resumed_at` timestamps and keep the original `created_at` for ordering.
- **Annual Collections UI** (`/annual`): Multi-step page — pick chapters from published monthly chapters, select milestones, preview the collection, and trigger PDF export. Shows live export status with progress, success/failure states, and download link. Entry link "制作年度合集" on Growth Home appears only when published chapters exist.

### Infrastructure & Tooling

- **MiMo/OpenCode API fix**: Removed the redundant `api-key` header from MiMo chat completion requests. OpenCode's new `sk-` format keys rejected the dual-header (`api-key` + `Authorization: Bearer`) auth pattern that the old base64-format keys tolerated. Added diagnostic logging showing active provider ID, type, base URL, model, and decrypted key prefix.
- **Golden eval tooling**: Added `golden_overrides.py` for per-sample override logic, `diff_baselines.py` for comparing eval runs, corresponding test suites, and a `golden-eval-ab-runbook.md` documenting the A/B evaluation workflow.
- **Person tracker**: Improved target relock decision logic, added self-heal recovery for manual-lock lost targets, and expanded test coverage for relock scenarios.
- **Keyframe candidates**: Enhanced arbitration diagnostics and vertical extrema confidence thresholds.
- **Debug page**: Golden label anchors now capture tracking anchor metadata (bbox, timestamp, frame ID), action window boundaries, and revision tracking for finer-grained labeling.

## Version History

- `v5.2.319`: P0 Growth Home dashboard with KPI radar, milestone timeline, skill evolution, and profile-aware action phases; P1 monthly growth chapters with highlight quotes, deterministic facts, structured generation, chapter workspace, and milestone share cards; P2 annual collections with chapter/milestone picker, preview, background PDF export, resume-on-restart, and download; removed redundant `api-key` header for MiMo/OpenCode compatibility; added golden overrides, diff baselines, and A/B eval runbook; improved person tracker relock and self-heal logic; enhanced keyframe arbitration diagnostics; debug golden labels capture tracking anchors and action window bounds.
- `v5.2.318`: Applied action-label and keyframe correction cards are persisted back into `analyses`, legacy applied corrections are backfilled at startup, and the report/follow-up chat workspaces refresh their current analysis detail before showing correction success.
- `v5.2.315`: Exported all-in-one Docker image from `codex/face-identity-target-lock` with face identity model layer, skater face profile API, target diagnostics, parent UI, and profile deletion.
- `v5.2.313`: Completed archive/progress records now link straight into `/golden?analysis_id=...`; the Golden workspace preselects URL-requested analyses without forcing an unrelated debug run.
- `v5.2.308`: Mobile target bbox selection supports pinch zoom/pan/reset; manual action windows trigger denser sampling and padded jump coverage; keyframe evidence adapts to jump/spin/step/spiral profiles; subscores are normalized with source labels and compare fallbacks; report/progress share cards add comments and subscore bars while follow-up sharing uses a short multi-turn timeline.
- `v5.2.307`: Comparison generation is persisted in `analysis_comparisons` background tasks; full source videos go only through the active `vision` model while the `report` provider summarizes structured JSON text; comparison result history, retry, sharing, mobile-muted synchronized playback, and training-plan fallbacks were hardened.
- `v5.2.306`: Follow-up chat detects multiple questions in user notes and answers each explicitly; training plan generation uses child-safe low-impact prompts with strict JSON schema; archive page adds aggregate API for parent mode, clickable calendar day detail modal, and jump-to-latest-month navigation.
- `v5.2.305`: Follow-up can run a video-AI-only full-source keyframe rerun that produces a proposed keyframes correction card without resetting target lock, rerunning pose/biomechanics, or overwriting reports.
- `v5.2.304`: Follow-up chat can queue full-video reanalysis with target-lock reset; retry confirmations explain when the skater lock will be rebuilt; report/chat share images resize for long text while exporting compressed JPEGs.
- `v5.2.303`: Review uploads no longer require a precise action subtype or skill node; "unknown / broad category only" is accepted, and user comments are passed into video-temporal action recognition.
- `v5.2.11`: Videos use full-context AI input by default; optional manual start/end windows are supported in review and debug flows; Path A consumes the generated AI clip.
- `v5.2.10`: Startup no longer seeds AI provider rows; configure model instances from `/settings/api`.
- `v5.2.9`: Path A requests stricter JSON, recovers malformed model output, retries a JSON-only repair pass, and reports fall back to Path B/top-issue evidence with action-specific drills.
- `v5.2.8`: Reused lost tracker boxes can be used as padded pose crop hints for distant tiny skaters.

Earlier versions (v5.2.1 through v5.2.7) focused on tracker stability, pose smoothing, keyframe confidence, and pipeline robustness. See [git log](https://github.com/qihq/skating-AI-analyzer/commits/master) for the full history.

## Architecture

- **Backend**: FastAPI + SQLAlchemy + SQLite (async), with Pydantic contracts, idempotent additive migrations, background analysis tasks, AI provider abstraction layer, and retry/fallback logic.
- **Frontend**: React 18 + TypeScript + Tailwind + Recharts, with Canvas-based share image generation, responsive layout (phone/tablet/desktop), and child/parent mode routing.
- **Analysis Pipeline**: Video precheck → frame extraction → target selection → YOLO/ByteTrack tracking → MediaPipe pose → biomechanics → semantic keyframe resolution → dual-path vision analysis (Path A/B) → AI report → skill unlock → training plan.
- **AI Provider Layer**: Slot-based active provider selection (`vision`, `report`), OpenAI-compatible, Claude-compatible, and MiMo backends, with encryption-at-rest for API keys.

## Deployment

### All-in-one Docker

```bash
docker run -d \
  --name skating-allinone \
  -p 8080:80 \
  -v /path/to/data:/data \
  -v /path/to/backups:/backups \
  -v /path/to/.env:/workspace/.env:ro \
  skating-analyzer-allinone:latest
```

### Docker Compose

```bash
docker compose up -d
```

The `.env` file should contain at minimum:

```env
SECRET_KEY=your-random-secret
```

## Development

```bash
# Backend
cd backend
pip install -r requirements.txt
PYTHONPATH=backend uvicorn app.main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```

### Running Tests

```bash
# Backend
PYTHONPATH=backend pytest backend/tests -q

# Frontend
cd frontend && npm test
```

## License

MIT License. See [LICENSE](./LICENSE) for details.
