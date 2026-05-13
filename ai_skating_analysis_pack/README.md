# AI 花样滑冰视频分析模块

版本：v1.1.11 | Pipeline 版本：`CURRENT_PIPELINE_VERSION = "v1.1.11"`

---

## 1. 模块概述

本模块是一个**端到端的花样滑冰训练视频 AI 分析系统**，接收一段花滑训练视频（mp4/mov/avi），自动完成视频预处理、骨骼姿态提取、动作类型识别、生物力学指标计算、**双路 LLM 视觉分析 + 交叉验证**、结构化报告生成，并输出综合发力评分（0-100 分）和五维子维度评分。

在整个 App 中的位置：本模块是后端核心分析引擎，通过 FastAPI REST API（`POST /api/analysis/upload`）接收前端上传的视频，后台异步执行完整分析流水线，将结果存入 SQLite 数据库，前端轮询获取报告。

---

## 2. 整体流水线架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                        视频输入 (mp4/mov/avi)                        │
└─────────────────────────────────────────┬───────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Step 1: 视频预处理 + 运动密度抽帧                                     │
│  [src/app/services/video.py]                                        │
│  ─ FFprobe 检测源帧率（ffprobe）                                      │
│  ─ 视频预检：magic bytes / 视频流 / 时长 / 分辨率 / 黑帧检测            │
│  ─ 低分辨率缩略图提取 (160x90, profile-specific fps)                  │
│  ─ OpenCV 帧差法计算运动密度曲线                                       │
│  ─ 滑动窗口定位动作峰值区间（按 profile 优化策略）                       │
│  ─ 运动密度加权采样 N 帧 → 480p 高清提取                               │
│  ─ 强制保护 top-2 运动峰值 ±1 帧                                      │
│  ─ 输出 effective_fps / source_fps / window_seconds 作为采样依据       │
│  输入: video_path, action_type, analysis_profile_hint                │
│  输出: frame_paths[], motion_scores{}, VideoSamplingMetadata         │
└─────────────────────────────────────────┬───────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Step 2: 目标锁定（选人）                                             │
│  [src/app/services/target_lock.py]                                  │
│  ─ 生成候选 bbox（中心/左/右三个区域）                                  │
│  ─ 置信度评分 → 自动锁定 or 等待手动选择                               │
│  ─ 支持前端手动框选 bbox 校验                                         │
│  输入: frame_names[]                                                 │
│  输出: target_lock{selected_bbox, candidates, status}                │
└─────────────────────────────────────────┬───────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Step 2.5: 逐帧目标跟踪                                              │
│  [src/app/services/bbox_tracker.py]                                 │
│  ─ OpenCV CSRT 跟踪器逐帧跟踪主目标 bbox                              │
│  ─ 跟踪失败时线性外推                                                 │
│  输入: frame_paths[], initial_bbox                                   │
│  输出: bbox_per_frame[], quality_flags[]                             │
└─────────────────────────────────────────┬───────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Step 3: 骨骼姿态提取                                                │
│  [src/app/services/pose.py]                                         │
│  ─ MediaPipe Pose Landmarker（单人/多人模式）                         │
│  ─ 结合 target_lock bbox 裁剪聚焦主滑行者                             │
│  ─ 多候选评分（IoU + 连续性 + 尺度 + 可见性 + 运动重叠）               │
│  ─ One-Euro Filter 时序平滑 + 短时遮挡插值                            │
│  输入: frames_dir, target_lock, bbox_per_frame                       │
│  输出: pose_data{connections, frames[{frame, keypoints[33]}]}        │
└─────────────────────────────────────────┬───────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Step 4: 分析 Profile 推断 + 跳跃几何证据                             │
│  [src/app/services/action_profiles.py]                              │
│  [src/app/services/jump_features.py]                                │
│  ─ 用户输入动作类型 → profile_hint                                    │
│  ─ 几何验证：CoM 垂直范围、人体高度归一化、腾空帧检测、髋部旋转信号      │
│  ─ 跳跃门控：relative_vertical >= 0.12 AND max_motion >= 0.06       │
│  ─ 跳跃种类弱几何证据：点冰/双脚并拢/自由腿摆动/进近方向/刃型评分        │
│  输入: action_type, action_subtype, pose_data, motion_scores         │
│  输出: analysis_profile ("jump"/"spin"/"step"/"spiral"), evidence{}  │
└─────────────────────────────────────────┬───────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Step 5: 生物力学计算                                                │
│  [src/app/services/biomechanics.py]                                 │
│  ─ 膝关节角度、躯干倾斜、手臂对称性（逐帧）                            │
│  ─ 质心（CoM）轨迹追踪                                               │
│  ─ T/A/L 关键帧检测（起跳/顶点/落冰）                                 │
│  ─ 跳跃指标估算（滞空时间、高度、起跳速度、转速）                       │
│  ─ 旋转轴稳定性评估                                                   │
│  ─ 五维子维度评分                                                     │
│  ─ 跳跃周数估算（转速 × 滞空时间）                                    │
│  输入: pose_data, action_type, analysis_profile, effective_fps       │
│  输出: bio_data{key_frames, jump_metrics, bio_subscores, ...}        │
└─────────────────────────────────────────┬───────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Step 6: 双路 LLM 视觉分析 + 交叉验证                                │
│  [src/app/services/vision_dual.py]                                  │
│  ┌─────────────────────┐    ┌─────────────────────────┐             │
│  │ Path A: 纯视觉判断   │    │ Path B: 量化 grounding   │             │
│  │ [vision_path_a.py]  │    │ [vision_path_b.py]      │             │
│  │ ─ 原始帧图片        │    │ ─ 骨架叠加帧图片         │             │
│  │ ─ 纯肉眼观察视角    │    │ ─ 膝角度/躯干倾斜数值   │             │
│  │ ─ phase_segments    │    │ ─ bio_context 逐帧注入   │             │
│  │ ─ pure_vision_      │    │ ─ subscores 量化评分     │             │
│  │   subscores         │    │ ─ top_issues 引用数值    │             │
│  └────────┬────────────┘    └──────────┬──────────────┘             │
│           │                            │                            │
│           └──────────┬─────────────────┘                            │
│                      ▼                                               │
│  [cross_validator.py] 交叉验证                                       │
│  ─ 逐维度对比 subscores（客观维度 ±6 同意，主观维度 ±10 同意）         │
│  ─ detected_phases Jaccard 相似度                                    │
│  ─ skeleton_reliability_signal: reliable/uncertain/likely_wrong      │
│  ─ 融合权重计算：reliable→B:65%, uncertain→50:50%, wrong→A:75%      │
│  输入: action_type, frame_payloads[], pose_data, bio_data            │
│  输出: DualPathResult{path_a, path_b, validation, blend_weights}    │
└─────────────────────────────────────────┬───────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Step 7: LLM 结构化报告生成                                          │
│  [src/app/services/report.py]                                       │
│  ─ 将视觉分析结果 + 生物力学指标发送给文本 LLM                        │
│  ─ 生成 summary/issues/improvements/training_focus/subscores        │
│  ─ AI(40%) + 生物力学(60%) 融合评分                                  │
│  ─ 最多 3 次 JSON 解析重试                                           │
│  输入: action_type, vision_structured, bio_data, dual_path_meta      │
│  输出: report{summary, issues, improvements, subscores, ...}         │
└─────────────────────────────────────────┬───────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Step 8: 综合评分 + 阶段平滑                                         │
│  ─ subscores 加权均值 → force_score (0-100)                         │
│    权重: 起跳发力(25%) + 旋转轴心(25%) + 手臂配合(15%)               │
│          + 落冰缓冲(25%) + 核心稳定(10%)                             │
│  ─ phase_smoother 验证/修正逐帧阶段预测                               │
│  ─ 关键帧 ±1 帧投票分歧时用 biomechanics T/A/L 强制回退               │
│  输出: force_score, smoothed_phases                                  │
└─────────────────────────────────────────┬───────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        结构化分析结果输出                              │
│  AnalysisResult{                                                     │
│    analysis_profile, vision_structured, bio_data, report,            │
│    force_score, pose_data, frame_motion_scores, target_lock,         │
│    sampling_metadata, smoothed_phases, cross_validation              │
│  }                                                                   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. 目录结构说明

