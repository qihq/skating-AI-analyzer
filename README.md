# Skating Analyzer — V2

**English** | [中文](./README.zh.md)

An evidence-first figure-skating analysis pipeline built with FastAPI, React, MediaPipe,
YOLO/ByteTrack and Docker. V2 runs **in shadow alongside** the stable `v5.2.x` pipeline:
the legacy pipeline remains the public authority, while V2 builds its own versioned,
rebuildable evidence artifacts and compares them against a frozen evaluation baseline.

[Contributing](./CONTRIBUTING.md) | [License](./LICENSE) | [Synology deployment guide](./SYNOLOGY_STEP_BY_STEP.md) | [Golden A/B runbook](./docs/golden-eval-ab-runbook.md)

---

## What this branch is

The `v2` branch contains the V2 analysis pipeline and its tooling. It does **not** replace
the `v5.2.x` product pipeline — both live in the same repository and share the same
database, models and Docker packaging.

| | Legacy (`v5.2.x`) | V2 |
|---|---|---|
| Public authority | yes — every user-visible report | no — `public_authority = "legacy"` |
| Writes user data | yes | no — `writes_user_data = false` |
| Output | reports, plans, archives | versioned JSON artifacts under an isolated runtime |
| Runtime | normal application runtime | isolated shadow runtime, bounded local queue |
| Purpose | shipped product | measurable pipeline that can be gated on evidence |

Switching pipelines is a configuration change, not a fork:

```env
SKATING_ANALYSIS_PIPELINE=legacy   # legacy | shadow | v2
```

## Design principles

These are enforced in code, not just documented.

- **Stage order is a contract.** A stage may only consume artifacts from stages to its
  left. Invalidating one stage invalidates every descendant, so a stale cache can never
  silently feed a downstream claim.
- **Nothing is mutated in place.** The completed legacy analysis is passed *into* a shadow
  run as an immutable input. A shadow run is a rebuildable, versioned JSON artifact.
- **Evidence before conclusions.** Reports are only allowed to explain claims that were
  already fused from cited evidence; a claim that cannot cite its inputs cannot be printed.
- **Refusal is a valid result.** Rotation, identity and moment estimators return an explicit
  refusal or an insufficiency flag instead of an unqualified number.
- **Fail closed.** Trial gates, runtime preflight and the contamination sentinel deny by
  default when their preconditions are not met.

## Pipeline

Stage order is defined once in `SHADOW_STAGE_ORDER` and is part of the contract:

```
timebase → observations → candidates → identity → pose → events → moments → rotation → path_reviews → claims
```

| Stage | What it establishes | Key modules |
|---|---|---|
| `timebase` | exact source PTS mapping between requested time, decoded frames and media | `timebase.py` |
| `observations` | bounded decoded observation stream, preserved holes and discontinuities | `detection.py`, `pose_observations.py` |
| `candidates` | person-track candidates with qualification and exclusion rules | `detection.py`, `tracking_states.py` |
| `identity` | identity timeline, conflict intervals, manual anchors and segment re-anchoring | `identity.py`, `evaluation/identity_anchor.py`, `services/segment_reanchor.py` |
| `pose` | identity-authorized pose samples with per-point quality | `pose_v2.py`, `services/pose_quality.py`, `services/pose_geometry.py` |
| `events` | profile-scoped event proposals and revisioned action-label facts | `event_proposals.py`, `event_label_facts.py`, `action_classification.py` |
| `moments` | revisioned, event-scoped takeoff / apex / landing proposals | `profile_moments.py`, `moment_selectors.py`, `event_moment_facts.py` |
| `rotation` | conservative multi-cue projected-turn estimates on exact source PTS | `rotation.py`, `rotation_facts.py`, `services/jump_rotation.py` |
| `path_reviews` | bounded semantic-review adapters over the legacy vision payloads | `path_review.py`, `fusion_inputs.py` |
| `claims` | deterministic claim fusion and the report boundary that explains it | `claim_fusion.py`, `claim_report.py`, `facts.py` |

Everything downstream of `claims` — presentation and the analysis experience — is a
consumer, not a producer: `presentation.py`, `fact_consumers.py`, `comparison.py`.

### Analysis experience (`analysis-experience.v2`)

