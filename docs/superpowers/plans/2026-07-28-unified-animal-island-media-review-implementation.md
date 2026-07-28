# Unified Animal Island Media and Review Implementation Plan

**Design:** `docs/superpowers/specs/2026-07-28-unified-animal-island-media-review-design.md`

**Goal:** Unify navigation state, sampling completeness, video and pose playback, sharing, and asynchronous submit feedback while directly using `animal-island-ui@1.3.0` controls.

**Delivery strategy:** Implement in dependency-ordered batches. Preserve existing business logic and old UI paths until each replacement has focused tests and all call sites are migrated. Commit each task independently so a regression can be reverted without discarding later unrelated work.

## Global Rules

- Preserve the user's untracked `backups/` and `output/` content.
- Keep existing API contracts backward compatible; add fields and query parameters rather than changing current meanings.
- Do not add a database migration for media renditions. Store a versioned `media-manifest.json` beside each analysis video and derive API responses from it.
- Do not upscale video. Omit 1080p or 720p entries when the original is smaller.
- Do not delete old player/share code until repository searches show no remaining production call sites.
- Use package components through `frontend/src/modern/AnimalUi.tsx`; do not duplicate their markup or loading animation in project CSS.
- Every asynchronous effect must clean up timers, animation frames, listeners, object URLs, and stale promise updates.
- All new animation must have a static `prefers-reduced-motion` path.

## Task 1: Baseline Characterization and Navigation State

**Status:** Complete (2026-07-28)

**Verification:** `npm test -- src/navigation.test.ts src/modern/ModernNavigation.test.tsx` (6 passed); `npm run build` passed.

**Implementation notes:** Inactive Start Review no longer owns a primary border, fill, or raised shadow. The yellow primary treatment now applies only with `is-active` on both the mobile dock and desktop rail.

**Files:**

- Modify: `frontend/src/navigation.test.ts`
- Modify: `frontend/src/modern/ModernNavigation.tsx`
- Modify: `frontend/src/modern/modern-island.css`
- Add: `frontend/src/modern/ModernNavigation.test.tsx`

**Work:**

1. Add route-mapping cases for `/review`, `/analysis/:id`, `/report/:id`, `/home`, `/growth`, and `/me`.
2. Render both `IslandDock` and `IslandRail` in tests and assert that Start Review receives `is-active` only in the Review space.
3. Remove border, fill, and raised shadow from inactive `island-dock__item--primary` and `island-rail__item--primary` styles.
4. Scope the yellow raised treatment to `.island-*-item--primary.is-active` only.
5. Verify keyboard focus remains visible independently of selection.

**Verification:**

```powershell
Set-Location frontend
npm test -- src/navigation.test.ts src/modern/ModernNavigation.test.tsx
```

**Commit:** `fix: show review navigation active state only on review routes`

## Task 2: Original-Library Adapter and Submit State Machine

**Status:** Complete (2026-07-28)

**Verification:** `npm test -- src/hooks/useSubmitAction.test.tsx src/modern/SubmitButton.test.tsx` (4 passed); `npm run build` passed.

**Implementation notes:** Added a shared duplicate-safe submit state machine and a `SubmitButton` backed by the installed Animal Island Button. It uses the package loading animation, emits original-library error notifications, and adds only the IceBuddy success check/bounce with a reduced-motion fallback. Page-by-page migration remains Task 14.

**Files:**

- Modify: `frontend/src/modern/AnimalUi.tsx`
- Add: `frontend/src/hooks/useSubmitAction.ts`
- Add: `frontend/src/hooks/useSubmitAction.test.tsx`
- Add: `frontend/src/modern/SubmitButton.tsx`
- Add: `frontend/src/modern/SubmitButton.test.tsx`
- Modify: `frontend/src/modern/modern-island.css`
- Modify: `frontend/src/index.css`

**Work:**

