# Feature Preservation Ledger

Iteration 0 generates `ledger.json` from production routes, frontend API exports, ORM models, startup and scheduled work, environment settings, artifacts, packaging entrypoints, and focused tests at baseline commit `c291324`.

Regenerate after an intentional inventory change:

```powershell
python scripts/generate_feature_preservation_ledger.py
```

The checked fingerprint makes unexplained removal of an inventoried production surface fail tests. Entries move only through:

```text
inventoried -> characterized -> adapted -> verified -> retirement-approved
```

`retirement-approved` requires explicit owner approval. Iteration 0 does not use that state.

## Characterization Index

The ledger points each surface to an existing focused test when a name-based match exists, or to an explicit test task in its owning iteration. The following cross-domain fixture groups protect the current product until their semantic inputs migrate:

| Domain | Current fixture groups | Owning migration |
|---|---|---:|
| Analysis lifecycle and media | `test_analysis_*`, `test_target_lock.py`, media frontend tests | 5-14 |
| Chat and corrections | `test_analysis_chat.py`, `test_analysis_corrections.py` | 5, 10-14 |
| Plans and sessions | `test_plan_generation.py`, plan page/hub tests | 5, 11-14 |
| Growth, compare, skills | `test_growth_*`, `test_analysis_compare.py`, `test_skills.py` | 5, 11-14 |
| Memories | Snowball router/service inventory and frontend route smoke; additional fixture task recorded | 5, 14 |
| Monthly and annual | `test_monthly_*`, `test_annual_*`, annual frontend tests | 5, 11-14 |
| Providers and settings | `test_provider_*`, settings/provider route inventory | 0, 5, 14-16 |
| Pose and tracking runtime | `test_person_tracker.py`, pose tests, pipeline tests | 0, 7-9 |
| Backup, restart, packaging | database/archive/provider startup/pack generation tests | 0, 15-17 |
| Historical routes and exports | navigation tests and artifact inventory | 0, 5, 14, 17 |
