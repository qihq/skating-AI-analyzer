# Skating Analyzer V2 Full-System Shadow Rebuild Design

Date: 2026-07-29

## Goal

Rebuild the skating-analysis algorithm around a timestamped, identity-safe evidence pipeline that improves all five coupled capabilities together:

1. main-skater tracking;
2. pose extraction;
3. action recognition;
4. key-moment localization;
5. rotation-count estimation.

The algorithm is the center of a full-product compatibility rebuild. Every existing feature that reads, changes, summarizes, exports, configures, or protects analysis data must migrate with the evidence contract. The new pipeline must run beside the current implementation until frozen Golden evaluation proves that each replacement is safer and more accurate. Existing scenario-specific rules remain available as a legacy baseline and failure-mode catalog, but no new rules are added to the legacy identity or semantic decision maze.

## Confirmed Product Decisions

- All five algorithm areas are in scope; this is not a tracking-only refactor.
- Use an incremental V2 shadow pipeline instead of a big-bang replacement.
- Keep Path A and Path B, but move them after deterministic structured evidence generation.
- Path A remains a target-video visual reviewer; Path B remains a structured pose and measurement reviewer.
- Neither Path A nor Path B is an authoritative identity, timestamp, or rotation source.
- Final reports consume fused claims, not `dual.path_a` directly.
- Optimize first for the owner's son and the real family-video distribution. Do not claim broad skater generalization from this dataset.
- Build the formal Golden dataset only from newly selected videos. Historical debug videos and outputs are excluded from development, validation, frozen-test, calibration, and release metrics.
- Prefer an explicit `uncertain` or `unobservable` result over a confident wrong-person or wrong-rotation result.
- Deployment constraints include a Synology DS918+ class host. Large ReID, pose, or temporal models are optional only after measured benefit and resource validation.
- Preserve every current product capability unless the owner explicitly approves its retirement after an inventory, replacement, migration, and rollback review.
- Treat training plans, follow-up chat/corrections, comparisons, progress, skills, memories, monthly chapters, annual collections, exports, settings, providers, runtime diagnostics, backups, and parent access as first-class V2 consumers or protected compatibility domains.
- A page opening successfully is not feature preservation. Its reads, writes, regeneration, background jobs, provenance, permissions, exports, and historical behavior must remain correct.

## Relationship to Earlier Plans

This specification and `docs/superpowers/plans/2026-07-29-skating-analysis-v2-shadow-pipeline-iteration-plan.md` are the authoritative design and execution entry points for the V2 rebuild. Earlier July high-accuracy plans remain useful historical references, test inventories, and failure-mode notes, but their unchecked tasks are not executed independently. Any reusable earlier task must be re-scoped under a V2 iteration and its current Golden gate.

## Why Refactoring Is Necessary

### No trustworthy real-world baseline

The repository has branch-level and synthetic tests, but no persisted `golden_manifest.json`, `golden_label.json`, or high-accuracy baseline report. Historical reports that showed zero T/A/L delta reused the same effective timestamps on both sides of the comparison. The current evaluator also fails to separate missed coverage from wrong-person relock cleanly.

Consequently, the previous scenario-specific optimizations are not discarded, but their real accuracy contribution is unknown. They are preserved as:

- a frozen legacy baseline;
- characterization tests;
- a catalog of known failure modes;
- reusable low-level detection, local-zoom, and diagnostics utilities where ablation proves value.

### The timebase is invalid for downstream dynamics

Motion-weighted sampling produces nonuniform time intervals, while tracking, pose smoothing, air time, rotation speed, and other logic frequently consume a derived constant `effective_fps`. This violates the assumption behind velocity, temporal smoothing, T/A/L spacing, and rotation unwrapping.

V2 therefore treats source presentation timestamps as mandatory data, not optional metadata.

### Identity confidence is not detector confidence

The legacy pipeline uses many geometric gates, ByteTrack continuity, and an optional mutable HSV torso template. Those signals can generate track candidates but do not establish the identity selected by the parent. An early wrong relock can also contaminate the mutable appearance template.

V2 separates detection and short-track generation from identity decisions.

### Pose coverage currently hides provenance

Measured points, weak points, smoothed points, interpolated points, and points obtained from uncertain or stale boxes are not separated strongly enough for biomechanics. V2 makes joint provenance and identity state part of the contract.

### Action, keyframe, and rotation rules are coupled

The existing action and semantic-keyframe code combines motion, pose, video semantics, retries, conflict repair, and historical exceptions. Weak mixed-action evidence can default to step; spin, step, and spiral key moments use simplified proxies; rotation relies mainly on a 2D shoulder-line angle.

V2 uses proposals, profile-specific event models, source-frame refinement, and multi-signal rotation estimation.

### Multiple implementations can drift

The backend, standalone analysis pack, and older `preprocessing`, `pose_estimation`, and `action_recognition` packages expose overlapping implementations. V2 has one algorithm core. Runtime applications and delivery packs contain adapters or generated snapshots, not independently edited algorithm copies.

## Existing Path A and Path B

### Current Path A

