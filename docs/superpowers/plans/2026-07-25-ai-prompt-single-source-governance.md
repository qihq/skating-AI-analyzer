# AI Prompt Single-Source Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `backend/` the only runtime prompt source, fix the training-plan prompt override, unify vision output contracts, isolate Path A from biomechanics, and make the review and generated snapshot accurate.

**Architecture:** Prompt builders own the final system/user request content and generate their JSON examples from one Python contract. Runtime services call those builders exactly once; Path A selects a pure-vision evidence mode while generic vision may use grounded evidence. The delivery pack is regenerated from backend and verified as an artifact rather than maintained as a second source tree.

**Tech Stack:** Python 3, `unittest`/pytest-compatible tests, `unittest.mock`, `json`, `pathlib`, Git.

## Global Constraints

- `backend/` is the only runtime source for prompts.
- `ai_skating_analysis_pack/` is a generated review/delivery snapshot and must not be edited as independent runtime logic.
- Keep one JSON repair completion; do not add retries without failure-rate evidence.
- Path A must not receive `bio_data`, skeleton measurements, or biomechanics text.
- Frame and video vision prompts must derive shared fields and five subscores from one Python contract.
- Preserve existing provider APIs, normalized payload shape, fallbacks, and user-facing Chinese output.
- Do not modify unrelated untracked `output/` content.

---

### Task 1: Fix the Effective Training-Plan System Prompt

**Files:**
- Modify: `backend/tests/test_plan_generation.py`
- Modify: `backend/app/services/plan.py:100`

**Interfaces:**
- Consumes: `generate_training_plan(action_type, report, skater_context, skater_id, variation_key=None)`.
- Produces: one module-level `PLAN_SYSTEM_PROMPT: str` used in the provider request and JSON repair request.

- [ ] **Step 1: Write a failing request-level test**

Add `PLAN_SYSTEM_PROMPT` to the imports and replace the English assertion in `test_generate_training_plan_prompt_includes_child_context_and_variation_seed` with assertions for the effective Chinese policy:

```python
self.assertEqual(messages[0]["content"], PLAN_SYSTEM_PROMPT)
self.assertIn("3-6岁", messages[0]["content"])
self.assertIn("不要套用固定模板", messages[0]["content"])
self.assertIn("Day 7", messages[0]["content"])
self.assertIn("related_issue", messages[0]["content"])
self.assertIn("parent_tip", messages[0]["content"])
```

Add an AST regression test that counts one top-level assignment:

```python
def test_plan_system_prompt_has_one_definition(self) -> None:
    tree = ast.parse(Path(plan_module.__file__).read_text(encoding="utf-8"))
    definitions = [
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "PLAN_SYSTEM_PROMPT" for target in node.targets)
    ]
    self.assertEqual(len(definitions), 1)
```

- [ ] **Step 2: Run the focused test and verify failure**

Run: `cd backend; python -m pytest tests/test_plan_generation.py -q`

Expected: FAIL because the effective prompt is English and `PLAN_SYSTEM_PROMPT` has two assignments.

- [ ] **Step 3: Merge the effective policy into one constant**

Delete the second English assignment. Expand the Chinese constant so it explicitly includes the constraints currently present only in English:

```python
PLAN_SYSTEM_PROMPT = (
    "你是儿童花样滑冰启蒙教练，擅长给3-6岁小朋友设计安全、有趣、家长可陪练的训练。"
    "请根据分析报告、动作类型、孩子档案和历史记忆生成7天个性化训练计划，只输出合法 JSON。"
    "所有项目必须低冲击、短时长、游戏化；每天2项，Day 7 只能安排冰上练习。"
    "不要安排成人体能、负重、Bosu、旋转椅、长时间平板支撑或痛苦拉伸。"
    "不要套用固定模板；每天都要回应本次报告里的具体问题。"
    "每个项目必须包含 related_issue 和 parent_tip。"
)
```

- [ ] **Step 4: Run the focused test and verify pass**

Run: `cd backend; python -m pytest tests/test_plan_generation.py -q`

Expected: all tests in `test_plan_generation.py` PASS.

- [ ] **Step 5: Commit the isolated fix**

```powershell
git add -- backend/app/services/plan.py backend/tests/test_plan_generation.py
git commit -m "fix: use one child-safe training plan prompt"
```

---

### Task 2: Generate Frame and Video Vision Contracts from One Source

**Files:**
- Modify: `backend/tests/test_vision_prompt_templates.py`
- Modify: `backend/tests/test_vision_specialized_prompt.py`
- Modify: `backend/app/services/vision_prompt_templates.py`
- Modify: `backend/app/services/vision.py:30`

