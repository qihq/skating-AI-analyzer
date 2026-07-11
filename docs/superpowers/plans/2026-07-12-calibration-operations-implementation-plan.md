# Confidence Calibration And Synology Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Calibrate action certainty from measured outcomes, constrain reports to evidence, and make the high-accuracy pipeline resumable, cache-safe, private, and stable on Synology DS918+.

**Architecture:** Add calibration and policy as pure services over stored raw evidence. Expand pipeline checkpoints and asset metadata only where recovery requires it. Keep reporting downstream of fused evidence, and roll out flags by measured gate rather than switching the entire pipeline at once.

**Tech Stack:** Python, FastAPI, SQLAlchemy/SQLite, NumPy, existing report/provider services, filesystem asset cache, React/TypeScript, pytest, Docker/FFmpeg.

## Global Constraints

- Gates G3/G4 must pass before the new report path becomes default.
- Calibration uses `golden-train`; thresholds are selected on validation; final claims use frozen test only.
- Confidence always ships with automatic coverage, uncertainty, and stratum metrics.
- Source videos and labels survive cleanup; generated proxies/crops/cache are rebuildable.
- DS918+ analysis concurrency defaults to 1 and FFmpeg uses 1-2 threads.
- Source design: sections 12, 15, 16, 20 and Phase 7-8 of `docs/superpowers/specs/2026-07-11-high-accuracy-tracking-action-analysis-design.md`.

---

### Task 1: Calibration Dataset Export

**Files:**
- Create: `backend/scripts/export_confidence_calibration.py`
- Test: `backend/tests/test_export_confidence_calibration.py`

**Interfaces:**
- Consumes: Golden manifest plus layered predictions.
- Produces: JSONL rows containing split, stratum tags, raw evidence features, predicted status/label, truth, observability, and correctness; no personal paths/assets.

- [ ] **Step 1: Write failing export tests**

Use synthetic manifest rows. Assert train/validation/test remain identifiable, missing truth is excluded from fitting rows, and absolute paths/video hashes/face features are absent.

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_export_confidence_calibration.py -q`

Expected: FAIL on missing script.

- [ ] **Step 3: Implement deterministic export**

Feature names are versioned and include tracking coverage/conflict, visibility, model agreement, geometry quality, boundary quality, raw margins, and evidence count. Sort rows by opaque sample/action ID.

- [ ] **Step 4: Verify**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_export_confidence_calibration.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/scripts/export_confidence_calibration.py backend/tests/test_export_confidence_calibration.py
git commit -m "feat: export confidence calibration data"
```

### Task 2: Versioned Confidence Policy

**Files:**
- Create: `backend/app/services/confidence_calibration.py`
- Create: `backend/app/configs/confidence_policy.json`
- Test: `backend/tests/test_confidence_calibration.py`

**Interfaces:**
- Produces: `calibrate_action_confidence(features, policy) -> CalibratedDecision`; policy version/hash is stored with every result.

- [ ] **Step 1: Write policy and hard-cap tests**

Assert monotonic evidence raises calibrated confidence; identity conflict, poor blade visibility for Lutz/Flip, interpolated T/L, independent disagreement, and single evidence source cap status exactly as designed.

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_confidence_calibration.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement simple measured calibration**

Start with versioned binning or logistic parameters learned offline; do not add a heavy ML runtime. Apply non-negotiable evidence caps after numeric calibration. Unknown policy version fails closed to uncalibrated/uncertain.

