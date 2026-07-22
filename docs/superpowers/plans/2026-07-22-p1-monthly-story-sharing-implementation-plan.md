# P1 Monthly Story And Sharing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add reviewable monthly growth chapters, semantically distinct family quotes, and milestone share cards on top of the completed P0 growth home.

**Architecture:** Persist immutable monthly fact snapshots before any text generation, call only the existing `report` provider with structured JSON, and store generated and parent-edited text as separate fields. Reuse the existing P0 milestone contract and Canvas sharing primitives; do not recalculate authoritative facts in React.

**Tech Stack:** FastAPI, SQLAlchemy/SQLite, Pydantic, existing provider layer, React 18, TypeScript, Canvas, Vitest, pytest.

## Global Constraints

- P0 commits `51a3524`, `57f693a`, `92e62e9`, and `37ae71a` are prerequisites.
- AI receives a deterministic fact snapshot, not unrestricted database rows or raw videos.
- Generated claims must reference valid fact IDs. Unknown references reject the response.
- Do not infer fear, fatigue, injury risk, coaching verification, formal level readiness, or predicted test dates.
- `draft_text` is model output; `final_text` is parent-editable. Publishing never silently overwrites either.
- A published chapter is immutable. Regeneration creates the next revision.
- Initial generation is manual. Do not add cron or automatic billing-period generation in P1.
- Existing operational `note` fields remain unchanged. Family quotes use dedicated fields.
- Quotes retain their declared speaker and are never rewritten as another person's words.
- Milestone share cards preserve `system_detected`, `parent_confirmed`, and `coach_confirmed` labels.
- No landing-rate claim is allowed until a versioned attempt/outcome contract exists.
- Source design: `docs/superpowers/specs/2026-07-22-growth-story-product-design.md`.

---

## File Map

### Backend

- Modify `backend/app/models.py`: add quote fields and `MonthlyChapter`.
- Modify `backend/app/database.py`: additive migration for quote columns and chapter table.
- Modify `backend/app/schemas.py`: fact, generation, edit, publish, and list contracts.
- Create `backend/app/services/monthly_facts.py`: deterministic fact aggregation and source hashing.
- Create `backend/app/services/monthly_chapters.py`: generation prompt, structured validation, revisions, and publication.
- Create `backend/app/routers/growth.py`: `/api/growth` chapter endpoints.
- Modify `backend/app/main.py`: register the growth router.
- Modify `backend/app/routers/analysis.py`: accept and persist upload quote fields.
- Create `backend/tests/test_monthly_facts.py`, `test_monthly_chapters.py`, and `test_growth_routes.py`.

### Frontend

- Modify `frontend/src/api/client.ts`: quote fields and monthly chapter API contracts.
- Modify `frontend/src/pages/ReviewPage.tsx`: optional quote/speaker controls.
- Create `frontend/src/pages/MonthlyChaptersPage.tsx` and its test.
- Create `frontend/src/components/MonthlyFactPreview.tsx` and its test.
- Create `frontend/src/components/MonthlyChapterEditor.tsx` and its test.
- Create `frontend/src/utils/milestoneShareCanvas.ts` and its test.
- Create `frontend/src/components/MilestoneShareDialog.tsx` and its test.
- Modify `frontend/src/components/MilestoneTimeline.tsx`: open the share dialog.
- Modify `frontend/src/pages/GrowthHomePage.tsx` and `frontend/src/App.tsx`: chapter entry and route.

---

## Data Contracts

### Analysis quote fields

```python
highlight_quote: str | None
quote_speaker: str | None  # skater | parent | coach
```

Maximum normalized quote length is 280 characters. `quote_speaker` must be null when the quote is empty.

### MonthlyChapter

```python
class MonthlyChapter(Base):
    __tablename__ = "monthly_chapters"
    __table_args__ = (UniqueConstraint("skater_id", "year_month", "revision", name="uq_monthly_chapter_revision"),)

    id: Mapped[str]
    skater_id: Mapped[str]
    year_month: Mapped[str]       # YYYY-MM
    revision: Mapped[int]
    status: Mapped[str]           # facts_ready | generated | published | stale
    fact_snapshot: Mapped[dict]
    source_hash: Mapped[str]
    prompt_version: Mapped[str | None]
    provider_id: Mapped[str | None]
    provider_name: Mapped[str | None]
    model_id: Mapped[str | None]
    generated_payload: Mapped[dict | None]
    draft_text: Mapped[str | None]
    final_text: Mapped[str | None]
    quality_flags: Mapped[list]
    representative_frames: Mapped[list]
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
    published_at: Mapped[datetime | None]
```

