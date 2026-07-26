# 花滑分析器 AI 提示词与调用链评审

**评审日期：2026-07-26**
**评审范围：当前分支 `backend/` 的线上模型调用、解析与降级链路，以及 `ai_skating_analysis_pack/` 的生成治理**

## 1. 执行摘要

本次评审不再按“有多少段 prompt 字符串”计数，而按一次用户操作实际可能触发的模型调用面审视。结论如下：

- 线上 prompt 的唯一运行来源是 `backend/`；`ai_skating_analysis_pack/` 是由后端源码生成的审查/交付快照，不接受独立功能修改。
- 训练计划主调用现在只使用一个中文儿童安全 system policy；同名英文覆盖问题已消除。
- 通用帧视觉与原生视频视觉由 `build_specialized_vision_prompt()` 和 `build_specialized_vision_schema()` 生成同一份字段契约；载体字段按模式分别为 `frame_analysis` 和 `phase_segments`，五个 subscore 字段一致。
- 双路视觉的 Path A 已成为可验证的纯视觉证据边界：不接收序列化的 `bio_data`、骨架测量或 biomechanics 文本；Path B 继续使用标注帧和数值 grounding。
- Path A 的原生视频、视频失败后的帧 fallback、以及单次 JSON repair 都使用与当前输出模式一致的契约。
- delivery snapshot 已按用户批准完整同步 26 个 service 文件，并由字节级 parity 测试约束。

这些结论来自静态调用链和离线结构测试。**本轮没有运行真实模型质量评测，因此不能据此声称准确率、稳定性或生成质量已经提升。**

## 2. 唯一来源与范围

### 2.1 运行与快照边界

- **运行源码**：`backend/app/services/` 与少量路由级调用（例如 `backend/app/routers/analysis.py`）。所有线上 provider 请求最终经 `backend/app/services/providers.py` 的 provider adapter 发出。
- **生成快照**：`ai_skating_analysis_pack/src/app/services/`。`ai_skating_analysis_pack/README.md:4` 明确声明其来自 `backend/`，不是线上源码；`ai_skating_analysis_pack/_rebuild.py:13` 以 backend services 为复制源。
- **同步约束**：`backend/tests/test_ai_pack_generation.py:33` 遍历生成清单，对全部 26 个 service 文件做逐字节一致性检查。功能改动必须先进入 `backend/`，再运行 rebuild。
- **参考文本**：`ai_skating_analysis_pack/configs/*_prompt.txt` 仅用于阅读，不是 provider 运行配置。

### 2.2 本轮重点

本轮直接治理训练计划、通用视觉契约、双路视觉证据隔离和生成快照。报告、对话、成长章节、记忆建议及对比文案等调用面未改动运行逻辑，但纳入调用面盘点和剩余风险分析。

## 3. 线上模型调用面

下表中的“证据边界”指允许进入该次模型上下文的数据，不代表下游一定采用模型输出。

