# Iteration 3 G1 completion progress

- Progress document version: `g1-completion-progress.v1.17.0`
- Updated: `2026-08-23` (Asia/Shanghai)
- Authorized iteration: Iteration 3 only
- Gate policy: `golden-gate-policy.v2`
- Evidence scope: `limited_sample`
- Release claim: `false`
- Current gate conclusion: `g1_v2_to_v5_controlled_attribution_blocked`

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

### E. Post-formal prediction-quality repair

- [x] Reproduced the committed formal failure from the preserved private revision-95 source-only diagnostic without exposing source paths, hashes, event IDs, frames, labels, or per-event diagnostics in Git.
- [x] Confirmed that the previous narrow proposal interval was taken from the selected classification candidate, coupling proposal recall to profile confidence and strong-signal localization.
- [x] Restored the evaluator contract separation for the G1 single-event source distribution: proposal recall now uses the observed source-time envelope, while the independently selected physical candidate still supplies only profile, moments, and rotation.
- [x] Preserved the no-leakage multi-event policy: the one two-event source remains skipped as a whole, so both events remain missing predictions in the denominator.
- [x] Added regression coverage for the observation-envelope proposal policy and the no-observation refusal path; the adapter/evaluator focused suite passed `24 passed`.
- [x] Re-ran the private 18-event preflight from the preserved source-only diagnostic. Proposal recall improved from `1/18` to `16/18`; class accuracy remains `3/18`, key-moment coverage remains `8/43`, rotation coverage remains `0/13`, and the result remains failed diagnostic evidence.
- [x] Separated the predicted top profile from its `confirmed | ambiguous | unknown` state. An ambiguous correct family now contributes to class accuracy while remaining rejected and producing `action_class_uncertain`; it is not promoted to a confirmed fact.
- [x] Added a bounded `limited_sample` source-family calibration using only source motion, edge/pose dynamics, airborne support, and rotation-family peaks. The private preflight class accuracy improved from `3/18` to `14/18`, while rejection increased to `15/18` and therefore continues to expose calibration uncertainty.
- [x] Re-ran profile-conditioned source-PTS moment localization and strict rotation estimation. Key-moment coverage moved from `8/43` to `9/43`; rotation remained a safe `0/13` refusal rather than emitting unsupported turn counts.
- [x] Completed a private identity-localization audit against the 77 confirmed tracking review frames. The diagnostic target boxes had median IoU `0.20`, only `7/77` reached IoU `0.30`, and 14 of 17 sources with review frames had no IoU-0.30 match.
- [x] Identified the upstream diagnostic contract defect: 15 of 18 source previews were correctly `awaiting_manual`, but the diagnostic runner forced the first candidate into a synthetic `manual=True` lock. The correct target was present among the candidates for every source with review frames, but the forced candidate was the best available candidate in only one source.
- [x] Replaced the synthetic manual lock with an explicit parent-confirmed initial identity-anchor path for action/moment/rotation masks. The private manifest contains one source hash, source frame/PTS, normalized bbox, and `parent_confirmed` authority per available source; it excludes event IDs, profiles, event windows, moments, rotations, paths, and full tracking timelines. Tracking evaluation rejects the anchor as leakage.
- [x] Re-ran all 18 sources and the private evaluator preflight from the corrected identity anchor. The first run consumed anchors for 17 sources and exposed a runner mismatch: `manual_override=True` was not propagated to `manual_lock_mode`. After a test-first one-line propagation repair, the focused runner/anchor/adapter/evaluator suite passed `34 passed` and the 18-source run completed without runtime failure.
- [x] Audited the corrected manual-mode output against 77 private confirmed review frames. Median tracking IoU improved from `0.236` to `0.455`, IoU at least `0.30` improved from `28/77` to `52/77`, and every reviewed source produced at least one IoU-0.30 match. However, manual-mode recovery rejection reduced average pose tracked ratio from `0.5515` to `0.2167`.
- [x] Re-ran key-moment and rotation diagnostics from the corrected manual-mode identity anchor before any formal evaluator rerun. Proposal recall remained `16/18`, class accuracy was `8/18`, rejection was `17/18`, key-moment timing coverage was `2/43`, and rotation remained a safe `0/13` refusal. This is failed private diagnostic evidence, not a formal or release pass.
- [x] Decoupled source-level proposal recall from event classification and event-to-source alignment. The evaluator now accepts multiple proposals per source, so both events on the shared source can independently match source proposals without reading Golden intervals or profiles.
- [x] Added an explicit `unknown` / `unlocalized_observability_envelope` fallback for source-only observations when localized proposals cover less than 80% of the observed timeline. Total recall and localized recall are reported separately, and an unlocalized match remains an `action_proposal_unlocalized` failure rather than a boundary-quality pass.
- [x] Passed the proposal/evaluator/adapter focused regression: `44 passed`.
- [x] Re-ran the private 18-event preflight from the strict manual-mode artifact. Total proposal recall improved from the formal `0/18` to `18/18`; localized proposal recall is `1/18`, and `17/18` events use the explicitly reported unlocalized fallback. Class accuracy remains `8/18`, key-moment coverage `2/43`, rotation coverage `0/13`, and all 18 events still fail at least one metric, so no formal Pilot rerun is authorized yet.
- [ ] Resolve identity-consistent recovery after the parent-confirmed initial anchor. Strict manual mode preserves the intended person better but rejects too many later detector recoveries; no action threshold, Golden event window, later tracking label, or semantic target may be used to hide this blocker.
- [ ] Replace the limited-sample family calibration with one unified, label-agnostic source evidence classifier that supports multiple temporal proposals and preserves ambiguous/unknown/refusal states. Development and validation may calibrate shared physical rules; frozen-test labels remain final verification only.
- [ ] Improve profile-conditioned moment localization and rotation observability from identity-consistent target evidence without lowering safety consensus thresholds or adding event-specific branches.
- [ ] Re-run the parent-authorized formal Pilot only after the repaired local payload and full regression evidence are accepted.