### Fact snapshot v1

```json
{
  "schema_version": "monthly_facts.v1",
  "skater_id": "skater-uuid",
  "year_month": "2026-07",
  "generated_at": "2026-07-31T12:00:00Z",
  "coverage": {"sessions": 4, "completed_analyses": 7, "comparable_metrics": 2},
  "facts": [
    {"id": "session_count", "kind": "count", "text": "本月记录 4 次训练课次", "value": 4},
    {"id": "milestone:skill-id", "kind": "milestone", "text": "华尔兹跳已点亮", "verification": "parent_confirmed"},
    {"id": "quote:analysis-id", "kind": "quote", "text": "我今天敢往后滑了", "speaker": "skater"}
  ],
  "source_analysis_ids": ["analysis-uuid"],
  "source_session_ids": ["session-uuid"],
  "source_skill_ids": ["skill-id"],
  "quality_flags": []
}
```

Fact order is deterministic: counts, comparable metrics, milestones, recurring observations, then quotes; each group sorts by stable ID/date.

---

### Task 1: Quote Fields And Migration

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/database.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/routers/analysis.py:8243`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/pages/ReviewPage.tsx`
- Test: `backend/tests/test_analysis_upload.py` or the existing upload-route test module
- Test: `frontend/src/pages/ReviewPage.test.tsx`

**Produces:** upload form fields `highlight_quote` and `quote_speaker` and persisted `Analysis` columns.

- [ ] Add a failing backend test that submits `highlight_quote="我今天敢往后滑了"`, `quote_speaker="skater"`, then asserts both fields persist.
- [ ] Add rejection tests for speaker `unknown`, quote length 281, and speaker-without-quote.
- [ ] Run the focused upload tests and confirm RED.
- [ ] Add nullable columns to `Analysis` and `AnalysisDetail`; add `run_migrations_growth_story()` that inspects `PRAGMA table_info(analyses)` and adds the two columns idempotently.
- [ ] Extend `upload_analysis()` with `highlight_quote: str | None = Form(default=None)` and `quote_speaker: str | None = Form(default=None)`. Normalize whitespace and validate against `{"skater", "parent", "coach"}` before creating the row.
- [ ] Extend TypeScript `AnalysisListItem`/`AnalysisDetail` and the Review draft state. Add an optional textarea labeled `今天最想记住的一句话（可选）`, a speaker select, counter `0/280`, and append the two form values only when the quote is nonempty.
- [ ] Add a frontend test that fills the quote, chooses `孩子本人`, submits, and asserts the outgoing `FormData` has `highlight_quote` and `quote_speaker=skater`.
- [ ] Run backend tests, frontend test, and `npm --prefix frontend run build`.
- [ ] Commit: `feat: add family highlight quotes`.

### Task 2: Monthly Chapter Persistence

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/database.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_monthly_chapters.py`

**Produces:** `MonthlyChapter`, `MonthlyChapterPublic`, and idempotent additive migration.

- [ ] Write failing tests for table creation, `(skater_id, year_month, revision)` uniqueness, status defaults, JSON round-trip, and published timestamp.
- [ ] Add the model exactly as specified in Data Contracts. Use `String(7)` for `year_month`, `JSON` for snapshot/payload/flags/frames, and indexed `skater_id`, `year_month`, and `status`.
- [ ] Add `run_migrations_monthly_chapters()` with `CREATE TABLE IF NOT EXISTS`, the unique index, and list indexes. Register it at the end of `_run_migrations()`.
- [ ] Add Pydantic contracts:

```python
class MonthlyChapterPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    skater_id: str
    year_month: str
    revision: int
    status: str
    fact_snapshot: dict[str, Any]
    source_hash: str
    generated_payload: dict[str, Any] | None = None
    draft_text: str | None = None
    final_text: str | None = None
    quality_flags: list[str] = Field(default_factory=list)
    representative_frames: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None = None