Path A prioritizes an action-window video clip, falls back to original image frames, and asks a visual-language model for phases, observations, strengths, weaknesses, and pure-vision subscores. It intentionally excludes biomechanics values, but it still receives the proposed action profile, motion context, and semantic-video context.

### Current Path B

Path B receives pose-annotated frames, per-frame measurements, biomechanics summaries, action-profile evidence, and keyframe context. It selects a stage-balanced subset, currently under a configurable safety cap, and supplies grounded observations and subscores. Path B failure is soft and does not stop report generation.

### Current fusion limitation

The paths run concurrently and produce agreement, conflict, recommendation, and blend-weight diagnostics. However, the host still sets the main structured vision result to Path A. This is diagnostics-assisted selection rather than claim-level evidence fusion.

## V2 Architecture

```text
Source video and source PTS
  -> dense low-resolution observation stream
  -> detections, camera motion, and short-track proposals
  -> identity fusion: confirmed | uncertain | lost
  -> identity-authorized target crops
  -> timestamped pose observations with provenance
  -> high-recall multi-event proposals
  -> profile-specific action classifiers
  -> source-video frame-accurate event refinement
  -> key moments and rotation evidence
  -> Path A target-video review + Path B structured-evidence review
  -> claim-level evidence fusion
  -> report, confidence, observability, and audit record
```

The pipeline uses three coordinated streams:

1. **Dense tracking stream**: low-resolution source-order frames with exact PTS. It favors temporal continuity and camera-motion estimation.
2. **Local pose and event stream**: target crops around proposals at sufficient frame rate. It favors joint quality and action dynamics.
3. **Sparse semantic review stream**: selected clips and frames for Path A, Path B, and other visual-language review. It favors semantic context and cost control.

Sparse semantic frames never define the timebase for physical measurements.

## Canonical Data Contracts

### `FrameObservation`

- `source_video_hash`
- `source_frame_index`
- `pts_sec`
- `duration_sec`
- `image_size`
- `camera_transform`
- `camera_reliability`
- `blur_score`
- `occlusion_context`
- `pipeline_version`

### `TrackCandidate`

- `candidate_id`
- `bbox`
- `detector_score`
- `short_track_id`
- `appearance_features`
- `pose_shape_features`
- `camera_compensated_motion`
- `evidence_sources`

### `TrackState`

- `state`: `confirmed | uncertain | lost`
- `bbox`
- `identity_score`
- `identity_margin`
- `candidate_ids`
- `bbox_source`
- `occlusion_state`
- `template_update_allowed`
- `reasons`

A fallback or stale display box is never represented as a confirmed `TrackState`.

### `PoseObservation`

- source frame identity and PTS;
- originating `TrackState`;
- per-joint coordinates and confidence;
- per-joint source: `measured | smoothed | interpolated | missing`;
- person-scale estimate;
- temporal-gap metadata;
- pose-quality and jitter diagnostics.

Only identity-confirmed, measured or explicitly permitted smoothed observations can enter authoritative action and biomechanics calculations. Interpolated pose is display-only by default.

### `ActionEvent`

- `event_id`
- `profile`: `jump | spin | step | spiral | unknown`
- start/end PTS;
- proposal source and scores;
- classifier evidence;
- tracking and pose coverage;
- observability;
- confidence and calibration version.

Multiple events per input video are supported.

### `KeyMoment`

- event ID and profile-specific semantic key;
- exact source frame index and PTS;
- definition version;
- candidate evidence;
- confidence;
- warnings and observability.

Jump T/A/L definitions are fixed and versioned. Spin, step, and spiral use their own state schemas instead of pretending to have jump phases.

### `RotationEstimate`

- pre-takeoff rotation;
- airborne rotation;
- post-landing continuation;
- total observed body rotation;
- rotation class;
- Axel/non-Axel convention;
- signal-level estimates and reliability;
- fused estimate and interval;
- observability and rejection reason.

### `EvidenceClaim`

- `claim_type`
- `value`
- `sources`
- `conflicts`
- `confidence`
- `observability`
- `status`: `confirmed | uncertain | unobservable`
- model, configuration, and prompt fingerprints.

Reports may explain an `EvidenceClaim`; they may not invent a new technical fact absent from the fused claim set.

### `AnalysisExperienceV2`

The backend exposes a presentation contract between internal evidence and the family-facing frontend. Pages do not read `TrackState`, raw Path A/B payloads, or loosely typed legacy dictionaries directly.

The contract contains:

- `schema_version` and compatibility capabilities;
- pipeline mode and public analysis status;
- one or more display-ready action events;
- event intervals and profile-specific moments on the source timeline;
- family-safe confidence, observability, and review-task states;
- pose availability and provenance summary;
- rotation value, range, or refusal state without false precision;
- traceable report claims and next actions;
- optional parent-only diagnostics references, never raw provider output.

An additive backend presenter creates this response for legacy, shadow, and V2 analyses. The frontend therefore consumes one stable experience model during migration instead of detecting dozens of old fields inside components.

The experience envelope also declares one authoritative rendering source:

