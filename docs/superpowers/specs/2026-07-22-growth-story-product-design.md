# Growth Story And Product Value Design

Date: 2026-07-22

## Goal

Turn the analysis, keyframe, biomechanics, skill-tree, archive, comparison, and sharing capabilities already present in Skating Analyzer into a parent-facing growth story.

The product should answer five questions in order:

1. What happened in this practice?
2. What is the single most important point to improve?
3. What should the skater practice next?
4. Is the skater making measurable progress this month?
5. Which moments are worth preserving as milestones?

This design adds a parallel product-visibility track to the high-accuracy analysis program. It does not weaken or bypass the Golden evaluation gates in `2026-07-12-high-accuracy-analysis-master-plan.md`.

## Confirmed Product Decisions

- Do not implement uniform per-second VLM analysis. Use detected technical events and precise timestamps.
- The first action-phase strip uses trustworthy profile-specific phases. For jumps this is T/A/L; a preparation frame is optional until it has a defined and validated source.
- An actual-pose overlay is not marketed as a standard-action comparison. A true red/green ghost comparison requires a reference library and view/scale normalization.
- Parent notes and existing share-image infrastructure are reused rather than duplicated.
- Landing rate is not inferred from force score or completed reports. It is shown only after attempts and outcomes have a defined, auditable metric contract.
- AI narrative may connect supplied facts but may not invent fear, fatigue, injury risk, coaching verification, or readiness for the next formal level.
- Automatic, parent-confirmed, and coach-confirmed milestones remain visibly distinct.
- The initial monthly chapter is manually generated and reviewed. Scheduling is added only after the workflow and data quality are stable.
- The annual PDF is a product runtime feature. Development tooling may help design and verify it, but the deployed application must use an explicit PDF renderer.

## Current Assets To Reuse

The system already has most of the underlying data and interaction primitives:

- `PoseViewer` draws skeletons and diagnostics on source frames with Canvas.
- `KeyframeEvidencePanel` resolves profile-specific keyframes and seeks the source video by timestamp.
- Jump analysis stores T/A/L, biomechanics metrics, confidence, evidence provenance, and data-quality warnings.
- Spin, spiral, and step profiles already use their own phase labels instead of being forced into T/A/L.
- `TrainingSession`, `Analysis.note`, and session notes already capture practice context.
- Skill progress stores `unlocked_at`, `unlocked_by`, and `unlock_note`.
- Archive and history already expose completed reports, sessions, filters, timelines, and comparisons.
- Report, comparison, and progress pages already generate and share Canvas-based images.

The main product gap is aggregation and presentation: these capabilities currently live in separate technical or task-oriented pages.

## Product Information Architecture

Add a parent-facing growth home as the primary summary surface. It presents:

1. Skater identity and trustworthy KPI summary.
2. The latest practice conclusion and action-phase strip.
3. One strength, one focus, and one next action.
4. Recent milestones with evidence source.
5. Entry points to the monthly chapter, full report, history, and detailed evidence.

The parent navigation can later converge on four primary concepts:

- Home;
- Review;
- Progress;
- Profile.

Golden labeling, debug, provider settings, and diagnostics remain available as advanced tools but are not primary parent navigation.

## P0: Product Visibility Without New AI Cost

### P0.1 Profile-aware action-phase strip

Create reusable `PoseFrameCard` and `ActionPhaseStrip` components.

For jumps, the initial strip contains:

- takeoff (T);
- air/apex (A);
- landing (L).

If a validated preparation record exists, the strip may show preparation as a fourth card. It must not synthesize preparation as an arbitrary fixed offset from T.

For other profiles, the component uses the established phase contract:

- spin: entry, main rotation, exit;
- spiral: representative hold;
- step sequence: chronological interval coverage frames.

Each card shows, when available:

- source frame;
- actual skeleton overlay;
- phase name and precise timestamp;
- confidence and evidence source;
- bounded joint or biomechanics diagnostics;
- an explicit unavailable/uncertain state.

Selecting a card seeks the source video to the corresponding timestamp. On phones the cards scroll horizontally; wider layouts use a three- or four-column grid.

No new VLM call is introduced. Missing frames, landmarks, or reliable angles are shown as missing rather than replaced by defaults.

### P0.2 Authoritative growth summary

Add an aggregation endpoint shaped as:

`GET /api/skaters/{skater_id}/growth-summary`

Initial fields:

```json
{
  "schema_version": 1,
  "skater_id": "skater-uuid",
  "as_of": "2026-07-22T00:00:00Z",
  "lesson_count": 18,
  "completed_analysis_count": 36,
  "current_month_analysis_count": 7,
  "milestone_count": 12,
  "current_focus": {
    "label": "Loop landing",
    "source_analysis_id": "analysis-uuid",
    "quality": "good"
  },
  "metric_definitions": {
    "lesson_count": "Distinct persisted training sessions",
    "milestone_count": "Skills with a persisted unlocked_at timestamp"
  }
}
```

The backend aggregates over persisted records, not the frontend's currently loaded archive page. Counts must have stable definitions and an `as_of` timestamp.

