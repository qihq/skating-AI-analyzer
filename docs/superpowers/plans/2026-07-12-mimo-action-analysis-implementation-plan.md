# MiMo Layered Action Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace one-shot semantic guessing with high-recall action candidates, bounded MiMo 2.5 tasks, independent specialty review, and source-frame T/A/L and rotation evidence.

**Architecture:** Build a versioned action-analysis package alongside the existing `video_temporal.py`. Each stage consumes and produces strict JSON contracts and can stop with uncertainty. The current temporal path remains available behind feature flags until action gates pass.

**Tech Stack:** Python, Pydantic, OpenCV/NumPy, FFmpeg assets, existing provider abstraction, MiMo 2.5, pytest.

## Global Constraints

- Gate G2 must pass before new target crops are trusted as model input.
- MiMo calls are task-specific: scan, boundary, coarse type, specialty, keyframe, dispute, report.
- Every response cites timestamps within the supplied source interval and carries visibility, support, contradiction, uncertainty, model, prompt version, and asset IDs.
- Invalid JSON or timestamps never become default labels/keyframes.
- Report generation cannot add conclusions absent from fused structured evidence.
- Source design: sections 7-12 and Phase 4-7 of `docs/superpowers/specs/2026-07-11-high-accuracy-tracking-action-analysis-design.md`.

---

### Task 1: Versioned Action Contracts And Validator

**Files:**
- Create: `backend/app/services/action_analysis_contracts.py`
- Create: `backend/app/services/action_analysis_validation.py`
- Test: `backend/tests/test_action_analysis_contracts.py`

**Interfaces:**
- Produces Pydantic models: `ActionCandidateV1`, `ActionIntervalV1`, `EvidenceItemV1`, `VisibilityV1`, `MimoStageResultV1`, `SpecialtyResultV1`, `KeyframeEstimateV1`, `FusedActionResultV1`.
- Produces: `validate_stage_result(payload, request_context) -> ValidationResult`.

- [ ] **Step 1: Write strict validation tests**

Cover legal output, timestamp before/after clip, illegal label, out-of-order T/A/L, missing contradiction list, invalid confidence, and `unobservable` with no invented primary label.

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_action_analysis_contracts.py -q`

Expected: FAIL because contracts do not exist.

- [ ] **Step 3: Implement additive contracts**

Use `extra="forbid"` on MiMo response models; keep conversion helpers for the existing `video_temporal_v1` payload. Raw model confidence is named `confidence_raw`, never `final_confidence`.

- [ ] **Step 4: Verify**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_action_analysis_contracts.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/action_analysis_contracts.py backend/app/services/action_analysis_validation.py backend/tests/test_action_analysis_contracts.py
git commit -m "feat: define layered action analysis contracts"
```

### Task 2: Multi-Source Action Candidate Recall

**Files:**
- Create: `backend/app/services/action_candidates.py`
- Test: `backend/tests/test_action_candidates.py`
- Modify: `.env.example`

**Interfaces:**
- Produces: `merge_action_candidates(motion, pose, mimo_scan, duration, policy) -> list[ActionCandidateV1]`.
- Preserves every source and clusters overlapping windows without choosing a final class.

- [ ] **Step 1: Write merge/split tests**

Test overlapping motion/pose jump windows merge; distinct nearby jumps stay separate when evidence contains two cores; missing pose does not delete MiMo/motion candidate; candidates clamp to video bounds with a diagnostic.

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_action_candidates.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement pure clustering and padding policy**

Use action-family-specific pre/post context, deterministic IDs, and no report text. Add `ACTION_LAYERED_PIPELINE=0`.