| Slot | 入口点 | Prompt builder / policy | 证据边界 | 输出契约 | 解析与 fallback |
|---|---|---|---|---|---|
| `vision`：完整视频时序 | `analyze_video_temporal()`，`backend/app/services/video_temporal.py:1916` | `build_video_temporal_prompts()`，`backend/app/services/video_temporal.py:1476` | 原视频、动作大类/可选细项、用户备注、时长/FPS；不注入骨架测量值 | 时序 JSON：动作确认、`phase_segments`、T/A/L、宏观评价、质量与 fallback 建议 | provider/超时/解析失败均返回诊断 payload，让骨架/采样帧链继续；见 `video_temporal.py:1935`、`video_temporal.py:2005` |
| `vision_path_a`：原生视频或原始帧 | `analyze_frames_dual()` → `analyze_path_a()`，`backend/app/services/vision_dual.py:310`、`backend/app/services/vision_path_a.py:222` | `build_specialized_vision_prompt(..., include_biomechanics=False)`，经 `vision_path_a.py:254` 调用 | 原视频或原始帧、动作/profile 线索、非骨架 motion features、去骨架 provenance 的时序上下文；Path A context 由 `render_prompt_context(..., include_bio=False)` 构建，见 `vision_dual.py:299` | 原生视频使用 `phase_segments`；帧模式使用 `frame_analysis`；两者共享 `pure_vision_subscores` 五字段 | 原生视频失败时重建帧契约并调用图像 completion，见 `vision_path_a.py:311`；JSON 先多策略本地提取，失败后最多一次、且按输出模式 repair，见 `vision_path_a.py:162`、`vision_path_a.py:199` |
| `vision_path_b`：骨架标注帧 | `analyze_frames_dual()` → `analyze_path_b()`，`backend/app/services/vision_dual.py:328`、`backend/app/services/vision_path_b.py:193` | `PATH_B_SYSTEM` + `_build_user_prompt()` | 骨架标注帧、逐帧 bio context、jump metrics、动作/profile 线索、含 bio 的统一 context；见 `vision_dual.py:304`、`vision_path_b.py:240` | JSON object：`frame_analysis`、`subscores`、阶段摘要、问题等 | 本地直接/围栏/平衡对象提取；任何调用或解析错误返回带 `error` 的软失败 payload，见 `vision_path_b.py:212`、`vision_path_b.py:265` |
| `vision`：通用帧/视频分析 | `analyze_frames()`，`backend/app/services/vision.py:659` | `_build_specialized_prompts()` → shared builder | 帧或视频、动作/profile、候选关键帧、motion features、可选 biomechanics、记忆上下文 | 与 Path A 共用 Python schema：帧为 `frame_analysis`，视频为 `phase_segments`，五 subscores 同源 | 原生视频失败后重建帧 prompt；帧 JSON 可激进提取，仍失败则转 raw-text fallback；全部 vote 失败返回规范化 unavailable payload，见 `vision.py:604`、`vision.py:877` |
| `report`：训练报告 | `generate_report()`，`backend/app/services/report.py:1293` | `REPORT_SYSTEM_PROMPT` + 函数内结构化 user prompt | 视觉摘要、bio 数据、双路校验、时序上下文、统一分析 context/记忆 | JSON report：summary、issues、improvements、training focus、五项 0-100 subscores、质量与动作确认 | 最多 3 次完整报告请求（`REPORT_JSON_MAX_ATTEMPTS`），provider/解析失败转结构化 biomechanics/视觉 fallback，见 `report.py:43`、`report.py:1403`、`report.py:1461` |
| `report`：初始训练计划 | API `create_training_plan()` → `generate_training_plan()`，`backend/app/routers/analysis.py:9214`、`backend/app/services/plan.py:701` | 唯一 `PLAN_SYSTEM_PROMPT` + compact JSON input | 儿童资料摘要、动作类型、报告问题、记忆、variation key；政策要求 3-6 岁、低冲击、每天两项、Day 7 仅冰上和禁用器械 | 一个含 `title`、`focus_skill`、7 天 sessions 的 JSON object | 首次 parse 失败后最多一次 JSON repair；AI 失败由路由生成 deterministic fallback plan，见 `plan.py:37`、`analysis.py:9246` |
| `report`：训练计划续写 | API `extend_plan()` → `extend_training_plan()`，`backend/app/routers/analysis.py:10087`、`backend/app/services/plan.py:549` | `EXTEND_PLAN_SYSTEM_PROMPT` + 已完成/剩余天数 prompt | 原计划、完成进度、报告问题、儿童 context、记忆 | 仅待更新天数的 JSON array，随后与原计划合并并 normalize | parse 失败后最多一次 array-mode JSON repair；AI 失败由路由保留完成天并生成 fallback 剩余计划，见 `plan.py:590`、`analysis.py:10116` |
| `report`：分析追问 | `create_analysis_chat_reply()`，`backend/app/services/analysis_chat.py:468` | 四段组合 policy：证据约束、校正建议、模型身份、多问题回答 | 已保存报告/视觉/时序/校正/记忆、有限历史消息、用户问题 | 自然语言，可附约定格式的 correction suggestion | 特定重跑和模型身份问题走本地确定性回复；空回复使用中文 fallback；provider 异常由上层 API 处理，见 `analysis_chat.py:507`、`analysis_chat.py:522` |
| `report`：雪球对话 | `chat_with_snowball()`，`backend/app/services/snowball.py:237` | `SNOWBALL_SYSTEM_PROMPT` + 记忆 context | 当前用户消息、对话历史、已审核长期记忆 | 简短中文自然语言 | 空回复使用固定中文文案；当前函数没有 provider 异常降级，只保证自建 session 关闭，见 `snowball.py:260` |
| `report`：记忆更新建议 | `suggest_memory_updates()`，`backend/app/services/memory_suggest.py:96` | `MEMORY_SUGGEST_SYSTEM_PROMPT` | 已有长期记忆、本次报告摘要/问题/训练重点 | 最多 3 条 add/update/expire JSON array | JSON 非法或非数组时返回空建议；provider 异常由调用方处理，见 `memory_suggest.py:142` |
| `report`：月度成长章节 | `generate_chapter_text()`，`backend/app/services/monthly_chapters.py:196` | `_chapter_system_prompt(snapshot)` | 先固化的事实快照及 fact IDs | JSON object：标题、叙事、亮点、引用与质量说明 | 非法 JSON 或事实引用校验失败抛 `GeneratedChapterError`，保留 `facts_ready` 快照，见 `monthly_chapters.py:200`、`monthly_chapters.py:227` |
| `report`：分析对比文案 | `_build_ai_compare_narrative()`，`backend/app/routers/analysis.py:8062` | `COMPARE_NARRATIVE_SYSTEM_PROMPT` | 两次分析的结构化比较摘要 | 家长可读中文短文 | provider/空回复回落到本地比较文案，见 `analysis.py:8074`、`analysis.py:8116` |
| `report`：完整视频 AI 对比报告 | `_build_video_ai_compare_report()`，`backend/app/routers/analysis.py:8731` | `VIDEO_AI_COMPARE_REPORT_SYSTEM_PROMPT` | 两侧完整视频时序结果及确定性 fallback 比较 | JSON compare report，normalize 后保留确定性状态和 caveats | 无可用两侧数据则不调用；调用/解析失败返回本地 fallback compare report，见 `analysis.py:8734`、`analysis.py:8763` |
| 任意 provider：连通性诊断 | `test_provider_connectivity()`，`backend/app/services/providers.py:1100` | 固定 `Reply with ok.`；视觉 slot 附 1×1 测试图 | 仅 provider 配置和测试内容，不含用户分析数据 | 非空文本即成功详情 | 捕获异常并返回 `(False, 中文错误)`；这不是分析质量调用，见 `providers.py:1117`、`providers.py:1151` |
| `vision` + `report`：设置页健康检查 | `GET /api/settings/test-api` → `test_api_connection()`，`backend/app/routers/settings.py:30` | 固定“请回复 ok。”；vision 请求附 1×1 测试图 | 当前激活 provider 配置和测试内容，不含用户分析数据 | 两个 slot 均成功后返回连接状态 | 任一阶段异常均分类为认证/额度/超时等中文诊断；不进入分析 fallback |

