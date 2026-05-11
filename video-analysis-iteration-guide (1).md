# 视频分析模块迭代开发指南

> 版本：v1.0 · 2026-04-30  
> 适用项目：花样滑冰训练分析系统 · 视频分析子模块  
> 目标：提升分析精度、修复已知缺陷、建立可持续迭代能力

---

## 一、当前架构快速回顾

分析链路：上传 → 抽帧 + 动作窗口裁剪 → 主滑行者锁定 → 姿态提取（MediaPipe）→ 生物力学计算 → 视觉分析（VLM）→ 报告生成 → force_score

核心文件职责：

| 文件 | 职责 |
|------|------|
| `routers/analysis.py` | 业务编排层，主流程状态机 |
| `services/video.py` | 抽帧、动作窗口检测、帧编码 |
| `services/target_lock.py` | 主滑行者候选框与锁定 |
| `services/pose.py` | MediaPipe 姿态提取，支持多候选回退 |
| `services/biomechanics.py` | 几何启发式指标计算 |
| `services/vision.py` | VLM 逐帧视觉分析，输出结构化 JSON |
| `services/report.py` | 报告生成，AI 分数 + 生物力学分数融合 |

---

## 二、根因诊断：当前精度瓶颈

### 2.1 抽帧太稀疏，高速动作信息丢失

```python
# video.py
FRAME_RATE = 5        # 固定 5fps
MAX_SAMPLED_FRAMES = 20
```

一个标准 1A 跳跃约 0.4~0.6 秒，5fps 只能抓到 2~3 帧，起跳和落冰阶段极易错过。步法序列 8 秒则相反——20 帧的上限会强制均匀下采样，导致快速步法细节丢失。

### 2.2 Vision Prompt 结构化过死，语义表达力弱

`vision.py` 的 observation 字段是固定枚举（`充分|不足|过度`），模型无法给出连续量的描述，信息损失严重。`max_tokens=3500` 对 20 帧逐帧 JSON 输出偏紧，后几帧频繁被截断。

### 2.3 生物力学在画面归一化坐标系里算物理量

```python
# biomechanics.py
left_distance = math.hypot(left_wrist["x"] - left_shoulder["x"], ...)
```

MediaPipe 输出 0~1 归一化坐标，用它直接计算手臂距离和对称性，会因人物在画面中大小不同而大幅漂移，导致同一动作在不同拍摄距离下得分差异很大。

### 2.4 分数融合没有数据质量加权

```python
# report.py
fused[key] = round(ai_score * 0.4 + bio_score * 0.6)
```

bio_score 的 default 是 65，即使关键帧只检测到 2 帧（遮挡严重），也会以 60% 权重参与融合。`biomechanics.py` 已有 `quality_flags` 输出，但 `report.py` 没有使用。

### 2.5 关键帧检测仅靠 CoM Y 轴极值

```python
apex_index = min(range(len(points)), key=lambda index: points[index]["y"])
```

对旋转、燕式等 Y 轴无明显变化的动作，关键帧识别几乎失效，发给 VLM 的"关键帧"可能根本不在关键阶段。

### 2.6 Vision 解析失败的 Dead Code Bug

```python
# vision.py — 当前代码
try:
    parsed = json.loads(cleaned)
except json.JSONDecodeError as exc:
    logger.warning(...)
    raise AnalysisPipelineError(...)   # ← raise 之后
    parsed = { ... }                   # ← 永远不会执行！
```

JSON 解析失败会直接让整条分析链断掉，而不是走 fallback 降级。

### 2.7 Analysis Profile 推断时机偏晚

当前 profile 在 pose 结果出来后才推断，但 vision prompt 和抽帧策略在更早阶段就需要用它。用户已经填写了 `action_type` + `action_subtype`，完全可以在上传时就确定 profile。

---

## 三、迭代任务清单

### P0 · 修 Bug + 零成本提升（优先实施）

---

#### TASK-01：修复 vision.py Dead Code Bug

**文件**：`backend/app/services/vision.py`

**问题**：`raise` 后的 fallback `parsed` 赋值永远不会执行，JSON 解析失败直接导致整条分析链失败。

**改法**：

```python
try:
    parsed = json.loads(cleaned)
except json.JSONDecodeError as exc:
    logger.warning("Vision JSON parse failed: %s | raw: %s", exc, cleaned[:300])
    # 降级：构造全帧 fallback，让分析在低质量状态下继续完成
    parsed = {
        "frame_analysis": [_fallback_frame(frame.frame_id) for frame in frame_payloads],
        "action_phase_summary": {
            "detected_phases": [],
            "weakest_phase": "不可分析",
            "strongest_phase": "不可分析",
        },
        "overall_raw_text": raw_content[:500],
    }
```

**验收**：构造一条必然导致 JSON 解析失败的 VLM mock 返回，确认分析流程能走完并标记 `data_quality` 低。

---

#### TASK-02：Vision max_tokens 动态化 + 输出长度约束

**文件**：`backend/app/services/vision.py`

**问题**：`max_tokens=3500` 对多帧输出偏紧，后几帧容易被截断。

**改法**：