- [ ] **Step 4: Verify**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_action_candidates.py backend/tests/test_analysis_keyframe_candidates.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/action_candidates.py backend/tests/test_action_candidates.py .env.example
git commit -m "feat: merge high-recall action candidates"
```

### Task 3: Prompt Registry And Common Evidence Rules

**Files:**
- Create: `backend/app/services/mimo_action_prompts.py`
- Test: `backend/tests/test_mimo_action_prompts.py`

**Interfaces:**
- Produces: `build_action_prompt(stage, context) -> PromptSpec`; stages `scan`, `boundary`, `coarse`, `jump`, `spin`, `step`, `spiral`, `keyframes`, `dispute`.
- `PromptSpec` contains version, system/user text, expected schema, and allowed labels.

- [ ] **Step 1: Write prompt responsibility tests**

Assert all prompts include target-only, visible-facts-first, contradiction, unobservable, time-bound, and strict-JSON clauses. Assert scan prompt excludes jump-name/score instructions; dispute context excludes the prior final label; report prose is absent.

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_mimo_action_prompts.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement registry**

Keep shared clauses DRY and stage responsibilities explicit. Embed fixed T/A/L definitions only in relevant prompts. Include mirror/rotation status for jump specialty.

- [ ] **Step 4: Verify**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_mimo_action_prompts.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/mimo_action_prompts.py backend/tests/test_mimo_action_prompts.py
git commit -m "feat: register bounded mimo action prompts"
```

### Task 4: MiMo Stage Runner, Validation, And Cache Key

**Files:**
- Create: `backend/app/services/mimo_action_runner.py`
- Modify: `backend/app/services/providers.py` only if a thin existing-provider call is needed
- Test: `backend/tests/test_mimo_action_runner.py`

**Interfaces:**
- Produces: `run_mimo_stage(request: MimoStageRequest) -> MimoStageResultV1`; `build_mimo_cache_key(request) -> str`.
- Consumes existing provider settings and video-content mechanism.

- [ ] **Step 1: Write mocked-provider tests**

Cover valid JSON, fenced JSON, malformed JSON, timeout, timestamp out of range, cache hit, and cache invalidation when track revision/prompt/model/schema/encoding changes.

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_mimo_action_runner.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement finite retry and validation**

Authentication failure stops immediately; timeout/rate limit retries finitely; malformed JSON gets limited repair/retry; out-of-range timestamps invalidate the response and are not clamped. Persist raw excerpt only under existing safe diagnostic limits.

- [ ] **Step 4: Verify**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_mimo_action_runner.py backend/tests/test_provider_retry.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/mimo_action_runner.py backend/app/services/providers.py backend/tests/test_mimo_action_runner.py
git commit -m "feat: run validated cached mimo action stages"
```

### Task 5: Scan And Boundary Pipeline

**Files:**
- Create: `backend/app/services/action_boundary_pipeline.py`
- Test: `backend/tests/test_action_boundary_pipeline.py`

**Interfaces:**
- Produces: `scan_and_resolve_boundaries(assets, local_signals, context) -> list[ActionIntervalV1]`.
- Consumes target crop and annotated overview plus tracking summary.

- [ ] **Step 1: Write mocked stage tests**

Cover no action, one action, two-jump combination, overlapping false positive, low tracking coverage, and boundary response outside candidate window. Assert combination children remain distinct and relate through `combination_id`.

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_action_boundary_pipeline.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement orchestration**

Run scan once per video, merge local sources, then boundary once per candidate. Stop/mark review when action-core identity conflict exists. Do not call specialty or report here.

- [ ] **Step 4: Verify**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_action_boundary_pipeline.py backend/tests/test_action_candidates.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/action_boundary_pipeline.py backend/tests/test_action_boundary_pipeline.py
git commit -m "feat: scan and split action boundaries"
```

### Task 6: Coarse Classification And Specialty Routing

**Files:**
- Create: `backend/app/services/action_classifier.py`
- Test: `backend/tests/test_action_classifier.py`

**Interfaces:**
- Produces: `classify_action(interval, assets, context) -> CoarseActionResult`; `specialty_stage_for(result) -> str | None`.
- Legal coarse labels match the design.

- [ ] **Step 1: Write routing and refusal tests**

Test jump/spin/step/spiral routing, close candidate probabilities -> uncertain, poor full-body visibility -> unobservable where required, and tracking conflict caps status.

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_action_classifier.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement classifier orchestration**

Store ranked alternatives, support, contradictions, visibility, and raw confidence. Do not use the user's uploaded action label as the final answer; it may be recorded only as non-model context excluded from evidence scoring.