The V2 user-facing surface is a structured, versioned payload rather than free-form prose:
a summary, a body of sections, a "more" area and a report view. It is served by
`GET /api/analysis-v2/{analysis_id}/experience-v2` and rendered by the
`frontend/src/analysis-v2/` components. Capability discovery reports which experiences a
deployment supports, so the UI degrades instead of guessing.

## Repository layout

```
backend/app/analysis_v2/     V2 pipeline: contracts, stages, orchestration, presentation
backend/app/analysis_v2/evaluation/
                             golden store, gate policy, G2/G8/G9 evaluators, adapters
backend/app/services/        shared services, including V2 tracking / pose / jump helpers
backend/app/trial.py         fail-closed trial gates (see "Trial mode")
backend/app/routers/         analysis_v2.py, segment_reanchor.py and the legacy routers
frontend/src/analysis-v2/    analysis experience, golden workspace, shadow workspace
frontend/src/components/     V2 panels: jump stage replay, rotation, segment re-anchor, trial
docker/allinone/             all-in-one images (standard, analysis, trial)
docs/                        architecture notes, evaluation runbook, plans and specs
scripts/                     release, verification and model-provenance tooling
```

## API surface

V2 routes are mounted on three prefixes: `/api/analysis` (analysis experience and
revisioned facts), `/api/shadow` (shadow orchestration runs) and `/api/golden/v2`
(golden evaluation). Runtime capabilities are reported by `/api/capabilities`.

All routes in this table are under `/api/analysis`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/{analysis_id}/experience-v2` | versioned analysis experience payload |
| GET | `/{analysis_id}/experience-v2/diagnostic` | diagnostic view of the same experience |
| POST | `/growth-admission` | decide whether an analysis may enter growth records |
| GET | `/{analysis_id}/event-proposals` | profile-scoped event proposals |
| POST | `/{analysis_id}/event-proposals/mutate` | revise an event proposal |
| GET/POST | `/{analysis_id}/events/{event_id}/label-facts` | read / propose action-label facts |
| POST | `/{analysis_id}/events/{event_id}/label-facts/{revision}/apply` | apply a label revision |
| POST | `/{analysis_id}/events/{event_id}/label-facts/{revision}/dismiss` | dismiss a label revision |
| GET/POST | `/{analysis_id}/events/{event_id}/moment-proposals` | read / propose T/A/L moments |
| POST | `/{analysis_id}/events/{event_id}/moment-proposals/{revision}/apply` | apply a moment revision |
| POST | `/{analysis_id}/events/{event_id}/moment-proposals/{revision}/dismiss` | dismiss a moment revision |
| GET | `/{analysis_id}/source-frames/{index}/image` | source frame image bound to an observation |
| GET | `/{analysis_id}/observations` | decoded observation stream |
| GET | `/{analysis_id}/identity` | identity timeline and conflict intervals |
| GET | `/{analysis_id}/pose-v2/detail` | pose samples with quality metadata |
| POST | `/{analysis_id}/identity/anchors/preview` | preview a manual identity anchor |
| POST | `/{analysis_id}/identity/anchors/confirm` | confirm an identity anchor |
| GET | `/pilot12-detection`, `/pilot12-event-proposals`, `/pilot14-action-classification` | frozen pilot evaluation inputs |

Manual segment re-anchoring is nested under the same prefix:

| Method | Path | Purpose |
|---|---|---|
| GET | `/{analysis_id}/identity/segments` | saved-evidence segment candidates |
| GET | `/{analysis_id}/identity/segments/images/{observation_index}` | candidate image |
| POST | `/{analysis_id}/identity/segments/preview` | preview a re-anchored segment |
| POST | `/{analysis_id}/identity/segments/confirm` | confirm a re-anchored segment |
| GET | `/{analysis_id}/identity/segments/revisions/{revision}` | read a saved revision |
| GET | `/{analysis_id}/identity/segments/revisions/{revision}/pose` | pose for that revision |
| GET | `/{analysis_id}/identity/segments/revisions/{revision}/images/{filename}` | images for that revision |

Re-anchoring works from **saved evidence only**. It never re-runs the detector, never
restores deleted media and never fabricates a segment that the saved observations cannot
support.

Shadow orchestration runs are exposed under `/api/shadow`, and the golden store,
evaluator status and G2 baseline under `/api/golden/v2`.

## Golden evaluation

V2 is only useful if it can be measured, so evaluation is a first-class subsystem rather
than a test fixture.

- **Frozen golden store** (`evaluation/golden_store.py`, `golden_schema.py`) — versioned
  labelled samples with source media identity and content hashes.
- **Gate policy** (`evaluation/gate_policy.py`) — `golden-gate-policy.v2` defines the
  thresholds and tolerances that a candidate must clear. Policies are versioned so a
  result can always be attributed to the policy that judged it.
- **Metric families** — `g2_baseline.py` (baseline regression), `g8_moments.py`
  (leakage-safe moment aggregation) and `g9_rotation.py` (convention-safe, refusal-aware
  rotation scoring).
- **Pilot evaluator** (`evaluation/pilot_evaluator.py`) with adapters that build proposals
  from source observations only, so the evaluator cannot see resolved labels.

The workflow is documented in [docs/golden-eval-ab-runbook.md](./docs/golden-eval-ab-runbook.md).

## Trial mode

`backend/app/trial.py` implements fail-closed gates for isolated trial deployments. A
profile can be baked into an image (`/etc/skating-trial-profile`) so it cannot be changed
at runtime by an environment variable:

| Profile | Behaviour |
|---|---|
| `off` | normal install; every feature available |
| `web-preview` | read-only preview; video upload and analysis are disabled |
| `legacy-analysis-preview` | existing legacy local analysis only; new diagnostics, shadow, controlled evaluation and external AI are all disabled |

`docker/allinone/Dockerfile.trial` builds the trial image with pinned, hash-locked
requirements (`requirements-trial-web.lock`, `requirements-trial-analysis.lock`), so a
trial install cannot silently resolve different dependency versions.

Trial deployments report `target_nas_verified=false` and `new_diagnostics=false` in their
capabilities payload until someone actually verifies them on the target hardware. The
system does not infer verification from a successful build.

## Deployment

### All-in-one Docker

```bash
docker run -d \
  --name skating-allinone \
  -p 8080:80 \
  -v /path/to/data:/data \
  -v /path/to/backups:/backups \
  -v /path/to/.env:/workspace/.env:ro \
  skating-analyzer-allinone:latest