1. Re-export typed package components and types needed by media UI: Button, Progress, Tooltip, Select, Modal, Loading, and Notification.
2. Add a `useSubmitAction` hook with `idle`, `submitting`, `success`, and `error` states; prevent concurrent execution and ignore completion after unmount.
3. Add `SubmitButton`, backed by the original package Button, that supplies loading text, success check, error restoration, and accessible live status.
4. Use the package `loading` prop for moving stripes; add only the IceBuddy success state and classic-theme variable overrides locally.
5. In reduced-motion mode, remove moving stripes/bounce and retain explicit status text.
6. Keep legacy `.island-button` rules temporarily for unmigrated call sites.

**Verification:**

```powershell
Set-Location frontend
npm test -- src/hooks/useSubmitAction.test.tsx src/modern/SubmitButton.test.tsx
npm run build
```

**Commit:** `feat: add shared animal island submit feedback`

## Task 3: Profile-Aware Dense Base Sampling

**Status:** Complete (2026-07-28)

**Verification:** `python -m pytest backend/tests/test_video_sampling_density.py backend/tests/test_analysis_profile_input.py -q` (27 passed).

**Implementation notes:** Sampling now uses action-profile base counts and duration scaling on the normalized action timeline. The persisted motion payload records requested/resolved counts, cap, and policy so follow-up diagnostics can distinguish configured density from frames actually extracted. Manual windows use their approved dense caps, and free-skate inputs retain a bounded duration-based fallback.

**Files:**

- Modify: `backend/app/configs/action_profiles.json`
- Modify: `backend/app/services/video.py`
- Add: `backend/tests/test_video_sampling_density.py`
- Modify: `.env.example`

**Work:**

1. Replace fixed profile counts with a helper that accepts profile, analyzed duration, and manual-window state.
2. Implement the approved counts:
   - jump: 48 base, 64 manual;
   - spin: 36 through six seconds, plus four per additional second, cap 52, manual cap 64;
   - step: 32 through eight seconds, plus three per additional second, cap 48, manual cap 56;
   - spiral: 28 through six seconds, plus three per additional second, cap 40, manual cap 48;
   - free skate: four per second, minimum 32, maximum 64.
3. Round duration-scaled counts upward and clamp counts to the profile cap.
4. Keep environment/config overrides explicit and record the resolved policy in `frame_motion_scores`.
5. Update sampling metadata with `requested_sample_count`, `resolved_sample_count`, `sampling_density_policy`, and profile cap.
6. Test exact boundary durations, fractional seconds, manual windows, slow-motion effective duration, and configuration overrides.

