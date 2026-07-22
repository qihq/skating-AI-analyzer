# P0 Growth Home Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a parent-facing growth home that reuses existing analysis evidence to show trustworthy KPIs, profile-specific action phases, recent milestones, and the next practice focus without adding model calls.

**Architecture:** Add one read-only backend aggregation service and endpoint, then build focused React components for phase evidence, KPIs, and milestones. The growth page fetches the summary first and lazily fetches the latest completed analysis for the evidence strip. Existing report, archive, skill-path, and advanced diagnostic routes remain the authoritative detail surfaces.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy/SQLite, Pydantic, React 18, TypeScript, Canvas, Axios, Tailwind CSS, pytest/unittest, Vitest, Testing Library, jsdom.

## Global Constraints

- P0 adds no VLM or text-model calls and does not modify stored analysis results.
- Use the resolved profile-specific phase contract: jump T/A/L, spin entry/main/exit, spiral hold, and step interval. Do not synthesize a preparation frame from a fixed offset.
- An actual skeleton overlay must not be labeled as a standard-action or ghost comparison.
- Do not display landing rate in P0; no attempt/outcome contract exists yet.
- Authoritative counts come from a backend aggregation over persisted data, never from frontend pagination.
- Missing frames, landmarks, timestamps, or confidence render explicit unavailable states rather than defaults.
- Preserve `system_detected`, `parent_confirmed`, and `coach_confirmed` as distinct milestone verification labels.
- Keep existing report, archive, history, skill path, chat, Golden, debug, and settings routes functional.
- Source design: `docs/superpowers/specs/2026-07-22-growth-story-product-design.md`.

---

## File Structure

### Backend

- Create `backend/app/services/growth_summary.py`: all authoritative KPI, latest-focus, and milestone aggregation.
- Create `backend/tests/test_growth_summary.py`: isolated SQLite service and endpoint contract tests.
- Modify `backend/app/schemas.py`: Pydantic response contracts only.
- Modify `backend/app/routers/skaters.py`: thin route that checks the skater and delegates to the service.

### Frontend

- Create `frontend/src/utils/poseCanvas.ts`: pure contain-rectangle math and focused skeleton drawing for phase cards.
- Create `frontend/src/components/PoseFrameCanvas.tsx`: one source frame plus aligned actual-pose overlay.
- Create `frontend/src/components/ActionPhaseStrip.tsx`: profile-aware phase cards and video seeking.
- Create `frontend/src/components/GrowthKpiBar.tsx`: summary KPI presentation.
- Create `frontend/src/components/MilestoneTimeline.tsx`: milestone event presentation with verification labels.
- Create `frontend/src/pages/GrowthHomePage.tsx`: data loading and page composition only.
- Create `frontend/src/navigation.ts`: shared four-concept primary navigation configuration and route matching.
- Create `frontend/src/components/AdvancedToolsLinks.tsx`: non-primary links to history, chat, Golden, debug, and API settings.
- Create `frontend/src/test/setup.ts`: Testing Library and browser API test setup.
- Create focused `*.test.ts`/`*.test.tsx` files beside each new unit.
- Modify `frontend/src/pages/ReportPage.tsx`: place the phase review after the report summary.
- Modify `frontend/src/pages/SettingsPage.tsx`: render the advanced-tools link group.
- Modify `frontend/src/api/client.ts`: exact growth-summary types and fetch function.
- Modify `frontend/src/App.tsx`: register `/home` and redirect `/` to it.
- Modify `frontend/src/components/AppLayout.tsx`, `frontend/src/components/BottomNav.tsx`, and `frontend/src/components/AppHeader.tsx`: use the shared four-concept navigation and retain settings access.
- Modify `frontend/package.json`, `frontend/package-lock.json`, `frontend/vite.config.ts`, and `frontend/tsconfig.json`: add the frontend test runner.

---

### Task 1: Authoritative Growth Summary Contract

**Files:**
- Create: `backend/app/services/growth_summary.py`
- Create: `backend/tests/test_growth_summary.py`
- Modify: `backend/app/schemas.py:497`
- Modify: `backend/app/routers/skaters.py:13-38`
- Modify: `backend/app/routers/skaters.py:296`

**Interfaces:**
- Consumes: `Analysis`, `Skater`, `SkaterSkill`, `SkillNode`, and `TrainingSession` persisted rows.
- Produces: `async build_growth_summary(session: AsyncSession, skater_id: str, *, now: datetime | None = None, milestone_limit: int = 8) -> GrowthSummaryResponse`.
- Produces: `GET /api/skaters/{skater_id}/growth-summary?milestone_limit=8` returning `GrowthSummaryResponse`.

- [ ] **Step 1: Write the failing aggregation tests**

Create `backend/tests/test_growth_summary.py` with an isolated database fixture and these tests:

```python
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path


class GrowthSummaryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        os.environ["DATA_DIR"] = self.tmpdir.name
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(self.tmpdir.name) / 'test.db'}"
        for module_name in [
            "app.database",
            "app.models",
            "app.schemas",
            "app.services.growth_summary",
            "app.routers.skaters",
        ]:
            sys.modules.pop(module_name, None)

        import app.database as database
        import app.models as models

        self.database = database
        self.models = models
        database.ensure_storage_dirs()
        await database.init_db()

    async def asyncTearDown(self) -> None:
        await self.database.engine.dispose()
        self.tmpdir.cleanup()

    async def test_summary_counts_only_completed_analyses_and_distinct_sessions(self) -> None:
        from app.services.growth_summary import build_growth_summary

        models = self.models
        async with self.database.AsyncSessionLocal() as session:
            session.add(models.Skater(id="skater-1", name="tantan", display_name="坦坦"))
            session.add_all(
                [
                    models.TrainingSession(id="session-1", skater_id="skater-1", session_date=date(2026, 7, 3)),
                    models.TrainingSession(id="session-2", skater_id="skater-1", session_date=date(2026, 6, 28)),
                    models.Analysis(
                        id="analysis-latest",
                        skater_id="skater-1",
                        session_id="session-1",
                        action_type="jump",
                        action_subtype="Loop",
                        video_path="latest.mp4",
                        status="completed",
                        report={"summary": "更稳定", "training_focus": "落冰保持", "data_quality": "good"},
                        created_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
                    ),
                    models.Analysis(
                        id="analysis-old",
                        skater_id="skater-1",
                        session_id="session-1",
                        action_type="jump",
                        video_path="old.mp4",
                        status="completed",
                        created_at=datetime(2026, 6, 20, tzinfo=timezone.utc),
                    ),
                    models.Analysis(
                        id="analysis-failed",
                        skater_id="skater-1",
                        action_type="jump",
                        video_path="failed.mp4",
                        status="failed",
                        created_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
                    ),
                ]
            )
            await session.commit()

        async with self.database.AsyncSessionLocal() as session:
            result = await build_growth_summary(
                session,
                "skater-1",
                now=datetime(2026, 7, 22, tzinfo=timezone.utc),
            )

        self.assertEqual(result.lesson_count, 2)
        self.assertEqual(result.completed_analysis_count, 2)
        self.assertEqual(result.current_month_analysis_count, 1)
        self.assertEqual(result.latest_analysis_id, "analysis-latest")
        self.assertEqual(result.current_focus.label, "落冰保持")
        self.assertEqual(result.current_focus.quality, "good")
        self.assertNotIn("landing_rate", result.model_dump())

    async def test_milestones_keep_verification_source_and_newest_first(self) -> None:
        from app.services.growth_summary import build_growth_summary

        models = self.models
        async with self.database.AsyncSessionLocal() as session:
            session.add(models.Skater(id="skater-1", name="tantan"))
            session.add_all(
                [
                    models.SkillNode(
                        id="skill-auto",
                        chapter="fs1",
                        chapter_order=1,
                        stage=1,
                        stage_name="基础",
                        group_name="跳跃",
                        sort_order=1,
                        name="华尔兹跳",
                        emoji="⛸️",
                        xp=100,
                    ),
                    models.SkillNode(
                        id="skill-parent",
                        chapter="fs1",
                        chapter_order=1,
                        stage=1,
                        stage_name="基础",
                        group_name="滑行",
                        sort_order=2,
                        name="后交叉步",
                        emoji="✨",
                        xp=100,
                    ),
                    models.SkaterSkill(
                        id="progress-auto",
                        skater_id="skater-1",
                        skill_id="skill-auto",
                        status="unlocked",
                        unlocked_by="auto",
                        unlocked_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
                    ),
                    models.Analysis(
                        id="analysis-auto-unlock",
                        skater_id="skater-1",
                        action_type="jump",
                        video_path="auto.mp4",
                        status="completed",
                        auto_unlocked_skill="skill-auto",
                        created_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
                    ),
                    models.SkaterSkill(
                        id="progress-parent",
                        skater_id="skater-1",
                        skill_id="skill-parent",
                        status="unlocked",
                        unlocked_by="parent",
                        unlock_note="今天连续完成三次",
                        unlocked_at=datetime(2026, 7, 18, tzinfo=timezone.utc),
                    ),
                ]
            )
            await session.commit()

        async with self.database.AsyncSessionLocal() as session:
            result = await build_growth_summary(session, "skater-1", milestone_limit=8)

        self.assertEqual(result.milestone_count, 2)
        self.assertEqual([item.source_skill_id for item in result.recent_milestones], ["skill-parent", "skill-auto"])
        self.assertEqual(result.recent_milestones[0].verification, "parent_confirmed")
        self.assertEqual(result.recent_milestones[1].verification, "system_detected")
        self.assertEqual(result.recent_milestones[0].note, "今天连续完成三次")
        self.assertEqual(result.recent_milestones[1].source_analysis_ids, ["analysis-auto-unlock"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```powershell