补充说明：`plan.py` 中 `_legacy_generate_training_plan_full_prompt()` 目前没有线上调用者，不应与 `generate_training_plan()` 的有效入口混为一谈。

## 4. 本轮已修复问题

### 4.1 训练计划 system policy 覆盖

- 删除了同名英文覆盖定义；`generate_training_plan()` 在 `plan.py:739` 直接发送唯一中文 policy，repair 在 `plan.py:752` 复用同一 policy。
- policy 明确覆盖 3-6 岁个性化、低冲击、每天两项、Day 7 仅冰上、禁止 Bosu/负重/旋转椅/痛苦拉伸、避免固定模板，以及每项 `related_issue`/`parent_tip`。
- AST 和 provider request 级测试防止重复定义或发送错误 policy：`backend/tests/test_plan_generation.py`、`backend/tests/test_prompt_policy.py`。

### 4.2 帧与视频 vision schema 漂移

- `build_specialized_vision_schema(output_mode)` 成为字段契约；`build_specialized_vision_prompt()` 序列化它，见 `backend/app/services/vision_prompt_templates.py:76`、`:108`。
- `frame_analysis` 与 `phase_segments` 只承担不同载体职责；`takeoff_power`、`rotation_axis`、`arm_coordination`、`landing_absorption`、`core_stability` 从 `_subscore_contract()` 同源生成。
- 原先分散在通用视频和 Path A 的手写 schema/example 已移除；通用原生视频失败后也会重建帧模式 prompt。

