# Bidirectional Identity Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Track the manually selected skater forward and backward through handheld multi-person video, detect identity conflicts, and produce stable target assets without silently switching people.

**Architecture:** Treat the current `PersonBBoxTracker` as a legacy single-direction engine behind an adapter. Add small modules for contracts, camera compensation, identity templates, three-state decisions, crossing protection, bidirectional fusion, quality, and crop generation. Integrate behind flags that default off until Gate G2 passes.

**Tech Stack:** Python, NumPy, OpenCV, Ultralytics YOLO/ByteTrack through the existing tracker, Pydantic/dataclasses, pytest.

## Global Constraints

- Gate G1 from the Golden/timebase plan must be satisfied before Task 3 changes any identity decision.
- Manual anchor is immutable; ByteTrack ID is not identity.
- Center position, largest-person, and raw IoU cannot independently relock identity.
- `uncertain` or `lost` must never fall back to another person.
- New modules must not expand `backend/app/services/person_tracker.py` with another large set of scenario rules.
- Every new behavior uses a default-off environment flag and emits diagnostics.
- Source design: section 6 and Phase 3 of `docs/superpowers/specs/2026-07-11-high-accuracy-tracking-action-analysis-design.md`.

---

### Task 1: Tracking Contracts And Legacy Adapter

**Files:**
- Create: `backend/app/services/tracking_contracts.py`
- Create: `backend/app/services/directional_tracker.py`
- Test: `backend/tests/test_directional_tracker.py`

**Interfaces:**
- Produces: `TrackingState = Literal["tracked", "uncertain", "lost"]`, `TrackFrame`, `DirectionalTrackResult`, and `run_directional_track(...)`.
- Consumes: current `track_person_bbox_detailed(...)` without changing its public return shape.

- [ ] **Step 1: Write failing adapter tests**

Mock the legacy detailed tracker result and assert it converts every diagnostic to a typed `TrackFrame`, preserves original timestamps/frame names, and does not convert legacy fallback bboxes into confirmed identity.

```python
assert result.frames[0].tracking_state == "tracked"
assert result.frames[1].tracking_state == "uncertain"
assert result.frames[1].bbox_source == "legacy_fallback"
```

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_directional_tracker.py -q`

Expected: FAIL because modules do not exist.

- [ ] **Step 3: Implement contracts and adapter**

Use focused frozen dataclasses. Store normalized bbox, timestamp, state, identity/second score, source, direction, candidate ID, camera reliability, occlusion, and flags. Adapter accepts `direction="forward"|"backward"`; backward reverses input frames before the legacy call and restores chronological output order.

- [ ] **Step 4: Verify focused and legacy tests**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_directional_tracker.py backend/tests/test_person_tracker.py -q`

Expected: PASS with no legacy behavior change.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/tracking_contracts.py backend/app/services/directional_tracker.py backend/tests/test_directional_tracker.py
git commit -m "refactor: add directional tracker adapter"
```

### Task 2: Immutable Identity Template Store

**Files:**
- Create: `backend/app/services/identity_templates.py`
- Test: `backend/tests/test_identity_templates.py`

**Interfaces:**
- Produces: `IdentityTemplateStore.from_manual_anchor(frame, bbox)`, `score_candidate(frame, bbox)`, `consider_update(...)`, `freeze_updates(reason)`, `unfreeze_updates()`.
- Template kinds: manual anchor, trusted, short term, optional face embedding metadata.

- [ ] **Step 1: Write contamination-protection tests**

Assert manual template never changes; crossing freezes updates; recovery frames below the configured stabilization count cannot enter trusted templates; a high-confidence separated candidate can update short-term then trusted state.

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_identity_templates.py -q`

Expected: FAIL on missing store.

- [ ] **Step 3: Implement lightweight appearance features**

Reuse/encapsulate existing HSV appearance logic first. Store feature vectors and quality, not raw face crops. Expose similarity components separately for diagnostics. Do not add OSNet in this task.

```python
UpdateDecision(accepted=False, reason="recovery_stabilization_window")
```

