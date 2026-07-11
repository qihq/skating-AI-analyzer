# 高准确率人物追踪与动作分析迭代设计

状态：已确认，待实施计划  
日期：2026-07-11  
适用系统：Skating Analyzer v5.2.318 及后续版本  
部署环境：Synology DS918+ Docker 负责本地编排，MiMo 2.5 云端 API 负责视频语义分析  
典型输入：30 秒以内、微信压缩、约 720p、手机跟拍、平移/变焦/抖动、多人物同框  
产品约束：每段视频允许用户在清晰帧手动框选目标；准确率优先；允许增加 API 调用、处理时间和成本

## 1. 文档目的

本文是可交给其他实现模型逐项执行的工程规格。它不是概念路线图，而是定义：

- 系统边界和不可破坏的原则；
- 人物身份锚点、双向追踪、冲突检测和人工复核方案；
- 动作候选、MiMo 分层调用、专项识别、关键帧和周数方案；
- 数据结构、模块边界、状态机、缓存和降级行为；
- Golden 数据集、指标、A/B 门槛和验收方式；
- Phase 0-8 的顺序、依赖、交付物和禁止事项。

本文不授权一次性重写现有分析管线。所有算法变化必须可开关、可回滚、可与旧路径并行评测。

## 2. 现状与根因

当前系统已经具备视频预处理、YOLO/ByteTrack 人物检测与关联、手动目标框、MediaPipe 姿态、动作 profile、关键帧候选、双路径视觉分析、MiMo 视频时序分析、质量标志、Golden 标注入口和离线评测脚本。

主要现有模块：

| 职责 | 当前模块 | 后续处理原则 |
|---|---|---|
| 视频探测、抽帧、动作窗口、精确帧提取 | `backend/app/services/video.py` | 扩展 PTS 映射和代理资产，不破坏旧接口 |
| 初始人物定位 | `backend/app/services/target_lock.py` | 人工锚点优先；旧自动定位作为辅助和兼容路径 |
| YOLO/ByteTrack、重锁与诊断 | `backend/app/services/person_tracker.py` | 新双向协调层应独立；禁止继续无限堆叠特例 |
| 姿态提取 | `backend/app/services/pose.py` | 消费融合后的目标轨迹，并保留质量状态 |
| 动作 profile | `backend/app/services/action_profiles.py` | 降为候选证据，不能单独决定最终类别 |
| 关键帧候选 | `backend/app/services/keyframe_candidates.py` | 作为几何候选源；增加原始帧局部回查 |
| 视频时序解析 | `backend/app/services/video_temporal.py` | 拆分为边界、类别、专项、关键帧调用 |
| 双路径视觉融合 | `backend/app/services/vision_dual.py`、`vision_fusion.py` | 保留兼容；最终改为消费结构化证据 |
| 自动质量评估 | `backend/app/services/auto_eval.py` | 扩展身份、覆盖率、拒识率、动作指标 |
| Golden 标注和清单 | `backend/app/routers/debug.py` | 扩展 schema、可观察性和集合划分 |
| 离线真值评测 | `backend/scripts/eval_against_gt.py` | 从当前指标扩展为完整分层评测 |

现有误差具有明确的级联关系：

```text
人物锁错/换人
  -> 姿态属于错误人物或姿态缺失
  -> 动作窗口偏移
  -> 动作大类/细类错误
  -> T/A/L 和周数错误
  -> 报告以高置信语言放大错误
```

因此实施顺序必须是：先评测，再时间轴，再身份追踪，再动作召回和分类，最后关键帧、周数和报告。禁止倒序优化报告文案来掩盖上游错误。

当前仓库中未发现实际 `data/uploads/_debug/golden_manifest.json` 或 `golden_label.json`。已有文档中的部分准确率是代码推测，并非真实样本统计。任何实现开始前必须先完成 Phase 0。

## 3. 总体设计

### 3.1 计算职责

群晖执行：

- `ffprobe`、FFmpeg 时间轴标准化和资产生成；
- 低并发轻量人体检测；
- 稀疏光流或 ORB 相机运动估计；
- 轨迹打分、双向融合、状态机和质量校验；
- 裁剪、标注、缓存、API 编排和结果持久化。

MiMo 2.5 执行：

- 全片动作候选语义扫描；
- 动作边界复核；
- 动作大类识别；
- 跳跃、旋转、步法、燕式等专项识别；
- T/A/L 或专项阶段的独立复核；
- 基于已确认结构化证据生成报告。

MiMo 不得单独决定人物身份。本地规则也不得在证据不足时强行决定动作名称。

### 3.2 主流程

```text
视频上传与质检
  -> 用户从候选清晰帧中框选目标人物
  -> CFR 追踪代理和原始 PTS 映射
  -> 从锚点前向追踪 + 后向追踪
  -> 身份一致性与双向冲突校验
  -> 必要时请求局部补充锚点
  -> 生成稳定人物裁剪和带框全景视频
  -> 多源动作候选召回
  -> MiMo 动作边界复核
  -> MiMo 大类和专项分类
  -> 原始帧局部回查 T/A/L 与周数
  -> 多证据融合和置信度校准
  -> 结构化结果
  -> 报告生成
```