**Verification:**

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m pytest backend/tests/test_video_sampling_density.py backend/tests/test_analysis_profile_input.py -q
```

**Commit:** `feat: increase profile-aware action sampling density`

## Task 4: Temporal Supplemental Frames and Coverage Diagnostics

**Status:** Complete (2026-07-28)

**Verification:** `python -m pytest backend/tests/test_evidence_frames.py backend/tests/test_semantic_keyframe_pipeline.py backend/tests/test_analysis_video_temporal_pipeline.py -q` (233 passed, 4 subtests passed).

**Implementation notes:** A versioned `evidence_frames_v1` ledger now retains base motion frames, MiMo phase/key-moment windows, resolved/partial semantic frames, and pose T/A/L candidates as separate evidence groups, even when they conflict. It records action-window coverage, maximum temporal gap, per-stage completeness, T/A/L ordering, source diversity, and insufficiency. Non-base timestamps are deduplicated against sampled frames by source-FPS tolerance and materialized once into `semantic_frames/`; any unavailable stage remains explicitly marked insufficient instead of silently discarded.

**Files:**

- Add: `backend/app/services/evidence_frames.py`
- Add: `backend/tests/test_evidence_frames.py`
- Modify: `backend/app/services/video_temporal.py`
- Modify: `backend/app/services/semantic_keyframe_pipeline.py`
- Modify: `backend/app/routers/analysis.py`
- Modify: `backend/tests/test_analysis_video_temporal_pipeline.py`
- Modify: `backend/tests/test_semantic_keyframe_pipeline.py`

**Work:**

1. Introduce typed internal records for timestamp, frame ID, phase, source, confidence, and selection reason.
2. Build supplemental timestamp windows from MiMo phase segments and key moments. For T/A/L, include the center plus profile/FPS-aware neighbors before and after it.
3. Extract supplements into `semantic_frames/` with stable IDs and deduplicate against base frames using a timestamp tolerance derived from source FPS.
4. Merge base motion, MiMo temporal, pose candidate, manual, and retry evidence without dropping a conflicting coherent group.
5. Compute and persist:
   - analyzed-window coverage ratio;
   - largest time gap;
   - required-stage completeness;
   - T/A/L ordering and continuity;
   - per-stage counts and source diversity.
6. If a required phase is missing or coverage fails its profile threshold, expand only that phase window once and extract a bounded retry set.
7. Persist `stage_evidence_insufficient` when the bounded retry does not recover the phase.
8. Preserve existing `selected` fields for compatibility and add a versioned `evidence_frames_v1` section to `frame_motion_scores`.
9. Cover the known conflict pattern where pose/motion T/A/L and MiMo T/A/L differ by roughly one second; assert both groups survive.

**Verification:**

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m pytest backend/tests/test_evidence_frames.py backend/tests/test_semantic_keyframe_pipeline.py backend/tests/test_analysis_video_temporal_pipeline.py -q
```

**Commit:** `feat: supplement action evidence from mimo stages`

## Task 5: Stage-Balanced Path B Input

**Status:** Complete (2026-07-28)

**Verification:** `python -m pytest backend/tests/test_vision_path_b.py backend/tests/test_vision_dual.py backend/tests/test_vision_weighted_fusion_integration.py -q` (24 passed).

**Implementation notes:** Path B now uses a configurable 16-frame safety cap (`PATH_B_MAX_FRAMES`) and reserves up to three frames for each required action stage before adding chronological context. Distinct MiMo and pose candidate windows are retained unless they resolve to the same sampled timestamp. Prompt labels expose evidence source/phase/reason, and dual-path metadata records stage counts, evidence sources, omitted context, and the cap reason. Uniform sampling remains only when phase-aware evidence is unavailable.

**Files:**

- Modify: `backend/app/services/vision_path_b.py`
- Modify: `backend/app/services/vision_dual.py`
- Modify: `backend/tests/test_vision_path_b.py`
- Modify: `backend/tests/test_vision_dual.py`
- Modify: `backend/tests/test_vision_weighted_fusion_integration.py`

**Work:**

1. Replace `PATH_B_MAX_FRAMES = 10` fallback selection with a configurable safety cap and phase quotas.
2. Select required core stages before approach/preparation context.
3. Include both conflicting coherent T/A/L candidate windows when available; deduplicate only timestamp-equivalent frames.
4. Pass provenance and phase labels into Path B prompt context without changing its public output schema.
5. Record input count, per-stage count, sources, omitted-context count, and cap reason in dual-path metadata.
6. Keep legacy uniform fallback only when neither semantic nor phase-aware evidence exists.
7. Test that a preparation-heavy source cannot consume the entire budget and that T/A/L remain represented.