- `authority`: `legacy | v2`;
- `source_pipeline_fingerprint`;
- `capabilities`;
- `compatibility_notes`;
- `review_tasks`;
- `events` and all downstream display data from the same authority.

There is no field-level legacy/V2 fallback inside one ordinary response. In shadow mode, the family response is entirely legacy-authoritative and the V2 result is available only from a separate parent-authorized comparison endpoint. After V2 cutover, a missing V2 claim is displayed as unavailable or unobservable; it is not silently filled with a legacy value. Historical legacy analyses are adapted wholesale into `AnalysisExperienceV2`, so they remain readable without mixing their evidence into a new V2 analysis.

### `AnalysisFactsV2`

`AnalysisExperienceV2` is the family-facing read model. Backend consumers use a sibling backend-owned `AnalysisFactsV2` projection built from the same single-authority evidence. Training plans, follow-up chat, corrections, comparisons, growth, monthly/annual stories, skill automation, memory suggestions, exports, and shares do not read `Analysis.bio_data`, `Analysis.report`, raw Path A/B, or incidental legacy columns directly after migration.

Each fact carries:

- analysis and event identity;
- `authority: legacy | v2` and source pipeline fingerprint;
- claim/metric definition version and unit;
- status, observability, confidence, and human-confirmation provenance;
- source event/moment references and compatibility group;
- permissions for family display, aggregation, comparison, coaching, correction, and export.

Downstream rules:

- a generated artifact stores the source fact hash, schema version, authority, and generation fingerprint;
- regeneration uses the current authoritative fact revision only after an explicit action;
- published monthly chapters, annual collections, completed plans, chat history, shares, and exports remain immutable historical snapshots unless their existing revision flow is used;
- cross-analysis aggregation requires matching metric definition, unit, convention, and sufficient confirmed coverage;
- `uncertain`, `lost`, `unobservable`, interpolated-only, or definition-incompatible facts cannot unlock skills, create progress trends, become technical memory, or produce confident plan instructions;
- Shadow facts are diagnostic only and cannot enter any family artifact or automation.

### Feature-preservation registry

The implementation maintains a machine-readable registry of current product surfaces. Each entry records route/API ownership, read and write models, parent/child access, background jobs, artifacts, legacy fixtures, V2 fixtures, rollback behavior, and owning iteration. A capability cannot disappear merely because it was missed by a new page shell. Any proposed retirement requires explicit owner approval and an independently reviewed migration plan.

The required registry covers:

| Domain | Existing capabilities that must remain |
|---|---|
| Analysis lifecycle | upload, target preview/lock, action window, notes/highlight quote, session link, status/logs, retry/rerun, delete, list/detail, auto-eval, Golden override compatibility |
| Media and evidence | original/rendition playback, quality selection, exact seek, frame/pose overlays, synchronized compare media, text/image/PDF exports |
| Follow-up and corrections | per-analysis chat history, multi-question replies, provider identity, action/moment/report/target correction proposals, apply/dismiss, regenerate report, video-keyframe rerun, chat sharing |
| Plans and practice | generate/regenerate plan, fallback plan, plan detail, session completion, extension, latest-plan entry, training-session CRUD and analysis/session linking |
| Growth and history | home KPIs, archive/history, progress/trends, compare creation/status/retry/result, milestones, manual skill lock/unlock, learning path, XP/streak/profile/avatar |
| Long-form growth | monthly fact preview/generation/edit/revision/publish/recycle/restore/permanent delete; annual preview/selection/revision/recycle/restore/permanent delete; resumable PDF export/download |
| Memories | Snowball memory CRUD/pin/expiry, suggestion review/apply/dismiss, Snowball chat, parent/child visibility |
| Family and appearance | parent PIN setup/verify/change, parent/child mode, skater settings, four-space navigation, classic-route compatibility, Animal Island time/theme preference |
| Providers and models | provider CRUD/activate/test, encrypted keys, vision/report/Path A/Path B slots, vote configuration, provider metrics/specialties, model/prompt/config fingerprints, API health test |
| Local vision runtime | MediaPipe single/multi-pose status, `POSE_NUM_POSES`, pose task path, YOLO weights/path/download state, ByteTrack/supervision/torchvision readiness, multi-person tracking, candidate selection, optional ReID/face experiment status |
| Operations and data safety | health/system/storage status, queue/resource telemetry, startup seeds/backfills/progress sync, archive scheduler, media cleanup, backup list/create/restore/retention, annual-export recovery, DB migration/downgrade, standalone analysis pack, Docker/all-in-one/DS918+ packaging |

Routes may be redirected into the four canonical spaces, but the capability, authorization, historical URL, and result semantics must remain. Classic UI may become a compatibility shell only after every function is reachable in the Animal Island experience and route tests prove the redirect.

Full-product scope has three treatment levels:

1. **Semantic migration:** features that consume or mutate analysis conclusions move to `AnalysisFactsV2` and versioned derived artifacts.
2. **Protected preservation:** independent features such as training-session CRUD, PIN, profile, and appearance keep their implementation unless integration requires change, but receive characterization, authorization, data, route, and rollback tests.
3. **Operational integration:** providers, local models, settings, background jobs, storage, backup/restore, packaging, and deployment integrate with V2 fingerprints, invalidation, persistence, privacy, and recovery.

