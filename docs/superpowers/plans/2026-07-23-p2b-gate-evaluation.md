# P2-B G3/G4 Gate Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build reproducible, privacy-safe G3/G4 reports for jump, spin, step, and spiral before any P2-B event scan or timeline starts.

**Architecture:** Preserve legacy keyframe and identity evaluation. Add a pure-Python multi-event evaluator for the compatible local Golden manifest, then a separate CLI that emits sanitized JSON/Markdown reports and profile-by-profile decisions. Golden gains annotation inputs only; it cannot scan video or enable a timeline.

**Tech Stack:** Python 3, FastAPI/Pydantic, React/TypeScript, unittest/pytest, JSON, SHA-256.

## Global Constraints

- Implement P2-B B0 evidence tooling only: no technical-event persistence, full-video scanning, event APIs, timeline UI, or profile flags.
- Profiles are exactly `jump`, `spin`, `step`, and `spiral`; every profile decides independently.
- Local manifests and predictions are sensitive; reports exclude raw video/prediction paths, filenames, skater IDs, and absolute paths.
- `unobservable` labels never enter accuracy denominators or parent-facing claims.
- Do not reinterpret a legacy action window as full coverage or introduce uniform per-second VLM inference.
- Default thresholds: recall >= 0.98; Macro F1 >= 0.90; jump T/A/L median <= 0.10s; jump T/A/L P95 <= 0.25s; high-confidence error < 0.02 at confidence >= 0.80.
- Use source-video seconds, finite numeric validation, deterministic matching/order, and nearest-rank P95.

## File Map

- Create `backend/app/services/technical_event_evaluation.py`: contracts, temporal matching, G3/G4 metrics, and profile decisions; no DB, filesystem, or provider dependency.
- Modify `backend/scripts/eval_against_gt.py`: add `event_evaluation` only for manifests containing `action_intervals`; retain legacy output.
- Create `backend/scripts/generate_technical_event_gate_report.py`: canonical hashes and sanitized report CLI.
- Modify `backend/app/schemas.py` and `backend/app/routers/debug.py`: additive Golden interval persistence.
- Modify `frontend/src/api/client.ts` and `frontend/src/pages/DebugPage.tsx`: narrow Golden interval annotation controls.
- Create `backend/tests/test_technical_event_evaluation.py`, `backend/tests/test_technical_event_gate_report.py`, and `frontend/src/pages/DebugPage.golden-events.test.tsx`.
- Modify `backend/tests/test_eval_against_gt.py`, `backend/tests/test_debug_runs.py`, `docs/golden-eval-ab-runbook.md`, and `docs/evaluation/technical-event-gate.md`.

## Shared Interfaces

```python
PROFILE_TYPES = ("jump", "spin", "step", "spiral")

@dataclass(frozen=True)
class GateThresholds:
    candidate_recall_min: float = 0.98
    coarse_macro_f1_min: float = 0.90
    jump_tal_median_error_max_sec: float = 0.10
    jump_tal_p95_error_max_sec: float = 0.25
    high_confidence_error_rate_max: float = 0.02
    high_confidence_threshold: float = 0.80
    minimum_match_iou: float = 0.20

def evaluate_technical_events(samples, thresholds) -> dict: ...
def build_gate_report(event_evaluation, manifest, thresholds, pipeline) -> dict: ...
```

Gold labels use `action_intervals`: `action_id`, `action_type`, `start_sec`, `end_sec`, `status`, optional `keyframes`. Predictions use `action_candidates`: `action_type`, search/core start/end seconds, `confidence`, `status`, optional `keyframes`.

### Task 1: Event Contracts and Deterministic Matching

**Files:**
- Create: `backend/app/services/technical_event_evaluation.py`
- Test: `backend/tests/test_technical_event_evaluation.py`

**Interfaces:** `validate_action_intervals`, `validate_action_candidates`, `temporal_iou`, `nearest_rank_percentile`, and `match_action_events`; malformed data raises `ValueError` with anonymous sample ID and field.

- [ ] **Step 1: Write failing tests**