- [ ] **Step 4: Verify**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_confidence_calibration.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/confidence_calibration.py backend/app/configs/confidence_policy.json backend/tests/test_confidence_calibration.py
git commit -m "feat: calibrate action confidence from evidence"
```

### Task 3: Fit And Validate The First Policy

**Files:**
- Create: `backend/scripts/fit_confidence_policy.py`
- Create: `docs/evaluation/confidence-calibration.md`
- Test: `backend/tests/test_fit_confidence_policy.py`

**Interfaces:**
- Consumes: Task 1 JSONL.
- Produces: candidate policy parameters from train; validation/test reliability tables, coverage, expected calibration error, and high-confidence error.

- [ ] **Step 1: Write split-isolation tests**

Assert fitting never reads validation/test labels; evaluation may read them only after parameters freeze. Test deterministic output with a seed.

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_fit_confidence_policy.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement fitting and report**

Use NumPy-only logistic fit or deterministic bins. Output reliability by status and difficult stratum, not one global score. Do not overwrite production policy automatically.

- [ ] **Step 4: Run measured calibration**

Run:

```powershell
python backend/scripts/export_confidence_calibration.py data/uploads/_debug/golden_manifest.json --output tmp/golden/calibration.jsonl
python backend/scripts/fit_confidence_policy.py tmp/golden/calibration.jsonl --candidate-output tmp/golden/confidence-policy-candidate.json --report docs/evaluation/confidence-calibration.md
```

Expected: exit 0; report includes train/validation/test counts, coverage, high-confidence error, and reliability.

- [ ] **Step 5: Review then commit selected policy/report**

Only copy the candidate to `backend/app/configs/confidence_policy.json` if validation improves without frozen-test safety regression.

```powershell
git add backend/scripts/fit_confidence_policy.py backend/tests/test_fit_confidence_policy.py backend/app/configs/confidence_policy.json docs/evaluation/confidence-calibration.md
git commit -m "test: fit evidence confidence policy"
```

### Task 4: Evidence-Only Report Context

**Files:**
- Create: `backend/app/services/evidence_report_context.py`
- Modify: `backend/app/services/report.py`
- Test: `backend/tests/test_evidence_report_context.py`
- Test: `backend/tests/test_report_video_temporal_context.py`

**Interfaces:**
- Produces: `build_evidence_report_context(fused_actions, quality) -> dict`; report provider receives this context and no source video in the new path.

- [ ] **Step 1: Write hallucination-boundary tests**

Assert uncertain Flip/Lutz remains uncertain, unobservable underrotation is not phrased as a defect, non-jump actions contain no T/A/L, and report context has no labels absent from fused results.

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_evidence_report_context.py backend/tests/test_report_video_temporal_context.py -q`

Expected: FAIL because the evidence-only report constraints are not implemented.

- [ ] **Step 3: Implement constrained context and prompt rules**

Separate observed technique, analysis limitations, and training suggestions. The model may rewrite language but may not introduce new action identity, keyframes, rotation, edge, or score.

- [ ] **Step 4: Verify**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_evidence_report_context.py backend/tests/test_report_video_temporal_context.py backend/tests/test_report_dual_path.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/evidence_report_context.py backend/app/services/report.py backend/tests/test_evidence_report_context.py backend/tests/test_report_video_temporal_context.py
git commit -m "feat: constrain reports to fused evidence"
```

### Task 5: Pipeline Checkpoint Contract

**Files:**
- Create: `backend/app/services/pipeline_checkpoints.py`
- Modify: `backend/app/models.py`
- Modify: `backend/app/database.py`
- Test: `backend/tests/test_pipeline_checkpoints.py`

**Interfaces:**
- Produces: `save_checkpoint`, `load_checkpoint`, `complete_checkpoint`, `invalidate_downstream`; stores stage, config hash, input/output asset IDs, attempts, error, and timestamps.

- [ ] **Step 1: Write migration and state tests**

Test new database and existing SQLite schema migration, idempotent stage completion, incomplete checkpoint retry, config-hash mismatch invalidation, and manual-wait state.

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_pipeline_checkpoints.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement smallest persistent model**

Prefer one `analysis_stage_checkpoints` table over many new columns. Add an index on analysis/stage and preserve existing `retry_from_stage` compatibility.

- [ ] **Step 4: Verify database compatibility**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_pipeline_checkpoints.py backend/tests/test_database_sqlite.py backend/tests/test_analysis_stage_retry.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/pipeline_checkpoints.py backend/app/models.py backend/app/database.py backend/tests/test_pipeline_checkpoints.py
git commit -m "feat: persist analysis stage checkpoints"
```

### Task 6: Resumable High-Accuracy Orchestrator

**Files:**
- Create: `backend/app/services/high_accuracy_orchestrator.py`
- Modify: `backend/app/routers/analysis.py` only at start/retry/status boundaries
- Test: `backend/tests/test_high_accuracy_orchestrator.py`
- Test: `backend/tests/test_analysis_stage_retry.py`

**Interfaces:**
- Produces explicit stages from design, including manual anchor/review waits; restarts from last complete valid checkpoint.
- Existing pipeline remains when `HIGH_ACCURACY_PIPELINE=0`.

- [ ] **Step 1: Write restart and invalidation tests**