- [ ] **Step 4: Verify**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_identity_templates.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/identity_templates.py backend/tests/test_identity_templates.py
git commit -m "feat: protect manual identity templates"
```

### Task 3: Camera Motion Estimation

**Files:**
- Create: `backend/app/services/camera_motion.py`
- Test: `backend/tests/test_camera_motion.py`

**Interfaces:**
- Produces: `estimate_camera_transform(previous, current, exclusion_boxes) -> CameraTransform`; `project_bbox(bbox, transform) -> bbox`.
- `CameraTransform` includes matrix, reliability, inlier ratio, feature count, and failure reason.

- [ ] **Step 1: Write synthetic translation/zoom/failure tests**

Generate a feature-dot background and mask a person rectangle. Assert known translation projects within tolerance; blank/blur frames return unreliable rather than identity motion.

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_camera_motion.py -q`

Expected: FAIL on missing functions.

- [ ] **Step 3: Implement ORB or sparse-flow affine estimation**

Exclude person boxes, use RANSAC, expose thresholds as config, and return identity transform with `reliable=False` on failure. Do not silently use raw center distance as equivalent evidence.

- [ ] **Step 4: Verify**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_camera_motion.py -q`

Expected: PASS for translation and fail-closed cases.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/camera_motion.py backend/tests/test_camera_motion.py
git commit -m "feat: estimate handheld camera motion"
```

### Task 4: Multi-Evidence Identity Scoring And Three-State Decision

**Files:**
- Create: `backend/app/services/identity_scoring.py`
- Test: `backend/tests/test_identity_scoring.py`
- Modify: `.env.example`

**Interfaces:**
- Consumes: appearance components, optional face score, camera-compensated motion, pose-shape score, IoU, detector confidence.
- Produces: `score_identity_candidate(...) -> CandidateIdentityScore`; `decide_tracking_state(scores, policy) -> TrackingDecision`.

- [ ] **Step 1: Write failing state-policy tests**

Cover: high top score/large margin -> tracked; medium score -> uncertain; high score but near-tie -> uncertain; strong anchor conflict -> lost; absent face score re-normalizes weights; unreliable camera removes its weight.

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_identity_scoring.py -q`

Expected: FAIL because scoring service is absent.

- [ ] **Step 3: Implement configurable weighted evidence**

Start with design weights but expose them in one policy object. Return component contributions and rejection reasons. Add default-off `TRACKING_THREE_STATE_DECISION=0` to `.env.example`.

```python
TrackingDecision(state="uncertain", reason="candidate_margin_too_small", selected_candidate_id=None)
```

- [ ] **Step 4: Verify**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_identity_scoring.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/identity_scoring.py backend/tests/test_identity_scoring.py .env.example
git commit -m "feat: add fail-closed identity scoring"
```

### Task 5: Crossing Guard

**Files:**
- Create: `backend/app/services/crossing_guard.py`
- Test: `backend/tests/test_crossing_guard.py`

**Interfaces:**
- Produces: stateful `CrossingGuard.update(frame_candidates, previous_tracks) -> CrossingState` with `inactive|approaching|merged|separating|unresolved`.
- Signals template store freeze and forces decision margin policy during crossing.

- [ ] **Step 1: Write crossing sequence tests**

Use a synthetic two-person sequence: separate -> overlap -> one merged detection -> separate with swapped detector IDs. Assert detector ID does not decide identity, template updates freeze, and unresolved equal scores yield uncertain.

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_crossing_guard.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement finite-state guard**

Use bbox overlap, center convergence, detection count change, and candidate-margin trend. Keep thresholds in `CrossingPolicy`. Emit start/end timestamps and reasons.

- [ ] **Step 4: Verify**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_crossing_guard.py -q`

Expected: PASS, including swapped detector IDs.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/crossing_guard.py backend/tests/test_crossing_guard.py
git commit -m "feat: guard identity through skater crossings"
```

### Task 6: New Directional Tracking Coordinator

**Files:**
- Create: `backend/app/services/identity_track_coordinator.py`
- Modify: `backend/app/services/directional_tracker.py`
- Test: `backend/tests/test_identity_track_coordinator.py`
- Modify: `.env.example`

