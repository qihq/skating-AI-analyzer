# Skating Analyzer 视频分析流程

本文档描述当前 `v5.2.303` 管线从上传视频到生成训练报告的实际数据流。核心原则是：所有时间戳都尽量保持源视频绝对时间；视频 AI 负责语义时序，运动/骨架/目标跟踪负责可验证证据，报告阶段只做融合与保守表达。

## 总览

```text
POST /api/analysis/upload
  -> 保存源视频，写入 Analysis
  -> 视频预检，解析 AI 输入范围
  -> 运动密度采样和动作窗口元数据
  -> 目标锁定预览；必要时等待人工选人
  -> YOLO/ByteTrack 人体跟踪
  -> MediaPipe 姿态提取和平滑
  -> 生物力学、动作 profile、跳跃特征和关键帧候选
  -> 视频语义 AI，携带用户备注和重试上下文
  -> 语义关键帧仲裁、可见性检查、重试、修复与 FFmpeg 抽帧
  -> Path A / Path B 双路径视觉分析
  -> LLM 报告、分数融合、训练计划、档案、调试输出
```

可重试阶段：

```text
extract_frames -> pose -> biomechanics -> vision -> report
```

视频语义、语义关键帧、Path A/B 都是这些阶段里的子流程，而不是独立状态。

## Stage 1：上传、预检和 AI 输入范围

入口：`POST /api/analysis/upload`

表单字段：

- `file`: `.mp4` / `.mov` / `.avi`
- `action_type`: `跳跃` / `旋转` / `步法` / `自由滑`
- `action_subtype`: 可选；未知时可以不传或使用 `未指定`
- `skill_node_id` / `skill_category`: 可选
- `skater_id`: 可选
- `session_id`: 可选
- `note`: 可选，会进入视频语义 prompt 和报告上下文
- `manual_action_window_start_sec` / `manual_action_window_end_sec`: 可选，必须成对出现

预检内容：

- 文件大小默认上限 `MAX_UPLOAD_SIZE_MB=500`
- magic bytes 与后缀检查
- `ffprobe` 视频流、时长、分辨率检查
- 最小时长 `0.5s`
- 最小分辨率 `320x180`
- 抽样帧黑屏/空白检测

AI 输入范围由 `build_video_input_window()` 生成：

| 模式 | 触发条件 | 说明 |
|---|---|---|
| `manual_window` | 用户提供起止秒数 | 优先使用用户指定片段 |
| `full_context` | 无手动片段且可完整输入 | 默认尽量保留源视频上下文 |
| `system_truncated` | 受模型或 clip 限制必须截断 | 会写入 `input_window_truncated` 与原因 |

这些字段会存入 `frame_motion_scores.input_window`，并在报告页和 Debug 页展示。

## Stage 2：运动采样与动作窗口

主要文件：`backend/app/services/video.py`

流程：

1. 以 `ACTION_WINDOW_DETECTION_FPS=2` 生成缩略图。
2. 计算相邻帧差异，形成 motion curve。
3. 按动作 profile 选择窗口。
4. 保护高运动峰值邻域，再按时间段和运动权重抽帧。
5. 高 FPS 视频按 `source_fps / 30` 处理慢动作时间折算。

默认 profile 配置：

| Profile | 窗口 | 抽帧 FPS | 最大帧数 |
|---|---:|---:|---:|
| `jump` | 3s | 16 | 32 |
| `spin` | 5s | 10 | 24 |
| `spiral` | 6s | 8 | 16 |
| `step` | 8s | 6 | 20 |

自由滑和混合动作会更依赖完整上下文与后续 profile 推断。

输出：

- `frame_0001.jpg` 等 sampled frames
- `frame_motion_scores`
- `VideoSamplingMetadata`
- action-window diagnostics

## Stage 3：目标锁定

主要文件：

- `backend/app/services/target_lock.py`
- `backend/app/services/person_tracker.py`
- `frontend/src/pages/TargetSelectionPage.tsx`

目标：

- 从多人或复杂背景里确定目标学员。
- 避免错人骨架污染报告。

行为：

- 自动生成候选 bbox 和预览帧。
- 高置信、低竞争风险时自动锁定。
- 多人、同锚点竞争、背景小人、前景遮挡、缩放目标等风险会进入人工选择。
- 手动目标锁定是 identity-authoritative：后续 tracker、pose、Path B 都必须服从它。
- 如果手动锁定缺少 tracker 诊断或身份支持，管线会 fail closed，而不是用错误 skeleton 回填。

## Stage 4：人体跟踪与姿态提取

主要文件：

