# P2 Annual Collection And Technical Event Timeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a rebuildable annual growth PDF from reviewed monthly chapters and, only after measured action gates pass, add evidence-linked full-video technical event timelines.

**Architecture:** P2 has two independent tracks. P2-A renders selected published chapters and milestones into a server-generated PDF with persisted export metadata and visual verification. P2-B introduces versioned `ActionWindow`/`TechnicalEvent` data only after the high-accuracy G3/G4 reports prove candidate recall and specialty/timing quality; until then P2-B remains blocked and no production event scan is authorized.

**Tech Stack:** FastAPI, SQLAlchemy/SQLite, ReportLab, pypdf, pdfplumber, Poppler, React/TypeScript, existing video/pose/biomechanics services, pytest, Vitest.

## Mandatory Prerequisites

### P2-A Annual PDF

- P1 `MonthlyChapter` exists with at least one `published` revision.
- Published chapters store immutable fact snapshots, final text, representative frame references, and source hashes.
- A Chinese-capable font is selected and licensed for redistribution or mounted by deployment configuration.

### P2-B Technical Event Timeline

Do not implement P2-B until both artifacts exist and pass:

```text
G3 candidate acceptance report:
  action-candidate recall >= 98%, or a lower measured target explicitly approved

G4 action acceptance report:
  specialty macro F1 and high-confidence-error gates pass
  T/A/L median <= 0.10s and P95 <= 0.25s for validated jump coverage
  automatic coverage and uncertainty rate are reported
```

Required source plans:

- `docs/superpowers/plans/2026-07-12-high-accuracy-analysis-master-plan.md`
- `docs/superpowers/plans/2026-07-12-mimo-action-analysis-implementation-plan.md`

Current single `analysis.action_window_start/end` and `detect_action_window()` are not a full-video multi-event contract. They must not be repackaged as full coverage.

## Global Constraints

- P2-A and P2-B must be assigned and reviewed independently.
- Annual PDFs contain only selected published chapter revisions; drafts are excluded.
- PDFs are derived assets, rebuildable from database records and safe media references.
- Do not store raw user videos, face crops, or arbitrary local filesystem paths in export JSON.
- PDF pages must render Chinese text without black squares, clipping, overlap, or broken line wrapping.
- Every annual metric shows definition, applicable date window, sample size, and coverage; omit unsupported rates.
- Technical events are event-triggered, not uniform per-second inference.
- Each event links to evidence, confidence, quality flags, and a seekable source timestamp.
- Unsupported/uncertain events remain `unobservable` or are omitted from parent-facing claims.
- Initial validated event profiles are jump, spin, step interval, and spiral/held pose only.
- No judge-grade edge calls, fear detection, fatigue diagnosis, injury prediction, or automatic level certification.
- Source design: `docs/superpowers/specs/2026-07-22-growth-story-product-design.md`.

---

# P2-A: Annual Growth PDF

## File Map

### Backend

- Modify `backend/requirements.txt`: pin `reportlab`, `pypdf`, and `pdfplumber`.
- Modify `backend/app/models.py`: add `AnnualCollection` and `AnnualExport`.
- Modify `backend/app/database.py`: additive annual tables migration.
- Modify `backend/app/schemas.py`: annual selection, preview, export, and status contracts.
- Create `backend/app/services/annual_collections.py`: validate selections and build immutable annual snapshot.
- Create `backend/app/services/annual_pdf.py`: ReportLab renderer only.
- Create `backend/app/routers/annual.py`: collection/export/download routes.
- Modify `backend/app/main.py`: include annual router.
- Create backend tests for selection, snapshot, PDF, and routes.

### Frontend

- Modify `frontend/src/api/client.ts`: annual contracts.
- Create `frontend/src/pages/AnnualCollectionPage.tsx` and test.
- Create `frontend/src/components/AnnualChapterPicker.tsx` and test.
- Create `frontend/src/components/AnnualExportStatus.tsx` and test.
- Modify `frontend/src/pages/GrowthHomePage.tsx` and `frontend/src/App.tsx`.

## Data Contracts

