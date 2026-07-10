# Golden Label Reanalysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Golden labeling into an authoritative, in-place formal reanalysis workflow while improving complete frame display and preserving current main-skater tracking behavior when no Golden anchors are applied.

**Architecture:** Add a versioned `Analysis.golden_overrides` JSON snapshot and a focused Golden override service for normalization, validation, hashing, retry-stage selection, and keyframe resolution. Extend the current sequential person tracker with optional timestamped anchor boxes, then expose apply-and-retry through the analysis API and wire the existing unified `/golden` workspace to save drafts, show complete frame state, and update the original report.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy async, Pydantic, unittest/pytest, React 18, TypeScript, Vite, Tailwind CSS.

## Global Constraints

- `/golden` remains the only Golden workspace; `analysis_id` only controls selection.
- Saving a draft must not change a formal analysis.
- Applying Golden updates the same `analysis_id` and `/report/{analysis_id}` route.
- Applied overrides survive ordinary retry until explicitly removed.
- No Golden anchors means existing tracker behavior is unchanged.
- Golden boxes are normalized to the uncropped source frame and keyed by stable frame identity plus timestamp.
- Existing uncommitted work in `DebugPage.tsx`, `debug.py`, `person_tracker.py`, and their tests must be preserved.

---

### Task 1: Versioned Golden Override Domain

**Files:**
- Create: `backend/app/services/golden_overrides.py`
- Modify: `backend/app/models.py`
- Modify: `backend/app/database.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_golden_overrides.py`
- Test: `backend/tests/test_pipeline_version.py`

**Interfaces:**
- Produces: `normalize_golden_label(label, run) -> dict`, `validate_golden_override(label) -> dict`, `golden_override_hash(payload) -> str`, `golden_retry_stage(previous, current) -> str`, and `apply_golden_keyframes(bio_data, resolved_keyframes, override) -> tuple[dict, dict]`.
- Produces: `Analysis.golden_overrides: dict | None`.

- [ ] Write failing tests for legacy target-box conversion, invalid boxes/order rejection, deterministic hashes, retry-stage selection, and Golden keyframe resolution that retains automatic prediction evidence.
- [ ] Run `python -m pytest backend/tests/test_golden_overrides.py backend/tests/test_pipeline_version.py -q` and confirm failures are caused by the missing field/service.
- [ ] Add the model field, SQLite migration column, Pydantic request/response models, and minimal focused service implementation.
- [ ] Rerun the two test modules and confirm they pass.

### Task 2: Revisioned Draft And Stable Tracking Anchors

**Files:**
- Modify: `backend/app/routers/debug.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/tests/test_debug_runs.py`

**Interfaces:**
- Consumes: Golden normalization types from Task 1.
- Produces: saved labels with `revision`, `tracking_anchors`, action-window fields, applied metadata, and backward-compatible `target_bboxes`.

- [ ] Add failing debug-route tests proving revision increments, legacy boxes gain timestamps/source IDs when frame metadata exists, and unchanged historical labels still load.
- [ ] Run the targeted tests and confirm the expected failures.
- [ ] Extend the label payload/response and manifest serialization without removing legacy fields.
- [ ] Rerun the targeted debug tests.

### Task 3: Apply Golden And Reanalyze In Place

**Files:**
- Modify: `backend/app/routers/analysis.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_analysis_stage_retry.py`

**Interfaces:**
- Consumes: `validate_golden_override`, `golden_override_hash`, and `golden_retry_stage`.
- Produces: `POST /analysis/{analysis_id}/golden-overrides/apply-and-retry` and `DELETE /analysis/{analysis_id}/golden-overrides`.

- [ ] Write failing tests for mismatched run IDs, stale revisions, invalid labels, idempotent duplicate apply, original ID preservation, pending transition, earliest retry boundary, and ordinary retry persistence.
- [ ] Run the targeted analysis retry tests and verify RED.
- [ ] Implement validation-before-mutation, atomic override/pending persistence, selective cache invalidation, background processing, and explicit removal.
- [ ] Rerun the targeted tests and verify GREEN.

