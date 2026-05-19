# 花样滑冰 AI 视频分析模块：深度复盘与迭代规划

本文档从计算机视觉、视频理解和训练产品工程视角复盘 Skating Analyzer 当前视频分析模块。它不是接口说明书；当前流水线细节见 [ai-analysis-flow.md](./ai-analysis-flow.md)。本文重点回答三个问题：

- 当前实现真正依赖哪些信号，哪些信号只是辅助。
- v5.0.0 已经解决了哪些历史问题。
- 后续迭代应该优先补哪些能力，避免继续堆 prompt 和阈值。

---

## 1. 当前实现概况

当前系统是一个 **规则 + 姿态估计 + 视频多模态 AI + 图片多模态 AI + 报告 LLM** 的混合流水线。它没有本地端到端训练模型，也没有 ISU 官方评分引擎；现阶段定位是儿童/青少年训练复盘工具，而不是比赛打分器。

核心架构：

```text
视频预检查
  -> profile 化动作窗口检测
  -> 运动加权抽帧
  -> 目标学员锁定
  -> MediaPipe 姿态与生物力学
  -> Qwen 3.6 Plus 视频语义时序
  -> 视频/骨架/运动峰值三方仲裁
  -> semantic keyframes 或 sampled frames
  -> Path A 纯视觉分析
  -> Path B 骨架叠加 + 量化 grounding
  -> cross-validation + auto-eval
  -> 报告融合 + Force Score
```

设计哲学：

- **不信任单一信号源**：视频 AI、图片 AI、骨架、运动密度互相校验。
- **视频 AI 只做语义层**：它输出阶段区间、动作确认、宏观评价，不直接作为逐帧裁判。
- **语义关键帧必须过门控**：T/A/L 顺序、阶段置信度、fallback recommendation、局部 refinement 都会影响是否采用 semantic frames。
- **Path A 与 Path B 分工明确**：Path A 看画面，Path B 看骨架标注和数值；冲突时降低确定性。
- **产品侧保守表达**：儿童训练场景下，报告要给可执行建议，不输出过度竞技化惩罚。

---

## 2. 当前数据流与模块职责

| 模块 | 输入 | 输出 | 主要职责 |
|---|---|---|---|
| `video.py` | 源视频 | 动作窗口、sampled frames、semantic frames、motion metadata | FFmpeg/OpenCV 预处理、慢动作折算、抽帧、局部运动 refinement |
| `video_temporal.py` | 动作窗口 AI clip | `video_temporal_v1`、`resolved_keyframes` | 视频语义定位、payload 校验、时间戳仲裁 |
| `target_lock.py` / `bbox_tracker.py` | sampled frames | target lock payload、跨帧 bbox | 多人场景目标选择与跟踪 |
| `pose.py` / `smoothing.py` | frames + target lock | 33 点姿态序列 | MediaPipe 姿态、多人/单人 fallback、平滑 |
| `biomechanics.py` | 姿态序列 | 几何指标、bio_subscores、keyframe candidates | 膝角、躯干、质心、跳跃和旋转估算 |
| `action_profiles.py` | 用户输入 + 运动/姿态证据 | `jump/spin/step/spiral` | profile 推断和 sampling/prompt 路由 |
| `vision_path_a.py` | 原始帧或 clip | 纯视觉帧分析、pure_vision_subscores | 从画面判断姿态、阶段、刃面和技术问题 |
| `vision_path_b.py` | 骨架叠加帧 + bio context | 量化 grounding 分析、subscores | 骨架/角度辅助的稳定性判断 |
| `cross_validator.py` | Path A + Path B | 一致率、推荐路径、冲突等级 | 发现骨架追踪或视觉判断分歧 |
| `auto_eval.py` | bio + vision + motion | 关键帧顺序和阶段质量 flags | 自动回归评估与质量诊断 |
| `report.py` | vision + bio + context | 结构化训练报告、Force Score | 报告融合、分数融合、儿童评分校准 |

---

## 3. v5.0.0 已解决的关键问题

### 3.1 关键帧不再只依赖运动抽帧

旧问题：动作速度快时，运动加权 sampled frames 可能错过最后离冰、最高点或首次落冰的瞬间。即便抽到运动峰值，也未必语义正确。

当前解法：

