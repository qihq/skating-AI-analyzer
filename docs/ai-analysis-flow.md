# 花样滑冰 AI 视觉分析流程

本文档描述 Skating Analyzer 当前（`CURRENT_PIPELINE_VERSION = v5.0.0`）从视频上传到训练报告输出的完整 AI 分析流水线。系统的核心原则是：视频 AI 负责语义时序，MediaPipe/运动密度负责可验证的几何与时间证据，图片/视频多模态模型负责技术观察，报告阶段只做融合与保守表达。

---

## 总览

```text
用户上传视频
  |
  v
Stage 1   上传、格式校验、视频预检查
Stage 2   动作窗口检测与 profile 化运动抽帧
Stage 1A  视频 AI 语义时间定位（基于动作窗口 clip，并行启动）
Stage 3   Target Lock：自动或手动锁定目标学员
Stage 4   MediaPipe 姿态提取、平滑、目标跟踪
Stage 5   动作 Profile 推断与跳跃子类型几何证据
Stage 6   生物力学指标与关键帧候选
Stage 7   视频语义时间戳仲裁与 semantic keyframe 精确抽取
Stage 8   Dual-path 视觉分析与交叉验证
Stage 9   LLM 训练报告生成
Stage 10  分数融合、auto-eval、存储与调试信息输出
  |
  v
结构化帧观察 + 生物力学指标 + 训练报告 + Force Score
```

实际代码中的可重试阶段为：

```text
extract_frames -> pose -> biomechanics -> vision -> report
```

文档中的 Stage 1A/7 属于这些阶段内部的并行或子流程，不是单独的重试入口。

---

## Stage 1: 上传与视频预检查

**入口**：`POST /api/analysis/upload`

上传阶段完成：

- 接受 `.mp4` / `.mov` / `.avi`。
- 默认上传大小上限为 `MAX_UPLOAD_SIZE_MB=500`。
- 使用 magic bytes、`ffprobe`、视频流元数据和抽样帧方差做预检查。
- 最小可分析视频要求：时长大于 0.5 秒，分辨率不低于 320x180。
- 分析主流程最长读取前 `MAX_SECONDS=60` 秒。
- 保存源文件到 `uploads/{analysis_id}/source.{ext}`。
- 创建 `Analysis` 记录，写入 `pipeline_version`、`status=pending`、`retry_from_stage=None`。
- 后台启动 `process_analysis()`。

**涉及文件**：

- `backend/app/services/video.py::save_upload_file()`
- `backend/app/services/video.py::precheck_video()`
- `backend/app/routers/analysis.py::upload_analysis()`

---

## Stage 2: 动作窗口检测与运动抽帧

**目标**：从整段视频中定位最值得分析的动作窗口，再按动作 profile 抽取有限数量的高价值帧。

动作窗口检测：

- 以 `ACTION_WINDOW_DETECTION_FPS=2` 抽取 160x90 缩略图。
- 计算相邻帧差异，形成 `motion_scores`。
- 按 profile 选择窗口：

| Profile | 默认窗口 | 抽帧 FPS | 最大帧数 |
|---|---:|---:|---:|
| `jump` | 3.5s | 16 | 32 |
| `spin` | 6.0s | 10 | 28 |
| `step` | 8.0s | 6 | 24 |
| `spiral` | 6.0s | 8 | 20 |

窗口选择规则：

- `jump`/默认：选择运动量最大的窗口。
- `spin`：运动量最大，同时奖励首尾连续性。
- `spiral`：选择更稳定、低波动的窗口。
- `自由滑`：保留前 60 秒作为窗口。

抽帧策略：

- 在动作窗口内生成缩略图并计算运动密度。
- `_select_motion_weighted_indices()` 保护 top-3 局部运动峰值及邻域。
- 剩余名额按 10 个时间段的运动权重分配。
- 抽取全分辨率帧，默认 `FRAME_FULL_SIZE=854x480`。
- 源视频 FPS >= 60 时按 `source_fps / 30` 折算慢动作时间轴。

输出写入 `frame_motion_scores`，包括窗口、FPS、慢动作倍率、采样帧时间戳、运动分数和 profile hint。

**涉及文件**：

