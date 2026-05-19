# 花样滑冰 AI 视觉分析流程

本文档描述 Skating Analyzer 系统从视频输入到最终报告输出的完整 AI 分析流水线。

---

## 总览

```
用户上传视频
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  Stage 1  视频上传 & 校验                             │
│  Stage 1A 视频 AI 语义时间定位 (qwen3.6-plus，并行)    │
│  Stage 2  动作窗口检测 (运动密度曲线)                   │
│  Stage 3  运动加权抽帧                                │
│  Stage 4  目标锁定 (Target Lock)                      │
│  Stage 5  姿态提取 (MediaPipe)                        │
│  Stage 6  动作 Profile 推断                           │
│  Stage 7  生物力学计算                                │
│  Stage 7A 时间戳仲裁 + FFmpeg 语义关键帧抽取            │
│  Stage 8  图片 AI 语义关键帧精析 (多模态)               │
│  Stage 9  LLM 报告融合                                │
│  Stage 10 评分融合 & 存储                             │
└─────────────────────────────────────────────────────┘
    │
    ▼
结构化报告 + 综合评分
```

---

## Stage 1: 视频上传与校验

**入口**: `POST /api/analysis/upload`

- 接受 `.mp4` / `.mov` / `.avi` 格式
- 文件大小限制: 默认 500MB（`MAX_UPLOAD_SIZE_MB`）
- 视频时长限制: 最长 60 秒（`MAX_SECONDS`）
- 保存到 `uploads/{analysis_id}/source.{ext}`
- 创建 `Analysis` 记录，状态设为 `pending`
- 后台启动 `process_analysis()` 异步任务

**涉及文件**: `video.py::save_upload_file()`, `routers/analysis.py::upload_analysis()`

---

## Stage 1A: 视频 AI 语义时间定位

**目标**: 用完整视频理解动作阶段区间，而不是让 MediaPipe 骨架时间戳成为唯一关键帧来源。

**默认模型**: `qwen3.6-plus`。`qwen-vl-max-latest` 仅保留为历史迁移兼容输入，不再推荐作为默认视觉模型。

**流程**:

1. `precheck_video()` 通过后，后端异步启动 `analyze_video_temporal()`
2. 视频 AI 输出 `video_temporal_v1`:
   - 动作类型确认
   - `phase_segments`，包含 `time_start` / `time_end` / `key_frame_hint`
   - 跳跃 T/A/L 建议时间
   - `macro_assessment` 和 `overall_impression`
3. 视频 AI 只提供语义阶段区间和宏观评价，不作为逐帧裁判
4. API 失败、超时、JSON 解析失败或低置信时，写入 fallback flags，主分析继续使用现有 sampled frames

**成本控制**:

- `QWEN_VISION_DAILY_COST_LIMIT_CNY`: 每日视觉成本上限，默认 30
- `QWEN_VISION_VIDEO_ESTIMATED_COST_CNY`: 单次视频语义定位估算成本
- `VIDEO_TEMPORAL_MAX_FRAMES`: 进入图片 AI 的语义关键帧预算，默认 12，上限 12

**涉及文件**: `video_temporal.py::analyze_video_temporal()`, `providers.py::request_dashscope_video_completion()`

---

## Stage 2: 动作窗口检测

**目标**: 从整段视频中定位动作最密集的时间窗口，避免分析无关片段。

**流程**:

1. 以 2fps 速率提取缩略图（160x90）
2. 计算相邻帧差异 → 运动密度曲线（`motion_scores`）
3. 根据动作类型选择窗口大小：
   - 跳跃: 3 秒
   - 旋转: 5 秒
   - 步法: 8 秒
   - 自由滑: 全段
4. 滑动窗口找峰值区间（不同 profile 有不同策略）:
   - **jump/spin**: 选运动量最大的窗口
   - **spiral**: 选运动最平稳的窗口（低方差）
   - **spin**: 附加连续性奖励

**输出**: `(start_sec, end_sec)` 时间窗口

