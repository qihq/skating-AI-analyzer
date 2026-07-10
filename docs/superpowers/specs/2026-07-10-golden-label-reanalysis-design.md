# Golden Label Reanalysis Design

Date: 2026-07-10

## Goal

Make Golden labeling a closed-loop correction workflow instead of an isolated evaluation tool.

After a parent labels the main skater and key moments, the same Golden workspace must be able to apply those labels as authoritative analysis inputs, rerun the affected pipeline stages, and update the existing report under the same `analysis_id` and report URL.

The change must also fix incomplete keyframe/frame presentation in the Golden workspace and preserve the current person tracker's recovery, relock, self-healing, and quality-diagnostic behavior.

## Confirmed Product Decisions

- `/golden` is the only Golden workspace.
- The sidebar opens `/golden` in sample-list mode.
- The progress/archive action opens `/golden?analysis_id=<id>` and automatically selects that analysis in the same workspace.
- Saving a Golden label remains a cheap draft operation.
- A separate `Apply Golden and reanalyze` action applies the label and starts formal reanalysis.
- Reanalysis updates the original analysis and report in place. It does not create a second report or a new `analysis_id`.
- Applied Golden data remains active on later ordinary retries until the user explicitly removes it.
- Golden main-skater boxes are tracking inputs, not report-only annotations.

## Current Problems And Root Causes

### Golden data does not affect formal reanalysis

The current Golden save route writes `golden_label.json`, `prediction.json`, and the shared Golden manifest. The formal `POST /analysis/{analysis_id}/retry` flow does not read those files. As a result, saving accurate labels and then retrying repeats the old automatic inputs.

### Frame identity is unstable

Golden boxes are currently keyed by mixed list positions or synthetic strings. Sampled, semantic, and partial semantic frames do not share one stable identity model. A reordered or incomplete list can therefore display a box on the wrong frame or make saved data appear missing.

### The workspace only exposes the debug run's partial frame sets

The existing editor merges sampled, semantic, and partial semantic arrays already present in one debug result. A local-pose Golden run may not contain all useful semantic/candidate frames. The fixed-height frame list and lack of an explicit missing-frame state further make available data look truncated.

### A single initial target box is not enough for difficult tracking

The existing manual target lock is a useful initial identity seed, but multi-skater crossings, small targets, and occlusion require identity evidence later in the action. Golden boxes should provide sparse, timestamped anchors without replacing the tracker's temporal model with static boxes.

## Recommended Architecture

Introduce an explicit `golden_overrides` layer on `Analysis` and consume it at well-defined pipeline boundaries.

The layer is separate from:

- the editable Golden draft;
- the tracker's automatic prediction;
- final derived analysis fields.

This separation preserves automatic evidence for comparison, makes applied state auditable, and prevents a later automatic retry from silently discarding human-confirmed inputs.

### Analysis Golden override record

Add a nullable JSON field to `Analysis` named `golden_overrides`. It contains a versioned applied snapshot:

```json
{
  "schema_version": 1,
  "source_debug_run_id": "...",
  "source_label_revision": 4,
  "applied_at": "2026-07-10T00:00:00Z",
  "applied_by": "parent",
  "action_window": {"start_sec": 1.2, "end_sec": 4.9},
  "keyframes": {
    "T": {"timestamp_sec": 2.31, "frame_id": "sampled:frame_0017"},
    "A": {"timestamp_sec": 2.73, "frame_id": "semantic:semantic_0002"},
    "L": {"timestamp_sec": 3.08, "frame_id": "sampled:frame_0023"}
  },
  "tracking_anchors": [
    {
      "anchor_id": "...",
      "timestamp_sec": 1.42,
      "source_frame_id": "sampled:frame_0008",
      "bbox": {"x": 0.22, "y": 0.12, "width": 0.18, "height": 0.66}
    }
  ],
  "label_hash": "..."
}
```

All coordinates remain normalized to the original uncropped video frame. Timestamps are the primary temporal identity; stable source frame IDs are supporting provenance rather than array indexes.

### Draft compatibility

The Golden label file remains the editable source. Its schema gains:

- a monotonically increasing `revision`;
- structured keyframe values with timestamps and source frame IDs;
- structured `tracking_anchors`;
- optional action-window values;
- applied revision, timestamp, and analysis status metadata.

Legacy numeric keyframes and `target_bboxes` maps are read through a compatibility normalizer. They are upgraded to the new representation on the next save. No existing Golden sample is discarded.

## Person Tracking Integration

Golden tracking boxes act as sparse identity anchors across the action, not as a per-frame replacement tracker.

### Anchor behavior

1. Sort validated anchors by `timestamp_sec`.
2. Use the earliest relevant anchor as a manual identity seed for the current target-lock flow.
3. At each anchor time, require the tracked target to agree with the human box, then refresh the tracker's location, appearance, and motion evidence from that confirmed target.
4. Between anchors, continue running the existing tracker normally.
5. Outside the anchored interval, retain the existing automatic target-lock and tracking behavior.

This keeps motion continuity and prevents a static box from following the wrong screen region as the skater moves.

