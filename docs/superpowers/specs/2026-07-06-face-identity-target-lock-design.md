# Face Identity Target Lock Design

Date: 2026-07-06

## Goal

Add a local-only face identity assist layer for the skating analyzer. The feature must help with three workflows:

- Identify which child a newly uploaded video likely belongs to.
- Improve main-skater target selection in multi-person rink videos.
- Help person tracking recover the same skater after occlusion or temporary loss.

Face identity is an assistive signal, not an authority. Existing target lock, motion continuity, body detection, appearance relock, and parent confirmation remain the primary safety rails.

## Constraints

- The system may store face embeddings locally, but must not upload face data or embeddings to external services.
- Deployment target is Synology/NAS/Docker with CPU-first execution.
- The family has two child skater profiles today, and the design must support more profiles later.
- Face features must follow the person profile. Each `Skater` owns its own face profile and embedding history.
- Face profile updates happen only when a parent explicitly chooses to update a child's face profile.
- The UI must work well on phone, tablet, and desktop.

## Recommended Approach

Use a local face identity service that plugs into the existing `target_lock` and `person_tracker` pipeline.

The service detects faces in selected frames, creates local embeddings, compares them against each enabled `Skater` face profile, and returns confidence diagnostics. Those diagnostics influence ranking and review decisions, but do not bypass low-confidence protections.

This approach covers upload identity, target selection, and relock recovery while keeping privacy and mis-learning risks controlled.

## Child-Scoped Face Profiles

Each child profile gets its own face data.

For example:

- Skater: Tantan
  - Own face profile.
  - Own embedding versions.
  - Own quality summary and last-updated timestamp.
- Skater: Zhaozao
  - Separate face profile.
  - Separate embedding versions.
  - Separate quality summary and last-updated timestamp.

When a video is uploaded without a selected child, the system compares visible faces against all enabled skater face profiles and returns ranked local matches.

Example result:

- Tantan: 0.86
- Zhaozao: 0.42
- Decision: likely Tantan if the absolute score and margin are high enough.

If scores are close, the face is low quality, or no face is visible, the system returns `uncertain` and asks the parent to confirm instead of auto-binding the analysis.

## Profile Creation And Updates

Initial profile creation supports both:

- Parent uploads several clear face photos for a child.
- Parent uses confirmed historical videos to extract face samples.

Updates are manual. A parent enters a specific child's profile and chooses "Update face profile". New samples are added only to that selected child after quality checks and parent confirmation.

The system must never automatically add a new face embedding to a child's long-term profile during normal analysis. This prevents a wrong target lock or another child in frame from polluting the profile.

Old embeddings stay available but can be weighted lower over time. Newer parent-confirmed embeddings get higher weight, which lets the profile adapt as the child grows while preserving older recognition coverage.

## Backend Architecture

Add a local `face_identity` service with these responsibilities:

- Detect faces in selected frames or within candidate person boxes.
- Generate face embeddings with a local CPU-friendly model.
- Compare embeddings against enabled `Skater` face profiles.
- Return match scores, quality reasons, and uncertainty flags.
- Refuse low-quality inputs instead of forcing a match.

The service should be optional and fail-soft. If the model is unavailable, dependencies are missing, or CPU budget is exceeded, analysis continues with the existing target lock pipeline.

## Data Model

Add `skater_face_profiles`:

- `id`
- `skater_id`
- `is_enabled`
- `model_name`
- `model_version`
- `embedding_count`
- `quality_summary`
- `last_updated_at`
- `created_at`
- `updated_at`

Add `skater_face_embeddings`:

- `id`
- `skater_id`
- `profile_id`
- `embedding`
- `source_type` such as `photo` or `video`
- `source_analysis_id`
- `source_frame_id`
- `quality_score`
- `quality_flags`
- `captured_at`
- `confirmed_at`
- `is_enabled`
- `created_at`

Analysis results may store lightweight diagnostics in `target_lock` or a related diagnostics object:

- `face_identity_status`
- `matched_skater_id`
- `matched_score`
- `runner_up_skater_id`
- `runner_up_score`
- `score_margin`
- `quality_flags`
- `decision_reason`

Raw face crops should not be stored long term by default. If debug crops are useful, keep them behind debug mode or short-lived cache policy.

## Upload Identity Flow

When a user uploads a video:

1. If a `skater_id` is selected, use that skater's face profile as an assistive identity hint.
2. If no `skater_id` is selected, compare visible faces against all enabled skater profiles.
3. If one skater has a high score and a clear margin, suggest that skater in the UI.
4. If the result is uncertain, ask the parent to choose.
5. If no face is visible, continue without identity assistance.

The system should not auto-bind a video to a child unless configured absolute-score and score-margin gates are met. Numeric values are model-specific and must live in backend configuration so they can be calibrated with local evaluation data.

## Target Lock Flow

Current YOLO/person candidates remain the base.

For each candidate:

1. Try to detect a face inside the candidate person box.
2. Compare the face embedding to the selected skater, if one is known.
3. Add an identity bonus when the candidate matches the selected skater.
4. Add a conflict flag when the candidate looks more like another skater profile.
5. Do not penalize a candidate only because no face is visible.
6. Keep existing manual review behavior for low-confidence or ambiguous cases.

This means face identity can help choose between two visible children, but it cannot override strong target-lock uncertainty.

## Relock Recovery Flow

When the person tracker loses the target and tries to reacquire:

1. Keep motion continuity, bbox geometry, and appearance relock as the primary checks.
2. If a candidate has a face matching the selected skater, allow a modest relock bonus.
3. If a candidate clearly matches another child profile, reject relock or require manual review.
4. If no face is visible, fall back to existing relock behavior.

This prevents face identity from breaking videos where the child is facing away, distant, or occluded.

## UI Entrances

### Child Profile Entry

Each child profile page gets a "Face Profile" entry. This is the main management surface.

It shows:

- Whether face assist is enabled for this child.
- Last update time.
- Number of active confirmed embeddings.
- Quality state such as good, needs more samples, or outdated.
- Actions for uploading photos, updating from historical video, disabling face assist, and reviewing samples.

The page must clearly show which child is being edited so a parent does not add Tantan's samples to Zhaozao's profile.

### Upload Entry

On upload:

- If a child is selected, show whether face assist is available for that child.
- If no child is selected, show a local suggestion such as "Likely Tantan" only when the result is confident.
- If uncertain, show a simple parent confirmation step.

### Target Confirmation Entry

The existing target selection page remains the parent-visible recovery point.

Candidate cards can show simple identity labels:

- "Looks like Tantan"
- "Face not visible"
- "Identity uncertain"
- "Possible profile conflict"

The UI should not expose raw embeddings or technical details.

Manual target selection may offer "Use this video to update this child's face profile", but it must be a deliberate parent action and must lead through confirmation.

### Settings Entry

Global settings should include privacy and availability controls:

- Local-only face assist status.
- Model availability.
- Disable all face assist.
- Brief storage explanation.

The primary create/update workflow still lives under each child profile, not only in global settings.

## Three-Form-Factor UI

### Phone

- Large touch targets.
- One primary action per step.
- Face profile summary appears on the child card and profile screen.
- Upload and target confirmation use short, parent-readable identity hints.

### Tablet

- Child list can appear beside the selected child face profile details.
- Update/review workflows can use a two-column layout when space allows.

### Desktop

- Full management view with child profiles, embedding sources, quality state, enable/disable controls, and update history.
- Diagnostics can be visible in parent/debug contexts without overwhelming normal usage.

## Quality And Safety Rules

The face identity service returns `uncertain` instead of forcing a match when:

- The face is too small.
- The frame is blurry.
- The face is heavily occluded.
- The face angle is too extreme.
- Multiple faces overlap a candidate box.
- Two skater profile scores are too close.
- The absolute score is below threshold.
- The model is unavailable.

Recommended statuses:

- `disabled`
- `model_unavailable`
- `no_face`
- `low_quality`
- `matched`
- `uncertain`
- `profile_conflict`

## Error Handling

- No face found: continue with existing analysis.
- Local model missing: show face assist unavailable, continue analysis.
- CPU timeout: skip face identity for that analysis and log a diagnostic.
- Two children score close together: require parent confirmation.
- Selected skater conflicts with visible face: lower auto-lock confidence and require target review.
- Parent tries to update one child with samples matching another child: block the update by default and ask the parent to reselect the correct child profile or provide clearer samples.

## Testing Strategy

Backend tests:

- Face profiles are isolated by `skater_id`.
- Updating Tantan does not change Zhaozao's embeddings.
- Upload without `skater_id` can return a confident suggested child.
- Close scores return `uncertain`.
- No face visible does not regress target lock.
- Candidate matching selected child receives a bounded identity bonus.
- Candidate matching another child produces a conflict flag.
- Relock bonus is applied only when existing geometry and continuity checks are plausible.
- Model unavailable path preserves existing analysis behavior.

Frontend tests:

- Child profile face entry is reachable on phone, tablet, and desktop layouts.
- Parent can upload photos for the selected child only.
- Target confirmation candidate cards show identity hints without technical details.
- Uncertain identity requires parent confirmation.
- Face assist can be disabled from the correct child profile and global settings.

Integration or golden tests:

- Two-child same-rink video does not auto-bind to the wrong child.
- Existing target-lock behavior does not degrade when faces are absent.
- Manual update from historical video writes embeddings only to the selected `Skater`.

## Open Implementation Notes

- Prefer a CPU-friendly local model and make the model layer swappable.
- Store embeddings compactly and version them by model name/version so future models can coexist.
- Keep thresholds configurable through backend constants or environment settings; initial numeric values should be chosen during implementation after the local model is selected.
- Use feature flags for rollout so the existing pipeline can remain default during early testing.

## Non-Goals

- Do not build cloud face recognition.
- Do not auto-update long-term child face profiles during normal analysis.
- Do not make face identity the sole authority for target lock.
- Do not expose raw embeddings in normal UI.