```python
# 每帧约 250 token，加上 action_phase_summary 约 400 token
max_tokens = min(8000, 400 + len(frame_payloads) * 250)

# 同时在 user_prompt 末尾加约束
"每帧的 issues 和 positives 各不超过 2 条，每条不超过 30 字。\n"
"必须只输出 JSON，禁止任何解释文字。"
```

**验收**：发送 20 帧时确认最后几帧有完整输出，不被截断。

---

#### TASK-03：跳跃动作窗口局部升帧

**文件**：`backend/app/services/video.py`

**问题**：5fps 对 0.4~0.6 秒的跳跃动作只能抓 2~3 帧。

**改法**：在 `extract_frames` 或动作窗口正式抽帧阶段，检测到 `jump` profile 时，对动作窗口内单独提高采样率：

```python
PROFILE_FRAME_RATES: dict[str, int] = {
    "jump":   10,   # 跳跃：10fps，确保起跳落冰帧
    "spin":    8,   # 旋转：8fps
    "spiral":  6,   # 燕式：6fps，动作慢
    "step":    5,   # 步法：5fps，窗口长优先覆盖
}

def get_frame_rate_for_profile(profile: str) -> int:
    return PROFILE_FRAME_RATES.get(profile, FRAME_RATE)
```

同时把 `MAX_SAMPLED_FRAMES` 也按 profile 区分：

```python
PROFILE_MAX_FRAMES: dict[str, int] = {
    "jump":   15,   # 窗口短，帧率高，15 帧够用
    "spin":   20,
    "spiral": 18,
    "step":   24,   # 步法窗口最长
}
```

**验收**：上传一段含有单跳的视频，确认抽出的帧里包含明显的起跳弯膝帧和落冰单腿帧。

---

#### TASK-04：Analysis Profile 推断前置

**文件**：`backend/app/routers/analysis.py`、`backend/app/services/video.py`

**问题**：profile 在 pose 完成后才推断，但抽帧策略（帧率、窗口大小）在更早阶段就需要用它。

**改法**：新增一个纯规则函数，在上传时根据 `action_type` + `action_subtype` 立即确定 profile：

```python
def infer_profile_from_input(action_type: str, action_subtype: str | None) -> str:
    jump_keywords = {"跳跃", "jump", "Axel", "Lutz", "Flip", "Loop", "Salchow", "Toe"}
    spin_keywords  = {"旋转", "spin", "Spin"}
    spiral_keywords = {"燕式", "螺旋线", "spiral", "Spiral"}
    step_keywords  = {"步法", "step", "Step"}

    text = f"{action_type} {action_subtype or ''}".lower()
    if any(k.lower() in text for k in jump_keywords):
        return "jump"
    if any(k.lower() in text for k in spin_keywords):
        return "spin"
    if any(k.lower() in text for k in spiral_keywords):
        return "spiral"
    if any(k.lower() in text for k in step_keywords):
        return "step"
    return "jump"  # 默认
```

将此函数的返回值传入抽帧和视觉分析阶段，pose 阶段的 profile 推断保留用于二次校验（可覆盖输入值）。

**验收**：填写"Axel 跳跃"上传时，确认抽帧阶段就使用了 jump profile 的帧率。

---

### P1 · 提升分析质量的核心改动

---

#### TASK-05：生物力学指标坐标归一化修正

**文件**：`backend/app/services/biomechanics.py`

**问题**：所有距离和对称性计算直接使用 MediaPipe 的 0~1 画面归一化坐标，导致指标随拍摄距离变化而漂移。

**改法**：新增参考长度计算函数，用人物肩宽作为归一化基准：

```python
def _reference_length(keypoints: list[dict[str, Any]]) -> float:
    """用肩宽作为参考长度，归一化人物在画面中的尺度。"""
    ls = _point(keypoints, 11)  # 左肩
    rs = _point(keypoints, 12)  # 右肩
    if not (ls and rs):
        return 0.0
    return math.hypot(ls["x"] - rs["x"], ls["y"] - rs["y"])

def calc_arm_symmetry(keypoints, frame_idx) -> dict:
    ref = _reference_length(keypoints)
    if ref < 0.01:
        return {"frame_idx": frame_idx, "symmetry": None}
    # 计算归一化后的手臂伸展距离
    left_dist  = math.hypot(...) / ref
    right_dist = math.hypot(...) / ref
    symmetry = max(0.0, 1.0 - abs(left_dist - right_dist))
    return {"frame_idx": frame_idx, "symmetry": symmetry}
```

同理修改 `calc_center_of_mass_trajectory` 的 `vertical_range`，改为相对于肩髋距的归一化值。

**验收**：同一动作在不同拍摄距离（全身 vs 半身）下，arm_symmetry 分值差异 < 5%。

---

#### TASK-06：分数融合加数据质量加权

**文件**：`backend/app/services/report.py`

**问题**：bio_score 固定占 60% 权重，不管生物力学检测质量好坏。

**改法**：