- Qwen 3.6 Plus 对动作窗口 clip 输出阶段区间和 T/A/L hint。
- `resolve_semantic_keyframes()` 用视频区间、骨架候选和运动峰值仲裁。
- T/L 使用 `±0.18s` 局部高 FPS 运动扫描 refine。
- 语义帧不可靠时回退 sampled frames。

剩余风险：

- 视频模型对高速动作的绝对时间戳仍可能偏移。
- 单机位、遮挡和低清晰度下，Apex 与落冰的可见性不稳定。
- 语义帧可靠性目前是规则门控，不是学习得到的置信校准。

### 3.2 抽帧策略从固定 20 帧升级为 profile 化

旧问题：跳跃、旋转、螺旋线、步法的时长和信息密度不同，固定 5fps/20 帧会让跳跃时间分辨率不足，也会浪费慢动作帧预算。

当前解法：

- `backend/app/configs/action_profiles.json` 配置每类 profile 的窗口、FPS、最大帧数。
- jump 当前默认 3.5s / 16fps / 32 帧。
- spin 当前默认 6s / 10fps / 28 帧。
- step 当前默认 8s / 6fps / 24 帧。
- spiral 当前默认 6s / 8fps / 20 帧。
- 源视频 >=60fps 时按 30fps 正常速度折算时间轴。

剩余风险：

- profile 推断错误会影响后续抽帧密度和 prompt。
- 对连续组合动作或长节目片段，单窗口策略仍偏窄。

### 3.3 双路径分析降低了单一路径误判

旧问题：只看原图时，模型容易被视角、服装和动作模糊影响；只看骨架时，MediaPipe 追踪错误会产生错误数值。

当前解法：

- Path A：纯视觉，不直接依赖骨架测量。
- Path B：骨架叠加帧 + 每帧 bio context + jump metrics。
- `cross_validate()` 比较阶段和五项评分，输出 `reliable/uncertain/likely_wrong`。
- 当 Path B 失败，主流程仍可用 Path A 生成报告。

剩余风险：

- Path A 和 Path B 的融合目前主要用于诊断和报告上下文，最终 `vision_structured` 仍以 Path A 为主。
- Path B 的骨架叠加质量受 MediaPipe 检测影响较大。
- 两路都使用通用多模态模型，仍缺乏专项学习能力。

### 3.4 报告生成加入质量降级和儿童评分校准

旧问题：模型容易在低质量视频中输出过度确定的技术结论，或按成人竞技标准给儿童动作过低评分。

当前解法：

- `data_quality` 会根据视觉质量、双路径冲突、human review 需求下调。
- 低置信帧比例高时，报告会提示“结果仅供参考”。
- 报告模型失败时转为 biomechanics fallback。
- Force Score 使用 `apply_child_score_floor()`，在无高危问题且数据质量不差时给儿童训练场景合理下限。

剩余风险：

- 儿童评分下限是产品策略，不是客观技术水平校准。
- 对“安全风险”与“严重技术错误”的文本识别依赖 issue 描述，仍有漏判可能。

---

## 4. 当前根本限制

### 限制 1：没有花滑专项训练数据闭环

系统目前没有可持续积累和标注的专项数据集。AI 能力主要来自通用云端多模态模型，规则阈值来自工程经验和少量回归测试。

影响：

- Flip/Lutz、Loop/Salchow 等相似跳跃区分不稳定。
- 动作边界置信无法用真实标签校准。
- 提升主要依赖 prompt、规则和人工测试，难以量化泛化能力。

### 限制 2：姿态估计不是运动专项模型

MediaPipe 适合通用人体姿态，但花滑存在高速旋转、冰面反光、长距离拍摄、服装遮挡、多人背景等困难场景。

影响：

- 旋转周数估算偏差大。
- 膝角和躯干角在低分辨率/遮挡下不稳定。
- 目标跟踪错误会污染 Path B 和生物力学。

### 限制 3：动作边界仍是规则仲裁

v5.0.0 引入视频语义定位后，边界质量明显改善，但最终仍由规则把视频 AI、骨架候选和运动峰值合并。

影响：

- 对连续步法、组合旋转、跳接跳等复杂片段支持有限。
- 单一动作窗口假设限制了长视频里的多元素分析。
- 规则门控难以表达模型置信度的真实分布。

### 限制 4：ISU 规则还未结构化落地