### Safety and non-regression rules

- No applied anchors means the current tracking path is byte-for-byte behaviorally unchanged apart from passive diagnostics.
- Existing occlusion recovery, detector relock, appearance relock, manual-lock self-healing, pose reliability gates, and quality flags remain active.
- An anchor is rejected if it has an invalid normalized box, is too small, falls outside the source duration/action window, or duplicates another anchor at the same timestamp.
- Before application, adjacent anchors are checked for impossible speed/shape changes and strong identity inconsistency. Invalid sets block reanalysis with an actionable UI message.
- One valid anchor is allowed and behaves like an improved manual seed. Multiple anchors additionally constrain identity after crossings or occlusion.
- The system never silently ignores a valid applied anchor. If automatic evidence conflicts, it records a diagnostic and uses the confirmed anchor at that instant.
- If the tracker cannot bridge two valid anchors, the output records fallback/lost-frame diagnostics rather than inventing a continuous confident track.

### Diagnostics

Store automatic and Golden-aware tracking evidence separately. Add summary fields such as:

- `golden_anchor_count`;
- `golden_anchor_hits`;
- `golden_anchor_conflicts`;
- `golden_anchor_reseed_count`;
- `golden_unbridged_intervals`;
- `identity_switch_count`;
- `automatic_fallback_frame_count`;
- Golden-specific quality flags.

These fields support regression evaluation and make it possible to prove that Golden improves identity tracking instead of merely changing the report.

## Keyframe Integration

Automatic biomechanics and semantic keyframe detection still run and remain stored as prediction evidence.

After automatic candidate generation, the pipeline applies validated Golden keyframes as the authoritative resolved T/A/L or profile-specific phase timestamps. Derived metrics that depend on those timestamps must be recomputed from the Golden-resolved moments before visual analysis, cross-validation, scoring, and report generation.

Final keyframe records expose:

- automatic prediction and confidence;
- applied Golden timestamp;
- final timestamp;
- `source: golden_override` when overridden;
- delta between prediction and Golden;
- source label revision.

An action profile must satisfy its required keyframe ordering before the override can be applied. Missing optional moments may fall back to automatic detection; missing required moments block application and identify the exact missing fields.

## Reanalysis Flow

Add a formal endpoint shaped as:

`POST /analysis/{analysis_id}/golden-overrides/apply-and-retry`

The request identifies the source debug run and expected label revision. The backend must:

1. Load the analysis, run, and saved label.
2. Verify that the run belongs to the requested analysis and the analysis has an available source video.
3. Reject stale revisions so a concurrent edit cannot be applied accidentally.
4. Normalize and validate action window, keyframes, and tracking anchors.
5. Persist an immutable applied snapshot in `analysis.golden_overrides`.
6. Mark the same analysis pending and clear only the derived fields invalidated by the override.
7. Start formal analysis with the appropriate retry boundary.
8. Return the original `analysis_id`, processing status, applied revision, and report route.

### Retry boundary

- Action-window changes restart frame extraction/sampling and all later stages.
- Tracking-anchor changes restart target tracking/pose and all later stages.
- Keyframe-only changes restart biomechanics resolution and all later dependent stages.
- A combined change uses the earliest required boundary.
- The first implementation should prefer a conservative earlier restart when stage-cache validity is uncertain. Correctness takes priority over saving runtime.

Ordinary `POST /analysis/{analysis_id}/retry` keeps applied overrides. Add a separate explicit remove endpoint; removal does not silently mutate a completed report and should offer reanalysis without Golden to make the report consistent.

### Atomicity and failure behavior

- Validation completes before the analysis is changed to `pending`.
- The applied override snapshot and pending transition are committed together.
- A processing failure leaves the applied override available for retry and preserves the existing stale-report behavior.
- The UI polls the existing analysis status and links to `/report/{analysis_id}` after completion.
- Repeated apply calls with the same label hash are idempotent and must not enqueue duplicate work.

## Unified Golden Workspace

Both entrances render `DebugPage workspace="golden"` at `/golden`.

### Sidebar entry

`/golden` opens the sample browser with existing labeled/unlabeled/error counts and the most recently selected sample when appropriate.

### Progress/archive entry

`/golden?analysis_id=<id>` uses the same page, automatically ensures/selects the corresponding Golden run, and opens the labeling panel. The query parameter is the only entry-specific state. It must not select a separate component or alternate data flow.

When an analysis ID is invalid or unavailable, the page shows an inline explanation and keeps the sample browser usable.

## Complete Frame And Video Experience

### Unified frame catalog

Expose a stable, chronological frame catalog for the Golden run. It merges:

- sampled frames;
- local pose/candidate frames;
- semantic frames;
- partial semantic frames;
- previously saved Golden source frames;
- on-demand frames generated from an exact source-video timestamp.

Each row contains stable ID, timestamp, source, image URL/status, dimensions, and any prediction/Golden markers. Deduplicate by timestamp tolerance while retaining source badges.

The catalog endpoint supports pagination or time ranges so completeness is not tied to one large debug-result payload.

### Editor layout