Landing rate remains absent from this first contract. It may be added only with:

- an explicit attempt definition;
- success/failure/unobservable outcomes;
- sample size;
- applicable action and date window;
- metric version and confidence/coverage.

### P0.3 Milestone highlight timeline

Expose a chronological milestone feed derived from persisted skill progress and explicitly entered achievements.

Each event contains:

```json
{
  "id": "milestone-uuid",
  "occurred_at": "2026-07-18T00:00:00Z",
  "type": "skill_unlock",
  "title": "Waltz jump stabilized",
  "note": "Three confident one-foot landings today",
  "verification": "parent_confirmed",
  "source_skill_id": "fs1-waltz-jump",
  "source_analysis_ids": ["analysis-uuid"],
  "evidence_quality": "good"
}
```

Supported verification labels are `system_detected`, `parent_confirmed`, and `coach_confirmed`. The UI must never promote an automatic unlock to coach-verified.

The first release reuses `unlocked_at`, `unlocked_by`, and `unlock_note`. A later explicit achievement record can cover tests, competitions, and personal highlights that are not skill-tree nodes.

### P0.4 Unified growth home

Compose the growth summary, latest action-phase strip, report conclusion, next action, and milestone feed into one page. Existing detailed pages remain the evidence and editing surfaces.

The growth home prioritizes outcome language over implementation language. It does not expose Path A/Path B, model slots, candidate frames, Golden terminology, or pipeline diagnostics in its primary content.

## P1: Monthly Narrative And Sharing

### P1.1 Monthly chapter data model

Add a persisted `MonthlyChapter` record with:

- skater and calendar month;
- generation and review status;
- immutable fact snapshot;
- included analysis, session, skill, and milestone IDs;
- representative frame references;
- prompt, provider, model, and schema versions;
- generated draft and parent-edited final text;
- quality/coverage warnings;
- generated, reviewed, and published timestamps.

Use one active chapter per skater/month with explicit revisions rather than silently overwriting a published chapter.

### P1.2 Fact-first generation flow

The initial flow is manually triggered:

```text
Select month
  -> aggregate deterministic facts
  -> preview facts and missing coverage
  -> generate narrative draft
  -> parent edits or confirms
  -> persist published chapter
```

Facts can include:

- distinct sessions and completed analyses;
- reliable same-action metric changes;
- newly unlocked skills and confirmed achievements;
- repeated issues and demonstrated improvements;
- parent/skater/coach quotes;
- representative keyframes with provenance.

The text model receives the fact snapshot rather than raw database objects. Its response must use structured output and may only narrate supplied facts. Unsupported causal, emotional, medical, or level-readiness claims are rejected or removed during validation.

If the month has insufficient comparable evidence, the chapter emphasizes participation, confirmed milestones, and the family's own notes instead of fabricating a trend.

### P1.3 Highlight quote

Existing operational and session notes stay unchanged. Add a semantically distinct optional quote:

```text
highlight_quote
quote_speaker: skater | parent | coach
```

The review/session UI labels it as the sentence the family wants to remember. Quotes are escaped, length-limited, editable, and never rewritten as a different speaker's words.

### P1.4 Milestone share card

Add a `milestone` template to the existing Canvas share pipeline. The card contains:

- best available representative frame;
- milestone title and date;
- verification source;
- optional quote;
- one concise, well-defined metric when available;
- product attribution and a non-medical disclaimer where appropriate.

Frame selection reuses existing clarity/evidence ranking. If no suitable frame exists, the card uses a designed non-image layout rather than a blurry placeholder.

## P2: Long-term Assets And Event Coverage

### P2.1 Annual collection

After confirmed monthly chapters exist, allow a parent to choose chapters and milestones for an annual collection.

The first release produces a PDF containing:

- cover and skater/year summary;
- selected monthly chapters;
- milestone timeline;
- representative frames and quotes;
- annual metrics with definitions and sample sizes;
- provenance/quality notes in a compact appendix.

The deployed backend uses an explicit, tested PDF renderer. Generated PDFs are treated as derived assets and can be rebuilt from persisted chapters and media references.

### P2.2 Full-video technical event timeline

This is not a P0 display-only feature. It depends on the high-recall action candidate and specialty classification work in the high-accuracy plan.

Introduce an `ActionWindow` contract only after the relevant Golden gates pass:

```json
{
  "start_sec": 12.2,
  "end_sec": 14.1,
  "action_type": "jump",
  "action_subtype": "loop",
  "representative_timestamp": 13.04,
  "keyframe_ids": ["frame-uuid"],
  "observation": "Landing knee remains relatively straight",
  "training_tip": "Practice a controlled landing hold",
  "confidence": 0.86,
  "evidence_source": "fused",
  "quality_flags": []
}
```

The pipeline performs a low-cost full-video scan, merges overlapping windows, extracts representative evidence, and reuses profile-specific pose/biomechanics analysis. The UI renders a timestamped comment stream whose entries seek the video.