```
ai_skating_analysis_pack/
├── src/
│   ├── __init__.py
│   └── app/
│       ├── __init__.py
│       ├── services/                      # ★ 核心 AI 分析源码（v1.1.11，保持原始 import 路径）
│       │   ├── __init__.py                # 服务层公共导出
│       │   ├── video.py                   # 视频预处理：FFmpeg 抽帧、运动密度采样、动作窗口检测
│       │   ├── target_lock.py             # 目标锁定：自动/手动选人、bbox 校验
│       │   ├── bbox_tracker.py            # [v1.1.1+] 逐帧目标跟踪：OpenCV CSRT 跟踪器
│       │   ├── smoothing.py               # [v1.1.6+] 姿态平滑：One-Euro Filter + 短时遮挡插值
│       │   ├── pose.py                    # 姿态估计：MediaPipe 33 关键点、多人候选评分
│       │   ├── action_profiles.py         # 动作 Profile 推断：几何门控 + 跳跃特征知识库
│       │   ├── jump_features.py           # [v1.1.7+] 跳跃种类弱几何证据：点冰/刃型/摆腿/进近方向
│       │   ├── biomechanics.py            # 生物力学：膝角/躯干/CoM/T-A-L 关键帧/跳跃指标
│       │   ├── bio_context.py             # [新增] 生物力学上下文构建：逐帧指标 → Path B prompt 注入
│       │   ├── vision.py                  # LLM 视觉分析（兼容层）：多 provider 投票合并
│       │   ├── vision_path_a.py           # [新增] Path A：纯视觉判断（无骨架数据）
│       │   ├── vision_path_b.py           # [新增] Path B：骨架叠加帧 + 生物力学数值 grounding
│       │   ├── vision_dual.py             # [新增] 双路分析编排 + 交叉验证
│       │   ├── cross_validator.py         # [新增] 交叉验证：逐维度对比、骨架可靠性信号、融合权重
│       │   ├── frame_annotator.py         # [新增] 骨架帧标注：MediaPipe 关键点 + 角度数字叠加
│       │   ├── phase_smoother.py          # 阶段平滑：profile 转换约束 + 关键帧回退
│       │   ├── report.py                  # LLM 报告生成：融合评分、降级策略
│       │   ├── providers.py               # AI 供应商管理：多 provider、重试、加密、连通性测试
│       │   ├── analysis_errors.py         # 错误分类与处理
│       │   ├── pipeline_version.py        # 流水线版本号 (v1.1.11)
│       │   ├── vision_vote_config.py      # [新增] 视觉投票配置持久化
│       │   ├── snowball.py                # 长期记忆上下文构建
│       │   ├── memory_suggest.py          # 记忆更新建议
│       │   └── plan.py                    # 训练计划生成
│       └── configs/
│           └── __init__.py
│
│   [旧版目录 - v1.1.0 快照，仅供参考]
│   ├── preprocessing/                     # 旧版：video.py, target_lock.py
│   ├── pose_estimation/                   # 旧版：pose.py
│   ├── action_recognition/                # 旧版：action_profiles.py, phase_smoother.py
│   ├── quality_assessment/                # 旧版：biomechanics.py, vision.py, report.py
│   ├── utils/                             # 旧版：providers.py, analysis_errors.py 等
│   └── pipeline.py                        # 旧版流水线入口
│
├── configs/                               # 配置文件
│   ├── action_profiles.json               # 动作 profile 配置（采样参数、窗口大小）
│   ├── vision_prompt.txt                  # 视觉分析 System Prompt（参考）
│   ├── report_prompt.txt                  # 报告生成 System Prompt（参考）
│   ├── snowball_prompt.txt                # 冰宝角色 System Prompt（参考）
│   └── memory_suggest_prompt.txt          # 记忆建议 System Prompt（参考）
├── weights/                               # 模型权重说明
│   ├── .gitkeep
│   └── WEIGHTS_README.md                  # 权重文件路径、下载源、配置说明
├── tests/                                 # 单元测试
│   ├── test_action_profiles.py
│   ├── test_biomechanics_jump_rotation_estimation.py
│   └── test_phase_smoother.py
├── requirements.txt                       # Python 依赖（含版本号）
├── README.md                              # 本文件
├── error_cases_and_metrics.md             # 错误案例与性能指标分析
└── _rebuild.py                            # 自动重建脚本（从 backend/ 复制最新源码）

注: 标注 [v1.1.x+] 或 [新增] 的文件为该版本引入的新模块。
    src/app/services/ 下的文件为 v1.1.11 最新版本，保持原始 `app.services.*` import 路径。
    旧版目录（src/preprocessing/ 等）为 v1.1.0 快照，可通过 `_rebuild.py` 更新。
```