- `backend/app/services/video.py::detect_action_window()`
- `backend/app/services/video.py::extract_motion_sampled_frames()`
- `backend/app/configs/action_profiles.json`

---

## Stage 1A: 视频 AI 语义时间定位

**目标**：让视频多模态模型理解动作的阶段区间，而不是让骨架候选或单张图片独自决定 T/A/L。

当前实现不是直接把完整源视频送入模型，而是在 Stage 2 得到动作窗口后切出轻量 clip：

- `ACTION_AI_CLIP_SIZE=640x360`
- `ACTION_AI_CLIP_FPS=15`
- `ACTION_AI_CLIP_CRF=30`
- `ACTION_AI_CLIP_MAX_MB=40`

默认模型为 `qwen3.6-plus`。`qwen-vl-max-latest` 仅作为历史迁移兼容输入，不再推荐作为默认视觉模型。

视频 AI 输出 `video_temporal_v1`：

```json
{
  "schema_version": "video_temporal_v1",
  "action_confirmation": {
    "action_family": "jump|spin|step|spiral|unknown",
    "confirmed_action": "Axel|Lutz|Flip|Loop|Salchow|Toe Loop|spin|step_sequence|spiral|不可分析",
    "confidence": 0.0
  },
  "phase_segments": [
    {
      "phase_code": "takeoff",
      "phase_label": "起跳",
      "time_start": 1.23,
      "time_end": 1.46,
      "key_frame_hint": 1.35,
      "confidence": 0.82
    }
  ],
  "key_moments": {
    "T_takeoff_sec": 1.34,
    "A_air_sec": 1.55,
    "L_landing_sec": 1.76
  },
  "macro_assessment": {},
  "overall_impression": "",
  "camera_view": "diagonal_front",
  "data_quality_hint": "good|partial|poor",
  "confidence": 0.0,
  "fallback_recommendation": "use_video_timestamps|use_sampled_frames|manual_review",
  "quality_flags": []
}
```

关键约束：

- 视频 AI 是语义层，不是逐帧裁判。
- 时间戳会被验证、仲裁、refine；不会被无条件信任。
- 失败、超时、JSON 解析失败、低置信或主动 fallback recommendation 都会写入 flags，主流程继续使用 sampled frames 或 skeleton fallback。
- 视频 AI 等待上限为 `VIDEO_TEMPORAL_WAIT_TIMEOUT_SECONDS=210`。

成本控制：

- `QWEN_VISION_DAILY_COST_LIMIT_CNY`：视觉每日成本上限，默认 30。
- `QWEN_VISION_VIDEO_ESTIMATED_COST_CNY`：单次视频语义定位估算成本。
- `VIDEO_TEMPORAL_MAX_FRAMES`：进入语义关键帧抽取的预算，上限 12。

**涉及文件**：

- `backend/app/services/video.py::cut_action_window_ai_clip()`
- `backend/app/services/video_temporal.py::analyze_video_temporal()`
- `backend/app/services/providers.py::request_dashscope_video_completion()`

---

## Stage 3: Target Lock

**目标**：多人物或复杂背景下确定被分析的学员。

流程：

1. 基于运动区域生成候选 bbox。
2. 计算候选连续性和置信度。
3. 置信度 `>= TARGET_LOCK_AUTO_THRESHOLD`（当前 0.72）时自动锁定。
4. 置信度不足时状态进入 `awaiting_target_selection`，前端显示预览帧和候选框。
5. 用户确认候选或手动画框后，分析从后续阶段恢复。

候选评分主要考虑：

- IoU 连续性
- 中心距离连续性
- 运动区域重叠
- 尺度一致性
- 关键点可见性

**涉及文件**：

- `backend/app/services/target_lock.py`
- `backend/app/services/bbox_tracker.py`
- `frontend/src/pages/TargetSelectionPage.tsx`

---

## Stage 4: 姿态提取、平滑与目标跟踪

**目标**：从抽帧序列中提取 33 点 MediaPipe 姿态，并尽量保持跨帧目标一致。

模式：

| 模式 | 条件 | 行为 |
|---|---|---|
| `multi_pose` | 配置 `MEDIAPIPE_POSE_TASK_PATH` | 多人检测，按目标锁定和连续性选最佳候选 |
| `fallback_single_pose` | 未配置或模型加载失败 | 基于 bbox 裁剪后做单人检测 |

