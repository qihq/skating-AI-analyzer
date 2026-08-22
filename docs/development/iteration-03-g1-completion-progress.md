# Iteration 3 G1 completion progress

- Progress document version: `g1-completion-progress.v1.9.0`
- Updated: `2026-08-22` (Asia/Shanghai)
- Authorized iteration: Iteration 3 only
- Gate policy: `golden-gate-policy.v2`
- Evidence scope: `limited_sample`
- Release claim: `false`
- Current gate conclusion: `g1_formal_loop_complete_metrics_failed`

This is the live, sanitized progress record for completing the remaining G1 evaluator loop. Private video paths, source hashes, event IDs, frames, labels, and per-event diagnostics remain outside Git.

## Fixed constraints

- [x] Work remains in the V2 worktree and branch.
- [x] No production deployment, merge, push, G2 freeze, or Iteration 4 work is authorized.
- [x] Golden labels, resolved moments, rotation labels, and evaluator targets are not prediction inputs.
- [x] Existing user changes under `ai_skating_analysis_pack/**` are preserved and are not part of this slice.
- [x] New diagnostic artifacts remain private and `release_claim` remains false.

## Real-time checklist

### A. Source-only proposal/classification repair

- [x] Added target-outside optical-flow camera compensation with reliability-aware weighting.
- [x] Removed whole-frame motion fallback when camera estimation is unreliable.
- [x] Tightened source-only physical admission gates for jump, spin, spiral, and step proposals.
- [x] Required sustained raised-leg extension evidence for spiral classification.
- [x] Tightened proposal gap and padding so continuous ordinary skating does not become a broad event.
- [x] Changed moment adjacency to sampled timeline order instead of consecutive source-frame numbers.
- [x] Recorded implementation versions `diagnostic-source-only-evidence.v2` and `profile-spiral-temporal.v2`.

### B. Focused verification

- [x] Focused source-evidence, proposal, profile-moment, and action-classification suite passed: `51 passed`.
- [x] One real redacted source was rerun from the original video without prediction-side Golden fields.
- [x] The real-source run produced one confirmed spiral profile with a narrow primary proposal.
- [x] Spiral entry, hold, and exit moments were all confirmed and the moment set was complete.
- [x] Non-primary step candidates remained ambiguous and were excluded from the formal profile result.
- [x] Rotation consensus and airborne-transition absence remained explicit rejection evidence.
- [x] The private diagnostic JSON was hashed locally; the hash is intentionally not committed here.
- [x] Added a label-agnostic adapter policy for the revision-95 source distribution: 16 single-event sources produce predictions, the one two-event source is skipped as a whole, and its two events remain missing predictions in the evaluator denominator.
- [x] Re-ran the adapter and evaluator matching tests: `22 passed`.
- [x] Completed a private source-only evaluator diagnostic for action, key moments, and rotation without tracking/pose claims. It produced 16 predictions for 18 events, proposal recall `1/18`, class accuracy `3/18`, key-moment coverage `8/43`, and rotation coverage `0/13`; all 18 events retained at least one failure.
- [x] Recorded the private dry-run deterministic fingerprint and artifact hash outside Git.

### C. Remaining Iteration 3 work

- [x] Complete static leakage and contract checks for the current source-only adapter and artifact.
- [x] Rerun the source-only diagnostic across all 18 real G1 source videos.
- [x] Review the first-pass aggregate for runtime failures, profile coverage, wrong-person/relock risks, moments, rotation refusals, and deterministic version fields.
- [ ] Resolve the prediction-quality blocker before any later frozen candidate: 18/18 sources ran successfully, but only five sources produced a confirmed profile and thirteen remained unknown; the formal Pilot remains failed diagnostic evidence.
- [x] Verify current private catalog revision, grouped split, duplicate/source-frame/schema checks, two delayed reviews, and all applicable independent second reviews.
- [x] Run the Iteration 3 evaluator/privacy/API/UI focused regression suite and production frontend build.
- [x] Run a formal evaluator dry-run only after the 18-source diagnostic is accepted.
- [x] Run the parent-authorized Pilot Evaluator only when every G1 governance prerequisite is verified.
- [x] Update sanitized G1 evidence and feature-preservation ledger.
- [x] Complete the final Iteration 3 regression, privacy, ledger, package-generation, JSON, and diff verification.
- [x] Created the independent Iteration 3 commit from an explicit 26-file allowlist; formal metric failure remains diagnostic evidence and is not rewritten as a pass.

### D. Final verification evidence