**Interfaces:**
- Produces: `build_specialized_vision_prompt(..., output_mode: Literal["frames", "video"] = "frames", include_biomechanics: bool = True) -> tuple[str, str]`.
- Produces: `build_specialized_vision_schema(output_mode: Literal["frames", "video"]) -> dict[str, Any]`.
- Consumes: existing action/profile/keyframe/motion/biomechanics arguments.

- [ ] **Step 1: Write failing contract tests**

Add tests that parse the schema text following `JSON schema:\n` and assert shared fields:

```python
def _schema_from_prompt(prompt: str) -> dict[str, object]:
    return json.loads(prompt.split("JSON schema:\n", 1)[1])

def test_frame_and_video_contracts_share_subscores(self) -> None:
    _, frame_prompt = build_specialized_vision_prompt(action_type="jump", output_mode="frames")
    _, video_prompt = build_specialized_vision_prompt(action_type="jump", output_mode="video")
    frame_schema = _schema_from_prompt(frame_prompt)
    video_schema = _schema_from_prompt(video_prompt)
    self.assertIn("frame_analysis", frame_schema)
    self.assertNotIn("phase_segments", frame_schema)
    self.assertIn("phase_segments", video_schema)
    self.assertNotIn("frame_analysis", video_schema)
    self.assertEqual(frame_schema["pure_vision_subscores"], video_schema["pure_vision_subscores"])
    self.assertEqual(set(frame_schema["pure_vision_subscores"]), {
        "takeoff_power", "rotation_axis", "arm_coordination", "landing_absorption", "core_stability"
    })
```

Update the request-level video test to assert there is exactly one schema and that it includes `element_confidence` and five subscores:

```python
self.assertEqual(kwargs["user_prompt"].count("JSON schema:"), 1)
self.assertIn('"phase_segments"', kwargs["user_prompt"])
self.assertIn('"core_stability"', kwargs["user_prompt"])
self.assertIn('"element_confidence"', kwargs["user_prompt"])
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `cd backend; python -m pytest tests/test_vision_prompt_templates.py tests/test_vision_specialized_prompt.py -q`

Expected: FAIL because video mode appends a second hand-written schema and the shared frame schema lacks `pure_vision_subscores`.

- [ ] **Step 3: Implement the shared schema builder**

In `vision_prompt_templates.py`, replace the schema string with small JSON-compatible builders. Use one shared subscore object and select only the carrier by `output_mode`:

```python
VisionOutputMode = Literal["frames", "video"]

def _subscore_contract() -> dict[str, float]:
    return {
        "takeoff_power": 0.0,
        "rotation_axis": 0.0,
        "arm_coordination": 0.0,
        "landing_absorption": 0.0,
        "core_stability": 0.0,
    }

def build_specialized_vision_schema(output_mode: VisionOutputMode) -> dict[str, Any]:
    payload = {
        "data_quality_hint": "good|partial|poor",
        "camera_view": "front|side|diagonal_front|diagonal_back|unknown",
        "camera_view_confidence": 0.0,
        "action_phase_summary": {
            "detected_phases": [],
            "weakest_phase": "",
            "strongest_phase": "",
            "key_frame_agreement": {"T": "agree|shifted|disagree|unavailable", "A": "agree|shifted|disagree|unavailable", "L": "agree|shifted|disagree|unavailable"},
        },
        "pure_vision_subscores": _subscore_contract(),
        "element_confidence": 0.0,
        "overall_raw_text": "2-3句中文总结",
    }
    payload["frame_analysis" if output_mode == "frames" else "phase_segments"] = [
        _frame_contract() if output_mode == "frames" else _segment_contract()
    ]
    return payload