$env:PYTHONPATH='backend'
python -m pytest backend/tests/test_growth_summary.py -q
```

Expected: FAIL because `app.services.growth_summary` and the response models do not exist.

- [ ] **Step 3: Add the exact Pydantic contracts**

Add to `backend/app/schemas.py` immediately after `ArchiveResponse`:

```python
class GrowthFocus(BaseModel):
    label: str
    source_analysis_id: str
    quality: str


class GrowthMilestoneEvent(BaseModel):
    id: str
    occurred_at: datetime
    type: str = "skill_unlock"
    title: str
    note: str | None = None
    verification: str
    source_skill_id: str
    source_analysis_ids: list[str] = Field(default_factory=list)
    evidence_quality: str = "persisted"


class GrowthSummaryResponse(BaseModel):
    schema_version: int = 1
    skater_id: str
    as_of: datetime
    lesson_count: int
    completed_analysis_count: int
    current_month_analysis_count: int
    milestone_count: int
    latest_analysis_id: str | None = None
    current_focus: GrowthFocus | None = None
    metric_definitions: dict[str, str]
    recent_milestones: list[GrowthMilestoneEvent] = Field(default_factory=list)
```

- [ ] **Step 4: Implement the minimal aggregation service**

Create `backend/app/services/growth_summary.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Analysis, SkaterSkill, SkillNode, TrainingSession
from app.schemas import GrowthFocus, GrowthMilestoneEvent, GrowthSummaryResponse


VERIFICATION_BY_SOURCE = {
    "parent": "parent_confirmed",
    "coach": "coach_confirmed",
}


async def build_growth_summary(
    session: AsyncSession,
    skater_id: str,
    *,
    now: datetime | None = None,
    milestone_limit: int = 8,
) -> GrowthSummaryResponse:
    as_of = now or datetime.now(timezone.utc)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    month_start = as_of.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    lesson_count = int(
        await session.scalar(select(func.count(TrainingSession.id)).where(TrainingSession.skater_id == skater_id)) or 0
    )
    completed_filter = (Analysis.skater_id == skater_id, Analysis.status == "completed")
    completed_analysis_count = int(
        await session.scalar(select(func.count(Analysis.id)).where(*completed_filter)) or 0
    )
    current_month_analysis_count = int(
        await session.scalar(
            select(func.count(Analysis.id)).where(*completed_filter, Analysis.created_at >= month_start)
        )
        or 0
    )
    latest_analysis = (
        await session.execute(
            select(
                Analysis.id,
                Analysis.action_type,
                Analysis.action_subtype,
                Analysis.skill_category,
                Analysis.report,
            )
        .where(*completed_filter)
        .order_by(Analysis.created_at.desc(), Analysis.id.desc())
        .limit(1)
        )
    ).first()

    unlocked_rows = list(
        (
            await session.execute(
                select(SkaterSkill, SkillNode)
                .join(SkillNode, SkillNode.id == SkaterSkill.skill_id)
                .where(SkaterSkill.skater_id == skater_id, SkaterSkill.unlocked_at.is_not(None))
                .order_by(SkaterSkill.unlocked_at.desc(), SkaterSkill.id.desc())
            )
        ).all()
    )
    unlocked_skill_ids = [progress.skill_id for progress, _node in unlocked_rows]
    source_rows = (
        list(
            (
                await session.execute(
                    select(Analysis.id, Analysis.auto_unlocked_skill)
                    .where(
                        Analysis.skater_id == skater_id,
                        Analysis.status == "completed",
                        Analysis.auto_unlocked_skill.in_(unlocked_skill_ids),
                    )
                    .order_by(Analysis.created_at.asc(), Analysis.id.asc())
                )
            ).all()
        )
        if unlocked_skill_ids
        else []
    )
    source_analysis_ids: dict[str, list[str]] = {}
    for analysis_id, skill_id in source_rows:
        if skill_id:
            source_analysis_ids.setdefault(skill_id, []).append(analysis_id)
    milestones = [
        GrowthMilestoneEvent(
            id=f"skill-unlock:{progress.id}",
            occurred_at=progress.unlocked_at,
            title=f"{node.name} 已点亮",
            note=progress.unlock_note,
            verification=VERIFICATION_BY_SOURCE.get(progress.unlocked_by or "", "system_detected"),
            source_skill_id=node.id,
            source_analysis_ids=source_analysis_ids.get(node.id, []),
        )
        for progress, node in unlocked_rows[:milestone_limit]
        if progress.unlocked_at is not None
    ]

    report = latest_analysis.report if latest_analysis and isinstance(latest_analysis.report, dict) else {}
    focus_label = str(report.get("training_focus") or "").strip()
    if not focus_label and latest_analysis is not None:
        focus_label = latest_analysis.action_subtype or latest_analysis.skill_category or latest_analysis.action_type
    focus = None
    if latest_analysis is not None and focus_label:
        focus = GrowthFocus(
            label=focus_label,
            source_analysis_id=latest_analysis.id,
            quality=str(report.get("data_quality") or "partial"),
        )

    return GrowthSummaryResponse(
        skater_id=skater_id,
        as_of=as_of,
        lesson_count=lesson_count,
        completed_analysis_count=completed_analysis_count,
        current_month_analysis_count=current_month_analysis_count,
        milestone_count=len(unlocked_rows),
        latest_analysis_id=latest_analysis.id if latest_analysis else None,
        current_focus=focus,
        metric_definitions={
            "lesson_count": "已保存且互不重复的训练课次",
            "completed_analysis_count": "状态为 completed 的视频复盘",
            "current_month_analysis_count": "本自然月完成的视频复盘",
            "milestone_count": "具有 unlocked_at 时间的技能点亮记录",
        },
        recent_milestones=milestones,
    )
