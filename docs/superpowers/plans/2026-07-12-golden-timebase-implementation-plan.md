# Golden Dataset And Video Timebase Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validate the existing Golden workflow, extend it with observability and dataset splits, freeze a 20-30 video baseline, and create source-PTS-safe video assets before algorithm changes.

**Architecture:** Extend existing Golden JSON compatibly rather than replacing it. Add pure timebase and asset-contract services beside `video.py`, then integrate through narrow calls. This plan creates measurement and infrastructure only; it does not change identity selection or action conclusions.

**Tech Stack:** Pydantic 2, FastAPI, JSON files, Python dataclasses/TypedDict, FFmpeg/ffprobe, OpenCV, React/TypeScript, pytest.

## Global Constraints

- Existing `golden_label.json`, `prediction.json`, and `golden_manifest.json` remain readable.
- Raw Golden videos and personal paths are not committed.
- Original PTS is authoritative; proxy frame index is never the final timestamp source.
- No tracker thresholds, MiMo prompts, or report logic change in this plan.
- Source design: sections 4, 5, 13, 14, and Phase 0-2 of `docs/superpowers/specs/2026-07-11-high-accuracy-tracking-action-analysis-design.md`.

---

### Task 1: Versioned Golden Label Contract

**Files:**
- Modify: `backend/app/schemas.py:645`
- Modify: `backend/app/routers/debug.py:519`
- Test: `backend/tests/test_debug_runs.py:1266`

**Interfaces:**
- Consumes: current `DebugGoldenLabelRequest`, `GoldenTrackingAnchor`, and `_build_debug_golden_label` behavior.
- Produces: optional `dataset_split`, `capture_tags`, `difficulty`, `observability`, `action_intervals`, `annotation_review`; old payloads receive safe defaults.

- [ ] **Step 1: Write failing compatibility and round-trip tests**

Add tests that submit the current minimal payload and an extended payload. Assert the old payload still saves; assert the extended fields round-trip exactly and manifest entries include `dataset_split` without embedding source video bytes.

```python
extended = DebugGoldenLabelRequest(
    skater_id="skater-a",
    action_type="jump",
    analysis_profile="jump",
    dataset_split="train",
    capture_tags=["wechat_compressed", "fast_pan", "multi_skater"],
    difficulty="hard",
    observability={"full_body": "good", "skates": "poor", "rotation_count": "reviewable"},
    action_intervals=[{"action_id": "jump-1", "core_start_sec": 2.1, "core_end_sec": 2.9}],
)
```

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_debug_runs.py -k "golden_label" -q`

Expected: FAIL because the new request fields do not exist or do not round-trip.

- [ ] **Step 3: Add typed optional fields and normalization**

Use bounded enums/literals where stable and dictionaries where the design intentionally evolves. Normalize tags by trimming, deduplicating, and sorting. Preserve unknown old fields already stored in an existing label instead of dropping them during a revision save.

```python
dataset_split: Literal["train", "validation", "test", "unassigned"] = "unassigned"
capture_tags: list[str] = Field(default_factory=list, max_length=32)
difficulty: Literal["easy", "medium", "hard", "unspecified"] = "unspecified"
observability: dict[str, str] = Field(default_factory=dict)
action_intervals: list[dict[str, Any]] = Field(default_factory=list)
annotation_review: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: Run focused tests**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_debug_runs.py -k "golden_label" -q`

Expected: PASS, including old-payload compatibility.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/schemas.py backend/app/routers/debug.py backend/tests/test_debug_runs.py
git commit -m "feat: version golden label metadata"
```

### Task 2: Golden Evaluator Coverage And Action Metrics

**Files:**
- Modify: `backend/scripts/eval_against_gt.py`
- Modify: `backend/tests/test_eval_against_gt.py`

**Interfaces:**
- Consumes: manifest samples with old or extended labels/predictions.
- Produces: `summary`, `stratum_summary`, `split_summary`, identity coverage, action detection/classification, per-keyframe error, uncertainty coverage, and failure tags.

- [ ] **Step 1: Add a failing synthetic-manifest test**

Create two in-test samples: one correctly tracked/confirmed action and one deliberately uncertain multi-skater action. Assert accuracy is not reported without coverage and T/A/L remain separate.