**Verification:**

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m pytest backend/tests/test_vision_path_b.py backend/tests/test_vision_dual.py backend/tests/test_vision_weighted_fusion_integration.py -q
```

**Commit:** `feat: balance skeleton vision frames by action stage`

## Task 6: Media Rendition Manifest and Transcoding

**Files:**

- Add: `backend/app/services/media_renditions.py`
- Add: `backend/tests/test_media_renditions.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/routers/analysis.py`
- Add: `backend/tests/test_analysis_media_routes.py`
- Modify: `backend/tests/test_analysis_video_temporal_pipeline.py`
- Modify: `.env.example`

**Manifest contract:**

```json
{
  "schema_version": "analysis_media.v1",
  "status": "processing",
  "sources": [
    {"quality":"original","status":"ready","width":1920,"height":1080,"url":"/api/analysis/{id}/video?quality=original"},
    {"quality":"1080p","status":"processing","width":1920,"height":1080,"url":null}
  ]
}
```

**Work:**

1. Probe original width, height, codecs, duration, and bitrate and write `media-manifest.json` atomically beside the video.
2. Generate 1080p, 720p, and 480p MP4 renditions with seek-friendly keyframe intervals, web-compatible H.264/AAC, and fast-start metadata.
3. Skip upscales and redundant same-size renditions. Record each quality independently as pending, processing, ready, or failed.
4. Add `MediaManifest`/`MediaSource` schemas and expose the manifest on `AnalysisDetail` plus `GET /analysis/{id}/media`.
5. Extend `GET /analysis/{id}/video` with a validated `quality` query parameter. Preserve the existing no-query behavior as Original and retain byte-range support.
6. Run analysis and rendition generation concurrently through one background wrapper; isolate failures so neither task marks the other failed.
7. For legacy analyses, lazily create an Original-only manifest on read and provide an explicit endpoint/service path to generate missing renditions.
8. Keep archived-video lookup compatible and resolve rendition paths only inside the analysis directory.
9. Test no-upscale behavior, atomic manifest writes, partial failures, path validation, Original fallback, and legacy records.

**Verification:**

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m pytest backend/tests/test_media_renditions.py backend/tests/test_analysis_media_routes.py backend/tests/test_analysis_video_temporal_pipeline.py -q
```

**Commit:** `feat: add analysis video quality renditions`

## Task 7: Frontend Media Types and Controller

**Files:**

- Modify: `frontend/src/api/client.ts`
- Add: `frontend/src/media/types.ts`
- Add: `frontend/src/media/useMediaController.ts`
- Add: `frontend/src/media/useMediaController.test.tsx`
- Add: `frontend/src/media/qualitySelection.ts`
- Add: `frontend/src/media/qualitySelection.test.ts`
- Add: `frontend/src/media/formatTime.ts`
- Add: `frontend/src/media/formatTime.test.ts`

**Work:**

1. Add typed media manifest/source data to `AnalysisDetail` and an API helper for manifest refresh.
2. Build a controlled media state machine for duration, current time, paused state, buffering, buffered ranges, volume, mute, rate, quality, full screen, picture-in-picture, and errors.
3. Separate preview time from committed media time during pointer drag.
4. Throttle preview updates and commit one exact seek on pointer release or keyboard activation.
5. Implement source switching that captures state, waits for metadata, seeks, restores rate/volume/mute, and resumes only if previously playing.
6. Restore the previous source and state if switching fails.
7. Implement Auto selection from viewport, DPR, connection hints, and buffering history; manual selection remains pinned.
8. Unit-test stale source events, rapid switches, seek clamping, failed play promises, unmount cleanup, and state restoration.

**Verification:**

```powershell
Set-Location frontend
npm test -- src/media/useMediaController.test.tsx src/media/qualitySelection.test.ts src/media/formatTime.test.ts
```

**Commit:** `feat: add shared media playback controller`

## Task 8: Timeline and Animal Island Media Controls

**Files:**

- Add: `frontend/src/media/MediaTimeline.tsx`
- Add: `frontend/src/media/MediaTimeline.test.tsx`
- Add: `frontend/src/media/MediaControls.tsx`
- Add: `frontend/src/media/MediaControls.test.tsx`
- Add: `frontend/src/media/media-player.css`
- Modify: `frontend/src/modern/AnimalUi.tsx`

**Work:**