**涉及文件**: `video.py::detect_action_window()`, `_pick_window_by_profile()`

---

## Stage 3: 运动加权抽帧

**目标**: 从动作窗口内智能采样 ~20 帧，运动越剧烈的区域帧越密集。

**流程**:

1. 在动作窗口内以 5fps 提取缩略图
2. 计算运动密度分数
3. 分 10 个段，按运动量分配配额
4. 每段内按运动分数降序选取
5. 对选中帧提取全分辨率帧（854x480）

**输出**: `frame_0001.jpg` ~ `frame_0020.jpg` + 运动元数据

**涉及文件**: `video.py::extract_motion_sampled_frames()`, `_select_motion_weighted_indices()`

---

## Stage 4: 目标锁定 (Target Lock)

**目标**: 当视频中有多人时，确定分析对象。

**流程**:

1. 基于运动检测生成候选区域（bbox）
2. 计算锁定置信度
3. 若置信度 >= 0.72 → 自动锁定，进入下一阶段
4. 若置信度 < 0.72 → 暂停分析，前端展示预览帧让用户手动选择
5. 用户确认后恢复分析

**涉及文件**: `target_lock.py::build_target_preview()`, `build_target_lock_payload()`

---

## Stage 5: 姿态提取 (MediaPipe)

**目标**: 从每帧中提取 33 个关键点的 3D 坐标。

**两种模式**:

| 模式 | 条件 | 行为 |
|------|------|------|
| `multi_pose` | `MEDIAPIPE_POSE_TASK_PATH` 配置了模型文件 | 检测多人，通过评分函数选最佳目标 |
| `fallback_single_pose` | 未配置或模型缺失 | 基于 bbox 裁剪后单人检测 |

**候选评分函数** (加权):
- IoU 连续性: 34%
- 中心距离连续性: 22%
- 运动区域重叠: 16%
- 尺度一致性: 14%
- 关键点可见性: 14%

**输出**: 每帧 33 个 `{x, y, z, visibility, name}` 关键点 + 追踪状态

**关键点索引** (MediaPipe 标准):
- 11/12: 左/右肩
- 23/24: 左/右髋
- 25/26: 左/右膝
- 27/28: 左/右踝

**涉及文件**: `pose.py::extract_pose()`

---

## Stage 6: 动作 Profile 推断

**目标**: 判断动作的实际类型（jump/spin/step/spiral），而非仅依赖用户选择。

**推理依据**:

| 指标 | 来源 | 用途 |
|------|------|------|
| `com_vertical_range` | 质心轨迹垂直跨度 | 判断是否有跳跃腾空 |
| `max_motion_score` | 运动密度最大值 | 判断动作幅度 |
| `avg_motion_score` | 运动密度均值 | 判断螺旋线稳定性 |
| `action_subtype` | 用户选择 | 初始倾向 |

**决策规则**:
- 螺旋线门控: `vertical_range <= 0.06 && avg_motion <= 0.09` 且子类型匹配
- 跳跃门控: `vertical_range >= 0.08 && max_motion >= 0.08` 且子类型匹配
- 未通过门控的跳跃降级为 step

**涉及文件**: `action_profiles.py::infer_analysis_profile()`

---

## Stage 7: 生物力学计算

**目标**: 基于骨骼关键点计算运动学指标，不依赖 AI。

**计算指标**:

| 指标 | 计算方式 |
|------|---------|
| 膝关节角度 | 髋-膝-踝三点夹角（左右分别计算） |
| 躯干倾斜 | 肩中点-髋中点连线与垂直轴夹角 |
| 手臂对称性 | 左右手腕到各自肩的距离差 |
| 质心轨迹 | 肩髋中点的 Y 坐标序列 |
| 跳跃高度 | `h = 0.5 * g * (t/2)^2`（基于滞空时间） |
| 起跳速度 | `v = sqrt(2gh)` |
| 旋转速度 | 肩连线角度变化率 / 时间 |

**子评分** (各 0-100):

