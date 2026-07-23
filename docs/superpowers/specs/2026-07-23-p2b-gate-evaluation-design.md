# P2-B G3/G4 Gate Evaluation Design

## Purpose

Build a reproducible, privacy-safe evaluation workflow that decides whether an
action profile may enter the P2-B technical-event timeline. This work measures
the existing pipeline; it does not scan full videos, create technical events,
or enable a parent-facing timeline.

## Scope and Non-Goals

The initial profiles are `jump`, `spin`, `step`, and `spiral`. Each profile is
accepted or blocked independently. A global passing average cannot enable an
unmeasured or failing profile.

This workflow must not call a VLM per second, turn one existing
`analysis.action_window_start/end` value into full-video coverage, make
judge-grade edge calls, infer fear/fatigue/injury, or create automatic level
certification. Parent-facing wording remains `关键时刻` or `技术事件`, never
`逐秒点评`.

## Chosen Approach

Three options were considered:

1. Extend the old keyframe evaluator only. This has the lowest code cost but
   cannot represent several actions in one source video or evaluate candidate
   recall, so it would make the G3/G4 result misleading.
2. Replace the Golden manifest. This gives a clean schema but would discard
   historical single-action fixtures and force label migration before any
   measurement can run.
3. Keep the old manifest compatible and add a dedicated multi-event evaluator.
   This is the selected approach. Historical keyframe evaluation remains
   usable, while new P2-B fixtures can measure the actual full-video contract.

## Data Contract

The existing top-level manifest remains a JSON object with `samples`. A sample
may use its historical `keyframes` fields, its new `action_intervals` fields,
or both. All durations and timestamps are source-video seconds.

```json
{
  "id": "anon-001",
  "stratum": "single_skater",
  "prediction_path": "predictions/anon-001.json",
  "action_intervals": [
    {
      "action_id": "evt-1",
      "action_type": "jump",
      "start_sec": 3.1,
      "end_sec": 5.0,
      "status": "observable",
      "keyframes": {"T": 3.7, "A": 4.0, "L": 4.4}
    }
  ]
}
```

`action_type` is one of `jump`, `spin`, `step`, or `spiral`. `status` is
`observable` or `unobservable`. `unobservable` records label limitations and
is excluded from accuracy denominators and parent-support conclusions. Every
observable interval has a stable, locally unique `action_id`, finite seconds,
and `0 <= start_sec < end_sec`. Jump labels used for G4 have all T/A/L values
inside their interval.

The prediction JSON adds this optional field:

```json
{
  "action_candidates": [
    {
      "action_type": "jump",
      "search_start_sec": 3.0,
      "search_end_sec": 5.1,
      "core_start_sec": 3.4,
      "core_end_sec": 4.7,
      "confidence": 0.94,
      "status": "supported",
      "keyframes": {"T": 3.72, "A": 4.02, "L": 4.43}
    }
  ]
}
```

Candidate bounds must be finite and ordered. `status` is `supported`,
`uncertain`, or `unobservable`. The evaluator never treats a missing candidate
as a supported prediction. Candidate type is the coarse action classification.

## Matching and Metrics

For each sample and profile, observable labels are matched one-to-one to
predictions using descending temporal IoU, then start-time distance, then
stable source order. A match requires the configured minimum IoU (default
`0.20`) or a nonzero overlap plus a core interval covering the labelled action
midpoint. This permits conservative candidate search windows without merging
separate actions. Unmatched labels are false negatives; unmatched candidates
are false positives.

G3 reports, per profile and in aggregate:

- candidate recall, precision, and F1;
- matched candidate coverage of source-labelled duration;
- false positives per labelled minute;
- automatic coverage and uncertainty rate;
- counts for observable labels, unobservable labels, matched candidates,
  false negatives, and false positives.