当前 Force Score 是训练导向评分，不是 TES/PCS 或 GOE/Level。

影响：

- 无法给出官方语义的 GOE、Level、q、<、e、! 等标记。
- 报告可解释，但不能作为比赛复盘的严格判分。
- 不同动作类别之间的分数不可直接等价比较。

### 限制 5：前端人工复核能力不足

系统已有 target lock 和 debug 面板，但缺少面向教练/开发者的标注与复核闭环。

影响：

- 错误案例难以沉淀为训练数据。
- 无法快速修正 T/A/L、phase、动作类别和评分标签。
- auto-eval 目前主要服务自动诊断，还没有形成数据集管理工作流。

---

## 5. 下一阶段迭代路线

### P0：建立错误案例与标注闭环

目标：把每次失败都变成可复用样本，而不是只修单个 bug。

建议实现：

- 在报告页或 Debug 页增加“标记为错误案例”入口。
- 保存源视频、动作窗口、sampled frames、semantic frames、pose、bio、Path A/B、cross-validation、auto-eval。
- 支持人工修正：
  - 动作类别 / 子类型
  - T/A/L 时间戳
  - phase sequence
  - target lock 是否正确
  - Path A/B 哪一路更可信
- 导出 JSONL 作为后续评估集。

预期收益：

- 建立稳定回归集。
- 为后续专项模型或规则校准提供数据。
- 快速定位“模型错、骨架错、抽帧错、报告错”的责任边界。

### P0：加强目标跟踪和姿态质量门控

目标：减少错误骨架污染 Path B 和生物力学。

建议实现：

- 为每帧姿态增加质量评分：可见关键点比例、bbox 连续性、人体尺度跳变、左右关键点异常交换。
- 将 `skeleton_reliability_signal` 前移到 biomechanics 阶段，提前决定是否弱化 bio 权重。
- 对 `likely_wrong` 场景主动提示用户重选目标，而不是只在报告里提示。
- 对 semantic frames 的轻量 pose 单独记录质量，不与主 sampled pose 混淆。

预期收益：

- 降低错误骨架导致的错误报告。
- Path B 的信任边界更清楚。
- target lock 手动复核触发更准确。

### P1：多动作窗口与长视频元素切分

目标：支持一个视频中出现多个动作元素，而不是只分析单个窗口。

建议实现：

- 将运动密度曲线切成多个候选片段。
- 每个片段独立 profile 推断、视频 AI 语义定位和抽帧。
- 前端允许用户选择要分析的动作片段。
- 数据结构从单 `Analysis` 单元素，逐步扩展到 `analysis.elements[]`。

预期收益：

- 更适合训练课视频。
- 步法、组合旋转、跳跃串联分析更自然。

### P1：结构化 ISU 规则引擎雏形

目标：让报告能清晰区分训练评分与规则判定。

建议实现：

- 先覆盖跳跃常见规则标签：
  - 起跳刃：`!` / `e` 仅输出置信等级，不做绝对判定。
  - 周数：`q` / `<` / `<<` 基于旋转估算 + 视觉观察给低/中/高置信。
  - 落冰质量：step out、two-foot、fall、hand down 等训练标签。
- 单独输出 `rule_findings`，不要直接混入 Force Score。
- 报告中明确：“训练建议”与“规则风险”分栏。

预期收益：

- 更接近教练复盘语言。
- 避免用户误以为 Force Score 等同官方分数。

### P2：专项动作识别模型或轻量分类器

目标：减少通用 LLM 对动作类别的猜测。

短期可选：

- 用现有错误案例训练轻量 tabular/sequence classifier：
  - 输入 motion features、bio features、phase features、Path A/B 输出摘要。
  - 输出 profile / jump subtype / confidence。

中期可选：

- 训练骨架序列分类器，例如 ST-GCN / Temporal Conv。
- 使用 VideoMAE/TimeSformer 特征做动作分类，但需足够数据。

预期收益：

- 相似动作分类更稳定。
- prompt 中的 `profile_evidence` 更可靠。

### P2：语义时间戳置信校准

目标：把当前规则门控升级为可量化的可信度模型。

建议实现：

- 收集 video AI timestamp、skeleton candidate、motion peak 与人工标签的偏差。
- 训练或拟合一个轻量校准器，输出 T/A/L 每个候选的 expected error。
- 用校准结果替代固定的 0.55/0.80、0.60 阈值，或作为阈值补充。