### E.1 Contained-bootstrap repair record (v1.14.0-v1.15.0)

- `v1.14.0` recorded the two identity-recovery negative results. The v3 self-heal attempt had no recovery effect: all `18/18` sources completed, average pose tracked ratio stayed at `21.67%`, keyframe coverage stayed at `0%`, and the aggregate profile count remained `16 unknown / 2 jump` (no confirmed spin). The v4 same-ID-recovery attempt had zero triggers and therefore zero gain: all `18/18` sources completed with the same `21.67%` tracked ratio, `0%` keyframe coverage, and `16 unknown / 2 jump` profile distribution. Both changes were rolled back or superseded; neither is an active acceptance mechanism.
- `v1.15.0` recorded the v5 contained-bootstrap mechanism. A detector candidate is admitted only when its rejection reasons are limited to `area_ratio` and/or `aspect_ratio`, the candidate and anchor boxes cover one another by at least `90%`, center distance is at most `0.06`, candidate height is `0.10..0.72`, and candidate aspect is `0.10..0.75`. This raised average pose tracked ratio from `21.67%` to `41.38%` (`+19.71pp`), while all `18/18` sources completed. The current profile distribution is `15 unknown / 2 jump / 1 spin`; keyframe coverage remains `0%`. Remaining failure scenes are `125 occlusion_or_detector_loss`, `71 target_bbox_relock_or_reuse`, and `1 pose_low_confidence_or_blur`.
- The v5 result is diagnostic evidence only. It has not passed the required confirmed-frame IoU audit (median threshold `0.405`, derived from the `0.455` v2-manual baseline), so it does not constitute acceptance and no downstream metric claim is made from it.

### E.2 IoU audit and stop decision (v1.16.0)