### 3.3 失败传播规则

- 身份冲突覆盖动作核心区间：动作不得进入 `confirmed`。
- T 或 L 使用插值轨迹：周数和不足周不得进入高置信。
- 冰刀不可见：Lutz/Flip 不得输出高置信唯一结论。
- 两次独立 MiMo 复核冲突：最终状态必须是 `conflicted` 或 `uncertain`。
- 姿态关键点大面积缺失：几何证据只能作为弱证据。
- 上游阶段失败时，保留已经完成的结构化结果，不得生成伪造默认值。

## 4. 视频时间轴和资产

### 4.1 为什么先标准化

微信视频可能包含可变帧率、旋转元数据、重复帧、非整数帧率和重新编码时间偏移。追踪代理可以是 CFR，但最终时间戳必须基于原视频 PTS。只依赖 `frame_index / fps` 会在关键帧和 30 秒视频尾部累积误差。

### 4.2 VideoAsset 数据契约

```json
{
  "schema_version": "video_asset.v1",
  "asset_id": "asset_uuid",
  "analysis_id": "analysis_uuid",
  "kind": "source|tracking_proxy|target_crop|annotated_overview|action_clip|slow_action_clip",
  "source_sha256": "...",
  "path": "...",
  "duration_sec": 18.47,
  "width": 1280,
  "height": 720,
  "average_fps": 29.97,
  "variable_frame_rate": true,
  "rotation_applied_degrees": 90,
  "mirrored": false,
  "encoding_profile": "tracking-cfr-v1",
  "depends_on": ["source_asset_id", "track_revision"],
  "created_at": "2026-07-11T10:00:00Z"
}
```

### 4.3 时间映射

每个代理帧必须保存：

```json
{
  "proxy_frame_index": 101,
  "proxy_timestamp_sec": 6.733333,
  "source_timestamp_sec": 6.741207,
  "source_frame_index_hint": 202,
  "mapping_error_sec": 0.007874,
  "duplicate_source_frame": false
}
```

要求：

1. 用 `ffprobe` 读取 stream、frame rate、time base、duration 和 rotation。
2. 自动应用旋转，所有 bbox 统一到已旋转的显示坐标。
3. 追踪代理默认 12-15 fps，长边不低于 960；困难区间可局部提升到 20-25 fps。
4. 跳跃局部视频默认 15-25 fps；同时生成正常播放和 0.25x/0.5x 慢放。
5. 慢放只改变帧显示时长，不进行 AI 插帧。
6. 最终 T/A/L 从原始 PTS 邻域精确提取，不能直接使用代理帧时间。
7. 调试资产烧录稳定时间码，模型返回时间戳必须在输入区间内。

### 4.4 视频质检

保存但不要自动修饰掉以下问题：

- 模糊、重复帧、强压缩、欠曝/过曝；
- 突然平移、俯仰、变焦；
- 目标人物过小、出画或被遮挡；
- VFR、旋转和镜像状态；
- 冰面和冰刀可见性。

质检结果进入后续权重和置信度上限，不能只显示给日志。

## 5. 人工身份锚点

### 5.1 候选帧选择

从全片选择 5-8 个候选清晰帧，评分考虑：

- 人物面积和人体检测置信度；
- 拉普拉斯模糊或同等清晰度指标；
- 人脸/上半身是否可见；
- 遮挡和人体框重叠；
- 快速摇镜、变焦或重复帧风险；
- 人物是否完整且与其他人分离。

默认展示最高分帧，但必须允许切换。禁止强制用户在第一帧框选。

### 5.2 TargetIdentityAnchor 数据契约

```json
{
  "schema_version": "target_identity_anchor.v1",
  "anchor_id": "anchor_uuid",
  "analysis_id": "analysis_uuid",
  "source": "manual",
  "timestamp_sec": 4.267,
  "source_frame_index_hint": 128,
  "bbox_normalized": {"x": 0.31, "y": 0.18, "width": 0.16, "height": 0.70},
  "frame_width": 1280,
  "frame_height": 720,
  "quality": {
    "blur_score": 0.13,
    "occlusion_score": 0.05,
    "person_confidence": 0.94,
    "face_available": true,
    "contains_multiple_people": false
  },
  "revision": 1
}
```

主锚点模板不可被自动覆盖。允许用户在冲突区间添加同身份补充锚点；补充锚点不能静默改变主锚点身份。

## 6. 双向人物追踪

### 6.1 模块边界

建议新增独立协调层，例如：

```text
tracking/
  contracts.py                 数据契约
  proxy_timeline.py            PTS 映射
  anchor_templates.py          主/可信/短期模板
  camera_motion.py             全局运动估计
  directional_tracker.py       单方向追踪适配器
  crossing_guard.py            多人交叉保护
  bidirectional_fusion.py      前后结果融合
  track_quality.py             指标和质量标志
  crop_assets.py               稳定裁剪
```

