# Iteration 12 profile-specific source-time moments

Status: implemented as a shadow/diagnostic vertical slice. Formal G8 is blocked because G2 is not frozen and the current G7 pilot has no confirmed validation classifications. No frozen-test run was attempted.

## Operational definitions

- Jump `takeoff`: first original source frame whose confirmed target evidence begins sustained airborne support after a confirmed ice-contact frame.
- Jump `apex`: original source frame between takeoff and landing with the highest confirmed body centre (minimum image-space `body_center_y`).
- Jump `landing`: first original source frame after sustained airborne support where confirmed ice contact returns. Absent or ambiguous contact is unavailable.
- Spin `entry/main/exit`: confirmed turning preparation, longest sustained periodic/stable-axis main interval, then confirmed release/deceleration.
- Spiral `entry/hold/exit`: confirmed extension build-up, longest sustained extension/stable-axis hold, then confirmed release.
- Step: longest sustained edge/step-complexity interval plus up to three distinct representative source moments inside it.

Definitions are versioned as `jump-tal.source-contact.v1`, `spin-phases.periodic-axis.v1`, `spiral-phases.extension-hold.v1`, and `step-sequence.edge-complexity.v1`.

## State machine and refusal rules

- Inputs must carry exact source PTS, source-frame identity, confirmed target state, and authoritative local motion/pose evidence.
- Coarse windows only bound a source-resolution search; they cannot create a stage.
- Each point/interval has its own score, observability, provenance, warnings, and competing candidates.
- Ordering is enforced by refusing the offending stage, never shifting or fabricating it.
- Missing landing, absent spin exit, incomplete spiral hold, or underpowered step representative moments remain unavailable.
- Ambiguity creates a `/review` task only when at least two preserved candidates make a parent choice meaningful.
- Semantic keyframes are recorded only as review provenance. Golden, resolved semantic, and Ground Truth fields are rejected from prediction inputs.

## Contract and product migration

- `EventMomentSet` carries expected/required/present/missing keys, completeness, definition/state-machine fingerprints, source timeline fingerprint, and `semantic_labels_consumed=false`.
- `AnalysisExperienceV2.events[].moments` is the single V2 UI source. A missing V2 set never falls back to legacy T/A/L.
- `ActionPhaseStrip` renders jump, spin, spiral, and step unions, exact source PTS/frame labels, unavailable states, synchronized markers, and seek behavior.
- Revisioned event moment proposals preserve propose/apply/dismiss, before/after snapshots, invalidation descendants, and the report-regeneration trigger.
- Migrated legacy correction/rerun proposals retain their stored T/A/L snapshot and `legacy-key-moment.v1`; reinterpretation is forbidden.
- Follow-up, monthly/annual media, compare pairs, thumbnails, pose-debug, and exports share the profile-specific source-reference selector. Published/historical legacy snapshots retain their old authority and meaning.

## G8 diagnostic

The existing pilot contains six labeled jump events, four observable. Because prediction-side confirmed profile/identity evidence is absent, all 12 observable T/A/L fields are refused. Median/P95 error is therefore not reported. Spin, step, and spiral are reported with their own definitions and do not borrow the jump threshold.
