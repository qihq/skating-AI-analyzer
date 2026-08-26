# Iteration 3 G1-D3 Classification Confirmation Implementation Plan

**Goal:** Replace the limited-sample family calibration with a unified, label-agnostic confirmation policy for every localized proposal while preserving uncertainty and refusal behavior.

**Architecture:** Keep the existing four family scorers unchanged and add one proposal-local physical confirmation policy after ranking. Store no source/event-specific branches. A separate diagnostic reconstructs classification evidence from the accepted v1.18 observation bridge, compares the D3-off baseline with D3-on output, and never imports evaluator, moment, or rotation execution paths.

**Tech stack:** Python 3.12, Pydantic contracts, pytest, JSON diagnostics.

## Global constraints

- Iteration 3 G1-D3 only.
- Do not modify tracker or identity bridge behavior.
- Do not consume Golden labels or evaluator targets.
- Do not tune or evaluate moments or rotation.
- Do not run the formal Pilot or enter G2/Iteration 4.
- Do not call superpower skills.
- Keep private runtime artifacts outside Git.

## File map

- Modify `backend/app/analysis_v2/action_classification.py`: shared D3 confirmation policy, compatibility switch, refusal metadata, deterministic policy fingerprint.
- Modify `backend/tests/analysis_v2/test_action_classification.py`: red/green unit coverage for all states and negative controls.
- Modify `backend/app/analysis_v2/evaluation/source_evidence_adapter.py`: expose the already-derived proposal-local temporal summaries required by the classifier; do not change tracking, identity, moments, or rotation algorithms.
- Modify `backend/tests/analysis_v2/test_source_evidence_adapter.py`: verify two proposals from one source receive independent evidence and decisions.
- Create `scripts/g1_d3_classification_confirmation_diagnostic.py`: label-free D3 artifact comparison.
- Create `backend/tests/analysis_v2/test_g1_d3_classification_confirmation_diagnostic.py`: leakage, ordering, baseline, multi-proposal, and fingerprint tests.
- Modify `docs/development/iteration-03-g1-completion-progress.md`: record only verified D3 evidence after implementation.

## Task 1: Compatibility and refusal contract

- [x] Add failing tests proving D3-off keeps legacy state/profile/confidence/margin/fingerprint behavior.
- [x] Add a failing test proving unlocalized evidence yields `unknown` with `refusal_reason="proposal_unlocalized"` under D3.
- [x] Run the two tests and confirm failures are caused by the absent D3 API.
- [x] Add `classification_confirmation_upgrade: bool = True` to `classify_action()` and compatible refusal metadata to `ProfileClassification`.
- [x] Keep the legacy decision branch intact when the switch is false.
- [x] Run the focused tests to green.

## Task 2: Unified physical confirmation policy

- [x] Add parametrized failing tests for near-threshold jump, spin, spiral, and step proposals using the same persistence, score, and margin contract.
- [x] Add failing negative tests for single-frame support, short temporal span, missing identity confirmation, missing pose observability, semantic conflict, small margin, and weak ordinary travel.
- [x] Run the tests and verify expected ambiguous/unknown versus missing-upgrade failures.
- [x] Implement a single policy object with shared minimum score, margin, support count, support ratio, and source-time span thresholds.
- [x] Select only the physical support channel by winning family; do not use semantic labels for upgrade admission.
- [x] Record policy version, decision reason, support summary, and upgrade contribution in `evidence_summary` and classifier fingerprint.
- [x] Run the classifier suite to green.

## Task 3: Proposal-local evidence and multi-proposal behavior

- [x] Add a source-evidence test constructing two non-overlapping proposals from one bundle and asserting independent event IDs, sample windows, temporal summaries, and classification results.
- [x] Verify the existing proposal-local evidence builder already supplies independent evidence, so no production adapter change is required.
- [x] Keep proposal generation, tracker state, identity state, moment localization, and rotation estimation unchanged.
- [x] Run source-evidence and classifier tests to green.

## Task 4: Label-free D3 diagnostic

- [x] Add failing tests for D3-off recorded baseline comparison, D3-on aggregate changes, multi-proposal accounting, Golden-shaped-field invariance, input-order invariance, and explicit downstream non-invocation flags.
- [x] Run the tests and verify they fail because the diagnostic does not exist.
- [x] Implement the diagnostic using only `source_evidence.proposal_samples`, `proposal_collection`, stored proposal-local classification evidence, and recorded classification payloads.
- [x] Regenerate proposals with the accepted D2 policy, classify each localized proposal independently, and mark unlocalized proposals as refusals without calling moments/rotation.
- [x] Emit deterministic canonical fingerprints and no per-source private identifiers in the committed test fixtures.
- [x] Run diagnostic tests to green.

## Task 5: Private bridge verification and closeout

- [x] Run the D3 diagnostic against both independent v1.18 bridge artifacts without reading any Golden artifact.
- [x] Verify D3-off reproduction, deterministic D3 results, multi-proposal handling, state/refusal counts, and byte-identical sanitized outputs.
- [x] Run action-classification, source-evidence, event-proposal, D2/D3 diagnostic, fusion, and shadow focused regressions (`91 passed`).
- [x] Run `git diff --check` and privacy scans.
- [x] Update the progress document with measured label-free evidence only.
- [x] Review the final D3 diff and stage only the D3 allowlist; do not include private runtime artifacts or unrelated dirty files.