| 子项 | 含义 | 理想值 |
|------|------|--------|
| `takeoff_power` | 起跳发力 | 膝角 ~145° |
| `rotation_axis` | 旋转轴心 | 躯干倾斜 ~8° |
| `arm_coordination` | 手臂配合 | 对称性 ~1.0 |
| `landing_absorption` | 落冰缓冲 | 落冰膝角 ~135° |
| `core_stability` | 核心稳定 | 倾斜方差小 |

**涉及文件**: `biomechanics.py::analyze_biomechanics()`

---

## Stage 7A: 时间戳仲裁与语义关键帧抽取

**目标**: 把视频 AI 的语义区间转成 FFmpeg 可切的真实时间点。

**仲裁规则**:

| 视频 AI 置信度 | 行为 |
|---|---|
| `>= 0.80` | 使用视频阶段区间，但在区间内用运动峰值或骨架候选 refine |
| `>= 0.55` | blended：视频区间作为边界，优先使用落在区间内的 T/A/L 骨架候选 |
| `< 0.55` | 回退现有骨架/运动采样 |

**关键原则**:

- 不直接相信视频 AI 单点时间戳
- 阶段 confidence `< 0.60`、越界、乱序或 fallback recommendation 非 `use_video_timestamps` 时保守回退
- 跳跃 T/A/L 顺序异常不会直接失败，会转 blended 或 fallback
- FFmpeg 按仲裁后的 `ResolvedKeyframePlan.selected` 精确抽取 `semantic_0001.jpg` 等语义帧
- 语义帧抽取失败时回退 Stage 3 sampled frames

**涉及文件**: `video_temporal.py::resolve_semantic_keyframes()`, `video.py::extract_precise_frames_at_timestamps()`

---

## Stage 8: LLM 视觉帧分析

**目标**: 用多模态大模型分析语义正确的关键帧。

**流程**:

1. 优先使用 Stage 7A 抽取的语义关键帧；不可用时回退 Stage 3 sampled frames
2. 将图片编码为 base64 data URL
3. 若使用语义帧，每帧 prompt 加入 `video_context`
4. 图片 AI 不再从零猜阶段，而是验证 `phase_verification`
5. Path B 可对语义帧运行轻量 pose/annotation；失败时使用原图 + 全局 bio context
6. 解析 JSON 响应，归一化到标准格式

**video_context 示例**:

```json
{
  "confirmed_action": "Axel",
  "phase_label": "腾空",
  "timestamp_sec": 2.43,
  "phase_time_start": 2.1,
  "phase_time_end": 2.72,
  "key_moment": "A_air_sec",
  "macro_axis_overall": "整体轴心略向左偏，但滑出可控",
  "camera_view": "diagonal_front",
  "video_confidence": 0.78
}
```

**新增帧级输出字段**:

```json
{
  "phase_verification": "agree|shifted|disagree|uncertain",
  "conflict_with_video_context": false,
  "video_context_note": ""
}
```

**原始流程仍保留**:

1. 将抽帧图片编码为 base64 data URL
2. 构造多模态 prompt:
   - System: 花样滑冰分析师角色 + 选手记忆上下文
   - User: 动作类型 + 子类型 + Profile 证据 + 每帧图片
3. 调用 Vision slot 的 AI 模型（默认 `qwen3.6-plus`）
4. 解析 JSON 响应，归一化到标准格式

**每帧输出**:

```json
{
  "frame_id": "frame_0001",
  "phase": "准备|起跳|腾空|落冰|滑出|旋转入|旋转中|旋转出|步法|不可分析",
  "observations": {
    "knee_bend": "充分|不足|过度|不适用",
    "arm_position": "正确|偏高|偏低|不对称|不适用",
    "axis_alignment": "垂直|前倾|后仰|侧倾|不适用",
    "blade_edge": "外刃|内刃|平刃|不适用",
    "core_stability": "稳定|轻微晃动|明显晃动|不适用",
    "landing_absorption": "良好|不足|过度|不适用"
  },
  "issues": ["问题描述"],
  "positives": ["优点描述"],
  "confidence": 0.85
}
```