```python
def fuse_subscores(
    ai_subscores: dict[str, Any],
    bio_subscores: dict[str, Any] | None,
    quality_flags: list[str] | None = None,
) -> dict[str, int]:
    normalized_ai = {key: _clamp_score(ai_subscores.get(key), 75) for key in SUBSCORE_KEYS}
    if not bio_subscores:
        return normalized_ai

    # 每个 warning flag 降低 bio 权重 0.08，最低降到 0.2
    warning_count = len(quality_flags or [])
    bio_weight = max(0.20, 0.60 - warning_count * 0.08)
    ai_weight  = 1.0 - bio_weight

    fused: dict[str, int] = {}
    for key in SUBSCORE_KEYS:
        ai_s  = normalized_ai[key]
        bio_s = _clamp_score(bio_subscores.get(key), ai_s)
        fused[key] = round(ai_s * ai_weight + bio_s * bio_weight)
    return fused
```

同时修改调用方，从 `bio_data` 里取出 `quality_flags` 传入：

```python
# routers/analysis.py 中
fused = fuse_subscores(
    ai_subscores=ai_subs,
    bio_subscores=bio_data.get("bio_subscores"),
    quality_flags=bio_data.get("quality_flags", []),
)
```

**验收**：构造一个 quality_flags 包含 3 条 warning 的 bio_data，确认 bio 权重降至 0.36，总分向 AI 分数偏移。

---

#### TASK-07：关键帧检测按 profile 分策略

**文件**：`backend/app/services/biomechanics.py`

**问题**：`_detect_key_frames` 只看 CoM Y 轴极值，对旋转、燕式等动作意义不大。

**改法**：

```python
def detect_key_frames(
    com_trajectory: dict[str, Any],
    pose_data: dict[str, Any],
    analysis_profile: str = "jump",
) -> dict[str, str]:
    points = com_trajectory.get("points", [])
    if len(points) < 3:
        return {}

    if analysis_profile == "jump":
        # 现有逻辑：找 CoM Y 最小值（最高点）
        apex_idx = min(range(len(points)), key=lambda i: points[i]["y"])
        takeoff_idx = _find_descent_start(points, apex_idx)
        landing_idx = _find_ascent_start(points, apex_idx)
        return {
            "T": points[takeoff_idx]["frame"],
            "A": points[apex_idx]["frame"],
            "L": points[landing_idx]["frame"],
        }

    elif analysis_profile == "spin":
        # 找相邻帧髋部 x 坐标变化最大的帧（旋转速度最快处）
        frames = pose_data.get("frames", [])
        max_delta_idx = _find_max_hip_x_delta(frames)
        if max_delta_idx is None:
            return {}
        mid = max_delta_idx
        start = max(0, mid - 1)
        end   = min(len(frames) - 1, mid + 1)
        return {
            "旋转入": frames[start].get("frame", ""),
            "旋转中": frames[mid].get("frame", ""),
            "旋转出": frames[end].get("frame", ""),
        }

    elif analysis_profile in ("spiral", "step"):
        # 找自由腿踝关节 Y 坐标最小帧（腿抬最高处）
        frames = pose_data.get("frames", [])
        peak_idx = _find_free_leg_peak(frames)
        if peak_idx is None:
            return {}
        return {"峰值": frames[peak_idx].get("frame", "")}

    return {}
```

**验收**：旋转视频分析后，key_frames 里有"旋转入/旋转中/旋转出"而不是"T/A/L"。

---

#### TASK-08：Vision Prompt 加入 Profile 专属引导

**文件**：`backend/app/services/vision.py`

**问题**：所有动作类型共用同一套 observation 字段和分析描述，LLM 注意力没有聚焦。

**改法**：新增 profile hint 字典，注入 user_prompt：

```python
PROFILE_HINTS: dict[str, str] = {
    "jump": (
        "重点观察：① 起跳阶段膝关节弯曲深度（深蹲效果）"
        " ② 腾空阶段手臂是否快速收紧至胸前"
        " ③ 落冰阶段是否为单腿支撑、膝盖弯曲缓冲"
        " ④ 轴线是否保持垂直，无明显侧倾。"
    ),
    "spin": (
        "重点观察：① 旋转轴垂直度，是否存在前倾/后仰漂移"
        " ② 手臂/腿收紧与旋转加速的对应关系"
        " ③ 入转和出转冰刃切换是否流畅"
        " ④ 头部固定点（spotting）是否存在。"
    ),
    "spiral": (
        "重点观察：① 自由腿高度，理想应超过髋关节水平线"
        " ② 支撑腿膝盖是否完全伸直"
        " ③ 躯干稳定性，不应有明显晃动"
        " ④ 手臂姿态是否与身体轴线协调。"
    ),
    "step": (
        "重点观察：① 冰刃切换节奏是否与音乐/节拍匹配"
        " ② 膝盖推送力度，每步是否有明显 push"
        " ③ 上半身（肩/臂）是否过度摆动"
        " ④ 重心转移是否平稳，无明显身体侧倾。"
    ),
}

# 在 user_prompt 里注入
profile_hint = PROFILE_HINTS.get(analysis_profile or "jump", "")
user_prompt = (
    f"分析以下【{action_type}】动作帧序列（共 {len(frame_payloads)} 帧，按时间顺序排列）。\n"
    f"动作子类型：{action_subtype or '未指定'}\n"
    f"分析 profile：{analysis_profile or 'unknown'}\n"
    f"{profile_hint}\n"
    ...
)
```

**验收**：旋转视频的 issues 和 positives 内容应涉及轴线、收臂，而不是"起跳膝盖弯曲"。

---