```python
class AnnualCollection(Base):
    __tablename__ = "annual_collections"
    __table_args__ = (UniqueConstraint("skater_id", "year", "revision", name="uq_annual_collection_revision"),)

    id: Mapped[str]
    skater_id: Mapped[str]
    year: Mapped[int]
    revision: Mapped[int]
    status: Mapped[str]              # draft | ready | exported | stale
    title: Mapped[str]
    selected_chapter_ids: Mapped[list]
    selected_milestone_ids: Mapped[list]
    snapshot: Mapped[dict]
    source_hash: Mapped[str]
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class AnnualExport(Base):
    __tablename__ = "annual_exports"
    id: Mapped[str]
    collection_id: Mapped[str]
    status: Mapped[str]              # pending | processing | completed | failed
    renderer_version: Mapped[str]
    asset_relative_path: Mapped[str | None]
    file_sha256: Mapped[str | None]
    page_count: Mapped[int | None]
    error_message: Mapped[str | None]
    created_at: Mapped[datetime]
    completed_at: Mapped[datetime | None]
```

Annual files live under `data/analysis_assets/annual/{collection_id}/{export_id}.pdf`. Only the relative path is stored.

### Task A1: Annual Persistence And Selection Validation

**Files:** `models.py`, `database.py`, `schemas.py`, `annual_collections.py`, `test_annual_collections.py`.

- [ ] Write failing tests for annual table migration, uniqueness, published-only selection, same-skater/year validation, duplicate ID rejection, stable ordering, and deterministic source hash.
- [ ] Add models and `run_migrations_annual_collections()` with foreign keys, unique/index definitions, and idempotent `CREATE TABLE IF NOT EXISTS`.
- [ ] Implement:

```python
async def build_annual_snapshot(
    session: AsyncSession,
    skater_id: str,
    year: int,
    chapter_ids: list[str],
    milestone_ids: list[str],
) -> dict[str, Any]
```

- [ ] Snapshot embeds published final text, immutable fact/source hashes, selected quote facts, representative-frame references, milestone verification sources, and definitions for every included metric.
- [ ] Reject chapters outside `year`, nonpublished revisions, another skater, missing media provenance, or stale source mismatch. Missing representative images are allowed and marked `text_only`.
- [ ] Run tests and commit: `feat: persist annual growth collections`.

### Task A2: PDF Renderer

**Files:** `backend/requirements.txt`, `backend/app/services/annual_pdf.py`, `backend/tests/test_annual_pdf.py`, `backend/assets/fonts/README.md`.

- [ ] Add pinned dependencies compatible with Python 3 and DS918+ deployment. Do not download fonts at application runtime.
- [ ] Add font configuration:

```text
ANNUAL_PDF_FONT_PATH=/app/assets/fonts/NotoSansCJKsc-Regular.otf
ANNUAL_PDF_FONT_BOLD_PATH=/app/assets/fonts/NotoSansCJKsc-Bold.otf
```

If fonts are bundled, record source, version, license, and SHA256 in `backend/assets/fonts/README.md`. If mounted, startup/export validation must report a clear missing-font error.

- [ ] Write failing PDF tests asserting `%PDF` header, expected page count, extractable Chinese chapter text, stable headers/footers, no draft chapter content, and text-only fallback when images are missing.
- [ ] Implement `render_annual_pdf(snapshot, output_path, font_paths) -> AnnualPdfResult` using ReportLab Platypus. Use A4 portrait, 18 mm side margins, 16 mm top/bottom margins, page numbers, and section page breaks.
- [ ] Page structure:

```text
Cover
Year at a glance
Selected monthly chapters, each starting on a new page
Milestone timeline
Metric definitions and provenance appendix
```

- [ ] Images must be decoded with bounded dimensions, EXIF orientation handled, aspect ratio preserved, and maximum rendered resolution capped. A failed image becomes a labeled text panel.
- [ ] Use ASCII hyphens in generated PDF metadata/text where a dash is required; avoid non-breaking dash glyphs.
- [ ] Write output atomically to a temporary file, compute SHA256/page count, then move to the stable asset path.
- [ ] Run tests and commit: `feat: render annual growth PDF`.

