# Golden Gate Threshold Reduction Design

**Date:** 2026-08-15
**Status:** Approved for implementation planning
**Scope:** Golden V2 collection gates, downstream sample-size requirements, status APIs, Golden UI, documentation, and compatibility behavior

## 1. Goal

Reduce the Golden labeling workload to a level that matches the real dataset already collected, while retaining the checks that protect label integrity and model safety.

The current Golden catalog becomes the fixed G1 quantity baseline. Later gates use a smaller, targeted expansion rather than the previous 36-event G1 and 60-80-event G2 requirements. Accuracy and safety thresholds remain unchanged; only sample-count requirements are reduced.

## 2. Verified Current State

The private Golden workspace was inspected on 2026-08-15 through its parent-authorized read-only views and APIs. The catalog reported:

- catalog revision 70;
- 18 source videos;
- 18 action events;
- 18 schema-valid events;
- 17 recording sessions;
- profile distribution of 10 jumps, 4 spins, 2 steps, and 2 spirals;
- complete coverage of the six existing G1 scene categories;
- no duplicate-source warnings;
- no source-frame identity issues;
- no delayed reviews completed yet;
- five ambiguous-rotation events requiring second review;
- one additional low-confidence event in the review queue;
- incomplete development, validation, and frozen-test split assignments.

The remaining G1 blockers are therefore label-governance tasks, not missing video volume.

## 3. Design Principles

1. **Freeze the quantity policy, not the dataset.** G1 remains fixed at 18 videos and 18 valid events even if more Golden data is added later.
2. **Preserve label integrity.** Deduplication, source-frame identity, split grouping, ambiguous-label review, and revision history remain mandatory.
3. **Expand only where coverage is weak.** G2 should add spin, step, and spiral events instead of accumulating more already-well-covered jumps.
4. **Keep safety and accuracy targets.** Lower sample counts must not weaken wrong-person, identity, timing, classification, rotation, or repeatability thresholds.
5. **Expose small-sample uncertainty.** Every gate result reports its denominator, coverage, and confidence information and distinguishes limited-sample evidence from broad validation.
6. **Version the policy.** Existing evidence remains interpretable under the gate policy that produced it.

## 4. Gate Policy Model

Introduce a single backend policy module as the authoritative source for collection thresholds. Backend evaluators, API responses, frontend displays, tests, and documentation consume the same policy values rather than duplicating literals.

The new policy is identified as `golden-gate-policy.v2` and contains:

- policy version and effective date;
- G1 source-video, valid-event, profile, scene, session, and review requirements;
- G2 total-event range and per-profile ranges;
- Pose representative-frame range;
- subtype reporting minimum and target;
- evidence-confidence classification rules.

Policy values are code-owned and versioned with the application. They are not automatically recalculated from the live catalog. Changing them later requires an explicit new policy version.

## 5. G1: Current-Catalog Baseline

G1 becomes a fixed, limited-sample Golden pilot gate with these requirements:

| Requirement | New threshold |
|---|---:|
| Source videos | At least 18 |
| Action events | At least 18 |
| Schema-valid and source-frame-valid events | At least 18 |
| Jump events | At least 10 |
| Spin events | At least 4 |
| Step events | At least 2 |
| Spiral events | At least 2 |
| Recording sessions | At least 5 |
| Delayed relabel reviews | At least 2 |
| Existing scene categories | At least 1 event in each category |
| Duplicate sources or near-duplicate events | None |
| Ambiguous rotations | Every applicable event independently reviewed |
| Frozen-test crossing events | Every applicable event independently reviewed |
| Split grouping | Every event assigned; no source, group, or session crosses splits |

The profile minimums deliberately match the verified current distribution. Additional events do not increase the target and cannot compensate for a missing profile minimum.

The sixth review-queue item, which is low-confidence but not an ambiguous rotation, remains visible and should be resolved as ordinary label-quality work. It does not create a new global video-count requirement.

G1 remains diagnostic and calibration-oriented. Passing it authorizes threshold calibration and end-to-end pilot evaluation, not a broad production-accuracy claim.

## 6. G2: Targeted Small Expansion

G2 becomes a frozen limited-sample baseline containing 24-30 valid events:

| Profile | Allowed range |
|---|---:|
| Jump | 10-14 |
| Spin | 6-8 |
| Step | 4-5 |
| Spiral | 4-5 |
| Total | 24-30 |

