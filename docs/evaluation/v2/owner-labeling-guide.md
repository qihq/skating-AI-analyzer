# Golden V2 Owner Labeling Guide

Use `/me/advanced?tool=golden` in parent mode. This workflow accepts only newly selected private videos; do not import the earlier debug pool.

1. Import one video, assign its recording-session and grouping IDs, then confirm the recorded SHA-256 and source metadata.
2. Choose the source and use the shared player. Step by source frame when marking a moment; the displayed PTS and frame identity are the annotation reference.
3. Create one interval per complete event. Ordinary events should take about 3-6 minutes. Crossing, occlusion, exit/re-entry, or uncertain-rotation events should take about 8-15 minutes.
4. Confirm the main skater. Draw 3-8 ordinary sparse boxes; add denser boxes only in challenge intervals. Mark joints or whole pose unobservable instead of filling guessed coordinates.
5. Select family, optional subtype, observability, scene strata, and ambiguity/failure tags. For jumps mark T/A/L and rotation count/range/class/convention. For spins mark entry/main/exit and observable turns. For steps and spirals mark the profile interval and one representative moment.
6. Review the queue, save only when the form is complete, and resolve a conflict by reloading before retrying. Offline or unavailable-frame messages never mean a label was confirmed.

Protocol: collect at least five recording sessions (prefer eight or more), never split a source or session across development/validation/frozen-test, re-label at least 10 percent after a delay, and double-review ambiguous rotation and frozen-test crossings. Unobservable fields are excluded from ordinary accuracy denominators but are counted and reported. The first pose pass covers 50-100 representative frames across the whole dataset, not every frame.

Suggestions are never Ground Truth. Frozen-test first-pass suggestions are rejected by the server; all human-confirmed fields carry annotator, timestamp, and revision history.