1. Build a semantic slider timeline with buffered ranges, preview/commit callbacks, keyboard seeking, marker labels, and previous/next marker actions.
2. Render T/A/L and other markers from a normalized marker model.
3. Build controls entirely from original Animal Island Button, Tooltip, Select, Progress, Loading, and Notification surfaces.
4. Add play/pause, five-second seek, frame step, mute/volume, speed, quality, picture-in-picture, and full-screen commands.
5. Implement one semantic DOM order with CSS rearrangement at phone, tablet, and desktop breakpoints.
6. Put quality, speed, and secondary actions in a phone overflow dialog/menu while leaving marker navigation directly available.
7. Ensure 44px touch targets, visible focus, accessible labels, and reduced-motion behavior.

**Verification:**

```powershell
Set-Location frontend
npm test -- src/media/MediaTimeline.test.tsx src/media/MediaControls.test.tsx
npm run build
```

**Commit:** `feat: add responsive animal island media controls`

## Task 9: Video and Pose Surfaces

**Files:**

- Add: `frontend/src/media/VideoSurface.tsx`
- Add: `frontend/src/media/VideoSurface.test.tsx`
- Add: `frontend/src/media/PoseSurface.tsx`
- Add: `frontend/src/media/PoseSurface.test.tsx`
- Add: `frontend/src/media/poseTimeline.ts`
- Add: `frontend/src/media/poseTimeline.test.ts`
- Add: `frontend/src/media/IceMediaPlayer.tsx`
- Add: `frontend/src/media/IceMediaPlayer.test.tsx`
- Modify: `frontend/src/components/PoseViewer.tsx`

**Work:**

1. Add `VideoSurface` as the only component that owns the HTML video element and forwards media events to the controller.
2. Extract pose Canvas drawing from `PoseViewer` into a controlled `PoseSurface` that receives a timestamp/frame selection and does not own playback.
3. Resolve pose frames from persisted `frame_timestamps` using binary search.
4. Interpolate only short reliable gaps; hold the last reliable frame and report a data gap for longer or low-confidence gaps.
5. Compose surface, controls, timeline, loading, and errors in `IceMediaPlayer`.
6. Support video-only, pose-only, and video-with-pose-overlay modes using one controller contract.
7. Keep `PoseViewer` as a compatibility wrapper until all call sites migrate, but route its controls through `IceMediaPlayer` rather than its old 200ms animation loop.

**Verification:**

```powershell
Set-Location frontend
npm test -- src/media/VideoSurface.test.tsx src/media/PoseSurface.test.tsx src/media/poseTimeline.test.ts src/media/IceMediaPlayer.test.tsx src/utils/poseCanvas.test.ts
```

**Commit:** `feat: unify video and skeleton playback surfaces`

## Task 10: Analysis and Keyframe Player Migration

**Files:**

- Modify: `frontend/src/components/ModernAnalysisWorkspace.tsx`
- Modify: `frontend/src/components/ActionPhaseStrip.tsx`
- Modify: `frontend/src/components/KeyframeEvidencePanel.tsx`
- Modify: `frontend/src/components/CorrectionKeyframeReview.tsx`
- Modify: `frontend/src/components/AnalysisDebugLogPanel.tsx`
- Modify: `frontend/src/pages/ReportWorkspacePage.tsx`
- Modify: `frontend/src/pages/PoseDebugPage.tsx`
- Modify: `frontend/src/pages/DebugPage.tsx`
- Modify existing focused tests and add missing component tests beside each migrated component.

**Work:**

1. Normalize analysis T/A/L, semantic, partial, and report markers through a shared marker adapter.
2. Replace page-local `<video>` controls and range inputs with `IceMediaPlayer`.
3. Replace manual `currentTime` writes with controller seeks while preserving existing keyframe buttons.
4. Use one video-pose player in Modern Analysis; keep diagnostic hover overlays as a surface extension.
5. Migrate debug pages without hiding technical metadata or parent-only controls.
6. Verify old URLs, selected frame IDs, route query state, and follow-up correction workflows remain unchanged.
7. Remove compatibility fallbacks only when every production `<video>` outside comparison has migrated.