### P1.5 · 视频处理质量提升

---

#### TASK-09：帧质量预过滤（模糊帧剔除）

**文件**：`backend/app/services/video.py`

**问题**：运动模糊、过曝、遮挡帧会被当作有效关键帧发给 VLM，拉低分析质量。

**改法**：在帧编码前加一个 Laplacian 方差检测，过滤掉模糊帧：

```python
import cv2
import numpy as np

BLUR_THRESHOLD = 80.0   # 可配置，值越低越严格

def is_blurry(image_path: Path, threshold: float = BLUR_THRESHOLD) -> bool:
    img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return True
    variance = cv2.Laplacian(img, cv2.CV_64F).var()
    return variance < threshold

def filter_frames(frame_paths: list[Path]) -> list[Path]:
    good_frames = [p for p in frame_paths if not is_blurry(p)]
    # 至少保留 3 帧，避免全部过滤
    return good_frames if len(good_frames) >= 3 else frame_paths[:3]
```

在 `encode_frames_for_vision` 调用前插入 `filter_frames`。

**验收**：上传一段含有明显运动模糊（快速平移）的视频，确认模糊帧不出现在发给 VLM 的帧列表里。

---

#### TASK-10：慢动作视频专项采样策略

**文件**：`backend/app/services/video.py`

**问题**：已检测到 `is_slow_motion`（源 FPS > 60），但慢动作视频按时间戳均匀采样会产生大量冗余帧（240fps 的视频每 0.2s 就有 48 帧）。

**改法**：对慢动作视频，按运动密度差异而非时间均匀采样：

```python
def get_slow_motion_scale(source_fps: float) -> float:
    """返回慢动作相对于正常速度的倍数，用于时间轴映射。"""
    normal_fps = 30.0
    return source_fps / normal_fps  # 240fps → 8x 慢动作

# 在动作窗口计算时，将时间窗口按慢放倍数压缩
if is_slow_motion:
    scale = get_slow_motion_scale(source_fps)
    # 3 秒的跳跃窗口在 240fps 源文件里对应 3*scale = 24 秒时长
    # 应该在这 24 秒里按正常速度等效采 15 帧
    effective_duration = action_window_duration / scale
```

**验收**：上传 240fps 慢动作跳跃视频，确认抽出的帧覆盖完整动作周期而不是集中在某一段。

---

#### TASK-11：跳跃圈数自动推断

**文件**：`backend/app/services/biomechanics.py`

**问题**：`rotation_rps`（每秒转速）和 `air_time_seconds`（滞空时间）已经计算出来，但没有用来推断跳跃圈数。

**改法**：

```python
def estimate_jump_rotations(
    rotation_rps: float | None,
    air_time_seconds: float | None,
) -> dict[str, Any]:
    if rotation_rps is None or air_time_seconds is None:
        return {"estimated_rotations": None, "probable_jump_type": "unknown"}

    rotations = rotation_rps * air_time_seconds

    # ISU 标准：1A≈1转，2A≈2转，3A≈3转（因起跳有半圈偏移，Axel 系列各多半圈）
    thresholds = [
        (0.8, 1.8, "单圈跳 (1T/1S/1Lo/1F/1Lz)"),
        (1.8, 2.8, "双圈跳 (2A/2T/2S/2Lo/2F/2Lz)"),
        (2.8, 3.8, "三圈跳 (3A/3T/3S/3Lo/3F/3Lz)"),
        (3.8, 5.0, "四圈跳 (4T/4S/4Lo/4F/4Lz)"),
    ]
    probable = "unknown"
    for lo, hi, label in thresholds:
        if lo <= rotations < hi:
            probable = label
            break

    return {
        "estimated_rotations": round(rotations, 2),
        "probable_jump_type": probable,
    }
```

将返回值合并进 `discipline_metrics` 或 `jump_metrics`。

**验收**：一段 2A 视频的分析报告里出现 `estimated_rotations ≈ 2.0~2.5`，`probable_jump_type` 包含"双圈跳"。

---

### P2 · 架构稳定性与版本治理

---

#### TASK-12：新增 pipeline_version 字段

**文件**：`backend/app/models.py`、`backend/app/routers/analysis.py`

**目的**：每次算法升级后能对比新旧版本的效果，而不是凭感觉判断是否提升。

**改法**：

```python
# models.py
pipeline_version: Mapped[str] = mapped_column(String, default="v1.0.0", nullable=False)

# 单独维护一个常量文件
# services/pipeline_version.py
CURRENT_PIPELINE_VERSION = "v1.1.0"

# 写入分析记录时赋值
analysis.pipeline_version = CURRENT_PIPELINE_VERSION
```

版本号规则建议：`v主版本.算法版本.hotfix`，每次修改以下任意一项就升 `算法版本`：抽帧策略、生物力学计算逻辑、Vision Prompt 内容、分数融合权重。

**验收**：完成一次分析后，数据库里 `pipeline_version` 字段有正确值。

---

#### TASK-13：分析阶段耗时埋点

**文件**：`backend/app/routers/analysis.py`

**目的**：知道哪个阶段最慢，才能优先优化；也便于发现偶发的超时问题。

**改法**：