G4 uses the matched pairs. It reports a coarse action confusion matrix and
Macro F1 across classes that have observable labelled support. A wrong-type
overlapping candidate is matched for classification but is not a G3 recall
success for the labelled profile. For jump pairs, it also reports separate
T/A/L absolute-error median and P95. Missing required keyframes contribute no
timing value and are recorded as incomplete timing coverage. High-confidence
error rate is the fraction of candidates at or above a configured confidence
threshold that are unmatched or coarse-type wrong.

Percentiles use the nearest-rank method (`ceil(0.95 * n) - 1` after ascending
sort) so small validation sets are deterministic.

## Gate Decision

Default thresholds are deliberately configuration input, copied into each
report rather than hidden in code:

```json
{
  "candidate_recall_min": 0.98,
  "coarse_macro_f1_min": 0.90,
  "jump_tal_median_error_max_sec": 0.10,
  "jump_tal_p95_error_max_sec": 0.25,
  "high_confidence_error_rate_max": 0.02,
  "high_confidence_threshold": 0.80
}
```

A profile is `accepted` only when it has observable support and satisfies all
metrics that apply to it. A profile with no labels, no matched candidates, no
required timing coverage, or any threshold failure is `blocked`. A lower G3
target may be used only when explicitly supplied as an approved override in
the threshold configuration; the report names the override and its reason.

`spin`, `step`, and `spiral` do not inherit jump T/A/L requirements. They must
still pass G3 and G4 classification/high-confidence requirements. Until a
profile is accepted, its future P2-B feature flag must remain off.

## Reproducible, Privacy-Safe Reports

The report generator receives the frozen manifest, evaluator result, pipeline
metadata, and threshold configuration. It computes SHA-256 over canonical JSON
(sorted keys, compact separators) for the manifest, configuration, and
pipeline metadata. It writes JSON plus Markdown with the same decision data.

Reports include only aggregate metrics and anonymous `sample_id` values. They
must remove `video_path`, `prediction_path`, `skater_id`, raw filenames, and
all absolute paths. The actual manifest and predictions remain local sensitive
inputs. A report records evaluator version, UTC generation time, hashes,
thresholds, profile decisions, and concise failure reasons.

## Components

- `backend/scripts/eval_against_gt.py` retains legacy keyframe/identity output
  and delegates new event metrics to a focused pure-Python module.
- `backend/app/services/technical_event_evaluation.py` validates contracts,
  deterministically matches labels and candidates, and calculates G3/G4
  metrics without database or provider dependencies.
- `backend/scripts/generate_technical_event_gate_report.py` assembles
  sanitized JSON/Markdown artifacts and profile decisions.
- `backend/tests/test_technical_event_evaluation.py` tests event matching,
  classifications, timing, uncertainty, and gate decisions with synthetic
  fixtures.
- `backend/tests/test_technical_event_gate_report.py` tests deterministic
  hashing and privacy-safe report output.
- `docs/evaluation/technical-event-gate.md` cites real generated reports only;
  it remains `blocked` until genuine Golden material is evaluated.

## Failure Handling

Malformed intervals, invalid confidence, repeated action IDs, impossible
keyframes, unsupported profile names, or unreadable predictions cause a clear
evaluation error; they cannot quietly improve a score. A profile with only
unobservable labels is blocked with an explicit insufficient-evidence reason.
Missing optional prediction data becomes a measurable false-negative outcome,
not a success. The report generator refuses metadata that contains raw paths
and verifies its own output contains none.

## Verification

Test-first coverage must include separated and adjacent actions, overlapping
candidates, missed candidates, wrong classification, high-confidence errors,
unobservable labels, missing profile coverage, T/A/L median and P95, stable
manifest hashing, and path/name redaction. Real acceptance requires a frozen,
human-labelled Golden set; synthetic tests validate tooling only and must never
be used to claim G3/G4 passed.

## Rollout Boundary

This delivers B0 evidence tooling only. After real reports exist, an operator
updates `docs/evaluation/technical-event-gate.md` with report hashes and
per-profile decisions. Only then may P2-B B1-B7 be planned and implemented;
the profile flags begin disabled and are enabled individually after acceptance.
