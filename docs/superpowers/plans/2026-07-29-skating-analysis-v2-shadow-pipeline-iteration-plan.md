# Skating Analyzer V2 Full-System Shadow Rebuild Iteration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps in the 2026-08-15 amendment use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the complete V2 Shadow pipeline while applying the approved `golden-gate-policy.v2` thresholds: G1 at 18 videos and 18 valid events, G2 at 24-30 events, Pose at 24-40 representative frames, and separately reported subtypes at a minimum of 4 samples with a target of 6.

**Architecture:** Keep the original full-system iteration order, but make a single backend gate-policy module authoritative for sample-count rules. Backend evaluators, API contracts, frontend Golden views, frozen artifacts, active documentation, and tests consume that versioned policy; quality and safety thresholds remain unchanged.

**Tech Stack:** Python 3, FastAPI, Pydantic, pytest, React 18, TypeScript, Vitest, Vite, JSON artifacts, private runtime Golden storage.

## Global Constraints

- Gate policy version is exactly `golden-gate-policy.v2`.
- G1 requires at least 18 source videos, 18 valid events, and profile minimums `jump=10`, `spin=4`, `step=2`, `spiral=2`.
- G1 retains scene coverage, at least 5 recording sessions, deduplication, source-frame validity, grouped split assignment, 2 delayed relabel reviews, and all applicable second reviews.
- G2 requires 24-30 valid events with ranges `jump=10-14`, `spin=6-8`, `step=4-5`, `spiral=4-5`.
- Pose labeling uses 24-40 representative source frames.
- A subtype needs at least 4 eligible samples for separate reporting; 6 is the recommended target.
- G3-G12 quality and safety thresholds do not change and cannot add generic video-count requirements.
- Passing a later gate on the reduced dataset is `limited_sample_candidate_pass`; insufficient applicable samples are `insufficient_sample`; neither is a broad release claim.
- Historical evidence files retain their original policy interpretation and are not rewritten.
- No implementation, test, deployment, or verification command freezes G2 without a separate explicit owner confirmation.

---

Date: 2026-07-29

Designs:

- `docs/superpowers/specs/2026-07-29-skating-analysis-v2-shadow-pipeline-design.md`
- `docs/superpowers/specs/2026-08-15-golden-gate-threshold-reduction-design.md`

This document supersedes the execution order and unchecked algorithm tasks in the July 12 high-accuracy master/child plans. Those documents remain historical references only. New implementation work starts from this plan, and any reused idea must satisfy the V2 contract and gate that owns it.

## Outcome

Deliver an identity-safe, timestamp-correct V2 skating-analysis pipeline for main-skater tracking, pose, multi-event action recognition, profile-specific key moments, and rotation count, while preserving and correctly reconnecting every current product feature, setting, model/runtime path, generated artifact, background job, and historical entry point. V2 runs in shadow mode until a newly collected, private Golden dataset plus full-product and deployment-class operational gates pass. Development happens in a separate Git worktree and nothing is merged into the main worktree until the complete program is accepted.

## Scope and Non-Negotiable Constraints

- Optimize the complete evidence chain, not five isolated outputs.
- Preserve the legacy pipeline as the current production path during development.
- Stop adding legacy scene-specific thresholds except for an approved production incident fix.
- Use exact source PTS for all temporal and physical calculations.
- Treat wrong-person analysis as more harmful than missing analysis.
- Keep `confirmed`, `uncertain`, `lost`, and `unobservable` as real output states.
- Keep raw video, crops, face data, embeddings, labels containing local paths, and private manifests out of Git.
- Use only newly selected videos in the formal V2 Golden dataset. The historical 21 unique debug videos are excluded from every V2 metric and split.
- Do not train a large model from the family dataset. Prefer pretrained inference, deterministic evidence, calibration, and small bounded components.
- Do not enable a large ReID, pose, or temporal model on DS918+ without a measured accuracy win and resource gate.
- Path A and Path B review evidence after the structured core. They do not decide identity or replace exact source timing.
- Preserve the current Animal Island/family-growth theme and four primary spaces. V2 does not create a new engineering-style primary navigation area.
- Keep frontend routes and historical reports backward compatible through a backend-owned presentation adapter.
- Keep Shadow, Golden, provider, and raw pipeline diagnostics behind parent-authorized advanced tools.
- Preserve the complete current product: analysis lifecycle, media, chat/corrections, plans, sessions, growth, skills, memories, chapters, annual collections/PDF, comparisons, shares/exports, settings, providers/models, diagnostics, backup/restore, background jobs, packaging, and historical links.
- Treat an existing capability as preserved only when its reads, writes, permissions, regeneration/revision behavior, background work, artifacts, and rollback behavior pass—not merely when its route renders.
- Make backend downstream consumers use `AnalysisFactsV2` from the same authority as `AnalysisExperienceV2`; do not move raw legacy/V2 mixing from the frontend into services.
- Keep Pose multi-person and YOLO+ByteTrack model/runtime configuration visible and testable in Resident Services. Any optional ReID/face/alternate-pose model remains a gated, fingerprinted experiment until accuracy, privacy, and DS918+ gates pass.
- No authoritative rollout occurs before every required gate passes on a frozen dataset.

## Worktree and Integration Policy

The following actions happen only when implementation begins, not while reviewing this plan.

1. Create a dedicated branch from the approved main commit, suggested name `codex/skating-analysis-v2`.
2. Create a separate worktree, suggested path `C:\Users\qihq\Documents\skating-analyzer-v2`.
3. Give the V2 worktree its own untracked runtime data directory and database. Never point experimental analysis at the main worktree's writable `data` directory.
4. Register private Golden source videos by path or copy them into the V2 runtime data directory. Do not add them to Git.
5. Commit each bounded full-stack behavior change with its tests and evidence. Include the UI changes required by that slice, but exclude unrelated visual or product refactors.
6. Keep the main worktree untouched by V2 implementation until all iterations, gates, documentation, and final review are complete.
7. If main receives necessary production changes meanwhile, integrate them into the V2 branch deliberately and rerun affected gates; do not partially merge V2 back.
8. Final integration is one user-approved operation after the final diff, database migration path, rollback plan, and verification report are reviewed.

## Runtime Isolation

Use one central mode selector rather than many unrelated flags:

```text
SKATING_ANALYSIS_PIPELINE=legacy | shadow | v2
```

- `legacy`: current production behavior; no V2 execution.
- `shadow`: legacy remains authoritative; V2 artifacts and diffs are produced separately.
- `v2`: V2 is authoritative. The explicit rollout policy may route an entire analysis back to a complete legacy experience, but it can never fill individual missing V2 fields from legacy.

Until Iteration 15 passes, the default remains `legacy`. Until final approval, production must not use `v2`.

Stage-level experiment switches may exist inside a typed V2 configuration object, but must be recorded in a canonical fingerprint. They are not scattered environment-variable decisions inside algorithm modules.

## Versioned Artifact Layout

Private, local runtime artifacts:

```text
<V2_DATA_DIR>/golden/v2/manifest.json
<V2_DATA_DIR>/golden/v2/videos/<private files or references>
<V2_DATA_DIR>/golden/v2/labels/<event-id>.json
<V2_DATA_DIR>/analysis-assets/<analysis-id>/v2/run-manifest.json
<V2_DATA_DIR>/analysis-assets/<analysis-id>/v2/observations.jsonl
<V2_DATA_DIR>/analysis-assets/<analysis-id>/v2/tracks.jsonl
<V2_DATA_DIR>/analysis-assets/<analysis-id>/v2/poses.jsonl
<V2_DATA_DIR>/analysis-assets/<analysis-id>/v2/events.json
<V2_DATA_DIR>/analysis-assets/<analysis-id>/v2/claims.json
<V2_DATA_DIR>/evaluation/<dataset-id>/<pipeline-fingerprint>/report.json
```

Committed, sanitized artifacts:

```text
docs/evaluation/v2/dataset-summary.md
docs/evaluation/v2/legacy-baseline.json
docs/evaluation/v2/legacy-baseline.md
docs/evaluation/v2/gate-<name>.json
docs/evaluation/v2/gate-<name>.md
```

Sanitized reports contain dataset IDs, strata, aggregate counts, metrics, confidence intervals, fingerprints, and redacted sample aliases. They contain no source paths, video frames, names, faces, or embeddings.

## Proposed Core Package Boundary

Create one backend-owned algorithm package:

```text
backend/app/analysis_v2/
  contracts.py
  config.py
  fingerprints.py
  timebase.py
  observations.py
  tracking/
  pose/
  events/
  keymoments/
  rotation/
  review/
  fusion/
  presentation/
  evaluation/
  orchestration.py
```

Rules:

- Modules under `analysis_v2` depend on explicit contracts, not ORM models or FastAPI request objects.
- The router calls an orchestration adapter; it does not contain algorithm decisions.
- Legacy `app/services` modules enter V2 only through narrow proposal adapters.
- The standalone analysis pack consumes generated adapters or a versioned package snapshot. No V2 source file is manually maintained in two places.
- Pure evaluators can run without a live database or external model provider.

The modern frontend adds a bounded feature package rather than spreading V2 field checks across existing pages:

```text
frontend/src/analysis-v2/
  contracts.ts
  api.ts
  adapters.ts
  statusLanguage.ts
  timeline.ts
  components/
```

- Backend Pydantic schemas own the wire contract.
- A checked schema artifact and cross-language fixtures protect TypeScript compatibility.
- Backend presenters return one `AnalysisExperienceV2` for legacy and V2 records; the frontend validates and selects from that model without normalizing raw algorithm fields.
- Existing pages migrate to selectors/components over this model; they do not inspect raw Path A/B or V2 algorithm artifacts.

## Gate Overview

| Gate | Evidence | Blocks |
|---|---|---|
| G0 Worktree isolation | Separate branch, runtime data, database, legacy smoke tests | Any V2 implementation |
| G1 Golden pilot | 18 videos and 18 valid events, 10/4/2/2 profile coverage, review, dedupe, source-frame, and split checks | Algorithm threshold calibration |
| G2 Baseline | 24-30 valid events, 10-14/6-8/4-5/4-5 profile ranges, frozen split, trustworthy evaluator, legacy report | Limited-sample V2 candidate claims |
| G3 Timebase | PTS/VFR/metamorphic tests pass; no physical metric uses sampled-frame count | Tracking and biomechanics switch |
| G4 Tracking | Zero confirmed identity switches; accuracy/coverage gates pass | Authoritative V2 pose |
| G5 Pose | Zero wrong-person skeletons; pose quality gates pass | Pose-dependent event switch |
| G6 Event proposals | Proposal recall at least 98% with coverage reported | Classifier rollout |
| G7 Action classification | Macro F1 at least 90%, high-confidence errors below 2% | V2 event authority |
| G8 Key moments | T/A/L median at most 0.10 s, P95 at most 0.25 s | Key-moment authority |
| G9 Rotation | Observable MAE at most 0.25 turns, class accuracy at least 90% | Rotation authority |
| G10 Evidence review | A/B conflicts are bounded; reports cannot invent claims | V2 report authority |
| G11 Shadow stability | Repeated consistency at least 95%; no unexplained stage drift | Production candidate |
| G12 Operations | DS918+ resource, restart, cleanup, privacy, migration pass | Controlled candidate deployment from the V2 worktree |
| UX1 Experience contract | Legacy/V2 presenter, schema compatibility, fixtures, and route fallback pass | Modern frontend consumption of V2 |
| UX2 Core V2 experience | Multi-event timeline, uncertainty, pose, rotation, and confirmation flows pass | Family-facing V2 rollout |
| UX3 Entry and theme | Four-space navigation, advanced-tool isolation, Animal Island visual/accessibility matrix pass | Final candidate approval |
| FP1 Feature inventory | Every current route/API/job/model/setting/artifact has an owner, fixture, and rollback expectation | Iteration 1 and any capability retirement |
| FP2 Downstream facts | Chat, corrections, plans, compare, growth, skills, memories, monthly/annual, shares, and exports consume same-authority facts | V2 family authority |
| FP3 Full-product parity | Complete route/API/write/job/settings/model/data-safety/packaging matrix passes in legacy, shadow, V2, and rollback modes as applicable | Controlled candidate deployment |

Percentage gates always include the numerator, denominator, rejection rate, confidence interval, and per-stratum breakdown. A percentage based on too few samples does not satisfy a gate by itself.

Every formal G3-G12 artifact produced under `golden-gate-policy.v2` must merge this policy-owned metadata shape instead of inventing gate-specific release language:

```json
{
  "gate_policy_version": "golden-gate-policy.v2",
  "evidence_scope": "limited_sample",
  "status": "limited_sample_candidate_pass | insufficient_sample | blocked_waiting_for_frozen_candidate | diagnostic_failed_or_insufficient",
  "gate_passed": false,
  "release_claim": false
}
```

`gate_passed` may be true only for `limited_sample_candidate_pass`; `release_claim` remains false. G3-G5 and G10-G12 must call the same helper when their artifact writers are implemented in their owning iterations. Current G6-G9 artifact writers are migrated by Task A5 below.

## Program Sequence and Ownership

The iterations are sequential at their gate boundaries. Within an iteration, tests, UI support, evaluator work, and algorithm work may proceed in parallel only when they do not share an unstable contract.

| Program block | Iterations | Primary owner action | User action | Exit evidence |
|---|---:|---|---|---|
| Isolation and labels | 0-2 | Build isolated runtime, contracts, and labeling workflow | Use the verified 18-video Golden catalog as the fixed G1 quantity baseline | Safe worktree plus usable private catalog |
| Measurement | 3-4 | Repair evaluator, complete the current G1 governance work, then add only the six or more targeted events needed for G2 | Assign splits, complete reviews, then prioritize spin, step, and spiral gaps | G1 report, then a limited-sample G2 baseline |
| Foundations | 5-7 | Implement contracts, experience API, frontend adapter, exact PTS, observations, camera motion, proposals | Review representative source-frame alignment and family terminology | G3, UX1, and proposal diagnostics |
| Identity and pose | 8-9 | Build identity fusion and trustworthy pose | Add anchors or review ambiguous crossings when requested | G4 and G5 reports |
| Events and timing | 10-12 | Build proposals, classifiers, and source-frame moments | Review incorrect/ambiguous action labels, not production rules | G6-G8 reports |
| Rotation and review | 13-14 | Build multi-signal rotation, claim-level A/B fusion, and the complete family V2 experience | Double-review ambiguous turn counts, report claims, and review wording | G9, G10, and UX2 reports |
| Productization | 15-16 | Shadow orchestration, advanced review, entry synchronization, calibration, and DS918+ hardening | Approve resource/accuracy and entry-point tradeoffs | G11, G12, and UX3 reports |
| Pre-merge validation | 17-19 | Final audit, worktree-built controlled rollout, and cleanup | Approve the exact final merge candidate | Merge/rollback evidence |

### Effort expectations

Calendar time depends mainly on video collection, labeling, external-model latency, and how often a gate exposes a genuine model limitation. Use these as planning ranges, not deadlines:

- Iterations 0-4: approximately 1-2 engineering weeks plus 4-8 hours of owner labeling spread across several sessions.
- Iterations 5-9: approximately 2-4 engineering weeks.
- Iterations 10-14: approximately 3-5 engineering weeks.
- Iterations 15-17: approximately 1-3 engineering weeks plus DS918+ observation time.
- Iterations 18-19: controlled observation period, typically at least 2-4 weeks before legacy retirement.

No later estimate authorizes skipping a failed gate. If the Golden set exposes a need to replace a base detector or pose model, schedule a separate bounded bakeoff inside the owning iteration rather than silently extending the architecture.

## User Labeling Workload

### Revised execution order (2026-08-15)

The private Golden catalog was verified at revision 70 with 18 videos, 18 schema-valid events, 17 recording sessions, no duplicate-source warning, complete G1 scene coverage, and profile counts of 10 jumps, 4 spins, 2 steps, and 2 spirals. This verified catalog fixes the G1 quantity and profile baseline; future uploads do not automatically raise it.

1. **Apply `golden-gate-policy.v2`.** Centralize the approved counts and make progress, exports, frozen artifacts, UI, tests, and active documentation consume the versioned policy.
2. **Finish G1 governance without adding videos.** Assign every event to development, validation, or frozen-test without crossing source/group/session boundaries; complete two delayed relabel reviews; complete all ambiguous-rotation and applicable frozen-crossing reviews.
3. **Run the 18-event G1 evaluator.** Record raw denominators, coverage, refusals, errors, latency, resource behavior, and confidence intervals. Passing G1 remains diagnostic and authorizes calibration, not broad accuracy claims.
4. **Expand only toward G2 gaps.** Add at least two spins, two steps, and two spirals from real actions, then stop when the dataset reaches a valid 24-30 total within the approved profile ranges. Do not add jumps merely to raise the total.
5. **Freeze only after explicit owner confirmation.** The implementation and its tests verify readiness and route availability but never send the G2 freeze confirmation automatically.
6. **Use reduced-sample evidence honestly.** G3-G12 keep their existing accuracy and safety thresholds, report actual denominators and confidence intervals, and use `limited_sample_candidate_pass` or `insufficient_sample` rather than broad release language.

The owner does not annotate every frame or every joint. For most events:

- select the action interval and family;
- confirm the main skater;
- record three profile moments where applicable;
- record rotation count/range and observability where applicable;
- draw 3-8 identity boxes;
- add a short ambiguity or scene tag when needed.

Difficult crossing/occlusion events receive denser boxes. The initial pose subset requires 24-40 representative frames across the whole dataset, not per video. The development team should keep the UI fast enough that an ordinary event takes roughly 3-6 minutes and a difficult event roughly 8-15 minutes; if actual timing is materially worse, improve the workflow before requesting the targeted G2 additions.

## 2026-08-15 Golden Gate Policy V2 Implementation Amendment

Execute this amendment before any remaining formal G1/G2 evaluation or later-gate acceptance claim. The tasks modify the already implemented Iterations 1-4, 9, and 11-13 without changing the surrounding full-system sequence.

### File responsibility map

| File | Responsibility after this amendment |
|---|---|
| `backend/app/analysis_v2/evaluation/gate_policy.py` | Single typed source for G1, G2, Pose, subtype, policy-version, and limited-sample evidence rules |
| `backend/app/analysis_v2/evaluation/pilot_store.py` | Calculate G1 progress from the central policy and produce governance-focused next actions |
| `backend/app/analysis_v2/evaluation/golden_store.py` | Export privacy-safe policy metadata with the sanitized catalog summary |
| `backend/app/analysis_v2/evaluation/g2_baseline.py` | Enforce G2 total/profile ranges and persist the policy version in freeze and baseline artifacts |
| `backend/app/analysis_v2/action_classification.py` | Use the approved subtype sample minimum instead of a private hard-coded value |
| `backend/app/analysis_v2/evaluation/g8_moments.py` | Report a limited-sample candidate result without converting it into a broad release claim |
| `backend/app/analysis_v2/evaluation/g9_rotation.py` | Report a limited-sample candidate result without converting it into a broad release claim |
| `backend/app/routers/golden_v2.py` | Validate and serialize policy-aware G1/G2 API contracts |
| `frontend/src/analysis-v2/golden-contracts.ts` | Mirror the policy-aware API types |
| `frontend/src/analysis-v2/components/GoldenPilotDashboard.tsx` | Render policy-provided G1 counts and actual governance blockers |
| `frontend/src/analysis-v2/components/GoldenG2StatusCard.tsx` | Render the G2 total/profile ranges and targeted collection gaps |
| `frontend/src/analysis-v2/components/GoldenAnnotationWorkspace.tsx` | Explain the fixed G1 baseline, targeted G2 additions, and 24-40 Pose-frame goal |
| Active V2 design, labeling, and development docs | Describe policy v2; historical evidence retains its original policy meaning |

### Task A1: Add the typed central gate policy

**Files:**

- Create: `backend/app/analysis_v2/evaluation/gate_policy.py`
- Create: `backend/tests/analysis_v2/test_gate_policy.py`

**Interfaces:**

- Produces: `GOLDEN_GATE_POLICY: GoldenGatePolicy`
- Produces: `gate_policy_summary() -> dict[str, object]`
- Produces: `artifact_gate_policy_version(payload: Mapping[str, object]) -> str`
- Produces: `artifact_uses_current_policy(payload: Mapping[str, object]) -> bool`
- Produces: `classify_limited_sample_evidence(applicable_n: int, thresholds_met: bool, protocol_met: bool) -> tuple[str, bool]`
- Consumed by: Tasks A2, A3, and A5

- [ ] **Step 1: Write the failing policy contract tests**

Create `backend/tests/analysis_v2/test_gate_policy.py`:

```python
from app.analysis_v2.evaluation.gate_policy import (
    CountRange,
    GOLDEN_GATE_POLICY,
    LEGACY_GATE_POLICY_VERSION,
    artifact_gate_policy_version,
    artifact_uses_current_policy,
    classify_limited_sample_evidence,
    gate_policy_summary,
    limited_sample_gate_metadata,
)


def test_policy_v2_contains_the_approved_thresholds() -> None:
    policy = GOLDEN_GATE_POLICY
    assert policy.schema_version == "golden-gate-policy.v2"
    assert policy.effective_date == "2026-08-15"
    assert policy.g1_source_video_minimum == 18
    assert policy.g1_valid_event_minimum == 18
    assert policy.g1_profile_minimums == {"jump": 10, "spin": 4, "step": 2, "spiral": 2}
    assert policy.g1_recording_session_minimum == 5
    assert policy.g1_delayed_review_minimum == 2
    assert policy.g2_event_range.model_dump() == {"minimum": 24, "maximum": 30}
    assert {key: value.model_dump() for key, value in policy.g2_profile_ranges.items()} == {
        "jump": {"minimum": 10, "maximum": 14},
        "spin": {"minimum": 6, "maximum": 8},
        "step": {"minimum": 4, "maximum": 5},
        "spiral": {"minimum": 4, "maximum": 5},
    }
    assert policy.pose_frame_range.model_dump() == {"minimum": 24, "maximum": 40}
    assert policy.subtype_reporting_minimum == 4
    assert policy.subtype_reporting_target == 6


def test_policy_summary_returns_a_detached_serializable_copy() -> None:
    first = gate_policy_summary()
    first["g1_profile_minimums"]["jump"] = 999
    second = gate_policy_summary()
    assert second["g1_profile_minimums"]["jump"] == 10


def test_count_range_rejects_an_inverted_policy() -> None:
    with pytest.raises(ValueError, match="maximum must be greater than or equal to minimum"):
        CountRange(minimum=30, maximum=24)


def test_unversioned_artifacts_remain_legacy_without_rewriting_them() -> None:
    assert LEGACY_GATE_POLICY_VERSION == "golden-gate-policy.v1"
    assert artifact_gate_policy_version({}) == "golden-gate-policy.v1"
    assert artifact_uses_current_policy({}) is False
    assert artifact_gate_policy_version({"gate_policy_version": "golden-gate-policy.v2"}) == "golden-gate-policy.v2"
    assert artifact_uses_current_policy({"gate_policy_version": "golden-gate-policy.v2"}) is True


def test_limited_sample_evidence_never_becomes_a_broad_release_claim() -> None:
    assert classify_limited_sample_evidence(0, False, True) == ("insufficient_sample", False)
    assert classify_limited_sample_evidence(4, True, False) == ("blocked_waiting_for_frozen_candidate", False)
    assert classify_limited_sample_evidence(4, True, True) == ("limited_sample_candidate_pass", True)
    assert classify_limited_sample_evidence(4, False, True) == ("diagnostic_failed_or_insufficient", False)
    assert limited_sample_gate_metadata(4, True, True) == {
        "gate_policy_version": "golden-gate-policy.v2",
        "evidence_scope": "limited_sample",
        "status": "limited_sample_candidate_pass",
        "gate_passed": True,
        "release_claim": False,
    }
```