具体目录可遵循项目现有习惯，但职责必须分离。`person_tracker.py` 已包含大量重锁和场景特例；新方案不得继续把全部双向状态、资产、模板和融合逻辑塞进该文件。旧类可以作为 `directional_tracker.py` 的检测/短期跟踪适配器。

### 6.2 单方向流程

从人工锚点分别运行到视频结束和视频开始：

```text
相机补偿后的目标位置预测
  -> YOLO 人体候选检测
  -> 候选多证据身份打分
  -> tracked / uncertain / lost
  -> 有条件更新短期或可信模板
  -> 保存逐帧诊断
```

CSRT 或光流只能填补 1-3 帧检测空洞，不能在长遮挡后决定身份。ByteTrack ID 只是轨迹候选 ID，不等于用户身份。

### 6.3 身份证据

初始建议权重仅作为 A/B 起点：

```text
0.35 appearance_similarity
+ 0.25 face_similarity（不可用时对剩余项重新归一化）
+ 0.15 camera_compensated_motion
+ 0.10 pose_shape_similarity
+ 0.10 short_term_iou
+ 0.05 detector_confidence
```

证据强度：人工锚点最强；质量合格的人脸较强；人体外观中强；姿态/身体比例和补偿运动为中等；IoU 和中心距离只适合短时连续；画面中心和最大人物不能决定身份。

禁止把上述权重写死为永久常量。每项必须可配置，并由 Golden 数据标定。

### 6.4 相机运动补偿

每两帧估计背景全局变换：

1. 排除目标和主要人体框区域。
2. 使用稀疏光流或 ORB 特征匹配。
3. 通过 RANSAC 估计仿射变换；只有明确需要时才用单应。
4. 将上一帧目标框投影到当前帧。
5. 候选与投影框比较，而不是与未补偿中心比较。

若内点不足、整屏模糊或变焦模型不可靠，记录 `camera_motion_unreliable` 并降低运动权重。不得悄悄回退为强中心距离。

### 6.5 模板库和污染保护

模板类型：

- `manual_anchor_template`：永久、不可自动覆盖；
- `trusted_templates`：从连续高置信且无冲突帧产生；
- `short_term_template`：适应转身、光照和尺度变化；
- `face_templates`：仅保存质量达标的 embedding 和质量元数据。

只有满足全部条件才能更新可信模板：

- 当前身份分数达到高阈值；
- 第一、第二候选分差达到阈值；
- 最近窗口无失联、遮挡、交叉或突然尺度跳变；
- 与主锚点无强冲突；
- 双向结果已经一致，或该帧尚未融合时仅更新临时缓存。

失联恢复后至少 5-10 帧禁止更新可信模板。`crossing_guard` 期间冻结所有身份模板更新。

### 6.6 三态决策

- `tracked`：身份证据充分，允许姿态和动作分析使用。
- `uncertain`：有候选但证据不足，只保存候选，不确认身份。
- `lost`：没有可信候选。

判断必须同时使用最高分和第一/第二候选分差。`uncertain`/`lost` 时禁止回退到画面中心、最大人物或最近人物。

短时轨迹空洞可插值 bbox，但标记 `bbox_source=interpolated`；插值框不等于已确认身份。长时空洞不得制造轨迹。

### 6.7 多人交叉保护

满足任一条件进入 `crossing_guard`：

- 两个人体框显著重叠；
- 两条轨迹快速接近；
- 检测从两个框短时合成一个框；
- 第一、第二身份候选分差持续缩小。

保护期间：冻结模板；禁止只靠 IoU 继承；交叉后同时比较所有分离候选；使用交叉前模板、人脸、分区颜色和身体比例重新关联。证据相近时输出 `uncertain`，不得延续 ByteTrack ID 伪装为确定身份。

### 6.8 失联和重锁

1. 短时失联：在相机补偿预测区域搜索。
2. 中时失联：扩大到全帧候选，比较主锚点和可信模板。
3. 长时失联/重新入画：位置降为极弱证据，依赖身份特征。
4. 证据不足：保持 `lost`。
5. 重要动作区间无法恢复：请求用户在冲突区间补锚点。

设计目标是高精度并允许拒识，不是伪造 100% 轨迹覆盖。

### 6.9 双向融合

| 前向 | 后向 | 融合行为 |
|---|---|---|
| 同一人物且均可信 | 同一人物且均可信 | 采用并提高置信度 |
| 可信 | lost/uncertain | 采用可信方向，保留单向标志 |
| lost/uncertain | 可信 | 采用可信方向，保留单向标志 |
| 不同人物且均可信 | 不同人物且均可信 | `identity_conflict`，禁止平均选人 |
| 均不可信 | 均不可信 | lost/uncertain |