```python
def test_rejects_invalid_event_contracts() -> None:
    with self.assertRaisesRegex(ValueError, "anon-1.*action_id"):
        validate_action_intervals("anon-1", [{"action_id": "same", "action_type": "jump", "start_sec": 2, "end_sec": 1, "status": "observable"}])

def test_nearest_rank_and_adjacent_matching() -> None:
    self.assertEqual(nearest_rank_percentile([.01, .02, .03, .90], .95), .90)
    self.assertEqual(len(match_action_events(labels, candidates, .2)), 2)
```

Cover nonfinite seconds, legal profile/status, duplicate IDs, ordered search/core intervals, confidence `[0,1]`, jump T/A/L bounds, candidate competition, core-midpoint fallback, and stable tie ordering.

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_technical_event_evaluation.py -q`

Expected: FAIL with module/functions missing.

- [ ] **Step 3: Implement minimal pure functions**

```python
def nearest_rank_percentile(values, percentile):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]

def _is_match(label, candidate, minimum_iou):
    iou = temporal_iou(label["start_sec"], label["end_sec"], candidate["search_start_sec"], candidate["search_end_sec"])
    midpoint = (label["start_sec"] + label["end_sec"]) / 2
    return iou >= minimum_iou or (iou > 0 and candidate["core_start_sec"] <= midpoint <= candidate["core_end_sec"])
```

Generate all eligible pairs, sort by descending IoU, start distance, label order, then candidate order; greedily use each exactly once. Retain wrong-type temporal matches for G4.

- [ ] **Step 4: Verify green**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_technical_event_evaluation.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add backend/app/services/technical_event_evaluation.py backend/tests/test_technical_event_evaluation.py; git commit -m "feat: validate and match technical event goldens"`

### Task 2: G3/G4 Metrics and Profile Decisions

**Files:**
- Modify: `backend/app/services/technical_event_evaluation.py`
- Modify: `backend/tests/test_technical_event_evaluation.py`

**Interfaces:** `evaluate_technical_events(samples, thresholds)` produces `profiles[profile].g3`, `.g4`, and `.decision`; every rate carries its denominator and every profile has a decision.

- [ ] **Step 1: Write failing metric tests**

```python
def test_g3_counts_wrong_type_miss_and_unobservable_separately() -> None:
    result = evaluate_technical_events([sample_with(labels, candidates)], GateThresholds())
    self.assertEqual(result["profiles"]["jump"]["g3"]["false_negatives"], 1)
    self.assertEqual(result["profiles"]["spin"]["g3"]["unobservable_label_count"], 1)

def test_g4_reports_confusion_timing_and_missing_profile_block() -> None:
    result = evaluate_technical_events(samples_for_timing_and_confusion(), GateThresholds())
    self.assertEqual(result["g4"]["confusion_matrix"]["jump"]["spin"], 1)
    self.assertEqual(result["profiles"]["jump"]["g4"]["tal_error_sec"]["T"]["p95"], .30)
    self.assertEqual(result["profiles"]["spiral"]["decision"]["status"], "blocked")
```

Cover recall/precision/F1, duration coverage, false positives per labelled minute, automatic coverage, uncertainty, Macro F1 only over observed classes, missing T/A/L, threshold-bound confidence, unmatched high-confidence candidates, non-jump timing exemption, synthetic accepted profile, and approved lower-recall override text.

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_technical_event_evaluation.py -q`

Expected: FAIL because metrics/decisions are absent.

- [ ] **Step 3: Implement fail-closed metrics and gates**

```python
def _f1(tp, fp, fn):
    denominator = 2 * tp + fp + fn
    return None if denominator == 0 else (2 * tp) / denominator

def decide_profile(profile, metrics, thresholds):
    reasons = []
    if metrics["g3"]["observable_label_count"] == 0:
        reasons.append("insufficient_observable_labels")
    if metrics["g3"]["recall"] is None or metrics["g3"]["recall"] < thresholds.candidate_recall_min:
        reasons.append("candidate_recall_below_threshold")
    return {"status": "accepted" if not reasons else "blocked", "reasons": reasons}