```

- [ ] **Step 5: Add the thin API route and endpoint test**

Import `GrowthSummaryResponse` and `build_growth_summary` in `backend/app/routers/skaters.py`, then add before `/{skater_id}/sessions`:

```python
@router.get("/{skater_id}/growth-summary", response_model=GrowthSummaryResponse)
async def get_growth_summary(
    skater_id: str,
    milestone_limit: Annotated[int, Query(ge=1, le=24)] = 8,
    session: AsyncSession = Depends(get_session),
) -> GrowthSummaryResponse:
    if await session.get(Skater, skater_id) is None:
        raise HTTPException(status_code=404, detail="未找到该练习档案对应的选手。")
    return await build_growth_summary(session, skater_id, milestone_limit=milestone_limit)
```

Append to the test file:

```python
    async def test_route_rejects_unknown_skater(self) -> None:
        import app.routers.skaters as skaters_router
        from fastapi import HTTPException

        async with self.database.AsyncSessionLocal() as session:
            with self.assertRaises(HTTPException) as raised:
                await skaters_router.get_growth_summary("missing", session=session)
        self.assertEqual(raised.exception.status_code, 404)
        self.assertIn("未找到", raised.exception.detail)
```

- [ ] **Step 6: Run focused and regression tests**

Run:

```powershell
$env:PYTHONPATH='backend'
python -m pytest backend/tests/test_growth_summary.py backend/tests/test_skaters_archive.py backend/tests/test_skills.py -q
```

Expected: all tests PASS.

- [ ] **Step 7: Commit the backend contract**

```powershell
git add backend/app/services/growth_summary.py backend/app/schemas.py backend/app/routers/skaters.py backend/tests/test_growth_summary.py
git commit -m "feat: add skater growth summary API"
```

---

### Task 2: Frontend Test Harness And Shared Pose Canvas

**Files:**
- Create: `frontend/src/test/setup.ts`
- Create: `frontend/src/utils/poseCanvas.ts`
- Create: `frontend/src/utils/poseCanvas.test.ts`
- Create: `frontend/src/components/PoseFrameCanvas.tsx`
- Create: `frontend/src/components/PoseFrameCanvas.test.tsx`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `frontend/vite.config.ts`
- Modify: `frontend/tsconfig.json`

**Interfaces:**
- Consumes: existing `PoseFrame`, `PoseKeypoint`, and `PoseResponse` types.
- Produces: `computeContainRect(containerWidth, containerHeight, mediaWidth, mediaHeight): ContainRect`.
- Produces: `drawPoseOverlay(canvas, frame, connections, options): void`.
- Produces: `<PoseFrameCanvas frame frameUrl connections alt className? />`.

- [ ] **Step 1: Install and configure the frontend test runner**

Run:

```powershell
npm --prefix frontend install --save-dev vitest jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event
```

Add scripts to `frontend/package.json`:

```json
"test": "vitest run",
"test:watch": "vitest"
```

Change the first import in `frontend/vite.config.ts` to `import { defineConfig } from "vitest/config";`, then add:

```typescript
test: {
  environment: "jsdom",
  setupFiles: "./src/test/setup.ts",
  css: true,
},
```

Add `"types": ["vitest/globals"]` to `compilerOptions` in `frontend/tsconfig.json` and create `frontend/src/test/setup.ts`:

```typescript
import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

Object.defineProperty(HTMLCanvasElement.prototype, "getContext", {
  configurable: true,
  value: vi.fn(() => ({
    setTransform: vi.fn(),
    clearRect: vi.fn(),
    fillRect: vi.fn(),
    strokeRect: vi.fn(),
    beginPath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    stroke: vi.fn(),
    arc: vi.fn(),
    fill: vi.fn(),
    setLineDash: vi.fn(),
    fillText: vi.fn(),
  })),
});
```

- [ ] **Step 2: Write failing contain-rectangle and missing-frame tests**

Create `frontend/src/utils/poseCanvas.test.ts`:

```typescript
import { describe, expect, it } from "vitest";
import { computeContainRect } from "./poseCanvas";

describe("computeContainRect", () => {
  it("letterboxes portrait media without stretching it", () => {
    expect(computeContainRect(320, 180, 90, 160)).toEqual({
      x: 109.375,
      y: 0,
      width: 101.25,
      height: 180,
    });
  });

  it("pillarboxes wide media inside a square", () => {
    expect(computeContainRect(200, 200, 400, 100)).toEqual({
      x: 0,
      y: 75,
      width: 200,
      height: 50,
    });
  });
});
```

Create `frontend/src/components/PoseFrameCanvas.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import PoseFrameCanvas from "./PoseFrameCanvas";

const frame = { frame: "frame_0010.jpg", keypoints: [] };