- [x] Final Analysis V2 suite passed: `362 passed`.
- [x] Modified legacy profile/video service regression passed: `33 passed`.
- [x] Full frontend suite passed: `60 files`, `166 tests`.
- [x] Production frontend build passed: TypeScript plus Vite, `310 modules transformed`.
- [x] Repository-wide backend run excluding the mutating AI-pack rebuild test completed with `1664 passed`; three shared-process route/database state failures each passed in a fresh isolated process (`3/3`).
- [x] AI-pack rebuild was verified in an isolated temporary copy: `62 files copied`, `0 missing`, and all `35` generated top-level V2 modules clean-imported. The user's `ai_skating_analysis_pack/**` worktree changes were not modified or selected for commit.
- [x] Final ledger/privacy/timebase/dependency/source-adapter/classifier regression passed: `53 passed`.
- [x] Feature-preservation ledger regenerated deterministically with `725` entries and fingerprint `fe49cd649d7ea38f91f9420e2932c0bd2f3343de26b378c7f2d44e4cd144a678`.
- [x] Sanitized evidence and ledger JSON parsing, selected-file private-literal scan, and `git diff --check` passed.
- [x] Removed the local private diagnostic artifact hash from committed evidence; formal and local evaluator result fingerprints remain aggregate deterministic evidence.

## Version history

- `g1-completion-progress.v1.0.0`: established the live checklist and recorded the completed focused tests plus the first real-source source-only verification.
- `g1-completion-progress.v1.1.0`: recorded the authority/previous-iteration audit and the 75-test leakage, evaluator-contract, privacy, proposal, classification, moment, and source-evidence verification pass.
- `g1-completion-progress.v1.2.0`: recorded the completed 18-source real diagnostic. All sources completed without runtime failure under `diagnostic-source-only-evidence.v2`; confirmed outputs were one spiral, three jump, and one spin, while thirteen sources remained unknown. Formal evaluator submission remains blocked pending revision-95 governance verification and prediction recall diagnosis.
- `g1-completion-progress.v1.3.0`: verified the parent-authorized revision-95 aggregate. G1 governance is `ready_for_evaluator`: 18 sources, 18 events, 17 sessions, 10/4/2/2 profiles, complete required scene coverage, grouped splits, no duplicate or source-frame issues, five qualifying delayed reviews, and no outstanding applicable independent second review. The previous formal run is a metric failure rather than an execution failure: proposal recall 0/18, action class accuracy 8/18, key-moment coverage 0/43, rotation coverage 0/13, and tracking correct localization 42/77. No new formal run was submitted.
- `g1-completion-progress.v1.4.0`: added and verified the no-leakage multi-event alignment policy. The source-only diagnostic now skips the one two-event source instead of consulting Golden intervals or profiles, so both events remain missing in the denominator. The private action/moment/rotation dry-run completed deterministically with 16 predictions for 18 events, but proposal recall `1/18`, class accuracy `3/18`, moment coverage `8/43`, rotation coverage `0/13`, and 18/18 failed events keep formal evaluator submission blocked.
- `g1-completion-progress.v1.5.0`: completed the Iteration 3 evaluator/store/adapter regression (`35 passed`), Golden dashboard and TypeScript contract regression (`13 passed`), and production frontend build (`tsc` plus Vite). The local source-only dry-run is accepted as a truthful preflight rather than a passing metric claim; its failures remain unchanged and will be preserved in the parent-authorized formal Pilot result.
- `g1-completion-progress.v1.6.0`: submitted the parent-authorized formal G1 Pilot against Golden revision 95 after confirming `ready_for_evaluator`. The run completed with `run_scope: formal_g1`, `gate_policy_version: golden-gate-policy.v2`, `evidence_scope: limited_sample`, and `release_claim: false`. Status is truthfully `failed`: proposal recall `0/18`, class accuracy `3/18`, key-moment coverage `8/43`, rotation coverage `0/13`, and 18/18 failed events. The formal result fingerprint is `554f387e42cbd1cc5d22f45eb23b9b5e2fbf77981efdb4178c2011dffb5ec2c4`. The identical prediction payload produced proposal recall `1/18` under the locally repaired matching semantics, so the online service is still on the older evaluator behavior; no prediction windows were widened to compensate.
- `g1-completion-progress.v1.7.0`: committed no private data, but added sanitized G1 evidence at `docs/evaluation/v2/iteration-03-g1-pilot-evidence.json` and regenerated the preservation ledger. All 19 Iteration 3 ledger entries are now `verified`; the inventory contains 725 entries with a current fingerprint. The combined Golden/evaluator/privacy/ledger verification passed (`42 passed`), the sanitized evidence privacy scan passed, JSON parsing passed, and `git diff --check` passed. G1's formal loop is complete with failed limited-sample metrics; no Iteration 4, deployment, merge, push, or release claim is authorized.
- `g1-completion-progress.v1.8.0`: completed final pre-commit verification. Analysis V2 passed `362` tests, modified legacy services passed `33`, the frontend passed `166` tests across `60` files, production build transformed `310` modules, and an isolated AI-pack rebuild copied `62` files with `0` missing and clean-imported `35` V2 modules. The broad backend run passed `1664` tests; its three shared-process state failures each passed alone. Final privacy/ledger/static checks passed `53` tests, the 725-entry ledger fingerprint remained deterministic, private-literal and JSON checks passed, and the user-owned AI-pack changes remain outside the commit set.
- `g1-completion-progress.v1.9.0`: created the independent Iteration 3 commit from the verified 26-file allowlist and confirmed that no `ai_skating_analysis_pack/**` file was staged. The final commit hash is intentionally reported outside this self-contained commit to avoid a self-referential hash. No push, merge, deployment, release claim, or Iteration 4 work was performed.