---

## 4. 模块入口

### 主入口文件
`backend/app/routers/analysis.py` — `process_analysis()` 异步函数

### REST API 调用
```bash
curl -X POST http://localhost:8000/api/analysis/upload \
  -F "file=@video.mp4" \
  -F "action_type=跳跃" \
  -F "action_subtype=单跳"
```

### 关键 API 端点
| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/analysis/upload` | POST | 上传视频，启动异步分析 |
| `/api/analysis/{id}` | GET | 获取分析详情（含所有中间结果） |
| `/api/analysis/{id}/retry` | POST | 从指定阶段重试分析 |
| `/api/analysis/{id}/target-preview` | GET | 获取目标锁定预览 |
| `/api/analysis/{id}/target-lock` | POST | 确认目标锁定（手动选人） |
| `/api/analysis/{id}/pose` | GET | 获取骨骼姿态数据 |
| `/api/analysis/{id}/plan` | POST | 生成训练计划 |
| `/api/analysis/{id}/export` | POST | 导出文本报告 |
| `/api/analysis/compare?id_a=X&id_b=Y` | GET | 对比两次分析 |

### 流水线阶段（可分段重试）
```
extract_frames → pose → biomechanics → vision → report
```

---

## 5. 核心类/函数详解

### 5.1 `video.py` — 视频预处理

#### `extract_motion_sampled_frames()`
- **职责**：运动密度加权抽帧（核心抽帧函数）
- **输入**：video_path, frames_dir, action_type, analysis_profile
- **输出**：(frame_paths[], motion_scores{}, VideoSamplingMetadata)
- **内部流程**：
  1. `detect_video_fps()` — FFprobe 读取源帧率
  2. `detect_action_window()` — 低分辨率缩略图 → 运动密度曲线 → 滑动窗口定位峰值区间
  3. `_extract_thumbnails_in_window()` — 在动作窗口内提取缩略图
  4. `_motion_scores_from_thumbs()` — OpenCV 帧差法计算运动分数
  5. `_select_motion_weighted_indices()` — 按运动强度分配采样配额，强制保护 top-2 峰值 ±1 帧
  6. `_extract_full_frame_at()` — 对选中帧提取 480p 高清版

#### `detect_action_window()`
- **职责**：从运动密度曲线中定位动作发生的时间窗口
- **Profile 特化**：
  - jump: 3 秒窗口，最大运动密度
  - spin: 5 秒窗口，运动密度 - 首尾差
  - spiral: 6 秒窗口，稳定性优先（低运动 + 低波动）
  - step: 8 秒窗口

#### `cut_action_window_clip()`
- **职责**：为 Qwen-VL 视频模式切出 <=10 秒动作窗口短片
- **输入**：video_path, window_start_sec, window_end_sec
- **输出**：mp4 clip path

#### `precheck_video()`
- **职责**：视频上传后预检
- **检查项**：magic bytes、ffprobe 视频流/时长/分辨率、抽样帧亮度方差

#### Profile 采样配置
```python
# 从 configs/action_profiles.json 读取，覆盖内置默认值
DEFAULT_PROFILE_FRAME_RATES = {"jump": 10, "spin": 8, "spiral": 6, "step": 5}
DEFAULT_PROFILE_MAX_FRAMES = {"jump": 32, "spin": 24, "spiral": 16, "step": 20}
DEFAULT_PROFILE_WINDOW_SIZES = {"jump": 3.0, "spin": 5.0, "step": 8.0, "spiral": 6.0}
```

---

### 5.2 `target_lock.py` — 目标锁定

#### `build_target_preview()`
- **职责**：从帧列表生成目标候选 bbox 预览
- **自动锁定阈值**：`TARGET_LOCK_AUTO_THRESHOLD = 0.72`
- **最低可见阈值**：`TARGET_PERSON_MIN_CONFIDENCE = 0.15`

#### `validate_manual_bbox()`
- **职责**：校验前端手动框选的 bbox
- **约束**：归一化 0-1、最小宽高 0.05、不超出画面

---

### 5.3 `bbox_tracker.py` — 逐帧目标跟踪

#### `track_bbox()`
- **职责**：使用 OpenCV CSRT 在抽样帧序列中跟踪主目标 bbox
- **输入**：frame_paths[], initial_bbox
- **输出**：(bbox_per_frame[], quality_flags[])
- **降级策略**：跟踪失败时使用上一帧速度线性外推

---

### 5.4 `smoothing.py` — 姿态关键点平滑

#### `smooth_keypoint_sequence()`
- **职责**：对逐帧 MediaPipe 关键点执行 One-Euro 去抖 + 短时遮挡插值
- **算法**：One-Euro Filter (min_cutoff=1.0, beta=0.05)
- **设计说明**：静止落冰阶段强平滑，高速旋转/腾空阶段随速度放宽截止频率

#### `OneEuroFilter`
- **参数**：min_cutoff=1.0, beta=0.05, d_cutoff=1.0
- **特性**：速度自适应低通滤波，动作越快保留越多高频变化

---

### 5.5 `pose.py` — 骨骼姿态提取

#### `extract_pose()`
- **职责**：从抽样帧中提取目标选手骨骼关键点（主入口）
- **模型**：MediaPipe Pose Landmarker
  - 架构：BlazePose（轻量级 CNN）
  - 输入：RGB 图像（任意分辨率）
  - 输出：33 个关键点 (x, y, z, visibility)，归一化坐标 0~1
- **多人模式**：通过 `MEDIAPIPE_POSE_TASK_PATH` 环境变量启用 Tasks API
- **单人模式**（fallback）：使用 `mp.solutions.pose.Pose`，结合 bbox 裁剪
- **候选评分函数** `_score_candidate()`：
  - IoU 连续性 (34%) + 中心距离 (22%) + 运动重叠 (16%) + 可见性 (14%) + 尺度一致性 (14%)

---

### 5.6 `action_profiles.py` — 动作 Profile 推断

#### `infer_analysis_profile()`
- **职责**：推断分析 profile（核心决策函数）
- **输入**：action_type, action_subtype, pose_data, frame_motion_scores
- **输出**：(profile_name, evidence_dict)
- **决策逻辑**：
  1. 用户输入 → `infer_profile_hint()` → 初始 profile 候选
  2. 几何验证：CoM 垂直范围、人体高度归一化、腾空帧检测、髋部旋转信号
  3. 跳跃门控：`relative_vertical >= 0.12 AND max_motion >= 0.06`
  4. 螺旋线门控：`vertical_range <= 0.06 AND avg_motion <= 0.09`
  5. 旋转门控：`rotation_signal >= 0.15`

#### `JUMP_CHARACTERISTICS`
- 6 种跳跃的特征知识库（Axel/Lutz/Flip/Loop/Salchow/Toe Loop）
- 包含：起跳刃、方向、识别要点、圈数说明

---

### 5.7 `jump_features.py` — 跳跃种类几何证据

#### `compute_jump_evidence()`
- **职责**：从姿态序列和 T/A/L 关键帧中提取跳跃判别的弱几何线索
- **输入**：pose_data, key_frames, effective_fps
- **输出**：jump_subtype_evidence 字典
- **证据维度**：
  - `takeoff_foot` — 起跳脚（左/右）
  - `toe_pick_pulse` — 点冰脉冲检测
  - `feet_together_at_takeoff` — 起跳时双脚并拢（Loop 特征）
  - `free_leg_swing_amplitude` — 自由腿摆动幅度（Salchow 特征）
  - `approach_direction` — 进近方向（forward=Axel 特征）
  - `pre_takeoff_edge_score` — 起跳前刃型评分（0=外刃/Lutz, 1=内刃/Flip）

---

### 5.8 `biomechanics.py` — 生物力学计算

#### `analyze_biomechanics()`
- **职责**：从骨骼姿态数据计算全部生物力学指标（主入口）
- **输入**：pose_data, action_type, analysis_profile, effective_fps
- **输出**：bio_data dict

#### T/A/L 关键帧检测逻辑
- **T（起跳）**：CoM Y 坐标开始上升的帧（Y 由大变小的转折点）
- **A（顶点 Apex）**：CoM Y 坐标最小值的帧（最高点）
- **L（落冰）**：CoM Y 坐标迅速下降后的稳定帧

#### 跳跃指标估算公式
```
滞空时间(秒) = 腾空帧数 / FPS
跳跃高度(cm) = 0.5 × 9.8 × (滞空时间/2)² × 100
起跳速度(m/s) = √(2 × 9.8 × 高度/100)
转速(圈/秒) = 肩膀连线旋转角度累积 / (2π × 持续时间)
跳跃周数 = 转速 × 滞空时间
```

#### `sanitize_biomechanics_data()`
- **职责**：校验并修正异常生物力学指标
- **阈值**：air_time > 1.5s, height > 120cm, takeoff_speed > 6.5m/s, rotation > 6.0rps

---

### 5.9 `bio_context.py` — 生物力学上下文构建

#### `build_frame_bio_context()`
- **职责**：将 bio_data 重排为逐帧测量字典，用于 Path B prompt 注入
- **输出示例**：`{"frame_0001": {"left_knee_angle": 145.2, "trunk_tilt_deg": 8.4}}`

#### `summarize_jump_metrics()`
- **职责**：将 jump_metrics 压缩为单行 ASCII grounding 文本
- **输出示例**：`"AirTime=0.55s | Height=37.1cm | VTakeoff=2.70m/s | Rot=4.80rps"`

---

### 5.10 `vision.py` — LLM 视觉分析（兼容层）

#### `analyze_frames()`
- **职责**：调用多模态 LLM 进行逐帧视觉分析
- **模式**：
  - `mode="video"`: 优先使用原生视频模式（Qwen-VL / Doubao），失败回退到帧模式
  - `mode="frames"`: 逐帧图片分析
- **多 provider 投票**：Qwen + Doubao 各 1 票并发，合并结果
- **帧模式自一致投票**：默认 n_votes=2，合并 phase 多数票、observations 并集

#### `normalize_vision_payload()`
- **职责**：归一化 LLM 返回的 JSON，补全缺失帧，校验 phase 值

#### `_merge_vision_results()`
- **职责**：合并多个归一化视觉结果
- **策略**：phase 多数票投票、observations/issues/positives 并集去重、confidence 均值

---

### 5.11 `vision_path_a.py` — Path A 纯视觉分析

#### `analyze_path_a()`
- **职责**：纯视觉判断，不引入任何骨架或测量数据
- **角色设定**：10 年执教经验花滑专项教练，场边肉眼观察视角
- **输出**：frame_analysis + pure_vision_subscores + action_phase_summary

---

### 5.12 `vision_path_b.py` — Path B 量化 grounding 分析

#### `analyze_path_b()`
- **职责**：骨架叠加帧 + 生物力学数值综合判断
- **角色设定**：花滑生物力学分析专家
- **输入增强**：每帧附带 LKnee/RKnee/TrunkTilt/ArmSym 测量值
- **输出**：frame_analysis + subscores + top_issues（必须引用具体测量数值）

#### `sample_frames_path_b()`
- **职责**：优先采样关键帧 ± 上下文窗口，fallback 到均匀采样

---

### 5.13 `vision_dual.py` — 双路分析编排

#### `analyze_frames_dual()`
- **职责**：并行运行 Path A + Path B，交叉验证
- **超时**：总超时 150 秒，超时后仅用 Path A
- **输出**：DualPathResult

---

### 5.14 `cross_validator.py` — 交叉验证

#### `cross_validate()`
- **职责**：逐维度对比 Path A 和 Path B 的结果
- **维度**：detected_phases (Jaccard) + 5 个 subscores
- **客观维度**（rotation_axis, core_stability）：±6 分内为 agree
- **主观维度**（其余）：±10 分内为 agree
- **骨架可靠性信号**：
  - `reliable`：无 major_conflict
  - `uncertain`：1-2 项 major_conflict
  - `likely_wrong`：≥2 项客观维度 major_conflict

#### `compute_blend_weights()`
- **职责**：根据验证结果计算融合权重 (a_weight, b_weight)
- **策略**：reliable→B:65%, uncertain→50:50%, likely_wrong→A:75%

---

### 5.15 `frame_annotator.py` — 骨架帧标注

#### `annotate_frames_batch()`
- **职责**：在原始帧上叠加 MediaPipe 骨架线条 + 关键点 + 角度标签
- **用途**：生成 Path B 使用的标注帧

---

### 5.16 `phase_smoother.py` — 阶段平滑

#### `smooth_phases()`
- **职责**：验证并修正逐帧阶段预测，确保符合合法转换规则
- **转换规则示例**（jump）：准备→起跳→腾空→落冰→滑出（不可回退）
- **关键帧回退**：投票分歧且帧位于 biomechanics T/A/L 关键帧 ±1 帧时，强制回退到起跳/腾空/落冰

---

### 5.17 `report.py` — LLM 报告生成

#### `generate_report()`
- **职责**：调用文本 LLM 生成结构化训练报告
- **模型**：DeepSeek-V3（默认）
- **输出**：report{summary, issues, improvements, training_focus, subscores, data_quality}
- **重试**：最多 3 次 JSON 解析重试

#### `fuse_subscores()`
- **职责**：AI(40%) + 生物力学(60%) 融合评分
- **权重动态调整**：quality_flags 越多，生物力学权重越高（0.20~0.60）

#### `calculate_force_score()`
- **职责**：从 subscores 加权均值计算综合发力评分
- **权重**：起跳发力(25%) + 旋转轴心(25%) + 手臂配合(15%) + 落冰缓冲(25%) + 核心稳定(10%)

---

### 5.18 `providers.py` — AI 供应商管理

#### 支持的供应商
| Slot | 默认模型 | API 端点 |
|------|---------|---------|
| vision | qwen3.6-plus | https://dashscope.aliyuncs.com/compatible-mode/v1 |
| vision (视频) | qwen-vl-max-latest | DashScope MultiModalConversation |
| vision (豆包) | doubao-seed-2-0-250615 | https://ark.cn-beijing.volces.com/api/v3 |
| report | deepseek-chat | https://api.deepseek.com/v1 |

#### `request_text_completion()`
- **职责**：统一的文本补全 API 调用
- **重试**：5xx/429/网络超时按 1s/2s/4s 指数退避
- **支持**：OpenAI 兼容 + Claude 兼容

#### `request_dashscope_video_completion()`
- **职责**：Qwen-VL 原生视频理解（DashScope SDK 本地 file:// 上传）
- **成本控制**：每日成本上限（默认 30 元）

#### `request_doubao_vision_completion()`
- **职责**：Doubao 视频理解（火山方舟 OpenAI 兼容入口）
- **限制**：单文件 <=50MB、时长 <=60s

---

## 6. 模型推理调用链

以一次完整的跳跃（3Lz，三周勾手跳）分析为例：

```
1. 视频到达 → video.py
   ├─ ffprobe 检测源帧率：240fps（慢动作）
   ├─ 视频预检：magic bytes ✓ / 视频流 ✓ / 时长 ✓ / 分辨率 ✓ / 黑帧 ✓
   ├─ 缩略图提取（160x90, 10fps）→ 30 张
   ├─ OpenCV 帧差法 → 运动密度曲线 [0.02, 0.05, ..., 0.95, 0.88, ...]
   ├─ 滑动窗口（3秒）→ 定位峰值区间：8.2s ~ 11.5s
   ├─ 运动密度加权采样 32 帧（保护 top-2 峰值 ±1 帧）
   └─ 逐帧提取 480p 高清 → frame_0001.jpg ~ frame_0032.jpg