姿态处理：

- MediaPipe 标准 33 个关键点。
- 支持 One-Euro 风格平滑和短时低可见性插值。
- `track_bbox()` 用于跨帧目标框跟踪。
- 姿态结果会影响生物力学、Path B 骨架叠加、cross-validation 和 report data_quality。

关键点索引：

- 11/12：左/右肩
- 23/24：左/右髋
- 25/26：左/右膝
- 27/28：左/右踝

**涉及文件**：

- `backend/app/services/pose.py::extract_pose()`
- `backend/app/services/smoothing.py`
- `backend/app/services/bbox_tracker.py`

---

## Stage 5: 动作 Profile 与跳跃子类型证据

**目标**：用规则证据校正用户输入，避免把所有动作都按同一套抽帧、提示词和评分逻辑处理。

Profile 支持：

- `jump`
- `spin`
- `step`
- `spiral`

推断依据：

| 指标 | 来源 | 用途 |
|---|---|---|
| `com_vertical_range` | 姿态质心轨迹 | 判断是否存在明显腾空 |
| `max_motion_score` | 运动密度峰值 | 判断动作爆发性 |
| `avg_motion_score` | 运动密度均值 | 判断滑行动作稳定性 |
| `action_subtype` / `skill_category` | 用户输入 | 初始倾向和 prompt 约束 |

跳跃子类型证据会提取 Lutz/Flip/Loop/Salchow/Axel 的几何线索，例如起跳前刃倾向、预备姿态和运动方向，用于提示词 grounding，但不会作为唯一判决。

**涉及文件**：

- `backend/app/services/action_profiles.py`
- `backend/app/services/jump_features.py`
- `backend/app/services/vision_prompt_templates.py`

---

## Stage 6: 生物力学计算与关键帧候选

**目标**：基于骨架序列生成可解释的几何指标，提供独立于 LLM 的客观证据。

主要指标：

| 指标 | 计算方式 / 含义 |
|---|---|
| 膝关节角度 | 髋-膝-踝三点夹角，左右分别计算 |
| 躯干倾斜 | 肩中点-髋中点连线相对垂直轴角度 |
| 手臂对称性 | 左右手臂位置差异 |
| 质心轨迹 | 肩髋中点的时序轨迹 |
| 跳跃滞空 / 高度 | 基于 T/A/L 与 FPS 修正估算 |
| 起跳速度 | 由估算高度推导 |
| 旋转速度 / 周数 | 肩线角度 unwrap 后估算 |

子评分：

- `takeoff_power`
- `rotation_axis`
- `arm_coordination`
- `landing_absorption`
- `core_stability`

生物力学还会生成 `key_frame_candidates`，为语义时间戳仲裁提供 skeleton T/A/L 候选。

**涉及文件**：

- `backend/app/services/biomechanics.py`
- `backend/app/services/keyframe_candidates.py`
- `backend/app/services/phase_smoother.py`

---

## Stage 7: 时间戳仲裁与语义关键帧抽取

**目标**：把视频 AI 的阶段区间、骨架候选、运动峰值合并为 FFmpeg 可精确抽取的真实时间点。

仲裁规则：

| 视频 AI 置信度 | 行为 |
|---:|---|
| `>= 0.80` | `video_ai_refined`：使用视频阶段区间，并用骨架候选或局部运动峰值 refine |
| `>= 0.55` | `blended`：视频区间作为边界，优先使用落在区间内的骨架 T/A/L |
| `< 0.55` | `skeleton_fallback`：回退到骨架候选与 sampled frames |

可靠性门控：

- 阶段 confidence `< 0.60` 不进入语义帧选择。
- T/A/L 必须满足顺序：`T < A < L`。
- `fallback_recommendation != use_video_timestamps` 时保守降级。
- 语义帧最多 12 张。
- T/L 会在 `±0.18s` 局部窗口内用高 FPS 运动峰值 refine。
- Apex（A）保留语义/骨架时间点，不强行贴到运动峰值。
- 语义帧抽取失败或 refinement 后不可靠时，视觉分析改用 Stage 2 sampled frames。

输出：