```

Serialize it only at the end with `json.dumps(..., ensure_ascii=False, indent=2)`. Add explicit video rules before the one schema when `output_mode == "video"`.

- [ ] **Step 4: Remove overwritten prompt construction in generic vision**

Delete `VISION_SYSTEM_PROMPT`, `PROFILE_HINTS`, the large legacy `user_prompt` construction, and `_build_specialized_video_prompt()`. Make `_build_specialized_prompts` accept and forward `output_mode`, then call it once:

```python
system_prompt, user_prompt = _build_specialized_prompts(
    action_type,
    action_subtype,
    analysis_profile,
    profile_evidence,
    bio_data,
    motion_features,
    output_mode="video" if mode == "video" and clip_path is not None else "frames",
)
```

Pass `user_prompt` directly to native video providers.

- [ ] **Step 5: Run vision contract tests**

Run: `cd backend; python -m pytest tests/test_vision_prompt_templates.py tests/test_vision_specialized_prompt.py tests/test_vision_fallback.py -q`

Expected: all selected tests PASS and each provider request contains one output schema.

- [ ] **Step 6: Commit the contract refactor**

```powershell
git add -- backend/app/services/vision_prompt_templates.py backend/app/services/vision.py backend/tests/test_vision_prompt_templates.py backend/tests/test_vision_specialized_prompt.py
git commit -m "refactor: unify vision prompt output contracts"
```

---

### Task 3: Enforce Path A Evidence Isolation

**Files:**
- Modify: `backend/tests/test_vision_path_a_prompt.py`
- Modify: `backend/tests/test_vision_path_a.py`
- Modify: `backend/app/services/vision_path_a.py:32`

**Interfaces:**
- Consumes: Task 2 `build_specialized_vision_prompt(..., output_mode, include_biomechanics)`.
- Produces: Path A requests containing motion/action context but no `bio_data`, biomechanics section, or skeleton-derived keyframe payload.

- [ ] **Step 1: Replace the existing grounding test with an isolation test**

Pass sentinel data in `bio_data` and assert it never reaches the final request while motion evidence remains:

```python
bio_data = {
    "key_frame_candidates": {"T": {"frame_id": "SKELETON_SENTINEL"}},
    "jump_metrics": {"estimated_rotation_turns": 9.99},
}
# after analyze_path_a(...)
self.assertIn('"motion_score": 0.95', prompt_text)
self.assertNotIn("SKELETON_SENTINEL", prompt_text)
self.assertNotIn("estimated_rotation_turns", prompt_text)
self.assertNotIn("biomechanics:", prompt_text)
self.assertIn("不引入骨架或测量数据", system_prompt)
```

Also update video-mode tests to assert `output_mode="video"` yields one `phase_segments` schema.

- [ ] **Step 2: Run Path A tests and verify failure**

Run: `cd backend; python -m pytest tests/test_vision_path_a_prompt.py tests/test_vision_path_a.py tests/test_vision_video_context.py -q`

Expected: FAIL because Path A currently serializes `bio_data` and skeleton-derived candidates.

- [ ] **Step 3: Remove dead Path A prompts and select pure-vision mode**

Delete `PATH_A_SYSTEM`, `_build_user_prompt()`, `_build_video_user_prompt()`, `_candidate_key_frames_from_bio()`, and `_build_specialized_video_user_prompt()`. Build Path A prompts once:

```python
system_prompt, user_text = build_specialized_vision_prompt(
    action_type=action_type,
    action_subtype=action_subtype,
    analysis_profile=analysis_profile,
    candidate_key_frames=None,
    motion_features=motion_features,
    biomechanics=None,
    profile_evidence=profile_evidence,
    skill_category=skill_category,
    output_mode="video" if mode == "video" and clip_path is not None else "frames",
    include_biomechanics=False,
)
```

The builder must label this mode as pure visual and must not render an empty `biomechanics` heading.

- [ ] **Step 4: Run Path A and dual-path tests**

Run: `cd backend; python -m pytest tests/test_vision_path_a_prompt.py tests/test_vision_path_a.py tests/test_vision_video_context.py tests/test_vision_dual.py -q`

Expected: all selected tests PASS; Path B behavior remains unchanged.

- [ ] **Step 5: Commit the evidence-boundary fix**

```powershell
git add -- backend/app/services/vision_path_a.py backend/tests/test_vision_path_a_prompt.py backend/tests/test_vision_path_a.py
git commit -m "fix: isolate Path A from biomechanics evidence"
```

---

### Task 4: Make the Delivery Snapshot Reproducible

**Files:**
- Create: `backend/tests/test_ai_pack_generation.py`
- Modify: `ai_skating_analysis_pack/_rebuild.py:13`
- Modify: `ai_skating_analysis_pack/_build_pack.py:14`
- Modify: `ai_skating_analysis_pack/README.md:1`
- Regenerate: `ai_skating_analysis_pack/src/app/services/plan.py`
- Regenerate: `ai_skating_analysis_pack/src/app/services/vision.py`
- Regenerate: `ai_skating_analysis_pack/src/app/services/vision_path_a.py`
- Regenerate: `ai_skating_analysis_pack/src/app/services/vision_prompt_templates.py`

**Interfaces:**
- Produces: both scripts expose a correct `REPO_ROOT == Path(__file__).resolve().parents[1]`.
- Produces: `AI_SERVICE_FILES`/`FILES` including `vision_prompt_templates.py`.
- Produces: generated key service files byte-identical to backend sources after `_rebuild.py`.

- [ ] **Step 1: Write failing generation tests**

Import `_rebuild.py` with `importlib.util` and assert paths/list entries:

```python
self.assertEqual(module.REPO_ROOT, REPO_ROOT)
self.assertEqual(module.SRC, REPO_ROOT / "backend" / "app" / "services")
self.assertIn("vision_prompt_templates.py", module.FILES)
```

Add a post-generation parity assertion for the prompt-bearing files:

```python
for name in ("plan.py", "vision.py", "vision_path_a.py", "vision_prompt_templates.py"):
    self.assertEqual(
        (REPO_ROOT / "backend/app/services" / name).read_bytes(),
        (REPO_ROOT / "ai_skating_analysis_pack/src/app/services" / name).read_bytes(),
    )