冲突持续超过门槛时要求补锚点。动作核心区间发生冲突时，阻断高置信动作分析。

### 6.10 TrackFrame 数据契约

```json
{
  "schema_version": "track_frame.v1",
  "timestamp_sec": 6.733,
  "source_frame_index_hint": 202,
  "bbox_normalized": {"x": 0.28, "y": 0.14, "width": 0.18, "height": 0.77},
  "tracking_state": "tracked",
  "identity_score": 0.89,
  "second_candidate_score": 0.47,
  "bbox_source": "detector",
  "forward_score": 0.91,
  "backward_score": 0.87,
  "bidirectional_agreement": true,
  "camera_motion_reliable": true,
  "occlusion_ratio": 0.08,
  "candidate_id": "det_3",
  "quality_flags": []
}
```

视频级追踪摘要必须包含：确认覆盖率、不确定占比、失联占比、最长失联、疑似身份切换、双向冲突时长、交叉次数、插值占比、动作核心区间覆盖率。

### 6.11 稳定人物裁剪

- 裁剪中心和尺寸做时序平滑，不能逐帧剧烈跳动。
- bbox 周围保留 30%-60% 上下文，确保手臂、自由腿、冰刀和冰面完整。
- 失联区间不裁到其他人物；可保持最后可靠视野并显式标记，或使用带框全景代替。
- 同时生成目标裁剪版和带目标框的全景版。
- 两个版本使用相同时间码和原 PTS 映射。

## 7. 动作候选与分层识别

### 7.1 多源高召回候选

候选是以下来源的时间并集：

1. 运动信号：补偿后的框速度/加速度、框内光流、质心、离冰候选、肩髋方向变化。
2. 姿态和生物力学：当前 jump/spin/step/spiral 门控和关键帧候选。
3. MiMo 全片扫描：只列动作候选区间和大类候选，不做技术评价。

候选层目标是召回，允许误报。不同来源不得过早压成唯一标签。

### 7.2 ActionCandidate 数据契约

```json
{
  "schema_version": "action_candidate.v1",
  "candidate_id": "action_003",
  "search_window": {"start_sec": 5.1, "end_sec": 9.4},
  "sources": [
    {"source": "motion", "type": "jump", "confidence": 0.71},
    {"source": "pose", "type": "jump", "confidence": 0.63},
    {"source": "mimo_scan", "type_candidates": ["jump", "step"], "confidence": 0.78}
  ],
  "tracking_quality": {"coverage": 0.98, "identity_conflict": false},
  "status": "needs_boundary_review"
}
```

时间聚类后仍要保留来源。跳跃候选保留起跳前约 1.5-2.5 秒和落冰后约 1.5-2 秒；具体值由 Golden 校准。

### 7.3 MiMo 调用层级

1. `scan`：全片找候选。
2. `boundary`：验证动作并拆分准备/核心/退出区间。
3. `coarse_classification`：只判断 jump/spin/step/spiral/transition/unknown。
4. `specialty`：按大类进入专项分析。
5. `keyframes`：独立定位 T/A/L 或旋转阶段。
6. `dispute_review`：不带第一次结论的独立复核。
7. `report`：只消费结构化证据，不重新猜视频。

高置信多路一致时可以不走争议复核；低质量时应提前停止，不要求走满七层。

### 7.4 通用 MiMo 请求元数据

```json
{
  "schema_version": "mimo_request.v1",
  "analysis_id": "...",
  "candidate_id": "action_003",
  "task": "boundary",
  "model": "mimo-2.5",
  "prompt_version": "boundary-v1",
  "assets": ["target_crop_asset", "annotated_overview_asset"],
  "source_time_range": {"start_sec": 5.1, "end_sec": 9.4},
  "target_identity_instruction": "Only analyze the skater inside the marked target track.",
  "tracking_summary": {"coverage": 0.98, "identity_conflict": false},
  "objective_signals": {}
}
```

所有响应必须含 schema/model/prompt/assets/time range、主结论、备选、支持证据、反证、可见性、不确定原因和 `requires_review`。

### 7.5 提示词公共约束模板

每个 prompt 必须包含以下不可省略的规则：

```text
Analyze only the marked target skater. Ignore all other people.
First describe directly visible evidence, then alternatives, then the conclusion.
Actively list contradictory evidence.
Do not infer a skate edge, toe pick, contact, or body phase when it is not visible.
Do not copy a user-provided action label as your answer.
Use only timestamps visible in the supplied clip and within its source time range.
"uncertain" and "unobservable" are valid preferred outputs when evidence is insufficient.
Return strict JSON matching the supplied schema. Do not add report prose.
```

实际 prompt 可使用中文或英文，但术语定义和 JSON 字段必须固定版本。

### 7.6 Scan prompt 职责

只回答：可能存在什么动作、粗时间范围、是否可能包含多个动作、可见性。禁止回答具体跳跃名称、周数、技术质量和训练建议。

### 7.7 Boundary prompt 职责