Cover restart after proxy, forward track, MiMo boundary, report failure; anchor revision invalidates tracks/crops/actions but not source probe; prompt change invalidates its MiMo stage and downstream only.

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_high_accuracy_orchestrator.py backend/tests/test_analysis_stage_retry.py -q`

Expected: FAIL because checkpoint-aware high-accuracy orchestration is absent.

- [ ] **Step 3: Implement orchestration outside the router**

The router invokes the orchestrator and exposes status. Do not duplicate algorithms. Manual waits are valid non-failure states and survive container restart.

- [ ] **Step 4: Verify**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_high_accuracy_orchestrator.py backend/tests/test_analysis_stage_retry.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/high_accuracy_orchestrator.py backend/app/routers/analysis.py backend/tests/test_high_accuracy_orchestrator.py backend/tests/test_analysis_stage_retry.py
git commit -m "feat: resume high-accuracy analysis stages"
```

### Task 7: Asset Cache And Dependency Invalidation

**Files:**
- Create: `backend/app/services/analysis_asset_cache.py`
- Test: `backend/tests/test_analysis_asset_cache.py`

**Interfaces:**
- Produces: cache key/source dependency graph, atomic write/read, invalidate by anchor/track/prompt/model/schema/encoding revision.

- [ ] **Step 1: Write key and corruption tests**

Assert identical request hits; changed track revision/prompt/model/schema misses; changed report prompt does not invalidate tracking proxy; partial file is never returned as hit.

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_analysis_asset_cache.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement atomic cache**

Write temporary then rename; sidecar records dependencies, size, checksum, created/access time, and rebuildability. Never cache API credentials.

- [ ] **Step 4: Verify**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_analysis_asset_cache.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/analysis_asset_cache.py backend/tests/test_analysis_asset_cache.py
git commit -m "feat: cache analysis assets by dependency"
```

### Task 8: Storage Cleanup And Privacy

**Files:**
- Create: `backend/app/services/analysis_asset_retention.py`
- Modify: `backend/app/services/archive_policy.py`
- Test: `backend/tests/test_analysis_asset_retention.py`

**Interfaces:**
- Produces dry-run/execute cleanup; source/labels protected; rebuildable assets cleaned by age/disk watermarks; delete-analysis queues associated local/cloud assets.

- [ ] **Step 1: Write safety tests**

Use a temporary workspace with source, Golden label, proxy, crop, cache, incomplete asset, and out-of-workspace symlink/path. Assert dry run, source protection, path containment, and exact deletion set.

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_analysis_asset_retention.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement safe retention**

Resolve every target inside the configured asset root before deletion. Never follow computed paths outside it. Log opaque asset IDs, not face/user details. Cloud deletion failures remain queued and retryable.

- [ ] **Step 4: Verify**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_analysis_asset_retention.py backend/tests/test_admin_storage_routes.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/analysis_asset_retention.py backend/app/services/archive_policy.py backend/tests/test_analysis_asset_retention.py
git commit -m "feat: safely retain analysis assets"
```

### Task 9: DS918+ Resource Policy

**Files:**
- Create: `backend/app/services/resource_policy.py`
- Modify: `.env.example`
- Modify: `docker-compose.yml`
- Test: `backend/tests/test_resource_policy.py`

**Interfaces:**
- Produces admission decision based on active jobs, memory/disk/load config; default concurrency 1 and FFmpeg threads 2.

- [ ] **Step 1: Write policy tests**

Test one active job blocks second heavy job; API-wait stage permits only explicitly safe local work; low disk blocks new generated assets; current job can checkpoint and pause.

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_resource_policy.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement configurable policy**

Add documented env vars such as `ANALYSIS_MAX_CONCURRENCY=1`, `ANALYSIS_FFMPEG_THREADS=2`, and disk watermark. Avoid platform-specific load assumptions; unavailable metrics degrade conservatively.

- [ ] **Step 4: Verify configuration**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_resource_policy.py -q`

Expected: PASS.

Run: `docker compose config`

Expected: exit 0.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/resource_policy.py backend/tests/test_resource_policy.py .env.example docker-compose.yml
git commit -m "feat: protect synology analysis resources"
```