```

- [ ] **Step 2: Run the generation test and verify failure**

Run: `cd backend; python -m pytest tests/test_ai_pack_generation.py -q`

Expected: FAIL because both scripts resolve `Documents` instead of the repository and omit `vision_prompt_templates.py`.

- [ ] **Step 3: Fix both builders and label the artifact**

Set `REPO_ROOT = Path(__file__).resolve().parents[1]`, remove unused `os` imports, add `vision_prompt_templates.py` to both copy lists, and add this README notice immediately below the title:

```markdown
> [!IMPORTANT]
> 本目录是从仓库根目录 `backend/` 生成的审查/交付快照，不是线上运行源码。
> 请勿直接修改 `src/app/services/` 或将 `configs/*_prompt.txt` 当作运行配置；功能修改应落在 `backend/`，然后运行 `python ai_skating_analysis_pack/_rebuild.py` 同步。
```

Update the configs description to “提示词参考文本（非运行配置）”.

- [ ] **Step 4: Regenerate the tracked snapshot**

Run: `python ai_skating_analysis_pack/_rebuild.py`

Expected: output reports copied files with `0 missing`, including `vision_prompt_templates.py`.

- [ ] **Step 5: Run generation and focused prompt tests**

Run: `cd backend; python -m pytest tests/test_ai_pack_generation.py tests/test_plan_generation.py tests/test_vision_prompt_templates.py tests/test_vision_path_a_prompt.py -q`

Expected: all selected tests PASS.

- [ ] **Step 6: Commit the snapshot governance changes**

```powershell
git add -- ai_skating_analysis_pack/_rebuild.py ai_skating_analysis_pack/_build_pack.py ai_skating_analysis_pack/README.md ai_skating_analysis_pack/src/app/services backend/tests/test_ai_pack_generation.py
git commit -m "build: regenerate AI review pack from backend"
```

---

### Task 5: Rewrite the Review and Run Final Verification

**Files:**
- Modify: `AI-PROMPTS-REVIEW.md`
- Verify: all files from Tasks 1-4

**Interfaces:**
- Produces: an evidence-backed review organized by runtime call surface rather than raw prompt-string count.

- [ ] **Step 1: Rewrite the review around actual calls**

Use these sections with concrete file/call references:

```markdown
# 花滑分析器 AI 提示词与调用链评审
## 1. 执行摘要
## 2. 唯一来源与范围
## 3. 线上模型调用面
## 4. 本轮已修复问题
## 5. 当前剩余风险
## 6. 解析、修复与降级可靠性
## 7. 测试与验证结果
## 8. 下一阶段 PromptOps
```

The runtime table must name slot, entry point, builder, evidence boundary, output contract, and fallback. Remove obsolete claims that `PATH_A_SYSTEM` is effective, that the pack is an independent runtime source, and that a second JSON repair is currently P3 work.

- [ ] **Step 2: Run static review checks**

Run: `rg -n "PATH_A_SYSTEM|VISION_SYSTEM_PROMPT|PLAN_SYSTEM_PROMPT.*英文|独立包.*运行" AI-PROMPTS-REVIEW.md`

Expected: no obsolete active-state claims. Historical mentions must explicitly say they were removed in this change.

- [ ] **Step 3: Run all prompt-focused tests**

Run:

```powershell
cd backend
python -m pytest tests/test_plan_generation.py tests/test_prompt_policy.py tests/test_vision_prompt_templates.py tests/test_vision_specialized_prompt.py tests/test_vision_path_a_prompt.py tests/test_vision_path_a.py tests/test_vision_video_context.py tests/test_vision_dual.py tests/test_vision_fallback.py tests/test_video_temporal_prompt.py tests/test_ai_pack_generation.py -q
```

Expected: all selected tests PASS.

- [ ] **Step 4: Run repository hygiene checks**

Run: `git diff --check`

Expected: no whitespace errors.

Run: `git status --short`

Expected: only intended review/code/test/generated snapshot changes plus the pre-existing untracked `output/`.

- [ ] **Step 5: Commit the reviewed final state**

```powershell
git add -- AI-PROMPTS-REVIEW.md
git commit -m "docs: rewrite AI prompt call-chain review"
```