- The private confirmed-review audit used `77` frames and the same nearest sampled timeline mapping for v2-manual-mode and v5. Aggregate result: v2 median IoU `0.455029`, `52/77` at or above `0.30`; v5 median IoU `0.255148`, `31/77` at or above `0.30`. The required v5 median is `>=0.405` (`0.455 - 0.05`), so the gate fails.
- The v5 tracker diagnostics contained `211` candidate-rejection rows with the permitted geometry reasons. Applying the complete contained-bootstrap predicate admitted only `6` rows, all in one source; all six source groups that regressed against the v2/v4 IoU baseline had zero admitted contained candidates. The admitted rows did not alter the v4 tracker bbox sequence or that source's review IoUs, so the measured IoU degradation is not attributable to a released contained candidate and cannot be repaired by tightening this pose-only geometry rule.
- The degraded source groups are recorded only as aggregate evidence: six source groups regressed against the v2/v4 sequence, while the other reviewed groups were unchanged or within the prior baseline. No private source hash, event identifier, frame identifier, label, or per-frame diagnostic is committed.
- Per the Iteration 3 stop rule, downstream classification/moments diagnosis and implementation are gated on a passing identity audit and were not run. No formal Pilot, frozen-test threshold selection, G2 freeze, or Iteration 4 work was performed. A new identity-consistent tracker repair requires explicit decision/authorization.

### E.3 Controlled v2-to-v5 drift attribution (v1.17.0)

