# High-Accuracy Skating Analysis Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a measured, reversible high-accuracy pipeline for manually anchored skater identity tracking, MiMo 2.5 action recognition, and precise action timing on Synology DS918+.

**Architecture:** Keep the existing pipeline operational while adding focused service modules behind default-off feature flags. Execute four independently reviewable plans in order: measurement/timebase, identity tracking, action analysis, then calibration/operations. Every algorithm change is blocked until a real Golden baseline exists.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy/SQLite, OpenCV, FFmpeg/ffprobe, Ultralytics YOLO/ByteTrack, MediaPipe, MiMo 2.5 through the existing provider layer, React/TypeScript, unittest/pytest.

## Global Constraints

- Source inputs are normally <=30 seconds, WeChat-compressed 720p handheld videos with pan, zoom, shake, occlusion, and multiple skaters.
- Synology DS918+ performs orchestration and light local vision only; do not deploy VideoMAE, SlowFast, large ReID inference, or model training there.
- A user-selected bbox at a clear timestamp is the strongest immutable identity anchor.
- Prefer `uncertain`, `conflicted`, or `unobservable` over choosing a plausible but unsupported answer.
- MiMo never decides person identity and no single MiMo call may locate, classify, score, and write the report together.
- Preserve existing APIs and stored analyses; new behavior stays behind default-off flags until its Golden gate passes.
- Do not add scenario-specific filenames, timestamps, sample IDs, or test-video geometry to production rules.
- One task, one behavior change, one test cycle, one focused commit.
- Source design: `docs/superpowers/specs/2026-07-11-high-accuracy-tracking-action-analysis-design.md`.

---

## Plan Set And Hard Gates

Execute these documents in order:

1. `2026-07-12-golden-timebase-implementation-plan.md`
2. `2026-07-12-bidirectional-tracking-implementation-plan.md`
3. `2026-07-12-mimo-action-analysis-implementation-plan.md`
4. `2026-07-12-calibration-operations-implementation-plan.md`

| Gate | Required evidence | Blocks |
|---|---|---|
| G0 Golden smoke | 3-5 labeled videos produce valid label, prediction, manifest, and eval output | Any tracker algorithm change |
| G1 Frozen baseline | 20-30 representative labeled videos; baseline JSON committed; train/validation/test split recorded | Enabling bidirectional tracking on normal analyses |
| G2 Tracking acceptance | Zero confirmed identity switches on frozen test; no stratum regression beyond plan limits | Generating target crops for MiMo by default |
| G3 Candidate acceptance | Action-candidate recall >=98% or documented lower target approved from measured baseline | Specialty classification rollout |
| G4 Action acceptance | Macro F1, T/A/L, high-confidence error, and repeatability gates pass | New report becoming default |
| G5 Operational acceptance | Restart recovery, cache invalidation, storage cleanup, and DS918+ load test pass | Production rollout |

If a gate fails, stop. Record the measured failure and create a narrowly scoped corrective task; do not continue into later plans.

## Branch And Review Strategy

- Create an isolated worktree when implementation starts; suggested branch `codex/high-accuracy-analysis`.
- Do not amend the two design commits or combine unrelated existing worktree changes.
- Each task ends in a commit. A reviewer checks contract compatibility, tests, and the relevant Golden delta before the next task.
- Merge child-plan work only after its final gate report is committed.

## Required Artifacts

```text
data/uploads/_debug/golden_manifest.json       local sensitive manifest; not committed
tmp/golden/smoke.json                          local smoke output
tmp/golden/baseline-<pipeline>.json            generated evaluation
docs/evaluation/high-accuracy-baseline.json    sanitized frozen baseline, committed
docs/evaluation/high-accuracy-baseline.md      sample strata and interpretation
data/analysis_assets/<analysis-id>/             generated/rebuildable assets
```

Do not commit raw user videos, face crops, embeddings, or personally identifying file paths.

## Design Coverage Matrix

| Design requirement | Implementation owner |
|---|---|
| Video PTS, VFR, rotation, proxy assets | Golden/timebase Tasks 4-5 |
| Clear manual anchor and multiple anchor support | Golden/timebase Task 6; tracking Task 10 |
| Forward/backward tracking and legacy compatibility | Tracking Tasks 1, 6-7 |
| Camera compensation, template protection, three states | Tracking Tasks 2-6 |
| Crossing guard, loss/relock refusal, conflict review | Tracking Tasks 5-8, 10 |
| Stable target crop and annotated overview | Tracking Task 9 |
| Golden schema, observability, splits, metrics | Golden/timebase Tasks 1-3, 7 |
| High-recall action candidates and combinations | Action Tasks 2, 5 |
| Bounded MiMo prompts, validation, cache | Action Tasks 1, 3-4 |
| Coarse and specialty classification | Action Tasks 6-8 |
| Source-frame T/A/L and rotation count | Action Tasks 9-10 |
| Independent review and evidence fusion | Action Task 11 |
| Confidence calibration and evidence caps | Operations Tasks 1-3 |
| Evidence-only reports and uncertainty UI | Operations Tasks 4, 10 |
| Checkpoints, restart, dependency invalidation | Operations Tasks 5-7 |
| Storage/privacy and DS918+ resource protection | Operations Tasks 8-9, 11 |
| 100-video final acceptance and rollback | Operations Task 12 |

## Full Verification Matrix

Run focused tests after each task. At each plan gate run:

```powershell
$env:PYTHONPATH='backend'
python -m pytest backend/tests/test_debug_runs.py backend/tests/test_eval_against_gt.py -q
python -m pytest backend/tests/test_video_precise_extract.py backend/tests/test_person_tracker.py -q
python -m pytest backend/tests/test_video_temporal.py backend/tests/test_analysis_video_temporal_pipeline.py -q
npm --prefix frontend run build
```

Expected: every command exits 0. The Golden command and expected metric direction are specified in each child plan.

## Definition Of Done

- All four child plans are complete and their gates have evidence.
- Existing tests and frontend build pass.
- Frozen test set has at least 100 videos before using the phrase “high accuracy” in product UI.
- Confirmed identity switches are zero; multi-skater identity accuracy is approximately >=95%; core-action tracking coverage is approximately >=95%.
- Action candidate recall is approximately >=98%; coarse-action macro F1 is >=90%; T/A/L median error is <=0.10 seconds and P95 is <=0.25 seconds.
- High-confidence error rate is <2%; repeat analysis agreement is >=95%.
- All metrics report automatic coverage and uncertainty rate alongside accuracy.
- DS918+ can resume after container restart and cleans rebuildable assets without deleting source or labels.

## Handoff Rule For Low-Cost Models

Give a worker only: this master plan, the active child plan, the design spec, and files named in the active task. Do not ask one worker to implement an entire child plan. Require it to return:

```text
Task completed:
Files changed:
Failing test observed:
Passing verification:
Feature flag and default:
Golden metric delta, if applicable:
Known limitations:
Commit:
```