### Task A3: Export API And Background Status

**Files:** `backend/app/routers/annual.py`, `backend/app/main.py`, `backend/app/schemas.py`, `backend/tests/test_annual_routes.py`.

**Endpoints:**

```text
POST /api/annual/skaters/{id}/{year}/preview
POST /api/annual/skaters/{id}/{year}/collections
GET  /api/annual/skaters/{id}/{year}/collections
POST /api/annual/collections/{collection_id}/exports
GET  /api/annual/exports/{export_id}
GET  /api/annual/exports/{export_id}/download
```

- [ ] Write failing tests for invalid selection, idempotent preview, export status transitions, renderer failure, path traversal rejection, completed download headers, and missing/deleted asset behavior.
- [ ] Export creation returns immediately with `pending` and schedules a background job. Repeated creation for the same collection source hash may reuse a completed export.
- [ ] Download resolves the stored relative path beneath the configured annual asset root and rejects any path that escapes it.
- [ ] Use `Content-Disposition: attachment; filename="icebuddy-<year>-<skater>.pdf"` with an ASCII-safe fallback.
- [ ] Register the router, run tests, and commit: `feat: add annual export API`.

### Task A4: Annual Selection UI

**Files:** `frontend/src/api/client.ts`, `AnnualCollectionPage.tsx`, `AnnualChapterPicker.tsx`, `AnnualExportStatus.tsx`, tests, `GrowthHomePage.tsx`, `App.tsx`.

- [ ] Add exact TS/API contracts.
- [ ] Write tests for year/skater selection, published chapter list, default selecting all published months, deselection, preview warnings, text-only chapter indicator, export polling, failure retry, and completed download link.
- [ ] Page copy must explain that only published monthly chapters appear and exports can be rebuilt.
- [ ] Register `/annual`; add a growth-home entry only when at least one published chapter exists.
- [ ] Run Vitest/build and commit: `feat: add annual collection workspace`.

### Task A5: PDF Visual Verification

Use the PDF skill workflow for every meaningful renderer change:

```powershell
New-Item -ItemType Directory -Force tmp/pdfs | Out-Null
$env:PYTHONPATH='backend'
python -m pytest backend/tests/test_annual_pdf.py backend/tests/test_annual_routes.py -q
pdftoppm -png output/pdf/icebuddy-annual-sample.pdf tmp/pdfs/annual-page
```

- [ ] Inspect every rendered PNG, not only the first page.
- [ ] Verify Chinese glyphs, line breaks, image aspect ratio, margins, page numbers, headers/footers, chapter transitions, long quotes, no-image chapters, and provenance appendix.
- [ ] Use `pypdf` to assert page count and `pdfplumber` to confirm expected text extraction.
- [ ] Keep intermediate renders in `tmp/pdfs/`; keep checked sample output under `output/pdf/` only for local QA. Do not commit user data or generated family PDFs.
- [ ] Commit visual fixes only after rerendering shows zero defects.

---

# P2-B: Full-video Technical Event Timeline

## Gate Task B0: Prove Authorization To Start

This task has no production-code edits.

- [ ] Locate committed G3 and G4 reports.
- [ ] Record measured recall, macro F1, timing error, high-confidence error, automatic coverage, uncertainty rate, pipeline version, and frozen-test hash in `docs/evaluation/technical-event-gate.md`.
- [ ] Verify the reports cover jumps, spins, step intervals, and held poses separately. A profile without measured acceptance remains disabled.
- [ ] If G3 or G4 fails or is absent, stop P2-B and report it as blocked. P2-A may continue.
- [ ] Commit the gate report before Task B1.

## P2-B File Map

- Create `backend/app/services/technical_event_contracts.py`.
- Create `backend/app/services/technical_event_scan.py`.
- Create `backend/app/services/technical_event_merge.py`.
- Create `backend/app/services/technical_event_analysis.py`.
- Create `backend/app/routers/technical_events.py`.
- Modify `backend/app/models.py`, `database.py`, `schemas.py`, and `main.py`.
- Create focused backend tests for contracts, scan, merge, analysis, and routes.
- Create `frontend/src/components/TechnicalEventTimeline.tsx`, `TechnicalEventCard.tsx`, tests, and route/page integration.