- [ ] **Step 4: Verify**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_action_classifier.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/action_classifier.py backend/tests/test_action_classifier.py
git commit -m "feat: classify and route action specialties"
```

### Task 7: Jump Specialty And Mirror Safety

**Files:**
- Create: `backend/app/services/jump_specialty.py`
- Test: `backend/tests/test_jump_specialty.py`

**Interfaces:**
- Produces: `analyze_jump_specialty(interval, assets, context) -> JumpSpecialtyResult`.
- Labels include Axel/Lutz/Flip/Loop/Salchow/Toe Loop/Waltz/unknown family variants.

- [ ] **Step 1: Write evidence-cap tests**

Assert forward takeoff can support Axel; toe-assisted family does not imply a unique jump; poor skate visibility prevents confirmed Lutz/Flip; unknown mirror state prevents confirmed takeoff-foot claims; alternatives remain available.

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_jump_specialty.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement staged jump interpretation**

MiMo describes facts first. Apply deterministic evidence caps after validation. Do not encode jump result from filename/user action subtype.

- [ ] **Step 4: Verify**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_jump_specialty.py backend/tests/test_action_profiles.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/jump_specialty.py backend/tests/test_jump_specialty.py
git commit -m "feat: add evidence-bounded jump classification"
```

### Task 8: Spin, Step, And Spiral Specialty Services

**Files:**
- Create: `backend/app/services/spin_specialty.py`
- Create: `backend/app/services/step_specialty.py`
- Create: `backend/app/services/spiral_specialty.py`
- Test: `backend/tests/test_action_specialties.py`

**Interfaces:**
- Each service consumes interval/assets/context and returns `SpecialtyResultV1` with family-specific measurements and observability.

- [ ] **Step 1: Write separate specialty tests**

Spin: entry/main/exit, direction, drift, no official level. Step: interval and continuity, no guaranteed per-edge verdict. Spiral: hold interval, free-leg relative height, trunk stability, objective description when name is uncertain.

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_action_specialties.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement bounded services**

Reuse the stage runner and contracts. Do not force T/A/L fields onto non-jump actions.

- [ ] **Step 4: Verify**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_action_specialties.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/spin_specialty.py backend/app/services/step_specialty.py backend/app/services/spiral_specialty.py backend/tests/test_action_specialties.py
git commit -m "feat: add non-jump specialty analysis"
```

### Task 9: Source-Frame T/A/L Refinement

**Files:**
- Create: `backend/app/services/jump_keyframes.py`
- Modify: `backend/app/services/video.py` only through existing precise-frame helpers
- Test: `backend/tests/test_jump_keyframes.py`

**Interfaces:**
- Produces: `refine_jump_keyframes(interval, source_asset, pts_map, geometry, mimo_result) -> JumpKeyframesResult`.
- Uses fixed T/flight_start/A/L/landing_stable definitions.

- [ ] **Step 1: Write ordering and PTS tests**

Test CFR and synthetic VFR maps, camera vertical translation, missing ankle visibility, interpolated tracking at takeoff, out-of-order MiMo candidates, and second-candidate retention.

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_jump_keyframes.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement coarse-to-fine refinement**

Use source PTS neighborhood, camera-compensated COM/local ice baseline, contact candidates, and validated MiMo range. Conflicts trigger re-search or uncertain output; never sort incorrect timestamps to hide a failure.

- [ ] **Step 4: Verify existing refinement compatibility**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_jump_keyframes.py backend/tests/test_video_precise_extract.py backend/tests/test_keyframe_candidates.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/jump_keyframes.py backend/app/services/video.py backend/tests/test_jump_keyframes.py
git commit -m "feat: refine jump keyframes on source pts"
```

### Task 10: Rotation Count Evidence

**Files:**
- Create: `backend/app/services/jump_rotation.py`
- Test: `backend/tests/test_jump_rotation.py`

**Interfaces:**
- Produces: `estimate_air_rotation(pose_frames, keyframes, orientation_evidence, jump_candidates) -> RotationEstimate`.

- [ ] **Step 1: Write unwrap and conditioning tests**

Test 179-to--179 unwrap, single-frame spike rejection, shoulder/hip disagreement, post-landing rotation exclusion, Axel conditional labels, and unobservable underrotation.

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_jump_rotation.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement continuous estimate**

Return revolutions, uncertainty, alternatives, evidence quality, and conditional interpretation. Do not reduce directly to an integer or official `q/< /<<` call.