```python
self.assertEqual(report["summary"]["tracked_coverage"], 0.75)
self.assertIn("takeoff_median_error_sec", report["summary"])
self.assertIn("landing_median_error_sec", report["summary"])
self.assertEqual(report["split_summary"]["test"]["sample_count"], 1)
```

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_eval_against_gt.py -q`

Expected: FAIL on missing new summary keys.

- [ ] **Step 3: Implement additive metrics**

Add pure aggregation helpers. Treat missing extended fields as “not measured,” never as correct. Keep existing keys so current scripts continue working.

```python
def _safe_rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None
```

Report accuracy, automatic coverage, uncertain coverage, lost coverage, false relock count, action recall/precision when labels exist, and separate T/A/L distributions.

- [ ] **Step 4: Verify green and CLI compatibility**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_eval_against_gt.py -q`

Expected: PASS.

Run: `python backend/scripts/eval_against_gt.py --help`

Expected: exit 0 and existing CLI arguments remain.

- [ ] **Step 5: Commit**

```powershell
git add backend/scripts/eval_against_gt.py backend/tests/test_eval_against_gt.py
git commit -m "feat: expand golden evaluation metrics"
```

### Task 3: Golden Smoke Run And Annotation Guide

**Files:**
- Create: `docs/golden-high-accuracy-labeling-guide.md`
- Create locally, do not commit: `data/uploads/_debug/golden_manifest.json`
- Create locally, do not commit: `tmp/golden/smoke.json`

**Interfaces:**
- Consumes: the existing `/golden` UI and Tasks 1-2.
- Produces: 3-5 valid labeled samples proving the workflow and a written annotation policy.

This is a measurement gate, not a production-code task. Its red condition is a missing/invalid manifest or evaluator failure; its green condition is a valid 3-5 sample report.

- [ ] **Step 1: Write the annotation guide before labeling**

Define exact T/A/L meanings, target bbox density, `unobservable`, dataset split, capture tags, and review rules. State that ambiguous identity and blade edges must not be guessed.

- [ ] **Step 2: Label 3-5 videos through `/golden`**

Required set: one clear single-skater jump; one multi-skater video; one crossing/occlusion or out-of-frame video; one spin or severe camera shake; optional zoom/small-target sample.

- [ ] **Step 3: Run smoke evaluation**

Run:

```powershell
python backend/scripts/eval_against_gt.py data/uploads/_debug/golden_manifest.json --output tmp/golden/smoke.json --iou-threshold 0.3 --switch-frames 3
```

Expected: exit 0; `sample_count` is 3-5; every sample resolves label and prediction paths; missing-label count is zero.

- [ ] **Step 4: Inspect one sample end-to-end**

Confirm source timestamp, bbox coordinates, label revision, prediction, action type, and keyframes refer to the same video. Record any UI/schema defect as a new focused task before expanding the set.

- [ ] **Step 5: Commit only the guide**

```powershell
git add docs/golden-high-accuracy-labeling-guide.md
git commit -m "docs: define high-accuracy golden labeling"
```

### Task 4: Source PTS Probe Contract

**Files:**
- Create: `backend/app/services/video_timebase.py`
- Modify: `backend/app/services/video.py:389`
- Test: `backend/tests/test_video_timebase.py`

**Interfaces:**
- Produces: `probe_video_timebase(video_path: Path) -> VideoTimebase`; `VideoTimebase` contains duration, dimensions, average/rational rates, time base, VFR indication, rotation, and mirror status.
- Consumes later: proxy generation and precise source-frame lookup.

- [ ] **Step 1: Write fixture-free parser tests**

Mock ffprobe JSON for CFR, VFR, and rotation metadata. Assert rational parsing is safe for `0/0` and missing values.

```python
result = parse_video_timebase(ffprobe_payload)
assert result.rotation_degrees == 90
assert result.variable_frame_rate is True
assert result.average_fps == 29.97
```

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_video_timebase.py -q`

Expected: FAIL because module/functions do not exist.

- [ ] **Step 3: Implement immutable contract and parser**

Use a frozen dataclass; keep subprocess invocation in one function and parsing pure. Existing `_probe_video` remains compatible and may delegate after tests pass.

```python
@dataclass(frozen=True)
class VideoTimebase:
    duration_sec: float
    width: int
    height: int
    average_fps: float
    nominal_fps: float
    time_base: str
    variable_frame_rate: bool
    rotation_degrees: int
    mirrored: bool = False
```

- [ ] **Step 4: Verify tests**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_video_timebase.py backend/tests/test_video_precheck.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/video_timebase.py backend/app/services/video.py backend/tests/test_video_timebase.py
git commit -m "feat: add source video timebase contract"
```

### Task 5: Tracking Proxy And PTS Map

**Files:**
- Create: `backend/app/services/video_assets.py`
- Modify: `backend/app/services/video.py:1019`
- Test: `backend/tests/test_video_assets.py`