This is a full-system contract and verification refactor, not a mandate to rewrite stable independent code without a measured reason.

## Component Design

### Timebase and media layer

- Decode source frame index and PTS from the original video.
- Preserve variable-frame-rate timing.
- Resampling outputs keep references to source frames and PTS.
- Replace frame-count thresholds with durations where they represent time.
- Track discontinuities and decoding gaps explicitly.
- Provide source-frame extraction for local refinement without relying on sampled frame numbering.

### Tracking V2

- Reuse YOLO and ByteTrack as detection and short-track proposal providers.
- Build initial identity from several high-quality human-selected or automatically ranked anchors.
- Maintain an immutable manual identity template and a separate short-term template.
- Freeze short-term template updates during crossings, recovery, low identity margin, or a stabilization window after relock.
- Estimate camera pan, zoom, and shake from background features; lower motion evidence weight if camera estimation is unreliable.
- Run forward and backward proposals with an overlap region.
- Confirm identity only when fused evidence is consistent; disagreements become `uncertain` conflict intervals.
- Expose additional-anchor requests for unresolved conflict intervals.
- Evaluate optional ReID or face embeddings only as additional evidence and only after a Golden ablation.

### Pose V2

- Run pose only on identity-authorized crops, with a controlled context margin.
- Map coordinates back to the source frame.
- Track joint confidence, crop clipping, body scale, and visibility.
- Smooth against real time gaps.
- Prevent smoothing across identity uncertainty or large temporal gaps.
- Preserve raw observations beside smoothed presentation data.
- Never produce an authoritative skeleton for the wrong or uncertain person.

### Action event V2

- Generate high-recall candidate intervals from dense motion, pose dynamics, track motion, and optional video-semantic hints.
- Classify each candidate independently for jump, spin, step, spiral, or unknown.
- Do not force a single action profile for the entire video.
- Do not default weak mixed evidence to step.
- Separate proposal recall evaluation from classification evaluation.
- Allow Path A to challenge or support the event class, but not to locate the person.

### Key-moment V2

- Use a profile-specific state machine for each event class.
- Refine a detected interval against original 30/60 FPS frames and exact PTS.
- Score each key moment independently.
- Enforce temporal ordering without fabricating missing moments.
- Return incomplete or unobservable phases explicitly.
- Keep model-selected semantic frames as review evidence, not as physical-time Ground Truth.

### Rotation V2

The rotation estimator combines independent signals where observable:

- shoulder and hip orientation with left/right assignment confidence;
- torso and limb appearance periodicity;
- target-crop optical flow and silhouette orientation;
- pose transition and arm-position context;
- Path A semantic support or disagreement.

The estimator must detect aliasing and reject an answer when sampling or visibility cannot distinguish competing turn counts. It separates ice pre-rotation, airborne rotation, and post-landing rotation. Axel convention is applied only after the action subtype is sufficiently supported.

### Path A V2

- Input: identity-confirmed target clip with enough surrounding context to understand travel and ice contact.
- Excludes pose coordinates, biomechanics, computed rotation, and final key moments.
- Outputs action-family support, stage ranges, visible technique observations, contradictions, and observability.
- Cannot override identity or exact source timing.
- Must output `unobservable` instead of guessing through blur or occlusion.

### Path B V2

- Input: source-linked pose frames and structured measurements with provenance.
- Clearly marks measured, smoothed, interpolated, uncertain, and missing evidence.
- Deterministic services compute physical values; the language model explains them.
- Does not infer identity from the annotated image.
- Automatically suppresses claims whose required joints or tracking states are unreliable.

### Evidence fusion and reporting

- Fuse individual claims rather than selecting an entire path.
- Use calibrated source reliability by task and scenario.
- Preserve conflicts rather than averaging incompatible values.
- An identity conflict blocks downstream authoritative pose and technical claims for that interval.
- A rotation conflict returns an interval or uncertain class, not a falsely precise number.
- The UI exposes concise uncertainty and a review action without exposing internal Path A/B implementation names in normal family-facing views.

## Frontend Experience and Entry Points

### Product-language boundary

Internal V2 states map to clear family language:

| Internal state | Family-facing meaning | Normal UI behavior |
|---|---|---|
| `confirmed` | 已确认 | Show the result and its evidence normally |
| `uncertain` | 需要确认 | Show the limited result and one concrete review action |
| `lost` | 这段没有跟清楚 | Do not show pose or technical conclusions for the interval |
| `unobservable` | 画面不足，暂不判断 | Explain what is unavailable without treating it as a technique defect |
| `shadow` | Hidden from ordinary users | Visible only in parent-authorized advanced review |

The frontend never translates confidence into certainty merely to fill a card. It avoids technical names such as Path A, Path B, ReID, identity margin, pipeline hash, or optical-flow aliasing outside advanced tools.

### Animal Island continuity

V2 extends the current Animal Island/family-growth theme instead of creating a parallel engineering interface:

- reuse the four primary spaces: 首页、开始复盘、成长、我的;
- reuse `IslandCard`, `IslandPageHeader`, `SectionNav`, shared media controls, spacing, rounded surfaces, natural colors, and day-period themes;
- use calm, actionable language rather than red/green telemetry dashboards;
- preserve parent/child information-density differences;
- keep warning colors semantically stable across island time themes;
- preserve keyboard, reduced-motion, contrast, touch-target, tablet, desktop, and mobile behavior.

### Entry-point changes

The route hierarchy remains recognizable and backward compatible:

- `/home`: the latest-analysis card shows `processing`, `needs_confirmation`, `completed`, or `partially_observable`, and sends the parent to the next useful action.
- `/review`: remains the primary "冰场小屋" entry for upload and analysis. It also becomes the inbox for pending main-skater, action-window, or ambiguity confirmation generated during an analysis.
- `/analysis/:id`: remains the stable analysis-detail route. It supports multiple events through an event selector and source-time timeline while retaining the current sections: 总结、关键时刻、身体与姿态、追问、更多.
- `/growth`: consumes only compatible confirmed claims. Uncertain, unobservable, changed-definition, or insufficient-coverage values do not silently enter trends, comparisons, milestones, chapters, or annual exports.
- `/me/advanced`: remains parent-authorized. Model/API, diagnostics, Golden labeling, and a new Shadow review tool live here.
- `/golden`, `/debug`, existing `/report/:id` links, and old stored report URLs remain compatible through redirects or presenters during migration.
- Compatibility routes remain explicit: `/upload` redirects to `/review`; `/skills` to `/path`; `/progress` to `/archive`; `/parent/setup` keeps PIN onboarding; `/settings` and `/settings/api` retain family/model settings; `/report/:id/workspace`, `/report/:id/pose-debug`, and `/report/:id/target` land on their canonical report/review sections; `/compare/results/:comparison_id` retains persisted comparison results.

No fifth primary navigation destination named V2, AI, Shadow, Golden, or Algorithms is introduced.

### Analysis-detail experience

For a video with several events, the detail page provides:

- an overview summarizing which events were found and which require review;
- a shared video timeline with event intervals and profile-specific key moments;
- an event selector that keeps video position, summary, moments, pose, and questions synchronized;
- per-event observability and confidence language;
- pose overlays only where identity and joints are authorized;
- measured/smoothed presentation without treating interpolated data as technical evidence;
- rotation as an estimate or range with the relevant convention, never an unsupported exact number;
- a single next action when an anchor, interval, or label needs confirmation.

Legacy single-action analyses are presented as one event, so historical reports do not require database rewrites.

### Advanced review experience

The parent-only Shadow workspace may display:

- legacy and V2 results side by side;
- the first divergent stage;
- identity conflict intervals and candidate evidence;
- measured/interpolated pose provenance;
- action, key-moment, rotation, Path A/B, and fused-claim differences;
- pipeline/model/config/prompt fingerprints;
- Golden evaluation status and gate evidence.

This workspace is diagnostic and cannot silently promote a shadow result into the family report. Promotion or correction requires a separately confirmed, audited action.

### API compatibility

- Existing `AnalysisDetail` fields remain readable during migration.
- A dedicated versioned `AnalysisExperienceV2` endpoint becomes the modern frontend's primary contract for both historical and V2 analyses; raw legacy analysis fields remain only for bounded compatibility consumers during retirement.
- The backend owns normalization from stored legacy/V2 evidence to the experience model.
- Frontend TypeScript types are generated or contract-checked against the backend schema; production components do not use `Record<string, unknown>` for V2 experience fields.
- Capabilities and schema versions control rendering. Components do not infer pipeline generation from incidental field presence.
- Shadow artifacts and private Golden labels are never returned by ordinary family endpoints.
- API and UI caches include schema and pipeline compatibility keys so rollback cannot show stale V2 data over a legacy response.

### Downstream product behavior

- **Follow-up and correction:** chat context is event-aware and uses `AnalysisFactsV2`; it preserves history, multiple questions, provider identity, rerun actions, correction proposal/apply/dismiss, report regeneration, and sharing. A correction creates a versioned fact revision and invalidates named descendants rather than mutating raw V2 evidence or unrelated events.
- **Training plans and sessions:** generation, AI fallback, regeneration, extension, completion, latest-plan links, shares, session CRUD, and analysis/session links remain. Plans store their source fact hash and do not silently change when an analysis is corrected; the parent chooses regeneration.
- **Growth, history, comparison, and skills:** stable counts can span authorities, but technical deltas/trends require compatible definitions and confirmed coverage. Comparison aligns events, not just analyses. Automatic skill unlock uses versioned eligible facts; manual lock/unlock and historical milestones remain intact.
- **Memories:** existing Snowball memories, expiry, pinning, chat, and review flow remain. Technical memory suggestions use confirmed family-safe facts and require the current parent-review workflow; Shadow and uncertain evidence are excluded.
- **Monthly and annual:** monthly fact generation reads compatible facts and preserves fact hashes, editing, revisions, publishing, recycling, media, and provider provenance. Annual selection/revision/recycling and resumable PDF export consume immutable monthly/milestone snapshots and keep old exports reproducible.
- **Shares and exports:** analysis, report, chat, plan, milestone, comparison, and annual artifacts store their source schema/authority/hash/renderer where applicable. Existing URLs and generated files remain readable.