Add `import pytest` at the top of the test file.

- [ ] **Step 2: Run the tests and verify the module is missing**

Run:

```powershell
python -m pytest backend/tests/analysis_v2/test_gate_policy.py -q
```

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'app.analysis_v2.evaluation.gate_policy'`.

- [ ] **Step 3: Implement the minimal typed policy**

Create `backend/app/analysis_v2/evaluation/gate_policy.py`:

```python
from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import Field, model_validator

from app.analysis_v2.contracts import ContractModel


class CountRange(ContractModel):
    minimum: int = Field(ge=0)
    maximum: int = Field(ge=0)

    @model_validator(mode="after")
    def ordered(self) -> "CountRange":
        if self.maximum < self.minimum:
            raise ValueError("maximum must be greater than or equal to minimum")
        return self


class GoldenGatePolicy(ContractModel):
    schema_version: Literal["golden-gate-policy.v2"] = "golden-gate-policy.v2"
    effective_date: Literal["2026-08-15"] = "2026-08-15"
    evidence_scope: Literal["limited_sample"] = "limited_sample"
    g1_source_video_minimum: int = 18
    g1_valid_event_minimum: int = 18
    g1_profile_minimums: dict[str, int] = Field(
        default_factory=lambda: {"jump": 10, "spin": 4, "step": 2, "spiral": 2}
    )
    g1_scene_minimums: dict[str, int] = Field(default_factory=lambda: {
        "normal": 1,
        "multi-skater": 1,
        "crossing/occlusion": 1,
        "small/distant target": 1,
        "pan/zoom": 1,
        "blur/compression": 1,
    })
    g1_recording_session_minimum: int = 5
    g1_delayed_review_minimum: int = 2
    g2_event_range: CountRange = Field(default_factory=lambda: CountRange(minimum=24, maximum=30))
    g2_profile_ranges: dict[str, CountRange] = Field(default_factory=lambda: {
        "jump": CountRange(minimum=10, maximum=14),
        "spin": CountRange(minimum=6, maximum=8),
        "step": CountRange(minimum=4, maximum=5),
        "spiral": CountRange(minimum=4, maximum=5),
    })
    pose_frame_range: CountRange = Field(default_factory=lambda: CountRange(minimum=24, maximum=40))
    subtype_reporting_minimum: int = 4
    subtype_reporting_target: int = 6


GOLDEN_GATE_POLICY = GoldenGatePolicy()
LEGACY_GATE_POLICY_VERSION = "golden-gate-policy.v1"


def artifact_gate_policy_version(payload: Mapping[str, object]) -> str:
    value = payload.get("gate_policy_version")
    return str(value) if isinstance(value, str) and value else LEGACY_GATE_POLICY_VERSION


def artifact_uses_current_policy(payload: Mapping[str, object]) -> bool:
    return artifact_gate_policy_version(payload) == GOLDEN_GATE_POLICY.schema_version


def gate_policy_summary() -> dict[str, object]:
    return GOLDEN_GATE_POLICY.model_dump(mode="json")


def classify_limited_sample_evidence(
    applicable_n: int,
    thresholds_met: bool,
    protocol_met: bool,
) -> tuple[str, bool]:
    if applicable_n <= 0:
        return "insufficient_sample", False
    if thresholds_met and protocol_met:
        return "limited_sample_candidate_pass", True
    if thresholds_met:
        return "blocked_waiting_for_frozen_candidate", False
    return "diagnostic_failed_or_insufficient", False


def limited_sample_gate_metadata(
    applicable_n: int,
    thresholds_met: bool,
    protocol_met: bool,
) -> dict[str, object]:
    status, gate_passed = classify_limited_sample_evidence(applicable_n, thresholds_met, protocol_met)
    return {
        "gate_policy_version": GOLDEN_GATE_POLICY.schema_version,
        "evidence_scope": GOLDEN_GATE_POLICY.evidence_scope,
        "status": status,
        "gate_passed": gate_passed,
        "release_claim": False,
    }
```

- [ ] **Step 4: Run the policy tests**

Run:

```powershell
python -m pytest backend/tests/analysis_v2/test_gate_policy.py -q
```

Expected: `5 passed`.

- [ ] **Step 5: Commit only the policy slice**

Run:

```powershell
git add -- backend/app/analysis_v2/evaluation/gate_policy.py backend/tests/analysis_v2/test_gate_policy.py
git commit -m "feat: centralize golden gate policy v2"
```

Expected: one commit containing only the two listed files.

### Task A2: Make G1 progress and sanitized exports policy-aware

**Files:**

- Modify: `backend/app/analysis_v2/evaluation/pilot_store.py`
- Modify: `backend/app/analysis_v2/evaluation/pilot_evaluator.py`
- Modify: `backend/app/analysis_v2/evaluation/golden_store.py`
- Modify: `backend/app/routers/golden_v2.py`
- Modify: `backend/tests/analysis_v2/test_pilot_store.py`
- Modify: `backend/tests/analysis_v2/test_pilot_evaluator.py`
- Modify: `backend/tests/analysis_v2/test_golden_store.py`

**Interfaces:**

- Consumes: `GOLDEN_GATE_POLICY`, `gate_policy_summary()`, and `artifact_gate_policy_version()` from Task A1
- Produces in G1 progress: `gate_policy_version`, `evidence_scope`, `requirements.source_video_count`, and `next_actions`
- Produces in sanitized export: a policy-aware `gate_template`
- Persists on every newly generated evaluator private report, sanitized report, gate artifact, and status artifact: `gate_policy_version="golden-gate-policy.v2"` and `evidence_scope="limited_sample"`
- Includes `gate_policy_version` in every new evaluator `deterministic_fingerprint`, so a policy change cannot reuse a result identity from another policy
- Preserves existing unversioned evaluator artifacts byte-for-byte; callers interpret their missing version as `golden-gate-policy.v1`, while current-policy status requires a new v2 run
- Preserves for compatibility: `next_best_videos` and `required_new_events`, both derived from policy v2

- [ ] **Step 1: Add a reusable 18-source/18-event fixture to the pilot-store tests**

Add these imports and helper to `backend/tests/analysis_v2/test_pilot_store.py`:

```python
from app.analysis_v2.evaluation.golden_schema import GoldenDatasetV2


def _policy_dataset(*, assigned_splits: bool = True, profiles: list[str] | None = None) -> GoldenDatasetV2:
    selected_profiles = profiles or (["jump"] * 10 + ["spin"] * 4 + ["step"] * 2 + ["spiral"] * 2)
    created_at = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    revision = {
        "revision": 2,
        "parent_revision": 1,
        "annotator_alias": "owner",
        "provenance": "human_annotation",
        "created_at": created_at,
    }
    scene_values = ["normal", "multi-skater", "crossing", "small", "pan", "blur"]
    sources: list[dict[str, object]] = []
    events: list[dict[str, object]] = []
    for index, profile in enumerate(selected_profiles):
        source_hash = f"{index + 1:064x}"
        start = 1.0
        end = 3.0
        sources.append({
            "source_sha256": source_hash,
            "duration_pts": 5.0,
            "width": 1280,
            "height": 720,
            "timebase": {"numerator": 1, "denominator": 90_000, "source_fps": 30, "is_vfr": False},
            "private_source_reference": f"videos/source-{index + 1}.mp4",
            "recording_session_id": f"session-{index + 1}",
            "grouping_id": f"group-{index + 1}",
            "redacted_alias": f"source-{index + 1:03d}",
        })
        event: dict[str, object] = {
            "event_id": f"event-{index + 1:03d}",
            "source_sha256": source_hash,
            "start_pts": start,
            "end_pts": end,
            "profile": profile,
            "observability": "observable",
            "strata": [scene_values[index % len(scene_values)]],
            "ambiguity_tags": [],
            "failure_tags": [],
            "annotator_confidence": 0.9,
            "main_skater_confirmed": True,
            "split": ("development", "validation", "frozen_test")[index % 3] if assigned_splits else None,
            "challenge_intervals": [],
            "revision": revision,
        }
        if profile == "jump":
            event["jump"] = {
                "takeoff": {"pts": 1.4, "source_frame_index": 42},
                "apex": {"pts": 2.0, "source_frame_index": 60},
                "landing": {"pts": 2.6, "source_frame_index": 78},
            }
        elif profile == "spin":
            event["spin"] = {
                "entry": {"start_pts": 1.0, "end_pts": 1.5},
                "main": {"start_pts": 1.5, "end_pts": 2.5},
                "exit": {"start_pts": 2.5, "end_pts": 3.0},
            }
        else:
            event[profile] = {
                "phase": {"start_pts": 1.0, "end_pts": 3.0},
                "representative_moment": {"pts": 2.0, "source_frame_index": 60},
            }
        events.append(event)
    return GoldenDatasetV2.model_validate({
        "dataset_id": "golden-v2-private-catalog",
        "revision": revision,
        "sources": sources,
        "events": events,
        "tracks": [],
        "poses": [],
    })
```

- [ ] **Step 2: Write failing G1 policy tests**

Append to `backend/tests/analysis_v2/test_pilot_store.py`:

```python
def _save_policy_dataset(store: GoldenCatalogStore, dataset: GoldenDatasetV2) -> None:
    store.ensure_initialized()
    store.save(dataset, expected_revision=1)


def test_verified_18_event_shape_meets_count_profile_scene_and_session_requirements(tmp_path: Path) -> None:
    store = GoldenCatalogStore(tmp_path / "golden")
    _save_policy_dataset(store, _policy_dataset(assigned_splits=False))
    progress = collection_progress(store.read(), store)
    assert progress["gate_policy_version"] == "golden-gate-policy.v2"
    assert progress["evidence_scope"] == "limited_sample"
    assert progress["requirements"]["source_video_count"] == {"count": 18, "target": 18, "passed": True}
    assert progress["requirements"]["event_count"]["passed"] is True
    assert progress["requirements"]["schema_valid"]["passed"] is True
    assert {item["key"]: item["missing"] for item in progress["profiles"]} == {
        "jump": 0, "spin": 0, "step": 0, "spiral": 0,
    }
    assert progress["requirements"]["split_grouping"]["passed"] is False
    assert "assign_consistent_splits" in progress["next_actions"]


def test_g1_becomes_ready_after_two_delayed_reviews_and_complete_splits(tmp_path: Path) -> None:
    store = GoldenCatalogStore(tmp_path / "golden")
    _save_policy_dataset(store, _policy_dataset())
    reviewed_at = datetime.now(timezone.utc).isoformat()
    for event_id in ("event-001", "event-002"):
        store.add_review_attestation(event_id, {
            "review_type": "delayed_relabel",
            "reviewer_alias": "owner",
            "reviewed_at": reviewed_at,
            "event_revision": 2,
        })
    progress = collection_progress(store.read(), store)
    assert progress["requirements"]["delayed_review"] == {"count": 2, "target": 2, "passed": True}
    assert progress["status"] == "ready_for_evaluator"


def test_g1_rejects_17_sources_or_a_missing_profile_minimum(tmp_path: Path) -> None:
    short_store = GoldenCatalogStore(tmp_path / "short")
    _save_policy_dataset(short_store, _policy_dataset(profiles=["jump"] * 10 + ["spin"] * 4 + ["step"] * 2 + ["spiral"]))
    assert collection_progress(short_store.read(), short_store)["requirements"]["source_video_count"]["passed"] is False

    missing_store = GoldenCatalogStore(tmp_path / "missing-profile")
    _save_policy_dataset(missing_store, _policy_dataset(profiles=["jump"] * 11 + ["spin"] * 4 + ["step"] * 2 + ["spiral"]))
    spiral = next(item for item in collection_progress(missing_store.read(), missing_store)["profiles"] if item["key"] == "spiral")
    assert spiral == {"key": "spiral", "count": 1, "target": 2, "missing": 1}


def test_new_diagnostic_artifacts_are_stamped_with_policy_v2(tmp_path: Path) -> None:
    store = GoldenCatalogStore(tmp_path / "golden")
    evaluator = PilotEvaluationStore(store)
    bundle = PilotPredictionBundle.model_validate({
        "pipeline_fingerprint": "pipeline-12345678",
        "evaluation_masks": ["tracking"],
        "predictions": [],
    })
    evaluator.run(bundle, diagnostic_snapshot=True)
    for path in (
        evaluator.private_report_path,
        evaluator.sanitized_report_path,
        evaluator.gate_path,
        evaluator.status_path,
    ):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["gate_policy_version"] == "golden-gate-policy.v2"
        assert payload["evidence_scope"] == "limited_sample"


def test_unversioned_evaluator_report_is_read_as_legacy_without_rewrite(tmp_path: Path) -> None:
    store = GoldenCatalogStore(tmp_path / "golden")
    report_path = store.root / "evaluation" / "sanitized-report.json"
    status_path = store.root / "evaluation" / "status.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps({"schema_version": "golden-pilot-sanitized-report.v1"}), encoding="utf-8")
    status_path.write_text(json.dumps({
        "status": "passed_for_pilot_only",
        "evaluator_version": "golden-pilot-evaluator.v1",
        "diagnostic_only": True,
        "message": "legacy run",
    }), encoding="utf-8")
    report_before = report_path.read_bytes()
    status_before = status_path.read_bytes()
    evaluator = PilotEvaluationStore(store)
    payload = evaluator.sanitized_result()
    status = evaluator.status()
    assert payload is not None
    assert artifact_gate_policy_version(payload) == "golden-gate-policy.v1"
    assert status["status"] == "not_run"
    assert status["gate_policy_version"] == "golden-gate-policy.v2"
    assert "Legacy evaluator evidence remains readable" in status["message"]
    assert report_path.read_bytes() == report_before
    assert status_path.read_bytes() == status_before
```

Add this import to `backend/tests/analysis_v2/test_pilot_store.py`:

```python
from app.analysis_v2.evaluation.gate_policy import artifact_gate_policy_version
```

Append to `backend/tests/analysis_v2/test_pilot_evaluator.py` and add `canonical_fingerprint` to its existing evaluator imports:

```python
def test_policy_v2_is_stamped_and_part_of_the_result_fingerprint() -> None:
    private, sanitized = evaluate_pilot(_dataset(), _bundle([_identity()], ["tracking"]))
    assert private["gate_policy_version"] == "golden-gate-policy.v2"
    assert private["evidence_scope"] == "limited_sample"
    assert sanitized["gate_policy_version"] == "golden-gate-policy.v2"
    assert sanitized["evidence_scope"] == "limited_sample"
    expected = canonical_fingerprint({
        "gate_policy_version": "golden-gate-policy.v2",
        "evaluator_version": private["evaluator_version"],
        "dataset_fingerprint": private["dataset_fingerprint"],
        "pipeline_fingerprint": private["pipeline_fingerprint"],
        "evaluation_masks": private["evaluation_masks"],
        "aggregate": private["aggregate"],
        "diagnostics": private["events"],
    })
    assert private["deterministic_fingerprint"] == expected
    assert sanitized["deterministic_fingerprint"] == expected
```

Append to `backend/tests/analysis_v2/test_golden_store.py`:

```python
def test_sanitized_export_carries_policy_v2_without_private_data(tmp_path: Path) -> None:
    store = GoldenCatalogStore(tmp_path / "golden")
    payload = store.sanitized_export()
    assert payload["gate_template"]["gate_policy_version"] == "golden-gate-policy.v2"
    assert payload["gate_template"]["required_source_videos"] == 18
    assert payload["gate_template"]["required_valid_events"] == 18
    assert payload["gate_template"]["profile_minimums"] == {"jump": 10, "spin": 4, "step": 2, "spiral": 2}
    assert payload["gate_template"]["required_new_events"] == 18
    assert payload["gate_template"]["pose_frame_range"] == [24, 40]
    assert payload["gate_template"]["g2_event_range"] == [24, 30]
    assert payload["gate_template"]["g2_profile_ranges"] == {
        "jump": [10, 14], "spin": [6, 8], "step": [4, 5], "spiral": [4, 5],
    }
```

- [ ] **Step 3: Run the G1/export tests and verify legacy values fail**

Run:

```powershell
python -m pytest backend/tests/analysis_v2/test_pilot_store.py backend/tests/analysis_v2/test_pilot_evaluator.py backend/tests/analysis_v2/test_golden_store.py -q
```

Expected: FAIL because the response and newly written evaluator artifacts lack `gate_policy_version`, `source_video_count`, and the new 18-event targets.

- [ ] **Step 4: Replace local G1 constants with policy-derived values**

In `backend/app/analysis_v2/evaluation/pilot_store.py`:

```python
from app.analysis_v2.evaluation.gate_policy import GOLDEN_GATE_POLICY

PROFILE_TARGETS = GOLDEN_GATE_POLICY.g1_profile_minimums
SCENE_TARGETS = GOLDEN_GATE_POLICY.g1_scene_minimums
```

Replace the G1 count/review requirement construction with:

```python
required_delayed = GOLDEN_GATE_POLICY.g1_delayed_review_minimum
requirements = {
    "source_video_count": {
        "count": len(dataset.sources),
        "target": GOLDEN_GATE_POLICY.g1_source_video_minimum,
        "passed": len(dataset.sources) >= GOLDEN_GATE_POLICY.g1_source_video_minimum,
    },
    "event_count": {
        "count": len(dataset.events),
        "target": GOLDEN_GATE_POLICY.g1_valid_event_minimum,
        "passed": len(dataset.events) >= GOLDEN_GATE_POLICY.g1_valid_event_minimum,
    },
    "recording_sessions": {
        "count": session_count,
        "target": GOLDEN_GATE_POLICY.g1_recording_session_minimum,
        "passed": session_count >= GOLDEN_GATE_POLICY.g1_recording_session_minimum,
    },
    "schema_valid": {
        "count": valid_events,
        "target": GOLDEN_GATE_POLICY.g1_valid_event_minimum,
        "passed": valid_events >= GOLDEN_GATE_POLICY.g1_valid_event_minimum,
    },
    "split_grouping": {"issues": split_issues, "passed": not split_issues},
    "duplicates": {"issues": duplicate_issues, "passed": not duplicate_issues},
    "delayed_review": {"count": delayed, "target": required_delayed, "passed": delayed >= required_delayed},
    "ambiguous_rotation_double_review": {
        "count": double_reviewed["ambiguous"],
        "target": ambiguous_required,
        "passed": double_reviewed["ambiguous"] >= ambiguous_required,
    },
    "frozen_crossing_double_review": {
        "count": double_reviewed["frozen_crossing"],
        "target": crossing_required,
        "passed": double_reviewed["frozen_crossing"] >= crossing_required,
    },
    "source_frame_identity": {"issues": frame_identity_issues, "passed": not frame_identity_issues},
}
```

Build `next_actions` from failed governance checks and return policy metadata:

```python
next_actions: list[str] = []
if not requirements["split_grouping"]["passed"]:
    next_actions.append("assign_consistent_splits")
if not requirements["delayed_review"]["passed"]:
    next_actions.append("complete_delayed_reviews")
if not requirements["ambiguous_rotation_double_review"]["passed"]:
    next_actions.append("complete_ambiguous_rotation_reviews")
if not requirements["frozen_crossing_double_review"]["passed"]:
    next_actions.append("complete_frozen_crossing_reviews")
if not requirements["duplicates"]["passed"]:
    next_actions.append("resolve_duplicates")
if not requirements["source_frame_identity"]["passed"]:
    next_actions.append("repair_source_frame_labels")

return {
    "gate": "G1",
    "gate_policy_version": GOLDEN_GATE_POLICY.schema_version,
    "evidence_scope": GOLDEN_GATE_POLICY.evidence_scope,
    "status": "ready_for_evaluator" if ready else "waiting_for_owner_labels",
    "diagnostic_only": True,
    "release_claim": False,
    "profiles": profile_progress,
    "scenes": scene_progress,
    "requirements": requirements,
    "next_actions": next_actions,
    "next_best_videos": [item["key"] for item in scene_progress + profile_progress if item["missing"]],
}
```

- [ ] **Step 5: Stamp new evaluator artifacts without migrating old files**

In `backend/app/analysis_v2/evaluation/pilot_store.py`, import `artifact_uses_current_policy` and define one policy metadata mapping plus one status constructor:

```python
POLICY_METADATA = {
    "gate_policy_version": GOLDEN_GATE_POLICY.schema_version,
    "evidence_scope": GOLDEN_GATE_POLICY.evidence_scope,
}


def _policy_status(**fields: Any) -> dict[str, Any]:
    return {**POLICY_METADATA, **fields}
```

Build every new status written by `invalidate()` and `run()` with `_policy_status(...)`. In `status()`, return a fresh current-policy `not_run` response when the persisted status is missing or belongs to another policy, but do not write that response over the legacy file:

```python
def status(self) -> dict[str, Any]:
    if not self.status_path.exists():
        return _policy_status(
            status="not_run",
            evaluator_version=EVALUATOR_VERSION,
            diagnostic_only=True,
            message=None,
        )
    persisted = self._read(self.status_path)
    if not artifact_uses_current_policy(persisted):
        return _policy_status(
            status="not_run",
            evaluator_version=EVALUATOR_VERSION,
            diagnostic_only=True,
            message="Legacy evaluator evidence remains readable; rerun under golden-gate-policy.v2.",
        )
    return persisted