输出 `approach_start_sec`、`core_start_sec`、`core_end_sec`、`exit_end_sec` 和边界不确定范围。发现连跳时拆分子动作并保存组合关系，不得把两个跳合成一个长动作。

### 7.8 大类 prompt 职责

合法大类：`jump`、`spin`、`step_sequence`、`spiral_or_field_move`、`transition`、`unknown_action`、`not_an_action`。必须返回候选排序、支持与反证、全身/冰刀可见性。

## 8. 跳跃专项

### 8.1 分层分类

禁止直接让模型做无证据六分类。顺序：

1. 是否明显前向起跳；
2. 是否存在点冰；
3. 起跳脚与自由腿关系；
4. 起跳前方向和旋转方向；
5. 起跳刃是否真实可见；
6. 双脚关系和自由腿摆动；
7. Axel/Lutz/Flip/Loop/Salchow/Toe Loop 模板候选；
8. 主动寻找反证。

冰刀/刃型不可见时，Lutz 与 Flip 应输出组合候选，而非高置信唯一答案。支持 `unknown_jump`、`toe_assisted_unknown`、`edge_jump_unknown` 和训练性半周跳。

### 8.2 左右、镜像和旋转方向

- 记录视频是否镜像。
- 左右脚按滑行者自身定义，不按屏幕左右。
- 所有派生资产继承同一坐标定义。
- prompt 明确当前镜像状态和旋转方向定义。
- 禁止在未确认镜像时输出确定起跳脚。

### 8.3 跳跃输出示例

```json
{
  "jump_family": "toe_assisted",
  "jump_candidates": [
    {
      "name": "flip",
      "confidence_raw": 0.52,
      "supporting_evidence": ["toe-pick candidate visible"],
      "contradicting_evidence": ["inside/outside edge is not observable"]
    },
    {
      "name": "lutz",
      "confidence_raw": 0.43,
      "supporting_evidence": ["counter-rotated preparation candidate"],
      "contradicting_evidence": ["takeoff edge is not observable"]
    }
  ],
  "final_label": "flip_or_lutz_uncertain",
  "skate_visibility": "poor",
  "requires_review": true
}
```

## 9. 周数与不足周

### 9.1 旋转估计

禁止只使用“平均转速 x 滞空时间”。融合：

- 起跳和落冰身体方向；
- 肩线、髋线逐帧圆周展开；
- 人体外观正背面周期；
- MiMo 对朝向变化的独立观察；
- 滞空时间作为辅助；
- 跳跃类型的半周解释差异。

算法要求：只用可见性合格帧；圆周 unwrap；过滤单帧尖峰；肩髋冲突时降级；不把落冰后冰上转动计入空中旋转。

### 9.2 输出

保留连续值、不确定范围和候选：

```json
{
  "air_rotation_revolutions": 2.31,
  "rotation_uncertainty": 0.28,
  "rotation_candidates": [
    {"label": "double", "confidence_raw": 0.69},
    {"label": "triple", "confidence_raw": 0.25}
  ],
  "classification": "double_likely",
  "underrotation_assessment": "unobservable"
}
```

Axel 与非 Axel 必须条件化解释。跳跃种类不确定时可输出：“若为 Axel，更接近 2A；若为非 Axel，更接近二周跳”。禁止强行合成唯一 `3Lz` 等标签。

第一阶段不足周只支持 `likely_full`、`likely_underrotated`、`unobservable`，不宣称裁判级 `q/< /<<`。

## 10. T/A/L 关键帧

### 10.1 固定定义

- `T`：最后一个仍与冰面接触的起跳帧，或首次明确离冰前的最后接触。
- `flight_start`：首次明确双脚离冰。
- `A`：空中身体质心最高点。
- `L`：冰刀首次重新接触冰面，不是落冰完全稳定。
- `landing_stable`：落冰滑出趋稳。
- `exit_end`：动作退出结束。

必须满足：`T < flight_start <= A < L <= landing_stable`。冲突时重新搜索或拒识，禁止单纯排序错误时间戳。

### 10.2 粗到细

1. 15-25 fps 局部片段找候选范围。
2. 回到原始 PTS 提取范围内所有真实帧。
3. MiMo 独立返回候选范围和可见证据。
4. 几何信号在范围内选择最终帧。
5. 保存第二候选和不确定区间。

证据包括脚/冰面接触、补偿后的质心、框底边、局部冰面基准、目标内姿态、MiMo 帧级判断。手机摇镜时不得直接使用原始像素 y 判断顶点。

```json
{
  "takeoff": {
    "timestamp_sec": 7.233,
    "candidate_range_sec": [7.167, 7.300],
    "confidence_raw": 0.81,
    "second_candidate_sec": 7.267,
    "evidence": ["last visible ice contact", "both feet airborne next frame"],
    "tracking_state": "tracked"
  }
}
```

## 11. 其他动作专项

### 11.1 旋转

