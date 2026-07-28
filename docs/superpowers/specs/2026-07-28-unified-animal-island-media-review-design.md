# Unified Animal Island Media and Review Design

**Date:** 2026-07-28  
**Status:** Approved  
**Scope:** Navigation selection, action-frame coverage, sharing, submit feedback, and all video/pose playback surfaces

## Goals

- Make Start Review look selected only within the Review space.
- Preserve complete action evidence by combining dense motion sampling with MiMo temporal stages instead of choosing one source.
- Use the installed `animal-island-ui@1.3.0` components directly for controls and feedback.
- Give normal video, comparison video, keyframe review, and skeleton playback one responsive player contract.
- Provide Auto, Original, 1080p, 720p, and 480p playback quality while preserving playback state during switches.
- Migrate all share sources to one Animal Island renderer with measured height and semantic pagination.
- Give every asynchronous submit/save action consistent loading, success, and failure feedback.

## Constraints

- Preserve classic and modern route behavior and existing analysis data.
- Classic and modern UI share player structure and behavior; only theme variables differ.
- Use the original Animal Island Button, Progress, Tooltip, Select/Dropdown, Modal, and Loading components through the project adapter rather than visually copying them.
- Retain CC BY-NC 4.0 attribution and keep the application personal and non-commercial while those components and assets remain in use.
- Respect `prefers-reduced-motion` throughout.
- Do not discard working analysis, canvas drawing, or comparison synchronization logic merely because presentation is being unified.

## Existing Behavior and Migration Boundary

The current application contains several generations of implementation:

- Modern navigation marks Start Review as `primary` at all times. Its inactive primary CSS still adds a border, filled background, and raised shadow, which visually resembles selection.
- Video surfaces mix native browser controls, page-specific custom timelines, and page-local comparison synchronization.
- `PoseViewer` owns a separate `requestAnimationFrame` playback loop.
- Monthly, annual, and plan sharing use the newer dialog, while report and follow-up sharing still own separate Canvas renderers and preview dialogs.
- Some submit actions use the Animal Island Button adapter; others use ordinary buttons with changed label text.
- Motion sampling, temporal video analysis, and semantic-frame resolution exist, but an unreliable semantic result causes the pipeline to replace semantic frames with sampled frames. Path B then caps its fallback input at ten frames.

Migration preserves domain behavior and progressively replaces duplicate presentation and state management:

- Existing video URLs, marker data, analysis result schemas, pose drawing, and comparison synchronization algorithms remain authoritative.
- Page-local media state moves into a shared controller before old controls are removed.
- `PoseViewer` remains the skeleton renderer but becomes controlled by the shared timeline.
- Old share generators and local `.island-button` styles are removed only after their call sites reach zero and tests cover the replacements.

## Architecture

### Animal Island Adapter

`frontend/src/modern/AnimalUi.tsx` becomes the sole application adapter for the installed package. It re-exports the selected original components and supplies project defaults for accessible labels, Chinese copy, icons, submit state, and theme variables.

The adapter must not reproduce package markup or animation in local CSS. Modern UI uses original Animal Island variables. Classic UI supplies an alternate variable set while retaining the same component structure, sizing, layout, pressed feedback, and loading animation.

### Shared Player

The unified player consists of independently testable units:

- `MediaController`: play state, current time, duration, seek lifecycle, volume, mute, playback rate, buffering, full screen, picture-in-picture, source quality, and errors.
- `MediaTimeline`: pointer/keyboard seeking, buffered ranges, time display, hover/drag preview, and markers.
- `MediaControls`: original Animal Island buttons, tooltips, quality selector, speed selector, and responsive overflow menu.
- `VideoSurface`: an HTML video renderer and quality-source switcher.
- `PoseSurface`: a controlled pose Canvas renderer driven by real timestamps.
- `SynchronizedMediaGroup`: shared play/pause/seek operations and drift correction for video-pose and comparison pairs.

Feature pages provide sources, markers, and labels; they do not implement playback mechanics.

### Sampling and Evidence

Motion-weighted sampled frames and MiMo temporal stages become complementary evidence inputs. The pipeline records each frame's timestamp, source, stage, and selection reason, then constructs a stage-balanced union for vision and pose analysis.

The semantic reliability result affects confidence and diagnostics, not whether temporal frames are erased. Conflicting candidate groups survive until fusion so visual evidence, pose evidence, temporal continuity, and stage coverage can score them together.

### Share Engine

One share adapter model represents title, summary, sections, keyframe images, source metadata, and footer attribution. Every share source maps domain data into this model, and a single renderer performs layout measurement, pagination, export, and preview.

## Navigation Selection

Route-to-space mapping remains the source of truth. Start Review is active for `/review`, `/analysis`, and `/report` routes and inactive elsewhere.

Inactive Start Review has the same neutral weight as other inactive destinations: no yellow fill, emphasis border, or raised shadow. Its icon and label remain recognizable but not selected. The raised yellow primary appearance is applied only together with `is-active` on both the mobile dock and desktop rail.