- `uploads/{analysis_id}/semantic_frames/semantic_0001.jpg`
- `frame_motion_scores.resolved_keyframes`
- `frame_motion_scores.video_temporal`

**涉及文件**：

- `backend/app/services/video_temporal.py::resolve_semantic_keyframes()`
- `backend/app/services/video_temporal.py::semantic_keyframes_are_reliable()`
- `backend/app/services/video.py::refine_semantic_keyframe_timestamps()`
- `backend/app/services/video.py::extract_precise_frames_at_timestamps()`

---

## Stage 8: Dual-Path 视觉分析

**目标**：让“纯视觉观察”和“骨架/数值 grounding”互相校验，降低单一路径误判。

Path A：纯视觉路径

- 使用原始 sampled frames 或 semantic frames。
- 如果没有可靠 semantic frames，会优先尝试动作窗口视频模式，失败后回退图片帧模式。
- 不直接引用骨架测量值，主要输出逐帧观察、阶段、问题、优点和 `pure_vision_subscores`。
- 当使用 semantic frames 时，每帧附带 `video_context`，模型需要做 phase verification。

Path B：骨架/数值 grounding 路径

- 对帧图像叠加 MediaPipe 骨架和角度标注。
- 输入每帧生物力学上下文、关键帧集合和 jump metrics 摘要。
- 常规 sampled frames 下最多取 10 张带上下文帧；semantic frames 下保留全部语义帧。
- Path B 是软失败：失败时返回 `error`，主流程继续依赖 Path A。

交叉验证：

- 比较两路 `detected_phases`、五项子评分和客观维度分歧。
- 生成 `skeleton_reliability_signal`：`reliable` / `uncertain` / `likely_wrong`。
- 根据一致率和可靠性给出 `recommended_path` 与 blend weights。
- 高冲突或关键帧顺序异常会标记 `needs_human_review`。

帧级视频上下文字段：

```json
{
  "phase_verification": "agree|shifted|disagree|uncertain",
  "conflict_with_video_context": false,
  "video_context_note": ""
}
```

**涉及文件**：

- `backend/app/services/vision_dual.py`
- `backend/app/services/vision_path_a.py`
- `backend/app/services/vision_path_b.py`
- `backend/app/services/vision_video_context.py`
- `backend/app/services/cross_validator.py`

---

## Stage 9: LLM 报告生成

**目标**：把视觉观察、生物力学、视频时序和学员记忆融合为结构化训练报告。

输入：

- Path A 标准化帧分析。
- Path B 子评分与量化观察。
- 生物力学指标。
- `cross_validation` 与 `auto_eval`。
- `video_temporal` 与 `resolved_keyframes` 摘要。
- 学员记忆、技能分类、用户备注等统一上下文。

输出：

```json
{
  "summary": "总体评价 2-3 句",
  "issues": [
    {
      "category": "落冰阶段",
      "description": "...",
      "severity": "high|medium|low",
      "phase": "落冰",
      "frames": ["semantic_0003"]
    }
  ],
  "improvements": [
    {"target": "落冰缓冲", "action": "..."}
  ],
  "training_focus": "本阶段训练重点",
  "subscores": {
    "takeoff_power": 80,
    "rotation_axis": 72,
    "arm_coordination": 76,
    "landing_absorption": 70,
    "core_stability": 74
  },
  "data_quality": "good|partial|poor"
}
```

报告策略：

- 报告模型失败时降级为基于生物力学的 fallback report。
- JSON 解析最多重试 3 次。
- `data_quality` 会结合视觉质量、双路径冲突和是否需要人工复核下调。
- 针对儿童/初学者启用保守评分校准，避免把可训练动作按成人高水平竞技标准过度扣分。

**涉及文件**：

- `backend/app/services/report.py::generate_report()`

---

## Stage 10: 分数融合、auto-eval 与存储

子评分融合：

```text
bio_weight = max(0.20, 0.60 - warning_count * 0.08)
ai_weight = 1.0 - bio_weight
fused[key] = round(ai_score * ai_weight + bio_score * bio_weight)
```

当生物力学质量 flags 较多时，系统会降低 bio 权重；没有 bio 子评分时直接使用 AI 子评分。

Force Score 权重：

