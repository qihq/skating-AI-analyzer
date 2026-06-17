# 视频分析模块复盘与迭代方向

本文是 Skating Analyzer 视频分析模块的工程复盘。流水线接口和阶段细节见 [ai-analysis-flow.md](./ai-analysis-flow.md)；本文关注当前能力边界、已沉淀的工程原则，以及后续优先级。

当前版本：`v5.2.303`

## 1. 当前模块定位

Skating Analyzer 目前是训练复盘系统，不是 ISU 比赛判分器。它的目标是帮助家长、学员和教练更稳定地回答：

- 视频里主要在练什么动作？
- 哪个滑行者是目标对象？
- 起跳、腾空、落冰或非跳跃阶段是否能被可靠定位？
- 可见的技术问题和积极点是什么？
- 下一周训练应优先练什么？

系统没有本地端到端专项模型，也没有完整 ISU 规则引擎。核心能力来自规则、运动密度、MediaPipe、YOLO/ByteTrack、云端多模态模型和报告 LLM 的组合。

## 2. 当前架构

```text
source video
  -> precheck + input window
  -> motion sampling
  -> target lock / manual target selection
  -> person tracking
  -> pose extraction
  -> biomechanics + keyframe candidates
  -> video temporal AI
  -> semantic keyframe pipeline
  -> Path A / Path B vision
  -> report + plan + debug output
```

关键原则：

- 单一信号不直接决定最终结论。
- 视频 AI 是语义层，不是逐帧裁判。
- 手动目标锁定比自动 relock 更权威。
- 错人骨架比缺少骨架更危险。
- semantic frames 必须能解释其来源、置信和降级原因。
- 报告要围绕可见证据和可执行训练建议，避免“数据质量有限”式空话。

## 3. 已经稳定下来的能力

### 3.1 输入范围透明化

系统现在会记录 AI 实际看到的视频范围：

- `manual_window`
- `full_context`
- `system_truncated`

报告页和 Debug 页会展示输入窗口。长视频可由用户在上传时手动指定起止秒数；未指定时默认尽量保留全量上下文。

价值：

- 用户知道 AI 是否看到了完整动作。
- Path A 和 video temporal 使用的 clip 有清晰 provenance。
- 旧的“只看动作窗口但 UI 不提示”的问题被消除。

### 3.2 broad category 上传

Review 上传不再要求精确动作子类或技能节点。用户只知道“跳跃/旋转/步法/自由滑”时也可以提交。

价值：

- 符合真实家长使用场景。
- 用户备注会进入最早的视频语义 prompt，让模型先理解“我想看什么”。
- 后续 profile inference 可以从视频和骨架信号修正输入。

### 3.3 manual target fail-closed

手动选人后，如果 tracker/pose 没有足够证据支持目标身份，系统会 fail closed 或 blank pose，而不是继续绘制疑似错误 skeleton。

价值：

- 错人分析的危害被优先控制。
- Path B 和 biomechanics 的污染减少。
- Debug 中能看到 manual lock、support anchor、final loss、foreground growth 等诊断。

### 3.4 语义关键帧管线

`semantic_keyframe_pipeline.py` 已经把视频语义、骨架候选、运动峰值、可见性、重试和局部修复集中管理。

它支持：

- full-context motion conflict 判断
- skeleton T/A/L conflict 判断
- low-visibility 和 foreground occlusion 检查
- same-video semantic reuse
- video temporal retry
- partial merge
- visual T/A/L promotion
- sampled-frame fallback

价值：

- T/A/L 不再只靠单次 video AI 或稀疏 sampled frames。
- 大量错误场景可以用 flags 定位。
- Debug 和批量脚本能复用同一批诊断字段。

### 3.5 双路径报告韧性

Path A 和 Path B 都会存储：

- `vision_path_a`
- `vision_path_b`
- `cross_validation`

报告生成会用 Path B/top issues 修补过泛化或失败的 Path A/报告结果，并生成动作专项 drills。

价值：

- 报告更少输出模板化建议。
- 骨架证据不再完全丢失在 prompt 里。
- 视觉失败时仍可给出可执行 fallback。

## 4. 当前主要限制

### 限制 1：专项数据闭环还不完整

系统缺少稳定的人工标注集。很多阈值来自工程经验和 batch diagnostics，而不是统计校准。

影响：

- 类似动作子类区分仍不稳定。
- 语义时间戳置信度无法可靠映射到真实误差。
- 每次修复都容易继续增加规则复杂度。

### 限制 2：目标跟踪仍是最大风险源

远距离小目标、多人同框、前景遮挡、local zoom、成年人和儿童混杂时，检测器和 tracker 都可能产生诱人但错误的 bbox。

影响：

- Path B 的骨架叠加可能失真。
- 生物力学数值可能被错误目标污染。
- semantic frame 可见性检查只能补救一部分场景。

### 限制 3：单 Analysis 仍偏向单动作

虽然 full-context 和自由滑输入更稳，但数据结构仍主要围绕一次分析生成一个主动作报告。

影响：

- 一个训练视频里多个跳跃/旋转/步法时，系统需要选择一个核心窗口。
- 长节目片段更适合“片段复盘”，不适合严格 T/A/L 单元素分析。

### 限制 4：ISU 规则未结构化

Force Score 是训练表现分，不等于 TES、PCS、GOE 或 Level。

