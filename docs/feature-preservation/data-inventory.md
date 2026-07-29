# Iteration 0 Data and Artifact Inventory

## Durable and backup-required

- Source videos, upload metadata, archived media, analyses, reports, notes, target locks, logs, and media renditions.
- Chat messages, correction proposals and decisions, report regeneration history, plans, sessions, analysis/session links, skill state, milestones, XP, memories, and suggestions.
- Monthly chapters and revisions, annual collections and revisions, completed/resumable annual exports, shares, provider configuration and encrypted secrets, parent PIN state, skater profiles, and durable UI settings.
- Private V2 Golden labels, manifest revisions, source references, human confirmations, and any future promoted/audited V2 fact revisions.

## Rebuildable or policy-controlled

- Extracted frames, thumbnails, temporary processing files, local caches, disposable diagnostic overlays, no-op Shadow state, and future reproducible V2 stage artifacts whose run manifests identify their inputs.
- Model files and provider model availability are operational dependencies. They are not user labels, but their hashes, sources, mounts, and fallback states must be reproducible.

## Never committed

- Raw videos, crops, frames, faces, embeddings, private paths/manifests, private Golden labels, provider keys, databases, backups, model outputs, caches, and test runtime data.

## Iteration 0 isolation map

All writable development paths resolve under `C:\Users\qihq\Documents\skating-analyzer-v2-runtime`. The local `.env.v2.local` is ignored by Git and selects a separate SQLite database. The committed `.env.v2.example` is a template only.