输出入转、主转、出转、方向、有效圈数估计、姿态变化、轴心漂移、转速曲线、可见性。高速旋转时 MediaPipe 可能左右肢体交换，必须融合人体轮廓、服装纹理周期、肩髋和 MiMo。第一阶段禁止自动输出正式 ISU 等级。

### 11.2 步法

重点是区间、连续换向/换脚候选、节奏、中断和上身控制。720p 微信视频通常不足以可靠逐刃识别，第一阶段不承诺内外刃裁判级结论。

### 11.3 燕式和自由滑动作

输出保持区间、自由腿相对髋高度、躯干角度、支撑腿稳定和保持时间。名称不确定时优先输出客观几何描述。

## 12. 证据融合和置信度

### 12.1 状态

- `confirmed`：多路证据一致且质量达标；
- `likely`：主要证据一致但有有限不确定；
- `uncertain`：候选接近或关键证据不可见；
- `conflicted`：不同证据矛盾；
- `unobservable`：视频质量不足；
- `not_applicable`：动作不适用。

前端必须区分“动作做得差”和“视频无法判断”。

### 12.2 置信度来源

MiMo 自报分数不能直接成为最终分数。融合考虑：模型独立一致性、可见性、人物追踪、几何证据、边界质量和类别可分辨性。初期可解释规则，数据足够后使用逻辑回归或等距校准。

硬上限：

- 动作核心身份不确定：不得高于低档。
- 冰刀不可见：Lutz/Flip 唯一分类不得 `confirmed`。
- T/L 位于插值轨迹：周数不得 `confirmed`。
- 独立复核冲突：不得 `confirmed`。
- 单一证据源：不得使用“确定”。

### 12.3 独立复核

第二次复核不得看到第一次最终标签，只接收客观资产、时间范围和非结论性信号。融合层再比较结论、边界、证据和遗漏。冲突时保留冲突，禁止简单平均选择。

## 13. Golden 数据集

### 13.1 集合划分

- `golden-train`：调阈值和 prompt。
- `golden-validation`：方案选择。
- `golden-test`：冻结验收。

同一原始视频、裁剪、慢放和同场连续片段只能位于同一集合。测试集不得用于调参。

### 13.2 数量

Phase 0 最少 30 段，覆盖单人、多人、交叉、遮挡/出画、快速摇镜、变焦、小目标、旋转、步法、燕式。稳定验收扩展到 100-150 段，其中跳跃不少于 60，旋转不少于 20，步法/自由滑不少于 20，多人或遮挡不少于 30%。

训练专用模型前建议至少：20,000 个有效身份框、200 组交叉/重锁、每主要跳跃类别 100-200 个片段、每周数类别 100 个、300 个精确 T/A/L。

### 13.3 标注 schema 扩展

每个样本包含：

- 原视频 SHA-256、PTS/FPS/VFR/旋转/镜像；
- capture tags 和难度；
- 身份锚点、目标 bbox、可见/遮挡/出画、交叉区间；
- 动作区间、大类、专项标签、组合关系；
- T/flight_start/A/L/landing_stable；
- 人物、全身、人脸、冰刀、起跳脚、落冰接触、刃型、周数可观察性；
- 标注者、分歧、仲裁和 revision。

普通区间每 5-10 帧标 bbox；交叉、失联、重锁和动作核心区间逐帧或每 2 帧标。不可辨认帧必须允许标为未知，不能强迫标注者猜人。

关键动作建议双人独立标注并仲裁。争议样本保留不确定标签。

## 14. 评测指标

### 14.1 人物追踪

- Identity Accuracy（确认帧和全部可见帧分别统计）；
- Identity Switches；
- False Relock Rate；
- Tracked/Uncertain/Lost Coverage；
- Bbox IoU；
- Core-action Coverage；
- Longest Lost Duration；
- Conflict Detection Recall。

必须联合报告“确认帧准确率 + 自动确认覆盖率 + 错误重锁率”，防止靠大量拒识虚增准确率。

### 14.2 动作

- 候选 Recall、每分钟误报、区间 IoU、边界误差；
- 连跳拆分 Recall 和合并错误率；
- 大类宏平均 Precision/Recall/F1 和混淆矩阵；
- 跳跃 Top-1、Top-2、按可观察性分层；
- 高置信错误率和正确拒识率；
- 重复分析一致率。

### 14.3 关键帧和周数

T/A/L 分别统计 MAE、中位、P95、最大误差以及 <=0.1/0.2/0.35 秒覆盖率。周数按单/双/三周、Axel/非 Axel、可观察/不可观察分别统计。

### 14.4 分层

至少按 `single_skater`、`multi_skater`、`crossing`、`occlusion`、`small_target`、`fast_pan`、`zoom`、`motion_blur`、`variable_fps`、`wechat_compressed`、动作类别和 easy/medium/hard 输出。整体均值不能掩盖任一困难层退化。

## 15. A/B、版本和合并门槛

每次运行保存 pipeline version、git commit、config hash、MiMo 模型、所有 prompt 版本、schema 版本和 feature flags。