```python
import time

async def process_analysis(analysis_id: str, ...):
    timings: dict[str, float] = {}
    
    t0 = time.monotonic()
    # ... 抽帧 ...
    timings["extract_frames_s"] = round(time.monotonic() - t0, 2)

    t1 = time.monotonic()
    # ... pose 提取 ...
    timings["pose_s"] = round(time.monotonic() - t1, 2)

    t2 = time.monotonic()
    # ... 生物力学 ...
    timings["biomechanics_s"] = round(time.monotonic() - t2, 2)

    t3 = time.monotonic()
    # ... vision 分析 ...
    timings["vision_s"] = round(time.monotonic() - t3, 2)

    t4 = time.monotonic()
    # ... 报告生成 ...
    timings["report_s"] = round(time.monotonic() - t4, 2)

    timings["total_s"] = round(time.monotonic() - t0, 2)

    # 写回 analysis 记录（可加一个 processing_timings JSON 字段）
    analysis.processing_timings = timings
    logger.info("Analysis %s timings: %s", analysis_id, timings)
```

**验收**：分析完成后，日志里有完整的各阶段耗时。

---

#### TASK-14：视觉分析 confidence 字段纳入评分

**文件**：`backend/app/services/report.py`、`backend/app/services/vision.py`

**目的**：VLM 自己输出的 `confidence` 字段当前完全没有用到，低置信帧的观察不应等权参与报告生成。

**改法**：在 report 生成 prompt 里传入每帧的 confidence，并在 prompt 中说明：

```python
# 构造传给报告模型的 vision 摘要时，过滤低置信帧
HIGH_CONF_THRESHOLD = 0.5

def summarize_vision_for_report(vision_structured: dict) -> dict:
    frames = vision_structured.get("frame_analysis", [])
    
    high_conf_frames = [f for f in frames if f.get("confidence", 0) >= HIGH_CONF_THRESHOLD]
    low_conf_count   = len(frames) - len(high_conf_frames)

    # 如果高置信帧太少，降级使用全部帧但在 prompt 里注明
    if len(high_conf_frames) < 3:
        high_conf_frames = frames
        low_conf_count   = 0

    return {
        "reliable_frames": high_conf_frames,
        "low_confidence_frame_count": low_conf_count,
        "overall_raw_text": vision_structured.get("overall_raw_text", ""),
    }
```

**验收**：构造一批全部 confidence=0.1 的 vision 结果，确认报告摘要标注了"低置信度帧较多，结果仅供参考"。

---

#### TASK-15：分段重试支持

**文件**：`backend/app/routers/analysis.py`

**目的**：当前重试会从头重跑整个流程。视觉模型调用失败时不应该重跑耗时的 pose 提取和生物力学计算。

**改法**：在 `analyses` 表增加 `retry_from_stage` 字段，重试时跳过已完成的阶段：

```python
PIPELINE_STAGES = ["extract_frames", "pose", "biomechanics", "vision", "report"]

async def process_analysis(analysis_id: str, retry_from: str | None = None):
    start_idx = PIPELINE_STAGES.index(retry_from) if retry_from else 0
    
    for stage in PIPELINE_STAGES[start_idx:]:
        if stage == "extract_frames":
            await run_extract_frames(...)
        elif stage == "pose":
            # 如果 pose_data 已存在，直接复用
            if not analysis.pose_data:
                await run_pose(...)
        elif stage == "vision":
            await run_vision(...)
        elif stage == "report":
            await run_report(...)
```

**验收**：VLM 调用失败后，选择"从 vision 阶段重试"，确认不重新跑 pose 和生物力学。

---

---

### P1 · 动作识别准确性专项提升

> **背景说明**
>
> 当前系统的"动作识别"并不是一个独立的分类模型，而是由 `services/action_profiles.py` 里的 `infer_analysis_profile()` 函数用几条几何启发式规则完成的。MediaPipe Pose Landmarker（Google 模型）负责的是**姿态提取**（输出 33 个关键点），并不做动作类型分类。因此动作识别精度低的根源是这套规则本身，而不是 MediaPipe 模型的问题。

---

#### TASK-16：跳跃判定阈值改为人物相对高度

**文件**：`backend/app/services/action_profiles.py`

**问题**：

```python
# 当前代码
jump_gate = vertical_range >= 0.08 and max_motion >= 0.08
```

`vertical_range` 是 MediaPipe 输出的画面归一化坐标（0~1）。远景拍摄时人物只占画面 25% 高度，一个完美的跳跃 CoM 垂直变化量可能只有 0.03~0.05，永远无法过 0.08 的门槛，导致跳跃被错误识别为步法。

**改法**：新增人物参考高度计算，将 `vertical_range` 转为相对于人物高度的比例：