- [ ] **Step 4: Verify**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_jump_rotation.py backend/tests/test_biomechanics_rotation_unwrap.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/jump_rotation.py backend/tests/test_jump_rotation.py
git commit -m "feat: estimate continuous airborne rotation"
```

### Task 11: Independent Dispute Review And Evidence Fusion

**Files:**
- Create: `backend/app/services/action_evidence_fusion.py`
- Test: `backend/tests/test_action_evidence_fusion.py`

**Interfaces:**
- Produces: `needs_dispute_review(results, policy) -> bool`; `fuse_action_evidence(...) -> FusedActionResultV1`.

- [ ] **Step 1: Write conflict and cap tests**

Cover agreement, close alternatives, independent disagreement, sole evidence source, identity conflict, poor skate visibility, interpolated T/L, and no prior-label leakage into dispute request.

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_action_evidence_fusion.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement status-first fusion**

Produce `confirmed|likely|uncertain|conflicted|unobservable|not_applicable`. Keep raw source scores for later calibration. Do not call report generation.

- [ ] **Step 4: Verify**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_action_evidence_fusion.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/action_evidence_fusion.py backend/tests/test_action_evidence_fusion.py
git commit -m "feat: fuse independent action evidence"
```

### Task 12: Layered Pipeline Integration

**Files:**
- Create: `backend/app/services/layered_action_pipeline.py`
- Modify: `backend/app/routers/analysis.py` at the existing vision/video-temporal stage only
- Modify: `backend/app/services/pipeline_version.py`
- Test: `backend/tests/test_layered_action_pipeline.py`
- Test: `backend/tests/test_analysis_video_temporal_pipeline.py`

**Interfaces:**
- With `ACTION_LAYERED_PIPELINE=0`, current temporal path is unchanged.
- With flag on, consumes Gate G2 assets and produces `action_analysis_v1` alongside current output.

- [ ] **Step 1: Write flag and partial-failure tests**

Assert old path off; full staged flow on; specialty failure retains coarse result; keyframe failure retains action class; tracking-core conflict stops specialty; report is not called here.

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_layered_action_pipeline.py backend/tests/test_analysis_video_temporal_pipeline.py -q`

Expected: FAIL because the layered flag-on orchestration is not integrated.

- [ ] **Step 3: Implement thin orchestration**

Keep stage logic in `layered_action_pipeline.py`; router starts/awaits it and persists result. Do not delete or reinterpret current `video_temporal` fields.

- [ ] **Step 4: Verify**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_layered_action_pipeline.py backend/tests/test_analysis_video_temporal_pipeline.py backend/tests/test_video_temporal.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/layered_action_pipeline.py backend/app/routers/analysis.py backend/app/services/pipeline_version.py backend/tests/test_layered_action_pipeline.py backend/tests/test_analysis_video_temporal_pipeline.py
git commit -m "feat: integrate layered action analysis"
```

### Task 13: Gates G3 And G4 A/B

**Files:**
- Create: `docs/evaluation/action-candidate-ab.md`
- Create: `docs/evaluation/layered-action-ab.md`

**Interfaces:**
- Consumes frozen manifest, regenerated predictions, at least three repeated MiMo runs for key prompt versions.
- Produces candidate and final-action rollout decisions.

This is an evaluation gate, not a production-code task. Its red state is insufficient candidate recall, a failed final-action threshold, or missing repeated predictions; green requires all G3/G4 thresholds.

- [ ] **Step 1: Evaluate candidate recall before specialty rollout**

Report recall, false candidates/minute, boundary IoU, combination split recall, and all strata. Require approximately >=98% recall or obtain explicit approval for a measured alternative.

- [ ] **Step 2: Repeat layered runs**

Run at least three predictions per validation/test sample with fixed model/prompt/assets. Report mean, worst, and agreement.

- [ ] **Step 3: Evaluate final actions**

Report coarse macro F1, class confusion, jump Top-1/Top-2 on observable samples, T/A/L separately, rotation classes, uncertainty/coverage, and high-confidence error.

- [ ] **Step 4: Apply gates**

No candidate recall regression; macro F1 regression <=1 point; major class regression <=3 points; high-confidence error does not increase; unobservable false certainty decreases or stays flat; T/A/L median materiality threshold is 0.03-0.05 seconds.

- [ ] **Step 5: Commit sanitized reports**

```powershell
git add docs/evaluation/action-candidate-ab.md docs/evaluation/layered-action-ab.md
git commit -m "test: validate layered action analysis"
```