All total and profile constraints must pass together. The total cap of 30 takes precedence when the upper profile bounds could otherwise sum above 30.

Starting from the current 10/4/2/2 distribution, the minimum G2 expansion is approximately six distinct events: two spins, two steps, and two spirals. These should come from real actions and should prioritize useful validation or frozen-test coverage rather than adding more jumps solely to raise the total.

G2 retains the following safeguards:

- development, validation, and frozen-test splits are all present;
- source, grouping, and recording-session membership never crosses splits;
- the frozen membership and dataset fingerprint are immutable without an explicitly authorized dataset revision;
- the legacy pipeline fingerprint is recorded;
- the legacy baseline is recorded against the exact frozen dataset fingerprint;
- duplicate and schema-invalid events are not eligible;
- no automatic suggestion becomes Ground Truth.

## 7. Later Gates and Supporting Sample Requirements

### 7.1 Pose labels

The initial Pose target changes from 50-100 to 24-40 representative source frames across the whole dataset.

The selection must still cover, where available:

- action cores;
- near and small/distant subjects;
- clear and blurred/compressed frames;
- partial occlusion;
- front and back views;
- multi-skater crossings.

Frames are selected for coverage, not evenly allocated to every event. More frames are added only when failure analysis or uncertainty requires them.

### 7.2 Separately reported subtypes

A jump, spin, step, or spiral subtype may receive a separate metric only when it has at least four eligible samples. Six samples is the recommended target.

With fewer than four eligible samples, the subtype is included in its parent action family and no standalone accuracy claim is shown.

### 7.3 G3-G12

G3-G12 do not introduce additional generic video-count or event-count requirements. They evaluate the frozen G2 dataset and any explicitly defined applicable subsets.

Existing quality thresholds remain unchanged, including:

- zero confirmed identity switches where currently required;
- zero authoritative wrong-person skeletons;
- action-proposal recall and classification targets;
- T/A/L and profile-moment timing tolerances;
- rotation error and confidently-wrong limits;
- unsupported-claim protections;
- repeatability and unexplained-stage-drift requirements;
- operational, privacy, restart, rollback, and resource checks.

A result that passes these thresholds on the reduced dataset is classified as `limited_sample_candidate_pass`, not broad or high-confidence validation. A result with too few applicable examples is `insufficient_sample`, not passed.

## 8. API and Data Contracts

### 8.1 G1 progress

The G1 progress response adds policy metadata and separates video and event requirements:

- `gate_policy_version`;
- `source_video_count` requirement and progress;
- `event_count` requirement and progress;
- policy-derived profile, scene, session, validation, review, grouping, and duplicate checks;
- `evidence_scope`, with a limited-sample value for this policy.

Existing fields may remain during a compatibility period, but their targets must come from the policy rather than hard-coded values.

### 8.2 Sanitized export

The sanitized export includes the gate policy version and the policy-derived G1 requirements. It continues to exclude paths, filenames, frames, identities, and private labels.

### 8.3 G2 status and freeze

The G2 status response exposes:

- `gate_policy_version`;
- the 24-30 event range;
- all four profile ranges;
- actual split and profile counts;
- readiness blockers;
- frozen policy version after freeze.

Freeze artifacts persist the gate policy version so future policy changes cannot retroactively reinterpret an old freeze.

The deployed G2 status route currently returns HTTP 404 despite the route existing in the repository. Implementation must diagnose and restore route availability before treating G2 status verification as complete. No implementation or verification step automatically freezes the dataset; freeze remains an explicit, confirmed owner action.

## 9. Frontend Behavior

The Golden workspace reads all target values from API responses. It must not contain display literals for 36, 60-80, or 50-100.

The G1 dashboard shows:

- videos as `current / 18`;
- valid events as `current / 18`;
- the 10/4/2/2 profile minimums;
- session, scene, split, duplicate, delayed-review, and second-review status;
- specific remaining governance tasks instead of requesting unnecessary new videos;
- a visible limited-sample diagnostic label.

Once the current catalog has valid split assignments, two delayed reviews, and all applicable second reviews, it can become G1-ready without adding videos.

The G2 card shows the 24-30 total range, per-profile ranges, and the smallest useful additions based on current gaps. With the verified catalog, it should recommend spins, steps, and spirals rather than jumps.

