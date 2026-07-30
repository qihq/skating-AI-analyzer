# Golden V2 Owner Labeling Guide

Use `/me/advanced?tool=golden` in parent mode. This workflow accepts only newly selected private videos; do not import the earlier debug pool.

1. Import one video, assign its recording-session and grouping IDs, then confirm the recorded SHA-256 and source metadata.
2. Choose the source and use the shared player. Step by source frame before recording a moment, box, or pose: the workspace only enables those captures after the private source returns the exact PTS and frame identity.
3. Create one interval per complete event. Ordinary events should take about 3-6 minutes. Crossing, occlusion, exit/re-entry, or uncertain-rotation events should take about 8-15 minutes.
4. Confirm the main skater. In **Skater boxes**, enter normalized left/top/right/bottom values (0 to 1), select confirmed/uncertain/lost, then use **Add box at current frame**. Draw 3-8 ordinary sparse boxes; add denser boxes only in challenge intervals.
5. Select family, optional subtype, observability, scene strata, and split. The profile panel changes with the family: jumps expose T/A/L plus rotation; spins expose entry/main/exit plus rotation; steps and spirals expose one phase and representative moment. Use the capture buttons at the exact source frame. Do not enter profile-specific labels for an unobservable event.
6. In **Pose joints**, add only observed normalized joints and visibility for the exact source frame. Do not add a pose when it is unobservable; omission, not guessed coordinates, is the required label.
7. Review the queue, save only when the form is complete, and resolve a conflict by reloading before retrying. Offline or unavailable-frame messages never mean a label was confirmed.
8. Use **Record eligible review** only after actually completing the selected second review. Delayed re-label attestations require 24 hours; ambiguous rotation and frozen-test crossing attestations remain separate from Ground Truth edits.

Protocol: collect at least five recording sessions (prefer eight or more), never split a source or session across development/validation/frozen-test, re-label at least 10 percent after a delay, and double-review ambiguous rotation and frozen-test crossings. Unobservable fields are excluded from ordinary accuracy denominators but are counted and reported. The first pose pass covers 50-100 representative frames across the whole dataset, not every frame.

Suggestions are never Ground Truth. Frozen-test first-pass suggestions are rejected by the server; all human-confirmed fields carry annotator, timestamp, and revision history.

## Iteration 3 pilot

The dashboard at `/golden` shows the exact G1 profile and scene gaps, raw denominators, confidence intervals, review requirements, and failed-event links. The 36-event pilot is diagnostic only and cannot be presented as release approval. Evaluator runs remain blocked as `waiting_for_owner_labels` until all real-event, grouping, duplicate, source-frame, delayed-review, and double-review checks pass.
