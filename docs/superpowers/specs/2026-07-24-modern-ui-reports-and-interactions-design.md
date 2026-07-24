# IceBuddy Modern UI Completion, Report Lifecycle, and Interaction Reliability

**Date:** 2026-07-24

**Status:** Approved design

## Objective

Complete the Animal-Island-inspired modern UI by integrating the real `animal-island-ui` component library, fix the reported PWA interaction and text-encoding defects, add versioned editing and recoverable deletion for monthly and annual reports, and make annual PDF generation reliable inside the all-in-one Docker image.

The classic UI remains functionally and visually unchanged. Shared backend fixes may serve both interfaces, but new report-management controls and visual migrations belong to the modern UI only.

## Confirmed Product Decisions

- Pin and use `animal-island-ui@1.3.0` through a modern-UI adapter layer.
- Scope visual work to the modern UI. Do not intentionally change classic UI pages, navigation, or styling.
- Monthly drafts can be edited in place. Editing a published monthly report creates a new revision.
- Annual reports can change title, selected monthly reports, and selected milestones by creating a new revision.
- Deletion is recoverable by default. Deleted reports enter a recycle bin and can be restored or permanently deleted.
- Existing annual reports keep their frozen snapshots even if a source monthly report is later deleted.
- The all-in-one Docker image bundles a Chinese-capable font with documented licensing and configures it as the annual PDF default.
- The modern UI must prefer real library components whenever the library provides the relevant primitive.

## Scope

### Included

- Modern UI component-library integration and style isolation.
- Modern analysis detail diagnostics navigation.
- Parent-mode dialog reliability.
- Target-skater and AI action-confirmation text corruption fixes.
- Follow-up chat working, confirmation, submission, and sharing states.
- Monthly and annual report editing, revision history, recycle bin, restore, and permanent deletion.
- Annual PDF font packaging, startup validation, retry, and forced regeneration.
- Modern UI migration audit, starting with every surface touched by this project.
- Phone PWA, iPad, desktop, reduced-motion, and accessibility verification.

### Excluded

- Redesigning the classic UI.
- Replacing business-specific video, pose, chart, canvas, or keyframe widgets with decorative library components.
- Mutating a published report or an existing annual snapshot in place.
- Adding Nintendo-owned characters, trademarks, artwork, audio, or official game assets.
- Adding unrelated analysis-pipeline or model changes.

## Reference Library and License

The implementation uses `animal-island-ui` version `1.3.0`, licensed under CC BY-NC 4.0. The application is confirmed to be personal and non-commercial. Attribution and the license notice remain available under modern Me > About and Open-Source Licenses.

The checked reference at `tmp/animal-island-ui-reference` is the implementation and visual source of truth. Its `PROMPT.md` is a secondary specification; when it differs from component source, source code wins. The reference library states that its designs are independently created and do not ship official Nintendo resources. IceBuddy follows the same restriction.

## Architecture

### Modern UI Adapter Layer

Create a single adapter module for modern UI primitives. It re-exports or lightly wraps the pinned library's `Button`, `Card`, `Table`, `Collapse`, `Modal`, `Drawer`, `Loading`, `Progress`, `Tag`, `Tabs`, `Input`, `Select`, `Checkbox`, `Radio`, `Switch`, `Tooltip`, `Title`, `Divider`, and `Notification` APIs.

The adapter owns:

- IceBuddy color and sizing variants;
- Chinese default labels where a wrapper needs them;
- accessibility defaults and stable test hooks;
- phone-safe modal and drawer behavior;
- loading-button conventions;
- compatibility fixes that are specific to the current library version.

Pages must not recreate a primitive with local Tailwind or CSS when the adapter supplies it. Business-specific components remain custom, but consume the same design tokens and compose adapter primitives for their controls.

### Style Isolation

Library styles and IceBuddy overrides are scoped under `.modern-island-shell`. The modern entry boundary loads them; classic routes do not. Global font and reset rules from the package must be either scoped at build time or replaced by equivalent scoped imports so that they cannot alter classic UI elements.