```python
def _person_height_normalized(pose_data: dict[str, Any] | None) -> float:
    """
    用 鼻尖(0) 到 两踝中点 的归一化 Y 距离作为人物高度参考。
    返回 0.0 表示无法计算。
    """
    if not isinstance(pose_data, dict):
        return 0.0
    frames = pose_data.get("frames", [])
    heights: list[float] = []
    for frame in frames:
        kps = frame.get("keypoints", [])
        nose        = next((k for k in kps if k.get("id") == 0  and k.get("visibility", 0) >= 0.5), None)
        left_ankle  = next((k for k in kps if k.get("id") == 27 and k.get("visibility", 0) >= 0.5), None)
        right_ankle = next((k for k in kps if k.get("id") == 28 and k.get("visibility", 0) >= 0.5), None)
        if not nose or not (left_ankle or right_ankle):
            continue
        ankles = [a for a in [left_ankle, right_ankle] if a]
        ankle_y = sum(a["y"] for a in ankles) / len(ankles)
        h = abs(ankle_y - nose["y"])
        if h > 0.05:
            heights.append(h)
    return sum(heights) / len(heights) if heights else 0.0


def infer_analysis_profile(...):
    ...
    person_height = _person_height_normalized(pose_data)

    # 改为相对高度比例：跳跃时 CoM 上升 >= 人物高度的 12%
    if person_height > 0.05:
        relative_vertical = vertical_range / person_height
        jump_gate = relative_vertical >= 0.12 and max_motion >= 0.06
    else:
        # 无法算人物高度时退回绝对阈值，但适当放宽
        jump_gate = vertical_range >= 0.05 and max_motion >= 0.06
```

**验收**：同一段跳跃视频在全身远景和半身近景两种拍摄距离下，均被识别为 `jump` profile。

---

#### TASK-17：足踝离冰检测作为跳跃强信号

**文件**：`backend/app/services/action_profiles.py`

**问题**：CoM 垂直范围是间接信号，容易受遮挡和噪声影响。最可靠的跳跃判定是直接检测双踝是否同时离开冰面基线。

**改法**：

```python
def _detect_airborne_frames(pose_data: dict[str, Any] | None) -> int:
    """
    检测连续多帧里双踝都高于正常站立基线的帧数。
    返回疑似腾空帧数量，>= 2 则认为存在跳跃腾空阶段。
    """
    if not isinstance(pose_data, dict):
        return 0
    frames = pose_data.get("frames", [])
    ankle_y_series: list[float] = []
    for frame in frames:
        kps = frame.get("keypoints", [])
        ankles = [k for k in kps if k.get("id") in (27, 28) and k.get("visibility", 0) >= 0.4]
        if ankles:
            ankle_y_series.append(sum(a["y"] for a in ankles) / len(ankles))
    if len(ankle_y_series) < 3:
        return 0
    # 用前 20% 帧的踝关节 Y 值均值作为"站立基线"
    baseline_count = max(1, len(ankle_y_series) // 5)
    baseline = sum(ankle_y_series[:baseline_count]) / baseline_count
    # Y 坐标越小代表画面越靠上（向上运动）
    # 若踝关节 Y 比基线小 15%（相对画面高度），认为腾空
    airborne_threshold = baseline * 0.85
    airborne_frames = sum(1 for y in ankle_y_series if y < airborne_threshold)
    return airborne_frames


def infer_analysis_profile(...):
    ...
    airborne_frames = _detect_airborne_frames(pose_data)
    # 腾空帧 >= 2 视为跳跃强信号，可覆盖 jump_gate 失败
    jump_gate = jump_gate or (airborne_frames >= 2 and hinted_profile == "jump")
    evidence["airborne_frames_detected"] = airborne_frames
```

**验收**：上传含明显腾空的跳跃视频（即使是远景），`evidence.airborne_frames_detected >= 2`，profile 正确识别为 jump。

---

#### TASK-18：Profile 推断失败不硬降级到 step

**文件**：`backend/app/services/action_profiles.py`

**问题**：

```python
# 当前代码：用户明确填"跳跃"，但 gate 没过，直接返回 step
if hinted_profile == "jump":
    evidence["negative_constraints"].append("...")
return "step", evidence   # 用户填跳跃也没用
```

当用户明确填了"跳跃"，hint 先验应该有更高权重，不应被几何 gate 完全否决。

**改法**：

```python
if hinted_profile == "jump":
    evidence["negative_constraints"].append(
        "几何证据不足（CoM 垂直范围低、无腾空帧检测），但用户填写了跳跃，保留 jump profile"
    )
    evidence["profile_confidence"] = "low"
    # 保留 jump，不降级到 step
    return "jump", evidence

# 只有用户没填跳跃时才 fallback
return "step", evidence
```

同时在 `bio_data` 的 `quality_flags` 里记录 `"jump_gate_not_passed"`，让报告层知道这是低置信度 jump 分析。

**验收**：用户填"跳跃"但拍摄距离很远时，profile 仍为 jump，报告里出现"几何证据不足"的质量提示。

---

#### TASK-19：Phase 时序合法性校验

**文件**：新增 `backend/app/services/phase_smoother.py`，在 `routers/analysis.py` 里调用

**问题**：VLM 的逐帧 phase 是独立判断的，没有跨帧约束，容易出现物理上不合理的序列（如"腾空→起跳→腾空"）。

**改法**：