影响：

- 不能宣称比赛判分。
- 起跳刃、周数不足、等级特征等目前只能作为训练风险语言出现。
- 家长和教练需要理解报告是训练建议，不是裁判表。

### 限制 5：前端标注和复核闭环不足

Target selection 和 Debug 已经存在，但还没有面向持续改进的数据标注工作台。

影响：

- 错误案例难以沉淀为 JSONL/fixture。
- 人工修正 T/A/L、target、profile、Path A/B 信任边界的流程不够顺。
- 后续训练轻量模型缺少干净输入。

## 5. 建议路线

### P0：错误案例导出与人工标签

目标：把失败分析变成可复用样本。

建议：

- 在 Report/Debug 增加“标记错误案例”。
- 导出源视频 hash、input window、target lock、sampled frames、semantic frames、pose、bio、Path A/B、report、flags。
- 支持人工填写：
  - 正确 target
  - 正确 action family/profile
  - T/A/L 或非跳跃阶段
  - 哪一路视觉更可信
  - 错误类型
- 输出 JSONL，供测试和离线评估使用。

验收：

- 至少能从任意 completed/failed 分析导出完整诊断包。
- 后端测试可加载 fixture 重放关键判定。

### P0：姿态质量评分前移

目标：在 report 之前判断 skeleton 是否值得信。

建议：

- 给每帧姿态增加 `pose_quality_score`。
- 指标包括可见点比例、bbox 连续性、人体尺度跳变、关键点左右异常、tracker state。
- 在 biomechanics 阶段就输出 `skeleton_reliability_signal`。
- 当 `likely_wrong` 时降低 bio 权重，必要时要求重新选人。

验收：

- 错人/前景 relock fixture 中 `data_quality` 下调。
- Path B 不再把明显错误骨架作为强证据。

### P1：多窗口候选

目标：更好支持训练课片段和自由滑。

建议：

- 从 motion curve 切出多个候选窗口。
- 每个窗口独立 profile inference 和 video temporal。
- 前端让用户选择要分析的窗口。
- 数据结构逐步引入 `analysis.elements[]`。

验收：

- 长视频能显示多个候选片段。
- 用户可明确选择“分析第 2 个跳跃”。

### P1：结构化规则风险

目标：区分训练建议和规则风险。

建议先覆盖跳跃：

- 起跳刃风险：`edge_clear` / `edge_attention` / `edge_likely_wrong`
- 周数风险：`clean` / `q_risk` / `under_risk`
- 落冰风险：step out、two-foot、hand down、fall

输出字段建议：

```json
{
  "rule_findings": [
    {
      "type": "rotation_risk",
      "label": "q_risk",
      "confidence": "medium",
      "evidence": ["estimated_rotations", "landing_frame"]
    }
  ]
}
```

验收：

- 报告 UI 单独展示“规则风险”，不混入 Force Score。
- 文案明确“训练参考，不等同裁判判分”。

### P2：轻量动作分类器

目标：减少通用多模态模型对动作类别的猜测。

短期：

- 用现有 JSONL 训练 tabular classifier。
- 输入 motion features、bio features、Path A/B 摘要、video temporal action family。
- 输出 profile/subtype/confidence。

中期：

- 骨架序列分类器。
- 视频特征分类器。

验收：

- 离线评估集有准确率和混淆矩阵。
- profile mismatch retry 次数下降。

### P2：时间戳置信校准

目标：把规则阈值转成可量化的误差估计。

建议：

- 收集 video AI、skeleton candidate、motion peak 与人工 T/A/L 的偏差。
- 估计每类候选 expected error。
- 用校准结果辅助替换固定 `0.55`、`0.80` 等阈值。

验收：

- semantic frames 采用率和错误率可用数据解释。
- 不同视频质量下的 fallback 更稳定。

## 6. 工程维护建议

- 新增规则必须写入 quality flag，方便 batch 汇总。
- 不要只改 prompt；prompt 改动需要配套 fixture 或至少批量诊断对比。
- target/pose 相关变更必须跑多人、tiny target、foreground occlusion、manual lock 相关测试。
- 语义关键帧变更必须检查 retry、partial frames、sampled fallback 和 same-video reuse。
- 报告文案变更要保证问题和建议绑定到证据，不回到“视频质量有限”占位句。

## 7. 关键测试方向

已有测试重点覆盖：

- broad-category upload
- user note prompt context
- video precheck
- target lock / manual selection
- person tracker
- pose smoothing
- biomechanics
- keyframe candidates
- video temporal resolver/provider/prompt
- semantic keyframe pipeline
- Path A/B and report fusion
- stage retry
- debug runs
- archive and training plan flows

建议继续补：

- manual lock 缺 tracker 支持的端到端 fixture
- foreground adult blocks small child target
- full-context jump with multiple motion peaks
- retry rejects worse semantic T/A/L
- Path A clip unavailable but frame mode succeeds
- report evidence repair when model emits generic issues

## 8. 结论

`v5.2.303` 的重点已经从“抽帧给 LLM 看”演进到“目标身份、视频语义、骨架几何、运动峰值和双路径证据共同约束”。下一阶段最重要的不是继续堆阈值，而是建立错误案例闭环、姿态质量评分和结构化规则风险。只要这些可验证数据沉淀下来，后续专项模型和时间戳校准才有可靠基础。
