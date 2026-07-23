# Growth and Sharing Animal Island Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair growth-entry failures and annual PDF export while unifying all share and confirmation UI under a responsive Animal Island design.

**Architecture:** Add explicit hub modes for plan and comparison routes, shared island modal/button/share primitives, and content adapters for each share source. Keep existing detail routes and API contracts, and make annual PDF capability observable in the backend and container.

**Tech Stack:** React 18, TypeScript, Canvas, FastAPI, SQLAlchemy, ReportLab, pypdf, Vitest, pytest, Docker.

## Global Constraints

- Preserve classic routes and current backend data.
- Use existing Animal Island licensed assets and attribution.
- Support phone, portrait tablet, landscape tablet, desktop, PWA safe areas, and reduced motion.
- Long non-annual shares use one height-adaptive poster; annual share uses summary cover plus PDF.

---

### Task 1: Annual PDF runtime capability

**Files:** `backend/app/services/annual_pdf.py`, `backend/app/routers/annual.py`, `backend/tests/test_annual_pdf.py`, `backend/tests/test_annual_routes.py`, `docker/allinone/Dockerfile`

- [ ] Add failing tests for dependency diagnostics and retry-safe export failure.
- [ ] Implement runtime capability reporting and preserve actionable error details.
- [ ] Verify the focused backend tests pass.

### Task 2: Plan and comparison hubs

**Files:** `frontend/src/modern/ModernGrowthSpace.tsx`, `frontend/src/pages/PlanPage.tsx`, `frontend/src/pages/ComparePage.tsx`, `frontend/src/api/client.ts`, new hub components and tests.

- [ ] Add failing route tests proving ID-less growth views render launchers rather than invalid-parameter errors.
- [ ] Implement plan list/empty/generation navigation and comparison selection launch flow using existing APIs.
- [ ] Verify detail routes remain unchanged and tests pass.

### Task 3: Shared Animal Island controls and parent verification

**Files:** `frontend/src/modern/IslandDialog.tsx`, `frontend/src/components/ParentPinVerifyModal.tsx`, `frontend/src/components/ParentUnlockModal.tsx`, `frontend/src/components/ModeToggle.tsx`, `frontend/src/modern/modern-island.css`

- [ ] Add modal behavior and theme tests.
- [ ] Implement shared dialog/button/loading primitives and migrate PIN flows.
- [ ] Replace confirm-based regenerate controls with an accessible island confirmation dialog.

### Task 4: Adaptive Animal Island share engine

**Files:** `frontend/src/utils/shareCanvas.ts`, new `frontend/src/modern/IslandShareDialog.tsx`, related tests.

- [ ] Add failing tests for measured adaptive height, long text, and capability fallbacks.
- [ ] Implement the Animal Island poster renderer and responsive share dialog.
- [ ] Verify poster content is not clipped and heavy rendering remains invocation-driven.

### Task 5: Integrate every share source

**Files:** report, progress, follow-up, milestone, plan, comparison, monthly, and annual frontend pages/components plus tests.

- [ ] Migrate existing report/progress/follow-up/milestone workflows to the shared dialog.
- [ ] Add plan, comparison, and monthly adaptive poster adapters.
- [ ] Add annual cover plus PDF native-share/download/copy fallback.
- [ ] Verify source-specific content and long-text behavior.

### Task 6: Validation and release

**Files:** `README.md`, `README.zh.md`, release artifacts.

- [ ] Run focused backend tests, full frontend tests, and production build.
- [ ] Validate four viewports and core workflows in the in-app browser.
- [ ] Update bilingual README, commit, and push GitHub.
- [ ] Build a fresh complete `skating-analyzer-allinone:latest`, verify ReportLab/pypdf and assets, then export versioned and latest TAR files to the NAS.