A/B 固定同一视频、同一锚点、同一模型、同一编码和采样；一次只改变一个主要变量。MiMo 关键变更至少重复 3 次，报告均值、最差值和一致率。

硬门槛：

- 不得新增已确认身份切换；
- 多人身份准确率不得下降超过 1 个百分点；
- 错误重锁率不得上升；
- 动作核心覆盖不得下降超过 2 个百分点；
- 动作候选召回不得下降；
- 大类宏 F1 不得下降超过 1 个百分点，单类不得下降超过 3 个百分点；
- T/A/L 中位改善小于 0.03-0.05 秒视为无显著收益；
- 高置信错误率不得上升；
- 不可观察样本的错误确定率必须下降或持平。

## 16. 群晖运行设计

### 16.1 资源限制

- 分析任务默认并发 1；
- FFmpeg 限制 1-2 线程；
- 避免 FFmpeg 和 YOLO 长期同时满载；
- API 等待期间可做轻量本地任务；
- 配置 CPU、内存、磁盘水位保护；
- 不在 DS918+ 运行 VideoMAE/SlowFast、大型 ReID、多路高帧率重姿态模型或训练。

### 16.2 可恢复状态机

```text
uploaded
prechecking
awaiting_target_anchor
normalizing_video
tracking_forward
tracking_backward
fusing_tracks
awaiting_tracking_review
generating_target_assets
detecting_action_candidates
reviewing_boundaries
classifying_actions
analyzing_specialties
locating_keyframes
fusing_evidence
generating_report
completed
```

每阶段保存输入/输出资产、配置 hash、时间、重试次数、错误码、可重试性和人工依赖。容器重启后从最后一个完整阶段继续。

### 16.3 缓存

MiMo 缓存键：源 SHA-256 + 时间区间 + 轨迹 revision + 编码参数 + 模型 + prompt + schema + 推理参数。人物轨迹修正后，依赖轨迹的裁剪和识别缓存失效；视频预检和原始 PTS 缓存保留。

### 16.4 API 异常

- 超时/限流：有限次数指数退避；
- 认证失败：立即停止；
- 非法 JSON：有限修复或重试，禁止填默认动作；
- 时间戳越界：结果无效，禁止自动 clamp；
- 专项失败：保留大类；
- 关键帧失败：不伪造 T/A/L；
- 报告失败：保留结构化分析；
- 保存模型服务版本变化和资产过期信息。

### 16.5 隐私

人脸尽量只存 embedding 和质量，不额外存截图。云端资产配置过期和删除；本地临时裁剪自动清理；删除原视频时级联删除裁剪、模板、缓存和云端资产；日志禁止记录 API Key、完整 embedding 和不必要的个人信息。Golden 与普通用户数据分区。

## 17. Phase 0-8 实施顺序

### Phase 0：测量基础设施

目标：不改算法，建立可信基线。

任务：固定 Golden schema；扩展标注工作台；标 30 段；运行当前基线；输出分层错误；冻结测试集；建立 diff 和门槛。

交付：manifest、标注指南、baseline JSON、错误清单、最差 10 个样本可视化。

验收：可重复评测；PTS 对齐；失败能追到中间证据。

### Phase 1：时间轴和资产

实现 PTS 映射、CFR 代理、旋转/镜像、调试时间码、原始帧回查、重复帧和模糊检测。

验收：30 秒末端仍约一帧内；横竖屏框不偏；重编码不累计漂移。

### Phase 2：强人工锚点

实现候选清晰帧、切换框选、主模板、框质量、多锚点和重跑复用。

验收：不依赖首帧；模糊/双人框提示；坐标跨资产一致。

### Phase 3：双向追踪

顺序：前后独立输出 -> 相机补偿 -> 三态 -> 模板库 -> 污染保护 -> crossing guard -> 冲突检测 -> 融合 -> 补锚点 -> 稳定裁剪。

建议 flags：

```text
TRACKING_BIDIRECTIONAL
TRACKING_CAMERA_MOTION_COMPENSATION
TRACKING_THREE_STATE_DECISION
TRACKING_TEMPLATE_GUARD
TRACKING_CROSSING_GUARD
TRACKING_REQUIRE_REVIEW_ON_CONFLICT
```

验收：测试集身份切换 0；错误重锁下降；系统能拒识；核心冲突阻断高置信分析。

### Phase 4：动作高召回候选

合并运动/姿态/MiMo；候选聚类；按动作 padding；组合拆分；保存来源和失败原因。

验收：候选 Recall 约 98%；连跳可拆；所有来源可追踪。

### Phase 5：MiMo 分层识别

依次实现 scan、boundary、coarse、各 specialty、dispute、严格 schema、校验、缓存和版本记录。

验收：prompt 职责隔离；第二次不受第一次标签诱导；不可见证据不产生高置信；非法输出不伪成功。

### Phase 6：T/A/L 和周数

