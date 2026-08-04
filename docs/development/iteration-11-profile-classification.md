# Iteration 11 profile-specific action classification

Status: implemented as a temporary 14-video diagnostic pilot. It is not a formal G7 pass because G2 is not frozen and the existing owner-labelled manifest is too small.

- Four independent classifiers share a contribution contract while keeping feature weights, configuration and fingerprints isolated.
- Inputs are interpretable motion/pose temporal evidence plus bounded semantic support or contradiction. Legacy `analysis_profile` is not a classifier input and there is no fallback to `step`.
- Path A cannot localize an event or determine identity. It is capped semantic evidence only; Path B semantic review remains non-authoritative for localization and identity too.
- Broad family is separate from specialty subtype. All current specialty subtypes are underpowered and require human confirmation.
- Subtype admission uses family-isolated validation label N, never the number of frames inside one event; the temporary pilot has no subtype with sufficient validation N.
- Missing or contradictory evidence produces `ambiguous` or `unknown`; only confirmed observable compatible profiles pass the `AnalysisFactsV2` downstream boundary.
- Training-plan selection, filters, progress grouping, compare, skill matching, monthly facts, memory suggestions and growth share the same profile-eligibility decision helper. V2 automatic skill unlock remains disabled until Iteration 14; manual and historical unlock state is unchanged.
- Action-label corrections have a revisioned event-fact core with propose/apply/dismiss, human provenance and an immutable legacy snapshot. The historical whole-analysis correction reader remains available for rollback/history during migration.
- Applied event-label revisions project into the V2 event without mutating legacy whole-analysis fields; dismissal removes that revision from the effective applied view.
- The parent growth view exposes a diagnostic admission card with included/excluded counts and reasons. Shadow, ambiguous and unknown events are excluded; this is an eligibility boundary only, not the Iteration 14 semantic migration.
- The temporary source-grouped pilot split remains in the private runtime. No full source hash or source path is committed; the repository contains aggregate sanitized evidence only.

Provider and prompt status: no new large model was trained or called. No new prompt is authoritative. The private pilot reused already-generated Path A/B text as bounded semantic review only.