```

Before computing `sanitized-diff.json`, ignore a prior report from another policy so cross-policy changes are not presented as an ordinary rerun diff:

```python
previous = self._read(self.sanitized_report_path) if self.sanitized_report_path.exists() else None
if previous is not None and not artifact_uses_current_policy(previous):
    previous = None
diff = _sanitized_diff(previous, sanitized)
```

Stamp the G1 gate artifact:

```python
gate = {
    "schema_version": "golden-pilot-gate.v1",
    "gate": "G1",
    **POLICY_METADATA,
    "status": status_value,
    "diagnostic_only": True,
    "release_claim": False,
    "dataset_fingerprint": sanitized["dataset_fingerprint"],
    "pipeline_fingerprint": sanitized["pipeline_fingerprint"],
    "result_fingerprint": sanitized["deterministic_fingerprint"],
    "failed_event_count": len(sanitized["failed_events"]),
}
```

In `backend/app/analysis_v2/evaluation/pilot_evaluator.py`, import `GOLDEN_GATE_POLICY`, add `gate_policy_version` to the mapping passed to `canonical_fingerprint()`, and put both policy fields directly into the newly created private and sanitized report dictionaries:

```python
result_fingerprint = canonical_fingerprint({
    "gate_policy_version": GOLDEN_GATE_POLICY.schema_version,
    "evaluator_version": EVALUATOR_VERSION,
    "dataset_fingerprint": dataset_fingerprint,
    "pipeline_fingerprint": bundle.pipeline_fingerprint,
    "evaluation_masks": sorted(masks),
    "aggregate": aggregate,
    "diagnostics": diagnostics,
})

