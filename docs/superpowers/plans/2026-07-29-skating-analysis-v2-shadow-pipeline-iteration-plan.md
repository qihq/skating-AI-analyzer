# Skating Analysis V2 Shadow Pipeline Iteration Plan

Date: 2026-07-29

Design: `docs/superpowers/specs/2026-07-29-skating-analysis-v2-shadow-pipeline-design.md`

This document supersedes the execution order and unchecked algorithm tasks in the July 12 high-accuracy master/child plans. Those documents remain historical references only. New implementation work starts from this plan, and any reused idea must satisfy the V2 contract and gate that owns it.

## Outcome

Deliver an identity-safe, timestamp-correct V2 skating-analysis pipeline for main-skater tracking, pose, multi-event action recognition, profile-specific key moments, and rotation count. V2 runs in shadow mode until a newly collected, private Golden dataset and deployment-class operational tests pass. Development happens in a separate Git worktree and nothing is merged into the main worktree until the complete program is accepted.

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
- No authoritative rollout occurs before every required gate passes on a frozen dataset.

## Worktree and Integration Policy

The following actions happen only when implementation begins, not while reviewing this plan.

1. Create a dedicated branch from the approved main commit, suggested name `codex/skating-analysis-v2`.
2. Create a separate worktree, suggested path `C:\Users\qihq\Documents\skating-analyzer-v2`.
3. Give the V2 worktree its own untracked runtime data directory and database. Never point experimental analysis at the main worktree's writable `data` directory.
4. Register private Golden source videos by path or copy them into the V2 runtime data directory. Do not add them to Git.
5. Commit each bounded behavior change with its tests and evidence. Do not mix product UI refactors or unrelated work.
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
- `v2`: V2 is authoritative and legacy is optional fallback only under the explicit rollout policy.

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
  evaluation/
  orchestration.py