**Interfaces:**
- Produces: `run_identity_direction(frames, anchor, direction, policy) -> DirectionalTrackResult`.
- Coordinates detector candidates, camera transform, template store, scorer, crossing guard, and short interpolation.

- [ ] **Step 1: Write end-to-end synthetic tests**

Cover: camera pan with same person; temporary detection loss; long loss with far passerby; crossing with ambiguous separation; correct far re-entry with strong appearance. Assert no fallback selects another person.

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_identity_track_coordinator.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement coordinator behind flags**

Reuse existing YOLO candidate detection. Permit interpolation only for configured short gaps and mark `bbox_source=interpolated`, `tracking_state=uncertain`. Add flags `TRACKING_CAMERA_MOTION_COMPENSATION=0`, `TRACKING_TEMPLATE_GUARD=0`, `TRACKING_CROSSING_GUARD=0`.

- [ ] **Step 4: Verify all focused tracking tests**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_identity_track_coordinator.py backend/tests/test_person_tracker.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/identity_track_coordinator.py backend/app/services/directional_tracker.py backend/tests/test_identity_track_coordinator.py .env.example
git commit -m "feat: coordinate fail-closed identity tracking"
```

### Task 7: Bidirectional Fusion

**Files:**
- Create: `backend/app/services/bidirectional_track.py`
- Test: `backend/tests/test_bidirectional_track.py`
- Modify: `.env.example`

**Interfaces:**
- Produces: `fuse_directional_tracks(forward, backward, policy) -> FusedTrackResult`; result includes frames, conflict intervals, review requirement, and summary.

- [ ] **Step 1: Write fusion table tests**

Test every design table row: agree/agree; tracked/lost; lost/tracked; trusted conflict; both uncertain. A trusted conflict must not average boxes or choose the larger score.

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_bidirectional_track.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement timestamp-aligned fusion**

Join using proxy/source mapping tolerance. Create `identity_conflict` intervals and `requires_manual_anchor` when duration/core overlap exceeds policy. Add `TRACKING_BIDIRECTIONAL=0` and `TRACKING_REQUIRE_REVIEW_ON_CONFLICT=1`.

- [ ] **Step 4: Verify**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_bidirectional_track.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/bidirectional_track.py backend/tests/test_bidirectional_track.py .env.example
git commit -m "feat: fuse forward and backward identity tracks"
```

### Task 8: Tracking Quality And Golden Prediction Export

**Files:**
- Create: `backend/app/services/track_quality.py`
- Modify: `backend/app/routers/debug.py:481`
- Modify: `backend/scripts/eval_against_gt.py`
- Test: `backend/tests/test_track_quality.py`
- Test: `backend/tests/test_debug_runs.py`

**Interfaces:**
- Produces: `summarize_track(frames, action_intervals) -> TrackQualitySummary`; prediction JSON includes per-frame state and summary while retaining existing `target_bboxes`.

- [ ] **Step 1: Write summary tests**

Assert tracked/uncertain/lost/interpolated coverage, longest loss, conflicts, suspected switches, crossings, and core-action coverage are computed from timestamps, not raw frame count when intervals vary.

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_track_quality.py backend/tests/test_debug_runs.py -k "golden" -q`

Expected: FAIL on missing summary fields.

- [ ] **Step 3: Implement additive export**

Do not remove old bbox prediction shape. Add `identity_track_v1` and `track_quality_v1`; evaluator prefers new fields and falls back to old behavior.

- [ ] **Step 4: Verify**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_track_quality.py backend/tests/test_debug_runs.py backend/tests/test_eval_against_gt.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/track_quality.py backend/app/routers/debug.py backend/scripts/eval_against_gt.py backend/tests/test_track_quality.py backend/tests/test_debug_runs.py
git commit -m "feat: export identity tracking quality"
```

### Task 9: Stable Target Crop Assets

**Files:**
- Create: `backend/app/services/target_crop_assets.py`
- Test: `backend/tests/test_target_crop_assets.py`

**Interfaces:**
- Consumes: `FusedTrackResult`, source asset, PTS map.
- Produces: target crop video and annotated overview `VideoAsset`s sharing source timecode.