```python
# phase_smoother.py

# 各 profile 的合法 phase 转移图
VALID_TRANSITIONS: dict[str, dict[str, set[str]]] = {
    "jump": {
        "准备":    {"准备", "起跳"},
        "起跳":    {"起跳", "腾空"},
        "腾空":    {"腾空", "落冰"},
        "落冰":    {"落冰", "滑出", "不可分析"},
        "滑出":    {"滑出", "不可分析"},
        "不可分析": {"准备", "起跳", "腾空", "落冰", "滑出", "不可分析"},
    },
    "spin": {
        "旋转入":  {"旋转入", "旋转中"},
        "旋转中":  {"旋转中", "旋转出"},
        "旋转出":  {"旋转出", "不可分析"},
        "不可分析": {"旋转入", "旋转中", "旋转出", "不可分析"},
    },
    "spiral": {
        "准备":    {"准备", "步法"},
        "步法":    {"步法", "不可分析"},
        "不可分析": {"准备", "步法", "不可分析"},
    },
    "step": {
        "步法":    {"步法", "不可分析"},
        "不可分析": {"步法", "不可分析"},
    },
}


def smooth_phases(frame_analysis: list[dict], analysis_profile: str) -> list[dict]:
    """
    对 VLM 输出的逐帧 phase 做合法性校验和修正。
    非法转移的帧 phase 替换为前一帧的 phase，并标记 phase_corrected=True。
    """
    transitions = VALID_TRANSITIONS.get(analysis_profile, {})
    if not transitions:
        return frame_analysis
    smoothed = []
    prev_phase = "不可分析"
    for frame in frame_analysis:
        current_phase = frame.get("phase", "不可分析")
        allowed = transitions.get(prev_phase, set())
        if current_phase not in allowed and allowed:
            frame = {**frame, "phase": prev_phase, "phase_corrected": True}
        else:
            frame = {**frame, "phase_corrected": False}
        smoothed.append(frame)
        prev_phase = frame["phase"]
    return smoothed
```

在 `routers/analysis.py` 的 vision 结果处理后插入：

```python
from app.services.phase_smoother import smooth_phases

vision_structured["frame_analysis"] = smooth_phases(
    vision_structured["frame_analysis"],
    analysis_profile,
)
```

**验收**：构造包含"腾空→起跳→腾空"序列的 mock vision 输出，经过 smooth 后中间的"起跳"被修正为"腾空"，并标记 `phase_corrected: true`。

---

#### TASK-20：跳跃子类型特征注入分析链

**文件**：`backend/app/services/action_profiles.py`（新增字典），`backend/app/services/vision.py`

**问题**：用户填写了 Axel、Lutz、Flip 等具体跳跃名称，但这些信息几乎没有进入分析逻辑。每种跳跃起跳刃型和方向不同，不注入会导致 VLM 无法做针对性的刃型错误检测。

**改法**：

```python
# action_profiles.py 新增

JUMP_CHARACTERISTICS: dict[str, dict[str, str]] = {
    "axel": {
        "takeoff_edge": "左刀前外刃起跳",
        "direction":    "前向起跳，空中向右旋转",
        "key_check":    "起跳腿（左腿）蹬冰后是否有明显前向跨步，而非向后起跳",
        "rotation_note":"单 Axel=1.5圈，双 Axel=2.5圈，圈数比同类多半圈",
    },
    "lutz": {
        "takeoff_edge": "左刀后外刃起跳（右脚 toe pick 辅助）",
        "direction":    "后向起跳",
        "key_check":    "重点检查是否发生刃型错误：起跳前外刃滑行变内刃（Flutz 错误）",
        "rotation_note":"常见错误：Flutz——外刃在起跳前瞬间偷换为内刃",
    },
    "flip": {
        "takeoff_edge": "左刀后内刃起跳（右脚 toe pick 辅助）",
        "direction":    "后向起跳",
        "key_check":    "与 Lutz 外形相似，区别在于起跳前冰刃为内刃",
        "rotation_note":"常见混淆：与 Lutz 起跳动作相似，需观察起跳前滑行路线",
    },
    "loop": {
        "takeoff_edge": "右刀后外刃起跳（无点冰辅助）",
        "direction":    "后向起跳，双腿并拢",
        "key_check":    "起跳时双腿并拢，右腿单腿承重，检查是否有提前开肩",
        "rotation_note":"纯刃跳，起跳瞬间双脚短暂并拢是识别标志",
    },
    "salchow": {
        "takeoff_edge": "左刀后内刃起跳（无点冰辅助）",
        "direction":    "后向起跳",
        "key_check":    "自由腿（右腿）向前大幅摆动辅助起跳，检查摆腿力度和时机",
        "rotation_note":"纯刃跳，自由腿摆动是起跳动力的关键来源",
    },
    "toe_loop": {
        "takeoff_edge": "右刀后外刃起跳（左脚 toe pick 辅助）",
        "direction":    "后向起跳",
        "key_check":    "点冰位置是否准确，点冰后是否快速收腿进入旋转轴",
        "rotation_note":"最常见的跳跃类型，也是连跳的常用后跳",
    },
}

def get_jump_characteristics(action_subtype: str | None) -> dict[str, str] | None:
    if not action_subtype:
        return None
    normalized = action_subtype.lower().replace(" ", "").replace("（", "(").replace("）", ")")
    for key in JUMP_CHARACTERISTICS:
        if key in normalized or normalized in key:
            return JUMP_CHARACTERISTICS[key]
    return None
```

在 `vision.py` 的 user_prompt 里加入：