**Verification:**

```powershell
Set-Location frontend
npm test -- src/components/ActionPhaseStrip.test.tsx src/components/CorrectionKeyframeReview.test.tsx src/components/ModernAnalysisWorkspace.test.tsx src/components/KeyframeEvidencePanel.test.tsx
npm run build
```

**Commit:** `refactor: migrate analysis playback to shared player`

## Task 11: Synchronized Comparison Playback

**Files:**

- Add: `frontend/src/media/useSynchronizedMediaGroup.ts`
- Add: `frontend/src/media/useSynchronizedMediaGroup.test.tsx`
- Modify: `frontend/src/pages/ComparePage.tsx`
- Add: `frontend/src/pages/ComparePage.test.tsx`

**Work:**

1. Move `prepareVideoForSync`, `seekVideoTo`, comparable-window mapping, rate compensation, and drift correction behind a shared synchronized-group interface.
2. Make explicit seeks exact for both players and keep playback-time drift correction conservative.
3. Preserve current before/after comparable windows and T/A/L pair jumps.
4. Give each video its own quality selection while group play/pause/seek remains synchronized.
5. Restore both players coherently when one source switch fails.
6. Replace comparison page video elements and page-local controls with paired `IceMediaPlayer` instances connected to the group.

**Verification:**

```powershell
Set-Location frontend
npm test -- src/media/useSynchronizedMediaGroup.test.tsx src/pages/ComparePage.test.tsx
```

**Commit:** `refactor: unify synchronized comparison playback`

## Task 12: Multipage Adaptive Share Engine

**Files:**

- Refactor: `frontend/src/utils/shareCanvas.ts`
- Add: `frontend/src/utils/shareLayout.ts`
- Add: `frontend/src/utils/shareLayout.test.ts`
- Add: `frontend/src/utils/shareExport.ts`
- Add: `frontend/src/utils/shareExport.test.ts`
- Modify: `frontend/src/modern/IslandShareDialog.tsx`
- Add: `frontend/src/modern/IslandShareDialog.test.tsx`

**Work:**

1. Define one share document model for title, summary, sections, paragraphs, lists, images, captions, metadata, and footer.
2. Split layout into measure and render passes.
3. Measure wrapped lines and block geometry before allocating Canvas height.
4. Grow ordinary cards to content height. At the safe-image threshold, paginate only between semantic blocks or legal paragraph/list boundaries.
5. Keep headings with following content and keep images with captions; never split a text line or image.
6. Return a multipage preview/result type while retaining a one-page compatibility adapter until all callers migrate.
7. Add page count, page selection, download-current, download-all, native multi-file share, and bundled fallback actions to `IslandShareDialog`.
8. Preserve successful pages on partial failure and expose a retry for failed pages.
9. Revoke every page object URL on replacement/unmount.

**Verification:**

```powershell
Set-Location frontend
npm test -- src/utils/shareLayout.test.ts src/utils/shareExport.test.ts src/modern/IslandShareDialog.test.tsx
```

**Commit:** `feat: add content-adaptive multipage sharing`

## Task 13: Migrate Every Share Source

**Files:**

- Modify: `frontend/src/pages/ReportPage.tsx`
- Modify: `frontend/src/components/AnalysisFollowUpPanel.tsx`
- Modify: `frontend/src/pages/ProgressPage.tsx`
- Modify: `frontend/src/pages/ComparePage.tsx`
- Modify: `frontend/src/pages/PlanPage.tsx`
- Modify: `frontend/src/components/MilestoneShareDialog.tsx`
- Modify: `frontend/src/pages/MonthlyChaptersPage.tsx`
- Modify: `frontend/src/pages/AnnualCollectionPage.tsx`
- Remove after migration: `frontend/src/utils/milestoneShareCanvas.ts`
- Update corresponding tests.