## 10. Compatibility and Historical Evidence

- Existing videos, labels, revisions, review attestations, and source identities are not migrated or rewritten.
- Existing evaluation reports retain their original policy interpretation.
- New reports and freeze artifacts persist `golden-gate-policy.v2`.
- A report without a policy version is interpreted as the legacy policy and is never retroactively promoted by the new thresholds.
- Cached progress or derived evaluation artifacts are invalidated when their inputs or policy version change.
- Current privacy and authorization boundaries remain unchanged.

## 11. Error Handling

- Missing or invalid policy configuration fails closed and prevents gate readiness.
- A catalog below either the video or valid-event minimum remains collecting.
- Missing profile coverage cannot be compensated by other profiles.
- Unassigned or cross-split groups remain explicit blockers.
- Missing required review attestations remain explicit blockers.
- Applicable metric subsets below their declared minimum return `insufficient_sample` and retain raw counts.
- G2 route unavailability is reported as a service/configuration error, not as a collecting or passing status.
- Fingerprint or frozen-membership mismatches prevent baseline recording and require an explicitly authorized revision.

## 12. Testing Strategy

### Backend policy and G1 tests

- The verified shape of 18 videos, 18 valid events, and profile counts 10/4/2/2 satisfies the quantity and profile checks.
- Seventeen videos, seventeen valid events, or any missing profile minimum fails G1.
- Duplicate sources, overlapping duplicate events, invalid source-frame identities, or schema-invalid events fail G1.
- Fewer than two delayed reviews fails G1.
- Every ambiguous rotation and applicable frozen crossing requires its corresponding independent review.
- Missing or inconsistent split assignments fail G1.
- Additional events do not increase policy targets.

### G2 tests

- A 24-event 10/6/4/4 dataset can become freeze-ready when all non-count checks pass.
- Total counts below 24 or above 30 fail.
- Each profile below its minimum or above its maximum fails.
- Valid profile ranges whose combined total exceeds 30 still fail the total cap.
- Missing required splits, cross-group assignments, fingerprint mismatch, or changed frozen membership blocks freeze or baseline recording.
- Freeze artifacts and public status contain `golden-gate-policy.v2`.

### Later-gate tests

- Pose progress uses 24-40.
- A subtype with three eligible samples is grouped and marked insufficient for standalone reporting.
- A subtype with four eligible samples may display a limited-sample standalone metric.
- Passing G3-G12 output uses limited-sample candidate language and includes raw denominators.
- Missing applicable values never become zero or success.

### Frontend and integration tests

- Golden components render policy-provided values and contain no hard-coded legacy quantity text.
- Current-catalog fixtures show governance blockers without recommending additional videos for G1.
- G2 fixtures recommend the current profile gaps.
- Legacy reports remain visibly associated with the legacy policy.
- G2 status routing is exercised against the assembled backend application.
- Run affected backend tests, frontend component tests, and the production frontend build.

## 13. Documentation Updates

Implementation updates the owner labeling guide, master V2 design/plan references, development notes, sanitized templates, and evidence messages that still describe 36-event G1, 60-80-event G2, 50-100 Pose frames, or the old subtype minimums.

Historical evidence files remain immutable when they describe what was true at the time. New documentation explains that they use the legacy gate policy rather than rewriting their original claims.

## 14. Out of Scope

- Lowering accuracy, safety, privacy, authorization, or operational thresholds.
- Automatically freezing G2.
- Automatically completing or fabricating review attestations.
- Reassigning split membership without owner-reviewed data decisions.
- Rewriting historical evaluation results.
- Training a large supervised model from the reduced dataset.

## 15. Success Criteria

The change is successful when:

1. the current 18-video catalog is recognized as meeting G1 quantity, profile, session, scene, duplicate, schema, and source-frame requirements;
2. G1 clearly reports only the real remaining split and review work;
3. G2 consistently enforces 24-30 total events and the approved profile ranges;
4. Pose and subtype requirements use the approved reduced counts;
5. G3-G12 retain their quality thresholds and expose limited-sample evidence honestly;
6. frontend, backend, exports, artifacts, tests, and documentation consume a versioned central policy;
7. legacy artifacts retain their original interpretation;
8. no implementation or test action freezes the private dataset without explicit owner confirmation.