- `backend/app/services/person_tracker.py`
- `backend/app/services/pose.py`
- `backend/app/services/phase_smoother.py`

跟踪：

- 支持 YOLO person detection 与 ByteTrack 风格连续性。
- 支持 target-lock support anchor、同帧 detector relock、长丢失恢复、前景尺度爆炸拒绝等诊断。
- tracker 状态会写入 frame metadata，影响姿态 crop、T/A/L 置信和报告质量。

姿态：

- MediaPipe 33 点关键点。
- 可配置 `MEDIAPIPE_POSE_TASK_PATH` 启用 task 模型与多姿态候选。
- 支持 regular crop、tracker-guided crop、fallback crop。
- 对低可见性、错误 relock、前景大人、tiny target 等情况降级或 blank pose。

## Stage 5：Profile、动作证据和生物力学

主要文件：

- `backend/app/services/action_profiles.py`
- `backend/app/services/biomechanics.py`
- `backend/app/services/keyframe_candidates.py`

Profile：

- `jump`
- `spin`
- `spiral`
- `step`

输入信号：

- 用户动作大类/子类
- 技能分类
- 运动密度
- 姿态质心轨迹
- 历史同视频语义结果
- video AI 动作家族

生物力学输出：

- 膝角
- 躯干倾角
- 手臂协调
- 质心轨迹
- 跳跃滞空/高度/起跳速度
- 肩线 unwrap 旋转速度和估算周数
- `bio_subscores`
- T/A/L 或非跳跃阶段候选
- `quality_flags`

## Stage 6：视频语义 AI

主要文件：

- `backend/app/services/semantic_keyframe_pipeline.py`
- `backend/app/services/video_temporal.py`
- `backend/app/services/providers.py`

视频 AI 由 `start_video_temporal_task()` 统一启动。它会：

1. 根据 `VideoInputWindow` 切出 AI clip。
2. 记录 clip path、offset、duration、source duration、input window payload。
3. 调用 `analyze_video_temporal()`。
4. 把用户备注、动作信息、重试上下文传入 prompt。

AI clip 默认参数：

- `ACTION_AI_CLIP_SIZE=640x360`
- `ACTION_AI_CLIP_FPS=15`
- `ACTION_AI_CLIP_CRF=30`
- `ACTION_AI_CLIP_MAX_MB=40`

视频 AI 输出 `video_temporal_v1`：

- `action_confirmation`
- `phase_segments`
- `key_moments`
- `macro_assessment`
- `overall_impression`
- `camera_view`
- `data_quality_hint`
- `fallback_recommendation`
- `quality_flags`

等待上限：`VIDEO_TEMPORAL_WAIT_TIMEOUT_SECONDS=210`。

## Stage 7：语义关键帧仲裁、重试和抽取

主要文件：`backend/app/services/semantic_keyframe_pipeline.py`

输入：

- `video_temporal_v1`
- motion records
- skeleton/keyframe candidates
- biomechanics quality flags
- tracker diagnostics
- AI input window metadata

仲裁目标：

- 选出可靠的 T/A/L 或非跳跃阶段关键帧。
- 在不可靠时保守回退到 sampled frames 或 keyframe candidates。

主要检查：

- 阶段顺序和完整性
- semantic confidence
- phase segment bounds
- motion cluster 支持
- skeleton candidate 支持
- foreground occlusion
- tiny target / low visibility
- tracker final loss
- reused same-video semantic stability
- full-context motion conflict

重试：

- `_should_retry_video_temporal()` 根据 flags、profile mismatch、motion/skeleton conflict 等决定是否重试。
- retry prompt 会携带冲突原因和 candidate anchors。
- retry 结果只有在分数更高且不触发拒绝 flags 时才替换原结果。
- 某些场景支持 partial merge、motion-cluster fallback、visual T/A/L promotion。

抽帧：

- 可靠 semantic records 用 `extract_precise_frames_at_timestamps()` 生成 `semantic_0001.jpg`。
- refinement 后不可靠则回退 sampled frames。
- partial semantic frames 可用于 debug，不一定进入正式视觉分析。

## Stage 8：双路径视觉分析

主要文件：

- `backend/app/services/vision_dual.py`
- `backend/app/services/vision_path_a.py`
- `backend/app/services/vision_path_b.py`
- `backend/app/services/vision_video_context.py`

Path A：

- 纯视觉 / video-aware 路径。
- 优先使用语义帧；必要时使用 AI input clip。
- 请求 JSON object，支持噪声 JSON 抽取和低温 JSON-only 修复。
- 输出 frame analysis、pure vision subscores、问题和优点。

Path B：