policy_metadata = {
    "gate_policy_version": GOLDEN_GATE_POLICY.schema_version,
    "evidence_scope": GOLDEN_GATE_POLICY.evidence_scope,
}
```

In the existing `private` dictionary insert `**policy_metadata` immediately after `"schema_version": "golden-pilot-private-report.v1"`. In the existing `sanitized` dictionary insert it immediately after `"schema_version": "golden-pilot-sanitized-report.v1"`. Do not remove or rename any existing report field.

Do not scan, rewrite, or backfill `evaluation/*.json` in `PilotEvaluationStore.__init__`, `status()`, or `sanitized_result()`. Reading an unversioned report returns its original mapping; consumers use `artifact_gate_policy_version()` or the frontend fallback from Task A4 to label it as v1 legacy evidence.

Extend `PilotEvaluationStatus` in `backend/app/routers/golden_v2.py` so new metadata is accepted while old unversioned status files remain readable:

```python
gate_policy_version: Literal["golden-gate-policy.v1", "golden-gate-policy.v2"] | None = None
evidence_scope: Literal["limited_sample"] | None = None
```

- [ ] **Step 6: Make sanitized export and FastAPI models carry the policy**

In `backend/app/analysis_v2/evaluation/golden_store.py`, import `gate_policy_summary` and replace `gate_template` with:

```python
policy = gate_policy_summary()
"gate_template": {
    "gate": "G1",
    "status": "not-run",
    "gate_policy_version": policy["schema_version"],
    "evidence_scope": policy["evidence_scope"],
    "required_source_videos": policy["g1_source_video_minimum"],
    "required_valid_events": policy["g1_valid_event_minimum"],
    "profile_minimums": policy["g1_profile_minimums"],
    "required_new_events": policy["g1_valid_event_minimum"],
    "pose_frame_range": [policy["pose_frame_range"]["minimum"], policy["pose_frame_range"]["maximum"]],
    "g2_event_range": [policy["g2_event_range"]["minimum"], policy["g2_event_range"]["maximum"]],
    "g2_profile_ranges": {
        profile: [limits["minimum"], limits["maximum"]]
        for profile, limits in policy["g2_profile_ranges"].items()
    },
},
```

Replace `GoldenGateTemplate` in `backend/app/routers/golden_v2.py` with:

```python
class GoldenGateTemplate(_StrictResponse):
    gate: Literal["G1"]
    status: Literal["not-run"]
    gate_policy_version: Literal["golden-gate-policy.v2"]
    evidence_scope: Literal["limited_sample"]
    required_source_videos: int
    required_valid_events: int
    profile_minimums: dict[str, int]
    required_new_events: int
    pose_frame_range: list[int]
    g2_event_range: list[int]
    g2_profile_ranges: dict[str, list[int]]
```

- [ ] **Step 7: Run the focused backend tests**

Run:

```powershell
python -m pytest backend/tests/analysis_v2/test_gate_policy.py backend/tests/analysis_v2/test_pilot_store.py backend/tests/analysis_v2/test_pilot_evaluator.py backend/tests/analysis_v2/test_golden_store.py backend/tests/analysis_v2/test_golden_privacy_boundary.py -q
```

Expected: all selected tests PASS and the privacy tests find no runtime paths or source references.

- [ ] **Step 8: Commit the G1/export slice**

Run:

```powershell
git add -- backend/app/analysis_v2/evaluation/pilot_store.py backend/app/analysis_v2/evaluation/pilot_evaluator.py backend/app/analysis_v2/evaluation/golden_store.py backend/app/routers/golden_v2.py backend/tests/analysis_v2/test_pilot_store.py backend/tests/analysis_v2/test_pilot_evaluator.py backend/tests/analysis_v2/test_golden_store.py
git commit -m "feat: apply policy v2 to golden g1 progress"
```

Expected: the commit excludes runtime Golden data and unrelated worktree changes.

### Task A3: Enforce and persist the reduced G2 ranges

**Files:**

- Modify: `backend/app/analysis_v2/evaluation/g2_baseline.py`
- Modify: `backend/app/routers/golden_v2.py`
- Modify: `backend/tests/analysis_v2/test_g2_baseline_store.py`
- Modify: `backend/tests/analysis_v2/test_g2_baseline_routes.py`
- Create: `backend/tests/analysis_v2/test_golden_route_assembly.py`

**Interfaces:**

- Consumes: `GOLDEN_GATE_POLICY`, `LEGACY_GATE_POLICY_VERSION`, and `artifact_gate_policy_version()` from Task A1
- Produces in G2 progress/status: `gate_policy_version`, `evidence_scope`, `required_event_range`, and `profile_ranges`
- Persists in freeze/baseline artifacts: `gate_policy_version`
- Interprets an existing unversioned freeze as policy v1 with total range 60-80 and profile ranges 24-32/16-20/12-16/8-12, without rewriting it
- Preserves: explicit confirmation string `freeze_g2_dataset`; no test calls a deployed freeze endpoint

- [ ] **Step 1: Rewrite the G2 fixture around the approved default distribution**

In `backend/tests/analysis_v2/test_g2_baseline_store.py`, replace `_dataset(event_count: int = 60)` with a helper that accepts a profile list:

```python
def _dataset(profiles: list[str] | None = None) -> GoldenDatasetV2:
    selected_profiles = profiles or (["jump"] * 10 + ["spin"] * 6 + ["step"] * 4 + ["spiral"] * 4)
    sources = []
    events = []
    splits = ["development", "development", "development", "validation", "frozen_test"]
    strata = ["normal", "multi-skater", "crossing", "small", "pan", "blur"]
    for source_index in range(5):
        source_hash = f"{source_index + 1:064x}"
        sources.append({
            "source_sha256": source_hash,
            "duration_pts": 300,
            "width": 1280,
            "height": 720,
            "timebase": {"numerator": 1, "denominator": 90_000, "source_fps": 30, "is_vfr": False},
            "private_source_reference": f"videos/source-{source_index}.mp4",
            "recording_session_id": f"session-{source_index}",
            "grouping_id": f"group-{source_index}",
            "redacted_alias": f"source-{source_index + 1:03d}",
        })
    for index, profile in enumerate(selected_profiles):
        source_index = index % 5
        start = float(index * 3)
        events.append({
            "event_id": f"event-{index + 1:03d}",
            "source_sha256": sources[source_index]["source_sha256"],
            "start_pts": start,
            "end_pts": start + 2,
            "profile": profile,
            "observability": "observable",
            "strata": [strata[index % len(strata)]],
            "ambiguity_tags": [],
            "failure_tags": [],
            "annotator_confidence": 0.9,
            "main_skater_confirmed": True,
            "split": splits[source_index],
            "challenge_intervals": [],
            "revision": REVISION,
        })
    return GoldenDatasetV2.model_validate({
        "dataset_id": "golden-v2-private-catalog",
        "revision": REVISION,
        "sources": sources,
        "events": events,
    })
```

- [ ] **Step 2: Write failing G2 range and artifact tests**

Replace the old range assertions and add boundary cases:

```python
def test_g2_progress_uses_policy_v2_ranges() -> None:
    progress = g2_collection_progress(_dataset())
    assert progress["gate_policy_version"] == "golden-gate-policy.v2"
    assert progress["evidence_scope"] == "limited_sample"
    assert progress["required_event_range"] == [24, 30]
    assert progress["profile_ranges"] == {
        "jump": [10, 14], "spin": [6, 8], "step": [4, 5], "spiral": [4, 5],
    }
    assert progress["ready_to_freeze"] is True


@pytest.mark.parametrize("profiles", [
    ["jump"] * 9 + ["spin"] * 6 + ["step"] * 4 + ["spiral"] * 4,
    ["jump"] * 10 + ["spin"] * 5 + ["step"] * 4 + ["spiral"] * 5,
    ["jump"] * 10 + ["spin"] * 6 + ["step"] * 3 + ["spiral"] * 5,
    ["jump"] * 15 + ["spin"] * 6 + ["step"] * 4 + ["spiral"] * 4,
    ["jump"] * 14 + ["spin"] * 8 + ["step"] * 5 + ["spiral"] * 5,
])
def test_g2_rejects_total_or_profile_values_outside_policy(profiles: list[str]) -> None:
    assert g2_collection_progress(_dataset(profiles))["ready_to_freeze"] is False


def test_freeze_and_baseline_persist_policy_version(tmp_path: Path) -> None:
    store = G2BaselineStore(GoldenCatalogStore(tmp_path / "golden"))
    dataset = _dataset()
    frozen = store.freeze(dataset, legacy_pipeline_fingerprint="legacy:v5.2.307")
    baseline = store.record_baseline(
        dataset,
        dataset_fingerprint=frozen["dataset_fingerprint"],
        result_fingerprint="result:123",
        aggregate={"event_count": 24},
    )
    assert frozen["gate_policy_version"] == "golden-gate-policy.v2"
    assert baseline["gate_policy_version"] == "golden-gate-policy.v2"
    assert store.public_status(dataset)["gate_policy_version"] == "golden-gate-policy.v2"


def test_unversioned_freeze_keeps_legacy_ranges_without_rewrite(tmp_path: Path) -> None:
    store = G2BaselineStore(GoldenCatalogStore(tmp_path / "golden"))
    dataset = _dataset()
    store.freeze(dataset, legacy_pipeline_fingerprint="legacy:v5.2.307")
    frozen = json.loads(store.freeze_path.read_text(encoding="utf-8"))
    frozen.pop("gate_policy_version")
    store.freeze_path.write_text(json.dumps(frozen, sort_keys=True), encoding="utf-8")
    before = store.freeze_path.read_bytes()

    status = store.public_status(dataset)

    assert status["gate_policy_version"] == "golden-gate-policy.v1"
    assert status["required_event_range"] == [60, 80]
    assert status["profile_ranges"] == {
        "jump": [24, 32], "spin": [16, 20], "step": [12, 16], "spiral": [8, 12],
    }
    baseline = store.record_baseline(
        dataset,
        dataset_fingerprint=frozen["dataset_fingerprint"],
        result_fingerprint="result:legacy-policy",
        aggregate={"event_count": len(dataset.events)},
    )
    assert baseline["gate_policy_version"] == "golden-gate-policy.v1"
    assert store.public_status(dataset)["gate_policy_version"] == "golden-gate-policy.v1"
    assert store.freeze_path.read_bytes() == before
```

Add `import json` at the top of `backend/tests/analysis_v2/test_g2_baseline_store.py`.

- [ ] **Step 3: Add an assembled-app route regression test**

Create `backend/tests/analysis_v2/test_golden_route_assembly.py`:

```python
from app.main import app


def test_g2_status_route_is_registered_in_the_assembled_application() -> None:
    paths = {route.path for route in app.routes}
    assert "/api/golden/v2/g2/status" in paths
    assert "/api/golden/v2/g2/freeze" in paths
```

- [ ] **Step 4: Update route-contract fixtures to the new fields**

In `backend/tests/analysis_v2/test_g2_baseline_routes.py`, make `G2Store.public_status()` return:

```python
return {
    "schema_version": "golden-g2-status.v1",
    "gate": "G2",
    "gate_policy_version": "golden-gate-policy.v2",
    "evidence_scope": "limited_sample",
    "status": "collecting",
    "event_count": 18,
    "required_event_range": [24, 30],
    "profile_ranges": {"jump": [10, 14], "spin": [6, 8], "step": [4, 5], "spiral": [4, 5]},
    "distribution": {
        "profiles": {"jump": 10, "spin": 4, "step": 2, "spiral": 2},
        "splits": {"unassigned": 18},
        "strata": {},
        "recording_session_count": 17,
    },
    "release_claim": False,
}
```

- [ ] **Step 5: Run the G2 tests and verify old constants fail**

Run:

```powershell
python -m pytest backend/tests/analysis_v2/test_g2_baseline_store.py backend/tests/analysis_v2/test_g2_baseline_routes.py backend/tests/analysis_v2/test_golden_route_assembly.py -q
```

Expected: FAIL on the legacy `[60, 80]` range, legacy profile constants, missing policy fields, or missing persisted policy version.

- [ ] **Step 6: Implement policy-based G2 readiness and persistence**

In `backend/app/analysis_v2/evaluation/g2_baseline.py`, preserve the historical v1 values under explicit legacy names and derive current readiness from policy v2:

```python
from app.analysis_v2.evaluation.gate_policy import (
    GOLDEN_GATE_POLICY,
    LEGACY_GATE_POLICY_VERSION,
    artifact_gate_policy_version,
)

PROFILE_RANGES = {
    profile: (limits.minimum, limits.maximum)
    for profile, limits in GOLDEN_GATE_POLICY.g2_profile_ranges.items()
}
LEGACY_PROFILE_RANGES = {
    "jump": (24, 32),
    "spin": (16, 20),
    "step": (12, 16),
    "spiral": (8, 12),
}
LEGACY_EVENT_RANGE = [60, 80]
```

Use:

```python
event_minimum = GOLDEN_GATE_POLICY.g2_event_range.minimum
event_maximum = GOLDEN_GATE_POLICY.g2_event_range.maximum
ready = (
    event_minimum <= event_count <= event_maximum
    and all(item["passed"] for item in profile_checks.values())
    and distribution["recording_session_count"] >= GOLDEN_GATE_POLICY.g1_recording_session_minimum
    and not split_issues
    and required_splits_present
)
return {
    "gate": "G2",
    "gate_policy_version": GOLDEN_GATE_POLICY.schema_version,
    "evidence_scope": GOLDEN_GATE_POLICY.evidence_scope,
    "status": "ready_to_freeze" if ready else "collecting",
    "event_count": event_count,
    "required_event_range": [event_minimum, event_maximum],
    "profile_ranges": {profile: [minimum, maximum] for profile, (minimum, maximum) in PROFILE_RANGES.items()},
    "distribution": distribution,
    "profiles": profile_checks,
    "split_issues": split_issues,
    "required_splits_present": required_splits_present,
    "ready_to_freeze": ready,
    "release_claim": False,
}
```

Change the freeze error to `G2 freeze requires 24-30 valid, grouped, split-assigned events within every profile range`. Stamp a new freeze with `GOLDEN_GATE_POLICY.schema_version`; make a new baseline inherit `artifact_gate_policy_version(frozen)` so a baseline recorded against a pre-v2 frozen candidate remains v1 evidence.

In `public_status()`, select display ranges from the persisted freeze version rather than today's policy whenever a freeze exists:

```python
frozen_policy_version = artifact_gate_policy_version(frozen)
if frozen_policy_version == LEGACY_GATE_POLICY_VERSION:
    required_event_range = LEGACY_EVENT_RANGE
    profile_ranges = LEGACY_PROFILE_RANGES
else:
    required_event_range = [
        GOLDEN_GATE_POLICY.g2_event_range.minimum,
        GOLDEN_GATE_POLICY.g2_event_range.maximum,
    ]
    profile_ranges = PROFILE_RANGES

return {
    "schema_version": "golden-g2-status.v1",
    "gate": "G2",
    "gate_policy_version": frozen_policy_version,
    "evidence_scope": GOLDEN_GATE_POLICY.evidence_scope,
    "status": "baseline_recorded" if baseline else "frozen_waiting_for_baseline",
    "event_count": progress["event_count"],
    "required_event_range": list(required_event_range),
    "profile_ranges": {
        profile: [minimum, maximum]
        for profile, (minimum, maximum) in profile_ranges.items()
    },
    "distribution": frozen["distribution"],
    "dataset_revision": frozen["dataset_revision"],
    "dataset_fingerprint": frozen["dataset_fingerprint"],
    "legacy_pipeline_fingerprint": frozen["legacy_pipeline_fingerprint"],
    "baseline_result_fingerprint": baseline.get("result_fingerprint") if baseline else None,
    "release_claim": False,
}
```

The no-freeze branch continues to return policy v2 progress. `freeze()`, `assert_compatible()`, and `public_status()` must not backfill `gate_policy_version` into an existing JSON file. In `freeze()`, calculate the candidate fingerprint, then check and return a matching existing freeze before applying current-policy readiness checks; otherwise a valid legacy 60-80 freeze would be rejected by today's 24-30 rule. An idempotent `freeze()` call over an existing unversioned artifact returns that artifact unchanged, while a different fingerprint still raises `a different dataset version is already frozen`.

- [ ] **Step 7: Extend the FastAPI G2 response model**

Add these fields to `G2StatusResponse` in `backend/app/routers/golden_v2.py`:

```python
gate_policy_version: Literal["golden-gate-policy.v1", "golden-gate-policy.v2"]
evidence_scope: Literal["limited_sample"]
profile_ranges: dict[str, list[int]]
```

- [ ] **Step 8: Run the focused G2 and route tests**

Run:

```powershell
python -m pytest backend/tests/analysis_v2/test_gate_policy.py backend/tests/analysis_v2/test_g2_baseline_store.py backend/tests/analysis_v2/test_g2_baseline_routes.py backend/tests/analysis_v2/test_golden_route_assembly.py -q
```

Expected: all selected tests PASS.

- [ ] **Step 9: Commit the G2 slice**

Run:

```powershell
git add -- backend/app/analysis_v2/evaluation/g2_baseline.py backend/app/routers/golden_v2.py backend/tests/analysis_v2/test_g2_baseline_store.py backend/tests/analysis_v2/test_g2_baseline_routes.py backend/tests/analysis_v2/test_golden_route_assembly.py
git commit -m "feat: reduce and version golden g2 baseline"
```

Expected: no private membership, source hashes, or runtime files are staged.

### Task A4: Render policy-provided G1/G2 values in the Golden UI

**Files:**

- Modify: `frontend/src/analysis-v2/golden-contracts.ts`
- Modify: `frontend/src/analysis-v2/components/GoldenCatalogShell.tsx`
- Modify: `frontend/src/analysis-v2/components/GoldenPilotDashboard.tsx`
- Modify: `frontend/src/analysis-v2/components/GoldenG2StatusCard.tsx`
- Modify: `frontend/src/analysis-v2/components/GoldenAnnotationWorkspace.tsx`
- Modify: `frontend/src/analysis-v2/components/GoldenPilotDashboard.test.tsx`
- Modify: `frontend/src/analysis-v2/components/GoldenG2StatusCard.test.tsx`
- Modify: `frontend/src/analysis-v2/components/GoldenCatalogShell.test.tsx`
- Modify: `frontend/src/analysis-v2/components/GoldenAnnotationWorkspace.test.tsx`

**Interfaces:**

- Consumes: policy-aware G1 and G2 JSON from Tasks A2 and A3
- Produces: no hard-coded G1/G2/Pose quantities in rendered components
- Displays: governance actions for G1 and targeted spin/step/spiral collection gaps for G2
- Labels: any unversioned or explicit v1 evaluator report as `golden-gate-policy.v1 (legacy evidence)` without altering the report
- Keeps: the annotation guide's 24-40 Pose target policy-derived by passing the loaded sanitized `gate_template` into `GoldenAnnotationWorkspace`

Because `GoldenAnnotationWorkspace` gains a required `gateTemplate` prop, update every direct render in `GoldenAnnotationWorkspace.test.tsx` to pass one shared fixture:

```typescript
const gateTemplate = {
  gate: "G1" as const,
  status: "not-run" as const,
  gate_policy_version: "golden-gate-policy.v2" as const,
  evidence_scope: "limited_sample" as const,
  required_source_videos: 18,
  required_valid_events: 18,
  profile_minimums: { jump: 10, spin: 4, step: 2, spiral: 2 },
  required_new_events: 18,
  pose_frame_range: [24, 40] as [number, number],
  g2_event_range: [24, 30] as [number, number],
  g2_profile_ranges: { jump: [10, 14], spin: [6, 8], step: [4, 5], spiral: [4, 5] } as Record<string, [number, number]>,
};
```

Use `<GoldenAnnotationWorkspace gateTemplate={gateTemplate} />` in those tests. The shell test may mock the component and assert the received `pose_frame_range`.

- [ ] **Step 1: Update TypeScript contracts before components**

In `frontend/src/analysis-v2/golden-contracts.ts`, use:

```typescript
export type GoldenGatePolicyVersion = "golden-gate-policy.v2";
export type HistoricalGoldenGatePolicyVersion =
  "golden-gate-policy.v1" | GoldenGatePolicyVersion;
export type LimitedSampleEvidenceScope = "limited_sample";
export type GateRequirement = { count?: number; target?: number; issues?: string[]; passed: boolean };

export interface GoldenSanitizedExport {
  schema_version: "golden-sanitized-summary.v1";
  dataset_id: string;
  golden_schema_version: "golden-dataset.v2";
  revision: number;
  aggregate: {
    source_count: number;
    event_count: number;
    profile_counts: GoldenCount[];
    observability_counts: GoldenCount[];
    strata_counts: GoldenCount[];
  };
  redacted_aliases: string[];
  gate_template: {
    gate: "G1";
    status: "not-run";
    gate_policy_version: GoldenGatePolicyVersion;
    evidence_scope: LimitedSampleEvidenceScope;
    required_source_videos: number;
    required_valid_events: number;
    profile_minimums: Record<string, number>;
    required_new_events: number;
    pose_frame_range: [number, number];
    g2_event_range: [number, number];
    g2_profile_ranges: Record<string, [number, number]>;
  };
}

export type PilotProgress = {
  gate: "G1";
  gate_policy_version: GoldenGatePolicyVersion;
  evidence_scope: LimitedSampleEvidenceScope;
  status: "waiting_for_owner_labels" | "ready_for_evaluator";
  diagnostic_only: true;
  release_claim: false;
  profiles: PilotGap[];
  scenes: PilotGap[];
  requirements: Record<string, GateRequirement>;
  next_actions: string[];
  next_best_videos: string[];
};

export type PilotSanitizedResult = {
  schema_version: "golden-pilot-sanitized-report.v1";
  gate_policy_version?: HistoricalGoldenGatePolicyVersion;
  evidence_scope?: LimitedSampleEvidenceScope;
  evaluator_version: string;
  dataset_id: string;
  dataset_fingerprint: string;
  pipeline_fingerprint: string;
  evaluation_masks: string[];
  run_scope?: "snapshot_diagnostic" | "formal_g1";
  diagnostic_only: true;
  release_claim: false;
  deterministic_fingerprint: string;
  repeatability: { deterministic: true; fingerprint: string };
  aggregate: Record<string, unknown>;
  failed_events: Array<{ alias: string; profile: GoldenProfile; strata: string[]; failure_codes: string[] }>;
};

export type GoldenG2Status = {
  schema_version: "golden-g2-status.v1";
  gate: "G2";
  gate_policy_version: HistoricalGoldenGatePolicyVersion;
  evidence_scope: LimitedSampleEvidenceScope;
  status: "collecting" | "ready_to_freeze" | "frozen_waiting_for_baseline" | "baseline_recorded";
  event_count: number;
  required_event_range: [number, number];
  profile_ranges: Record<string, [number, number]>;
  distribution: {
    profiles: Record<string, number>;
    splits: Record<string, number>;
    strata: Record<string, number>;
    recording_session_count: number;
  };
  dataset_revision?: number | null;
  dataset_fingerprint?: string | null;
  legacy_pipeline_fingerprint?: string | null;
  baseline_result_fingerprint?: string | null;
  release_claim: false;
};
```

- [ ] **Step 2: Replace component fixtures with the actual approved values**

In `GoldenPilotDashboard.test.tsx`, make the fixture contain 18 videos/events, 10/4/2/2 profiles, and governance blockers:

```typescript
function waitingProgress(): PilotProgress {
  return {
    gate: "G1",
    gate_policy_version: "golden-gate-policy.v2",
    evidence_scope: "limited_sample",
    status: "waiting_for_owner_labels",
    diagnostic_only: true,
    release_claim: false,
    profiles: [
      { key: "jump", count: 10, target: 10, missing: 0 },
      { key: "spin", count: 4, target: 4, missing: 0 },
      { key: "step", count: 2, target: 2, missing: 0 },
      { key: "spiral", count: 2, target: 2, missing: 0 },
    ],
    scenes: [{ key: "crossing/occlusion", count: 7, target: 1, missing: 0 }],
    requirements: {
      source_video_count: { count: 18, target: 18, passed: true },
      event_count: { count: 18, target: 18, passed: true },
      recording_sessions: { count: 17, target: 5, passed: true },
      schema_valid: { count: 18, target: 18, passed: true },
      split_grouping: { issues: ["session:split-inconsistent"], passed: false },
      delayed_review: { count: 0, target: 2, passed: false },
      ambiguous_rotation_double_review: { count: 0, target: 5, passed: false },
    },
    next_actions: ["assign_consistent_splits", "complete_delayed_reviews", "complete_ambiguous_rotation_reviews"],
    next_best_videos: [],
  };
}
```

Assert that the dashboard shows `18/18` for videos and events, `0/2` delayed reviews, a limited-sample label, and the three governance actions; assert that it does not recommend another jump video.

In the existing evaluator-result test, keep the fixture intentionally unversioned and add:

```typescript
expect(screen.getByText("golden-gate-policy.v1 (legacy evidence)")).toBeInTheDocument();
```

Add a second assertion or fixture with `gate_policy_version: "golden-gate-policy.v2"` and verify the dashboard displays `golden-gate-policy.v2` without the legacy suffix. This proves historical evidence remains distinguishable after the new policy is deployed.

In `GoldenG2StatusCard.test.tsx`, use current distribution `10/4/2/2`, range `[24, 30]`, and profile ranges `10-14/6-8/4-5/4-5`. Assert the rendered recommendation contains `spin +2`, `step +2`, and `spiral +2` and does not contain `jump +`.

In `GoldenCatalogShell.test.tsx`, replace the legacy gate template fixture with policy v2 fields, the 18-event compatibility value, `pose_frame_range: [24, 40]`, `g2_event_range: [24, 30]`, and the four G2 profile ranges. Assert the shell passes this template to the annotation workspace.

In `GoldenAnnotationWorkspace.test.tsx`, assert the guide contains `G1 已固定为 18 个视频和 18 个有效事件`, `G2 只需扩充到 24-30 个事件`, and `Pose 全数据集目标为 24-40 个代表帧`.

- [ ] **Step 3: Run the frontend tests and verify hard-coded legacy copy fails**

Run:

```powershell
npm --prefix frontend test -- GoldenPilotDashboard.test.tsx GoldenG2StatusCard.test.tsx GoldenCatalogShell.test.tsx GoldenAnnotationWorkspace.test.tsx
```

Expected: FAIL because the components still render `36`, `60-80`, lack policy/governance fields, and do not label an unversioned evaluator report as legacy evidence.

- [ ] **Step 4: Render G1 requirements from response targets**

In `GoldenPilotDashboard.tsx`, derive requirements once:

```typescript
const videoRequirement = progress.requirements.source_video_count;
const eventRequirement = progress.requirements.event_count;
const schemaRequirement = progress.requirements.schema_valid;
const delayedRequirement = progress.requirements.delayed_review;
const evaluatorPolicyLabel = result?.gate_policy_version === "golden-gate-policy.v2"
  ? result.gate_policy_version
  : result
    ? "golden-gate-policy.v1 (legacy evidence)"
    : null;
const actionLabels: Record<string, string> = {
  assign_consistent_splits: "为全部事件分配一致的 development / validation / frozen-test split",
  complete_delayed_reviews: "完成 2 个相隔至少 24 小时的延迟复标",
  complete_ambiguous_rotation_reviews: "完成所有模糊旋转的独立二次复核",
  complete_frozen_crossing_reviews: "完成 frozen-test 交叉场景复核",
  resolve_duplicates: "处理重复或近重复素材",
  repair_source_frame_labels: "补齐精确源帧标识",
};
```

Render the main card with response values:

```tsx
<p>这是 {progress.gate_policy_version} 的有限样本诊断门槛，不是大规模发布准确率声明。</p>
{evaluatorPolicyLabel ? <p>Evaluator evidence: {evaluatorPolicyLabel}</p> : null}
<dl className="modern-runtime-status">
  <div><dt>Evaluator</dt><dd>{status.status}</dd></div>
  <div><dt>视频</dt><dd>{videoRequirement.count ?? 0}/{videoRequirement.target ?? 0}</dd></div>
  <div><dt>有效事件</dt><dd>{eventRequirement.count ?? 0}/{eventRequirement.target ?? 0}</dd></div>
  <div><dt>录制场次</dt><dd>{progress.requirements.recording_sessions.count ?? 0}/{progress.requirements.recording_sessions.target ?? 0}</dd></div>
  <div><dt>Schema / 源帧有效</dt><dd>{schemaRequirement.count ?? 0}/{schemaRequirement.target ?? 0}</dd></div>
  <div><dt>延迟复核</dt><dd>{delayedRequirement.count ?? 0}/{delayedRequirement.target ?? 0}</dd></div>
</dl>
{progress.next_actions.length ? <ul>{progress.next_actions.map((action) => <li key={action}>{actionLabels[action] ?? action}</li>)}</ul> : <p>G1 治理要求已经满足，可以运行正式 G1 诊断。</p>}
```

Use `next_best_videos` only for actual profile/scene collection gaps; when it is empty, do not show a collection recommendation.

- [ ] **Step 5: Render G2 per-profile gaps and limited-sample language**

In `GoldenG2StatusCard.tsx`, compute:

```typescript
const additions = Object.entries(status.profile_ranges)
  .map(([profile, [minimum]]) => ({ profile, missing: Math.max(0, minimum - (status.distribution.profiles[profile] ?? 0)) }))
  .filter((item) => item.missing > 0);
```

Replace legacy copy with:

```tsx
<p>G2 总量要求为 {minimum}-{maximum} 个有效事件，并且每个 profile 都必须落在策略范围内。</p>
{additions.length ? <p>最小补标建议：{additions.map((item) => `${item.profile} +${item.missing}`).join("，")}。</p> : null}
<p>满足数量和质量条件后也只产生有限样本候选证据；冻结仍需家长明确确认。</p>
```

- [ ] **Step 6: Replace the annotation guide copy with policy-provided Pose values**

In `GoldenCatalogShell.tsx`, pass the loaded template:

```tsx
<GoldenAnnotationWorkspace gateTemplate={exportData.gate_template} />
```

Update `GoldenAnnotationWorkspace.tsx` to accept:

```typescript
type GoldenAnnotationWorkspaceProps = {
  gateTemplate: GoldenSanitizedExport["gate_template"];
};
```

Destructure `gateTemplate`, derive `g2Minimums`, and replace the old target paragraphs with policy values:

```typescript
const g2Minimums = Object.fromEntries(
  Object.entries(gateTemplate.g2_profile_ranges).map(([profile, [minimum]]) => [profile, minimum]),
) as Record<string, number>;
```

```tsx
<p><strong>G1 已固定为 {gateTemplate.required_source_videos} 个视频和 {gateTemplate.required_valid_events} 个有效事件。</strong>当前数量已经达到，接下来优先完成 split 和复核，不需要为了 G1 再上传视频。</p>
<p><strong>G2 只需扩充到 {gateTemplate.g2_event_range[0]}-{gateTemplate.g2_event_range[1]} 个事件。</strong>最低 profile 数量为 jump {g2Minimums.jump}、spin {g2Minimums.spin}、step {g2Minimums.step}、spiral {g2Minimums.spiral}；按实际状态卡缺口补标，不要为了抬高总数重复补跳跃。</p>
```

Render the Pose card introduction from the policy range:

```tsx
<p>Pose 全数据集目标为 {gateTemplate.pose_frame_range[0]}-{gateTemplate.pose_frame_range[1]} 个代表帧，不需要每帧或每个事件都标。覆盖动作核心、远景、模糊、遮挡、正背面和交叉场景；看不清的关节留空。</p>
```

- [ ] **Step 7: Run focused frontend tests and build**

Run:

```powershell
npm --prefix frontend test -- GoldenPilotDashboard.test.tsx GoldenG2StatusCard.test.tsx GoldenCatalogShell.test.tsx GoldenAnnotationWorkspace.test.tsx
npm --prefix frontend run build
```

Expected: selected tests PASS; TypeScript and Vite build exit with code 0.

- [ ] **Step 8: Commit the frontend slice**

Run:

```powershell
git add -- frontend/src/analysis-v2/golden-contracts.ts frontend/src/analysis-v2/components/GoldenCatalogShell.tsx frontend/src/analysis-v2/components/GoldenPilotDashboard.tsx frontend/src/analysis-v2/components/GoldenG2StatusCard.tsx frontend/src/analysis-v2/components/GoldenAnnotationWorkspace.tsx frontend/src/analysis-v2/components/GoldenPilotDashboard.test.tsx frontend/src/analysis-v2/components/GoldenG2StatusCard.test.tsx frontend/src/analysis-v2/components/GoldenCatalogShell.test.tsx frontend/src/analysis-v2/components/GoldenAnnotationWorkspace.test.tsx
git commit -m "feat: show reduced golden gates in parent ui"
```

Expected: the commit contains only Golden frontend contracts, components, and tests.

### Task A5: Apply subtype and limited-sample evidence semantics to later gates

**Files:**

- Modify: `backend/app/analysis_v2/action_classification.py`
- Modify: `backend/app/analysis_v2/evaluation/g8_moments.py`
- Modify: `backend/app/analysis_v2/evaluation/g9_rotation.py`
- Modify: `backend/app/analysis_v2/evaluation/pilot12_event_proposals.py`
- Modify: `backend/tests/analysis_v2/test_action_classification.py`
- Modify: `backend/tests/analysis_v2/test_g8_moments.py`
- Modify: `backend/tests/analysis_v2/test_g9_rotation.py`
- Modify: `backend/tests/analysis_v2/test_event_proposals.py`
- Create: `backend/tests/analysis_v2/test_pilot14_action_classification.py`

**Interfaces:**

- Consumes: `GOLDEN_GATE_POLICY.subtype_reporting_minimum`
- Consumes: `limited_sample_gate_metadata()`
- Produces: `gate_policy_version`, `evidence_scope`, `limited_sample_candidate_pass`, or `insufficient_sample`
- Guarantees: `release_claim` remains `False` for reduced-dataset evidence

- [ ] **Step 1: Change subtype tests from N=20 to the approved N=4 boundary**

In `backend/tests/analysis_v2/test_action_classification.py`, replace the subtype tests with:

```python
def test_subtype_with_three_samples_is_underpowered() -> None:
    result = classify_action(jump_evidence(
        subtype_candidates={"jump": (("toe_loop", .95),)},
        subtype_validation_n={"jump": {"toe_loop": 3}},
    ))
    assert result.subtype.underpowered is True
    assert result.subtype.state == "unknown"
    assert "required N=4" in result.subtype.reason


def test_subtype_with_four_samples_can_be_confirmed_as_limited_sample() -> None:
    result = classify_action(jump_evidence(
        subtype_candidates={"jump": (("toe_loop", .95),)},
        subtype_validation_n={"jump": {"toe_loop": 4}},
    ))
    assert result.subtype.subtype == "toe_loop"
    assert result.subtype.state == "confirmed"
    assert result.subtype.underpowered is False
```

- [ ] **Step 2: Add limited-sample status assertions to G8 and G9 tests**

In `test_g8_moments.py`, change the frozen calibrated assertion to:

```python
assert result["status"] == "limited_sample_candidate_pass"
assert result["gate_passed"] is True
assert result["release_claim"] is False
assert result["gate_policy_version"] == "golden-gate-policy.v2"
assert result["evidence_scope"] == "limited_sample"
```

Add:

```python
def test_empty_g8_dataset_is_insufficient_sample() -> None:
    result = evaluate_g8_moments(labels=[], predictions={}, candidate_fingerprint="candidate-v1", dataset_frozen=True, validation_calibrated=True)
    assert result["status"] == "insufficient_sample"
    assert result["gate_passed"] is False
    assert result["release_claim"] is False
```

In `test_g9_rotation.py`, change the frozen calibrated assertion to the same limited-sample fields and change the empty test expectation to `insufficient_sample`.

In `test_event_proposals.py`, add a small JSON fixture test for G6:

```python
def test_g6_pilot_payload_is_policy_scoped(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot.json"
    labels = tmp_path / "labels.json"
    snapshot.write_text("{}", encoding="utf-8")
    labels.write_text('{"events": []}', encoding="utf-8")
    result = evaluate_pilot12_event_proposals(snapshot, labels)
    assert result["gate"] == "G6"
    assert result["gate_policy_version"] == "golden-gate-policy.v2"
    assert result["evidence_scope"] == "limited_sample"
    assert result["release_claim"] is False
```

Create `backend/tests/analysis_v2/test_pilot14_action_classification.py` so G7 is tested independently rather than inferred from the G6 evaluator:

```python
from pathlib import Path

from app.analysis_v2.evaluation.pilot12_event_proposals import evaluate_pilot14_action_classification


def test_g7_pilot_payload_is_policy_scoped(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot.json"
    labels = tmp_path / "labels.json"
    snapshot.write_text("{}", encoding="utf-8")
    labels.write_text('{"events": []}', encoding="utf-8")
    result = evaluate_pilot14_action_classification(snapshot, labels)
    assert result["gate"] == "G7"
    assert result["gate_policy_version"] == "golden-gate-policy.v2"
    assert result["evidence_scope"] == "limited_sample"
    assert result["release_claim"] is False
```

- [ ] **Step 3: Run the later-gate tests and verify legacy status semantics fail**

Run:

```powershell
python -m pytest backend/tests/analysis_v2/test_action_classification.py backend/tests/analysis_v2/test_g8_moments.py backend/tests/analysis_v2/test_g9_rotation.py backend/tests/analysis_v2/test_event_proposals.py backend/tests/analysis_v2/test_pilot14_action_classification.py -q
```

Expected: FAIL on subtype N=4, status `passed`, `release_claim=True`, empty-dataset status, or missing policy fields.

- [ ] **Step 4: Use the central subtype minimum**

In `backend/app/analysis_v2/action_classification.py`, import the policy and change the dataclass default:

```python
from app.analysis_v2.evaluation.gate_policy import GOLDEN_GATE_POLICY

subtype_minimum_evidence: int = GOLDEN_GATE_POLICY.subtype_reporting_minimum
```

Keep the existing classifier score threshold and manual-confirmation behavior; only the declared validation sample boundary changes.

- [ ] **Step 5: Classify G8 and G9 evidence through the limited-sample helper**

In each evaluator, import:

```python
from app.analysis_v2.evaluation.gate_policy import GOLDEN_GATE_POLICY, limited_sample_gate_metadata
```

For G8, compute:

```python
gate_metadata = limited_sample_gate_metadata(
    applicable_n=expected,
    thresholds_met=jump_thresholds_met,
    protocol_met=formal_protocol_met,
)
```

For G9, use `applicable_n=clear_exact_label_n`.

In both result payloads use:

```python
**gate_metadata,
```

Do not change the existing accuracy/error thresholds.

- [ ] **Step 6: Tag G6/G7 diagnostic outputs with policy scope**

In `pilot12_event_proposals.py`, add these fields to both G6 and G7 payloads:

```python
"gate_policy_version": GOLDEN_GATE_POLICY.schema_version,
"evidence_scope": GOLDEN_GATE_POLICY.evidence_scope,
```

Keep their diagnostic-only and non-release behavior unchanged.

- [ ] **Step 7: Run the later-gate tests**

Run:

```powershell
python -m pytest backend/tests/analysis_v2/test_action_classification.py backend/tests/analysis_v2/test_g8_moments.py backend/tests/analysis_v2/test_g9_rotation.py backend/tests/analysis_v2/test_event_proposals.py backend/tests/analysis_v2/test_pilot14_action_classification.py -q
```

Expected: all selected tests PASS; G8/G9 quality thresholds are unchanged and release claims remain false.

- [ ] **Step 8: Commit the later-gate slice**

Run:

```powershell
git add -- backend/app/analysis_v2/action_classification.py backend/app/analysis_v2/evaluation/g8_moments.py backend/app/analysis_v2/evaluation/g9_rotation.py backend/app/analysis_v2/evaluation/pilot12_event_proposals.py backend/tests/analysis_v2/test_action_classification.py backend/tests/analysis_v2/test_g8_moments.py backend/tests/analysis_v2/test_g9_rotation.py backend/tests/analysis_v2/test_event_proposals.py backend/tests/analysis_v2/test_pilot14_action_classification.py
git commit -m "feat: mark later gates as limited sample evidence"
```

Expected: no changes to the numeric G3-G12 accuracy and safety thresholds.

### Task A6: Reconcile active documentation without rewriting history

**Files:**

- Modify: `docs/evaluation/v2/owner-labeling-guide.md`
- Modify: `docs/superpowers/specs/2026-07-29-skating-analysis-v2-shadow-pipeline-design.md`
- Modify: `docs/development/iteration-8-identity-tracking.md`
- Modify: `docs/evaluation/v2/golden-v2-sanitized-summary-template.json`
- Create: `docs/evaluation/v2/golden-gate-policy-v2-transition.json`
- Modify: `backend/tests/analysis_v2/test_golden_privacy_boundary.py`

**Interfaces:**

- Consumes: approved policy values and verified aggregate catalog state
- Produces: active documentation aligned with policy v2
- Preserves: historical files such as `pilot-12-diagnostic-2026-08-01.json` and the iteration evidence snapshots

- [ ] **Step 1: Write the sanitized transition artifact first**

Create `docs/evaluation/v2/golden-gate-policy-v2-transition.json`:

```json
{
  "schema_version": "golden-gate-policy-transition.v1",
  "gate_policy_version": "golden-gate-policy.v2",
  "effective_date": "2026-08-15",
  "verified_catalog": {
    "revision": 70,
    "source_video_count": 18,
    "valid_event_count": 18,
    "recording_session_count": 17,
    "profile_counts": {"jump": 10, "spin": 4, "step": 2, "spiral": 2},
    "duplicate_source_count": 0,
    "scene_coverage_complete": true
  },
  "g1": {
    "source_video_minimum": 18,
    "valid_event_minimum": 18,
    "remaining_governance": [
      "assign grouped development/validation/frozen-test splits",
      "complete two delayed relabel reviews",
      "complete all applicable independent second reviews"
    ]
  },
  "g2": {
    "event_range": [24, 30],
    "profile_ranges": {"jump": [10, 14], "spin": [6, 8], "step": [4, 5], "spiral": [4, 5]},
    "minimum_targeted_additions_from_verified_catalog": {"spin": 2, "step": 2, "spiral": 2}
  },
  "pose_frame_range": [24, 40],
  "subtype_reporting": {"minimum": 4, "target": 6},
  "evidence_scope": "limited_sample",
  "release_claim": false,
  "private_data_included": false
}
```

- [ ] **Step 2: Extend privacy tests for the new artifact and policy template**

Append to `backend/tests/analysis_v2/test_golden_privacy_boundary.py`:

```python
def test_policy_v2_transition_artifact_is_aggregate_only() -> None:
    evidence = ROOT / "docs" / "evaluation" / "v2" / "golden-gate-policy-v2-transition.json"
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    encoded = json.dumps(payload).lower()
    assert payload["gate_policy_version"] == "golden-gate-policy.v2"
    assert payload["verified_catalog"]["source_video_count"] == 18
    assert payload["release_claim"] is False
    for forbidden in ("c:\\users", "source_sha256", "event_id", "annotator_alias", "reviewer_alias", "filename", "embedding"):
        assert forbidden not in encoded


def test_sanitized_template_uses_policy_v2_counts() -> None:
    template = ROOT / "docs" / "evaluation" / "v2" / "golden-v2-sanitized-summary-template.json"
    payload = json.loads(template.read_text(encoding="utf-8"))
    gate = payload["gate_template"]
    assert gate["gate_policy_version"] == "golden-gate-policy.v2"
    assert gate["required_source_videos"] == 18
    assert gate["required_valid_events"] == 18
    assert gate["pose_frame_range"] == [24, 40]
    assert gate["g2_event_range"] == [24, 30]
    assert gate["g2_profile_ranges"] == {"jump": [10, 14], "spin": [6, 8], "step": [4, 5], "spiral": [4, 5]}
```

- [ ] **Step 3: Run privacy tests and verify the old template fails**

Run:

```powershell
python -m pytest backend/tests/analysis_v2/test_golden_privacy_boundary.py -q
```

Expected: FAIL because the existing sanitized template still carries the legacy gate shape.

- [ ] **Step 4: Update active text while retaining historical meaning**

Make these exact policy statements in active docs:

- `owner-labeling-guide.md`: G1 is fixed at 18 videos/18 valid events; finish split/review work first; G2 is 24-30 with targeted spin/step/spiral additions; Pose is 24-40.
- `2026-07-29-skating-analysis-v2-shadow-pipeline-design.md`: add a dated policy-v2 amendment at the Golden dataset section and replace its active recommended counts with 18 and 24-30; subtype minimum is 4 and target is 6; Pose is 24-40.
- `iteration-8-identity-tracking.md`: preserve the original diagnostic statement but append that the 36 and 60-80 values were the legacy policy and were superseded on 2026-08-15.
- `golden-v2-sanitized-summary-template.json`: use the same `gate_template` keys returned by Task A2.

Do not alter the original numeric claims inside dated evidence JSON files that recorded earlier runs.

- [ ] **Step 5: Scan active surfaces for legacy quantity copy**

Run:

```powershell
rg -n "36-event|36 个真实动作|60-80|50-100|10-15 examples|6-8 events" docs/evaluation/v2/owner-labeling-guide.md docs/superpowers/specs/2026-07-29-skating-analysis-v2-shadow-pipeline-design.md frontend/src/analysis-v2 backend/app/analysis_v2/evaluation backend/app/routers/golden_v2.py
```

Expected: no matches. Dated historical evidence files are intentionally outside this scan.

- [ ] **Step 6: Run privacy tests again**

Run:

```powershell
python -m pytest backend/tests/analysis_v2/test_golden_privacy_boundary.py -q
```

Expected: all privacy tests PASS.

- [ ] **Step 7: Commit documentation and sanitized evidence**

Run:

```powershell
git add -- docs/evaluation/v2/owner-labeling-guide.md docs/superpowers/specs/2026-07-29-skating-analysis-v2-shadow-pipeline-design.md docs/development/iteration-8-identity-tracking.md docs/evaluation/v2/golden-v2-sanitized-summary-template.json docs/evaluation/v2/golden-gate-policy-v2-transition.json backend/tests/analysis_v2/test_golden_privacy_boundary.py
git commit -m "docs: align active v2 guidance with reduced gates"
```

Expected: historical iteration evidence JSON files are absent from the commit.

### Task A7: Verify the complete policy change and the deployed read-only G2 route

**Files:**

- Verification only; edit a file only if a failing check identifies a real defect in the approved scope

**Interfaces:**

- Consumes: all prior amendment tasks
- Produces: reproducible backend, frontend, contract, privacy, route, and static-scan evidence
- Forbidden action: `POST /api/golden/v2/g2/freeze`

- [ ] **Step 1: Run the complete focused backend suite**

Run:

```powershell
python -m pytest backend/tests/analysis_v2/test_gate_policy.py backend/tests/analysis_v2/test_pilot_store.py backend/tests/analysis_v2/test_pilot_evaluator.py backend/tests/analysis_v2/test_golden_store.py backend/tests/analysis_v2/test_golden_privacy_boundary.py backend/tests/analysis_v2/test_g2_baseline_store.py backend/tests/analysis_v2/test_g2_baseline_routes.py backend/tests/analysis_v2/test_golden_route_assembly.py backend/tests/analysis_v2/test_action_classification.py backend/tests/analysis_v2/test_g8_moments.py backend/tests/analysis_v2/test_g9_rotation.py backend/tests/analysis_v2/test_event_proposals.py backend/tests/analysis_v2/test_pilot14_action_classification.py -q
```

Expected: exit code 0 with no failed tests.

- [ ] **Step 2: Run the affected frontend suite and production build**

Run:

```powershell
npm --prefix frontend test -- GoldenPilotDashboard.test.tsx GoldenG2StatusCard.test.tsx GoldenCatalogShell.test.tsx GoldenAnnotationWorkspace.test.tsx
npm --prefix frontend run build
```

Expected: selected Vitest files PASS and the production build exits 0.

- [ ] **Step 3: Verify assembled local routes without starting a server**

Run:

```powershell
Push-Location backend
python -c "from app.main import app; paths={route.path for route in app.routes}; assert '/api/golden/v2/g2/status' in paths; assert '/api/golden/v2/g2/freeze' in paths; print('golden-g2-routes-ok')"
Pop-Location
```

Expected: `golden-g2-routes-ok`.

- [ ] **Step 4: Verify the deployed G2 status endpoint read-only**

Set the PIN in the process environment without committing it, then run only the GET request:

```powershell
$headers = @{ 'X-Parent-Pin' = $env:GOLDEN_PARENT_PIN }
$status = Invoke-RestMethod -Uri 'http://192.168.50.179:27831/api/golden/v2/g2/status' -Headers $headers -Method Get
$status | Select-Object gate_policy_version,status,event_count,required_event_range,profile_ranges | ConvertTo-Json -Depth 6
```

Expected after the owner-approved NAS annotation deployment: HTTP 200, `gate_policy_version` equal to `golden-gate-policy.v2`, `event_count` equal to the current catalog count, and `required_event_range` equal to `[24,30]`.

If this GET still returns 404 while Step 3 passes, record the deployment as stale and stop before claiming route restoration. Rebuild/restart the NAS annotation containers only under the existing controlled deployment procedure and explicit owner approval. Never call the freeze endpoint as part of deployment verification.

- [ ] **Step 5: Verify the private catalog without writing it**

Run:

```powershell
$headers = @{ 'X-Parent-Pin' = $env:GOLDEN_PARENT_PIN }
$catalog = Invoke-RestMethod -Uri 'http://192.168.50.179:27831/api/golden/v2/catalog' -Headers $headers -Method Get
$progress = Invoke-RestMethod -Uri 'http://192.168.50.179:27831/api/golden/v2/evaluator/progress' -Headers $headers -Method Get
[pscustomobject]@{
  videos = $catalog.source_count
  events = $catalog.event_count
  policy = $progress.gate_policy_version
  source_video_requirement = $progress.requirements.source_video_count
  event_requirement = $progress.requirements.event_count
  next_actions = $progress.next_actions
} | ConvertTo-Json -Depth 8
```

Expected: read-only output reflecting the actual catalog, policy-derived 18/18 targets, and only real remaining governance actions. The command performs no annotation save, review attestation, or freeze.

- [ ] **Step 6: Run final static and whitespace checks**

Run:

```powershell
rg -n "36-event|36 个真实动作|60-80|50-100|10-15 examples|6-8 events" docs/evaluation/v2/owner-labeling-guide.md docs/superpowers/specs/2026-07-29-skating-analysis-v2-shadow-pipeline-design.md frontend/src/analysis-v2 backend/app/analysis_v2/evaluation backend/app/routers/golden_v2.py
git diff --check
git status --short
```

Expected: the legacy-copy scan prints no matches, `git diff --check` prints no errors, and status contains no unexpected runtime or private Golden files.

- [ ] **Step 7: Commit any verification-only fixes, if required**

If Steps 1-6 exposed a scoped defect, stage only the exact files changed for that defect and commit:

```powershell
git commit -m "fix: complete golden gate policy verification"
```

If no files changed, do not create an empty commit.

## Full-Stack Vertical Slice Rule

This is a full-system refactor, not a backend project followed by a frontend port. Every iteration must address all affected layers before its gate can pass:

```text
algorithm/state
  -> persistence and schema
  -> AnalysisFacts projection and AnalysisExperience presenter
  -> downstream service consumers and background jobs
  -> typed TypeScript contract and selectors
  -> Animal Island page/component
  -> compatibility behavior
  -> backend + frontend + route + accessibility tests
```

### Single rendering authority

- Every ordinary analysis response declares exactly one authority: `legacy` or `v2`.
- All events, moments, pose availability, rotation, report claims, and review tasks in that response come from the same authority.
- In `shadow` mode, ordinary family pages receive the legacy experience only. V2 is fetched from a separate parent-authorized Shadow endpoint.
- In `v2` mode, missing V2 evidence remains missing/unobservable. The presenter cannot patch it with a legacy value.
- Historical legacy analyses are converted wholesale by a legacy presenter into the same `AnalysisExperienceV2` shape.
- Frontend components never combine `analysis.bio_data`, `vision_path_a`, `vision_path_b`, legacy pose dictionaries, and V2 claims themselves.
- Raw legacy fields remain available only to backend adapters, legacy export compatibility, and parent-authorized diagnostics during migration.

### Single downstream authority

- `AnalysisFactsV2` is the only analysis-semantic input for migrated chat, correction, plan, compare, progress, growth, skill, memory, chapter, annual, share, and export services.
- Every fact carries authority, pipeline fingerprint, definition version, unit/convention, observability, confidence, provenance, event identity, and allowed-use flags.
- Shadow facts cannot create or alter a family artifact, plan, skill state, memory suggestion, trend, chapter, annual collection, share, or export.
- Aggregation and comparison require compatible definitions, units, conventions, and confirmed coverage; incompatible data stays visible as excluded context, not a fabricated trend.
- Generated artifacts store their input fact hash and generation fingerprint. Existing published/completed artifacts remain immutable snapshots unless the current explicit revision or regeneration workflow is used.
- Static dependency-boundary tests prevent migrated backend consumers from reading `Analysis.bio_data`, `Analysis.report`, raw Path A/B, or incidental legacy columns directly.

### Iteration completion checklist

Each iteration report must include:

- backend behavior and stored-data changes;
- API schema/presenter changes;
- frontend types, selectors, components, and entry-point changes;
- Animal Island theme and family-language review;
- legacy/history behavior;
- affected downstream services, mutations, generated artifacts, and background-job behavior;
- settings/provider/model/runtime behavior and configuration fingerprints when affected;
- data migration, deletion, backup/restore, privacy, and rollback behavior when affected;
- desktop, tablet, mobile, keyboard, contrast, loading, empty, error, uncertain, and rollback states as applicable;
- backend tests, frontend tests, production build, and contract-fixture evidence;
- confirmation that no ordinary component reads mixed raw sources.
- confirmation that no migrated backend consumer bypasses `AnalysisFactsV2`.

If an iteration is intentionally invisible to ordinary users, it must still provide a complete parent-authorized Golden/Shadow/diagnostic experience in the same iteration. A backend-only state with no discoverable review surface fails the iteration.

### UI migration boundary

- `frontend/src/analysis-v2/` owns V2 contracts, API access, adapters, status language, timeline selectors, and shared analysis components.
- `ModernTodayIsland`, `ReviewPage`, `ModernAnalysisDetail`, growth views, archive/compare views, and advanced tools consume selectors from this package.
- `frontend/src/api/client.ts` transports the typed experience schema but does not become another algorithm-normalization layer.
- Add a static/import-boundary test that prevents migrated production analysis components from reading raw Path A/B or raw legacy biomechanics fields.
- Modern Animal Island pages are the canonical V2 experience. Existing routes remain stable, and classic/historical entry points use the same presenter or route to the canonical experience rather than implementing a second V2 interpretation.

### Frontend migration matrix

| Surface | Owning iteration | Required V2 behavior | Compatibility rule |
|---|---:|---|---|
| Application boot, routing, and capability loading | 0, 5, 17 | Load pipeline/schema capabilities before enabling V2 components; keep the four primary spaces | A capability failure falls back to a complete legacy experience, never a partially hydrated page |
| `/home` and `ModernTodayIsland` | 5, 10, 16, 18 | Show one authoritative latest-analysis status and the next useful family action | Shadow remains invisible; historical and current cards use the presenter |
| `/review`, `ModernReviewSpace`, and `ReviewPage` | 2, 8, 10, 11 | Keep upload; add annotation for Golden and family confirmation inboxes under the correct authorization | Golden and Shadow tools remain parent-only; legacy upload behavior remains intact |
| `/analysis/:id` and `ModernAnalysisDetail` | 5, 6, 9-14 | Render the authoritative event selector, source timeline, moments, pose, rotation, claims, and review state | A legacy analysis is adapted wholesale as one legacy-authoritative experience |
| `IceMediaPlayer`, `MediaControls`, and timeline overlays | 2, 6, 8, 10, 12 | Seek and step by source PTS; render event, conflict, and moment markers | Media playback remains usable when a legacy record has only limited timing metadata |
| `ActionPhaseStrip` | 10-12 | Render several profile-specific event intervals and moments, including unknown/incomplete states | It cannot synthesize missing V2 stages from legacy T/A/L fields |
| `PoseViewer` | 9, 14 | Render authorized target pose and measured/smoothed/interpolated provenance | Uncertain identity suppresses authoritative pose; no raw pose-dictionary fallback |
| `/growth` and growth selectors | 5, 11-14, 18 | Admit only confirmed, definition-compatible claims into trends and comparisons | Changed definitions, uncertainty, and insufficient coverage are excluded with an explanation |
| `/me` and `/me/advanced` | 0, 3-5, 7, 15-19 | Keep resident-services styling; add Golden, gates, Shadow, pipeline, resource, and rollout tools for parents | No engineering diagnostics enter child mode or primary navigation |
| `/golden` | 1-4 | Provide the complete private themed catalog, annotation, evaluator, and frozen-gate workflow | Existing access checks and links remain valid |
| `/debug` | 0, 7, 15-17 | Link to bounded observation/pipeline diagnostics without becoming a second report UI | Raw artifacts remain parent-authorized and are not ordinary-page fallbacks |
| `/report/:id`, archives, compare, and shared historical links | 5, 14, 17, 19 | Route through the same presenter and family-safe claim language | Stored historical evidence is never rewritten or blended with V2 |
| `/analysis-chat` and analysis 追问 section | 5, 10-14, 17 | Use selected-event, same-authority facts; retain history, multi-question replies, provider identity, suggestions, rerun actions, and sharing | Existing chat snapshots remain readable; new V2 corrections cannot mutate legacy dictionaries or another event |
| Correction and report regeneration flows | 5, 8, 10-14, 17, 19 | Replace raw overlays with revisioned event/claim/anchor/moment corrections and regenerate from the resulting fact revision | Applied legacy corrections are adapted as a complete legacy fact revision; no startup backfill rewrites V2 evidence |
| `/plan/:plan_id` and `GrowthPlanHub` | 5, 11-14, 17-19 | Generate/regenerate/fallback/extend from confirmed coachable facts with source hash; retain completion state and share | Existing plans remain immutable historical snapshots until explicitly regenerated |
| Training sessions and analysis/session links | 0, 5, 17-19 | Preserve create/read/update/delete and linkage independent of pipeline mode | Analysis authority changes cannot detach or duplicate a session |
| `/growth`, `/archive`, `/history`, `/progress` | 5, 11-14, 17-19 | Build counts, focus, metrics, media, filters, and timeline from compatible facts | Counts remain defined; incompatible technical metrics are excluded with reasons rather than mixed |
| `/compare` and `GrowthCompareHub` | 5, 6, 10-14, 17-19 | Compare event-aligned claims/moments/media only when definitions are compatible; retain persisted jobs and retry | Legacy-to-legacy remains available; cross-authority comparison is labeled and refuses incompatible deltas |
| `/path`, skills, milestones, XP/streak/avatar | 5, 11, 14, 17-19 | Preserve manual lock/unlock and learning path; auto-unlock only from eligible confirmed facts under versioned rules | Existing unlock history remains; no Shadow, uncertain, changed score, or unobservable claim auto-unlocks |
| `/chapters` and monthly facts | 5, 11-14, 17-19 | Preserve fact preview, generation, edit, revision, publish, recycle/restore/delete and representative media from compatible facts | Published revisions and hashes remain immutable; legacy/V2 facts cannot silently share a metric bucket |
| `/annual` and annual PDF | 5, 14, 16-19 | Preserve preview, chapter/milestone selection, revision, recycle/restore/delete, resumable export/download and media provenance | Existing annual snapshots/PDFs remain reproducible; new exports retain source authority/definition metadata |
| `/snowball` memories and suggestions | 5, 14, 17-19 | Preserve memory CRUD/pin/expiry/chat; suggestions use confirmed family-safe facts and remain parent-reviewed | Existing memories are not rewritten; Shadow/uncertain technical claims cannot become memory |
| Shares and exports | 5, 6, 12-14, 17-19 | Preserve analysis text export, chat share, milestone/share images, plan shares, report links and annual PDF using authoritative snapshots | Previously generated artifacts remain readable; new artifacts record source fact hash/schema |
| `/me` family/profile/appearance | 0, 5, 17-19 | Preserve PIN setup/verify/change, parent/child mode, skater identity/avatar, classic compatibility, time theme and UI preference | Permissions never weaken; theme/preferences survive mode and pipeline changes |
| Provider/API settings | 0, 5, 14-19 | Preserve provider CRUD/activate/delete/test, encrypted keys, all slots, vote config, specialties, metrics, API health and prompt/model fingerprints | Secret values never enter experience/diagnostic payloads or sanitized reports |
| Pose and multi-person tracking settings | 0, 7-9, 15-19 | Preserve MediaPipe single/multi-pose status, task path/pose count, YOLO path/weights/download, ByteTrack dependencies and candidate/target tools; add V2 model fingerprint/status | Legacy mode remains runnable; model changes invalidate only dependent V2 artifacts and require measured gates |
| System/storage/backup operations | 0, 15-19 | Preserve health/system/storage, scheduler, startup seed/backfill/recovery, archive cleanup, backup list/create/restore/retention and V2 artifact policy | Backup/restore covers schema and durable V2/user artifacts while rebuildable caches stay optional; no live-data experiment |
| Docker, all-in-one, DS918+, standalone pack | 0, 5-7, 14-19 | Keep dependency/model mounts, API/frontend routing, generated core adapter, clean install, upgrade, restart and rollback verified | No independently edited V2 algorithm copy and no package/runtime contract drift |
| Compatibility routes | 0, 5, 14, 17-19 | Preserve `/upload`, `/skills`, `/progress`, `/parent/setup`, `/settings`, `/settings/api`, `/report/:id/workspace`, `/report/:id/pose-debug`, `/report/:id/target`, `/compare/:id_a/:id_b`, and `/compare/results/:comparison_id` | Redirects retain query/deep-link intent, parent gating, selected analysis/event, and historical result semantics |

The owning iteration must update every listed surface affected by its contract change. Later iterations extend the same components; they do not introduce parallel legacy and V2 component trees.

### Full-system preservation ledger

Iteration 0 creates a checked `feature-preservation` ledger from all current frontend routes, exported API client operations, backend routes, persistence models, scheduled/startup jobs, environment/model settings, generated artifacts, Docker/package entry points, and existing focused tests. Each entry must have exactly one owning iteration and these states:

```text
inventoried -> characterized -> adapted -> verified -> retirement-approved (optional)
```

- CI fails if a production route/API/job/model setting disappears without an approved ledger change.
- `retirement-approved` is never inferred from low use or duplicate appearance; it requires explicit owner approval after replacement and migration proof.
- Iteration 17 must report zero unowned or merely inventoried entries. Iteration 19 may remove only entries marked `retirement-approved`.

### Treatment rule

- Semantic consumers are migrated to `AnalysisFactsV2` inside their owning iterations.
- Independent domains are not rewritten merely for uniformity; their existing behavior is characterized and protected across legacy, Shadow, V2, restart, backup/restore, and rollback.
- Operational domains integrate with V2 fingerprints, invalidation, privacy, persistence, model availability, and recovery.
- Any implementation change outside these three treatments requires a separately stated reason tied to a preservation-ledger entry.

## Iteration 0: Isolated Development Foundation

### Objective

Create a safe V2 development environment without modifying the current production data or behavior.

### Changes

- Create the dedicated worktree and branch according to the approved base commit.
- Add a V2-specific untracked environment file pointing to its own `DATA_DIR`, SQLite database, cache, and model outputs.
- Add a central pipeline-mode parser with default `legacy` and reject invalid values at startup.
- Add a no-op shadow orchestrator interface that records no user data yet.
- Record the baseline dependency versions, model paths, provider identities, and source commit.
- Document how to start legacy and shadow modes locally without touching the main data store.
- Generate the initial feature-preservation ledger from all current frontend routes/API client operations, backend routes, database models, startup/scheduled jobs, environment/model settings, exports, Docker/package entry points, and existing focused tests.
- Capture read/write characterization fixtures for chat/corrections, plans, sessions, growth, skills, memories, monthly/annual, comparison, shares/exports, settings, providers, runtime status, backup/restore, and historical URLs before changing their inputs.
- Inventory durable versus rebuildable data, including source videos, analyses, chat/corrections, plans, sessions, skills, memories, chapters, annual exports, Golden labels, V2 artifacts, caches, model files, provider secrets, and UI preferences.
- Record Pose and person-tracker runtime baselines: MediaPipe mode/task path/pose count, YOLO resolved source/path/existence/download behavior, ByteTrack and dependency readiness, relevant tracking configuration, and DS918+ mounts.

### API and Animal Island delivery

- Add a read-only capability endpoint exposing supported experience-schema versions, `legacy | shadow | v2` runtime mode, public authority, and parent-only tool capabilities without exposing private paths.
- Add typed capability loading at application boot. `/home`, `/review`, `/growth`, and `/me` keep their existing routes and Animal Island presentation.
- Add a parent-only `/me/advanced` Shadow status card in an honest `not_configured | disabled | ready` state; it is a discoverable no-op, not fake analysis output.
- If capabilities are absent or incompatible, the entire ordinary experience remains legacy. No V2 component or label appears.

### Tests

- Invalid pipeline mode fails with an actionable configuration error.
- Default mode remains legacy.
- Shadow mode cannot overwrite current legacy result fields.
- V2 runtime paths resolve beneath the V2 data root.
- Existing focused backend tests and frontend production build pass.
- Capability API fixture, TypeScript decoding, boot fallback, four-space route, parent/child authorization, responsive, keyboard, loading, and error-state tests pass.
- The migrated boot/navigation code passes the raw-source import-boundary check.
- Current feature-preservation fixtures pass unchanged in isolated legacy mode, including settings, provider, model-runtime, backup/restore-on-a-copy, startup jobs, and all historical route smoke tests.

### Gate G0

- Separate worktree, branch, runtime data, and database are demonstrated.
- One legacy analysis produces the same public result shape as before.
- One no-op shadow run cannot mutate legacy evidence.
- The capability response and advanced status card agree on mode/authority, and the production frontend build passes without changing the four primary entries.
- FP1 inventory has zero unowned current capabilities and every entry has an owning Iteration 0-19, compatibility expectation, and focused test or explicit new-test task.
- Full-stack gate evidence includes backend/API contract fixtures, checked TypeScript contracts/selectors, affected frontend component and route tests, the production build, responsive/accessibility states, and a zero-violation mixed raw-source import audit.

### Stop condition

Do not build V2 algorithms if runtime isolation is not proven.

## Iteration 1: Golden V2 Schema and Private Catalog

### Objective

Create a source-time-based, leakage-resistant labeling contract before evaluating algorithms.

### Changes

- Define `GoldenDatasetV2`, `GoldenSourceVideo`, `GoldenEventLabel`, `GoldenTrackLabel`, `GoldenPoseLabel`, and revision metadata.
- Identify every source by SHA-256, duration, dimensions, source FPS/VFR metadata, and a private source reference.
- Identify every event by source hash plus start/end PTS.
- Add recording-session and grouping IDs so related clips cannot cross splits.
- Add profiles, subtypes, strata, observability, ambiguity, failure tags, and annotator confidence.
- Store T/A/L, spin phases, step/spiral phases, rotation labels, sparse tracking boxes, and optional pose labels in separate typed fields.
- Add schema migration only for future Golden revisions; do not convert the old historical debug pool.
- Add privacy-safe export producing aggregate metadata without video paths.

### API and Animal Island delivery

- Add parent-authorized catalog/schema/revision endpoints with typed request and response fixtures; ordinary family analysis endpoints never return Golden labels.
- Add the Golden catalog shell under `/golden`, linked only from `/me/advanced`, using `IslandPageHeader`, `IslandCard`, existing controls, and parent-mode density.
- Render empty, schema-incompatible, invalid-source, duplicate-source, and private-export states in family-safe language while retaining precise details in expandable parent diagnostics.
- Generate or contract-check TypeScript Golden types from backend schemas; do not represent Golden records as unbounded dictionaries.

### Likely files

- Create `backend/app/analysis_v2/evaluation/golden_schema.py`.
- Create `backend/app/analysis_v2/evaluation/golden_store.py`.
- Add focused API schemas/routes under the existing Golden workspace boundary.
- Add `backend/tests/analysis_v2/test_golden_schema.py`.
- Add `backend/tests/analysis_v2/test_golden_store.py`.

### Tests

- Invalid time order, out-of-window moments, duplicate event IDs, and invalid boxes are rejected.
- Source hash and session grouping remain stable across renames.
- Duplicate or near-duplicate source records are flagged before split assignment.
- Raw paths are absent from sanitized exports.
- Labels remain readable after a schema round trip.
- Golden API fixtures, TypeScript contract checks, `/me/advanced` to `/golden` authorization/route tests, empty/error/responsive/accessibility component tests, production build, and raw-source import-boundary checks pass.

### Iteration gate

A private empty manifest and a sanitized dataset summary template.

- Full-stack gate evidence includes backend/API contract fixtures, checked TypeScript contracts/selectors, affected frontend component and route tests, the production build, responsive/accessibility states, and a zero-violation mixed raw-source import audit.

## Iteration 2: Lightweight Annotation Workflow

### Objective

Make accurate manual labeling practical enough to build the dataset without frame-by-frame full-body annotation.

### Changes

- Import newly selected videos and compute source metadata.
- Add a source-time player with frame stepping and exact timestamp display.
- Create and edit multiple action intervals from one source video.
- Label action family, optional subtype, observability, and scene strata.
- For jump, capture T/A/L and rotation count/class.
- For spin, capture entry/main/exit and observable turn count or range.
- For step and spiral, capture their profile-specific interval and representative key moment.
- Draw sparse target boxes and mark dense challenge intervals for crossings, occlusion, exits, and relock.
- Mark a joint or full pose as unobservable rather than forcing coordinates.
- Record revision, timestamp, and annotator for every human-confirmed field.
- Keep automatic suggestions hidden for the first labeling pass on frozen-test events to reduce confirmation bias.
- Add a review queue for incomplete, contradictory, or low-confidence labels.

### API and Animal Island delivery

- Deliver the complete themed annotation workspace in `/golden`: source browser, exact-time player, event list, profile-specific form, sparse boxes, pose visibility, rotation convention, revision history, and review queue.
- Reuse the same media shell intended for family analysis so exact PTS, frame stepping, touch targets, keyboard shortcuts, and coordinate overlays are tested once and shared.
- Keep automatic suggestions visually and structurally separate from confirmed human labels; frozen-test first-pass mode must make suggestions inaccessible, not merely hidden with CSS.
- Add save-conflict, unsaved-change, offline/retry, unavailable-frame, and authorization states without allowing partial writes to appear confirmed.

### Annotation protocol

- Collect from at least five recording sessions; more sessions are preferable to more repeated attempts in one session.
- Treat one complete action as one event.
- Keep all events from a source video and recording session in the same split.
- Re-label at least 10% of events after a delay to estimate intra-annotator consistency.
- Double-review all ambiguous rotation labels and all frozen-test identity crossings.
- Exclude genuinely unobservable technical fields from ordinary accuracy denominators, but report their count and the algorithm's refusal behavior.

### Tests

- Frame-step timestamps match extracted source frames within one source-frame duration.
- Editing one event does not modify another event from the same video.
- Saving never promotes an unconfirmed suggestion to Ground Truth.
- Concurrent or repeated saves preserve the latest explicit revision.
- UI exposes incomplete and ambiguous status clearly.
- Annotation API fixtures, generated/checked TypeScript forms, media/overlay/component/route tests, parent authorization, desktop/tablet/mobile, keyboard/contrast/reduced-motion checks, production build, and raw-source import-boundary checks pass.

### Iteration gate

A usable labeling workflow plus a short owner-facing labeling guide.

- Full-stack gate evidence includes backend/API contract fixtures, checked TypeScript contracts/selectors, affected frontend component and route tests, the production build, responsive/accessibility states, and a zero-violation mixed raw-source import audit.

## Iteration 3: Golden Pilot and Evaluator Repair

### Objective

Produce the first trustworthy diagnostic dataset and correct evaluation semantics before tuning V2.

### Data target G1

The fixed G1 target is the verified current catalog: at least 18 source videos and at least 18 valid events.

Require at least:

- 10 jump;
- 4 spin;
- 2 step;
- 2 spiral.

The pilot should include normal, multi-skater, crossing/occlusion, small/distant target, pan/zoom, and blur/compression examples. It is a development diagnostic set, not the final release set.

### Evaluator changes

- Match predictions and labels by source hash, event ID, source frame index, and PTS.
- Include missing predictions in denominators.
- Separate `wrong_person`, `lost`, `uncertain`, `false_relock`, and low-IoU localization.
- Add confirmed/uncertain/lost coverage.
- Add action proposal recall and action-class confusion matrices.
- Add profile-specific key-moment timing errors.
- Add rotation MAE, class accuracy, confidently wrong rate, and refusal quality.
- Add pose joint availability, PCK/OKS subset metrics, provenance, and wrong-person skeleton rate.
- Add per-stratum raw counts and confidence intervals.
- Add explicit evaluation masks so the field being evaluated cannot be injected as an input.
- Add machine-readable diff reports and fail gates.

### API and Animal Island delivery

- Add parent-authorized evaluator run/status/result endpoints whose public artifacts use redacted aliases and whose private event drill-down never leaks into ordinary analysis APIs.
- Add a Golden pilot dashboard under `/golden` for progress, denominators, coverage, refusal, confidence intervals, strata, confusion matrices, and failed-event review; use the existing island visual language rather than an engineering-themed primary page.
- Show `not_run`, `running`, `invalid_labels`, `failed`, and `passed_for_pilot_only` explicitly. A pilot result can never be rendered as release approval.
- Link evaluator failures back to the exact annotation event and source PTS without changing labels from the dashboard.

### Tests

- A missing track frame lowers coverage and recall rather than disappearing from the denominator.
- A wrong-person relock is not counted as merely lost.
- An unobservable rotation refusal is not scored as a wrong confident estimate.
- A Golden T/A/L value injected into a key-moment prediction run triggers leakage detection.
- Reordering manifest records cannot change metrics.
- Identical prediction and label fixtures pass only the intended metric, without manufacturing unrelated fields.

### Gate G1

- At least 18 source videos are present.
- At least 18 events pass schema and source-frame validation.
- Profile minimums 10/4/2/2 and all existing scene minimums pass.
- At least 5 recording sessions are represented.
- Split grouping and duplicate checks pass.
- At least 2 events have a valid delayed relabel review.
- Every ambiguous rotation and applicable frozen-test crossing has its independent review attestation.
- Evaluator fixture tests pass.
- Pilot metrics are recorded as diagnostic, not release claims.
- Evaluator/status API fixtures, TypeScript result decoding/selectors, Golden dashboard and drill-down route tests, responsive/accessibility/loading/error tests, production build, and raw-source import-boundary checks pass.
- Full-stack gate evidence includes backend/API contract fixtures, checked TypeScript contracts/selectors, affected frontend component and route tests, the production build, responsive/accessibility states, and a zero-violation mixed raw-source import audit.

## Iteration 4: Full Golden Set and Frozen Legacy Baseline

### Objective

Reach enough varied data to measure the architectural replacement honestly.

### Data target G2

Freeze 24-30 valid events:

- 10-14 jump;
- 6-8 spin;
- 4-5 step;
- 4-5 spiral.

Require at least 4 eligible examples for any subtype reported separately and target 6. Keep subtypes with fewer than 4 examples grouped by action family and mark them `insufficient_sample` for standalone metrics.

### Split

- Development: approximately 60%.
- Validation: approximately 20%.
- Frozen test: approximately 20%.

Assign by recording group, not by random event. Publish only redacted aliases and aggregate distribution.

### Legacy baseline

- Freeze a legacy pipeline fingerprint.
- Run every Golden event without injecting the field being evaluated.
- Store private per-event predictions and a sanitized aggregate report.
- Record failures and coverage for tracking, pose, action, key moments, and rotation.
- Manually review the largest apparent successes and failures to detect evaluator mistakes.

### API and Animal Island delivery

- Extend the parent Golden dashboard with dataset distribution, grouping/duplicate warnings, split lock, frozen-test access state, legacy fingerprint, baseline comparisons, and sanitized-report download.
- Require an explicit parent confirmation before freezing; after freeze, the UI becomes read-only for test membership and records any authorized new revision as a new dataset version.
- Present sparse strata and wide confidence intervals honestly; do not use celebratory success treatments for underpowered percentages.
- Keep baseline/gate terminology out of child mode and ordinary family reports.

### Gate G2

- The total is 24-30 and every profile is within its approved range.
- Required scenario coverage remains met and actual denominators are reported.
- Frozen-test membership and hashes are recorded and locked.
- Legacy baseline JSON/Markdown is committed without private paths.
- Re-running the same baseline produces stable aggregates within declared nondeterminism limits.
- Dataset/baseline API fixtures, TypeScript compatibility, freeze/unfreeze authorization and route tests, dashboard component tests, responsive/accessibility states, production build, and raw-source import-boundary checks pass.
- Full-stack gate evidence includes backend/API contract fixtures, checked TypeScript contracts/selectors, affected frontend component and route tests, the production build, responsive/accessibility states, and a zero-violation mixed raw-source import audit.

### Stop condition

No V2 result can be called more accurate until this gate passes.

## Iteration 5: Canonical Contracts and Pipeline Fingerprints

### Objective

Establish stable boundaries before writing new algorithms.

### Changes

- Implement the contracts from the design: `FrameObservation`, `TrackCandidate`, `TrackState`, `PoseObservation`, `ActionEvent`, `KeyMoment`, `RotationEstimate`, and `EvidenceClaim`.
- Add schema versions and strict serializers.
- Add invariants for state, PTS, coordinate spaces, provenance, confidence, and observability.
- Add a pipeline fingerprint covering source commit, model files, configuration, provider/model identity, prompt version, and contract version.
- Add an immutable `RunManifest` linking stage inputs and outputs by content hash.
- Add adapters from legacy sampled frames, tracks, pose, and keyframes for shadow comparison only.
- Implement backend `AnalysisFactsV2` projections from the same legacy/V2 authority as `AnalysisExperienceV2`, with use permissions for display, coaching, aggregation, comparison, correction, automation, share, and export.
- Add source fact hash/revision, authority, definition/unit/convention compatibility, observability, confidence, and provenance to all new downstream artifact contracts.

### API and Animal Island delivery

- Implement the backend-owned `AnalysisExperienceV2` presenter and versioned endpoint as the only modern frontend analysis contract.
- Generate or contract-check `frontend/src/analysis-v2/contracts.ts`; add typed transport, capability negotiation, selectors, status language, and a whole-record legacy adapter owned by the backend presenter.
- Migrate the `/analysis/:id` shell, latest-analysis card, review inbox shell, growth ingestion boundary, archives, and historical report routing to that experience model before adding V2 fields.
- Add bounded fact-consumer interfaces for follow-up/corrections, plans, comparison, progress/growth, skills, memories, chapters/annual, shares, and exports. Initially their legacy projection must reproduce characterized behavior before V2 facts are enabled.
- Add source fact schema/hash/fingerprint fields to new plan, comparison, chapter, annual, share/export, chat-context, correction, skill-automation, and memory-suggestion writes without rewriting historical snapshots.
- Every ordinary envelope declares exactly one `authority`. Shadow returns a separate parent-authorized comparison resource and cannot be selected by ordinary-page code.
- Preserve the existing single-event legacy layout, sections, Animal Island components, parent/child modes, and stable URLs through the wholesale adapter.

### Tests

- Contract round trips are stable and deterministic.
- Invalid confirmed tracks without a valid bbox are rejected.
- An interpolated joint cannot claim `measured` provenance.
- Output hashes change when a relevant model/config/prompt changes and remain stable otherwise.
- Legacy adapters cannot mutate source legacy dictionaries.
- Backend/OpenAPI and TypeScript fixtures reject contract drift, unsupported schema versions, mixed-authority events, or cross-authority review tasks.
- Backend dependency-boundary tests reject direct raw-field reads from every migrated downstream service, while legacy adapters remain the only bounded exception.
- Characterization fixtures prove legacy chat/corrections, plan/session, growth/skills, memory, chapter/annual, compare, share/export, settings, providers, runtimes, backup/restore, and startup jobs retain behavior through their adapters.
- Component and route tests prove a legacy record renders completely, a missing V2 claim stays unavailable, Shadow is absent from ordinary endpoints, and historical links still open.
- Production build, responsive/accessibility/loading/error/empty tests, cache-key rollback tests, and a static import-boundary test forbidding migrated production components from raw Path A/B, `bio_data`, and legacy pose fields pass.

### Iteration gate

UX1 plus the first half of FP2: a contract-complete V2 package, presenter-backed modern frontend, and downstream fact boundary with no changed legacy-visible conclusions or lost capability.

- Full-stack gate evidence includes backend/API contract fixtures, checked TypeScript contracts/selectors, affected frontend component and route tests, the production build, responsive/accessibility states, and a zero-violation mixed raw-source import audit.

## Iteration 6: Source PTS and Observation Stream

### Objective

Replace derived uniform timing with exact source timing everywhere in V2.

### Changes

- Probe stream timebase, VFR behavior, rotation metadata, dimensions, and duration.
- Decode or index source frames with source frame index and PTS.
- Build a dense low-resolution tracking stream whose observations retain source references.
- Build source-frame extraction by PTS/frame index for local refinement.
- Represent decode gaps and discontinuities explicitly.
- Provide transforms between source frame, tracking proxy, target crop, and annotated display coordinates.
- Prohibit V2 physical metrics from accepting `effective_fps` without timestamps.
- Migrate comparison playback, representative-frame selection, analysis/chat shares, report/export frame links, and annual media resolution to canonical source PTS/frame references while retaining legacy approximate references.

### API and Animal Island delivery

- Add exact source-time media metadata and timeline mapping to `AnalysisExperienceV2`; selectors expose PTS/frame identity without components recalculating time from sampled FPS.
- Upgrade the shared media player and `/analysis/:id` timeline to exact seek/frame-step behavior while retaining the Animal Island controls and existing section navigation.
- Show decode gaps, timestamp unavailability, rotation metadata, and approximate legacy timing as explicit presentation states; an approximate legacy marker is never presented as exact V2 evidence.
- Reuse the exact-time player in `/golden` and parent diagnostics so annotation, evidence review, and family playback point to the same source frame.
- Preserve media quality selection/renditions, synchronized before/after playback, share/export thumbnails, source-video authorization, and cleanup behavior across legacy, Shadow, and V2 artifacts.

### Tests

- Constant-frame-rate, variable-frame-rate, duplicate-PTS, dropped-frame, and rotated-video fixtures.
- Coordinate round trips stay within tolerance.
- Re-encoding equivalent content at a different container FPS preserves event timestamps within one source frame.
- No V2 time calculation divides sampled-frame count by an average FPS.
- Dense and sparse streams resolve to the same source frame identity.
- Media-contract fixtures, TypeScript timeline selectors, player seek/frame-step/transform tests, analysis/Golden route tests, desktop/tablet/mobile, keyboard/touch/reduced-motion/accessibility states, production build, and raw-source import-boundary checks pass.

### Gate G3

- Timebase and metamorphic tests pass.
- A static audit finds no sampled-frame-count physical timing in V2.
- Legacy public output remains unchanged in shadow mode.
- Full-stack gate evidence includes backend/API contract fixtures, checked TypeScript contracts/selectors, affected frontend component and route tests, the production build, responsive/accessibility states, and a zero-violation mixed raw-source import audit.

## Iteration 7: Detection, Camera Motion, and Short-Track Proposals

### Objective

Build reusable observations without yet making identity decisions.

### Changes

- Preserve and wrap the current YOLO model resolution policy, mounted/default/downloaded weights behavior, ByteTrack/supervision/torchvision dependencies, preview candidate selection, manual target lock, and person-tracker diagnostics as versioned candidate providers.
- Inventory every current `PERSON_TRACKER_*` option. Keep it functional and characterized in legacy mode; map only evidence-backed V2 choices into the typed fingerprinted tracking configuration, and mark any redundant scenario option for Iteration 19 review rather than silently dropping it.
- Preserve all plausible skater candidates and short tracks, not just one selected box.
- Estimate camera pan, zoom, and shake from background features while masking detected people.
- Score blur, clipping, full-body visibility, crowd overlap, and candidate quality.
- Rank anchor frames for identity confirmation by quality rather than motion alone.
- Persist proposal diagnostics in the shadow artifact stream.

### API and Animal Island delivery

- Expose proposal/camera/quality diagnostics only through a parent-authorized observation resource referenced by the Shadow experience, never through the ordinary family envelope.
- Add an Animal Island-styled observation panel under `/me/advanced` or `/debug` showing candidate boxes/short tracks, camera-motion reliability, quality strata, anchor suggestions, and `not_run | running | unavailable | failed | complete` states.
- Use restrained diagnostic overlays and expandable technical detail; child mode and the four primary navigation labels remain unchanged.
- Anchor suggestions are review aids only and cannot alter an analysis or Golden label in this iteration.
- Expand Resident Services model/runtime diagnostics to show configured versus active detector/tracker, model hash/source, dependency readiness, legacy/V2 use, invalidation scope, and DS918+ compatibility without exposing private paths in ordinary UI.

### Tests

- Synthetic pan/zoom does not become equivalent skater motion after compensation.
- Camera estimation failure lowers reliability without raising an exception.
- Crossing candidates remain distinct short tracks.
- Tiny targets and temporary detector misses preserve candidate uncertainty.
- Proposal output is deterministic under fixed detector fixtures.
- Diagnostic API fixtures, TypeScript decoding/overlay selectors, parent authorization, route/component/media-overlay tests, responsive/accessibility/loading/error states, production build, and raw-source import-boundary checks pass.

### Evaluation

Measure detection/candidate recall independently from identity accuracy. Do not tune identity gates yet.

### Iteration gate

- Candidate-recall metrics and proposal diagnostics are available from the parent workspace without changing an ordinary family response.
- Full-stack gate evidence includes backend/API contract fixtures, checked TypeScript contracts/selectors, affected frontend component and route tests, the production build, responsive/accessibility states, and a zero-violation mixed raw-source import audit.

## Iteration 8: Identity Tracking V2

### Objective

Convert candidates into an identity-authoritative `confirmed | uncertain | lost` timeline.

### Changes

- Support several manual identity anchors across the source timeline.
- Build an immutable manual template and a separate short-term template.
- Combine appearance, body proportions/pose shape, camera-compensated motion, box continuity, and optional face evidence behind explicit reliability weights.
- Require an identity margin over the second-best candidate.
- Freeze template updates during crossings, low margin, uncertain recovery, and a stabilization period after relock.
- Run forward and backward tracking through an overlap region.
- Fuse matching evidence; output a conflict interval if directions disagree.
- Add crossing guard and false-relock diagnostics.
- Allow an optional additional anchor to resolve a conflict without changing earlier confirmed intervals silently.
- Keep stale/fallback boxes as display hints only.

### API and Animal Island delivery

- Add identity state, conflict intervals, anchor revisions, and one recommended review task to the V2 presenter and parent-authorized Shadow contract.
- Add the main-skater confirmation flow to `/review`: choose or add a high-quality anchor, inspect forward/backward conflicts on the exact source timeline, confirm intentionally, and see which intervals will be recalculated.
- On `/analysis/:id`, render `confirmed`, `需要确认`, and `这段没有跟清楚` consistently; uncertain/lost intervals suppress pose and conclusions instead of falling back to legacy.
- In Shadow mode the ordinary page remains wholly legacy; the new identity timeline is visible only to the parent Shadow reviewer.

### Tests

- Same-clothes crossing, foreground occlusion, full exit/re-entry, fast pan, zoom, small target, and detector dropout fixtures.
- First wrong relock cannot mutate the immutable identity template.
- Forward/backward disagreement becomes uncertain, never confirmed.
- A stale box cannot satisfy confirmed coverage.
- Additional anchors resolve only causally affected intervals and retain revision provenance.
- Identity/review-task API fixtures, TypeScript state-machine and selectors, confirmation/revision/authorization tests, `/review` and analysis route tests, timeline/overlay component tests, responsive/accessibility/loading/conflict/error states, production build, and raw-source import-boundary checks pass.

### Golden evaluation

- Run development and validation first.
- Calibrate identity score and margin on validation only.
- Run frozen test once for the gate candidate.

### Gate G4

- Confirmed identity switches: 0 on frozen test.
- Multi-skater identity accuracy: at least 95%.
- Core-event confirmed coverage: at least 90% initially, with a target of 95%.
- False relock does not exceed legacy.
- Accuracy, uncertain coverage, lost coverage, and longest lost interval are reported together.
- Full-stack gate evidence includes backend/API contract fixtures, checked TypeScript contracts/selectors, affected frontend component and route tests, the production build, responsive/accessibility states, and a zero-violation mixed raw-source import audit.

### Conditional experiment

If HSV/body-shape evidence cannot pass G4, benchmark a lightweight ReID or face embedding as an additional signal. Adopt it only if the frozen protocol shows a meaningful gain without violating privacy or DS918+ limits. Do not introduce it merely because it is available.

Any optional identity model receives a settings/runtime status, model/config fingerprint, privacy/retention declaration, resource result, enable/disable/rollback control, and Shadow-only badge before it can be considered. Disabling it must leave YOLO+ByteTrack candidate generation operational.

## Iteration 9: Pose V2 and Joint Provenance

### Objective

Produce trustworthy target-only pose observations without hiding uncertainty through interpolation.

### Changes

- Preserve both current MediaPipe fallback single-pose and task-based multi-pose modes, `POSE_NUM_POSES`, task model path resolution, runtime status, and model-missing behavior behind the V2 pose-provider interface; run the selected provider only on confirmed target crops with configurable context margin.
- Map joints into source coordinates.
- Record joint confidence, visibility, crop clipping, body scale, and source method.
- Apply gap-aware smoothing using PTS.
- Break smoothing at identity uncertainty, scene cuts, and large time gaps.
- Preserve raw measured observations alongside smoothed presentation values.
- Keep interpolated joints display-only unless a future metric explicitly permits them.
- Produce per-frame and per-phase pose quality.

### API and Animal Island delivery

- Add pose availability, joint/phase quality, and provenance summaries to the authoritative event experience; raw joint evidence remains behind an authorized detail resource when needed for rendering.
- Update `PoseViewer` and the 身体与姿态 section to distinguish measured, smoothed, interpolated-display-only, missing, clipped, and identity-blocked states without implying that smoothing creates evidence.
- Synchronize pose overlays with selected event and source PTS. Do not display a skeleton for uncertain/lost target intervals.
- Growth and report selectors cannot consume interpolated-only or identity-blocked biomechanical claims.
- Update Resident Services Pose runtime status to distinguish configured, active, fallback, missing model, model hash/version, pose count, legacy/V2 use, and dependent-artifact invalidation.

### Model bakeoff

First evaluate the corrected existing pose model. If pose quality still blocks G5, compare a small number of pretrained alternatives on the same labeled subset. Compare accuracy, joint availability, latency, memory, model size, and DS918+ feasibility. Change the model only after the data-contract fixes are measured.

### Tests

- Wrong/uncertain identity produces no authoritative pose.
- Crop-to-source coordinate transformations are correct.
- Variable time gaps change smoothing strength correctly.
- Interpolation cannot enter authoritative biomechanics.
- Left/right swaps and missing joint visibility are surfaced.
- Pose API fixtures, TypeScript provenance exhaustiveness, viewer/timeline/selected-event tests, growth/report exclusion tests, responsive/accessibility/color-independent provenance/loading/error states, production build, and raw-source import-boundary checks pass.

### Pose labeling target

Start with 24-40 stratified source frames covering action cores, small targets, blur, occlusion, front/back views, and crossings. Expand only where confidence intervals or failure analysis require it.

### Gate G5

- Wrong-person authoritative skeleton rate: 0.
- PCK@0.2: at least 90% on labeled usable joints.
- Joint availability and jitter improve or have an approved tradeoff versus legacy.
- Core-event pose coverage is reported and sufficient for later event stages.
- Full-stack gate evidence includes backend/API contract fixtures, checked TypeScript contracts/selectors, affected frontend component and route tests, the production build, responsive/accessibility states, and a zero-violation mixed raw-source import audit.

## Iteration 10: Multi-Event Proposal Generation

### Objective

Detect all plausible action intervals with high recall before forcing a class.

### Changes

- Generate proposals from camera-compensated track motion, pose dynamics, ice-contact proxies, periodicity, and bounded semantic hints.
- Support several actions in one input video.
- Merge overlapping evidence without collapsing distinct consecutive events.
- Retain candidate profile scores and `unknown`.
- Carry tracking/pose coverage and observability into every proposal.
- Keep proposal generation independent from final subtype classification.

### API and Animal Island delivery

- Extend the authoritative experience with an ordered event collection, exact intervals, proposal status, observability, and stable event IDs; preserve a legacy single-action record as one event.
- Add the multi-event overview, shared source-time event timeline, and event selector to `/analysis/:id`; selection keeps playback, summary, moments, pose, questions, and URL/deep-link state synchronized.
- Add pending action-window confirmations to the `/review` inbox with merge/split/ignore actions and an explicit ordinary-skating/unknown outcome.
- In Shadow mode these V2 proposals remain only in the parent comparison workspace; ordinary pages continue to render the complete legacy experience.
- Extend follow-up/chat, corrections, compare jobs, list/archive filters, highlight/share deep links, and retry/rerun actions with stable event IDs. A multi-event mutation must name one event or explicitly name the whole analysis.
- Preserve the current analysis note, highlight quote, session link, delete, list/status/log, and completed-analysis semantics while adding `partially_observable` as experience state rather than breaking stored status queries.

### Tests

- Multiple jumps, jump followed by spin, interrupted action, ordinary skating, and overlapping proposal fixtures.
- Camera pan alone does not create a high-confidence action.
- Weak evidence remains unknown instead of defaulting to step.
- Proposal merge and split operations preserve source PTS.
- Multi-event API fixtures, TypeScript stable-ID/order/selectors, event-selector/deep-link/timeline/review tests, single-event legacy compatibility, responsive/accessibility/touch/loading/empty/error states, production build, and raw-source import-boundary checks pass.

### Gate G6

- Proposal recall at least 98% on observable Golden events.
- False proposals per minute and proposal coverage are reported.
- No profile stratum has a hidden recall collapse.
- Full-stack gate evidence includes backend/API contract fixtures, checked TypeScript contracts/selectors, affected frontend component and route tests, the production build, responsive/accessibility states, and a zero-violation mixed raw-source import audit.

## Iteration 11: Profile-Specific Action Classification

### Objective

Classify proposals without coupling all action families into one fallback-heavy rule function.

### Changes

- Implement independent jump, spin, step, and spiral classifiers behind a common interface.
- Make each classifier consume only documented features and return evidence contributions.
- Add unknown/ambiguous outcomes.
- Separate broad family classification from specialty subtype classification.
- Let Path A provide bounded semantic support or contradiction, not authoritative localization.
- Calibrate confidence on validation data.
- Add confusion and high-confidence error diagnostics.

### API and Animal Island delivery

- Add profile, optional subtype, `unknown | ambiguous | confirmed`, evidence summary, and confirmation task to each authoritative event.
- Render action state in the event selector, summary, and `/review` inbox with family language; never relabel unknown as step or hide ambiguity behind a generic confidence badge.
- Keep profile-specific cards modular so jump, spin, step, and spiral can expose different supported fields without conditionals leaking into page shells.
- Admit an event to growth only when its profile/definition is confirmed and compatible; show excluded counts and reasons to the parent.
- Migrate action corrections from whole-analysis legacy field overlays to revisioned event-label facts; retain existing propose/apply/dismiss and human provenance.
- Make training-plan selection, analysis filters, progress grouping, compare eligibility, skill matching, monthly facts, and memory suggestions consume confirmed event profiles through `AnalysisFactsV2`; unknown/ambiguous events cannot silently become another family.
- Preserve manual skill lock/unlock and existing unlock history. Automatic action-based unlock remains disabled for V2 facts until the claim/score eligibility rules pass Iteration 14.

### Small-data policy

- Do not train a large supervised classifier on the 24-30 event G2 dataset.
- Start with interpretable temporal features plus pretrained semantic review.
- Use subtype-specific metrics only at 4 or more eligible samples; treat 6 as the recommended target.
- If a lightweight learned calibrator is tested, fit it only on development, select on validation, document features, and keep frozen test untouched.

### Tests

- Profile classifiers are isolated and cannot silently fall through to step.
- Missing required evidence lowers confidence or returns unknown.
- One classifier's configuration change does not alter another classifier's fingerprint.
- Conflicting deterministic and semantic evidence remains visible.
- Action API fixtures, TypeScript discriminated-union exhaustiveness, profile card/unknown/ambiguous/confirmation/growth-exclusion tests, analysis/review/growth route tests, responsive/accessibility/loading/error states, production build, and raw-source import-boundary checks pass.

### Gate G7

- Macro F1 at least 90%, target 95%.
- High-confidence classification error below 2%.
- Unknown/rejection and coverage rates are reported.
- No important stratum regresses materially against legacy without an approved safety tradeoff.
- Full-stack gate evidence includes backend/API contract fixtures, checked TypeScript contracts/selectors, affected frontend component and route tests, the production build, responsive/accessibility states, and a zero-violation mixed raw-source import audit.

## Iteration 12: Profile-Specific Key Moments

### Objective

Localize technical moments on original source frames with fixed, versioned definitions.

### Changes

- Define jump T/A/L operationally and version the definitions.
- Define spin entry/main/exit, spiral entry/hold/exit, and step sequence intervals separately.
- Use profile-specific state machines over timestamped pose and motion evidence.
- Refine coarse candidate windows at source 30/60 FPS.
- Score moments independently and enforce order without fabricating absent stages.
- Preserve competing candidates and warnings.
- Keep semantic keyframes as review evidence, not exact-time Ground Truth.

### API and Animal Island delivery

- Add profile-versioned moment definitions, source PTS, observability, competing candidates, and completeness to the authoritative experience.
- Replace jump-only assumptions in `ActionPhaseStrip`: jump shows T/A/L, spin shows entry/main/exit, spiral shows entry/hold/exit, and step shows sequence interval plus representative moments.
- Keep 关键时刻, media markers, selected event, thumbnails, and seek position synchronized; absent stages show unavailable/incomplete instead of synthesized markers.
- Add moment/interval confirmation tasks to `/review` only when a parent decision can resolve ambiguity.
- Migrate legacy keyframe corrections and video-keyframe rerun into revisioned, event-scoped moment proposals. Preserve propose/apply/dismiss, exact before/after snapshots, and report-regeneration trigger behavior.
- Migrate keyframe chips in follow-up, representative frames in monthly/annual, compare moment pairs, report/share thumbnails, pose-debug links, and evidence exports to profile-specific moment selectors.
- Preserve historical T/A/L chat/correction/share snapshots through the legacy fact adapter; never reinterpret their stored frames as a new V2 definition.

### Tests

- Source-frame boundary, VFR, dropped-frame, incomplete jump, two close events, and ambiguous landing fixtures.
- T/A/L cannot be copied from resolved semantic labels under evaluation.
- Missing landing returns incomplete/unobservable rather than a guessed frame.
- Equivalent transcodes preserve timestamps within tolerance.
- Moment API fixtures, TypeScript profile/moment exhaustiveness, phase-strip/timeline/seek/thumbnail/review-task tests, legacy T/A/L adapter tests, responsive/accessibility/touch/loading/unobservable states, production build, and raw-source import-boundary checks pass.

### Gate G8

- Observable T/A/L median absolute error at most 0.10 seconds.
- P95 at most 0.25 seconds.
- Per-moment errors, completeness, refusal, and event-core tracking coverage are reported.
- Spin/step/spiral metrics use their own definitions and do not borrow jump gates.
- Full-stack gate evidence includes backend/API contract fixtures, checked TypeScript contracts/selectors, affected frontend component and route tests, the production build, responsive/accessibility states, and a zero-violation mixed raw-source import audit.

## Iteration 13: Multi-Signal Rotation Estimation

### Objective

Replace 2D shoulder-angle multiplication with an observable, profile-aware rotation estimate.

### Changes

- Extract shoulder and hip orientation with left/right assignment confidence.
- Extract torso/silhouette and limb-appearance periodicity.
- Extract target-crop optical-flow rotation evidence.
- Detect signal aliasing, occlusion, insufficient sampling, and conflicting turn hypotheses.
- Fuse signal likelihoods into an estimate, interval, and class.
- Separate pre-takeoff, airborne, and post-landing rotation.
- Apply Axel convention only after subtype support is sufficient.
- Provide an explicit unobservable result and reason.

### API and Animal Island delivery

- Add rotation convention, estimate/range/class, confidence, observability, contributing evidence summary, and refusal reason to the authoritative event contract.
- In the summary and key-moment sections show a supported value, a bounded range, or `画面不足，暂不判断`; visually distinguish airborne rotation from competition naming when relevant.
- Never round an uncertain interval into a confident turn count, substitute a legacy value, or turn unobservable into a technique warning.
- Add ambiguous rotation review to `/review` and the Golden workflow with exact source-time playback and double-review status.
- Add definition-compatible rotation facts for compare/progress/monthly/annual selectors. Only confirmed estimates with matching convention and unit may form a delta or trend; ranges and refusals remain contextual evidence.
- Preserve current jump metric labels in historical artifacts, but version and rename V2 metrics where semantics changed so old and new values cannot occupy one bucket.

### Label protocol

- Review rotation at source-frame speed.
- Store exact count when clear, a bounded interval when partially visible, and unobservable otherwise.
- Repeat-review every ambiguous frozen-test rotation.
- Record whether the label follows airborne body rotation or competition naming convention; do not mix them.

### Tests

- Ideal turns, front/back flips, left/right swaps, occlusion, sparse sampling, camera roll, changing arm position, Axel convention, pre-rotation, and continued landing rotation.
- A single unreliable shoulder signal cannot dominate fusion.
- Aliased hypotheses return uncertain/unobservable.
- Rotation duration uses PTS, never sampled-frame count.
- Rotation API fixtures, TypeScript range/value/refusal exhaustiveness, card/timeline/review/Golden tests, report/growth exclusion tests, responsive/accessibility/loading/unobservable/conflict states, production build, and raw-source import-boundary checks pass.

### Gate G9

- Observable rotation MAE at most 0.25 turns.
- Integer/half-integer class accuracy at least 90%.
- Confidently wrong rate below 2%.
- Results are stratified by single/double/triple where available, Axel/non-Axel, and observability.
- Full-stack gate evidence includes backend/API contract fixtures, checked TypeScript contracts/selectors, affected frontend component and route tests, the production build, responsive/accessibility states, and a zero-violation mixed raw-source import audit.

## Iteration 14: Path A, Path B, Claim Fusion, and Reporting

### Objective

Retain the useful dual-review design while preventing either language-model path from becoming an unsupported source of truth.

### Path A changes

- Build an identity-confirmed target-focused clip with enough surrounding context to see travel and ice contact.
- Prevent unrelated skaters from becoming the apparent subject through target marking, crop/context policy, and tests.
- Exclude pose, biomechanics, computed key moments, and rotation values.
- Ask for action-family support, broad stage ranges, visible technique observations, contradictions, and observability.
- Allow uncertainty and refusal.

### Path B changes

- Consume structured source-linked pose and deterministic measurements.
- Render provenance clearly: measured, smoothed, interpolated, uncertain, missing.
- Suppress technical claims when required identity/joint evidence is unreliable.
- Use the language model only to interpret supported measurements.

### Fusion changes

- Fuse claim by claim instead of returning Path A as `vision_structured`.
- Record supporting sources, conflicts, calibrated confidence, observability, and status.
- Block downstream claims during identity conflicts.
- Preserve incompatible estimates instead of averaging them.
- Constrain report generation to the fused claim list.
- Keep legacy A/B fields temporarily for API compatibility and diagnostics.

### API and Animal Island delivery

- Populate the authoritative experience only from fused `EvidenceClaim` records; expose claim status, support, conflicts, observability, and source-linked moments in family-safe form.
- Complete `/analysis/:id` sections 总结、关键时刻、身体与姿态、追问、更多 for all supported profiles and multi-event selection; ordinary copy never mentions internal Path A/B names.
- Route `/report/:id`, archive, compare, and shared historical links through the same presenter. A legacy report remains wholly legacy-authoritative, while a V2 report never borrows a missing legacy claim.
- Let `/growth` consume only confirmed, definition-compatible claims and show why uncertain, changed-definition, or low-coverage values are excluded.
- Add claim conflicts and raw A/B evidence to the parent Shadow workspace only; preserve a single concrete review action rather than exposing competing prose to the family page.

### Complete downstream feature migration

This iteration completes FP2. All family artifacts below consume `AnalysisFactsV2` from exactly the authority used by the analysis experience.

- **Follow-up chat:** preserve analysis selection, history, multi-question replies, provider/model identity answers, event/moment chips, full-rerun and video-keyframe-rerun actions, context snapshots, empty/error/retry states, and chat sharing. New messages name the selected event or whole analysis and store authority/fact hash. The model receives only family-safe supported facts plus explicit unknown/conflict states, never raw Path A/B or legacy `bio_data`.
- **Corrections:** preserve propose/apply/dismiss, manual and chat suggestions, target/action/moment/report-note corrections, before/after snapshots, report regeneration, and audit history. Applying a V2 correction creates an event/claim/anchor/moment fact revision and invalidates dependent artifacts; it never mutates legacy dictionaries. Applied historical corrections are projected as one legacy revision.
- **Training plans:** preserve create/read/regenerate, AI failure fallback, day/session completion, extension, latest-plan entry, sharing, and existing completed state. Generation uses only confirmed coachable claims and stores source fact hash/schema/authority/prompt/provider fingerprint. Existing plans remain historical snapshots; changed facts show `source_updated` and require explicit regeneration.
- **Training sessions:** preserve CRUD and analysis/session linking. Session identity, completion, notes, duration, coach flag, and linkage do not change when an analysis authority changes or a report is regenerated.
- **Growth/home/archive/progress:** preserve counts, current focus, timeline, filters, KPIs, milestones, latest analysis, representative media, and history. Counts may span authorities under a stable definition; technical trends require compatible fact definitions and expose excluded/rejected coverage.
- **Comparison:** preserve immediate and persisted comparison flows, status/retry, before/after synchronized media, score/metric/moment/quality changes, and semantic summary. Match by event/profile and compatibility group; label legacy-to-V2 definition changes and refuse unsupported deltas instead of aligning unrelated events.
- **Skills/learning path:** preserve catalog, manual lock/unlock, attempt/best state, milestones, XP/streak/avatar, and source analysis links. Automatic unlock requires an eligible confirmed fact and versioned score/rule definition; Shadow, uncertain, unobservable, corrected-but-unconfirmed, or definition-incompatible evidence cannot unlock.
- **Snowball memory:** preserve memory CRUD, pin, expiry, chat, suggestion review/apply/dismiss, and existing memory text. New technical suggestions require confirmed family-safe facts and remain parent-reviewed; changed analysis facts do not rewrite accepted memories.
- **Monthly chapters:** preserve facts preview, generation, editing, revision, publish, recycle/restore/permanent-delete, quote facts, representative frames, source hash, and provider provenance. Metrics, recurring observations, focus, milestones, and frames come from eligible fact projections; published revisions stay immutable.
- **Annual collections:** preserve preview, chapter/milestone selection, creation/revision, recycle/restore/permanent-delete, resumable PDF generation/status/download, fonts, source hash, and representative media. It consumes immutable chapter/milestone snapshots and records their authority/definition coverage without rewriting old annual books.
- **Shares and exports:** preserve analysis text export, report links, chat share, plan/milestone/share images, compare media, and annual PDF. New artifacts record experience/fact schema, authority, source hash, and renderer version; previously generated artifacts and URLs remain readable.
- **Providers and prompts:** preserve provider CRUD/activate/delete/test, encrypted credentials, metrics/specialties, vote config, and `vision`, `vision_path_a`, `vision_path_b`, `report` compatibility slots. Map V2 review roles explicitly, fingerprint the chosen provider/model/prompt, and keep legacy-only vote settings labeled rather than silently applying them to V2 fusion.

Ordinary frontend surfaces render these capabilities inside the existing Animal Island spaces. Parent-only mutations and provider/model details stay in Resident Services or existing parent gates; no capability is moved into child mode merely to simplify routing.

### Tests

- Path A prompt has no pose/biomechanics/computed-rotation leakage.
- Path B cannot promote interpolated or uncertain joints into authoritative facts.
- A/B disagreement affects only related claims.
- Report generation cannot introduce an action, timestamp, turn count, or technique defect absent from claims.
- Path A or Path B timeout leaves deterministic evidence retryable.
- Provider/model/prompt changes update fingerprints.
- Claim/report API fixtures, generated/checked TypeScript claims, unsupported-claim and authority invariants, all analysis/report/archive/compare/growth routes, family-language and parent/child tests, desktop/tablet/mobile/accessibility/loading/error/unobservable/conflict states, visual regression, production build, and raw-source import-boundary checks pass.
- Follow-up tests cover selected-event context, history, multiple questions, identity response, raw-evidence exclusion, all correction mutations, rerun actions, regeneration invalidation, shares, and legacy snapshots.
- Plan/session tests cover generation, fallback, explicit regeneration, stale-source indication, completion, extension, latest lookup, linkage, share, and legacy plan immutability.
- Growth/compare/skill tests cover compatible/incompatible definitions, coverage/refusal, persisted job retry, media synchronization, manual skill actions, automatic-unlock eligibility, XP/streak preservation, and Shadow exclusion.
- Memory/monthly/annual tests cover every current mutation, revision and recycle state, immutable hashes, representative source PTS, provider failure/retry, startup PDF recovery, existing PDF download, and Shadow/unconfirmed exclusion.
- Export/share/provider tests cover all artifact types and historical URLs, source hash/fingerprint, secret redaction, provider slot compatibility, activation/test/metrics, vote-setting scope, and legacy/V2 rollback.
- Static backend boundary audit reports zero direct raw analysis-field reads in migrated downstream services; static frontend audit covers every migrated page/component, not only analysis detail.

### Gate G10

- All technical report statements trace to one or more evidence claims.
- Unsupported-claim test suite is clean.
- Conflicts and unobservable states survive into user-visible summaries.
- A/B repeatability and provider failure behavior are documented.
- UX2 passes: the ordinary V2 experience is complete for multi-event action, moments, pose, rotation, reports, and review without a mixed-source read.
- FP2 passes: every analysis-semantic downstream service listed above consumes the same-authority fact projection, and all existing writes/revisions/artifacts remain functional.
- Full-stack gate evidence includes backend/API contract fixtures, checked TypeScript contracts/selectors, affected frontend component and route tests, the production build, responsive/accessibility states, and a zero-violation mixed raw-source import audit.

## Iteration 15: End-to-End Shadow Orchestration

### Objective

Run legacy and V2 on the same analysis without changing the user's authoritative report.

### Changes

- Add stage checkpoints and dependency hashes.
- Run V2 asynchronously or under a bounded local queue so legacy latency remains acceptable.
- Persist V2 artifacts separately from legacy fields.
- Add a stage-by-stage diff: timebase, candidate coverage, identity, pose, event, key moments, rotation, claims.
- Add restart/resume and cache invalidation when source/model/config/prompt changes.
- Add a reviewer view for conflicts and largest metric deltas.
- Ensure deleting rebuildable V2 artifacts never deletes source video or Golden labels.
- Run a Shadow contamination sentinel across plans, chat/corrections, comparisons, progress, skills, memories, chapters, annual collections, shares, exports, and notifications; creating Shadow artifacts must leave every family table and artifact hash unchanged.

### API and Animal Island delivery

- Add parent-authorized Shadow run, status, stage diff, artifact-reference, retry, and review-decision endpoints separate from `AnalysisExperienceV2` family responses.
- Complete the Shadow workspace under `/me/advanced`: legacy/V2 side by side, first divergent stage, exact-time identity conflicts, pose provenance, event/moment/rotation/claim differences, fingerprints, gate links, retry/resume, and reviewer notes.
- Keep the workspace visually part of Resident Services/Animal Island while allowing denser parent diagnostics; it is not added to primary navigation and is inaccessible in child mode.
- Comparison is read-only by default. Any correction or candidate promotion is an explicit, authorized, audited action and cannot rewrite the legacy report.
- Ordinary `/home`, `/review`, `/analysis/:id`, and `/growth` continue to receive only the legacy-authoritative response while mode is `shadow`.
- Show downstream impact in the parent Shadow workspace as a dry-run list (`would_change`, `excluded`, `incompatible`, `unchanged`) without executing plan regeneration, skill unlock, memory suggestion, chapter/annual changes, or exports.

### Tests

- Shadow failure cannot fail or overwrite the legacy analysis.
- Restart resumes at the first invalid or incomplete stage.
- Changing pose config invalidates pose and descendants, not decoded source observations.
- Changing a report prompt does not rerun tracking.
- Duplicate shadow requests coalesce safely.
- Storage cleanup respects source/label retention.
- Shadow execution leaves all existing downstream rows, completed artifacts, published revisions, parent settings, provider activation, and backup inventory byte/logically unchanged except the isolated Shadow audit tables.
- Shadow API fixtures, TypeScript stage/diff contracts, authorization, side-by-side synchronization, retry/resume/cache, review-decision, route and ordinary-endpoint isolation tests, responsive/accessibility/loading/partial-failure states, visual regression, production build, and raw-source import-boundary checks pass.

### Gate G11

- Repeated-analysis agreement at least 95% under fixed fingerprints.
- Every unexplained legacy/V2 difference identifies its first divergent stage.
- A full Golden shadow run completes without private data in committed reports.
- No legacy public API regression.
- Full-stack gate evidence includes backend/API contract fixtures, checked TypeScript contracts/selectors, affected frontend component and route tests, the production build, responsive/accessibility states, and a zero-violation mixed raw-source import audit.

## Iteration 16: Calibration, Resource Limits, and Production Candidate

### Objective

Calibrate uncertainty and prove the complete V2 is operationally safe on the deployment class.

### Changes

- Calibrate identity margins, action confidence, key-moment confidence, rotation intervals, and refusal policies on validation only.
- Freeze configuration and create a production-candidate fingerprint.
- Run frozen test without threshold edits.
- Add CPU, memory, latency, disk, external-provider cost, and queue telemetry by stage.
- Test DS918+ with representative concurrent uploads and restarts.
- Establish local concurrency caps, model-loading strategy, cache limits, and cleanup policy.
- Add privacy review for crops, embeddings, logs, and exports.
- Write operator runbooks for enable, disable, resume, rollback, and artifact cleanup.
- Define durable/backup-required versus rebuildable/cache V2 artifacts; version database migrations and downgrade/read behavior for every new fact, correction, plan, comparison, and audit record.
- Validate startup initialization, correction compatibility backfill, skater/skill/memory seed idempotence, optional progress sync, archive scheduler, media cleanup, interrupted annual-export recovery, health checks, and background task shutdown with the new schemas.
- Validate provider secrets/encryption and every provider role, vote configuration scope, provider metrics, API test, model/task/weights mounts, clean/offline startup behavior, and fingerprint-driven cache invalidation.

### API and Animal Island delivery

- Add parent-authorized pipeline health, queue/resource, candidate fingerprint, artifact retention, provider retry, and mode-readiness endpoints with redacted operational detail.
- Add a pipeline/status workspace under `/me/advanced` and synchronize entry badges on `/home` and `/review` to user-relevant states only: processing, needs confirmation, completed, partially observable, delayed, or failed.
- Separate family actions from operator actions: family pages may retry/continue an analysis where safe; only the parent advanced workspace may change candidate mode, concurrency, retention, or rollback controls.
- Cache keys include experience schema and authority. Switching mode or rolling back invalidates incompatible frontend caches before rendering another authority.
- Complete Resident Services surfaces for system/storage, backups, skater/profile/avatar, PIN, appearance, Provider/API, Pose runtime, detector/tracker/optional identity models, queue/resources, Golden, Shadow, and diagnostics without changing parent authorization.

### Operational targets

Exact latency and memory budgets are measured during this iteration and approved before rollout. At minimum:

- no out-of-memory restart loop;
- bounded queue and concurrency;
- source and Golden labels survive restart and cleanup;
- failed external review calls can retry without rerunning local vision;
- legacy mode remains immediately selectable;
- V2 artifacts have predictable retention and disk growth.
- Backup creation/restoration on a copied data root preserves all durable legacy and V2 user data, provider configuration/secrets, correction/chat/plan/session/skill/memory/chapter/annual state, and source references; rebuildable caches are documented and safe to omit.
- Clean install, copied-database upgrade, downgrade/read compatibility, Docker frontend/backend/all-in-one routing, model mounts, annual fonts/PDF, standalone pack generation, offline dependency/model behavior, and DS918+ restart pass.
- Operations API fixtures, TypeScript status state machines, queue/resource/admin authorization, home/review entry synchronization, cache invalidation/rollback, responsive/accessibility/loading/stale/offline/error states, visual regression, production build, and raw-source import-boundary checks pass.

### Gate G12

- G4-G11 still pass under the frozen production-candidate fingerprint.
- DS918+ restart, queue, memory, storage, and cleanup tests pass.
- Privacy and sanitized-export checks pass.
- Rollback to legacy is demonstrated without database restoration.
- Resident Services and every setting/model/runtime write/read path pass parent authorization, secret redaction, restart persistence, invalidation, unavailable-model, and rollback tests.
- Full-stack gate evidence includes backend/API contract fixtures, checked TypeScript contracts/selectors, affected frontend component and route tests, the production build, responsive/accessibility states, and a zero-violation mixed raw-source import audit.

## Iteration 17: Pre-Release Review

### Objective

Decide whether the completed V2 branch is safe enough to build and deploy as a controlled pre-merge candidate. Do not merge it into the main worktree yet.

### Required review packet

- Full branch diff and architecture map.
- Database/schema migration and downgrade behavior.
- Private dataset hash and sanitized distribution summary.
- Legacy baseline and every gate report.
- Final frozen-test report with raw counts and confidence intervals.
- Per-stratum regressions and approved tradeoffs.
- DS918+ operational report.
- Known limitations and unsupported action subtypes.
- Privacy review.
- Rollback procedure.
- List of legacy modules retained and retirement rationale.
- Full frontend migration inventory showing every analysis-facing route/component, its presenter selector, authority behavior, legacy fixture, V2 fixture, and parent/child visibility.
- Screenshots or visual-regression baselines for the four primary Animal Island spaces, analysis detail, Golden, Shadow, diagnostics, historical reports, and every consequential state.
- Final feature-preservation ledger covering every frontend route/API client operation, backend route, data model, startup/scheduled job, setting/model/env surface, generated artifact, Docker/package path, and focused test; no entry may remain merely `inventoried` or unowned.
- Full downstream provenance report for chat/corrections, plans/sessions, growth/compare, skills/memories, monthly/annual, shares/exports, showing fact authority/hash, compatibility rules, immutable-history behavior, and Shadow exclusion.
- Resident Services matrix for PIN/profile/theme, Provider/API, vote config, provider metrics, Pose single/multi mode, YOLO/ByteTrack/dependencies, optional identity models, health/storage, backups, model mounts, and rollback.

### Final verification

- Run all backend tests in bounded groups if one full run exceeds the execution window.
- Run all frontend tests and production build.
- Run packaging/generation checks for the standalone analysis pack.
- Rebuild the deployment artifact from the V2 worktree.
- Run one clean-install smoke test and one upgrade smoke test using a copied database, never the live database.
- Run the frozen Golden suite against the exact artifact fingerprint.
- Run backend schema fixtures against checked TypeScript contracts and all frontend route/component tests.
- Run the full desktop/tablet/mobile, keyboard, screen-reader semantics, contrast, reduced-motion, loading, empty, error, uncertain, unobservable, authorization, and rollback matrix.
- Run the static import-boundary audit and manually inspect migrated components for raw `bio_data`, Path A/B, legacy pose, or field-level fallback reads.
- Run the backend dependency-boundary audit for downstream raw-field reads and verify the exception list contains only legacy presenters/export readers scheduled for Iteration 19 review.
- Verify no fifth primary navigation entry exists and the Animal Island theme remains coherent in both parent and child modes.
- Exercise every mutating API at least once on copied test data: upload/target/retry/note/session/delete, chat/corrections/regeneration, plans/sessions, compare, skills, memories, chapters/annual/export, PIN/profile, providers/vote config, backup/restore, Golden/Shadow/admin controls.
- Exercise startup/scheduled/recovery paths, every model-runtime status combination, Docker/all-in-one/standalone packaging, and DS918+ clean install/upgrade/restart/rollback.

### Candidate deployment rule

Build the controlled candidate from the exact V2 worktree commit only if:

- all gates pass;
- no unresolved P0/P1 review finding remains;
- the user approves the final report;
- the exact tested commit is the controlled-deployment candidate;
- rollback is documented and tested.
- UX3 passes with one authority per ordinary page and complete entry-point synchronization.
- FP3 passes with zero missing current capabilities, zero unowned ledger entries, zero unauthorized permission changes, zero Shadow family mutations, and zero unexplained historical-artifact regressions.
- Full-stack gate evidence includes backend/API contract fixtures, checked TypeScript contracts/selectors, affected frontend component and route tests, the production build, responsive/accessibility states, and a zero-violation mixed raw-source import audit.

Otherwise keep the V2 branch/worktree intact, record the failed gate, and continue there without modifying main. Passing this review still does not authorize a main-worktree merge.

## Iteration 18: Controlled Pre-Merge Rollout

This iteration deploys an artifact built directly from the approved V2 worktree commit. The main worktree and main branch remain unchanged. Legacy remains available inside the candidate artifact throughout observation.

### Rollout steps

1. Build and identify the candidate artifact from the exact approved V2 worktree commit.
2. Deploy with default `legacy` and verify migration/startup.
3. Enable `shadow` for a bounded set of new analyses and compare operational behavior.
4. Enable V2 authority for manually selected analyses only.
5. Expand to the owner's normal workflow after metrics and resource behavior remain stable.
6. Keep one-step rollback to `legacy` throughout the observation period.
7. Change the candidate artifact's default to `v2` only after explicit approval; this still does not merge main.

### Candidate UI rollout

- The rollout control lives only in `/me/advanced`; it shows the exact candidate fingerprint, current mode, selected analyses, compatibility status, and one-step rollback.
- For a selected `v2` analysis, `/home`, `/review`, `/analysis/:id`, `/growth`, archives, reports, and share routes all switch through the same authority decision. No page or card may retain a cached legacy field beside V2.
- The same selection applies atomically to follow-up/corrections, plan regeneration, compare, progress/growth, eligible skill automation, memory suggestions, future monthly facts, annual inputs, and new shares/exports. Existing snapshots remain tied to their recorded authority and hash.
- Before each expansion, run automated route probes and a parent/child visual/accessibility smoke matrix; store results with the rollout evidence.
- If an experience schema is unsupported, the analysis is not selected for V2 and the UI presents a coherent legacy experience or an explicit unavailable state according to the rollout policy.
- Rollout smoke tests cover Resident Services and all non-analysis features too; a candidate cannot expand if Provider/Pose/tracker settings, PIN, profile/theme, sessions, memories, chapters/annual, backups, or background jobs regress.

### Iteration gate

- Candidate-mode API fixtures, TypeScript authority/cache tests, every affected route, mode-transition/rollback, responsive/accessibility/visual smoke, production build, and raw-source import-boundary checks pass for each rollout expansion.
- Full-stack gate evidence includes backend/API contract fixtures, checked TypeScript contracts/selectors, affected frontend component and route tests, the production build, responsive/accessibility states, and a zero-violation mixed raw-source import audit.

### Rollback triggers

- any confirmed wrong-person result;
- a high-confidence technical claim contradicted by manual review;
- unexplained drift under an unchanged fingerprint;
- queue, memory, storage, or restart instability;
- missing source/label data;
- a material stratum regression not represented in the Golden gate.
- any missing current capability, permission regression, historical artifact change, Shadow leak into a family artifact, incompatible cross-authority trend, automatic skill/memory mutation from ineligible evidence, backup/restore loss, or runtime/model setting drift.

## Iteration 19: Legacy Retirement

### Objective

Remove complexity only after V2 has real controlled-deployment evidence, then produce the final merge candidate.

### Changes

- Run ablations for reusable detector, crop, diagnostics, and fallback components.
- Keep a component only if it has a measured benefit or required compatibility role.
- Delete redundant scenario thresholds and unreachable recovery branches in bounded commits.
- Remove duplicated standalone implementations and retain generated adapters/snapshots only.
- Migrate old stored analyses through read adapters rather than rewriting their historical evidence.
- Update documentation to distinguish legacy historical results from V2 results.
- Reconcile the preservation ledger against the final source tree. Retain compatibility code for every non-retired historical route, API, stored artifact, model setting, job, or package entry.

### Frontend and compatibility cleanup

- Remove direct raw legacy/V2 reads, duplicate normalizers, parallel analysis-detail implementations, and obsolete feature flags from migrated production components.
- Retain one backend legacy presenter for historical records and explicitly bounded parent diagnostics; keep stable routes and Animal Island presentation.
- Remove obsolete UI only after route analytics/inventory and fixtures prove no stored or shared link depends on it; redirects must land on the canonical presenter-backed experience.
- Remove raw downstream legacy adapters only after chat/corrections, plans, compare, growth, skills, memories, monthly/annual, shares, and exports have same-authority facts plus historical fixtures; retain immutable snapshot readers as needed.
- Do not remove MediaPipe fallback, YOLO+ByteTrack provider/runtime visibility, provider slots, settings, backup/restore, or packaging support unless a separately approved replacement/retirement entry exists.
- Update family help text and parent advanced documentation so historical legacy conclusions and current V2 conclusions are clearly identified without exposing unnecessary implementation jargon.

### Gate

- No current stored report becomes unreadable.
- V2 tests and frozen metrics remain unchanged.
- Deployment artifact shrinks or complexity measurably decreases.
- Legacy rollback is retired only after an explicitly approved observation period.
- Final backend/API and TypeScript fixtures, all frontend routes/components, historical-link migration, responsive/accessibility/visual regression, production build, and a zero-violation raw-source import-boundary audit pass.
- The final preservation ledger has no unapproved deletions; every retained feature passes its complete read/write/job/artifact/permission/rollback contract.
- Full-stack gate evidence includes backend/API contract fixtures, checked TypeScript contracts/selectors, affected frontend component and route tests, the production build, responsive/accessibility states, and a zero-violation mixed raw-source import audit.

### Final merge rule

Only after Iterations 0-19 are complete:

1. rerun full repository, packaging, frozen-Golden, privacy, migration, and DS918+ verification on the exact final commit;
2. review the complete V2 branch diff against the current main branch;
3. resolve any changes that arrived on main entirely inside the V2 worktree and rerun affected gates;
4. obtain explicit user approval for the exact final commit;
5. merge the completed branch into main in one controlled integration operation.

No partial iteration, provisional algorithm, or intermediate gate commit is merged into the main worktree.

## Golden Collection Matrix

Use this matrix to select the 24-30 G2 events. One event can satisfy several scene columns, but the dataset summary must show actual counts.

| Dimension | Required coverage |
|---|---|
| Recording sessions | At least 5; prefer 8 or more |
| Rinks/backgrounds | At least 2 if available |
| Camera modes | Fixed, pan/follow, zoom, vertical/horizontal where used |
| Subject scale | Near, medium, small/distant |
| Crowd | Single, multi-skater, crossing |
| Visibility | Clear, partial occlusion, blur/compression |
| Track lifecycle | Continuous, detector miss, exit/re-entry |
| Outcome | Successful, incomplete/failed, ambiguous/unobservable |
| Jump | Several common subtypes and turn counts actually performed |
| Spin | Entry, stable main rotation, exit; more than one spin posture if available |
| Step | Genuine sequences plus ordinary-skating negatives |
| Spiral | Genuine holds plus leg-lift/transition negatives |

Do not manufacture balance by repeatedly clipping the same attempt. Diversity across recording sessions is more valuable than raw clip count.

## Metric Ownership

| Metric | Authoritative source |
|---|---|
| Source time | Decoder/source PTS |
| Identity | Human Golden track labels |
| Pose | Human-labeled usable joints |
| Action event | Human event intervals and family/subtype labels |
| T/A/L and profile moments | Human source-frame review under versioned definitions |
| Rotation | Human source-frame review with observability and convention |
| Path A/B quality | Agreement with supported Golden/fused claims, not prose similarity |
| Report correctness | Claim traceability and unsupported-claim rate |
| Downstream coaching/aggregation | `AnalysisFactsV2` eligible claims plus artifact source hash and definition compatibility |
| Feature preservation | Checked preservation ledger plus characterization/mutation/history/permission/job/artifact tests |
| Settings and models | Runtime/config/provider/model fingerprints plus Resident Services state and restart checks |
| Operations | Runtime telemetry from the exact deployment artifact |

## Test Pyramid

### Per commit

- Focused unit and contract tests for changed modules.
- Static type/lint checks already used by the repository.
- Affected preservation-ledger entries and backend/frontend dependency-boundary tests.
- No external model calls in ordinary unit tests.

### Per iteration

- Relevant legacy characterization tests.
- V2 integration fixtures.
- Affected downstream read/write/artifact/background-job and settings/model-runtime fixtures.
- Frontend route/component and production build for every affected Animal Island or advanced surface.
- Private development/validation evaluation where allowed.
- Artifact fingerprint and privacy checks.

### Per gate

- Gate-specific Golden evaluation.
- Sanitized report generation and review.
- Repeatability run.
- Same-authority downstream, Shadow-contamination, historical-snapshot, authorization, backup/restore, and rollback checks when affected.
- No threshold edits after viewing frozen-test results; a failure returns to development/validation and requires a new production-candidate cycle.

### Final

- Complete backend/frontend/package verification.
- Zero unowned preservation-ledger entries and zero raw-field dependency-boundary violations.
- Complete route/API/mutation/job/artifact/settings/model/history/permission matrix.
- Exact deployment artifact Golden run.
- DS918+ operational and restart run.

## Failure Investigation Protocol

For any failed gate:

1. Record the exact fingerprint, metric, numerator/denominator, strata, and affected aliases.
2. Locate the first divergent stage rather than patching the final report.
3. Classify the cause as label ambiguity, source/timebase, candidate coverage, identity, pose, event, key moment, rotation, review, fusion, downstream facts, feature compatibility, settings/models, data safety, packaging, or operations.
4. Verify labels without exposing frozen-test content to tuning when possible.
5. Create one bounded corrective experiment on development data.
6. Validate on validation data.
7. Freeze a new candidate fingerprint before running frozen test again.
8. Never add a filename, timestamp, person-specific geometry, or sample ID to production logic.

## Review Checkpoints

Request explicit review at these checkpoints:

- after Iteration 4: dataset and baseline are trustworthy;
- after Iteration 8: identity tracking is safe enough to authorize pose;
- after Iteration 13: all five core algorithm outputs have measurable V2 results;
- after Iteration 14: all semantic downstream features consume same-authority facts without functional loss;
- after Iteration 15: end-to-end shadow behavior is stable;
- after Iteration 17: controlled candidate deployment decision;
- after the rollout observation period: legacy retirement and final merge decision.

## Definition of Done

The V2 program is complete only when:

- a 24-30 event Golden dataset using `golden-gate-policy.v2` is labeled, grouped, reviewed, and explicitly frozen;
- source-time and leakage-safe evaluation are proven;
- tracking, pose, action, key-moment, and rotation gates pass;
- Path A/B consume bounded evidence and final reports are claim-traceable;
- shadow mode is restartable, diffable, fingerprinted, and cannot mutate legacy results;
- every current capability is present in the preservation ledger, has an owning iteration, and passes its read/write/job/artifact/permission/history/rollback contract or has explicit retirement approval;
- chat/corrections, plans/sessions, comparisons/growth, skills/memories, monthly/annual, shares/exports consume same-authority facts and never admit Shadow or incompatible evidence;
- Parent PIN/profile/theme, Provider/API/vote/metrics, MediaPipe single/multi-pose, YOLO+ByteTrack/dependencies, optional-model gates, system/storage, backup/restore, startup/scheduled work, annual recovery, and historical routes remain functional;
- frozen metrics include coverage, refusal, raw counts, confidence intervals, and strata;
- the exact deployment artifact passes DS918+ operational tests;
- clean install, copied-database upgrade/downgrade-read, Docker/all-in-one routing, standalone-pack generation, model mounts, restart, background jobs, and rollback pass;
- all repository tests/builds required by the final verification pass;
- no unresolved P0/P1 finding remains;
- rollback is demonstrated;
- the user approves the exact commit before it is merged into the main worktree.