### Settings, models, and operations

Resident Services remains the management boundary for:

- parent PIN setup/verification/change and parent/child content density;
- skater identity, display name, avatar, birth year, level, and appearance/theme preference;
- Provider/API CRUD, activation, testing, encrypted keys, specialties, metrics, vote configuration, and separate legacy/V2 role mapping;
- MediaPipe fallback single-pose and task-based multi-pose status, model path/hash/version, `POSE_NUM_POSES`, active/fallback reason, and dependent-artifact invalidation;
- YOLO person model path/source/hash/existence/download state, ByteTrack and dependency readiness, candidate/target tools, V2 tracking use, and DS918+ resource result;
- current `YOLO_PERSON_MODEL_PATH`, `MEDIAPIPE_POSE_TASK_PATH`, `POSE_NUM_POSES`, and `PERSON_TRACKER_*` environment compatibility in legacy mode; V2 maps relevant choices into one typed, fingerprinted configuration and retires an option only through the preservation ledger;
- optional ReID, face, alternate detector, pose, or temporal models only as disabled/Shadow candidates until Golden, privacy, and resource gates approve them;
- health, system/storage usage, queue/resources, backup list/create/restore, retention, cleanup, and rollback.

Model configuration is operational state, not an incidental environment detail. Every active model/provider/config/prompt is fingerprinted into the stages it affects. A change invalidates only dependent V2 artifacts, remains visible in the parent UI, survives/reappears correctly after restart, and cannot silently alter a published historical artifact.

Startup and scheduled behavior are also product features: database initialization/migration, applied-correction compatibility, preset skater/memory/skill seeding, optional progress sync, archive cleanup, media retention, interrupted annual-export recovery, task shutdown, Docker/all-in-one routing, standalone-pack generation, model mounts, clean install, upgrade, and DS918+ restart all remain explicitly verified.

### Synchronized vertical delivery

V2 is a full-system refactor. Each implementation iteration ships one coherent vertical slice:

1. internal backend evidence or behavior;
2. persisted schema and API presenter behavior;
3. same-authority downstream fact consumers and jobs;
4. typed frontend contract and selector;
5. Animal Island user or parent-authorized diagnostic experience;
6. legacy/history/settings/model/data-safety compatibility behavior;
7. backend contract/dependency, frontend component/route, accessibility, visual-regression, packaging, and rollback tests.

An iteration is incomplete if a new backend state has no intentional frontend representation, if a frontend or downstream service must inspect mixed raw legacy/V2 fields, if an ordinary page exposes partially migrated engineering data, or if an existing capability loses a read/write/job/artifact/permission behavior. Backend-only shadow computation is allowed only when the same iteration adds its parent-authorized Shadow visualization, proves zero mutation of family artifacts, and keeps it absent from family endpoints.

## Golden Dataset Strategy for Limited Family Videos

### New-video-only policy

The formal Golden dataset uses only videos newly selected by the owner for this V2 evaluation. The 21 unique historical debug videos and their repeated runs are not imported, do not prefill labels, and do not contribute to any metric. They remain ordinary historical debug artifacts outside the Golden dataset.

The recommended first useful dataset contains 60-80 independently labeled action events:

- 24-32 jump events;
- 16-20 spin events;
- 12-16 step events;
- 8-12 spiral events.

This distribution is intentionally uneven because jump and spin require stronger temporal and rotation coverage. If collection cost is temporarily limiting, a 36-event pilot may start with 14 jumps, 10 spins, 6 steps, and 6 spirals, but pilot percentages are diagnostic only and cannot serve as final release claims.

For any jump or spin subtype that receives its own classifier or reported accuracy, collect at least 6-8 events before measuring it separately and target 10-15 events across multiple recording sessions. Otherwise it remains grouped under the broader action family.

### Deduplication unit

The annotation unit is one complete action event identified by source video hash and source-time interval. One source video can contribute multiple events, but all events from the same original video and recording session remain in one split.

### Split policy

- Development: approximately 60%, visible during algorithm work.
- Validation: approximately 20%, used for calibration and threshold selection.
- Frozen test: approximately 20%, used only at release gates.

Splits are grouped by original video, recording day, outfit, and rink when those relationships are known. Near-duplicate clips remain in one split.

### Layered annotation

Every Golden event receives:

- source video hash and source-time interval;
- action type and subtype if known;
- observability;
- scene strata and failure tags;
- main-skater confirmation.

Event-specific labels include:

- jump: T/A/L and airborne rotation class/count;
- spin: entry/main/exit and observed rotation interval/count where meaningful;
- step and spiral: profile-specific phase interval and representative key moment.

Tracking labels are sparse in easy regions and dense around crossings, occlusion, relock, exits, and re-entry. Pose Ground Truth is a small stratified frame subset, not every frame.