```python
jump_chars = get_jump_characteristics(action_subtype)
if jump_chars and analysis_profile == "jump":
    user_prompt += (
        f"\n跳跃类型专项信息：\n"
        f"  起跳刃型：{jump_chars['takeoff_edge']}\n"
        f"  方向特征：{jump_chars['direction']}\n"
        f"  重点检查：{jump_chars['key_check']}\n"
        f"  圈数说明：{jump_chars['rotation_note']}\n"
    )
```

**验收**：上传 Lutz 跳跃视频，VLM 的 issues 里应出现关于刃型检查（Flutz 错误可能性）的描述。

---

#### TASK-21：旋转 Profile 的几何二次验证

**文件**：`backend/app/services/action_profiles.py`

**问题**：旋转 profile 完全靠 `SPIN_SUBTYPES` 集合匹配用户输入，没有用 pose 数据验证。用户填了"旋转"但实际是步法时，整个分析方向会偏。

**改法**：检测相邻帧间髋部 X 轴的累积变化量作为旋转信号：

```python
def _detect_rotation_signal(pose_data: dict[str, Any] | None) -> float:
    """
    计算相邻帧间髋部中心 X 坐标的累积绝对变化量。
    旋转动作时此值会持续累积；步法或燕式时此值较小且方向随机。
    """
    if not isinstance(pose_data, dict):
        return 0.0
    frames = pose_data.get("frames", [])
    hip_x_series: list[float] = []
    for frame in frames:
        kps = frame.get("keypoints", [])
        hips = [k for k in kps if k.get("id") in (23, 24) and k.get("visibility", 0) >= 0.4]
        if hips:
            hip_x_series.append(sum(h["x"] for h in hips) / len(hips))
    if len(hip_x_series) < 3:
        return 0.0
    total_delta = sum(abs(hip_x_series[i] - hip_x_series[i-1]) for i in range(1, len(hip_x_series)))
    return round(total_delta, 4)


def infer_analysis_profile(...):
    ...
    rotation_signal = _detect_rotation_signal(pose_data)
    evidence["hip_rotation_signal"] = rotation_signal

    if hinted_profile == "spin":
        if rotation_signal < 0.15:
            evidence["profile_confidence"] = "low"
            evidence["negative_constraints"].append(
                f"髋部旋转信号弱（{rotation_signal:.3f}），可能不是旋转或存在视角遮挡"
            )
        return "spin", evidence
```

**验收**：上传步法序列视频但填写"旋转"时，`evidence.profile_confidence == "low"` 且报告里有质量提示。

---

## 四、实施顺序建议

按以下顺序推进，每完成一个 TASK 后进行验收测试，再继续下一个：

```
第一批（P0，当天可完成）：
  TASK-01 → TASK-02 → TASK-04

第二批（P0，需测试视频验证）：
  TASK-03 → TASK-09

第三批（P1，核心质量提升 · 通用）：
  TASK-05 → TASK-06 → TASK-07 → TASK-08

第四批（P1，动作识别专项 · 先做最高收益的三个）：
  TASK-16 → TASK-17 → TASK-18 → TASK-19

第五批（P1，动作识别专项 · 子类型精细化）：
  TASK-20 → TASK-21

第六批（P1.5，视频处理优化）：
  TASK-10 → TASK-11

第七批（P2，架构治理）：
  TASK-12 → TASK-13 → TASK-14 → TASK-15
```

---

## 五、不在本次迭代范围内的事项

以下内容已经评估，当前阶段暂不实施：

- **人工纠错入口**：需要前端改动较多，暂缓
- **Celery/RQ 任务队列**：属于架构层升级，待 P0/P1 算法稳定后再引入
- **多人检测模型替换**：需要引入新模型（如 YOLOv8-pose），成本较高，列为后续 P2
- **帧级标注与训练数据积累**：依赖人工纠错，暂缓
- **在线/流式分析**：当前离线批处理满足需求，暂不改造

---

## 六、关键文件变更速查

| TASK | 主要改动文件 |
|------|-------------|
| TASK-01 | `services/vision.py` |
| TASK-02 | `services/vision.py` |
| TASK-03 | `services/video.py` |
| TASK-04 | `routers/analysis.py`, `services/video.py` |
| TASK-05 | `services/biomechanics.py` |
| TASK-06 | `services/report.py`, `routers/analysis.py` |
| TASK-07 | `services/biomechanics.py` |
| TASK-08 | `services/vision.py` |
| TASK-09 | `services/video.py` |
| TASK-10 | `services/video.py` |
| TASK-11 | `services/biomechanics.py` |
| TASK-12 | `models.py`, `routers/analysis.py`, 新增 `services/pipeline_version.py` |
| TASK-13 | `routers/analysis.py` |
| TASK-14 | `services/report.py`, `services/vision.py` |
| TASK-15 | `routers/analysis.py`, `models.py` |
| TASK-16 | `services/action_profiles.py` |
| TASK-17 | `services/action_profiles.py` |
| TASK-18 | `services/action_profiles.py` |
| TASK-19 | 新增 `services/phase_smoother.py`，`routers/analysis.py` |
| TASK-20 | `services/action_profiles.py`（新增字典），`services/vision.py` |
| TASK-21 | `services/action_profiles.py` |

---

*文档由人工 code review + AI 辅助分析生成，基于 2026-04-29 版本代码包。*