## Versioned Event Contract

```python
class TechnicalEventV1(BaseModel):
    schema_version: Literal["technical_event.v1"] = "technical_event.v1"
    event_id: str
    analysis_id: str
    start_sec: float
    end_sec: float
    action_type: Literal["jump", "spin", "step", "spiral"]
    action_subtype: str | None
    representative_timestamp: float
    keyframe_ids: list[str]
    observation: str
    training_tip: str | None
    confidence: float = Field(ge=0, le=1)
    status: Literal["supported", "uncertain", "unobservable"]
    evidence_source: str
    quality_flags: list[str]
    contract_version: str
    detector_version: str
    source_video_hash: str
```

Required invariants:

```text
0 <= start_sec < end_sec <= source duration
start_sec <= representative_timestamp <= end_sec
keyframe IDs resolve to the same analysis
supported requires confidence >= calibrated profile threshold and usable evidence
parent-facing observation/training_tip may use only supported evidence
```

### Task B1: Persistence And Contracts

- [ ] Write failing Pydantic/model/migration tests for invariants, version fields, analysis ownership, source hash, and status.
- [ ] Persist one `technical_event_runs` row per scan configuration and `technical_events` rows linked to it. A unique key on `(analysis_id, source_video_hash, detector_version, config_hash)` prevents accidental duplicate runs.
- [ ] Store evidence references and structured observation payloads, not duplicated image bytes.
- [ ] Add default-off flags per profile: `TECHNICAL_EVENTS_JUMP_ENABLED`, `SPIN`, `STEP`, and `SPIRAL`.
- [ ] Run tests and commit: `feat: add technical event contracts`.

### Task B2: Low-cost Full-video Candidate Scan

**Consumes:** accepted `ActionCandidateV1` from the high-accuracy action plan. Do not recreate another candidate schema.

- [ ] Write failing tests for multiple separated events, overlapping candidates, combinations, no-motion video, camera pan, and candidate provenance.
- [ ] Scan the complete allowed input duration at the accepted low-cost sampling profile. Do not repeatedly call a VLM per second.
- [ ] Convert accepted candidates to source-video timestamps using the timebase contract. Preserve search/core/exit windows and uncertainty bounds.
- [ ] Enforce per-profile candidate gates and a hard maximum candidates/minute. Excess candidates become a quality flag and require review rather than unlimited downstream calls.
- [ ] Persist the candidate run before specialty analysis for restart recovery.
- [ ] Run Golden evaluation and commit only if candidate recall and coverage do not regress. Commit: `feat: scan full-video technical candidates`.

### Task B3: Deterministic Window Merge

- [ ] Write failing tests for IoU/time-overlap merge, adjacent distinct jumps, jump combinations, spin-to-jump transitions, nested windows, and deterministic IDs.
- [ ] Implement `merge_technical_candidates(candidates, policy) -> list[TechnicalEventSeed]` in `technical_event_merge.py`.
- [ ] Never merge two high-confidence core intervals of different action profiles. Preserve combination parent/child relationships.
- [ ] Event IDs derive from analysis ID, profile, rounded source interval, detector version, and source hash.
- [ ] Run tests and commit: `feat: merge technical event windows`.

### Task B4: Reuse Pose/Biomechanics Per Event

- [ ] Write failing tests proving each seed reuses existing profile-specific keyframe/pose/biomechanics services and does not mutate the main `Analysis` report.
- [ ] Extract/cache representative frames beneath `data/analysis_assets/{analysis_id}/technical-events/{event_id}/`.
- [ ] Jump uses T/A/L; spin uses entry/main/exit; spiral uses hold; step uses interval coverage. Missing required evidence sets `uncertain` or `unobservable`.
- [ ] Generate `observation` and `training_tip` from deterministic rules and the existing structured report provider only when a bounded text rewrite is needed. One event must not trigger an unbounded chain of provider calls.
- [ ] Record runtime/cost counters and profile coverage.
- [ ] Run focused tests, repeatability tests, and Golden A/B. Commit: `feat: analyze technical events`.

