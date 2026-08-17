# Iteration 8 Identity Tracking V2

This worktree implements the identity-safe tracking contract in Shadow mode. The existing 12 labeled videos at `private-runtime/pilot-12-run-20260801` are used for development and validation diagnostics only.

## Safety contract

- Identity is a timestamped `confirmed | uncertain | lost` timeline. Wrong-person evidence is rejected in favor of missing coverage.
- Manual anchors carry immutable template fingerprints, annotator provenance, and revision history. The immutable manual template is separate from the short-term adaptive template.
- Appearance, body shape/pose shape, camera-compensated motion, bbox continuity, and optional face evidence have explicit per-signal reliability. No single signal can take over.
- Confirmation requires score and second-best margin. Crossing, recovery, low margin, and relock stabilization freeze adaptive updates.
- Forward/backward disagreements become conflict intervals and `uncertain`; stale/fallback boxes are display hints only.
- Additional anchors preview and invalidate only a causally affected interval while retaining prior revisions.

## Pilot status

`docs/evaluation/v2/iteration-8-pilot12-identity-evidence.json` is diagnostic-only. It is not a G1, G2, frozen-test, or G4 acceptance claim. The 36-event G1 and 60-80-event G2 values in this original diagnostic statement were the legacy policy; they were superseded on 2026-08-15 by `golden-gate-policy.v2`. G4 still requires a frozen candidate run.

## Optional identity models

ReID is not adopted and face is interface-only. There is no measured validation gain yet, no family-data training, no face/embedding retention, and no DS918+ resource claim. YOLO+ByteTrack remains the operational candidate provider when optional evidence is disabled. Any future benchmark must be bounded, parent-authorized, fingerprinted, Shadow-only, privacy-reviewed, and rollback-safe.

## Product boundary

The ordinary family experience remains wholly legacy-authoritative in Shadow mode. Parent-only identity diagnostics are available through the analysis V2 diagnostic API and the `/review?analysis_id=...` panel. Uncertain/lost identity must suppress authoritative pose and technical conclusions; no legacy fallback is mixed into a V2 identity interval.
