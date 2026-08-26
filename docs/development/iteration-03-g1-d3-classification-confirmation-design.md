# Iteration 3 G1-D3 classification confirmation design

- Status: approved for implementation
- Date: 2026-08-26 (Asia/Shanghai)
- Authorized iteration: Iteration 3 G1-D3 only
- Release claim: false

## Objective

Replace the limited-sample source-family calibration with one unified, label-agnostic source-evidence classification confirmation policy. The policy operates independently on every existing localized proposal, supports multiple proposals on one source, and preserves uncertainty rather than forcing a family.

## Scope boundaries

- Consume only proposal-local source observations and derived physical features already present in `ActionClassificationEvidence`.
- Do not read Golden labels, evaluator targets, event identities, labeled intervals, resolved moments, or rotation labels.
- Do not modify tracker or identity-bridge behavior.
- Do not tune or evaluate profile moments or rotation.
- Do not rerun the formal Pilot or enter G2/Iteration 4.
- An `unlocalized_observability_envelope` is never classified or confirmed.

## Decision model

The existing four family scorers remain responsible for ranking `jump`, `spin`, `step`, and `spiral`. D3 adds one shared confirmation policy after ranking; it does not add family-specific source or event branches and does not globally lower profile thresholds.

For every localized proposal, the policy evaluates:

1. proposal-local observability and identity consistency;
2. exact source-time sample count and temporal span;
3. winning score and margin over the runner-up;
4. sustained, directly observed physical support for the winning family;
5. semantic conflict and broad-localization exclusions.

The physical support channel is selected from the same proposal-local evidence contract:

- jump: airborne/contact transition support;
- spin: sustained periodic turning support;
- spiral: sustained extension support;
- step: sustained step/edge complexity support.

The same policy thresholds apply to all families. A candidate below its existing family confirmation threshold may be upgraded only when physical support, temporal persistence, observability, identity consistency, score, and margin all pass the shared confirmation contract. Existing confirmations remain confirmations. A weak winner, close family competition, semantic conflict, insufficient duration, or insufficient identity/pose evidence cannot be upgraded.

## Output states

- `confirmed`: an existing confirmation or a D3 physical-confirmation upgrade.
- `ambiguous`: a top family exists, but confirmation evidence is insufficient or conflicting.
- `unknown`: no defensible family claim is available.
- refusal: represented compatibly as `state="unknown"` plus a non-empty `refusal_reason`; the evaluator three-state wire contract is unchanged.

Every classification records the confirmation policy version, decision reason, and whether the upgrade contributed. These fields participate in the classifier fingerprint.

## Baseline and diagnostics

`classify_action()` receives an explicit switch that disables the D3 confirmation upgrade. With the switch disabled, stored v1.18 classification evidence must reproduce the pre-D3 classification payloads exactly.

A D3 diagnostic consumes only stored proposal-local classification evidence and recorded classification payloads. It reports baseline reproduction, before/after states, multi-proposal behavior, refusal counts, and a deterministic label-free fingerprint. It explicitly records that Golden labels, moments, rotation, and the formal Pilot were not invoked.

The diagnostic may measure confirmation-state changes but must not claim class accuracy, Golden recall, downstream moment quality, rotation quality, or a gate pass.

## Test and acceptance strategy

Implementation follows test-first red/green cycles. Coverage includes:

- strong sustained physical evidence can upgrade a near-threshold localized proposal;
- the same confirmation policy works for all four families;
- multiple proposals on one source are classified independently;
- unlocalized fallback returns unknown with an explicit refusal reason;
- single-frame spikes, short spans, camera-pan residuals, missing pose/identity consistency, weak step-like travel, semantic conflict, and small margins do not confirm;
- disabling the upgrade preserves the pre-D3 result;
- diagnostic output is invariant to Golden-shaped fields and source/proposal ordering;
- both independent v1.18 observation-bridge artifacts produce deterministic, label-free results.

Completion requires focused regression, `git diff --check`, sanitized documentation, and a strict D3 file allowlist. Private runtime artifacts remain outside Git.