```

- [ ] Run `python -m pytest backend/tests/test_monthly_chapters.py -q` with `PYTHONPATH=backend`.
- [ ] Commit: `feat: persist monthly growth chapters`.

### Task 3: Deterministic Monthly Facts

**Files:**
- Create: `backend/app/services/monthly_facts.py`
- Create: `backend/tests/test_monthly_facts.py`
- Modify: `backend/app/services/growth_summary.py` only to reuse a shared verification-source helper if necessary.

**Produces:**

```python
async def build_monthly_fact_snapshot(
    session: AsyncSession,
    skater_id: str,
    year_month: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]

def monthly_source_hash(snapshot: dict[str, Any]) -> str
```

- [ ] Write failing tests for calendar boundaries, completed-only analyses, distinct sessions, unlocks within the month, quote speaker retention, deterministic order/hash, and `insufficient_comparable_evidence` when no reliable trend exists.
- [ ] Validate `year_month` with regex `^\d{4}-(0[1-9]|1[0-2])$`; compute an inclusive start and exclusive next-month boundary in UTC.
- [ ] Query only required columns. Do not load videos, processing logs, raw vision responses, or pose arrays.
- [ ] Add facts for session count, completed analysis count, milestones, report focus/issue recurrence, and quotes. A recurring observation requires the same normalized category in at least two `data_quality != poor` reports.
- [ ] Add comparable metric facts only when two or more records share action subtype, metric name/unit, and acceptable data quality. Include before/after values, sample count, and source analysis IDs.
- [ ] Select at most four representative frame references from milestone-linked or good-quality analyses. Store analysis ID, frame ID, timestamp, phase label, and evidence source; do not copy image bytes.
- [ ] Hash canonical JSON using sorted keys and compact separators after removing `generated_at`.
- [ ] Run the focused tests and commit: `feat: build monthly growth facts`.

### Task 4: Structured Narrative Generation And Review API

**Files:**
- Create: `backend/app/services/monthly_chapters.py`
- Create: `backend/app/routers/growth.py`
- Create: `backend/tests/test_growth_routes.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/schemas.py`

**Produces endpoints:**

```text
POST /api/growth/skaters/{id}/chapters/{YYYY-MM}/facts
POST /api/growth/skaters/{id}/chapters/{YYYY-MM}/generate
GET  /api/growth/skaters/{id}/chapters
GET  /api/growth/chapters/{chapter_id}
PATCH /api/growth/chapters/{chapter_id}
POST /api/growth/chapters/{chapter_id}/publish
```

- [ ] Write failing route tests for missing skater, invalid month, facts-only creation, provider failure preserving facts, valid generation, invalid fact references, parent edit, publish, immutable published rows, and regeneration creating revision `n+1`.
- [ ] Define the model response contract:

```json
{
  "title": "七月：落冰开始变得安静",
  "narrative": "本月记录了四次训练……",
  "highlights": [{"text": "华尔兹跳已点亮", "fact_ids": ["milestone:skill-id"]}],
  "quote_fact_id": "quote:analysis-id",
  "quality_note": "本月可比较指标较少，未生成趋势结论"
}
```

- [ ] Implement `validate_generated_chapter(payload, snapshot)`: require all fields, reject unknown fact IDs, reject quote text not copied verbatim from its fact, cap narrative at 1600 characters, and scan forbidden claim phrases (`受伤`, `恐惧`, `疲劳诊断`, `一定能升级`, `教练确认`) unless the exact claim exists in a supplied fact.
- [ ] Resolve the provider with `provider = get_active_provider("report", session)`, then call `request_text_completion(provider, messages=messages, temperature=0.3, max_tokens=1800, response_format={"type": "json_object"})`. Store prompt version `monthly_chapter.v1` and provider metadata.
- [ ] On generation failure, keep the `facts_ready` revision and return an actionable 502/503; never delete the snapshot.
- [ ] PATCH accepts `final_text` up to 2400 characters only for nonpublished chapters. Publish requires nonempty `final_text` or copies `draft_text` once, then sets `published_at`.
- [ ] Register the router, run focused tests, and commit: `feat: generate reviewable monthly chapters`.

### Task 5: Monthly Chapter UI

**Files:**
- Modify: `frontend/src/api/client.ts`
- Create: `frontend/src/pages/MonthlyChaptersPage.tsx`
- Create: `frontend/src/pages/MonthlyChaptersPage.test.tsx`
- Create: `frontend/src/components/MonthlyFactPreview.tsx`
- Create: `frontend/src/components/MonthlyFactPreview.test.tsx`
- Create: `frontend/src/components/MonthlyChapterEditor.tsx`
- Create: `frontend/src/components/MonthlyChapterEditor.test.tsx`
- Modify: `frontend/src/pages/GrowthHomePage.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] Add exact TS contracts matching the Pydantic models and API functions for all six endpoints.
- [ ] Write tests for month selection, facts preview before generation, coverage warnings, generation error retaining facts, editable draft, publish confirmation, published read-only state, and revision history.
- [ ] `MonthlyFactPreview` groups facts by count/metric/milestone/observation/quote and shows source/quality badges. It must never calculate new trends.
- [ ] `MonthlyChapterEditor` uses a controlled textarea, character counter, `保存修改`, and `确认发布`; publishing requires `window.confirm("发布后本修订将只读，确定发布吗？")`.
- [ ] `MonthlyChaptersPage` selects skater/month, loads existing revisions, and exposes the explicit sequence `整理本月事实 -> 生成叙事初稿 -> 编辑 -> 发布`.
- [ ] Register `/chapters`; add `查看月度章节` to the growth home without changing the four-item primary navigation.
- [ ] Run Vitest and frontend build. Commit: `feat: add monthly chapter workspace`.

