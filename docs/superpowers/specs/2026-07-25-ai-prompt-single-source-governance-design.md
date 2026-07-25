# AI 提示词单一来源治理设计

日期：2026-07-25

## 目标

本次改造解决提示词“看起来被修改，但实际请求没有使用”的问题。`backend/` 是唯一运行源码和提示词来源；`ai_skating_analysis_pack/` 是由主工程生成的审查/交付快照，不再手工维护。

本次范围包括：

- 修复训练计划 system prompt 被同名英文常量覆盖的问题。
- 收敛视觉分析实际调用的 prompt builder 和输出契约。
- 删除或替换运行路径中已经被覆盖、没有调用者的旧 prompt 常量和 builder。
- 修复快照生成脚本，使其能从当前仓库的 `backend/` 正确复制文件。
- 增加最终请求级 prompt 回归测试，而不只测试常量文本。
- 重写 `AI-PROMPTS-REVIEW.md`，反映真实调用链、风险和分阶段行动。

本次不引入完整 PromptOps 平台，不建立模型成本看板，也不凭主观判断批量改写全部提示词。Golden case、线上质量指标和 prompt 版本看板列入后续阶段。

## 单一来源和边界

### 运行源码

所有线上提示词只在 `backend/app/` 下维护。调用方应通过明确的 prompt builder 获得最终 system/user prompt，避免先构造旧 prompt、随后又被新 prompt 覆盖。

### 快照包

`ai_skating_analysis_pack/` 保留为审查/交付快照：

- README 顶部标记其为生成产物，并指向 `backend/`。
- `_rebuild.py` 和 `_build_pack.py` 使用脚本文件父目录的正确层级定位仓库根目录。
- 生成脚本复制当前实际依赖的提示词模块，包括 `vision_prompt_templates.py`。
- 一致性测试验证关键生成文件与 backend 源文件一致，防止快照悄悄过期。
- `configs/*_prompt.txt` 明确为参考文档，或由构建过程生成；不得被描述为运行配置。

旧版 `src/quality_assessment/`、`src/utils/` 等目录仅作为历史快照，不纳入当前线上 prompt 缺陷统计。

## 训练计划提示词

保留一个 `PLAN_SYSTEM_PROMPT`，使用中文规则，因为用户输入、报告证据和训练计划输出均主要为中文。合并当前中英文版本中仍有效的约束：

- 3-6 岁儿童、低冲击、短时长、游戏化和家长陪练。
- 每天两项、Day 7 仅冰上练习。
- 每项包含 `related_issue` 和 `parent_tip`。
- 主题和项目必须回应本次报告，不套用固定模板。
- 只输出合法 JSON。

调用级测试检查最终发给 provider 的 system prompt 包含个性化和儿童安全规则，并确认不存在重复定义。

JSON 修复仍限制为一次额外模型调用。本次不把第二次修复作为 prompt 优化，因为当前已有响应格式约束、解析恢复和安全 fallback；增加更多模型重试会提高延迟与成本，却没有现有失败率证据支持。

## 视觉提示词和输出契约

`build_specialized_vision_prompt()` 继续作为通用视觉和 Path A 的共享入口。删除两条调用路径中先构造后覆盖的旧 system/user prompt。

共享输出契约以 Python 数据结构为来源，再序列化为提示词中的 JSON schema/example，避免手工维护多份字符串。契约覆盖：

- 通用质量字段：`data_quality_hint`、`camera_view`、置信度。
- 帧模式：`frame_analysis` 和 `frame_id`。
- 视频模式：`phase_segments` 和片段相对时间。
- 阶段摘要与 T/A/L 一致性。
- `pure_vision_subscores` 五个维度。
- `element_confidence` 和中文短总结。

帧模式和视频模式允许载体字段不同，但共享字段、枚举和评分维度必须来自同一契约。现有 normalization 继续负责容错；测试验证最终请求包含相应模式所需字段。

Path A 虽然名为纯视觉路径，但当前共享 builder 会接收后端骨架和生物力学证据，这是语义冲突。本次将明确边界：Path A 只接收画面、动作上下文、运动/语义关键帧线索，不注入骨架测量或 `bio_data`；Path B 继续承担骨架和数值 grounding。这样双路径交叉验证才具有独立性。

## 测试和验证

测试按风险分层：

1. Prompt builder 单元测试：检查 schema、儿童校准、不确定性和纯函数行为。
2. 调用级测试：mock provider，检查实际发送的 system/user prompt，防止死常量测试产生虚假安全感。
3. 模式契约测试：帧模式包含 `frame_analysis`，视频模式包含 `phase_segments`，共享字段一致。
4. Path A 隔离测试：最终 prompt 不包含骨架测量或 `bio_data` 内容。
5. 快照一致性测试：构建文件清单覆盖 prompt 依赖，仓库根目录解析正确，关键复制文件与 backend 相同。

运行与提示词相关的定向测试后，再运行受影响服务的完整测试集合。生成脚本在验证时写入现有快照目录，因此执行前记录 git 状态，生成后只保留预期同步结果。

## Review 文档结构

新版 `AI-PROMPTS-REVIEW.md` 不再用“发现字符串数量”代表系统质量，而按实际模型调用面组织：

- 执行摘要和唯一来源说明。
- 线上调用清单：slot、入口、builder、输入证据、输出契约、fallback。
- 已验证问题：调用链证据、影响、优先级、测试缺口。
- 生成快照问题：与线上问题分开记录。
- 可靠性问题：解析、修复、fallback、超时，不混入提示词文案评分。
- 本轮修改和验证结果。
- 后续 PromptOps：golden case、质量指标、token/延迟/成本、prompt 版本和 A/B 评估。

优先级按用户影响和线上可达性判定：P0 为确定影响所有相关调用的行为错误；P1 为高概率漂移或证据边界错误；P2 为维护性和测试缺口；没有运行调用者的历史快照内容不作为线上 P1。

## 成功标准

- 训练计划最终请求只使用一份完整中文 system prompt。
- 通用视觉与 Path A 不再构造随后被覆盖的 prompt。
- Path A 最终请求不包含骨架/生物力学测量。
- 帧/视频视觉 schema 从同一契约派生，五项评分字段一致。
- 快照脚本从当前仓库正确读取 backend，并覆盖共享 prompt builder。
- 相关测试通过，review 中的每个高优先级结论都有调用链或测试证据。