2. 目标锁定 → target_lock.py
   ├─ 生成 3 个候选 bbox（center/left/right）
   ├─ center 置信度 0.78 > 0.72 → 自动锁定
   └─ 输出 selected_bbox: {x:0.28, y:0.08, w:0.44, h:0.84}

2.5. 逐帧跟踪 → bbox_tracker.py
   ├─ CSRT 跟踪器初始化
   ├─ 逐帧更新 bbox
   └─ 输出 bbox_per_frame[]

3. 骨骼提取 → pose.py
   ├─ MediaPipe Tasks API（多人模式，4人）
   ├─ 逐帧检测 → 每帧最多 4 个骨骼候选
   ├─ 候选评分（IoU + 连续性 + 运动重叠）→ 选最佳
   ├─ One-Euro Filter 时序平滑
   └─ 输出 32 帧 × 33 关键点序列

4. Profile 推断 → action_profiles.py + jump_features.py
   ├─ 用户输入 "跳跃" + "单跳" → hint = "jump"
   ├─ CoM 垂直范围 = 0.15（归一化后 0.19 > 0.12）
   ├─ 最大运动分数 = 0.82 > 0.06
   ├─ 腾空帧 = 4 帧
   ├─ 结论：profile = "jump", jump_gate_passed = True
   ├─ 跳跃证据：toe_pick_pulse=True, takeoff_foot=left, edge_score=0.72(内刃)
   └─ 输出 jump_subtype_evidence