**Work:**

1. Add one domain-to-share-document adapter per source.
2. Move report and follow-up sharing off their private Canvas and preview implementations first.
3. Migrate progress, comparison, plan, milestone, monthly, and annual cards to the same result/dialog contract.
4. Keep annual cover plus full PDF; the cover uses the shared renderer.
5. Test unusually long Chinese text, long unbroken values, missing images, multiple keyframes, and multi-page native-share fallbacks for every source family.
6. Search for `createChatShareImage`, `createReportShareImage`, `createMilestoneShareImage`, and direct share Canvas sizing; remove implementations only after no production references remain.

**Verification:**

```powershell
Set-Location frontend
npm test -- src/components/MilestoneShareDialog.test.tsx src/utils/shareLayout.test.ts src/utils/shareExport.test.ts src/pages/AnnualCollectionPage.test.tsx src/pages/MonthlyChaptersPage.test.tsx src/pages/ReviewPage.test.tsx
npm run build
```

Delete `frontend/src/utils/milestoneShareCanvas.test.ts` together with the retired renderer after its source adapter is covered by `MilestoneShareDialog.test.tsx` and the shared layout/export suites.

**Commit:** `refactor: unify all animal island share cards`

## Task 14: Migrate Asynchronous Submit and Save Buttons

**Files:**

- Modify: `frontend/src/pages/UploadPage.tsx`
- Modify: `frontend/src/pages/TargetSelectionPage.tsx`
- Modify: `frontend/src/components/AnalysisFollowUpPanel.tsx`
- Modify: `frontend/src/modern/GrowthCompareHub.tsx`
- Modify: `frontend/src/pages/ComparePage.tsx`
- Modify: `frontend/src/pages/PlanPage.tsx`
- Modify: `frontend/src/pages/MonthlyChaptersPage.tsx`
- Modify: `frontend/src/pages/AnnualCollectionPage.tsx`
- Modify: `frontend/src/pages/SettingsPage.tsx`
- Modify: `frontend/src/pages/ParentSetupPage.tsx`
- Modify: `frontend/src/components/ParentPinVerifyModal.tsx`
- Modify: `frontend/src/components/ParentUnlockModal.tsx`
- Modify: `frontend/src/components/RetryAnalysisConfirmSheet.tsx`
- Modify: `frontend/src/components/DeleteAnalysisModal.tsx`
- Inspect and migrate when asynchronous: `frontend/src/pages/ArchivePage.tsx`, `frontend/src/pages/HistoryPage.tsx`, `frontend/src/pages/ReportPage.tsx`, `frontend/src/pages/ReviewPage.tsx`, `frontend/src/pages/SnowballPage.tsx`, `frontend/src/pages/DebugPage.tsx`, and `frontend/src/components/AppModeContext.tsx`
- Add: `frontend/src/test/submitActions.test.tsx` or focused tests beside complex forms.
- Remove obsolete `.island-button` rules from `frontend/src/modern/modern-island.css` after the final call-site search.

**Work:**

1. Run `rg -l -F 'type="submit"' frontend/src -g '*.tsx'` plus a state-name search for saving/generating/retrying/sending/working before and after migration; every result must be classified as asynchronous mutation, synchronous form, or non-submit control.
2. Migrate actual asynchronous mutations to `SubmitButton`/`useSubmitAction` without altering validation or navigation behavior.
3. Start with Upload, target confirmation, follow-up send/corrections, comparison creation/retry, plan generation, monthly/annual generation, settings save, and parent PIN flows.
4. Leave navigation, dialog-close, marker, and playback controls as ordinary package Buttons.
5. Ensure failed actions retain inputs and show a useful Animal Island notification.
6. Verify duplicate clicks trigger exactly one request.
7. Remove local button/loading CSS only after `rg` reports no production `.island-button` call sites.