### Annotation cost policy

- The annotation UI may show a clearly separated automatic suggestion after the owner first attempts the label, but automatic output is never silently persisted as Ground Truth.
- A human confirmation creates Ground Truth and records revision and annotator.
- Ordinary samples need only several identity anchors and event moments.
- Difficult tracking intervals receive denser boxes.
- Pose annotation starts with 50-100 representative frames and grows only where metrics need it.

### Evaluation isolation

The same Golden record can contain multiple label types, but an evaluator masks the field under test:

- tracking evaluation may receive the product-required initial anchor but hides later boxes;
- automatic key-moment evaluation hides Golden T/A/L;
- rotation evaluation hides Golden turn count;
- report evaluation may consume confirmed upstream labels because it tests explanation, not detection.

## Evaluation Metrics and Initial Gates

### Tracking

- confirmed identity switches: 0 on frozen test;
- multi-skater identity accuracy: at least 95%;
- core-event confirmed coverage: at least 90%;
- false relock count;
- confirmed, uncertain, and lost coverage;
- target bbox recall and IoU;
- longest lost interval;
- crossing-conflict duration.

Missing predictions remain in the denominator. Wrong-person relock and target lost are separate outcomes.

### Pose

- wrong-person authoritative skeleton rate: 0;
- PCK@0.2 target: at least 90% on labeled usable joints;
- OKS or normalized joint error;
- joint availability by action phase;
- temporal jitter under stable motion;
- core-event pose coverage;
- measured versus interpolated contribution.

### Action events

- proposal recall: at least 98%;
- macro F1 initial gate: at least 90%, target 95%;
- high-confidence error rate: below 2%;
- per-profile and per-stratum confusion matrix;
- unknown and rejection rate.

### Key moments

- T/A/L median absolute error: at most 0.10 seconds;
- T/A/L P95: at most 0.25 seconds;
- phase completeness and refusal rate;
- separate results for observable and unobservable events.

### Rotation

- observable-sample MAE: at most 0.25 turns;
- integer/half-integer class accuracy: at least 90%;
- confidently wrong rate: below 2%;
- separate Axel/non-Axel and single/double/triple reporting;
- separate pre-air-post components and observability strata.

### Stability and operations

- repeated-analysis consistency: at least 95%;
- automatic coverage always reported with accuracy;
- legacy versus V2 outputs include pipeline, configuration, model, and prompt fingerprints;
- DS918+ memory, CPU, latency, and queue behavior pass an explicit operational gate.

Initial numeric thresholds are release gates to validate against the first real Golden baseline. If label volume cannot support a stable percentage, the gate also reports raw numerator/denominator and confidence intervals.

## Shadow Rollout

### Phase 0: Measurement and freeze

- Stop adding legacy scenario thresholds.
- Import newly selected videos, detect accidental duplicates, and build the first Golden manifest.
- Fix evaluator semantics before using it for architectural decisions.
- Freeze a legacy baseline and store its version fingerprints.
- Deliver the parent-authorized Animal Island Golden catalog, annotation, evaluator, and gate surfaces together with their backend states.

### Phase 1: Contracts and source time

- Introduce canonical types and adapters.
- Introduce `AnalysisFactsV2`, the feature-preservation registry, and same-authority downstream interfaces before any consumer switches.
- Build exact source-PTS observation streams.
- Introduce the versioned experience presenter and migrate the affected Animal Island surfaces in the same vertical slices.
- Keep ordinary family responses wholly legacy-authoritative while producing V2 diagnostics in parent-authorized tools.

### Phase 2: Tracking and pose

- Shadow identity V2 beside legacy tracking.
- Generate V2 pose only from V2-confirmed identity in shadow artifacts; ordinary family responses remain wholly legacy-authoritative.
- Passing tracking and pose gates makes those stages eligible for the complete V2 candidate; it does not switch individual fields inside an ordinary response.

### Phase 3: Events and key moments

- Add multi-event proposals and classifiers.
- Refine events on source frames.
- Shadow profile-specific key moments and compare with legacy results.
- Extend the same analysis-detail event selector, source timeline, and review inbox; do not create profile-specific parallel pages.
- Migrate event-aware chat/corrections, plan/compare selectors, growth/skill eligibility, and monthly/annual representative moments without changing historical snapshots.

### Phase 4: Rotation and A/B redesign

- Add multi-signal rotation estimation and observability.
- Adapt Path A and Path B to consume their new bounded evidence.
- Add claim-level fusion and constrain reporting.
- Complete the presenter-backed family report, pose, rotation, growth eligibility, and parent Shadow comparison views as one authority-consistent experience.
- Complete every semantic downstream consumer: follow-up, corrections, plans, compare, progress, skills, memories, monthly/annual, shares, and exports.

### Phase 5: Calibration and retirement