Tests cover representative review, analysis, report, home, growth, and me paths.

## Player Interaction and Responsive Layout

### Common Capabilities

- Play/pause, seek, back/forward five seconds, previous/next marker, frame step backward/forward, mute, volume, 0.25x-2x speed, full screen, and picture-in-picture where supported.
- Click-to-seek and drag-to-preview timeline behavior. Drag updates are throttled, and the definitive media seek occurs on pointer release to prevent decode thrashing.
- T/A/L and other stage markers on the shared timeline. Marker clicks and previous/next controls seek without changing marker identity.
- Keyboard shortcuts with focus-aware guards so typing in forms never controls media.
- Buffering uses the original Loading and striped Progress components. Errors use an Animal Island notification with retry.
- Marker and control states have text or accessible labels; color is never their only carrier.

### Phone

- Media surface first, followed by a large play control, timeline, and current/total time.
- Minimum touch target is 44px.
- Quality, speed, picture-in-picture, and secondary actions live in an overflow menu.
- Timeline markers remain directly tappable and do not require opening the menu.

### Tablet

- Timeline occupies its own row.
- Play, five-second seek, frame step, and marker navigation sit on the left.
- Time, speed, quality, and full screen sit on the right.
- Portrait and landscape use the same semantic control order and rearrange through CSS.

### Desktop

- Complete controls remain visible.
- Hover timeline preview and precise time input are available.
- The layout supports the existing wide analysis and comparison workspaces without page overflow.

## Quality Sources and Transcoding

Each uploaded video exposes source descriptors for Auto, Original, 1080p, 720p, and 480p. The backend never upscales a source: unavailable or redundant higher renditions are omitted.

Original playback is available as soon as the source passes validation. Additional renditions are generated asynchronously and appear as they become ready; analysis is not blocked by all transcodes completing.

Auto mode prefers adaptive playback when the deployment/browser supports it. The compatibility path selects an available MP4 using viewport, device pixel ratio, connection hints, and recent buffering. A manual quality selection remains fixed until the user returns to Auto.

Source switching captures current time, paused state, volume, mute, and playback rate. The replacement source seeks only after metadata is ready and then resumes the prior state. On failure, the previous source is restored with an actionable retry notice.

Failed renditions are hidden. If every derived rendition fails, Original remains available. Rendition status is observable through the existing analysis/media API rather than inferred by probing URLs.

## Skeleton and Synchronized Playback

Pose frames play from persisted timestamps rather than array indices or an assumed fixed FPS. The shared controller selects or interpolates the pose state for the media time.

- Short gaps may interpolate coordinates only when both bounding frames contain reliable observations.
- Longer gaps hold the last reliable frame and visibly label a data gap; they never invent motion.
- Video and pose can join one synchronized group so play, pause, seek, speed, and marker jumps affect both.
- Comparison videos use the same synchronized-group abstraction. Existing comparable-window and playback-rate compensation logic moves behind that abstraction.
- Drift correction is conservative during playback and exact after explicit seeks.

## Action Sampling and Completeness

### Base Density

- Jump: 48 base frames; 64 for a manually selected action window.
- Spin: 36 frames for up to six seconds, plus four frames for each additional analyzed second, capped at 52; manual windows cap at 64.
- Step: 32 frames for up to eight seconds, plus three frames for each additional analyzed second, capped at 48; manual windows cap at 56.
- Spiral: 28 frames for up to six seconds, plus three frames for each additional analyzed second, capped at 40; manual windows cap at 48.
- Free skate: four frames per analyzed second with a minimum of 32 and a maximum of 64 within the existing bounded input window; manual selection uses the same maximum.

Frame totals round up after duration scaling. These values live in action-profile configuration rather than prompts and receive unit tests at every boundary and cap.

### Temporal Supplement

After MiMo produces phase segments and key moments, the backend extracts supplemental full-resolution frames around every core phase. For T/A/L, each anchor contributes its center and neighboring frames on both sides. Neighbor spacing is based on source FPS and action profile so the sequence shows entry into and exit from the instant.

Supplemental frames are deduplicated by timestamp tolerance, then merged with base sampled frames. Core stages receive quotas before preparation/approach frames consume the remaining model budget.

### Conflict and Quality Gate

When motion/pose candidates conflict with MiMo timestamps, both coherent candidate windows remain in the evidence set. Fusion scores source confidence, visual stage agreement, pose geometry, motion context, temporal order, and continuity.

Coverage diagnostics include:

- analyzed-window coverage ratio;
- largest uncovered time gap;
- required-stage completeness;
- T/A/L temporal order and continuity;
- per-stage frame counts and source diversity.

If a required stage is missing or coverage is below its profile threshold, one targeted supplemental extraction expands that stage window. The process is bounded to one retry per stage. Remaining gaps become explicit `stage_evidence_insufficient` warnings; the pipeline does not force an incorrect phase label.