实现固定定义、原始帧回查、补偿质心、冰面基准、肩髋 unwrap、候选融合、第二候选、空中/冰上转动分离、Axel 条件化。

验收：分别达到中位和 P95 目标；低清视频不输出虚假不足周。

### Phase 7：校准和报告

收集原始分数；校准状态；实现证据上限；报告只消费结构化结果；展示证据和限制。

验收：`confirmed` 的真实准确率显著高于 `likely`；报告不新增动作；高置信错误率达标。

### Phase 8：专用模型评估

仅在 Phase 0-7 的真实数据证明瓶颈后评估云端 OSNet/FastReID、VideoMAE、时序定位、冰刀接触或跳跃分类器。使用主动学习优先标注分歧样本，不提前锁定模型。

## 18. 实施任务模板

每次只给实现模型一个可验证任务。任务说明必须包含：

```text
目标：只实现 <单一能力>。
先读：<相关代码、测试、本文章节>。
禁止修改：<无关模块>。
兼容要求：旧数据/旧 API/旧路径继续工作。
feature flag：<名称，默认关闭>。
先写失败测试：<场景>。
输出契约：<schema>。
诊断要求：<必须保存的字段和 flags>。
验证：单测 + Golden A/B + 分层指标。
回滚：关闭 flag 即回旧路径。
完成报告：修改文件、测试结果、指标 delta、已知限制。
```

推荐拆分示例：

1. 只实现 PTS mapping，不改跟踪。
2. 只实现锚点候选帧评分，不改自动目标锁。
3. 只新增前/后方向结果契约，不启用融合。
4. 只实现相机运动估计和诊断，不改变候选选择。
5. 只实现三态决策，不改模板。
6. 只实现 crossing guard，不改 MiMo。
7. 只实现双向冲突检测，不自动解决冲突。
8. 只实现稳定裁剪资产。
9. 只实现 scan prompt 和 schema。
10. 只实现 boundary prompt，不改报告。
11. 只实现 T/A/L 原始帧回查。
12. 只实现置信度上限规则，不重新训练模型。

## 19. 实施禁止事项

- 禁止未建 Golden 基线就宣称准确率提升。
- 禁止一次提交混改跟踪、prompt、关键帧和报告。
- 禁止把测试样本文件名、时间戳或人物位置硬编码进规则。
- 禁止继续向旧 `person_tracker.py` 无限增加场景阈值而不建立独立边界。
- 禁止把 ByteTrack ID、画面中心、最大人物当成用户身份。
- 禁止失联后自动选择最接近人物以追求满覆盖。
- 禁止自动更新主人工锚点模板。
- 禁止交叉或重锁后立即更新可信模板。
- 禁止用插帧视频测量真实 T/A/L。
- 禁止 MiMo 单次调用同时定位、分类、打分和写报告。
- 禁止第二次复核看到第一次最终标签。
- 禁止 JSON 失败时填默认动作或默认关键帧。
- 禁止对不可观察的刃型、周数或接触输出高置信结论。
- 禁止只报告总体平均指标。
- 禁止用更多 `uncertain` 隐藏自动覆盖率下降。
- 禁止在群晖上引入未经测量的大型模型或高并发。

## 20. 目标验收标准

达到以下条件后才可称为高精度版本：

- 冻结测试集至少 100 段并覆盖困难分层；
- 已确认人物身份切换为 0；
- 多人身份准确率约 95% 或以上；
- 动作核心跟踪覆盖率约 95% 或以上；
- 动作候选召回约 98% 或以上；
- 动作大类宏 F1 至少 90%，目标接近 95%；
- T/A/L 中位误差 <=0.10 秒；
- T/A/L P95 <=0.25 秒；
- 跳跃类型报告可观察样本 Top-1/Top-2；
- 周数按单/双/三周分别达标；
- 高置信错误率 <2%；
- 重复分析一致率 >=95%；
- 不可观察样本能稳定拒识；
- 任一困难分层没有超过门槛的回归；
- 群晖任务支持缓存、恢复、有限重试和安全清理。

这些数值是产品验收目标，不是当前基线结论。Phase 0 完成后应根据真实基线给每个 Phase 设置合理增量目标，但不得降低“身份切换为 0”和“高置信错误率”这两项安全目标。

## 21. 设计决策摘要

选择本方案的原因：用户允许逐视频手动框选；典型视频手机跟拍、变焦、抖动且经微信压缩；群晖本地算力有限但云端 MiMo 调用成本可增加。因此最优路线是“人工强身份锚点 + 本地轻量双向连续跟踪 + 稳定目标资产 + MiMo 职责隔离的分层复核 + Golden 数据闭环”。

未选择纯调 prompt：无法修复上游换人、VFR 和稀疏追踪问题。  
未立即训练专用模型：当前没有足够 Golden 真值，无法验证收益或防止过拟合。  
未追求表面满覆盖：在教练分析场景中，明确“不确定”优于稳定地分析错人或编造动作。