- The source video is the temporal authority and remains synchronized with the selected frame/keyframe.
- The frame strip is chronological, virtualized or incrementally loaded, and not hidden inside a fixed-height truncated panel.
- The UI shows loaded count, total count, active filters, and explicit missing/loading/error states.
- Source badges distinguish sampled, candidate, semantic, partial, saved Golden, and on-demand frames.
- The user can set a keyframe from a catalog frame or directly from the current video time.
- To draw a tracking anchor at an arbitrary time, the backend extracts/caches the exact video frame; the resulting frame receives a stable timestamp-based ID.
- Reopening the workspace restores keyframes and boxes to the same timestamp/source frame.
- Images use their natural aspect ratio with `object-contain`; box coordinates map to the actual displayed image area rather than letterbox padding.

## Primary Actions And Status

The workspace presents two distinct actions:

- `Save draft`: persists edits without changing the formal report.
- `Apply Golden and reanalyze`: validates, previews impact, applies the snapshot, and reruns the formal analysis.

Before reanalysis, show an impact summary such as:

`3 keyframes and 5 tracking anchors will rerun from person tracking and update the existing report.`

The applied state shows label revision, applied time, current analysis status, and whether the draft contains newer unapplied edits. While processing, disable duplicate application but keep the page readable.

## API And Data Boundaries

New or extended backend responsibilities:

- Golden label normalization and revisioning.
- Stable frame catalog and exact-time frame extraction.
- Applied-override validation and idempotency.
- Conversion of tracking anchors into tracker inputs.
- Golden keyframe resolution before dependent metrics/report stages.
- Explicit override removal.

Frontend responsibilities:

- Route-driven run selection in one workspace.
- Draft/applied/processing status presentation.
- Complete frame catalog loading and source filtering.
- Video synchronization and exact-time capture.
- Impact preview and apply/reanalysis action.

Do not make the frontend write directly into `Analysis` fields or infer retry stages. Those decisions belong to the backend.

## Testing Strategy

### Backend unit tests

- Legacy Golden labels normalize without data loss.
- Stable frame IDs survive frame-list reordering.
- Stale label revisions and mismatched analysis/run IDs are rejected.
- Invalid boxes, timestamps, ordering, and conflicting anchors block application.
- The same label hash does not enqueue duplicate reanalysis.
- Action-window, anchor, and keyframe changes choose the correct earliest retry boundary.
- Applied overrides survive ordinary retry and can be explicitly removed.
- Golden keyframes become final resolved moments while automatic predictions remain available.
- Derived keyframe metrics use Golden timestamps.

### Person tracker regression tests

- With no Golden anchors, current tracker fixtures produce unchanged results.
- A single anchor behaves as a manual identity seed.
- Multiple anchors preserve identity through a two-skater crossing.
- Anchors before and after a short occlusion recover the same skater.
- Small-target and partial-visibility anchors retain existing reliability gates.
- A clearly invalid/wrong-person anchor set is rejected before formal reanalysis.
- Existing appearance relock, manual-lock blocking, and self-heal tests continue to pass.
- Diagnostics accurately report hits, conflicts, reseeds, fallback frames, and unbridged intervals.

### API/integration tests

- Save draft does not modify the formal analysis.
- Apply and reanalyze updates the same `analysis_id` and report route.
- Tracking anchors rerun pose and downstream stages; keyframe-only labels rerun dependent stages.
- A failed reanalysis retains the applied override for a safe retry.
- Sidebar and progress-created runs resolve to the same Golden run and saved label.
- Frame catalog includes every available source and reports missing assets explicitly.

### Frontend and rendered QA

- `/golden` opens the sample-list workspace.
- `/golden?analysis_id=3330183c-978b-428c-92bc-145c6a1aa2e4` selects the requested sample and displays its full frame catalog.
- Desktop, tablet, and phone layouts show the video, frame counts, frame sources, keyframe controls, and action buttons without clipping or scroll traps.
- Selecting a frame seeks the video; selecting video time can create an exact frame and anchor.
- Save/reopen preserves exact keyframes and boxes.
- Apply shows impact summary, processing state, and final link to the unchanged report URL.
- Page identity, nonblank state, framework overlay, console health, screenshot, and target interaction checks pass.

## Rollout And Regression Guardrails

- Keep `golden_overrides` nullable and all pipeline reads conditional.
- Land normalization/validation and no-override regression tests before tracker integration.
- Compare automatic and Golden-aware tracking on the existing Golden evaluation set before making the apply action generally available.
- Record pipeline version, label hash, and source revision in the final report diagnostics.
- Keep a feature flag for applying Golden tracking anchors during initial rollout; draft labeling and evaluation remain usable if the integration is disabled.
- Do not delete automatic prediction evidence or existing Golden files during migration.

## Non-Goals

- Golden does not continuously train or fine-tune a model online.
- Golden does not create a second report/version browser in this iteration.
- Golden does not replace the person tracker with frame-by-frame manual boxes.
- Golden does not automatically apply a saved draft without explicit confirmation.
- This work does not redesign unrelated debug workspace features.