### Task 6: Milestone Share Card

**Files:**
- Create: `frontend/src/utils/milestoneShareCanvas.ts`
- Create: `frontend/src/utils/milestoneShareCanvas.test.ts`
- Create: `frontend/src/components/MilestoneShareDialog.tsx`
- Create: `frontend/src/components/MilestoneShareDialog.test.tsx`
- Modify: `frontend/src/components/MilestoneTimeline.tsx`

**Produces:**

```typescript
createMilestoneShareImage(input: {
  skaterName: string;
  milestone: GrowthMilestone;
  frameUrl?: string | null;
  metric?: { label: string; value: string; definition: string } | null;
}): Promise<ShareImageResult>
```

- [ ] Write Canvas tests for title/date/source/quote text, image and text-only layouts, long Chinese wrapping, and no coach badge for system events.
- [ ] Reuse `loadShareImage`, `drawWrappedText`, `canvasToCompressedBlob`, clipboard, download, and native-share helpers from `shareCanvas.ts`; do not duplicate compression or sharing code.
- [ ] Fixed output is 1080x1350 JPEG, maximum 2.4 MB. When the frame fails or is absent, use a designed gradient panel and preserve all text.
- [ ] Use the first `source_analysis_id` to resolve a representative frame only when the caller already has a safe frame URL; do not fetch arbitrary filesystem paths in Canvas code.
- [ ] Add a share button to each milestone. Dialog shows preview, verification source, download, copy, and native share.
- [ ] Run tests/build and commit: `feat: add milestone share cards`.

---

## Verification Gate

Run:

```powershell
$env:PYTHONPATH='backend'
python -m pytest backend/tests/test_monthly_facts.py backend/tests/test_monthly_chapters.py backend/tests/test_growth_routes.py backend/tests/test_growth_summary.py -q
npm --prefix frontend test
npm --prefix frontend run build
```

Rendered QA at 390x844, 820x1180, and 1440x1000 must verify quote input, facts preview, generated/edited text separation, publish lock, long Chinese content, low-data month warnings, revision selection, and image/text-only milestone cards. Inspect network calls to confirm one text-generation request occurs only after the explicit generate action.

## Definition Of Done

- A fact snapshot is reproducible and hash-stable for unchanged sources.
- Every generated highlight references existing fact IDs.
- Parent edits and AI draft remain separately auditable.
- Published revisions cannot be mutated or silently regenerated.
- Quotes retain speaker and exact text.
- Milestone cards preserve verification source and work without an image.
- No schedule, annual PDF, full-video event scan, landing rate, medical inference, or level prediction is included in P1.