**Interfaces:**
- Consumes: `VideoTimebase`.
- Produces: `create_tracking_proxy(source: Path, output_dir: Path, fps: float = 15.0) -> VideoAsset`; sidecar `<asset>.timeline.json` with `ProxyFrameMap` records.

- [ ] **Step 1: Write failing command-builder and mapping tests**

Assert rotation is applied exactly once, output is CFR, no AI interpolation filter appears, and every proxy frame maps to a source timestamp.

```python
assert "minterpolate" not in " ".join(command)
assert asset.kind == "tracking_proxy"
assert maps[0].proxy_frame_index == 0
assert maps[-1].source_timestamp_sec <= source.duration_sec
```

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_video_assets.py -q`

Expected: FAIL because asset service is absent.

- [ ] **Step 3: Implement asset and map creation**

Keep FFmpeg command construction pure. Use ffprobe frame timestamps to map nearest source PTS. Include source SHA-256, encoding profile, dependencies, and mapping error in sidecar JSON.

- [ ] **Step 4: Verify focused and existing precise-frame tests**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_video_assets.py backend/tests/test_video_precise_extract.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/video_assets.py backend/app/services/video.py backend/tests/test_video_assets.py
git commit -m "feat: generate tracking proxy with pts map"
```

### Task 6: Clear Anchor Candidate Frames

**Files:**
- Create: `backend/app/services/target_anchor_candidates.py`
- Modify: `backend/app/routers/analysis.py` only at the target-selection response builder
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_target_anchor_candidates.py`

**Interfaces:**
- Produces: `rank_anchor_candidates(frames, detections, quality) -> list[AnchorCandidate]`, maximum 8.
- Does not select identity; user selection remains mandatory for the new path.

- [ ] **Step 1: Write ranking tests**

Provide synthetic candidates where the first frame is blurred, a middle frame is clear/separated, and a later frame has overlapping people. Assert the clear middle frame ranks first and output remains deterministic.

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_target_anchor_candidates.py -q`

Expected: FAIL on missing module.

- [ ] **Step 3: Implement pure scoring and additive response field**

Score person area/confidence, blur, overlap, edge truncation, and camera-motion risk. Return component scores for audit. Do not alter current auto-lock or manual bbox semantics.

- [ ] **Step 4: Verify**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_target_anchor_candidates.py backend/tests/test_analysis_bbox_tracking.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/target_anchor_candidates.py backend/app/routers/analysis.py backend/app/schemas.py backend/tests/test_target_anchor_candidates.py
git commit -m "feat: rank manual anchor candidate frames"
```

### Task 7: Freeze The First Real Baseline

**Files:**
- Create: `docs/evaluation/high-accuracy-baseline.md`
- Create: `docs/evaluation/high-accuracy-baseline.json`
- Modify if needed: `.gitignore` only to exclude raw/private Golden artifacts, never sanitized reports.

**Interfaces:**
- Consumes: Tasks 1-6 and 20-30 manually labeled videos.
- Produces: Gate G1 evidence used by every later plan.

This is a measurement gate, not a production-code task. Before labeling, the expected red state is fewer than 20 representative samples or missing split/stratum output; green requires every criterion below.

- [ ] **Step 1: Expand the manifest to 20-30 representative videos**

Include at least five multi-skater, four crossing/occlusion, four fast-pan/shake, three zoom/small-target, plus jump/spin/step/spiral coverage. Assign splits by source sequence, not derived clip.

- [ ] **Step 2: Run and retain current baseline**

```powershell
python backend/scripts/eval_against_gt.py data/uploads/_debug/golden_manifest.json --output tmp/golden/baseline-v5.2.318.json --iou-threshold 0.3 --switch-frames 3
```

Expected: exit 0; 20-30 samples; split and stratum summaries present.

- [ ] **Step 3: Sanitize and document**

Copy only aggregate metrics, opaque sample IDs, failure tags, pipeline/config versions, and strata into committed artifacts. Remove absolute paths, names, raw frames, face data, and video hashes that could identify user files.

- [ ] **Step 4: Verify Gate G1**

Run: `rg -n "C:\\|Users\\|source.mp4|face_embedding" docs/evaluation/high-accuracy-baseline.*`

Expected: no sensitive path/data matches. Confirm the markdown states that metrics are measured baseline values, not targets.

- [ ] **Step 5: Commit**

```powershell
git add docs/evaluation/high-accuracy-baseline.md docs/evaluation/high-accuracy-baseline.json .gitignore
git commit -m "test: freeze high-accuracy golden baseline"
```

Gate G1 is now satisfied. Only now may the bidirectional tracking plan modify identity behavior.