- Audit recheck first: the unchanged private audit implementation recomputed v2-manual-mode as median IoU `0.4550294188`, `52/77` at or above `0.30`, and v5-contained-bootstrap as `0.2551479277`, `31/77`. The audit script did not drift between the two evaluations.
- Determinism control: current runner + current backend + the same parent-confirmed anchor manifest was run twice over the same `18/18` inputs. Both runs produced pose tracked ratio `30.60%`, median IoU `0.4550294188`, `52/77` at or above `0.30`, and identical canonical bbox-sequence hashes for all 18 sources. No inference-thread, sampling, or TensorFlow Lite non-determinism was observed.
- Runner-head ablation: executing the exact `HEAD` runner source while keeping current backend code produced `18/18` successful sources, pose tracked ratio `85.72%`, median IoU `0.1999717763`, `8/77` at or above `0.30`, auto-lock `16.67%`, and keyframe coverage `5.56%`. This confirms the runner's target-lock/manual-mode/anchor path is behaviorally material; it does not reproduce either the v2 manual-anchor result or the v5 artifact.
- Pose-only ablation: current runner + parent-confirmed anchors with the contained-candidate hunk removed from `pose.py` produced pose tracked ratio `21.67%`, median IoU `0.4550294188`, and `52/77` at or above `0.30`. Restoring the contained hunk produced `30.60%` with the identical bbox hashes and identical IoU. Therefore contained-bootstrap's measured net effect is `+8.93pp` pose tracked ratio and `0.000000` IoU change; it cannot explain the v2-to-v5 IoU degradation.
- The old v5 artifact (`41.38%` pose tracked) is not reproducible from the current source under fixed inputs: the same code path is deterministic at `30.60%`, while contained-off is deterministic at `21.67%`. The six source groups that regressed in the historical v5 IoU audit had no admitted contained candidate rows. The remaining unisolated factor is the historical diagnostic run state/input path (runner/runtime artifact provenance), not a new tracker mechanism; no attempt was made to change it in this slice.
- No tested configuration satisfies both acceptance gates. Current runner + parent-confirmed anchors + contained-bootstrap retains median IoU `0.4550294188 >= 0.405` but pose tracked ratio is only `0.3060`; contained-bootstrap-off is `0.2167` pose with the same IoU; HEAD-runner ablation reaches `0.8572` pose but IoU is only `0.1999717763`. The old v5 artifact's `0.4138` pose ratio is not accepted as reproducible evidence.
- Focused regression after exact pose hunk restoration passed `133` tests (`test_pose_smoothing.py` + `test_person_tracker.py`). `git diff --check` and the sanitized progress-document privacy scan passed. No new recovery/tracking mechanism, classifier/moments change, formal Pilot, frozen-test tuning, G2 freeze, or Iteration 4 work was performed.

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
- `g1-completion-progress.v1.10.0`: began the post-formal prediction-quality repair from the preserved private revision-95 diagnostic. Proposal recall was decoupled from the selected classification candidate by using the source observation envelope only for single-event sources with actual observations. The leakage-safe multi-event skip remains unchanged. Focused tests passed `24 passed`, and the local proposal recall improved from `1/18` to `16/18`; classification, moment, and rotation metrics remain blocked and no formal rerun was submitted.
- `g1-completion-progress.v1.11.0`: separated top-family scoring from confirmation state, added bounded limited-sample source-family calibration, and reran the private preflight. Proposal recall is `16/18`, class accuracy is `14/18`, rejection is `15/18`, moments are `9/43`, and rotation remains a safe `0/13` refusal. A private 77-frame localization audit then exposed the dominant upstream defect: the old runner converted 15 `awaiting_manual` previews into synthetic manual locks, producing median target IoU `0.20`. The next repair is an evaluation-mask-safe parent-confirmed initial identity anchor, not further timing-threshold tuning.
- `g1-completion-progress.v1.12.0`: implemented the private parent-confirmed initial identity-anchor contract, verified tracking-mask leakage rejection, and completed two 18-source reruns. The runner originally failed to propagate manual-lock semantics; a focused regression reproduced the defect, the minimal repair passed `34` tests, and strict manual mode improved private median tracking IoU from `0.236` to `0.455`. It also reduced pose tracked ratio from `0.5515` to `0.2167`, leaving class accuracy `8/18`, moments `2/43`, and rotation `0/13`. The next blocker is identity-consistent recovery after the single upstream anchor; no formal Pilot rerun is authorized yet.
- `g1-completion-progress.v1.13.0`: repaired the proposal contract at source level. Multiple proposals on one source are evaluated independently, while source-only observation envelopes are explicitly marked unlocalized and remain failures for boundary quality. The focused proposal/evaluator/adapter regression passed `44` tests. On the preserved 18-event manual-mode diagnostic, total proposal recall improved from the formal `0/18` to `18/18`, but localized recall is only `1/18`; class accuracy remains `8/18`, moments `2/43`, rotation `0/13`, and the formal Pilot remains blocked.
- `g1-completion-progress.v1.14.0`: recorded the v3 self-heal and v4 same-ID-recovery negative results. Both runs completed `18/18` sources with average pose tracked ratio `21.67%` and keyframe coverage `0%`; v3 produced `16 unknown / 2 jump`, while v4 produced the same distribution and zero same-ID recovery triggers. Both approaches were rolled back or superseded.
- `g1-completion-progress.v1.15.0`: recorded v5 contained-bootstrap. The unified geometry rule admitted only area/aspect-only rejected candidates with bidirectional `>=90%` coverage and center distance `<=0.06`, improving pose tracked ratio from `21.67%` to `41.38%`. The run completed `18/18`, with `15 unknown / 2 jump / 1 spin`; residual failures were `125 occlusion_or_detector_loss`, `71 target_bbox_relock_or_reuse`, and `1 pose_low_confidence_or_blur`. The required IoU audit is not yet passed, so this remains diagnostic evidence rather than acceptance.
- `g1-completion-progress.v1.16.0`: completed the required 77-frame v5 identity audit. Median IoU was `0.255148` with `31/77` at or above `0.30`, failing the `0.405` acceptance line versus the `0.455029` v2-manual baseline. Only six contained candidates were actually admitted, all in one source whose tracker bbox sequence was unchanged from v4; the six regressed source groups therefore are not explained by contained-bootstrap. The downstream classification/moments work is stopped pending an authorized identity-consistent tracker decision.
- `g1-completion-progress.v1.17.0`: completed controlled attribution without adding a mechanism, but the acceptance gate remains blocked. The audit recheck was identical (`v2 0.4550294188 / 52-of-77`, `v5 0.2551479277 / 31-of-77`); two current-code runs were deterministic (`30.60%` pose, `0.4550294188` IoU, `52/77`, identical 18-source bbox hashes); HEAD-runner ablation yielded `85.72%` pose and `0.1999717763` IoU with `8/77`; pose contained-off yielded `21.67%` pose with unchanged `0.4550294188` IoU and `52/77`. The contained hunk's net effect is `+8.93pp` pose only and zero IoU effect. Historical v5 `41.38%` is not reproducible under current fixed inputs; the unresolved factor is historical runner/runtime artifact provenance, and no single hunk was uniquely proven as its cause. No tested configuration satisfies both acceptance gates, so downstream and formal work remain blocked.
