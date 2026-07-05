# Golden Progress Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a responsive Golden labeling entry from the progress/archive UI and let Golden debug runs created from historical analyses use a manual keyframe/input time range.

**Architecture:** Reuse the existing `/golden` workspace, debug run creation APIs, and Golden label editor. The archive timeline will pass `analysis_id` through the route, and the Golden workspace form will preselect it and expose manual start/end seconds for both history and upload sources.

**Tech Stack:** React 18, React Router, TypeScript, Vite, existing FastAPI debug endpoints.

---

### Task 1: Route Golden Entry From Progress/Archive

**Files:**
- Modify: `frontend/src/pages/ArchivePage.tsx`
- Modify: `frontend/src/pages/DebugPage.tsx`

- [ ] Add a responsive "Golden 标注" action beside completed archive entries.
- [ ] Link to `/golden?analysis_id=<analysis_id>`.
- [ ] In `DebugPage`, read `analysis_id` from `useLocation().search`.
- [ ] Preselect the matching historical analysis in Golden mode and keep the label tab active.

### Task 2: Manual Window For Historical Debug Runs

**Files:**
- Modify: `frontend/src/pages/DebugPage.tsx`

- [ ] Let `DebugRunForm` receive an optional default analysis id from the route.
- [ ] Show "AI 输入片段" start/end controls for the history source as well as upload source.
- [ ] Prefill history source controls from selected analysis detail when available: `manual_action_window_start/end`, then `action_window_start/end`.
- [ ] Send `manualActionWindowStartSec` and `manualActionWindowEndSec` for history-source debug runs when both values are present.
- [ ] Validate both values with `validateManualWindow` before submitting.

### Task 3: Verification

**Files:**
- Test command target: `frontend`

- [ ] Run `npm run build` from `frontend`.
- [ ] Start the Vite app.
- [ ] Verify `/archive` and `/golden?analysis_id=...` on desktop, tablet, and mobile widths.
- [ ] Confirm the new button wraps cleanly and the Golden form preselects the requested historical record.