The adapter exposes stable IceBuddy tokens derived from the library: mint teal, parchment surfaces, warm-brown text, yellow focus, semantic status colors, rounded geometry, motion durations, and Nunito/Noto Sans SC typography. Existing time-of-day atmosphere tokens may modify environmental backgrounds but not semantic colors or text contrast.

### Asset Policy

Use upstream assets only where they carry meaning or improve an empty/loading state: navigation, loading, report cover, sharing, empty state, badges, and environmental decoration. Keep attribution and source metadata. Do not copy the full item catalog into the production bundle. Select assets deliberately and let the bundler include only referenced files.

### Migration Order

The first pass covers all surfaces in this project:

1. analysis detail, diagnostics, and follow-up;
2. target confirmation and parent access;
3. monthly reports, annual reports, report history, and recycle bin;
4. sharing dialogs and generated-image previews;
5. other modern UI pages found by a primitive-usage audit.

The audit records every remaining hand-rolled interactive primitive. Each result is either migrated or explicitly documented as a business-specific exception.

## Interaction Reliability

### Diagnostics Navigation

Selecting Diagnostics in modern Analysis Detail performs one state transition that:

1. selects the `more` section;
2. expands the diagnostics disclosure;
3. waits until the destination exists;
4. scrolls the diagnostics heading into view with an offset for the sticky section switcher;
5. moves keyboard focus to the heading without triggering a second unexpected scroll.

Phone layouts keep the section switcher visible. Reduced-motion users receive an immediate scroll instead of smooth animation. A deep link with `view=more&tool=diagnostics` produces the same state.

### Parent Mode Dialog

The parent-mode request state moves to the modern application shell or a shell-level controller. The mode toggle emits an intent and does not own the dialog lifetime. The dialog renders through the library modal portal and remains mounted across route-level rerenders.

Entering parent mode always opens PIN verification unless an existing verified session permits direct entry. Closing, validation failure, success, UI-theme switching, and route changes each have explicit transitions. Switching between classic and modern UI cannot be required to make the dialog appear.

The dialog traps and restores focus, locks background scroll, has a stable z-index above navigation, and becomes a safe-area-aware bottom sheet on phones.

### Working and Submission Feedback

While follow-up AI is consulting evidence, show an inline library `Loading` treatment with a short animated stage label such as “AI 正在对照视频、关键帧和报告证据”. The occupied layout stays stable and the status uses `role="status"` with an accessible static description. Reduced-motion mode disables decorative movement but retains textual progress.

All submit, confirm, regenerate, and apply actions use the library's striped loading button, disable duplicate submission, and retain their width while the label changes. Failure restores the action and displays a retryable error near the control.

### Video-AI Keyframe Confirmation

The confirmation uses the shared modal. The explanatory body scrolls independently; the footer remains fixed inside the dialog and includes the PWA bottom safe area. The primary action has at least a 44-pixel touch target and cannot be covered by the bottom navigation or browser chrome.

Submitting changes the action to a visible loading state. Success closes the modal and exposes queued/working state. Failure leaves the modal open with the action available for retry.

## Text-Encoding Repair

Repair known mojibake literals in frontend and backend source, including target confirmation, AI action confirmation, report fallback text, and affected service prompts. Store source files as UTF-8 and add assertions for user-visible strings where practical.

For historical API values, use a conservative compatibility decoder:

- only attempt conversion when the value contains known mojibake marker sequences;
- require the converted value to improve a deterministic text-quality score;
- maintain a focused field allowlist for user-visible legacy data;
- never guess-convert normal Chinese text;
- do not rewrite database values during reads.

If persistent cleanup is later desired, it must be a separate backup-aware migration. This project only normalizes display and newly written values.

## Follow-Up Sharing

The follow-up share image uses a two-pass layout:

1. normalize and group turns, answers, and correction records;
2. measure wrapped text using Noto Sans SC/Nunito-compatible canvas fonts;
3. compute each block and total canvas height within an explicit maximum;
4. render blocks using the same measurements;
5. paginate or summarize only when the maximum supported image height is exceeded.

No fixed-height block may contain variable multi-turn text. The preview dialog uses the shared modern share dialog, loading state, buttons, and responsive container. Font loading completes before measurement. Generated output must not overlap, clip the final correction record, or render tofu for Chinese characters.

## Monthly Report Lifecycle