```

G3 success requires same-type match; G4 coarse classification uses all temporal matches. T/A/L uses matched jumps with available paired values and records missing timing coverage. Never turn absent metrics into zero or success.

- [ ] **Step 4: Verify green**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_technical_event_evaluation.py backend/tests/test_eval_against_gt.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add backend/app/services/technical_event_evaluation.py backend/tests/test_technical_event_evaluation.py; git commit -m "feat: calculate G3 G4 profile gates"`

### Task 3: Legacy Evaluation Integration and Gate Report CLI

**Files:**
- Modify: `backend/scripts/eval_against_gt.py`
- Create: `backend/scripts/generate_technical_event_gate_report.py`
- Modify: `backend/tests/test_eval_against_gt.py`
- Create: `backend/tests/test_technical_event_gate_report.py`

**Interfaces:** Legacy `evaluate_manifest()` keeps current keys and adds `event_evaluation` only for multi-event manifests. CLI takes manifest, pipeline metadata, thresholds, JSON output, and Markdown output.

- [ ] **Step 1: Write failing integration/report tests**

```python
def test_legacy_manifest_has_no_event_section() -> None:
    self.assertNotIn("event_evaluation", evaluate_manifest(legacy_manifest_path, iou_threshold=.3, switch_frames=2))

def test_report_hash_is_canonical_and_path_safe() -> None:
    self.assertEqual(canonical_sha256({"b": 2, "a": 1}), canonical_sha256({"a": 1, "b": 2}))
    text = json.dumps(sanitize_gate_report(report_from_path_fixture()), ensure_ascii=False)
    self.assertNotIn("secret", text)
    self.assertIn("anon-1", text)
```

Cover relative prediction loading, malformed prediction failure, Markdown/JSON decision equality, profile-block reasons, metadata path rejection, deterministic fixed-time output, and atomic writes.

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_eval_against_gt.py backend/tests/test_technical_event_gate_report.py -q`

Expected: FAIL for absent event section/report module.

- [ ] **Step 3: Implement integration and sanitised report**

```python
def canonical_sha256(value):
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

if event_samples:
    report["event_evaluation"] = evaluate_technical_events(event_samples, thresholds)
```

Keep old keyframe aliases, tags, and summary calculations untouched. Reject raw path-like pipeline metadata. Include evaluator version, UTC time, hashes, thresholds, aggregates, profile decisions/reasons, anonymous IDs only; use temporary sibling files then `Path.replace()`.

- [ ] **Step 4: Verify green**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_eval_against_gt.py backend/tests/test_technical_event_evaluation.py backend/tests/test_technical_event_gate_report.py -q`

Expected: PASS.

Run: `$env:PYTHONPATH='backend'; python backend/scripts/generate_technical_event_gate_report.py --help`

Expected: exit code `0` and input/output options.

- [ ] **Step 5: Commit**

Run: `git add backend/scripts/eval_against_gt.py backend/scripts/generate_technical_event_gate_report.py backend/tests/test_eval_against_gt.py backend/tests/test_technical_event_gate_report.py; git commit -m "feat: generate P2-B G3 G4 gate reports"`

### Task 4: Persist Multi-Event Golden Labels

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/routers/debug.py`
- Modify: `backend/tests/test_debug_runs.py`

**Interfaces:** Add `GoldenActionInterval` and `DebugGoldenLabelRequest.action_intervals`. Legacy labels without intervals remain valid and serialize unchanged.

- [ ] **Step 1: Write failing persistence tests**

```python
async def test_golden_label_round_trips_multiple_event_intervals(self) -> None:
    response = await debug_router.save_debug_golden_label(run_id, DebugGoldenLabelRequest(action_intervals=[jump_interval, unobservable_spin]), session=session)
    self.assertEqual(len(response.action_intervals), 2)
    self.assertEqual(read_manifest()["samples"][0]["action_intervals"][0]["action_id"], "jump-1")
```

Cover duplicate IDs, illegal type/status, bad bounds, out-of-range jump T/A/L, and empty legacy labels.

- [ ] **Step 2: Verify red**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_debug_runs.py -q`

Expected: FAIL because the request model does not persist intervals.

- [ ] **Step 3: Implement additive Pydantic/router support**