### Task 10: User-Facing Evidence And Uncertainty

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/pages/ReportPage.tsx`
- Modify: `frontend/src/pages/ReportWorkspacePage.tsx`
- Test/build: frontend TypeScript build

**Interfaces:**
- Displays status, alternatives, evidence, contradiction, visibility, tracking coverage/conflict, and review action; does not flatten all states into a percentage.

- [ ] **Step 1: Add typed API response fields**

Use discriminated status union and optional backward-compatible fields. UI mapping must separate `unobservable` from poor execution quality.

- [ ] **Step 2: Verify red with a temporary compile-time fixture**

Run: `npm --prefix frontend run build`

Expected: FAIL because the discriminated evidence response and renderer do not yet exist. Keep the failing fixture until Step 3 implements the types and rendering, then make it pass rather than deleting it.

- [ ] **Step 3: Implement minimal evidence panels**

Show confirmed/likely/uncertain/conflicted/unobservable labels; alternatives and limitations; target tracking warning; link to manual review for conflict. Do not create a redesign.

- [ ] **Step 4: Verify build**

Run: `npm --prefix frontend run build`

Expected: exit 0.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/api/client.ts frontend/src/pages/ReportPage.tsx frontend/src/pages/ReportWorkspacePage.tsx
git commit -m "feat: show action evidence and uncertainty"
```

### Task 11: Gate G5 Operational Runbook And Load Test

**Files:**
- Create: `scripts/high_accuracy_operational_check.py`
- Create: `docs/high-accuracy-operations-runbook.md`
- Test: `backend/tests/test_high_accuracy_operational_check.py`

**Interfaces:**
- Produces read-only checks by default and optional controlled test job; verifies dependencies, disk, model path, FFmpeg/ffprobe, flags, checkpoint DB, and cache health.

- [ ] **Step 1: Write read-only check tests**

Mock missing ffprobe, low disk, stale partial asset, unavailable YOLO, and healthy environment. Default invocation must not delete or start analysis.

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_high_accuracy_operational_check.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement check and runbook**

Document deployment flags, one-job concurrency, backup, rollback, restart recovery test, cache cleanup dry run, cloud asset deletion, and incident diagnostics.

- [ ] **Step 4: Verify on deployment-equivalent Docker**

Run:

```powershell
python scripts/high_accuracy_operational_check.py --json
docker compose config
```

Expected: exit 0 in healthy environment; JSON contains no secrets. On DS918+, run one representative 30-second video, restart the container after tracking and after MiMo boundary, and confirm checkpoint resume.

- [ ] **Step 5: Commit**

```powershell
git add scripts/high_accuracy_operational_check.py backend/tests/test_high_accuracy_operational_check.py docs/high-accuracy-operations-runbook.md
git commit -m "docs: add high-accuracy operations gate"
```

### Task 12: Final Rollout And 100-Video Acceptance

**Files:**
- Create: `docs/evaluation/high-accuracy-final-acceptance.md`
- Modify: `backend/app/services/pipeline_version.py`
- Modify: `.env.example`

**Interfaces:**
- Consumes all prior gates and frozen test expanded to at least 100 videos.
- Produces default/rollback flag decision and honest product claim.

This is the final evaluation gate, not a production-code feature task. Its red state is any unmet metric, test/build failure, insufficient test-set coverage, or missing rollback flag; only all-green evidence permits rollout.

- [ ] **Step 1: Expand frozen test coverage without tuning on it**

Reach at least 100 videos with sufficient multi-skater, crossing, occlusion, pan, zoom, blur, VFR, and action strata. New labels are reviewed; final policy remains frozen before test evaluation.

- [ ] **Step 2: Run complete verification**

```powershell
$env:PYTHONPATH='backend'
python -m pytest backend/tests -q
npm --prefix frontend run build
docker compose config
```

Expected: all exit 0.

- [ ] **Step 3: Run final repeated Golden evaluation**

Repeat nondeterministic MiMo stages at least three times. Report mean, worst, agreement, accuracy plus coverage, every required stratum, T/A/L separately, and resource/runtime distribution.

- [ ] **Step 4: Apply final criteria**

Required targets are those in the master plan. Any miss remains documented and prevents the corresponding “high accuracy” claim; do not relabel a miss as pass.

- [ ] **Step 5: Commit rollout decision**

Update default flags only for components whose gates passed. Preserve one-step rollback flags.

```powershell
git add docs/evaluation/high-accuracy-final-acceptance.md backend/app/services/pipeline_version.py .env.example
git commit -m "release: gate high-accuracy analysis pipeline"
```
