# Iteration 0 Data and Artifact Inventory

## Durable and backup-required

- Source videos, upload metadata, archived media, analyses, reports, notes, target locks, logs, and media renditions.
- Chat messages, correction proposals and decisions, report regeneration history, plans, sessions, analysis/session links, skill state, milestones, XP, memories, and suggestions.
- Monthly chapters and revisions, annual collections and revisions, completed/resumable annual exports, shares, provider configuration and encrypted secrets, parent PIN state, skater profiles, and durable UI settings.
- Private V2 Golden labels, manifest revisions, source references, human confirmations, and any future promoted/audited V2 fact revisions.
- Canonical source references in analyses, shares, exports, comparisons, monthly chapters, and annual collections. A durable reference includes the source hash, source frame index, exact PTS when available, timing status, and timeline fingerprint; cleanup must retain the referenced source video.

## Rebuildable or policy-controlled

- Extracted frames, thumbnails, temporary processing files, local caches, disposable diagnostic overlays, no-op Shadow state, and future reproducible V2 stage artifacts whose run manifests identify their inputs.
- Source-frame indexes, dense observation streams, playback renditions, extracted refinement frames, and coordinate-overlay caches are rebuildable from a durable source reference plus the original source video. Cleanup may remove them only if it leaves enough metadata to rebuild them safely.
- Model files and provider model availability are operational dependencies. They are not user labels, but their hashes, sources, mounts, and fallback states must be reproducible.

## Never committed

- Raw videos, crops, frames, faces, embeddings, private paths/manifests, private Golden labels, provider keys, databases, backups, model outputs, caches, and test runtime data.

## Iteration 0 isolation map

All writable development paths resolve under `C:\Users\qihq\Documents\skating-analyzer-v2-runtime`. The local `.env.v2.local` is ignored by Git and selects a separate SQLite database. The committed `.env.v2.example` is a template only.

## Iteration 6 backup and cleanup policy

- Backup/restore must preserve source videos, source hashes, canonical source references, media manifests, published snapshot references, and authorization metadata. Rebuildable indexes and observation files may be omitted.
- Source deletion is rejected while a durable analysis, share, export, comparison, chapter, or annual snapshot still references that source unless the existing product deletion flow removes or tombstones those references atomically.
- Legacy references remain readable through an explicit `approximate_legacy` adapter. They are never relabeled as exact V2 source evidence during restore, export, or regeneration.
- A rebuilt source index must match the stored source hash and timeline fingerprint before it can replace an existing cache. Mismatch is an explicit unavailable/stale state, not an implicit repair.