5. 生物力学 → biomechanics.py
   ├─ 膝关节角度序列：[170°, 155°, 120°, 95°, 110°, 145°, 165°]
   ├─ 躯干倾斜：平均 6.2°
   ├─ CoM 轨迹：垂直范围 0.15
   ├─ T/A/L 关键帧：T=frame_0005, A=frame_0011, L=frame_0016
   ├─ 滞空时间：(16-5)/10 = 1.1s（慢动作修正后）
   ├─ 跳跃高度：0.5 × 9.8 × (1.1/2)² × 100 = 29.6cm
   ├─ 转速：4.8 圈/秒
   ├─ 估算周数：4.8 × 1.1 = 5.28 → "三圈跳"（阈值 2.8~3.8）
   └─ bio_subscores: {takeoff:72, rotation:68, arm:75, landing:70, core:73}

6. 双路视觉分析 → vision_dual.py
   ├─ Path A: 32 帧原始图 + 纯视觉 prompt → Qwen 3.6 Plus
   │   └─ 返回：frame_analysis + pure_vision_subscores
   ├─ Path B: 骨架叠加帧（关键帧 ±2 上下文）+ bio 数值 → 另一 provider
   │   └─ 返回：frame_analysis + subscores + top_issues
   ├─ 交叉验证：
   │   ├─ detected_phases Jaccard = 0.85 → agree
   │   ├─ rotation_axis: A=70, B=68, diff=2 → agree
   │   ├─ landing_absorption: A=65, B=72, diff=7 → minor_conflict
   │   └─ overall_agreement = 0.82, skeleton = reliable, blend = (0.35, 0.65)
   └─ 输出 DualPathResult

