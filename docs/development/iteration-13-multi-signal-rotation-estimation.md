# Iteration 13 multi-signal rotation estimation

Status: implemented as a V2 shadow/diagnostic vertical slice. Formal G9 remains blocked: G2 is collecting with no frozen dataset fingerprint, the checked Golden runtime contains no rotation labels, and the Iteration 11 validation diagnostic has zero confirmed classifications. No frozen-test G9 run was attempted.

## Authoritative definition

- Jump value: airborne body rotation on exact source PTS, versioned as `airborne-body-rotation.source-pts.v1`.
- Spin value: observed rotation in the localized spin-main phase.
- Pre-takeoff and post-landing continuation are separate phase estimates and never added to the airborne result.
- Competition naming is a separate field. Axel convention is applied only when subtype support is at least `0.75`; it never changes the physical airborne estimate.
- Historical `estimated_rotations` and `rotation_rps` remain legacy-labeled and are not migrated into the V2 bucket.

## Signals and fusion

Independent evidence providers are shoulder orientation, hip orientation, torso appearance periodicity, silhouette orientation, limb appearance periodicity, and target-crop optical-flow rotation. Every signal retains likelihoods, reliability, warnings, sample count, source-PTS duration, and provenance.

Fusion requires at least two independent signal families. One signal is capped at `0.45` contribution mass; when only two signals survive, the remaining mass stays explicitly unassigned as uncertainty instead of being renormalized back into either signal. Low-confidence shoulders, left/right swaps, changing arms, occlusion, camera roll, sparse PTS, aliasing, and conflicting turn hypotheses can only reduce support or produce a range/refusal; none can dominate the result.

## Contract and experience

`rotation-estimate.v2` is an exact/range/unobservable discriminated contract with value/range/class/confidence, refusal reason, convention, phase separation, evidence summary, estimator fingerprint, and source-timeline fingerprint. Missing evidence returns `画面不足，暂不判断`; it never reads legacy rotation fields.

The diagnostic experience projects the estimate on each jump/spin event, exposes versioned V2 rotation facts, and creates exact-PTS rotation review tasks for ambiguous ranges. Summary and key-moment UI distinguish airborne rotation from competition naming and never round an interval.

## Golden and downstream

Golden rotation labels are normalized to `rotation-label.v2`: clear stores exact, partial stores an interval, otherwise unobservable. Labels explicitly record airborne body rotation, competition naming, or observed spin rotation. Ambiguous rotation review requires a different reviewer, source-frame stepping, a bounded source-PTS interval, a matching definition, and the current event revision.

Comparison, progress, monthly, and annual selectors admit only confirmed facts with matching definition, unit, convention, and compatibility group. Ranges/refusals remain context only.

## G9 protocol

The evaluator reports raw N, observable N, clear-exact N, coverage/refusal with Wilson intervals, MAE with deterministic bootstrap CI, integer/half-integer class accuracy, confidently-wrong rate, convention mismatches, and single/double/triple-or-more, Axel/non-Axel, observability, and supplied strata. Exact-label coverage must be complete for thresholds to count; unobservable or range rows cannot be hidden or rounded.

Current diagnostic evidence has raw N `0`; therefore all metrics and confidence intervals are unavailable, coverage is `0/0`, and no threshold claim is made.