### 4.3 Path A 纯视觉边界及模式一致性

- 旧的 Path A 专用 system/user prompt helpers 已删除；Path A 复用 shared builder 的纯视觉模式，因此获得同一儿童校准和不确定性规则。
- `vision_dual.py:299` 将 Path A context 与 Path B context 分开渲染，避免统一 context 把 `bio_data` 重新带回 Path A system context。
- shared builder 在纯视觉模式下不序列化 candidate keyframes 或 biomechanics；视频 context 对 Path A 隐藏 skeleton provenance。
- 原生视频 context 使用 segment 指令；视频失败后的图像 completion 重建 frame 指令；repair 根据调用模式要求正确 carrier 字段。

### 4.4 交付快照漂移

- 修正 `_rebuild.py` 和 `_build_pack.py` 的仓库根路径，并将 shared prompt template 加入清单。
- 经用户明确批准，已同步生成器列出的完整 26 个 service 文件，而非只同步四个 prompt 文件。
- 连续两次 rebuild 均报告 `Copied 26 files, 0 missing.`，且 diff hash 相同；最终 parity 测试覆盖完整清单。

## 5. 当前剩余风险

1. **缺少真实模型质量基线。** 当前测试验证 prompt 结构、字段、隔离、fallback 和 snapshot parity，不衡量动作识别准确率、T/A/L 时间误差、subscore 校准、中文建议可执行性或 provider 间差异。
2. **调用面的 schema 治理仍不完全统一。** Shared vision 已集中，但报告、Path B、时序、月度章节、记忆建议和对比报告仍各自维护手写 JSON 提示与本地 normalize/validate 逻辑，存在后续漂移空间。
3. **记忆注入需要持续审计。** 记忆会进入视觉、报告、计划和对话。Path A 已排除 bio，但仍需用 PromptOps 样本验证记忆是否造成事实污染、token 膨胀或旧结论强化。
4. **软失败可观测性不一致。** 某些入口返回诊断 payload，某些返回空数组/固定文案，某些抛业务异常；调用方虽然有各自处理，但跨调用面的失败率和原因尚无统一 dashboard。
5. **旧训练计划 helper 尚留在源码。** `_legacy_generate_training_plan_full_prompt()` 当前无调用者，增加维护者误判有效 policy 的概率；删除前应确认无外部动态引用。
6. **单次 repair 的真实收益未知。** 训练计划与 Path A 各保留最多一次 repair completion。没有失败率和成本证据前，不增加第二次 repair；应先记录首解析、repair 成功和最终 fallback 比例。

## 6. 解析、修复与降级可靠性