### Task 4: Golden Anchors In Main-Person Tracking

**Files:**
- Modify: `backend/app/services/person_tracker.py`
- Modify: `backend/app/routers/analysis.py`
- Modify: `backend/tests/test_person_tracker.py`
- Modify: `backend/tests/test_analysis_stage_retry.py`

**Interfaces:**
- Consumes: validated `tracking_anchors` from `Analysis.golden_overrides`.
- Produces: optional anchor-aware calls with diagnostics `golden_anchor_count`, `golden_anchor_hits`, `golden_anchor_reseed_count`, and `golden_anchor_conflicts`.

- [ ] Add a no-anchor regression test using current fixtures and anchor tests for one seed, crossing/reseed, and invalid conflict behavior.
- [ ] Run the targeted tests and confirm only new anchor expectations fail.
- [ ] Add an optional anchor map to the existing sequential tracker. At anchor frames, force the confirmed bbox and refresh tracker state; between anchors keep current prediction/relock logic.
- [ ] Pass source timestamps/anchors from formal analysis and store diagnostics in `target_lock`.
- [ ] Rerun tracker and analysis tests.

### Task 5: Golden Keyframes In The Formal Pipeline

**Files:**
- Modify: `backend/app/routers/analysis.py`
- Modify: `backend/tests/test_analysis_stage_retry.py`

**Interfaces:**
- Consumes: `apply_golden_keyframes` from Task 1.
- Produces: final `bio_data.key_frame_timestamps` and `resolved_keyframes.selected` with `source=golden_override`, while retaining `automatic_prediction`.

- [ ] Add a failing pipeline-stage test showing Golden T/A/L replaces final resolved times before vision/report inputs.
- [ ] Run the test and verify RED.
- [ ] Apply Golden moments immediately after automatic semantic resolution and before downstream context/metrics persistence.
- [ ] Rerun the stage-retry and correction test modules.

### Task 6: Frontend Apply Flow And Complete Frame Presentation

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/pages/DebugPage.tsx`
- Modify: `frontend/src/pages/ArchivePage.tsx` only if route parity is missing

**Interfaces:**
- Consumes: revisioned labels and apply-and-retry API.
- Produces: stable structured tracking anchors, draft/applied state, impact summary, processing state, same-report link, and an untruncated chronological frame strip.

- [ ] Add TypeScript types and client methods for structured keyframes, anchors, apply response, and removal.
- [ ] Convert selected frame boxes into anchors containing timestamp/source frame ID while continuing to send legacy boxes.
- [ ] Replace the fixed-height frame list with a source-filtered chronological strip that shows loaded/total counts and explicit empty/image-error states.
- [ ] Add separate `保存草稿` and `应用 GOLD 并重新分析` actions, stale-draft/applied badges, confirmation impact text, and `/report/{analysis_id}` completion link.
- [ ] Confirm both sidebar and progress/archive entry paths render the same component and selected run.
- [ ] Run `npm run build` in `frontend`.

### Task 7: Regression And Rendered Verification

**Files:**
- Verify only; do not add committed screenshots or temporary browser scripts.

**Interfaces:**
- Consumes all prior tasks.
- Produces fresh backend, frontend, route, and interaction evidence.

- [ ] Run targeted backend tests for Golden overrides, debug runs, stage retry, person tracker, and corrections.
- [ ] Run the full frontend production build.
- [ ] Run `git diff --check` on changed files.
- [ ] Start or reuse the local backend/frontend and verify `/golden` plus `/golden?analysis_id=3330183c-978b-428c-92bc-145c6a1aa2e4`.
- [ ] Check desktop and mobile page identity, nonblank content, no framework overlay, console health, complete frame counts, video/frame synchronization, draft save, and apply confirmation without submitting a destructive production reanalysis.
- [ ] Review the final diff against every confirmed design requirement and document any residual risk.