- 使用骨架叠加帧、生物力学、keyframe context。
- 作为 grounding 和报告证据来源。
- 失败不阻塞主流程。

融合：

- `vision_structured` 以 Path A 标准化结果为主。
- `vision_path_a` / `vision_path_b` 原始结果都会存储。
- cross-validation 比较阶段、评分、骨架可靠性和冲突。
- 当 Path A 或报告输出过泛化时，报告会用 Path B/top issues 和动作专项 drills 修补。

## Stage 9：报告、评分和训练计划

主要文件：

- `backend/app/services/report.py`
- `backend/app/services/plan.py`
- `backend/app/services/auto_eval.py`

报告输入：

- Path A / Path B
- biomechanics
- resolved keyframes
- video temporal summary
- cross-validation
- auto-eval
- skater context
- user note

报告输出：

- `summary`
- `issues`
- `improvements`
- `training_focus`
- `subscores`
- `data_quality`
- `user_note`
- `score_breakdown`

评分：

- Force Score 使用五项子分加权。
- 生物力学质量 flags 会影响 bio/AI 融合权重。
- 儿童/初学者在无高危问题且数据质量可接受时有保守分数下限。

训练计划：

- 优先调用 AI。
- AI 不可用时生成 safe fallback plan。
- 计划会记录来源，前端明确标注 fallback。

## Stage 10：持久化与调试

存储字段包括：

- `analysis.frame_motion_scores`
- `analysis.pose_data`
- `analysis.bio_data`
- `analysis.vision_structured`
- `analysis.vision_path_a`
- `analysis.vision_path_b`
- `analysis.cross_validation`
- `analysis.report`
- `analysis.force_score`
- `analysis.processing_logs`
- `analysis.processing_timings`
- `analysis.pipeline_version`

调试入口：

- `/report/:id/pose-debug`
- `/debug`
- `scripts/batch_api_analyze_videos.py`
- `scripts/skate_video_iteration_diagnostics.py`
- `scripts/summarize_api_batch_diagnostics.py`

Debug 页面展示：

- AI input window
- semantic frames / partial semantic frames
- target lock
- tracker diagnostics
- video temporal payload
- resolved keyframes
- quality flags
- provider logs
- timings

## Provider Slots

| Slot | 用途 |
|---|---|
| `report` | 文本报告 |
| `vision` | 主视觉 fallback 和投票池 |
| `vision_path_a` | Path A 纯视觉 / video-aware |
| `vision_path_b` | Path B 骨架量化 grounding |

后端启动不再自动写 provider rows。请在 `/settings/api` 创建模型实例并激活 slot。

## 常见失败与降级

| 场景 | 行为 |
|---|---|
| 视频预检失败 | 分析失败并返回用户可读错误 |
| 目标不确定 | 进入 `awaiting_target_selection` |
| 手动目标缺少身份支持 | fail closed |
| 视频 AI 超时/解析失败 | sampled frames 或 skeleton fallback 继续 |
| semantic frames 不可靠 | 回退 sampled frames |
| Path A 失败 | 尝试修复 JSON；失败后报告更多依赖 Path B/fallback |
| Path B 失败 | 记录错误，主流程继续 |
| 报告模型失败 | 生成 biomechanics fallback report |

## 相关文件索引

| 文件 | 职责 |
|---|---|
| `backend/app/routers/analysis.py` | 主编排、状态流转、重试、存储、导出 |
| `backend/app/services/video.py` | 预检、输入窗口、运动采样、clip、FFmpeg 抽帧 |
| `backend/app/services/semantic_keyframe_pipeline.py` | 视频语义任务、重试、语义关键帧仲裁 |
| `backend/app/services/video_temporal.py` | 视频语义 payload、resolver 辅助函数 |
| `backend/app/services/person_tracker.py` | YOLO/ByteTrack 与身份诊断 |
| `backend/app/services/target_lock.py` | 目标候选、自动锁定、人工选择 |
| `backend/app/services/pose.py` | MediaPipe 姿态 |
| `backend/app/services/biomechanics.py` | 生物力学和评分证据 |
| `backend/app/services/vision_path_a.py` | Path A |
| `backend/app/services/vision_path_b.py` | Path B |
| `backend/app/services/vision_dual.py` | 双路径协调 |
| `backend/app/services/report.py` | 报告、分数融合和证据修补 |
| `frontend/src/pages/ReviewPage.tsx` | 上传、动作上下文、手动输入窗口 |
| `frontend/src/pages/ReportPage.tsx` | 报告、分享图、重试、调试入口 |
| `frontend/src/pages/DebugPage.tsx` | debug-run 与原始诊断查看 |