### Editable Fields

Monthly reports expose `title` and `final_text`. Draft/facts-ready/generated revisions can update those fields in place. Existing narrative length and validation rules remain.

### Published Editing

Editing a published monthly report creates a new revision instead of changing the published record. The new revision:

- references the prior revision as its parent;
- copies the immutable fact snapshot and source hash;
- copies title, draft, and final text as the editing baseline;
- starts in an editable revision state;
- receives a new revision number and identifier.

Publishing the new revision does not remove the old revision. Annual selection defaults to the latest non-deleted published revision for each month, while history can show all revisions.

### Deletion

Soft deletion records `deleted_at` and hides the revision from normal lists and new annual selection. The recycle bin lists deleted revisions and supports restore. Restore fails with a clear conflict only if doing so would violate a current uniqueness rule; the revision model should avoid such a conflict by keying uniqueness on revision number, not active status.

Permanent deletion requires a second confirmation and is allowed only from the recycle bin. If a monthly record is referenced structurally outside a frozen annual snapshot, return a conflict describing the dependency. Frozen annual snapshots remain valid because they contain copied content rather than live report references.

## Annual Report Lifecycle

### Versioned Editing

An annual edit form changes:

- title;
- selected published monthly revision IDs;
- selected milestone IDs.

Saving from the annual edit flow always creates a new annual collection revision and a new frozen snapshot. The previous collection and exports remain unchanged. The existing idempotent create behavior may remain for the separate first-time collection creation endpoint, but it is not used to collapse an explicit edit into an older revision.

### Deletion and Restore

Annual collections use the same recycle-bin lifecycle. Soft deletion hides the collection and its exports from normal history but does not immediately remove PDF assets. Restore makes them visible again.

Permanent deletion removes the collection's export records and PDF files only after resolving every path beneath the annual asset root. Failure to remove an asset aborts the database deletion and returns an actionable error so storage and records do not silently diverge.

### List Presentation

Desktop history uses the real library `Table`; narrow layouts use semantic report cards instead of a horizontally overflowing table. Revision, status, modified date, export state, and actions remain visible. Edit groups use `Collapse`, destructive confirmation uses `Modal`, and state badges use `Tag`.

## Annual PDF Reliability

### Bundled Font

The all-in-one image includes a Chinese-capable regular and bold font whose upstream source, version, license, filenames, and SHA256 hashes are recorded in `backend/assets/fonts/README.md` or an adjacent notice. The Dockerfile sets:

- `ANNUAL_PDF_FONT_PATH` to the bundled regular font;
- `ANNUAL_PDF_FONT_BOLD_PATH` to the bundled bold font.

The container startup check verifies that both files exist and are readable. Application startup logs a concise actionable warning if validation fails, while the export endpoint returns a Chinese user-facing error.

Empty environment variables stay empty during validation. They must not be converted to `Path("")` and reported as `.` or `..`.

### Regeneration Semantics

The export API accepts an explicit force-regeneration intent. Normal export may reuse a completed, valid artifact. Forced regeneration always creates a new export record and renders a new file, even when an earlier export is complete. Retrying a failed export also creates a new export attempt, preserving the failed record for diagnostics.

The UI labels these operations distinctly:

- `生成年度 PDF` when no valid export exists;
- `重试生成` after failure;
- `重新生成年度 PDF` when a valid prior PDF exists.

Only one active pending/processing attempt per collection is allowed. A duplicate request returns the active attempt rather than queueing concurrent writes.

## API and Data Model

Add explicit lifecycle fields rather than overloading status strings:

- monthly chapter: `title`, `parent_revision_id`, `deleted_at`;
- annual collection: `parent_revision_id`, `deleted_at`;
- existing `revision`, timestamps, source hashes, and snapshots remain authoritative.

Provide authenticated endpoints consistent with the current router conventions for:

- patching an editable monthly report;
- creating a revision from a published monthly report;
- soft deleting, restoring, and permanently deleting a monthly report;
- listing active or recycled monthly reports;
- creating an annual revision from edited selections;
- soft deleting, restoring, and permanently deleting an annual report;
- listing active or recycled annual reports;
- creating a normal or forced annual PDF export.