| 调用面 | 本地解析 | 额外模型修复/重试 | 最终降级 |
|---|---|---|---|
| Shared vision frame | 清理 JSON → 直接 parse → 激进对象提取 | 无 JSON repair；vote 数量由现有配置决定 | raw text 结构化 fallback；全部调用失败返回 unavailable payload |
| Shared vision native video | 清理/提取后 normalize | provider 调用失败转帧模式，不复用视频 prompt | 帧分析；若仍失败返回 unavailable payload |
| Path A | 直接、code fence、平衡括号对象提取 | **最多一次** repair；repair 的 carrier 随 `frames`/`video` 变化 | 原生视频异常转帧；最终 parse 失败由 dual path 记录 Path A error 并继续 Path B/report fallback |
| Path B | 直接、code fence、平衡对象提取 | 无模型 repair | 返回 `error` payload，双路融合继续 |
| Video temporal | 多策略对象/部分对象提取并 normalize/validate | 下游 quality gate 可带结构化 retry context 重新分析，但不是 JSON repair 循环 | 建议 existing skeleton timestamps / sampled frames / manual review |
| Report | `clean_json_text()` + `json.loads()` + normalize | 最多 3 次完整报告请求 | 视觉/生物力学结构化 fallback report |
| Initial/extended plan | 清理 + JSON object/array parse + normalize | **最多一次** JSON repair | 路由生成 deterministic fallback plan/extension |
| Memory suggestion | 清理 + array parse + normalize | 无 | 空建议，不写入 suggestion |
| Monthly chapter | 严格 JSON parse + fact 引用验证 | 无 | 抛业务错误并保留事实快照 |
| Compare outputs | 清理/JSON parse + normalize，或直接文本清理 | 无 | 本地 deterministic compare narrative/report |

可靠性原则是“结构恢复优先、有限调用、可诊断降级”。当前没有证据支持为 Path A 或训练计划增加第二次 repair completion。

## 7. 测试与验证结果

最终验证命令（从 `backend/` 执行）：

```powershell
python -m pytest tests/test_plan_generation.py tests/test_prompt_policy.py tests/test_vision_prompt_templates.py tests/test_vision_specialized_prompt.py tests/test_vision_path_a_prompt.py tests/test_vision_path_a.py tests/test_vision_video_context.py tests/test_vision_dual.py tests/test_vision_fallback.py tests/test_video_temporal_prompt.py tests/test_ai_pack_generation.py -q
```

结果：`60 passed, 3 warnings in 22.08s`。三个 warning 均来自第三方依赖：Starlette 对 `python_multipart` 的 `PendingDeprecationWarning`，以及 protobuf 的 `MessageMapContainer` / `ScalarMapContainer` Python 3.14 兼容性 `DeprecationWarning`。该 suite 覆盖：

- 训练计划唯一 policy、儿童安全条款、请求边界与单次 repair；
- 帧/视频 shared schema 和五项 subscore 同源；
- Path A 的 bio 隔离、双路 system-context 隔离、视频 context 模式、帧 fallback prompt 和 output-mode-aware repair；
- 通用 vision fallback 和 video temporal prompt；
- 全 26 文件生成清单及 backend/snapshot 字节级一致性。

静态扫描用于防止旧 active-state 叙述回归；历史结论在本评审中统一改写为“旧专用 prompt 已删除”或“同名英文覆盖已消除”。仓库 hygiene 门禁另执行 `git diff --check` 和 `git status --short`。

## 8. 下一阶段 PromptOps

1. **建立版本化 eval 集。** 按 jump/spin/step/spiral、儿童年龄、视角、遮挡、多人、画质分层，保存人工动作标签、T/A/L 容差、可见问题和不可判断项。
2. **记录调用级指标。** 至少记录 prompt/schema version、provider/model、mode、首解析成功、repair 使用/成功、fallback 原因、token、延迟和成本；Path A/Path B 分开观察。
3. **做 contract diff 门禁。** 将 report、Path B、video temporal、plan 的 schema hint 逐步转为 Python/类型模型生成，并在 CI 比较 prompt schema 与 normalize/validate 接口。
4. **评估而非假设 repair 策略。** 先用生产匿名统计和离线 malformed corpus 计算一次 repair 的成功率、成本和尾延迟，再决定是否调整；默认维持一次上限。
5. **增加 prompt injection 与证据污染样本。** 专门覆盖 user note、历史记忆、provider raw text 中的指令注入，以及 Path A 中 `bio_data`/skeleton sentinel 不可见性。
6. **设置质量发布门槛。** 结构测试之外，要求关键动作族的识别率、T/A/L 时间误差、不可判断 precision、儿童 subscore 校准和中文建议人工评分不退化，才宣称模型质量改善。