**涉及文件**: `vision.py::analyze_frames()`

---

## Stage 9: LLM 报告生成

**目标**: 综合视觉分析和生物力学指标，生成结构化训练报告。

**输入**:
- 结构化帧分析（Stage 8 输出）
- 生物力学指标（Stage 7 输出）
- 选手记忆上下文（长期训练背景）

**调用**: Report slot 的 AI 模型（默认 DeepSeek V3）

**输出**:

```json
{
  "summary": "总体评价 2-3 句",
  "issues": [{"category": "落冰阶段", "description": "...", "severity": "high", "phase": "落冰", "frames": ["frame_0012"]}],
  "improvements": [{"target": "落冰缓冲", "action": "练习轻落地..."}],
  "training_focus": "本阶段训练重点",
  "subscores": {"takeoff_power": 80, "rotation_axis": 72, ...},
  "data_quality": "good|partial|poor"
}
```

**涉及文件**: `report.py::generate_report()`

---

## Stage 10: 评分融合与存储

**目标**: 将 AI 评分和生物力学评分融合为最终 Force Score。

**融合公式**:
```
final_score[key] = round(ai_score * 0.4 + bio_score * 0.6)
```

**Force Score 加权**:

| 子项 | 权重 |
|------|------|
| `takeoff_power` | 25% |
| `rotation_axis` | 25% |
| `landing_absorption` | 25% |
| `arm_coordination` | 15% |
| `core_stability` | 10% |

**最终存储**:
- `analysis.vision_structured` — 帧分析结构化数据
- `analysis.report` — 训练报告
- `analysis.pose_data` — 骨骼关键点
- `analysis.bio_data` — 生物力学指标
- `analysis.force_score` — 综合评分
- `analysis.status` → `"completed"`

**涉及文件**: `report.py::fuse_subscores()`, `calculate_force_score()`, `routers/analysis.py::process_analysis()`

---

## AI 供应商架构

系统使用**双 slot** 架构，视觉分析和报告生成可以使用不同的 AI 模型:

| Slot | 用途 | 推荐模型 | 备选 |
|------|------|---------|------|
| `vision` | 多模态帧分析 | Qwen 3.6 Plus | Kimi K2.5, GLM-4.5V, Doubao Seed 2.0 |
| `report` | 文本报告生成 | DeepSeek V3 | Doubao Seed 2.0, MiniMax M2.7, GLM-5, Qwen-Max |

供应商配置存储在 `ai_providers` 表中，API Key 使用 AES-GCM 加密。

---

## 错误处理

| 错误码 | 含义 | 触发场景 |
|--------|------|---------|
| `VIDEO_DECODE_FAILED` | 视频格式无法识别 | FFmpeg 无法解码 |
| `FRAME_EXTRACT_FAILED` | 帧提取失败 | FFmpeg 输出为空 |
| `AI_API_TIMEOUT` | AI 分析超时 | 模型响应超 90s |
| `AI_API_AUTH_ERROR` | API Key 无效 | Key 过期或错误 |
| `AI_API_QUOTA_EXCEEDED` | API 额度不足 | 429 限流 |
| `AI_API_CONTENT_FILTER` | 内容安全过滤 | 模型拒绝分析 |
| `AI_RESPONSE_PARSE_FAIL` | AI 返回格式异常 | JSON 解析失败 |
| `REPORT_SAVE_FAILED` | 报告保存失败 | 数据库写入异常 |
| `UNKNOWN_ERROR` | 未知错误 | 兜底 |

每种错误都会映射为用户友好的中文提示。

---

## 状态流转

```
pending → extracting_frames → [awaiting_target_selection] → analyzing → generating_report → completed
                                                                                          → failed
```

- `awaiting_target_selection`: 仅在自动锁定置信度不足时出现，等待用户手动选择目标
- 任何阶段失败 → `failed` + 错误码 + 错误详情