**Verification:**

```powershell
Set-Location frontend
npm test
npm run build
```

**Commit:** `refactor: unify asynchronous action feedback`

## Task 15: Cleanup, Documentation, and Full Verification

**Files:**

- Modify: `README.md`
- Modify: `README.zh.md`
- Modify: `.env.example`
- Modify: `frontend/src/modern/ModernMeSpace.tsx` only if attribution wording needs the added directly-used components clarified.
- Remove obsolete media/share helpers and CSS proven unused by repository search.

**Work:**

1. Document quality rendition storage, transcode settings, profile sampling density, player controls, and share pagination.
2. Retain and clarify `guokaigdg/animal-island-ui` attribution and CC BY-NC 4.0 use.
3. Search for remaining production `<video>`, native `controls`, page-local range timelines, `PoseViewer` playback loops, old share renderers, and `.island-button` controls; explain any intentional exception in code comments/tests.
4. Reanalyze the known conflict video and inspect persisted evidence diagnostics for both candidate windows and T/A/L completeness.
5. Verify rendition playback and state-preserving quality switches against the local backend.
6. Verify phone, tablet portrait/landscape, desktop, and wide desktop layouts, including PWA safe areas and reduced motion.

**Backend verification:**

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m pytest backend/tests -q
```

**Frontend verification:**

```powershell
Set-Location frontend
npm test
npm run build
```

**Static checks:**

```powershell
Set-Location C:\Users\qihq\Documents\skating-analyzer
git diff --check
rg -n '<video| controls(=|\s|>)|createChatShareImage|createReportShareImage|createMilestoneShareImage|className="[^"]*island-button' frontend/src -g '*.tsx' -g '*.ts'
```

**Manual viewport matrix:**

- 375px phone: timeline drag, marker taps, overflow controls, share page selector, upload submit states.
- 768px tablet portrait: player control wrapping, modal/bottom-sheet transitions, keyframe jumps.
- 1024px tablet landscape: split analysis layout, video-pose sync, comparison sync.
- 1280px desktop: full control row, hover preview, precise time input, quality switch.
- 1440px wide desktop: analysis and debug workspaces without excessive stretching or overflow.

**Final acceptance:**

- Start Review is visually active only in Review routes.
- Jump sampling resolves to 48/64 and the known conflict retains both evidence windows.
- Path B receives stage-balanced evidence with T/A/L represented or an explicit insufficiency warning.
- Auto, Original, 1080p, 720p, and 480p behave according to source availability; switching preserves playback state.
- Normal video, pose, and comparison share the same control/timeline behavior.
- Every share source grows or paginates without clipped text.
- Async submits prevent duplicates and show accessible loading/success/error states.
- Full backend tests, frontend tests, and production build pass.

**Commit:** `docs: document unified media review experience`

## Rollback Boundaries

- Tasks 1-2 are frontend-only and can revert independently.
- Tasks 3-5 alter analysis evidence selection but remain backward compatible through existing fields and can be disabled via profile/config flags during rollout.
- Task 6 adds files and API fields without changing Original playback; disabling rendition generation restores old behavior.
- Tasks 7-11 migrate one surface at a time; compatibility wrappers keep unmigrated pages working.
- Tasks 12-13 retain a single-page compatibility adapter until the last share source migrates.
- Task 14 removes legacy styles only after all dependent call sites are gone.

## Recommended Execution Batches

1. **Foundation:** Tasks 1-2.
2. **Analysis quality:** Tasks 3-5.
3. **Media backend:** Task 6.
4. **Player core:** Tasks 7-9.
5. **Player migration:** Tasks 10-11.
6. **Sharing:** Tasks 12-13.
7. **System-wide actions and release:** Tasks 14-15.

Run the focused verification after every task and the full suites at the end of every batch. Do not begin cleanup/removal work while a compatibility consumer remains.