| 子项 | 权重 |
|---|---:|
| `takeoff_power` | 25% |
| `rotation_axis` | 25% |
| `landing_absorption` | 25% |
| `arm_coordination` | 15% |
| `core_stability` | 10% |

儿童评分下限：

- `data_quality=good` 且没有高危问题时，Force Score 最低 70。
- `data_quality=partial` 且没有高危问题时，Force Score 最低 65。
- `data_quality=poor`、骨架 `likely_wrong`、高严重度/安全风险问题时不应用下限。

auto-eval：

- 校验关键帧顺序。
- 校验阶段序列。
- 收集高置信冲突。
- 输出 data quality flags 和 key-frame signature。

最终存储字段：

- `analysis.vision_structured`
- `analysis.vision_path_a`
- `analysis.vision_path_b`
- `analysis.cross_validation`
- `analysis.report`
- `analysis.pose_data`
- `analysis.bio_data`
- `analysis.frame_motion_scores`
- `analysis.force_score`
- `analysis.processing_logs`
- `analysis.processing_timings`
- `analysis.pipeline_version`
- `analysis.status = completed`

**涉及文件**：

- `backend/app/services/report.py::fuse_subscores()`
- `backend/app/services/report.py::calculate_force_score()`
- `backend/app/services/report.py::apply_child_score_floor()`
- `backend/app/services/auto_eval.py`
- `backend/app/routers/analysis.py::process_analysis()`

---

## AI 供应商架构

系统采用多 slot 供应商配置，API 使用 OpenAI SDK 兼容接口或 DashScope 视频接口。

| Slot | 用途 |
|---|---|
| `vision` | 兼容旧视觉入口或 fallback |
| `vision_path_a` | Path A 纯视觉/视频模式 |
| `vision_path_b` | Path B 骨架图 + 量化 grounding |
| `report` | 文本报告生成 |

若 `vision_path_a` 或 `vision_path_b` 未配置，后端会回退到 `vision` slot，并在日志中记录 fallback。

推荐默认：

- 视觉：`qwen3.6-plus`
- 报告：DeepSeek 系列文本模型

供应商配置存储在数据库 `ai_providers` 表中，API Key 使用 AES-GCM 加密。

---

## 状态流转与重试

状态流转：

```text
pending -> processing/extracting_frames -> awaiting_target_selection -> analyzing -> generating_report -> completed
                                                                                                  -> failed
```

重试入口：

| retry_from | 前置缓存要求 |
|---|---|
| `extract_frames` | 源视频存在 |
| `pose` | 已有 `frame_motion_scores` |
| `biomechanics` | 已有 `pose_data` |
| `vision` | 已有 `pose_data` + `bio_data` |
| `report` | 已有 `vision_structured` + `bio_data` |

系统会记录：

- `processing_logs`：阶段日志、耗时、provider 细节和 fallback 原因。
- `processing_timings`：每个阶段耗时。
- `retry_from_stage`：失败后建议从哪个阶段恢复。
- stale task 恢复：长时间卡住的任务会被标记为 failed，并保留可重试阶段。

---

## 错误处理

常见错误码：

| 错误码 | 含义 |
|---|---|
| `VIDEO_FORMAT_INVALID` | 容器或 magic bytes 不合法 |
| `VIDEO_NO_VIDEO_STREAM` | 无视频流、时长/分辨率不满足要求 |
| `VIDEO_BLANK_FRAMES` | 抽样帧为空白或近似黑屏 |
| `VIDEO_DECODE_FAILED` | FFmpeg 解码失败 |
| `FRAME_EXTRACT_FAILED` | 抽帧失败或语义帧抽取失败 |
| `AI_API_TIMEOUT` | AI 请求超时 |
| `AI_API_AUTH_ERROR` | API Key 无效 |
| `AI_API_QUOTA_EXCEEDED` | API 额度或限流问题 |
| `AI_API_CONTENT_FILTER` | 模型拒绝内容 |
| `AI_RESPONSE_PARSE_FAIL` | AI 返回 JSON 不合法 |
| `REPORT_SAVE_FAILED` | 数据库存储失败 |
| `UNKNOWN_ERROR` | 未知兜底错误 |

错误会映射为用户可读提示；可降级的 AI 错误尽量转为 fallback report 或 sampled-frame fallback，而不是直接中断整条流水线。