Path B receives the complete stage-balanced core set rather than an unconditional ten-frame fallback. A configurable safety cap remains to prevent unbounded payloads, but each required stage receives quota before optional context.

All selected frames retain provenance: base motion sample, MiMo temporal supplement, pose candidate, manual window, retry supplement, or merged duplicate.

## Sharing

The unified renderer covers reports, follow-up records, progress, comparison, plans, milestones, monthly stories, and annual collections.

Layout proceeds in two passes:

1. Measure wrapped title, body, list, image, caption, metadata, and footer blocks.
2. Allocate page height and render using the measured geometry.

Normal content grows vertically without truncation. At a safe long-image threshold, content is split only between semantic blocks or permitted paragraph/list boundaries. Text lines, images, headings, and captions are never cut across pages.

Preview exposes the page count and individual pages. Users may download one page or all pages. Native sharing sends all page files when supported; otherwise the UI provides sequential downloads and a bundled-download fallback. Annual sharing retains its concise cover and full PDF.

All pages use the same paper surface, rounded title treatment, ice/island decoration, page numbering, and IceBuddy/Animal Island attribution. Phone, tablet, and desktop dialogs rearrange preview and actions without regenerating different content.

If one page fails, successfully rendered pages remain available and the failed portion can be retried. The UI must not imply the share is complete while pages are missing.

## Submit Feedback

Every asynchronous submit/save action uses a shared state contract:

```text
idle -> submitting -> success -> idle
                  \-> error -> idle/retry
```

- Submitting disables duplicate activation and uses the original Animal Island teal moving-stripe Button loading state.
- Success briefly shows a check and tactile bounce.
- Error restores the actionable label and emits an Animal Island notification containing a useful retry message.
- Navigation buttons and player playback controls do not use submit-success effects.
- Reduced-motion mode replaces bounce and moving stripes with static state and text.
- Unmounting aborts pending visual timers and prevents stale state updates.

## Error Handling and Recovery

- Transcode failure is isolated per rendition and never invalidates Original.
- Quality-switch failure restores the previous source and playback position.
- Supplemental extraction failure leaves the base result usable but records stage and coverage warnings.
- Unsupported picture-in-picture, native sharing, multi-file sharing, or adaptive streaming hides or replaces the capability rather than leaving a broken control.
- Media decode errors distinguish retryable source loading from an unavailable asset.
- Share generation preserves successful pages and supports targeted retry.
- Submit errors retain form input and restore an enabled retry action.

## Testing and Acceptance

### Frontend Unit and Integration

- Navigation selection for all primary route families.
- Shared submit state transitions, duplicate-submit prevention, error recovery, and reduced motion.
- Timeline click, drag, marker navigation, keyboard behavior, and seek throttling.
- Quality switching preserves time, pause state, volume, mute, and rate; failure restores the old source.
- Pose timestamp selection, short-gap interpolation, long-gap hold, and data-gap labeling.
- Synchronized comparison seek/play behavior and bounded drift.
- Share measurement, wrapping, semantic pagination, page export, failure recovery, and browser capability fallbacks.

### Backend

- Profile frame density and manual-window caps.
- MiMo-stage supplemental extraction, timestamp deduplication, stage quotas, and bounded retry.
- Conflicting MiMo and pose/motion candidates remain present through fusion.
- Path B receives stage-balanced input and does not regress to preparation-dominated selection.
- Rendition generation, no-upscale filtering, status reporting, partial failure, and Original fallback.

### Responsive and End-to-End

- Validate 375px phone, 768px tablet, 1024px tablet, 1280px desktop, and 1440px wide desktop.
- No horizontal overflow; touch controls are at least 44px.
- Repeated scrub, marker jumps, quality switches, video-pose sync, and dual-video sync remain responsive and preserve position.
- Reanalyzing the known conflict video retains continuous evidence around both candidate windows and provides T/A/L coverage or an explicit insufficiency warning.
- Long report, follow-up, comparison, and plan content grows or paginates without clipped or overlapping text.
- Classic and modern business workflows continue to pass.

## Delivery Sequence

1. Expand the original-library adapter and shared submit state.
2. Implement dense base sampling, temporal supplementation, coverage diagnostics, and stage-balanced Path B input.
3. Add rendition storage/status APIs and asynchronous transcode jobs.
4. Build the shared controller, timeline, controls, video surface, pose surface, and synchronized group.
5. Migrate analysis, keyframe, debug, comparison, and skeleton surfaces incrementally.
6. Replace remaining share generators and preview dialogs with the measured multipage engine.
7. Remove obsolete controls/CSS only after call-site and regression checks.
8. Run focused tests, complete frontend/backend suites, production build, and responsive browser verification.

## Non-Goals

- Replacing analysis models or report semantics.
- Adding official Nintendo art, audio, trademarks, or game assets.
- Maintaining separate phone, tablet, and desktop component trees.
- Generating unlimited frames or unbounded model payloads solely because inference cost is low.
- Rewriting stable pose drawing or comparison-window algorithms without a demonstrated need.