### Task B5: Event API And Background Processing

**Endpoints:**

```text
POST /api/analysis/{analysis_id}/technical-events
GET  /api/analysis/{analysis_id}/technical-events
GET  /api/analysis/{analysis_id}/technical-events/{event_id}
POST /api/analysis/{analysis_id}/technical-events/retry
```

- [ ] Write tests for completed-analysis requirement, missing source video, idempotent create, polling state, restart recovery, profile flags, stale source hash, and deletion/cleanup.
- [ ] POST creates/reuses a run and returns immediately. GET returns run status, coverage, uncertainty, and events ordered by `start_sec`.
- [ ] Retry accepts failed/partial runs only and reuses cached candidates/evidence when config/source hashes match.
- [ ] Register router, run tests, and commit: `feat: add technical event API`.

### Task B6: Seekable Timeline UI

**Files:** `frontend/src/api/client.ts`, `TechnicalEventTimeline.tsx`, `TechnicalEventCard.tsx`, tests, and report integration.

- [ ] Write tests for chronological order, event type labels, supported/uncertain/unobservable display, quality badges, missing thumbnails, and video seeking.
- [ ] Render a single shared video player and chronological event list. Clicking a supported event sets `video.currentTime = representative_timestamp` and optionally plays.
- [ ] Default parent view shows supported events; uncertainty toggle reveals uncertain/unobservable entries without converting them into claims.
- [ ] Use copy `关键时刻` or `技术事件`, never `逐秒点评`.
- [ ] Display run coverage and uncertainty rate so an empty timeline is distinguishable from an unscanned video.
- [ ] Integrate below `ActionPhaseStrip` only when a completed event run exists; otherwise show an explicit manual `分析全程关键时刻` action when profile gates are enabled.
- [ ] Run Vitest/build and commit: `feat: add technical event timeline`.

### Task B7: Gate Revalidation And Rollout

- [ ] Run the frozen Golden suite and compare candidate recall, specialty F1, timing, high-confidence error, coverage, uncertainty, runtime, and cost.
- [ ] Run repeat analysis and require deterministic event IDs/order plus >=95% supported-event agreement.
- [ ] Test one representative 30-second video on DS918+; verify restart after candidate scan and after event analysis resumes from checkpoints.
- [ ] Roll out per profile behind default-off flags. Enable only accepted profiles; do not use one global switch to enable unvalidated types.
- [ ] Document rollback, cache invalidation, and asset cleanup.

---

## Combined Verification

P2-A:

```powershell
$env:PYTHONPATH='backend'
python -m pytest backend/tests/test_annual_collections.py backend/tests/test_annual_pdf.py backend/tests/test_annual_routes.py -q
npm --prefix frontend test
npm --prefix frontend run build
```

P2-B, only after B0 passes:

```powershell
$env:PYTHONPATH='backend'
python -m pytest backend/tests/test_technical_event_contracts.py backend/tests/test_technical_event_scan.py backend/tests/test_technical_event_merge.py backend/tests/test_technical_event_analysis.py backend/tests/test_technical_event_routes.py -q
npm --prefix frontend test
npm --prefix frontend run build
```

## Definition Of Done

### P2-A

- Only published selected chapters enter an annual snapshot.
- A PDF can be rebuilt from its snapshot and relative media references.
- Every rendered page passes PNG visual inspection.
- Chinese text, images, page numbers, and provenance render correctly.
- Missing media produces a polished text-only section.
- Export paths cannot escape the annual asset root.

### P2-B

- B0 records passing G3/G4 evidence before production code starts.
- Full-video scan produces multiple evidence-linked events without per-second VLM calls.
- Events are versioned, deterministic, seekable, and report coverage/uncertainty.
- Only profiles with measured acceptance can be enabled.
- No parent-facing unsupported claim, medical inference, or judge-grade promise is introduced.