Mutating and destructive operations use the application's existing parent authorization mechanism. API responses include enough revision and deletion metadata for the UI to explain what will happen before confirmation.

Database migrations are additive and idempotent. Existing monthly and annual records remain active with `deleted_at = NULL`; existing titles are backfilled from their current display convention.

## Error Handling and State Recovery

- Long-running requests have stable operation keys so progress replaces prior status instead of stacking notices.
- Reloading the PWA restores active annual export polling and queued analysis state from server truth.
- A failed mutation leaves the form contents intact.
- Delete/restore conflicts identify the report and blocking dependency.
- Offline mode permits reading cached report history but disables edit, delete, restore, retry, and export with an explanation.
- Unexpected backend details are logged server-side; user-facing messages remain Chinese and actionable.

## Accessibility and Responsive Behavior

- Interactive targets are at least 44 pixels; primary child-mode targets remain at least 56 pixels.
- Library controls retain visible yellow focus treatment and keyboard activation.
- Modals and drawers trap focus, restore focus, support Escape where safe, and expose labelled dialog semantics.
- Loading and result notifications are announced without repeatedly reading decorative animation.
- Phone sheets include `env(safe-area-inset-bottom)` and never sit below the fixed island dock.
- Tables become cards on narrow screens; no page-level horizontal overflow is permitted.
- `prefers-reduced-motion` removes smooth scrolling, leaf motion, and nonessential transitions without removing status information.

## Testing and Verification

### Backend

- Monthly draft title/body editing.
- Published monthly edit creates a new revision and preserves the old revision.
- Monthly soft delete, filtered listing, recycle-bin listing, restore, and permanent delete.
- Existing annual snapshots remain valid after source soft deletion.
- Annual edit creates a new collection and frozen snapshot.
- Annual soft delete, restore, permanent delete, and safe asset cleanup.
- Empty font config produces an actionable error without `.` or `..` placeholders.
- Bundled fonts render and extract representative Chinese text.
- Failed export retry creates a new attempt.
- Forced regeneration creates a new completed artifact.
- Duplicate requests do not create concurrent active exports.

### Frontend

- Diagnostics selection expands and focuses the diagnostic section.
- Deep-linked diagnostics produce the same visible state.
- Parent verification opens reliably without switching UI modes.
- Known mojibake displays as corrected Chinese and valid Chinese remains unchanged.
- Evidence-loading and all submission buttons expose working and disabled states.
- Video-AI keyframe confirmation remains clickable at phone/PWA heights.
- Follow-up share images expand for multi-turn content without overlap or clipping.
- Monthly and annual revision flows explain that a new version will be created.
- Recycle-bin delete, restore, and permanent-delete controls update lists correctly.
- Modern pages use adapter primitives; a targeted audit prevents new local primitive copies.

### Browser and Deployment

Verify representative phone PWA, iPad portrait/landscape, desktop, keyboard, and reduced-motion flows. Check safe areas, sticky controls, focus restoration, scroll positioning, and horizontal overflow.

Build the all-in-one Docker image and run an integration smoke test inside the container that generates, downloads, and force-regenerates an annual PDF containing Chinese text. Verify the current classic UI regression suite to detect style leakage.

## Acceptance Criteria

- Clicking Diagnostics immediately reveals the diagnostic content without manual downward searching.
- Parent-mode PIN verification opens on every valid request in modern UI without toggling classic/modern UI.
- Target and AI action-confirmation screens show valid Chinese text.
- Follow-up evidence work and all submissions provide visible, accessible animated feedback.
- The video-AI keyframe confirm action is reachable and clickable in installed-phone layouts.
- Follow-up share output contains all supported turns and corrections without layout corruption.
- Monthly drafts edit in place; published monthly reports and all annual edits create revisions.
- Monthly and annual reports can be moved to a recycle bin, restored, and permanently deleted.
- Existing annual snapshots and PDFs survive deletion of a source monthly report.
- The all-in-one image generates Chinese annual PDFs without host font mounts.
- Users can retry failures and explicitly regenerate a completed annual PDF.
- Touched modern UI surfaces use real `animal-island-ui` primitives through the adapter.
- Classic UI visual and behavioral regression tests remain unchanged and pass.