- [ ] **Step 1: Write crop-envelope tests**

Assert padding preserves arms/skates, center/size smoothing limits frame-to-frame jumps, source bounds clamp safely, and lost intervals never jump to another candidate bbox.

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_target_crop_assets.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement crop path and FFmpeg rendering**

Generate crop trajectory sidecar before video. For unresolved/lost regions, hold a widened last reliable view or use full-frame context and label the interval; never crop around an unconfirmed candidate.

- [ ] **Step 4: Verify**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_target_crop_assets.py backend/tests/test_video_assets.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/target_crop_assets.py backend/tests/test_target_crop_assets.py
git commit -m "feat: generate stable target video assets"
```

### Task 10: Thin Analysis-Pipeline Integration And Manual Review Gate

**Files:**
- Modify: `backend/app/routers/analysis.py:4339`
- Modify: `backend/app/schemas.py`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/pages/TargetSelectionPage.tsx`
- Test: `backend/tests/test_analysis_bbox_tracking.py`
- Test: `backend/tests/test_analysis_stage_retry.py`

**Interfaces:**
- With `TRACKING_BIDIRECTIONAL=0`, behavior is unchanged.
- With flag on, analysis runs both directions after anchor selection, persists track result/asset IDs, and pauses at `awaiting_tracking_review` on material conflict.

- [ ] **Step 1: Write flag-off, flag-on, and conflict tests**

Assert old call path when off; fused track when on; conflict does not run pose/MiMo and exposes a response that accepts an additional manual anchor.

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_analysis_bbox_tracking.py backend/tests/test_analysis_stage_retry.py -q`

Expected: FAIL because the flag-on fused-track/review-gate behavior is not integrated.

- [ ] **Step 3: Add narrow integration**

Keep orchestration logic in the new service, not the router. Store new data additively in existing JSON fields first; do not add database columns unless a measured query/recovery need requires them. UI lets user choose a conflict timestamp and submit another bbox.

- [ ] **Step 4: Verify backend and frontend**

Run:

```powershell
$env:PYTHONPATH='backend'
python -m pytest backend/tests/test_analysis_bbox_tracking.py backend/tests/test_analysis_stage_retry.py -q
npm --prefix frontend run build
```

Expected: both exit 0.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/routers/analysis.py backend/app/schemas.py frontend/src/api/client.ts frontend/src/pages/TargetSelectionPage.tsx backend/tests/test_analysis_bbox_tracking.py backend/tests/test_analysis_stage_retry.py
git commit -m "feat: integrate review-gated bidirectional tracking"
```

### Task 11: Gate G2 Golden A/B

**Files:**
- Create: `docs/evaluation/bidirectional-tracking-ab.md`
- Generated locally: `tmp/golden/tracking-off.json`, `tmp/golden/tracking-on.json`

**Interfaces:**
- Consumes: frozen Gate G1 manifest and identical manual anchors.
- Produces: rollout decision.

This is an evaluation gate, not a production-code task. Its red state is any failed G2 metric or missing regenerated prediction set; green requires all G2 thresholds.

- [ ] **Step 1: Regenerate predictions with flags off and on**

Do not merely rerun evaluator on identical `prediction.json`. Rerun the analysis/debug pipeline for each configuration, preserving separate predictions.

- [ ] **Step 2: Evaluate both predictions**

Run `eval_against_gt.py` for both manifests/prediction sets and compare with `backend/scripts/diff_baselines.py`.

- [ ] **Step 3: Manually inspect largest improvement and regression**

Review at least one multi-skater crossing, one lost/re-entry case, and any newly uncertain action-core interval.

- [ ] **Step 4: Apply Gate G2**

Required: confirmed identity switches = 0; false relock does not increase; multi-skater identity accuracy does not regress >1 point; core-action coverage does not regress >2 points; automatic coverage delta is reported.

- [ ] **Step 5: Commit the sanitized report**

```powershell
git add docs/evaluation/bidirectional-tracking-ab.md
git commit -m "test: validate bidirectional identity tracking"
```

Only after G2 passes may target crops feed the new MiMo path by default.