```python
class GoldenActionInterval(BaseModel):
    action_id: str = Field(min_length=1, max_length=120)
    action_type: Literal["jump", "spin", "step", "spiral"]
    start_sec: float = Field(ge=0)
    end_sec: float = Field(gt=0)
    status: Literal["observable", "unobservable"]
    keyframes: dict[str, float] = Field(default_factory=dict)
```

Add validators for end-after-start, unique request IDs, and observable jump T/A/L. Normalize fields in `_debug_label_payload_from_request()` and add only `action_intervals` to `_write_debug_golden_manifest_entry()` while retaining old schema/fields.

- [ ] **Step 4: Verify green**

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_debug_runs.py backend/tests/test_technical_event_evaluation.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add backend/app/schemas.py backend/app/routers/debug.py backend/tests/test_debug_runs.py; git commit -m "feat: save multi-event golden labels"`

### Task 5: Golden Annotation UI and Operator Handoff

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/pages/DebugPage.tsx`
- Create: `frontend/src/pages/DebugPage.golden-events.test.tsx`
- Modify: `docs/golden-eval-ab-runbook.md`
- Modify: `docs/evaluation/technical-event-gate.md`

**Interfaces:** Golden drafts add/edit/delete action type, status, start/end seconds, and observable jump T/A/L; no new endpoints, playback scanner, or parent-facing feature.

- [ ] **Step 1: Write failing UI test**

```tsx
it("saves an event list and hides jump timing for spin", async () => {
  renderGoldenLabel({ action_intervals: [] });
  await userEvent.click(screen.getByRole("button", { name: "添加技术事件" }));
  await userEvent.selectOptions(screen.getByLabelText("动作类型"), "spin");
  expect(screen.queryByLabelText("起跳 T")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "保存 Golden 标注" }));
  expect(saveGoldenLabel).toHaveBeenCalledWith(expect.objectContaining({ action_intervals: expect.any(Array) }));
})
```

Also cover existing intervals, unobservable state, invalid start/end feedback, deletion, and empty legacy list.

- [ ] **Step 2: Verify red**

Run: `npm --prefix frontend test -- DebugPage.golden-events.test.tsx`

Expected: FAIL because client contract and controls are absent.

- [ ] **Step 3: Implement narrow UI and docs**

```tsx
const addInterval = () => setDraft((current) => ({
  ...current,
  action_intervals: [...(current.action_intervals ?? []), { action_id: `event-${crypto.randomUUID()}`, action_type: "jump", start_sec: 0, end_sec: 0.1, status: "observable", keyframes: {} }],
}));
```

Use source-second number inputs. Say labels measure candidate coverage and do not create a timeline. Document exact evaluator/report commands, frozen real-data workflow, profile review, and no sensitive manifest commit. Retain `technical-event-gate.md` as `blocked`; add no fabricated metrics.

- [ ] **Step 4: Verify all focused checks**

Run: `npm --prefix frontend test -- DebugPage.golden-events.test.tsx`

Expected: PASS.

Run: `$env:PYTHONPATH='backend'; python -m pytest backend/tests/test_eval_against_gt.py backend/tests/test_technical_event_evaluation.py backend/tests/test_technical_event_gate_report.py backend/tests/test_debug_runs.py -q`

Expected: PASS.

Run: `npm --prefix frontend run build`

Expected: exit code `0`.

Run: `git diff --check`

Expected: no output.

- [ ] **Step 5: Commit**

Run: `git add frontend/src/api/client.ts frontend/src/pages/DebugPage.tsx frontend/src/pages/DebugPage.golden-events.test.tsx docs/golden-eval-ab-runbook.md docs/evaluation/technical-event-gate.md; git commit -m "docs: document P2-B gate evaluation workflow"`

## Definition Of Done

- Legacy Golden evaluation remains compatible.
- Multi-event labels and predictions validate and yield deterministic G3/G4 metrics with denominators.
- Each profile has an accepted/blocked decision; missing/unobservable-only support blocks.
- Reports have canonical hashes, configuration/pipeline provenance, aggregates, anonymous IDs, and no sensitive paths/names.
- Golden UI can produce real labels but does not expose P2-B scan/timeline work.
- Only a frozen, human-labelled real report can unblock P2-B B1-B7.