```

Rules:

- Modules under `analysis_v2` depend on explicit contracts, not ORM models or FastAPI request objects.
- The router calls an orchestration adapter; it does not contain algorithm decisions.
- Legacy `app/services` modules enter V2 only through narrow proposal adapters.
- The standalone analysis pack consumes generated adapters or a versioned package snapshot. No V2 source file is manually maintained in two places.
- Pure evaluators can run without a live database or external model provider.

## Gate Overview

| Gate | Evidence | Blocks |
|---|---|---|
| G0 Worktree isolation | Separate branch, runtime data, database, legacy smoke tests | Any V2 implementation |
| G1 Golden pilot | 36 new events, valid labels, dedupe and split checks | Algorithm threshold calibration |
| G2 Baseline | 60-80 new events, frozen split, trustworthy evaluator, legacy report | V2 acceptance claims |
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

Percentage gates always include the numerator, denominator, rejection rate, confidence interval, and per-stratum breakdown. A percentage based on too few samples does not satisfy a gate by itself.

## Program Sequence and Ownership

The iterations are sequential at their gate boundaries. Within an iteration, tests, UI support, evaluator work, and algorithm work may proceed in parallel only when they do not share an unstable contract.

| Program block | Iterations | Primary owner action | User action | Exit evidence |
|---|---:|---|---|---|
| Isolation and labels | 0-2 | Build isolated runtime, contracts, and labeling workflow | Select new videos and learn the short labeling flow | Safe worktree plus usable private catalog |
| Measurement | 3-4 | Repair evaluator, dedupe/split data, freeze baseline | Label 36-event pilot, then expand to 60-80 events; review ambiguity | G1 and G2 reports |
| Foundations | 5-7 | Implement contracts, exact PTS, observations, camera motion, proposals | Review representative source-frame alignment | G3 and proposal diagnostics |
| Identity and pose | 8-9 | Build identity fusion and trustworthy pose | Add anchors or review ambiguous crossings when requested | G4 and G5 reports |
| Events and timing | 10-12 | Build proposals, classifiers, and source-frame moments | Review incorrect/ambiguous action labels, not production rules | G6-G8 reports |
| Rotation and review | 13-14 | Build multi-signal rotation and claim-level A/B fusion | Double-review ambiguous turn counts and report claims | G9 and G10 reports |
| Productization | 15-16 | Shadow orchestration, calibration, DS918+ hardening | Approve resource/accuracy tradeoffs | G11 and G12 reports |
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

The owner does not annotate every frame or every joint. For most events:

- select the action interval and family;
- confirm the main skater;
- record three profile moments where applicable;
- record rotation count/range and observability where applicable;
- draw 3-8 identity boxes;
- add a short ambiguity or scene tag when needed.

Difficult crossing/occlusion events receive denser boxes. The initial pose subset requires 50-100 frames across the whole dataset, not per video. The development team should keep the UI fast enough that an ordinary event takes roughly 3-6 minutes and a difficult event roughly 8-15 minutes; if actual timing is materially worse, improve the workflow before asking for the full 60-80 events.

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

### Tests

- Invalid pipeline mode fails with an actionable configuration error.
- Default mode remains legacy.
- Shadow mode cannot overwrite current legacy result fields.
- V2 runtime paths resolve beneath the V2 data root.
- Existing focused backend tests and frontend production build pass.

### Gate G0

- Separate worktree, branch, runtime data, and database are demonstrated.
- One legacy analysis produces the same public result shape as before.
- One no-op shadow run cannot mutate legacy evidence.

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

### Output

A private empty manifest and a sanitized dataset summary template.

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

### Deliverable

A usable labeling workflow plus a short owner-facing labeling guide.

## Iteration 3: Golden Pilot and Evaluator Repair

### Objective

Produce the first trustworthy diagnostic dataset and correct evaluation semantics before tuning V2.

### Data target G1

Collect 36 new events:

- 14 jump;
- 10 spin;
- 6 step;
- 6 spiral.

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

### Tests

- A missing track frame lowers coverage and recall rather than disappearing from the denominator.
- A wrong-person relock is not counted as merely lost.
- An unobservable rotation refusal is not scored as a wrong confident estimate.
- A Golden T/A/L value injected into a key-moment prediction run triggers leakage detection.
- Reordering manifest records cannot change metrics.
- Identical prediction and label fixtures pass only the intended metric, without manufacturing unrelated fields.

### Gate G1

- All 36 events pass schema validation.
- Split grouping and duplicate checks pass.
- At least 10% have a delayed second review.
- Evaluator fixture tests pass.
- Pilot metrics are recorded as diagnostic, not release claims.

## Iteration 4: Full Golden Set and Frozen Legacy Baseline

### Objective

Reach enough varied data to measure the architectural replacement honestly.

### Data target G2

Collect 60-80 new events:

- 24-32 jump;
- 16-20 spin;
- 12-16 step;
- 8-12 spiral.

Target at least 10-15 examples for any subtype reported separately, and never report a subtype as a standalone percentage below 6-8 examples. Keep rare subtypes grouped by action family until enough data exists.

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

### Gate G2

- Required event counts and scenario coverage are met.
- Frozen-test membership and hashes are recorded and locked.
- Legacy baseline JSON/Markdown is committed without private paths.
- Re-running the same baseline produces stable aggregates within declared nondeterminism limits.

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

### Tests

- Contract round trips are stable and deterministic.
- Invalid confirmed tracks without a valid bbox are rejected.
- An interpolated joint cannot claim `measured` provenance.
- Output hashes change when a relevant model/config/prompt changes and remain stable otherwise.
- Legacy adapters cannot mutate source legacy dictionaries.

### Deliverable

A contract-only V2 package with no changed production behavior.

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

### Tests

- Constant-frame-rate, variable-frame-rate, duplicate-PTS, dropped-frame, and rotated-video fixtures.
- Coordinate round trips stay within tolerance.
- Re-encoding equivalent content at a different container FPS preserves event timestamps within one source frame.
- No V2 time calculation divides sampled-frame count by an average FPS.
- Dense and sparse streams resolve to the same source frame identity.

### Gate G3

- Timebase and metamorphic tests pass.
- A static audit finds no sampled-frame-count physical timing in V2.
- Legacy public output remains unchanged in shadow mode.

## Iteration 7: Detection, Camera Motion, and Short-Track Proposals

### Objective

Build reusable observations without yet making identity decisions.

### Changes

- Wrap current detector and ByteTrack as candidate providers.
- Preserve all plausible skater candidates and short tracks, not just one selected box.
- Estimate camera pan, zoom, and shake from background features while masking detected people.
- Score blur, clipping, full-body visibility, crowd overlap, and candidate quality.
- Rank anchor frames for identity confirmation by quality rather than motion alone.
- Persist proposal diagnostics in the shadow artifact stream.

### Tests

- Synthetic pan/zoom does not become equivalent skater motion after compensation.
- Camera estimation failure lowers reliability without raising an exception.
- Crossing candidates remain distinct short tracks.
- Tiny targets and temporary detector misses preserve candidate uncertainty.
- Proposal output is deterministic under fixed detector fixtures.

### Evaluation

Measure detection/candidate recall independently from identity accuracy. Do not tune identity gates yet.

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

### Tests

- Same-clothes crossing, foreground occlusion, full exit/re-entry, fast pan, zoom, small target, and detector dropout fixtures.
- First wrong relock cannot mutate the immutable identity template.
- Forward/backward disagreement becomes uncertain, never confirmed.
- A stale box cannot satisfy confirmed coverage.
- Additional anchors resolve only causally affected intervals and retain revision provenance.

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

### Conditional experiment

If HSV/body-shape evidence cannot pass G4, benchmark a lightweight ReID or face embedding as an additional signal. Adopt it only if the frozen protocol shows a meaningful gain without violating privacy or DS918+ limits. Do not introduce it merely because it is available.

## Iteration 9: Pose V2 and Joint Provenance

### Objective

Produce trustworthy target-only pose observations without hiding uncertainty through interpolation.

### Changes

- Run the existing pose model on confirmed target crops with configurable context margin.
- Map joints into source coordinates.
- Record joint confidence, visibility, crop clipping, body scale, and source method.
- Apply gap-aware smoothing using PTS.
- Break smoothing at identity uncertainty, scene cuts, and large time gaps.
- Preserve raw measured observations alongside smoothed presentation values.
- Keep interpolated joints display-only unless a future metric explicitly permits them.
- Produce per-frame and per-phase pose quality.

### Model bakeoff

First evaluate the corrected existing pose model. If pose quality still blocks G5, compare a small number of pretrained alternatives on the same labeled subset. Compare accuracy, joint availability, latency, memory, model size, and DS918+ feasibility. Change the model only after the data-contract fixes are measured.

### Tests

- Wrong/uncertain identity produces no authoritative pose.
- Crop-to-source coordinate transformations are correct.
- Variable time gaps change smoothing strength correctly.
- Interpolation cannot enter authoritative biomechanics.
- Left/right swaps and missing joint visibility are surfaced.

### Pose labeling target

Start with 50-100 stratified source frames covering action cores, small targets, blur, occlusion, front/back views, and crossings. Expand only where confidence intervals or failure analysis require it.

### Gate G5

- Wrong-person authoritative skeleton rate: 0.
- PCK@0.2: at least 90% on labeled usable joints.
- Joint availability and jitter improve or have an approved tradeoff versus legacy.
- Core-event pose coverage is reported and sufficient for later event stages.

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

### Tests

- Multiple jumps, jump followed by spin, interrupted action, ordinary skating, and overlapping proposal fixtures.
- Camera pan alone does not create a high-confidence action.
- Weak evidence remains unknown instead of defaulting to step.
- Proposal merge and split operations preserve source PTS.

### Gate G6

- Proposal recall at least 98% on observable Golden events.
- False proposals per minute and proposal coverage are reported.
- No profile stratum has a hidden recall collapse.

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

### Small-data policy

- Do not train a large supervised classifier on 60-80 events.
- Start with interpretable temporal features plus pretrained semantic review.
- Use subtype-specific metrics only when their sample counts meet the declared minimum.
- If a lightweight learned calibrator is tested, fit it only on development, select on validation, document features, and keep frozen test untouched.

### Tests

- Profile classifiers are isolated and cannot silently fall through to step.
- Missing required evidence lowers confidence or returns unknown.
- One classifier's configuration change does not alter another classifier's fingerprint.
- Conflicting deterministic and semantic evidence remains visible.

### Gate G7

- Macro F1 at least 90%, target 95%.
- High-confidence classification error below 2%.
- Unknown/rejection and coverage rates are reported.
- No important stratum regresses materially against legacy without an approved safety tradeoff.

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

### Tests

- Source-frame boundary, VFR, dropped-frame, incomplete jump, two close events, and ambiguous landing fixtures.
- T/A/L cannot be copied from resolved semantic labels under evaluation.
- Missing landing returns incomplete/unobservable rather than a guessed frame.
- Equivalent transcodes preserve timestamps within tolerance.

### Gate G8

- Observable T/A/L median absolute error at most 0.10 seconds.
- P95 at most 0.25 seconds.
- Per-moment errors, completeness, refusal, and event-core tracking coverage are reported.
- Spin/step/spiral metrics use their own definitions and do not borrow jump gates.

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

### Gate G9

- Observable rotation MAE at most 0.25 turns.
- Integer/half-integer class accuracy at least 90%.
- Confidently wrong rate below 2%.
- Results are stratified by single/double/triple where available, Axel/non-Axel, and observability.

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

### Tests

- Path A prompt has no pose/biomechanics/computed-rotation leakage.
- Path B cannot promote interpolated or uncertain joints into authoritative facts.
- A/B disagreement affects only related claims.
- Report generation cannot introduce an action, timestamp, turn count, or technique defect absent from claims.
- Path A or Path B timeout leaves deterministic evidence retryable.
- Provider/model/prompt changes update fingerprints.

### Gate G10

- All technical report statements trace to one or more evidence claims.
- Unsupported-claim test suite is clean.
- Conflicts and unobservable states survive into user-visible summaries.
- A/B repeatability and provider failure behavior are documented.

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

### Tests

- Shadow failure cannot fail or overwrite the legacy analysis.
- Restart resumes at the first invalid or incomplete stage.
- Changing pose config invalidates pose and descendants, not decoded source observations.
- Changing a report prompt does not rerun tracking.
- Duplicate shadow requests coalesce safely.
- Storage cleanup respects source/label retention.

### Gate G11

- Repeated-analysis agreement at least 95% under fixed fingerprints.
- Every unexplained legacy/V2 difference identifies its first divergent stage.
- A full Golden shadow run completes without private data in committed reports.
- No legacy public API regression.

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

### Operational targets

Exact latency and memory budgets are measured during this iteration and approved before rollout. At minimum:

- no out-of-memory restart loop;
- bounded queue and concurrency;
- source and Golden labels survive restart and cleanup;
- failed external review calls can retry without rerunning local vision;
- legacy mode remains immediately selectable;
- V2 artifacts have predictable retention and disk growth.

### Gate G12

- G4-G11 still pass under the frozen production-candidate fingerprint.
- DS918+ restart, queue, memory, storage, and cleanup tests pass.
- Privacy and sanitized-export checks pass.
- Rollback to legacy is demonstrated without database restoration.

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

### Final verification

- Run all backend tests in bounded groups if one full run exceeds the execution window.
- Run all frontend tests and production build.
- Run packaging/generation checks for the standalone analysis pack.
- Rebuild the deployment artifact from the V2 worktree.
- Run one clean-install smoke test and one upgrade smoke test using a copied database, never the live database.
- Run the frozen Golden suite against the exact artifact fingerprint.

### Candidate deployment rule

Build the controlled candidate from the exact V2 worktree commit only if:

- all gates pass;
- no unresolved P0/P1 review finding remains;
- the user approves the final report;
- the exact tested commit is the controlled-deployment candidate;
- rollback is documented and tested.

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

### Rollback triggers

- any confirmed wrong-person result;
- a high-confidence technical claim contradicted by manual review;
- unexplained drift under an unchanged fingerprint;
- queue, memory, storage, or restart instability;
- missing source/label data;
- a material stratum regression not represented in the Golden gate.

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

### Gate

- No current stored report becomes unreadable.
- V2 tests and frozen metrics remain unchanged.
- Deployment artifact shrinks or complexity measurably decreases.
- Legacy rollback is retired only after an explicitly approved observation period.

### Final merge rule

Only after Iterations 0-19 are complete:

1. rerun full repository, packaging, frozen-Golden, privacy, migration, and DS918+ verification on the exact final commit;
2. review the complete V2 branch diff against the current main branch;
3. resolve any changes that arrived on main entirely inside the V2 worktree and rerun affected gates;
4. obtain explicit user approval for the exact final commit;
5. merge the completed branch into main in one controlled integration operation.

No partial iteration, provisional algorithm, or intermediate gate commit is merged into the main worktree.

## Golden Collection Matrix

Use this matrix to select the 60-80 events. One event can satisfy several scene columns, but the dataset summary must show actual counts.

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
| Operations | Runtime telemetry from the exact deployment artifact |

## Test Pyramid

### Per commit

- Focused unit and contract tests for changed modules.
- Static type/lint checks already used by the repository.
- No external model calls in ordinary unit tests.

### Per iteration

- Relevant legacy characterization tests.
- V2 integration fixtures.
- Private development/validation evaluation where allowed.
- Artifact fingerprint and privacy checks.

### Per gate

- Gate-specific Golden evaluation.
- Sanitized report generation and review.
- Repeatability run.
- No threshold edits after viewing frozen-test results; a failure returns to development/validation and requires a new production-candidate cycle.

### Final

- Complete backend/frontend/package verification.
- Exact deployment artifact Golden run.
- DS918+ operational and restart run.

## Failure Investigation Protocol

For any failed gate:

1. Record the exact fingerprint, metric, numerator/denominator, strata, and affected aliases.
2. Locate the first divergent stage rather than patching the final report.
3. Classify the cause as label ambiguity, source/timebase, candidate coverage, identity, pose, event, key moment, rotation, review, fusion, or operations.
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
- after Iteration 15: end-to-end shadow behavior is stable;
- after Iteration 17: controlled candidate deployment decision;
- after the rollout observation period: legacy retirement and final merge decision.

## Definition of Done

The V2 program is complete only when:

- a 60-80 event new-video Golden dataset is labeled, grouped, and frozen;
- source-time and leakage-safe evaluation are proven;
- tracking, pose, action, key-moment, and rotation gates pass;
- Path A/B consume bounded evidence and final reports are claim-traceable;
- shadow mode is restartable, diffable, fingerprinted, and cannot mutate legacy results;
- frozen metrics include coverage, refusal, raw counts, confidence intervals, and strata;
- the exact deployment artifact passes DS918+ operational tests;
- all repository tests/builds required by the final verification pass;
- no unresolved P0/P1 finding remains;
- rollback is demonstrated;
- the user approves the exact commit before it is merged into the main worktree.