The product calls this `technical events` or `key moments`, not `per-second feedback`. Initial coverage is limited to validated jumps, spins, step intervals, and held poses. It does not promise judge-grade edge calls, fear detection, fatigue diagnosis, or injury prediction.

## Dependency Gates

| Product capability | Earliest dependency | Required behavior |
|---|---|---|
| T/A/L action-phase strip | Existing resolved keyframes; improves after G4 | Show confidence, source, and missing states |
| Optional preparation frame | Defined profile contract plus Golden measurement | Never infer from a fixed offset alone |
| KPI summary | Persisted sessions/analyses/skill unlocks | Stable definitions and backend aggregation |
| Landing rate | Versioned attempt/outcome contract and measured coverage | Show sample size and unobservable rate |
| Milestone timeline | Persisted unlock timestamps and verification source | Preserve system/parent/coach distinction |
| Monthly chapter | Deterministic monthly fact snapshot | Human review before publication |
| Standard-action ghost comparison | Reference library plus view/scale normalization validation | Do not label actual-pose overlay as standard comparison |
| Full-video event timeline | G3 candidate acceptance and G4 specialty/timing acceptance | Event-triggered, evidence-linked output |
| Annual collection | Reviewed monthly chapters | Rebuildable PDF with provenance |

## API And Component Boundaries

Backend responsibilities:

- authoritative KPI and milestone aggregation;
- metric definitions, coverage, and versioning;
- monthly fact snapshots and narrative validation;
- chapter revision and publication state;
- later ActionWindow persistence and evidence linkage;
- annual export orchestration.

Frontend responsibilities:

- reusable pose-frame/action-phase presentation;
- growth home composition;
- milestone timeline and source labels;
- monthly fact preview, editing, and publication controls;
- share-card rendering and export;
- video seeking from keyframes and technical events.

The frontend must not calculate authoritative rates from paginated records, invent missing phase frames, or convert confidence scores into verification labels.

## Error And Uncertainty Handling

- Missing keyframes render explicit unavailable cards without breaking the remaining strip.
- Low-confidence pose or metrics remain visible only with a quality warning and no exaggerated precision.
- Aggregation responses include `as_of`, definitions, and coverage so stale or partial data can be explained.
- Narrative generation failure preserves the deterministic fact snapshot and allows retry without losing edits.
- A chapter with changed source data is marked stale; it is not silently regenerated.
- Missing/deleted representative media falls back to text-first cards and PDF sections.
- All exported claims retain the verification source and applicable disclaimer.

## Testing Strategy

### Backend

- Growth summary counts distinct sessions and complete analyses across all pages.
- Metric definitions and `as_of` are stable and serialized.
- Milestones preserve source, verification label, timestamp, and evidence references.
- Landing rate is absent until a valid attempt/outcome dataset exists.
- Monthly fact aggregation is deterministic for the same source revision.
- Narrative validation rejects unsupported claims and unknown fact references.
- Published chapters are revisioned and never silently overwritten.

### Frontend

- Jump, spin, step, and spiral phase strips use the correct labels and ordering.
- A missing phase produces an unavailable card; it does not shift another frame into its place.
- Selecting a phase or event seeks the video to the exact stored timestamp.
- Mobile horizontal scrolling and desktop grids avoid clipping and distorted frames.
- Growth-home KPI values match the backend response and never recompute from loaded pages.
- Milestone cards distinguish system, parent, and coach confirmation.
- Share cards export with and without representative images.

### Rendered QA

- Verify growth home, monthly chapter, milestone card, and annual PDF at phone, tablet, and desktop widths where applicable.
- Verify long Chinese text, missing images, low-data months, and many milestones.
- Confirm no source frame is stretched and skeleton overlays remain aligned with the displayed image area.

## Rollout Order

1. P0 data contracts and aggregation tests.
2. Profile-aware action-phase strip.
3. KPI and milestone feed.
4. Unified growth home and navigation simplification.
5. Monthly fact snapshot and manual narrative workflow.
6. Highlight quote and milestone share template.
7. Annual PDF.
8. Full-video event timeline after G3/G4 evidence gates.

Every product metric ships behind a display-quality check. Existing detailed report, evidence, archive, and debug pages remain available during rollout.

## Success Criteria

- A parent can understand the latest practice outcome and next action from one page without opening diagnostics.
- Every visible phase, KPI, milestone, and narrative claim has a persisted source or an explicit unavailable state.
- P0 adds no new model calls and does not change analysis results.
- Monthly chapters can be regenerated from immutable fact snapshots and remain editable before publication.
- No automatic event is presented as coach-confirmed.
- No landing rate is displayed without attempt count, applicable window, metric version, and unobservable coverage.
- Full-video feedback is event-triggered and evidence-linked rather than uniform per-second inference.

## Non-Goals

- Reproducing SkateMarks branding, copy, FormLens naming, media, or page layout.
- Claiming judge-grade scoring, medical safety, fear recognition, fatigue diagnosis, or predicted test dates.
- Replacing the coach or presenting AI output as formal certification.
- Building payments, referrals, public social profiles, or a coach dashboard in this design.
- Replacing the high-accuracy Golden evaluation program with better presentation.