- Calibrate confidence and identity margins on validation data.
- Run frozen-test and DS918+ operational gates.
- Enable V2 only for selected whole analyses/cohorts, retaining whole-experience rollback to legacy.
- Remove legacy rules only after ablation shows no required benefit.
- Remove raw mixed-source reads and obsolete frontend paths only after the four-space route, historical-link, theme, responsive, and accessibility matrix passes.
- Validate Resident Services, Provider/API roles, Pose and multi-person tracker models, optional model gates, backup/restore, startup/scheduled work, Docker/all-in-one/standalone packaging, and DS918+ operations before candidate rollout.

## Error Handling and Safety

- Decoder or PTS discontinuity: mark affected intervals and prohibit physical timing estimates that span them.
- Camera-motion failure: lower motion reliability; do not silently assume a static camera.
- Identity conflict: output uncertain and request an optional additional anchor.
- Pose failure: preserve track result and mark pose-dependent claims unobservable.
- Action ambiguity: keep multiple candidates or unknown; do not force step.
- Key moment absent: return an incomplete event; do not fabricate a timestamp for schema completeness.
- Rotation aliasing: return an interval or unobservable result.
- Path A failure: continue with deterministic evidence and Path B if safe.
- Path B failure: continue with deterministic evidence and Path A if safe.
- A/B disagreement: preserve the conflict and downgrade only affected claims.
- Report provider failure: retain structured evidence so report generation can be retried without rerunning the full algorithm.
- Downstream stale source: keep the existing plan/chapter/export/chat snapshot and show that newer facts exist; regenerate only through its explicit workflow.
- Incompatible metric/action definition: exclude it from comparison, trend, milestone, or annual aggregation and state the reason.
- Shadow contamination attempt: reject the write, record an audit event, and leave the family artifact unchanged.
- Provider/model setting unavailable: surface configured versus active/fallback status, preserve legacy availability, and invalidate only dependent V2 artifacts.
- Backup/restore or migration failure: stop candidate startup safely, retain the copied/pre-migration data, and never continue with a partially migrated authority.

## Testing Strategy

- Unit tests for each canonical type, invariant, state transition, and observability policy.
- Backend schema fixtures checked against the TypeScript `AnalysisExperienceV2` contract and exhaustive selectors.
- Property tests for PTS monotonicity, coordinate transforms, and temporal ordering.
- Synthetic tests for camera pan, zoom, crossing, occlusion, left/right swap, dropped frames, and variable frame rate.
- Golden end-to-end tests stratified by scene and action profile.
- Metamorphic tests: equivalent transcode and frame-rate representations should preserve source-time events within tolerance.
- Determinism tests for repeated runs under fixed fingerprints.
- Shadow-diff tests that identify exactly which stage changed a downstream claim.
- Frontend component and route tests for legacy authority, V2 authority, Shadow isolation, historical records, multi-event selection, review tasks, growth eligibility, and rollback cache invalidation.
- Desktop, tablet, mobile, keyboard, screen-reader semantics, contrast, reduced-motion, touch-target, loading, empty, error, uncertain, and unobservable checks for every affected Animal Island surface.
- Static import-boundary tests proving migrated ordinary components cannot read raw legacy biomechanics, pose dictionaries, Path A/B payloads, or combine authorities.
- Backend dependency-boundary tests proving chat, corrections, plans, compare, growth, skills, memory, chapters, annual, share, and export services cannot bypass `AnalysisFactsV2`.
- Feature-preservation contract tests for every current frontend route/API client operation, backend route/mutation, data model, startup/scheduled job, setting/model state, generated artifact, and package entry.
- Historical snapshot tests for chat/corrections, plans, comparisons, skills, memories, published chapters, annual collections/PDFs, shares, exports, backups, and legacy routes.
- Settings/runtime tests for parent PIN and permissions, skater/profile/theme, provider secrets/slots/vote config/metrics, MediaPipe single/multi-pose, YOLO/ByteTrack/dependencies, optional model disabled/Shadow states, storage, backup/restore, and restart persistence.
- Shadow contamination tests proving no family-facing downstream row or generated artifact changes during Shadow execution.
- Production frontend build and visual-regression coverage for the four primary spaces, analysis detail, Golden, Shadow, diagnostics, and historical reports.
- Clean install, copied-database upgrade/downgrade-read, Docker/all-in-one routing, standalone-pack generation, startup/recovery/scheduler, and resource tests on the deployment-class host.

Existing legacy tests remain during migration. They are characterization coverage, not substitutes for Golden evaluation.

## Non-Goals

- Training a large detector, pose model, or foundation video model from scratch.
- Claiming population-wide accuracy from one child's videos.
- Maximizing skeleton coverage by accepting uncertain identity.
- Making a language model the authoritative source of identity or biomechanics.
- Deleting all legacy code before shadow gates pass.
- Annotating every video frame or every joint before the first V2 experiment.

## Acceptance of the Design

This design is complete when implementation can be decomposed into independently testable full-stack iterations, each backend state has an intentional Animal Island or parent-authorized diagnostic representation, every current product capability is owned by the feature-preservation registry, all semantic consumers use same-authority facts, settings/models/data-safety/package behavior is verified, historical artifacts remain readable, and no ordinary response switches to V2 authority until every required Golden, feature-parity, experience, operational, and rollback gate passes.