7. 报告生成 → report.py
   ├─ vision_structured + bio_data + dual_path_meta → DeepSeek-V3
   ├─ 返回 JSON：
   │   summary: "三周勾手跳整体完成度较好，起跳发力充分..."
   │   issues: [{category:"落冰缓冲", description:"落冰时膝盖弯曲不足", severity:"medium"}]
   │   improvements: [{target:"落冰缓冲", action:"练习软膝盖停住"}]
   │   subscores: {takeoff:75, rotation:70, arm:73, landing:65, core:72}
   └─ force_score = 75×0.25 + 70×0.25 + 73×0.15 + 65×0.25 + 72×0.10 = 70.7 → 71

8. 阶段平滑 → phase_smoother.py
   └─ 验证 phase 序列合法性，修正异常转换，关键帧回退
```

---

## 7. 模型权重说明

详见 `weights/WEIGHTS_README.md`。

### 使用的模型

| 模型 | 类型 | 来源 | 用途 |
|------|------|------|------|
| MediaPipe Pose Landmarker | 本地 CNN | pip 包内置 | 33 关键点骨骼提取 |
| Qwen 3.6 Plus | 云端多模态 LLM | 阿里云 DashScope | 逐帧视觉分析 (Path A) |
| Qwen-VL-Max | 云端多模态 LLM | 阿里云 DashScope | 原生视频理解 |
| Doubao Seed 2.0 | 云端多模态 LLM | 火山方舟 | 视频理解备选 / Path B |
| DeepSeek-V3 | 云端文本 LLM | DeepSeek | 结构化报告生成 |

### 环境变量配置
```bash
# Vision API Key（至少配置一个）
QWEN_API_KEY=sk-xxxxxxxx
# 或
DASHSCOPE_API_KEY=sk-xxxxxxxx

# Report API Key（至少配置一个）
DEEPSEEK_API_KEY=sk-xxxxxxxx

# API Key 加密密钥（必填）
SECRET_KEY=your-32-char-random-string

# 可选：多视觉模型投票
VISION_PROVIDERS=qwen,doubao

# 可选：多人姿态估计
MEDIAPIPE_POSE_TASK_PATH=/path/to/pose_landmarker.task
POSE_NUM_POSES=4

# 可选：视觉模型自定义
QWEN_VISION_MODEL=qwen-vl-max-latest

# 可选：每日成本限制
QWEN_VISION_DAILY_COST_LIMIT_CNY=30
```