```

### Docker Compose

```bash
docker compose up -d
```

`.env` needs at minimum:

```env
SECRET_KEY=your-random-secret
```

See [.env.example](./.env.example) for the full set and [.env.v2.example](./.env.v2.example)
for the isolated V2 development layout. Never point the V2 paths at production data.

The Synology step-by-step guide is [SYNOLOGY_STEP_BY_STEP.md](./SYNOLOGY_STEP_BY_STEP.md).

## Development

```bash
# Backend
cd backend
pip install -r requirements.txt
PYTHONPATH=backend uvicorn app.main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```

To run V2 in isolation, copy `.env.v2.example` to `.env.v2.local`, point every path at a
separate runtime directory, and set `SKATING_ANALYSIS_PIPELINE=shadow`.

## Testing

```bash
# Backend — 192 test modules, 55 of them in tests/analysis_v2/
cd backend
pip install -r requirements-test.txt
python -m pytest tests -q -n 4 --dist loadfile

# Frontend — 76 test modules (Vitest)
cd frontend
npm test
```

## Privacy and data handling

- Uploaded videos, extracted frames, databases and backups are runtime data and are never
  committed. `.gitignore` excludes `data/`, `backups/`, `models/`, `deliverables/`, `*.pt`
  and image archives.
- API keys are stored encrypted at rest and are never written to logs in full.
- V2 shadow runs write only inside their own isolated runtime directory. The contamination
  sentinel (`contamination_inventory.py`) snapshots family state before and after a run so
  an unintended write is detected rather than assumed absent.
- This repository contains no family media, no real training videos and no personal data.

## License

MIT License — see [LICENSE](./LICENSE).

The optional Animal Island-inspired interface is adapted from
[guokaigdg/animal-island-ui](https:/github.com/guokaigdg/animal-island-ui) under
CC BY-NC 4.0, for personal non-commercial use, with attribution retained.