describe("PoseFrameCanvas", () => {
  it("shows an explicit unavailable state when the frame URL is missing", () => {
    render(<PoseFrameCanvas frame={frame} frameUrl={null} connections={[]} alt="起跳" />);
    expect(screen.getByText("当前阶段没有可展示的画面")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run the frontend tests to verify they fail**

Run:

```powershell
npm --prefix frontend test -- src/utils/poseCanvas.test.ts src/components/PoseFrameCanvas.test.tsx
```

Expected: FAIL because both modules are missing.

- [ ] **Step 4: Implement the shared renderer and component**

Create `frontend/src/utils/poseCanvas.ts` with exported `ContainRect`, `computeContainRect`, and `drawPoseOverlay`. The renderer must map normalized landmarks and target boxes into the contain rectangle, not the entire canvas:

```typescript
import type { PoseFrame, PoseKeypoint } from "../api/client";

export type ContainRect = { x: number; y: number; width: number; height: number };

export function computeContainRect(
  containerWidth: number,
  containerHeight: number,
  mediaWidth: number,
  mediaHeight: number,
): ContainRect {
  if (containerWidth <= 0 || containerHeight <= 0 || mediaWidth <= 0 || mediaHeight <= 0) {
    return { x: 0, y: 0, width: containerWidth, height: containerHeight };
  }
  const scale = Math.min(containerWidth / mediaWidth, containerHeight / mediaHeight);
  const width = mediaWidth * scale;
  const height = mediaHeight * scale;
  return { x: (containerWidth - width) / 2, y: (containerHeight - height) / 2, width, height };
}

const UPPER_BODY = new Set([11, 12, 13, 14, 15, 16]);
const LOWER_BODY = new Set([23, 24, 25, 26, 27, 28, 29, 30, 31, 32]);
const AXIS_POINTS = new Set([0, 11, 12, 23, 24]);

function pointColor(point: PoseKeypoint) {
  if (AXIS_POINTS.has(point.id)) return "#F8FAFC";
  if (UPPER_BODY.has(point.id)) return "#34D399";
  if (LOWER_BODY.has(point.id)) return "#F59E0B";
  return "#38BDF8";
}

export function drawPoseOverlay(
  canvas: HTMLCanvasElement,
  frame: PoseFrame,
  connections: number[][],
  options: { mediaWidth: number; mediaHeight: number },
) {
  const context = canvas.getContext("2d");
  if (!context) return;
  const width = canvas.clientWidth || 720;
  const height = canvas.clientHeight || Math.round(width * 0.5625);
  const pixelRatio = Math.min(window.devicePixelRatio || 1, 3);
  canvas.width = Math.round(width * pixelRatio);
  canvas.height = Math.round(height * pixelRatio);
  context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
  context.clearRect(0, 0, width, height);

  const rect = computeContainRect(width, height, options.mediaWidth, options.mediaHeight);
  const x = (value: number) => rect.x + value * rect.width;
  const y = (value: number) => rect.y + value * rect.height;
  const points = new Map(frame.keypoints.map((point) => [point.id, point]));

  if (frame.target_bbox) {
    context.strokeStyle = "rgba(56, 189, 248, 0.95)";
    context.lineWidth = 2;
    context.strokeRect(
      x(frame.target_bbox.x),
      y(frame.target_bbox.y),
      frame.target_bbox.width * rect.width,
      frame.target_bbox.height * rect.height,
    );
  }

  for (const [from, to] of connections) {
    const a = points.get(from);
    const b = points.get(to);
    if (!a || !b || a.visibility < 0.5 || b.visibility < 0.5) continue;
    context.strokeStyle = "rgba(226, 232, 240, 0.82)";
    context.lineWidth = 3;
    context.beginPath();
    context.moveTo(x(a.x), y(a.y));
    context.lineTo(x(b.x), y(b.y));
    context.stroke();
  }
  for (const point of frame.keypoints) {
    if (point.visibility < 0.5) continue;
    context.fillStyle = pointColor(point);
    context.beginPath();
    context.arc(x(point.x), y(point.y), AXIS_POINTS.has(point.id) ? 5 : 4, 0, Math.PI * 2);
    context.fill();
  }
}
```

Create `frontend/src/components/PoseFrameCanvas.tsx`:

```tsx
import { useEffect, useRef, useState } from "react";
import type { PoseFrame } from "../api/client";
import { drawPoseOverlay } from "../utils/poseCanvas";

type Props = {
  frame: PoseFrame | null;
  frameUrl: string | null;
  connections: number[][];
  alt: string;
  className?: string;
};

export default function PoseFrameCanvas({ frame, frameUrl, connections, alt, className = "" }: Props) {
  const imageRef = useRef<HTMLImageElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [failed, setFailed] = useState(false);

  const redraw = () => {
    const image = imageRef.current;
    if (!frame || !image || !canvasRef.current || !image.naturalWidth || !image.naturalHeight) return;
    drawPoseOverlay(canvasRef.current, frame, connections, {
      mediaWidth: image.naturalWidth,
      mediaHeight: image.naturalHeight,
    });
  };

  useEffect(() => {
    setFailed(false);
    window.addEventListener("resize", redraw);
    return () => window.removeEventListener("resize", redraw);
  }, [frame, frameUrl, connections]);

  if (!frameUrl || failed) {
    return <div className={`flex aspect-video items-center justify-center bg-slate-950 px-4 text-center text-sm text-slate-300 ${className}`}>当前阶段没有可展示的画面</div>;
  }

  return (
    <div className={`relative aspect-video overflow-hidden bg-slate-950 ${className}`}>
      <img ref={imageRef} src={frameUrl} alt={alt} className="absolute inset-0 h-full w-full object-contain" onLoad={redraw} onError={() => setFailed(true)} />
      {frame ? <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" aria-hidden="true" /> : null}
    </div>
  );
}
```

- [ ] **Step 5: Add image-only and alignment regression assertions**

Append these tests to `PoseFrameCanvas.test.tsx`:

```tsx
  it("renders an available source frame even when pose landmarks are unavailable", () => {
    render(<PoseFrameCanvas frame={null} frameUrl="/frame.jpg" connections={[]} alt="腾空" />);
    const image = screen.getByRole("img", { name: "腾空" });
    expect(image).toHaveClass("object-contain");
    expect(screen.queryByText("当前阶段没有可展示的画面")).not.toBeInTheDocument();
  });

  it("adds a canvas overlay when pose landmarks are available", () => {
    const { container } = render(<PoseFrameCanvas frame={frame} frameUrl="/frame.jpg" connections={[]} alt="落冰" />);
    expect(container.querySelector("canvas")).toBeInTheDocument();
  });
```

Keep the existing `PoseViewer` unchanged in P0; it has tracker diagnostic drawing that the focused phase-card renderer must not accidentally remove.

- [ ] **Step 6: Run tests and build**

Run:

```powershell
npm --prefix frontend test
npm --prefix frontend run build
```

Expected: all Vitest tests PASS and the TypeScript/Vite build exits 0.

- [ ] **Step 7: Commit the frontend evidence primitive**

```powershell
git add frontend/package.json frontend/package-lock.json frontend/vite.config.ts frontend/tsconfig.json frontend/src/test/setup.ts frontend/src/utils/poseCanvas.ts frontend/src/utils/poseCanvas.test.ts frontend/src/components/PoseFrameCanvas.tsx frontend/src/components/PoseFrameCanvas.test.tsx
git commit -m "feat: add reusable pose frame canvas"
```

---

### Task 3: Profile-aware Action Phase Review

**Files:**
- Create: `frontend/src/components/ActionPhaseStrip.tsx`
- Create: `frontend/src/components/ActionPhaseStrip.test.tsx`
- Modify: `frontend/src/pages/ReportPage.tsx:730-770`
- Modify: `frontend/src/pages/ReportPage.tsx:1278-1365`
- Test: `frontend/src/utils/keyframeEvidence.test.ts`

**Interfaces:**
- Consumes: `buildCurrentKeyframeEvidenceItems(analysis)` and `PoseResponse`.
- Produces: `<ActionPhaseStrip analysis pose showVideo={boolean} />` with internal video seeking.

- [ ] **Step 1: Write failing phase-contract and interaction tests**

Create `frontend/src/components/ActionPhaseStrip.test.tsx` with fixtures for jump and spin:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { AnalysisDetail, PoseResponse } from "../api/client";
import ActionPhaseStrip from "./ActionPhaseStrip";

const pose: PoseResponse = {
  connections: [],
  frames: [{ frame: "frame_0010.jpg", keypoints: [] }],
  frame_urls: { "frame_0010.jpg": "/frame.jpg" },
  frame_timestamps: { frame_0010: 2.4 },
};

const jump = {
  id: "analysis-1",
  analysis_profile: "jump",
  bio_data: { key_frames: { T: "frame_0010", A: "", L: "" } },
  video_temporal_diagnostics: { selected_semantic_frames: [{ frame_id: "frame_0010", phase_code: "T", timestamp: 2.4 }] },
} as unknown as AnalysisDetail;

describe("ActionPhaseStrip", () => {
  it("renders T/A/L in order and preserves missing phases", () => {
    render(<ActionPhaseStrip analysis={jump} pose={pose} showVideo={false} />);
    expect(screen.getAllByRole("heading", { level: 3 }).map((item) => item.textContent)).toEqual(["起跳", "腾空", "落冰"]);
    expect(screen.getAllByText("当前阶段没有可展示的画面")).toHaveLength(2);
    expect(screen.queryByText("准备")).not.toBeInTheDocument();
  });

  it("seeks the bundled video to the stored timestamp", () => {
    render(<ActionPhaseStrip analysis={jump} pose={pose} showVideo />);
    const video = screen.getByTestId("phase-video") as HTMLVideoElement;
    Object.defineProperty(video, "currentTime", { value: 0, writable: true });
    fireEvent.click(screen.getByRole("button", { name: "查看起跳 2.400s" }));
    expect(video.currentTime).toBe(2.4);
  });
});
```

Add a pure utility test in `frontend/src/utils/keyframeEvidence.test.ts` asserting spin produces `入转/主转/出转`, spiral produces one `姿态保持`, and step produces one `步法区间`.

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
npm --prefix frontend test -- src/components/ActionPhaseStrip.test.tsx src/utils/keyframeEvidence.test.ts
```

Expected: FAIL because `ActionPhaseStrip` does not exist.

- [ ] **Step 3: Implement the action-phase component**

Create `frontend/src/components/ActionPhaseStrip.tsx`. It must:

```tsx
import { useMemo, useRef } from "react";
import type { AnalysisDetail, PoseResponse } from "../api/client";
import { buildCurrentKeyframeEvidenceItems, formatKeyframeTimestamp, keyframeConfidenceLabel } from "../utils/keyframeEvidence";
import PoseFrameCanvas from "./PoseFrameCanvas";

type Props = { analysis: AnalysisDetail; pose: PoseResponse | null; showVideo?: boolean };

function frameKey(value: string) {
  return value.replace(/\.jpg$/i, "");
}

export default function ActionPhaseStrip({ analysis, pose, showVideo = true }: Props) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const items = useMemo(() => buildCurrentKeyframeEvidenceItems(analysis), [analysis]);
  const frames = pose?.frames ?? [];

  return (
    <section className="app-card overflow-hidden p-4 phone:p-5 tablet:p-6" aria-labelledby="action-phase-title">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">Key Moments</p>
        <h2 id="action-phase-title" className="mt-2 text-2xl font-semibold text-slate-900">关键动作阶段</h2>
        <p className="mt-2 text-sm leading-6 text-slate-500">这里展示实际姿态证据，不代表标准动作判定。</p>
      </div>
      {showVideo ? <video ref={videoRef} data-testid="phase-video" controls preload="metadata" src={`/api/analysis/${analysis.id}/video`} className="mt-5 aspect-video w-full rounded-[22px] bg-slate-950 object-contain" /> : null}
      <div className="mt-5 flex snap-x gap-4 overflow-x-auto pb-2 tablet:grid tablet:grid-cols-3 tablet:overflow-visible">
        {items.map((item) => {
          const frame = item.frameId ? frames.find((candidate) => frameKey(candidate.frame) === frameKey(item.frameId!)) ?? null : null;
          const frameUrl = frame && pose ? pose.frame_urls[frame.frame] ?? item.imageUrl : item.imageUrl;
          const timestampLabel = formatKeyframeTimestamp(item.timestamp);
          return (
            <article key={item.key} className="min-w-[82%] snap-start overflow-hidden rounded-[22px] border border-slate-200 bg-white phone:min-w-[68%] tablet:min-w-0">
              <PoseFrameCanvas frame={frame} frameUrl={frameUrl} connections={pose?.connections ?? []} alt={`${item.label}关键帧`} />
              <div className="p-4">
                <h3 className="text-lg font-semibold text-slate-900">{item.label}</h3>
                <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-500">
                  <span>{timestampLabel}</span><span>{item.source}</span><span>{keyframeConfidenceLabel(item.confidence) ?? "置信度暂无"}</span>
                </div>
                <button
                  type="button"
                  aria-label={`查看${item.label} ${timestampLabel}`}
                  disabled={item.timestamp == null || !showVideo}
                  onClick={() => {
                    if (videoRef.current && item.timestamp != null) {
                      videoRef.current.currentTime = item.timestamp;
                      void videoRef.current.play().catch(() => undefined);
                    }
                  }}
                  className="mt-3 min-h-[40px] w-full rounded-full bg-blue-50 px-4 py-2 text-sm font-semibold text-blue-600 disabled:opacity-45"
                >
                  跳到这一刻
                </button>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
```

Use the existing timestamp and confidence formatters; do not introduce a second display contract for the same stored evidence.

- [ ] **Step 4: Add the phase review to the completed report**

Import `ActionPhaseStrip` in `ReportPage.tsx`. Directly after the report summary header section and before the two-column report content, render:

```tsx
<ActionPhaseStrip
  analysis={deferredAnalysis}
  pose={deferredAnalysis.pose_data}
  showVideo
/>
```

Do not add another API request; `AnalysisDetail` already carries `pose_data` and resolved evidence.

- [ ] **Step 5: Run focused tests and build**

```powershell
npm --prefix frontend test -- src/components/ActionPhaseStrip.test.tsx src/utils/keyframeEvidence.test.ts
npm --prefix frontend run build
```

Expected: tests PASS and build exits 0.

- [ ] **Step 6: Commit the phase review**

```powershell
git add frontend/src/components/ActionPhaseStrip.tsx frontend/src/components/ActionPhaseStrip.test.tsx frontend/src/utils/keyframeEvidence.test.ts frontend/src/pages/ReportPage.tsx
git commit -m "feat: show profile-aware action phases"
```

---

### Task 4: KPI Bar And Milestone Timeline

**Files:**
- Create: `frontend/src/components/GrowthKpiBar.tsx`
- Create: `frontend/src/components/GrowthKpiBar.test.tsx`
- Create: `frontend/src/components/MilestoneTimeline.tsx`
- Create: `frontend/src/components/MilestoneTimeline.test.tsx`
- Modify: `frontend/src/api/client.ts:379-440`
- Modify: `frontend/src/api/client.ts:1252-1266`

**Interfaces:**
- Consumes: Task 1 `GrowthSummaryResponse` JSON.
- Produces: TypeScript `GrowthSummary`, `GrowthFocus`, and `GrowthMilestone`.
- Produces: `fetchGrowthSummary(skaterId, milestoneLimit?): Promise<GrowthSummary>`.
- Produces: `<GrowthKpiBar summary />` and `<MilestoneTimeline items />`.

- [ ] **Step 1: Add exact client contracts and fetch function**

Add to `frontend/src/api/client.ts`:

```typescript
export type MilestoneVerification = "system_detected" | "parent_confirmed" | "coach_confirmed";

export interface GrowthFocus {
  label: string;
  source_analysis_id: string;
  quality: string;
}

export interface GrowthMilestone {
  id: string;
  occurred_at: string;
  type: string;
  title: string;
  note: string | null;
  verification: MilestoneVerification;
  source_skill_id: string;
  source_analysis_ids: string[];
  evidence_quality: string;
}

export interface GrowthSummary {
  schema_version: 1;
  skater_id: string;
  as_of: string;
  lesson_count: number;
  completed_analysis_count: number;
  current_month_analysis_count: number;
  milestone_count: number;
  latest_analysis_id: string | null;
  current_focus: GrowthFocus | null;
  metric_definitions: Record<string, string>;
  recent_milestones: GrowthMilestone[];
}

export async function fetchGrowthSummary(skaterId: string, milestoneLimit = 8) {
  const response = await apiClient.get<GrowthSummary>(`/skaters/${skaterId}/growth-summary`, {
    params: { milestone_limit: milestoneLimit },
  });
  return response.data;
}
```

- [ ] **Step 2: Write failing component tests**

Create `frontend/src/components/GrowthKpiBar.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { GrowthSummary } from "../api/client";
import GrowthKpiBar from "./GrowthKpiBar";

const summary = {
  lesson_count: 8,
  completed_analysis_count: 12,
  current_month_analysis_count: 3,
  milestone_count: 4,
  metric_definitions: {
    lesson_count: "课次定义",
    completed_analysis_count: "累计定义",
    current_month_analysis_count: "本月定义",
    milestone_count: "里程碑定义",
  },
} as GrowthSummary;

describe("GrowthKpiBar", () => {
  it("renders only the four defined P0 metrics with definitions", () => {
    render(<GrowthKpiBar summary={summary} />);
    for (const label of ["训练课次", "累计复盘", "本月复盘", "成长里程碑"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getByTitle("课次定义")).toBeInTheDocument();
    expect(screen.queryByText(/落冰率/)).not.toBeInTheDocument();
  });
});
```

Create `frontend/src/components/MilestoneTimeline.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { GrowthMilestone } from "../api/client";
import MilestoneTimeline from "./MilestoneTimeline";

const event = (id: string, verification: GrowthMilestone["verification"], note: string | null): GrowthMilestone => ({
  id,
  occurred_at: `2026-07-${id}T00:00:00Z`,
  type: "skill_unlock",
  title: `里程碑 ${id}`,
  note,
  verification,
  source_skill_id: `skill-${id}`,
  source_analysis_ids: [],
  evidence_quality: "persisted",
});

describe("MilestoneTimeline", () => {
  it("preserves API order and verification source", () => {
    render(<MilestoneTimeline items={[
      event("18", "parent_confirmed", "连续完成三次"),
      event("17", "coach_confirmed", null),
      event("16", "system_detected", null),
    ]} />);
    expect(screen.getAllByRole("listitem").map((item) => item.textContent?.includes("里程碑 18"))).toEqual([true, false, false]);
    expect(screen.getByText("家长确认")).toBeInTheDocument();
    expect(screen.getByText("教练确认")).toBeInTheDocument();
    expect(screen.getByText("系统检测")).toBeInTheDocument();
    expect(screen.getAllByText("连续完成三次")).toHaveLength(1);
  });

  it("renders an explicit empty state", () => {
    render(<MilestoneTimeline items={[]} />);
    expect(screen.getByText("还没有已确认的成长里程碑")).toBeInTheDocument();
  });
});
```

Use these verification labels in the implementation:

```typescript
const verificationLabels = {
  system_detected: "系统检测",
  parent_confirmed: "家长确认",
  coach_confirmed: "教练确认",
};
```

- [ ] **Step 3: Run tests to verify they fail**

```powershell
npm --prefix frontend test -- src/components/GrowthKpiBar.test.tsx src/components/MilestoneTimeline.test.tsx
```

Expected: FAIL because the components do not exist.

- [ ] **Step 4: Implement the KPI bar**

Create `GrowthKpiBar.tsx` with this fixed P0 metric set:

```tsx
import type { GrowthSummary } from "../api/client";

export default function GrowthKpiBar({ summary }: { summary: GrowthSummary }) {
  const items = [
    ["训练课次", summary.lesson_count, "lesson_count"],
    ["累计复盘", summary.completed_analysis_count, "completed_analysis_count"],
    ["本月复盘", summary.current_month_analysis_count, "current_month_analysis_count"],
    ["成长里程碑", summary.milestone_count, "milestone_count"],
  ] as const;
  return (
    <section className="app-card p-4 tablet:p-5" aria-label="成长数据摘要">
      <div className="grid grid-cols-2 gap-3 tablet:grid-cols-4">
        {items.map(([label, value, definitionKey]) => (
          <article key={definitionKey} title={summary.metric_definitions[definitionKey]} className="rounded-[20px] bg-slate-50 px-4 py-4">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">{label}</p>
            <p className="mt-2 text-3xl font-semibold text-slate-900">{value}</p>
          </article>
        ))}
      </div>
    </section>
  );
}
```

- [ ] **Step 5: Implement the milestone timeline**

Create `frontend/src/components/MilestoneTimeline.tsx`:

```tsx
import type { GrowthMilestone, MilestoneVerification } from "../api/client";

const LABELS: Record<MilestoneVerification, string> = {
  system_detected: "系统检测",
  parent_confirmed: "家长确认",
  coach_confirmed: "教练确认",
};

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(value));
}

export default function MilestoneTimeline({ items }: { items: GrowthMilestone[] }) {
  return (
    <section className="app-card p-4 phone:p-5 tablet:p-6" aria-labelledby="milestone-title">
      <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">Highlights</p>
      <h2 id="milestone-title" className="mt-2 text-2xl font-semibold text-slate-900">成长里程碑</h2>
      {items.length ? (
        <ol className="mt-5 space-y-4">
          {items.map((item) => (
            <li key={item.id} className="rounded-[22px] border border-slate-200 bg-slate-50 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <time dateTime={item.occurred_at} className="text-sm text-slate-500">{formatDate(item.occurred_at)}</time>
                <span className="rounded-full bg-white px-3 py-1 text-xs font-semibold text-blue-600">
                  {LABELS[item.verification] ?? LABELS.system_detected}
                </span>
              </div>
              <h3 className="mt-3 text-lg font-semibold text-slate-900">{item.title}</h3>
              {item.note ? <p className="mt-2 text-sm leading-6 text-slate-600">{item.note}</p> : null}
            </li>
          ))}
        </ol>
      ) : <p className="mt-5 rounded-[20px] bg-slate-50 p-5 text-sm text-slate-500">还没有已确认的成长里程碑</p>}
    </section>
  );
}
```

- [ ] **Step 6: Run tests and build**

```powershell
npm --prefix frontend test -- src/components/GrowthKpiBar.test.tsx src/components/MilestoneTimeline.test.tsx
npm --prefix frontend run build
```

Expected: tests PASS and build exits 0.

- [ ] **Step 7: Commit the summary components**

```powershell
git add frontend/src/api/client.ts frontend/src/components/GrowthKpiBar.tsx frontend/src/components/GrowthKpiBar.test.tsx frontend/src/components/MilestoneTimeline.tsx frontend/src/components/MilestoneTimeline.test.tsx
git commit -m "feat: add growth KPI and milestone views"
```

---

### Task 5: Unified Growth Home

**Files:**
- Create: `frontend/src/pages/GrowthHomePage.tsx`
- Create: `frontend/src/pages/GrowthHomePage.test.tsx`
- Modify: `frontend/src/App.tsx:1-20`
- Modify: `frontend/src/App.tsx:118-130`

**Interfaces:**
- Consumes: `fetchSkaters`, `fetchGrowthSummary`, `fetchAnalysis`, and Tasks 3-4 components.
- Produces: route `/home` and root redirect `/ -> /home`.

- [ ] **Step 1: Write the failing page composition test**

Create `frontend/src/pages/GrowthHomePage.test.tsx`:

```tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchAnalysis, fetchGrowthSummary, fetchSkaters } from "../api/client";
import type { AnalysisDetail, GrowthSummary, Skater } from "../api/client";
import GrowthHomePage from "./GrowthHomePage";

vi.mock("../api/client", () => ({ fetchAnalysis: vi.fn(), fetchGrowthSummary: vi.fn(), fetchSkaters: vi.fn() }));
vi.mock("../components/ActionPhaseStrip", () => ({ default: () => <div>阶段联图</div> }));

const summary: GrowthSummary = {
  schema_version: 1,
  skater_id: "skater-1",
  as_of: "2026-07-22T00:00:00Z",
  lesson_count: 8,
  completed_analysis_count: 12,
  current_month_analysis_count: 3,
  milestone_count: 4,
  latest_analysis_id: "analysis-1",
  current_focus: { label: "落冰保持", source_analysis_id: "analysis-1", quality: "good" },
  metric_definitions: {
    lesson_count: "已保存且互不重复的训练课次",
    completed_analysis_count: "状态为 completed 的视频复盘",
    current_month_analysis_count: "本自然月完成的视频复盘",
    milestone_count: "具有 unlocked_at 时间的技能点亮记录",
  },
  recent_milestones: [],
};

const skaters = [
  { id: "skater-1", name: "tantan", display_name: "坦坦", is_default: true },
  { id: "skater-2", name: "zhaozhao", display_name: "昭昭", is_default: false },
] as Skater[];
const analysis = {
  id: "analysis-1",
  report: {
    summary: "这次落冰更稳定",
    training_focus: "落冰保持",
    improvements: [{ target: "膝盖缓冲", action: "做三组落冰定格" }],
  },
  pose_data: null,
} as unknown as AnalysisDetail;

describe("GrowthHomePage", () => {
  beforeEach(() => {
    vi.mocked(fetchSkaters).mockResolvedValue(skaters);
    vi.mocked(fetchGrowthSummary).mockImplementation(async (id) => ({
      ...summary,
      skater_id: id,
      latest_analysis_id: id === "skater-1" ? "analysis-1" : null,
    }));
    vi.mocked(fetchAnalysis).mockResolvedValue(analysis);
  });

  it("loads the default skater and composes the growth story", async () => {
    render(<MemoryRouter><GrowthHomePage /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "看见每次训练，积累每一步进步" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "当前练习档案" })).toHaveValue("skater-1");
    expect(screen.getByText("落冰保持")).toBeInTheDocument();
    expect(screen.getByText("这次落冰更稳定")).toBeInTheDocument();
    expect(screen.getByText("做三组落冰定格")).toBeInTheDocument();
    expect(await screen.findByText("阶段联图")).toBeInTheDocument();
  });

  it("reloads the selected skater and handles an empty analysis history", async () => {
    render(<MemoryRouter><GrowthHomePage /></MemoryRouter>);
    fireEvent.change(await screen.findByRole("combobox", { name: "当前练习档案" }), { target: { value: "skater-2" } });
    await waitFor(() => expect(fetchGrowthSummary).toHaveBeenCalledWith("skater-2"));
    expect(await screen.findByText("完成第一次复盘后，这里会出现关键动作阶段")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the page test to verify it fails**

```powershell
npm --prefix frontend test -- src/pages/GrowthHomePage.test.tsx
```

Expected: FAIL because `GrowthHomePage` does not exist.

- [ ] **Step 3: Implement page loading and stale-request protection**

Create `frontend/src/pages/GrowthHomePage.tsx` with separate skater, summary, and latest-analysis states. Use two effects with local `cancelled` flags: the first loads skaters and selects `is_default` or the first item; the second clears old content, calls `fetchGrowthSummary(selectedId)`, then calls `fetchAnalysis(latest_analysis_id)` only when that ID exists.

Render, in order:

1. An `.app-card` header with the exact heading `看见每次训练，积累每一步进步` and an accessible skater `<select aria-label="当前练习档案">`.
2. Error or loading state.
3. `<GrowthKpiBar summary={summary} />`.
4. Three cards using only: `report.summary`, `summary.current_focus.label`, and `report.improvements[0].action` with `report.training_focus` as fallback.
5. `<ActionPhaseStrip analysis={latestAnalysis} pose={latestAnalysis.pose_data} showVideo />`, or the exact no-history text from the test.
6. `<MilestoneTimeline items={summary.recent_milestones} />`.
7. Links to the latest report when available, `/archive`, and `/path`.

Do not infer conclusions or rates beyond those source fields.

- [ ] **Step 4: Register the route**

In `App.tsx` import `GrowthHomePage`, change the root redirect, and register the page:

```tsx
<Route path="/" element={<Navigate to="/home" replace />} />
<Route element={<AppLayout />}>
  <Route path="/home" element={<GrowthHomePage />} />
  <Route path="/path" element={<SkillTreePage />} />
  <Route path="/snowball" element={<SnowballPage />} />
  <Route path="/review" element={<ReviewPage />} />
  <Route path="/analysis-chat" element={<AnalysisChatPage />} />
  <Route path="/archive" element={<ArchivePage />} />
  <Route path="/history" element={<HistoryPage />} />
  {/* Retain the existing compare, report, settings, debug, and Golden child routes after these entries. */}
```

- [ ] **Step 5: Run tests and build**

```powershell
npm --prefix frontend test -- src/pages/GrowthHomePage.test.tsx
npm --prefix frontend run build
```

Expected: test PASS and build exits 0.

- [ ] **Step 6: Commit the growth home**

```powershell
git add frontend/src/pages/GrowthHomePage.tsx frontend/src/pages/GrowthHomePage.test.tsx frontend/src/App.tsx
git commit -m "feat: add parent growth home"
```

---

### Task 6: Four-concept Primary Navigation

**Files:**
- Create: `frontend/src/navigation.ts`
- Create: `frontend/src/navigation.test.ts`
- Create: `frontend/src/components/AdvancedToolsLinks.tsx`
- Create: `frontend/src/components/AdvancedToolsLinks.test.tsx`
- Modify: `frontend/src/components/BottomNav.tsx:1-32`
- Modify: `frontend/src/components/AppLayout.tsx:1-52`
- Modify: `frontend/src/components/AppHeader.tsx:1-30`
- Modify: `frontend/src/pages/SettingsPage.tsx`

**Interfaces:**
- Produces: `PRIMARY_NAV_ITEMS` with Home, Review, Progress, Profile.
- Produces: `primaryTabForPath(pathname): PrimaryTab | undefined`.
- Preserves: all non-primary routes and adds a persistent settings link in the header.

- [ ] **Step 1: Write the failing navigation contract test**

Create `frontend/src/navigation.test.ts`:

```typescript
import { describe, expect, it } from "vitest";
import { PRIMARY_NAV_ITEMS, primaryTabForPath } from "./navigation";

describe("primary navigation", () => {
  it("contains exactly the four parent concepts", () => {
    expect(PRIMARY_NAV_ITEMS.map((item) => [item.label, item.to])).toEqual([
      ["首页", "/home"],
      ["复盘", "/review"],
      ["进步", "/archive"],
      ["档案", "/path"],
    ]);
  });

  it("keeps detail routes attached to their parent concept", () => {
    expect(primaryTabForPath("/report/analysis-1")).toBe("review");
    expect(primaryTabForPath("/analysis-chat")).toBe("review");
    expect(primaryTabForPath("/history")).toBe("archive");
    expect(primaryTabForPath("/compare/a/b")).toBe("archive");
    expect(primaryTabForPath("/settings")).toBeUndefined();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```powershell
npm --prefix frontend test -- src/navigation.test.ts
```

Expected: FAIL because `navigation.ts` does not exist.

- [ ] **Step 3: Implement shared navigation configuration**

Create `frontend/src/navigation.ts`:

```typescript
export type PrimaryTab = "home" | "review" | "archive" | "path";

export const PRIMARY_NAV_ITEMS = [
  { tab: "home", to: "/home", label: "首页", detail: "成长总览", icon: "🏠" },
  { tab: "review", to: "/review", label: "复盘", detail: "上传与分析", icon: "🎬" },
  { tab: "archive", to: "/archive", label: "进步", detail: "趋势与历史", icon: "📈" },
  { tab: "path", to: "/path", label: "档案", detail: "技能与目标", icon: "⛸️" },
] as const;

const TAB_PATHS: Record<PrimaryTab, string[]> = {
  home: ["/home"],
  review: ["/review", "/report", "/analysis-chat"],
  archive: ["/archive", "/history", "/compare"],
  path: ["/path", "/plan", "/snowball"],
};

export function primaryTabForPath(pathname: string): PrimaryTab | undefined {
  return (Object.entries(TAB_PATHS) as Array<[PrimaryTab, string[]]>).find(([, paths]) =>
    paths.some((path) => pathname.startsWith(path)),
  )?.[0];
}
```

- [ ] **Step 4: Replace duplicated nav arrays and retain advanced access**

- `BottomNav.tsx` imports `PRIMARY_NAV_ITEMS` and `PrimaryTab`; both child and parent modes use the same four primary concepts.
- `AppLayout.tsx` imports the same array and `primaryTabForPath`; modern and classic layouts render identical concepts.
- `AppHeader.tsx` adds a 44px settings `Link` with `aria-label="打开设置"` beside the existing toggles.
- Keep `/analysis-chat`, `/history`, `/golden`, `/debug`, and `/settings` routes unchanged.
- Replace sidebar copy that lists the old eight entries with `首页、复盘、进步和档案构成主线；设置里保留标注与调试工具。`

Create `frontend/src/components/AdvancedToolsLinks.tsx` and render it as the last settings card:

```tsx
import { Link } from "react-router-dom";

const tools = [
  ["历史记录", "/history"],
  ["AI 追问", "/analysis-chat"],
  ["Golden 标注", "/golden"],
  ["诊断调试", "/debug"],
  ["API 设置", "/settings/api"],
] as const;

export default function AdvancedToolsLinks() {
  return (
    <section className="app-card p-5 tablet:p-6" aria-labelledby="advanced-tools-title">
      <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">Advanced</p>
      <h2 id="advanced-tools-title" className="mt-2 text-2xl font-semibold text-slate-900">高级工具</h2>
      <div className="mt-5 grid gap-3 phone:grid-cols-2 tablet:grid-cols-3">
        {tools.map(([label, to]) => <Link key={to} className="app-pill justify-center" to={to}>{label}</Link>)}
      </div>
    </section>
  );
}
```

Create `frontend/src/components/AdvancedToolsLinks.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import AdvancedToolsLinks from "./AdvancedToolsLinks";

describe("AdvancedToolsLinks", () => {
  it("keeps every non-primary workflow discoverable", () => {
    render(<MemoryRouter><AdvancedToolsLinks /></MemoryRouter>);
    expect(screen.getByRole("link", { name: "历史记录" })).toHaveAttribute("href", "/history");
    expect(screen.getByRole("link", { name: "AI 追问" })).toHaveAttribute("href", "/analysis-chat");
    expect(screen.getByRole("link", { name: "Golden 标注" })).toHaveAttribute("href", "/golden");
    expect(screen.getByRole("link", { name: "诊断调试" })).toHaveAttribute("href", "/debug");
    expect(screen.getByRole("link", { name: "API 设置" })).toHaveAttribute("href", "/settings/api");
  });
});
```

- [ ] **Step 5: Run the complete frontend suite and build**

```powershell
npm --prefix frontend test
npm --prefix frontend run build
```

Expected: all tests PASS and build exits 0.

- [ ] **Step 6: Commit the navigation change**

```powershell
git add frontend/src/navigation.ts frontend/src/navigation.test.ts frontend/src/components/AdvancedToolsLinks.tsx frontend/src/components/AdvancedToolsLinks.test.tsx frontend/src/components/BottomNav.tsx frontend/src/components/AppLayout.tsx frontend/src/components/AppHeader.tsx frontend/src/pages/SettingsPage.tsx
git commit -m "feat: simplify primary growth navigation"
```

---

### Task 7: Integrated Verification And Rendered QA

**Files:**
- Modify only if verification reveals a defect in files introduced by Tasks 1-6.
- Record screenshots locally; do not commit personal video frames.

**Interfaces:**
- Consumes: all P0 tasks.
- Produces: verification evidence for backend contracts, frontend behavior, responsive rendering, and no-new-model-call constraint.

- [ ] **Step 1: Run backend regression tests**

```powershell
$env:PYTHONPATH='backend'
python -m pytest backend/tests/test_growth_summary.py backend/tests/test_skaters_archive.py backend/tests/test_skills.py backend/tests/test_analysis_compare.py -q
```

Expected: all tests PASS.

- [ ] **Step 2: Run the complete frontend tests and build**

```powershell
npm --prefix frontend test
npm --prefix frontend run build
```

Expected: all Vitest tests PASS and build exits 0.

- [ ] **Step 3: Verify the endpoint against local data**

Start the existing backend/frontend development stack. Request one real skater summary and verify:

```powershell
$skaterId = (Invoke-RestMethod 'http://127.0.0.1:8000/api/skaters/')[0].id
Invoke-RestMethod "http://127.0.0.1:8000/api/skaters/$skaterId/growth-summary?milestone_limit=8" | ConvertTo-Json -Depth 6
```

Expected:

- `schema_version` is `1`;
- counts are non-negative integers;
- no `landing_rate` key exists;
- milestone verification values belong to the three allowed labels;
- `latest_analysis_id` is null or belongs to a completed analysis.

- [ ] **Step 4: Perform rendered browser QA**

Use the frontend testing/debugging browser workflow at phone (390x844), tablet (820x1180), and desktop (1440x1000). Verify:

- `/home` displays the selected skater, four KPIs, current focus, phase strip, and milestone timeline;
- portrait and landscape source frames remain undistorted and skeletons align to the contained image area;
- jump shows T/A/L without a fabricated prep card;
- spin, step, and spiral use their profile-specific labels;
- missing phase evidence displays an unavailable card;
- clicking an available phase seeks the bundled video to the stored timestamp;
- the mobile nav contains exactly four items and no item is clipped;
- settings remains reachable from the header;
- report, archive, history, chat, Golden, debug, and settings URLs still open;
- browser console contains no new errors.

- [ ] **Step 5: Confirm no model-call path was added**

Run:

```powershell
git diff HEAD~6..HEAD -- backend/app/services/growth_summary.py backend/app/routers/skaters.py frontend/src/pages/GrowthHomePage.tsx | rg -n "provider|completion|vision|DeepSeek|QWEN|MiMo|generate_report"
```

Expected: no matches that invoke or configure a model provider. References inside existing analysis response field names are acceptable only outside the new aggregation service.

- [ ] **Step 6: Commit verification-only fixes if needed**

If QA required code changes, rerun Steps 1-5, inspect `git status --short`, and stage each verified P0 file by its literal path. For example, when only the phase strip needed a fix:

```powershell
git add -- frontend/src/components/ActionPhaseStrip.tsx frontend/src/components/ActionPhaseStrip.test.tsx
git commit -m "fix: polish growth home verification findings"
```

If no fixes were required, do not create an empty commit.

---

## Completion Gate

P0 is complete only when:

- the growth summary is authoritative, versioned, and contains no landing-rate field;
- the report and growth home show profile-specific phase evidence with explicit missing states;
- skeleton overlays stay aligned for portrait and landscape frames;
- milestones preserve their verification source;
- the growth home answers latest outcome, focus, next action, monthly activity, and recent highlights;
- primary navigation contains Home, Review, Progress, and Profile while advanced routes remain usable;
- no new model call or analysis mutation was introduced;
- focused backend tests, complete frontend tests, frontend build, and rendered QA all pass.