预期收益：

- semantic frames 采用率更可控。
- 降低“看似高置信但时间错位”的风险。

---

## 6. 建议的近期工程任务清单

| 优先级 | 任务 | 影响面 | 验收标准 |
|---|---|---|---|
| P0 | 错误案例导出与人工标签 JSONL | 后端 + 前端 Debug | 可从任意 completed/failed 分析导出完整诊断包 |
| P0 | 姿态质量评分与 target lock 复核触发 | pose / biomechanics / report | 骨架异常时 `data_quality` 下调，并提示重选目标 |
| P0 | auto-eval 面板化 | 前端 Report/Debug | 关键帧顺序、阶段序列、冲突字段可视化 |
| P1 | `rule_findings` 结构字段 | report / schemas / UI | 报告能单独展示规则风险，不混入训练评分 |
| P1 | 多窗口候选预览 | video / UI | 长视频能显示多个候选动作片段供选择 |
| P2 | 动作分类轻量评估集 | scripts / tests | 至少 100 条标注样本，可跑离线准确率 |

---

## 7. 当前测试覆盖与应补测试

已有测试覆盖较完整，重点包括：

- 视频预检查、模糊过滤、精确抽帧。
- profile 抽帧、动作窗口、慢动作 FPS 修正。
- target lock、bbox tracking、pose smoothing。
- biomechanics、rotation unwrap、jump feature。
- video temporal prompt/resolver/provider。
- semantic keyframes、dual-path、cross-validation、report。
- provider retry、metrics、stage retry、pipeline version。
- auto-eval 和 replay export script。

建议补充：

- 真实错误案例 fixture：target 错、T/A/L 乱序、低清晰度、多人背景。
- Path A 视频模式失败后 frame fallback 的端到端断言。
- semantic frames refinement 后不可靠时回退 sampled frames 的报告质量断言。
- `apply_child_score_floor()` 对安全风险文本的边界测试。
- 多 slot provider fallback 的日志和 UI 展示测试。

---

## 8. 关键代码索引

| 文件 | 职责 |
|---|---|
| `backend/app/routers/analysis.py` | 主分析编排、阶段重试、状态流转、日志与存储 |
| `backend/app/services/video.py` | 视频预处理、动作窗口、抽帧、慢动作折算、语义帧精确抽取 |
| `backend/app/services/video_temporal.py` | 视频 AI 语义定位、payload 校验、时间戳仲裁 |
| `backend/app/services/pose.py` | MediaPipe 姿态提取 |
| `backend/app/services/smoothing.py` | 姿态平滑与短缺口插值 |
| `backend/app/services/target_lock.py` | 目标学员候选、自动锁定、手动选择 |
| `backend/app/services/bbox_tracker.py` | bbox 跨帧跟踪 |
| `backend/app/services/action_profiles.py` | 动作 profile 推断 |
| `backend/app/services/jump_features.py` | 跳跃子类型几何证据 |
| `backend/app/services/biomechanics.py` | 生物力学计算与 bio_subscores |
| `backend/app/services/keyframe_candidates.py` | T/A/L 等关键帧候选 |
| `backend/app/services/vision_path_a.py` | 纯视觉路径 |
| `backend/app/services/vision_path_b.py` | 骨架/数值 grounding 路径 |
| `backend/app/services/vision_dual.py` | 双路径协调、骨架标注、并行执行 |
| `backend/app/services/cross_validator.py` | 双路径一致性与冲突诊断 |
| `backend/app/services/auto_eval.py` | 自动质量评估 |
| `backend/app/services/report.py` | 报告生成、评分融合、儿童评分校准 |
| `frontend/src/pages/ReportPage.tsx` | 报告、调试信息、重试入口 |
| `frontend/src/components/AnalysisDebugLogPanel.tsx` | 分析阶段日志展示 |

---

## 9. 结论

v5.0.0 已经把系统从“抽几张图给 LLM 看”推进到“视频语义时序 + 骨架几何 + 双路径交叉验证”的工程化流水线。当前最有价值的下一步不是继续增加 prompt 复杂度，而是建立错误案例闭环、姿态质量门控和结构化规则输出。只有先把可验证数据沉淀下来，后续专项模型、时间戳校准和 ISU 规则引擎才有稳定基础。
