
## 一、v2.4 之后新发现的事实

### 1. `request_text_completion` 已经是 Claude 兼容入口 —— 但 Path A/B 直接用 `AsyncOpenAI` 绕开了它

`providers.py` 里 `request_text_completion()` 会判断 `is_claude_compatible_provider()` 走不同路径。但 `vision.py::analyze_frames` 自己直接 `AsyncOpenAI(...)`，**完全没走 `request_text_completion`**——这意味着 vision 路径**不支持 Claude 兼容 provider**。

v2.4 的 Path A/B 抄了 `analyze_frames` 的写法，等于继承了这个**已知局限**。这是现状，v2.5 沿用即可，但要在文档里写明。

### 2. `default_extra_body` 工具函数已存在

`providers.py:33` 已经有 `default_extra_body(model_id)`，处理 qwen3.6-plus 的 `enable_thinking=False`。v2.4 的 Path A 调用了它（✅），但 Path B 没用——直接抄了 vision.py 的内联写法。**v2.5 统一用 `default_extra_body`**，免得 model_id 列表分散维护。

### 3. `normalize_vision_payload` 会**丢弃 Path A 的额外字段**

仔细看 `normalize_vision_payload` 的实现：它只输出 `frame_analysis / action_phase_summary / overall_raw_text` **三个字段**，其他字段全部丢掉。

v2.4 里 Path A 的做法是：
```python
normalized = normalize_vision_payload(parsed, frame_payloads)
normalized["pure_vision_subscores"] = parsed.get("pure_vision_subscores")  # 后注入
```

这是**对的**，但写得不够显式。v2.5 改用包装函数 `_normalize_path_a()` 集中处理，避免未来有人改 `normalize_vision_payload` 时漏掉。

### 4. `fuse_subscores` 的 bio 输入并不是整个 bio_data —— 而且只在 `key_frames` 非空时才生效

```python
# report.py 现状
bio_sub = None
if isinstance(bio_data, dict) and bio_data.get("key_frames"):
    bio_sub = bio_data.get("bio_subscores") if ... else None
```

**关键发现**：
- 非 jump profile（spin/spiral/step）的 `key_frames={}`，所以 `bio_sub = None`，**bio 子分根本不参与融合**！
- 这是个**预存的 bug**：spiral 跳跃以外的项目，bio 计算了 `bio_subscores` 却完全没用上。
- 双路场景下，Path B 在 spiral 时其实是**唯一的 bio 信号来源**。
- v2.5 不修这个 bug（超出范围），但在文档中**明确指出**，让宿主决定要不要顺手修。

### 5. `extract_motion_sampled_frames` 异常 fallback 路径的 timestamp 是**错的**

```python
records = [{"frame_id": p.stem, "source_thumb_index": i, "timestamp": round(i / FRAME_RATE, 3), ...} for i, p in enumerate(paths)]
```

注意：fallback 里 `timestamp` 用的是 `i / FRAME_RATE`，**没加 window_start 偏移**。这意味着 `build_timestamp_map` 在 fallback 路径返回的 ts 不准确。这不在 v2.5 修复范围（属于 video.py 的独立 bug），但 Path A/B 的 prompt 不应过度依赖 ts 的绝对精度。**v2.5 在文档里加一条 "ts 仅用于排序参考，不作物理量"**。

### 6. `pose_data["frames"][i]` 可能包含 `keypoints: []`（追踪丢失）

`pose.py:172` 处看到 lost 状态时 `keypoints: []`。`build_pose_by_stem` 收进来后，对应 stem 在 `annotate_frames_batch` 里就是 `kps=[]` → 原样复制。这是**期望行为**，文档里要明示，避免有人误以为是 bug。

### 7. `extract_motion_sampled_frames` 默认抽 **20 帧**（`FRAME_SAMPLE_COUNT=20`）

v2.4 的 Path B token 预算 `1000 + 20*380 = 8600`，**会撞到 cap=8000**。在采样前 Path B 已经过 `sample_frames_path_b` 降到 ≤10，所以实际不会越界。但 v2.5 把这个安全边界写进 assertion。

---

## 二、v2.5 相对 v2.4 的改动清单（最终敲定）

| # | 改动 | 原因 |
|---|------|------|
| C1 | Path B 改用 `default_extra_body(provider.model_id)` | 统一 qwen3.6-plus 等模型的 extra_body 处理 |
| C2 | 抽取 `_normalize_path_a_payload()` 包装函数 | 显式声明扩展字段保留逻辑 |
| C3 | 明确 Path A/B **不支持 Claude 兼容 provider**，文档化 | 与现有 `analyze_frames` 行为对齐 |
| C4 | `sample_frames_path_b` 上限 `min(PATH_B_MAX_FRAMES, len(input))` | 防御 input 突变到 30+ |
| C5 | `bio_context.py` 增加 `air_time_seconds / rotation_rps` 等**全局 jump_metrics** 摘要 | Path B 整体提示里加入，提升 jump 判断质量 |
| C6 | `vision_dual.py` 加 `dual_path_summary` 工具函数 | 让宿主一行代码就能生成给前端展示的"分析质量"卡片数据 |
| C7 | 显式声明：`AnalysisErrorCode.UNKNOWN_ERROR` 用于双路整体超时 | 走宿主侧 `classify_ai_failure` 链路 |
| C8 | Path A `temperature=0.1`（与现有 `analyze_frames` 一致）而非 0.05 | 避免与现有调用产生显著行为分裂；差异化由"是否带骨架/bio"承担 |
| C9 | `tests/` 增加 **vision_path_b 软失败传染检查**：Path B 失败不能污染 Path A 的结果 | 双路并发的隔离断言 |
| C10 | 加附录 E："已知预存问题清单"（fuse_subscores spiral bug、ts fallback bug、Claude 兼容限制） | 给后续迭代留线索 |

---

## 三、产出：v2.5 任务书

```markdown
# skating_vision 双路交叉验证迭代 · Codex 任务书 v2.5

> 版本：v2.5 · 2026-05-11
> 范围：仅 SDK 层（`skating_vision/` 包内）。宿主侧改动在 v2.5-host 单独任务书。
> 前置：当前 `skating_vision` 1.x（13 个文件，README 中 `__init__.py` 列举的全部符号稳定）
> 相对 v2.4 的精修要点：默认参数对齐现有 vision/report、provider extra_body 统一、jump_metrics 摘要进 Path B、新增 dual_path_summary 工具
>
> ⚠️ 阅读顺序：本文档先读 §一 "设计原则" 和 §二 "契约映射"，再按 TASK 顺序执行。
> 每个 TASK 验收通过后再继续，禁止跳序。

---

## 一、设计原则（执行前必读）

1. **零破坏**：现有 `analyze_frames` / `generate_report` / `FramePayload` 签名不动；
   新增字段一律给默认值，旧调用方零修改即可继续工作
2. **依赖注入**：所有新函数沿用现有 SDK 风格 —— provider / config 由调用方传入；
   **禁止在 SDK 内部读取业务级环境变量**（不要写 `DUAL_PATH_ENABLED=os.getenv(...)`）
3. **可独立调用**：双路是 opt-in。宿主可以只调 `analyze_frames`，也可以调 `analyze_frames_dual`
4. **错误约定**：
   - **硬错**（Path A、报告、整体失败）→ 抛 `AnalysisPipelineError(AnalysisErrorCode.xxx)`
   - **软错**（双路中 Path B 单独失败）→ 返回 `{"error": "..."}` dict，**不抛**
5. **LLM 不打加权分**：`fuse_subscores(ai, bio)` 仍是唯一融合点；
   LLM 仅产出 `data_quality` 等元数据，不参与 0.4/0.6 加权
6. **provider 限制**：Path A/B 直连 `AsyncOpenAI`（与现有 `analyze_frames` 一致），
   **不支持 Claude 兼容 provider**。这是现状，本任务不打算修
7. **timestamp 仅用于排序参考**：现有 `extract_motion_sampled_frames` 的异常 fallback 路径
   不加 window_start 偏移，prompt 中不要把 ts 当物理量使用

---

## 二、与现有 SDK 的契约映射

| 现有契约 | 双路如何对接 |
|---------|------------|
| `FramePayload`（slots dataclass） | 加 `timestamp_sec: float = 0.0` 默认值字段 |
| `encode_frames(frame_paths)` | 加可选 `timestamps` 参数，向后兼容 |
| `extract_motion_sampled_frames` 返回的 `payload["selected"][i]["timestamp"]` | 双路读取此处构造 ts_map |
| `infer_analysis_profile()` 返回 `(profile, evidence)` | `profile`→`analysis_profile`，`evidence`→`profile_evidence` |
| `pose_data["frames"][i]["frame"]`（含 `.jpg`）| `build_pose_by_stem` 内部去后缀 |
| `pose_data["frames"][i]["keypoints"]` 可能为 `[]`（lost）| 标注阶段原样复制源帧，不抛 |
| `analyze_biomechanics` 返回的 `knee_angles/trunk_tilts/arm_symmetry` 用 `frame_idx`（1-based）| `bio_context.py` 转换为 stem 索引 |
| `bio_data["key_frames"]` 仅 jump 有，非 jump 为 `{}` | Path B 关键帧采样自动退回均匀 |
| `bio_data["jump_metrics"]` 含 air_time/height/speed/rps（仅 jump） | Path B prompt 顶部注入摘要（v2.5 新增） |
| `analyze_frames` 输出经 `normalize_vision_payload` | Path A 也走同一 normalize（保前端兼容），扩展字段后注入 |
| `generate_report(action_type, vision_structured, provider, bio_data, memory_context)` | 加 `dual_path_meta` 可选 kwarg，注入 prompt 与 `data_quality` |
| `fuse_subscores(ai, bio)` | **保持不变**；LLM 不参与加权 |
| `default_extra_body(model_id)` | 所有新发起 chat completion 的地方统一调用 |
| `AnalysisPipelineError(AnalysisErrorCode.AI_RESPONSE_PARSE_FAIL)` | Path A、报告解析失败时抛；Path B 内部 catch 不抛 |
| `AnalysisPipelineError(AnalysisErrorCode.AI_API_TIMEOUT)` | 双路整体 wait_for 超时时由宿主感知（dual 内部转 UNKNOWN_ERROR 软处理） |

---

## 三、执行顺序

```
TASK-V01  修改 types.py            → FramePayload 加 timestamp_sec
TASK-V02  修改 video.py            → encode_frames 加 timestamps 参数 + build_timestamp_map
TASK-V03  新建 frame_annotator.py  → 骨架叠加（ASCII 标签）
TASK-V04  新建 bio_context.py      → per-stem bio + jump_metrics 摘要
TASK-V05  新建 vision_path_a.py    → 复用 normalize_vision_payload + 扩展字段
TASK-V06  新建 vision_path_b.py    → 骨架帧 + bio 数值 + jump_metrics 摘要
TASK-V07  新建 cross_validator.py  → 比对 + skeleton_signal + blend_weights
TASK-V08  修改 report.py           → 加 dual_path_meta 可选参数
TASK-V09  新建 vision_dual.py      → analyze_frames_dual + dual_path_summary
TASK-V10  修改 __init__.py         → export 新符号
TASK-V11  新增 tests/test_dual_path.py → 端到端 + 软失败隔离断言
```

---

## TASK-V01：修改 `types.py`

### 代码

```python
# skating_vision/types.py
from __future__ import annotations
from dataclasses import dataclass


@dataclass(slots=True)
class FramePayload:
    frame_id:      str
    data_url:      str
    timestamp_sec: float = 0.0   # ← 新增，默认 0.0 保证向后兼容


@dataclass(slots=True)
class VideoSamplingMetadata:
    action_window_start: float
    action_window_end:   float
    source_fps:          float
    is_slow_motion:      bool
```

### 验收

```
1. 旧调用 FramePayload(frame_id="x", data_url="y") 不报错
2. 新调用 FramePayload(frame_id="x", data_url="y", timestamp_sec=1.4) 正常
3. analyze_frames（vision.py）未修改即可继续运行
4. mypy/pyright 不报错
```

---

## TASK-V02：修改 `video.py::encode_frames` + 新增 `build_timestamp_map`

### 修改 encode_frames

```python
async def encode_frames(
    frame_paths: Sequence[Path],
    timestamps:  dict[str, float] | None = None,   # ← 新增可选参数
) -> list[FramePayload]:
    """
    timestamps: dict 映射 frame_path.stem → 时间戳（秒）。
    不传时所有 payload.timestamp_sec=0.0，与旧版完全等价。
    """
    payloads: list[FramePayload] = []
    ts_map = timestamps or {}
    for p in frame_paths:
        async with aiofiles.open(p, "rb") as f:
            binary = await f.read()
        payloads.append(FramePayload(
            frame_id      = p.stem,
            data_url      = f"data:image/jpeg;base64,{base64.b64encode(binary).decode()}",
            timestamp_sec = ts_map.get(p.stem, 0.0),
        ))
    return payloads
```

### 新增 build_timestamp_map

```python
def build_timestamp_map(sampling_payload: dict[str, object] | None) -> dict[str, float]:
    """
    从 extract_motion_sampled_frames 第二个返回值构造 frame_id(stem) → 秒数映射。
    
    ⚠️ 现有 fallback 路径的 timestamp 未加 window_start 偏移，
    仅作排序/相对位置参考，不要当物理时间使用。
    """
    if not isinstance(sampling_payload, dict):
        return {}
    selected = sampling_payload.get("selected")
    if not isinstance(selected, list):
        return {}
    out: dict[str, float] = {}
    for rec in selected:
        if not isinstance(rec, dict):
            continue
        fid = rec.get("frame_id")
        ts  = rec.get("timestamp")
        if isinstance(fid, str) and isinstance(ts, (int, float)):
            out[fid] = float(ts)
    return out
```

### 验收

```
1. encode_frames(paths) 不传 timestamps → 输出与旧版字节等价
2. encode_frames(paths, timestamps={"frame_0001": 1.4}) → frame_0001 的 ts=1.4
3. build_timestamp_map(payload) 处理正常 payload → 返回非空 dict
4. build_timestamp_map(None / {} / {"selected": "not a list"}) → 返回 {}
5. 现有 analyze_frames 调用未受影响（手动 grep 确认）
```

---

## TASK-V03：新建 `frame_annotator.py`

### 关键决定

- ASCII 标签（LKnee/RKnee/LElbow/RElbow），避免 `cv2.putText` 中文乱码
- key 统一 stem
- cv2/numpy import 失败时降级到原样复制
- pose 追踪 lost 帧（`keypoints=[]`）原样复制，不抛

### 完整代码

```python
# skating_vision/frame_annotator.py
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 颜色 (BGR)；MediaPipe 偶数 id 是运动员右侧
COLOR_RIGHT = (255, 120,   0)
COLOR_LEFT  = (  0, 120, 255)
COLOR_TRUNK = (200, 200, 200)
COLOR_ANGLE = ( 50, 255,  50)

RIGHT_JOINTS = {12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 32}
LEFT_JOINTS  = {11, 13, 15, 17, 19, 21, 23, 25, 27, 29, 31}

POSE_CONNECTIONS = [
    (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
    (11, 23), (12, 24), (23, 24),
    (23, 25), (25, 27), (27, 29), (27, 31),
    (24, 26), (26, 28), (28, 30), (28, 32),
    (0, 11),  (0, 12),
]

# (vertex_id, a_id, b_id, ascii_label)
ANGLE_ANNOTATIONS = [
    (25, 23, 27, "LKnee"),
    (26, 24, 28, "RKnee"),
    (13, 11, 15, "LElbow"),
    (14, 12, 16, "RElbow"),
]

DEFAULT_MIN_VISIBILITY = 0.4


def _safe_copy(src: Path, dst: Path) -> None:
    try:
        shutil.copy2(src, dst)
    except Exception as exc:
        logger.warning("frame_annotator copy fallback failed: %s", exc)


def annotate_frame(
    image_path:     Path,
    keypoints:      list[dict[str, Any]],
    output_path:    Path,
    *,
    draw_angles:    bool  = True,
    min_visibility: float = DEFAULT_MIN_VISIBILITY,
) -> Path:
    """
    叠加骨架 + 关节角度数字。任何异常 → 原样复制，永不抛。
    pose 追踪 lost 时 keypoints=[] → 原样复制（不画）。
    """
    try:
        import cv2
        import numpy as np
    except Exception:
        _safe_copy(image_path, output_path)
        return output_path

    try:
        image = cv2.imread(str(image_path))
        if image is None or not keypoints:
            _safe_copy(image_path, output_path)
            return output_path

        h, w = image.shape[:2]
        kp_map: dict[int, tuple[int, int]] = {}
        for kp in keypoints:
            try:
                if float(kp.get("visibility", 0)) < min_visibility:
                    continue
                kp_map[int(kp["id"])] = (int(float(kp["x"]) * w), int(float(kp["y"]) * h))
            except (TypeError, ValueError, KeyError):
                continue

        for a, b in POSE_CONNECTIONS:
            if a in kp_map and b in kp_map:
                cv2.line(image, kp_map[a], kp_map[b], (160, 160, 160), 2, cv2.LINE_AA)

        for kp_id, (px, py) in kp_map.items():
            color = (COLOR_LEFT  if kp_id in LEFT_JOINTS  else
                     COLOR_RIGHT if kp_id in RIGHT_JOINTS else COLOR_TRUNK)
            cv2.circle(image, (px, py), 5, color, -1, cv2.LINE_AA)
            cv2.circle(image, (px, py), 6, (255, 255, 255), 1, cv2.LINE_AA)

        if draw_angles:
            for vid, aid, bid, label in ANGLE_ANNOTATIONS:
                if not all(i in kp_map for i in (vid, aid, bid)):
                    continue
                v  = np.array(kp_map[vid], dtype=float)
                pa = np.array(kp_map[aid], dtype=float)
                pb = np.array(kp_map[bid], dtype=float)
                ba, bc = pa - v, pb - v
                denom = (np.linalg.norm(ba) * np.linalg.norm(bc)) + 1e-6
                cos_a = float(np.clip(np.dot(ba, bc) / denom, -1.0, 1.0))
                angle = float(np.degrees(np.arccos(cos_a)))
                vx, vy = kp_map[vid]
                cv2.putText(
                    image, f"{label}:{angle:.0f}",
                    (vx + 8, vy - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    COLOR_ANGLE, 1, cv2.LINE_AA,
                )

        cv2.imwrite(str(output_path), image, [cv2.IMWRITE_JPEG_QUALITY, 88])
        return output_path
    except Exception as exc:
        logger.warning("annotate_frame failed for %s: %s", image_path.name, exc)
        _safe_copy(image_path, output_path)
        return output_path


def annotate_frames_batch(
    frame_paths:  list[Path],
    pose_by_stem: dict[str, list[dict[str, Any]]],
    output_dir:   Path,
) -> list[Path]:
    """pose_by_stem key 必须是 frame_path.stem，与 FramePayload.frame_id 对齐。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    result: list[Path] = []
    for fp in frame_paths:
        kps = pose_by_stem.get(fp.stem, [])
        out = output_dir / fp.name
        annotate_frame(fp, kps, out)
        result.append(out)
    return result


def build_pose_by_stem(pose_data: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    """
    从 extract_pose 输出构造 stem → keypoints 映射。
    pose_data['frames'][i]['frame'] 形如 'frame_0001.jpg'（带后缀），需去后缀。
    keypoints 可能为 []（lost 帧），原样收下让 annotate_frame 做原样复制。
    """
    if not isinstance(pose_data, dict):
        return {}
    out: dict[str, list] = {}
    for fr in pose_data.get("frames", []):
        if not isinstance(fr, dict):
            continue
        name = str(fr.get("frame", ""))
        stem = name[:-4] if name.endswith(".jpg") else name
        kps  = fr.get("keypoints") or []
        if stem and isinstance(kps, list):
            out[stem] = kps
    return out
```

### 验收

```
1. cv2 可用 + keypoints 非空 → 输出存在且与原图不同（写过像素）
2. cv2 import 失败 → 原样复制，不抛
3. keypoints=[]（lost 帧）→ 原样复制
4. 标签为 ASCII，不出现 ???
5. build_pose_by_stem('frame_0001.jpg') → key='frame_0001'
6. build_pose_by_stem(None / {}) → {}
```

---

## TASK-V04：新建 `bio_context.py`

### 关键决定

- `frame_idx`（1-based）转 stem
- 缺值不写入（避免 `None` 进 prompt）
- 新增 `summarize_jump_metrics()`：把 `bio_data["jump_metrics"]` 拼成单行 grounding 文本

### 完整代码

```python
# skating_vision/bio_context.py
from __future__ import annotations

import math
from typing import Any


def _safe(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def build_frame_bio_context(
    bio_data:    dict[str, Any] | None,
    frame_stems: list[str],
) -> dict[str, dict[str, float]]:
    """
    把 biomechanics 输出按 stem 重排成 per-frame 测量字典。
    frame_stems 必须按抽帧顺序传入（1-based 索引对应 frame_idx）。

    输出每帧形如：
      {"left_knee_angle": 145.2, "right_knee_angle": 152.0,
       "trunk_tilt_deg": 8.4, "arm_symmetry": 0.93}
    缺测量值的帧不出现在输出字典中。
    """
    if not isinstance(bio_data, dict):
        return {}

    by_idx_knee  = {int(item.get("frame_idx", 0)): item for item in bio_data.get("knee_angles", []) if isinstance(item, dict)}
    by_idx_trunk = {int(item.get("frame_idx", 0)): item for item in bio_data.get("trunk_tilts", []) if isinstance(item, dict)}
    by_idx_arm   = {int(item.get("frame_idx", 0)): item for item in bio_data.get("arm_symmetry", []) if isinstance(item, dict)}

    out: dict[str, dict[str, float]] = {}
    for i, stem in enumerate(frame_stems, start=1):
        knee  = by_idx_knee.get(i, {})
        trunk = by_idx_trunk.get(i, {})
        arm   = by_idx_arm.get(i, {})

        entry: dict[str, float] = {}
        l = _safe(knee.get("left"))
        r = _safe(knee.get("right"))
        if l is not None: entry["left_knee_angle"]  = l
        if r is not None: entry["right_knee_angle"] = r
        t = _safe(trunk.get("tilt_degrees"))
        if t is not None: entry["trunk_tilt_deg"]   = t
        s = _safe(arm.get("symmetry"))
        if s is not None: entry["arm_symmetry"]     = s
        if entry:
            out[stem] = entry
    return out


def extract_key_frame_stems(bio_data: dict[str, Any] | None) -> set[str]:
    """从 bio_data['key_frames'] 提取 stem 集合（仅 jump profile 有效）。"""
    if not isinstance(bio_data, dict):
        return set()
    kf = bio_data.get("key_frames")
    if not isinstance(kf, dict):
        return set()
    return {str(v) for v in kf.values() if isinstance(v, str) and v}


def summarize_jump_metrics(bio_data: dict[str, Any] | None) -> str:
    """
    把 jump_metrics 摘成 ASCII 单段文本。非 jump 或 jump_metrics_status != 'ok' 时返回 ''。
    用于 Path B prompt 顶部 grounding。
    """
    if not isinstance(bio_data, dict):
        return ""
    if bio_data.get("jump_metrics_status") != "ok":
        return ""
    jm = bio_data.get("jump_metrics")
    if not isinstance(jm, dict):
        return ""
    parts = []
    if (v := _safe(jm.get("air_time_seconds")))    is not None: parts.append(f"AirTime={v:.2f}s")
    if (v := _safe(jm.get("estimated_height_cm"))) is not None: parts.append(f"Height={v:.1f}cm")
    if (v := _safe(jm.get("takeoff_speed_mps")))   is not None: parts.append(f"VTakeoff={v:.2f}m/s")
    if (v := _safe(jm.get("rotation_rps")))        is not None: parts.append(f"Rot={v:.2f}rps")
    return " | ".join(parts)
```

### 验收

```
1. 有效 bio_data + 20 个 stem → build_frame_bio_context 返回 ≥1 entry
2. left/right 均 None → 该 stem 不出现
3. extract_key_frame_stems jump → {"frame_0017","frame_0021","frame_0025"}
4. extract_key_frame_stems spiral/spin（key_frames={}）→ set()
5. summarize_jump_metrics jump ok → "AirTime=0.45s | Height=24.8cm | ..."
6. summarize_jump_metrics 非 jump 或 status!='ok' → ""
7. 全 None 输入不抛
```

---

## TASK-V05：新建 `vision_path_a.py`

### 关键决定

- 输出走 `normalize_vision_payload`（兼容现有 vision_structured 消费者）
- 扩展字段（`pure_vision_subscores` / `path` / `path_desc`）通过 **`_normalize_path_a_payload` 包装**显式注入，避免有人改 normalize_vision_payload 时漏掉
- **temperature=0.1**（与现有 `analyze_frames` 一致），差异化由 prompt 决定
- 用 `default_extra_body`
- 失败抛 `AnalysisPipelineError`（硬错）

### 完整代码

```python
# skating_vision/vision_path_a.py
from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI

from skating_vision.analysis_errors import AnalysisErrorCode, AnalysisPipelineError
from skating_vision.providers import ActiveProviderConfig, extract_message_text, default_extra_body
from skating_vision.report import clean_json_text
from skating_vision.types import FramePayload
from skating_vision.vision import normalize_vision_payload

logger = logging.getLogger(__name__)

PATH_A_TEMPERATURE       = 0.1
PATH_A_MAX_TOKENS_BASE   = 800
PATH_A_MAX_TOKENS_FRAME  = 280
PATH_A_MAX_TOKENS_CAP    = 8000

PATH_A_SYSTEM = (
    "你是拥有 10 年执教经验的花样滑冰专项教练，本次以场边肉眼观察的视角分析。"
    "**不引入任何骨架或测量数据**，只基于画面给出第一直觉判断。"
    "严格输出 JSON，禁止任何额外文字。"
)


def _build_user_prompt(
    action_type:      str,
    action_subtype:   str | None,
    analysis_profile: str | None,
    profile_evidence: dict[str, Any] | None,
    n_frames:         int,
) -> str:
    ev = json.dumps(profile_evidence or {}, ensure_ascii=False)
    return (
        f"分析以下【{action_type}】动作帧序列（共 {n_frames} 帧，按时间顺序排列）。\n"
        f"动作子类型：{action_subtype or '未指定'}\n"
        f"分析 profile：{analysis_profile or 'unknown'}\n"
        f"规则证据：{ev}\n"
        "重要约束：燕式滑行/螺旋线不要误判为跳跃，除非存在清晰的起跳/腾空/落冰证据。\n\n"
        "**纯视觉判断**（不要假设任何测量数据），每一帧输出以下结构化数据：\n\n"
        '{"frame_analysis":[{"frame_id":"frame_0001",'
        '"phase":"准备|起跳|腾空|落冰|滑出|旋转入|旋转中|旋转出|步法|不可分析",'
        '"observations":{"knee_bend":"充分|不足|过度|不适用",'
        '"arm_position":"正确|偏高|偏低|不对称|不适用",'
        '"axis_alignment":"垂直|前倾|后仰|侧倾|不适用",'
        '"blade_edge":"外刃|内刃|平刃|不适用",'
        '"core_stability":"稳定|轻微晃动|明显晃动|不适用",'
        '"landing_absorption":"良好|不足|过度|不适用"},'
        '"issues":["问题描述"],"positives":["优点描述"],"confidence":0.0}],'
        '"action_phase_summary":{"detected_phases":["起跳","腾空","落冰"],'
        '"weakest_phase":"最需改进的阶段","strongest_phase":"表现最好的阶段"},'
        '"pure_vision_subscores":{"takeoff_power":0,"rotation_axis":0,'
        '"arm_coordination":0,"landing_absorption":0,"core_stability":0},'
        '"overall_raw_text":"综合文字描述 2-3 句"}\n\n'
        "必须只输出 JSON。"
    )


def _normalize_path_a_payload(
    parsed:         dict[str, Any],
    frame_payloads: list[FramePayload],
) -> dict[str, Any]:
    """
    走 normalize_vision_payload 保兼容，再显式注入扩展字段。
    注意：normalize_vision_payload 当前只保留 frame_analysis/action_phase_summary/overall_raw_text，
    pure_vision_subscores 等扩展字段必须在这里后注入，否则会丢。
    """
    normalized = normalize_vision_payload(parsed, frame_payloads)
    subs = parsed.get("pure_vision_subscores")
    normalized["pure_vision_subscores"] = subs if isinstance(subs, dict) else {}
    normalized["path"]      = "A"
    normalized["path_desc"] = "纯视觉判断（与 analyze_frames schema 兼容）"
    return normalized


async def analyze_path_a(
    action_type:      str,
    frame_payloads:   list[FramePayload],
    provider:         ActiveProviderConfig,
    *,
    action_subtype:   str | None = None,
    analysis_profile: str | None = None,
    profile_evidence: dict[str, Any] | None = None,
    memory_context:   str = "",
) -> dict[str, Any]:
    """
    Path A：纯视觉分析。签名与 analyze_frames 对等。
    失败抛 AnalysisPipelineError（与 analyze_frames 一致）。

    注意：与 analyze_frames 一样直连 AsyncOpenAI，
    **不支持 Claude 兼容 provider**（已知局限）。
    """
    if not frame_payloads:
        raise AnalysisPipelineError(
            AnalysisErrorCode.FRAME_EXTRACT_FAILED,
            "Path A 无可分析帧",
        )

    n = len(frame_payloads)
    max_tokens = min(PATH_A_MAX_TOKENS_CAP, PATH_A_MAX_TOKENS_BASE + n * PATH_A_MAX_TOKENS_FRAME)

    client = AsyncOpenAI(
        api_key=provider.api_key, base_url=provider.base_url,
        timeout=90.0, max_retries=0,
    )

    sys_prompt = PATH_A_SYSTEM if not memory_context else f"{PATH_A_SYSTEM}\n\n{memory_context}"
    user_text  = _build_user_prompt(action_type, action_subtype, analysis_profile, profile_evidence, n)

    content: list[dict[str, object]] = [{"type": "text", "text": user_text}]
    for f in frame_payloads:
        content.append({"type": "text", "text": f"帧编号：{f.frame_id} | 时间：{f.timestamp_sec:.2f}s"})
        content.append({"type": "image_url", "image_url": {"url": f.data_url}})

    resp = await client.chat.completions.create(
        model       = provider.model_id,
        temperature = PATH_A_TEMPERATURE,
        max_tokens  = max_tokens,
        extra_body  = default_extra_body(provider.model_id),
        messages    = [
            {"role": "system", "content": sys_prompt},
            {"role": "user",   "content": content},
        ],
    )

    raw     = extract_message_text(resp.choices[0].message.content)
    cleaned = clean_json_text(raw)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.warning("Path A JSON parse failed: %s; raw[:500]=%r", exc, cleaned[:500])
        raise AnalysisPipelineError(
            AnalysisErrorCode.AI_RESPONSE_PARSE_FAIL,
            f"Path A JSON parse failed: {exc}: {cleaned[:500]}",
        ) from exc

    return _normalize_path_a_payload(parsed, frame_payloads)
```

### 验收

```
1. 输出可被现有前端/fuse_subscores 消费（含 frame_analysis / action_phase_summary）
2. 输出含 path='A' + pure_vision_subscores
3. JSON 解析失败 → 抛 AnalysisPipelineError(AI_RESPONSE_PARSE_FAIL)
4. frame_payloads=[] → 抛 AnalysisPipelineError(FRAME_EXTRACT_FAILED)
5. temperature=0.1（与 analyze_frames 一致）
6. provider.model_id="qwen3.6-plus" → extra_body={"enable_thinking": False}
7. max_tokens=min(8000, 800+n*280)
```

---

## TASK-V06：新建 `vision_path_b.py`

### 关键决定

- **软失败**：所有异常 catch，返回 `{"error": ...}`，不抛
- 关键帧采样优先；无 key_frames 退回均匀 10 帧
- jump_metrics 摘要进 prompt 顶部 grounding
- temperature=0.25（与 Path A 拉开差异）
- 用 `default_extra_body`

### 完整代码

```python
# skating_vision/vision_path_b.py
from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI

from skating_vision.providers import ActiveProviderConfig, extract_message_text, default_extra_body
from skating_vision.report import clean_json_text
from skating_vision.types import FramePayload

logger = logging.getLogger(__name__)

PATH_B_TEMPERATURE       = 0.25
PATH_B_MAX_FRAMES        = 10
PATH_B_CONTEXT_WIN       = 2
PATH_B_MAX_TOKENS_BASE   = 1000
PATH_B_MAX_TOKENS_FRAME  = 380
PATH_B_MAX_TOKENS_CAP    = 8000

PATH_B_SYSTEM = (
    "你是花样滑冰生物力学分析专家。"
    "每帧图像已叠加 MediaPipe 骨架与角度数字（ASCII 标签：LKnee/RKnee/LElbow/RElbow）。"
    "请结合图像和文字测量值综合判断。"
    "严格输出 JSON，禁止任何额外文字。"
)


def sample_frames_path_b(
    frame_payloads: list[FramePayload],
    key_stems:      set[str] | None = None,
    n_context:      int = PATH_B_CONTEXT_WIN,
    max_frames:     int = PATH_B_MAX_FRAMES,
) -> list[FramePayload]:
    """关键帧 ±n_context 上下文采样；无 key_stems 时均匀采样。"""
    cap = min(max_frames, len(frame_payloads))
    if not key_stems:
        if len(frame_payloads) <= cap:
            return list(frame_payloads)
        step = len(frame_payloads) / cap
        return [frame_payloads[int(i * step)] for i in range(cap)]

    selected: set[int] = set()
    for i, fp in enumerate(frame_payloads):
        if fp.frame_id in key_stems:
            selected.update(range(
                max(0, i - n_context),
                min(len(frame_payloads), i + n_context + 1),
            ))
    if not selected:
        return sample_frames_path_b(frame_payloads, None, n_context, max_frames)
    # 防御：邻域过大时再裁剪到 max_frames
    indices = sorted(selected)[:max_frames]
    return [frame_payloads[i] for i in indices]


def _build_bio_text(bio: dict[str, float] | None) -> str:
    if not bio:
        return ""
    parts = ["  [Measurements]"]
    for k, label, unit in [
        ("left_knee_angle",  "LKnee",     "deg"),
        ("right_knee_angle", "RKnee",     "deg"),
        ("trunk_tilt_deg",   "TrunkTilt", "deg(0=vertical)"),
        ("arm_symmetry",     "ArmSym",    "(1.0=symmetric)"),
    ]:
        v = bio.get(k)
        if v is None:
            continue
        try:
            parts.append(f"  {label}={float(v):.2f}{unit}")
        except (TypeError, ValueError):
            continue
    return "\n".join(parts) if len(parts) > 1 else ""


def _build_user_prompt(
    action_type:        str,
    action_subtype:     str | None,
    analysis_profile:   str | None,
    profile_evidence:   dict[str, Any] | None,
    jump_metrics_text:  str,
    n_frames:           int,
) -> str:
    blocks: list[str] = []
    if analysis_profile or profile_evidence:
        blocks.append(
            "【动作识别已知信息 · 请勿推翻】\n"
            f"  分析 profile：{analysis_profile or 'unknown'}\n"
            f"  规则证据：{json.dumps(profile_evidence or {}, ensure_ascii=False)}"
        )
    if jump_metrics_text:
        blocks.append(f"【整体生物力学摘要】\n  {jump_metrics_text}")
    grounding = ("\n\n".join(blocks) + "\n\n") if blocks else ""

    body = (
        f"分析【{action_type}】动作（共 {n_frames} 帧，骨架已叠加，按时间顺序）。\n"
        f"动作子类型：{action_subtype or '未指定'}\n\n"
        "每帧图像前附有该帧测量值，请结合数值和图像综合判断。\n\n"
        "输出严格符合下方 schema 的 JSON：\n"
        '{"frame_analysis":[{"frame_id":"frame_0001",'
        '"phase":"准备|起跳|腾空|落冰|滑出|旋转入|旋转中|旋转出|步法|不可分析",'
        '"bio_observations":{"knee_angle_assessment":"<=25字",'
        '"axis_assessment":"<=25字","arm_symmetry_assessment":"<=25字",'
        '"overall_bio_quality":"<=25字"},'
        '"confidence":0.0}],'
        '"action_phase_summary":{"detected_phases":[],"weakest_phase":"","strongest_phase":""},'
        '"subscores":{"takeoff_power":0,"rotation_axis":0,'
        '"arm_coordination":0,"landing_absorption":0,"core_stability":0},'
        '"top_issues":["最多3条，必须引用具体测量数值"],'
        '"top_positives":["最多2条，结合量化数据"]}\n\n'
        "必须只输出 JSON。"
    )
    return grounding + body


def _fallback(error: str) -> dict[str, Any]:
    return {
        "path":  "B",
        "error": error,
        "frame_analysis": [],
        "subscores": {},
        "action_phase_summary": {"detected_phases": [], "weakest_phase": "", "strongest_phase": ""},
        "top_issues": [],
        "top_positives": [],
    }


async def analyze_path_b(
    action_type:              str,
    annotated_frame_payloads: list[FramePayload],
    provider:                 ActiveProviderConfig,
    *,
    frame_bio_context:        dict[str, dict[str, float]] | None = None,
    key_frame_stems:          set[str] | None = None,
    jump_metrics_text:        str = "",
    action_subtype:           str | None = None,
    analysis_profile:         str | None = None,
    profile_evidence:         dict[str, Any] | None = None,
    memory_context:           str = "",
) -> dict[str, Any]:
    """
    Path B：骨架帧 + bio 数值 grounding。
    **软失败**：任何异常 → 返回含 'error' 字段 dict，不抛。
    **不支持 Claude 兼容 provider**（已知局限，与 analyze_frames 一致）。
    """
    if not annotated_frame_payloads:
        return _fallback("no frames")

    try:
        frames = sample_frames_path_b(annotated_frame_payloads, key_frame_stems)
        n = len(frames)
        if n == 0:
            return _fallback("sampling produced 0 frames")

        max_tokens = min(PATH_B_MAX_TOKENS_CAP, PATH_B_MAX_TOKENS_BASE + n * PATH_B_MAX_TOKENS_FRAME)

        client = AsyncOpenAI(
            api_key=provider.api_key, base_url=provider.base_url,
            timeout=90.0, max_retries=0,
        )

        sys_prompt = PATH_B_SYSTEM if not memory_context else f"{PATH_B_SYSTEM}\n\n{memory_context}"
        user_text  = _build_user_prompt(
            action_type, action_subtype, analysis_profile,
            profile_evidence, jump_metrics_text, n,
        )

        bio_ctx = frame_bio_context or {}
        content: list[dict[str, object]] = [{"type": "text", "text": user_text}]
        for f in frames:
            label = f"帧编号：{f.frame_id} | 时间：{f.timestamp_sec:.2f}s"
            bio_text = _build_bio_text(bio_ctx.get(f.frame_id))
            if bio_text:
                label += "\n" + bio_text
            content.append({"type": "text",      "text": label})
            content.append({"type": "image_url", "image_url": {"url": f.data_url}})

        resp = await client.chat.completions.create(
            model       = provider.model_id,
            temperature = PATH_B_TEMPERATURE,
            max_tokens  = max_tokens,
            extra_body  = default_extra_body(provider.model_id),
            messages    = [
                {"role": "system", "content": sys_prompt},
                {"role": "user",   "content": content},
            ],
        )

        raw     = extract_message_text(resp.choices[0].message.content)
        cleaned = clean_json_text(raw)
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.warning("Path B JSON parse failed: %s; raw[:500]=%r", exc, cleaned[:500])
            return _fallback(f"json_parse: {exc}")

        if not isinstance(parsed, dict):
            return _fallback("response is not a dict")

        parsed["path"]      = "B"
        parsed["path_desc"] = "量化 grounding（骨架帧 + bio 数值）"
        parsed["n_frames"]  = n
        parsed.setdefault("frame_analysis", [])
        parsed.setdefault("subscores", {})
        parsed.setdefault("action_phase_summary", {"detected_phases": [], "weakest_phase": "", "strongest_phase": ""})
        parsed.setdefault("top_issues", [])
        parsed.setdefault("top_positives", [])
        return parsed

    except Exception as exc:
        logger.error("Path B soft-failure: %s", exc, exc_info=True)
        return _fallback(str(exc))
```

### 验收

```
1. annotated_frame_payloads=[] → 返回 {"error":"no frames"}，不抛
2. provider api_key 错误 → 返回 {"error":...}，不抛（软失败）
3. key_frame_stems={"frame_0021"} → frame_0021 ± 2 邻域被选中
4. key_frame_stems=None → 均匀采样 ≤10 帧
5. key_frame_stems 与现有 frame_id 无交集 → 退回均匀采样
6. frame_bio_context 命中 → prompt 含 "LKnee=145.20deg"
7. jump_metrics_text="AirTime=0.45s..." → prompt 顶部含【整体生物力学摘要】
8. 成功路径返回 dict 含 path/subscores/frame_analysis/action_phase_summary/n_frames
9. 输入 30 帧时采样不超过 10 帧
```

---

## TASK-V07：新建 `cross_validator.py`

> 此文件代码与 v2.4 完全一致，verbatim 复制即可。要点：
> - 客观维度（rotation_axis / core_stability）阈值更严
> - 仅客观维度多处 major → likely_wrong
> - compute_blend_weights 显式处理单路情形

### 完整代码（与 v2.4 一致，列出便于复制）

```python
# skating_vision/cross_validator.py
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


SUBSCORE_KEYS = [
    "takeoff_power", "rotation_axis", "arm_coordination",
    "landing_absorption", "core_stability",
]

OBJECTIVE_FIELDS = {"rotation_axis", "core_stability"}

AGREE_THRESHOLD = {"objective": 6,  "subjective": 10}
MINOR_THRESHOLD = {"objective": 15, "subjective": 22}


@dataclass(slots=True)
class FieldValidation:
    field_name:   str
    path_a_value: Any
    path_b_value: Any
    agreement:    str
    confidence:   float
    note:         str = ""


@dataclass(slots=True)
class CrossValidationReport:
    overall_agreement_rate:      float
    skeleton_reliability_signal: str
    field_validations:           list[FieldValidation]
    high_confidence_fields:      list[str]
    conflict_fields:             list[str]
    recommended_path:            str
    conflict_summary:            str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["field_validations"] = [asdict(v) for v in self.field_validations]
        return d


def _classify(field: str, diff: int) -> tuple[str, float]:
    kind = "objective" if field in OBJECTIVE_FIELDS else "subjective"
    if diff <= AGREE_THRESHOLD[kind]:
        return "agree", round(1.0 - diff / 100, 3)
    if diff <= MINOR_THRESHOLD[kind]:
        return "minor_conflict", round(max(0.0, 0.6 - diff / 100), 3)
    return "major_conflict", round(max(0.1, 0.4 - diff / 100), 3)


def _compare_phases(a: list[str], b: list[str]) -> FieldValidation:
    sa, sb = set(a), set(b)
    j = (len(sa & sb) / len(sa | sb)) if (sa | sb) else 1.0
    if   j >= 0.7: agr, conf = "agree",          j
    elif j >= 0.4: agr, conf = "minor_conflict", j * 0.7
    else:          agr, conf = "major_conflict", j * 0.4
    return FieldValidation("detected_phases", a, b, agr, round(conf, 3), f"jaccard={j:.2f}")


def _compare_subscores(a: dict, b: dict) -> list[FieldValidation]:
    out: list[FieldValidation] = []
    for key in SUBSCORE_KEYS:
        av, bv = a.get(key), b.get(key)
        if av is None or bv is None:
            out.append(FieldValidation(key, av, bv, "missing", 0.5))
            continue
        try:
            diff = abs(int(av) - int(bv))
        except (TypeError, ValueError):
            out.append(FieldValidation(key, av, bv, "missing", 0.5, "non-numeric"))
            continue
        agr, conf = _classify(key, diff)
        out.append(FieldValidation(key, av, bv, agr, conf, f"diff={diff}"))
    return out


def _single_path_report(which: str, reason: str) -> CrossValidationReport:
    return CrossValidationReport(
        overall_agreement_rate=0.5, skeleton_reliability_signal="unknown",
        field_validations=[], high_confidence_fields=[], conflict_fields=[],
        recommended_path=which, conflict_summary=reason,
    )


def cross_validate(
    path_a: dict[str, Any] | None,
    path_b: dict[str, Any] | None,
) -> CrossValidationReport:
    a_ok = bool(path_a and not path_a.get("error"))
    b_ok = bool(path_b and not path_b.get("error"))

    if not a_ok and not b_ok:
        return CrossValidationReport(0.0, "unknown", [], [], [], "neither", "两路分析均失败。")
    if not a_ok: return _single_path_report("B", "Path A 失败，仅使用 Path B。")
    if not b_ok: return _single_path_report("A", "Path B 失败，仅使用 Path A。")

    validations: list[FieldValidation] = [
        _compare_phases(
            (path_a.get("action_phase_summary") or {}).get("detected_phases", []),
            (path_b.get("action_phase_summary") or {}).get("detected_phases", []),
        )
    ]
    validations.extend(_compare_subscores(
        path_a.get("pure_vision_subscores", {}) or {},
        path_b.get("subscores", {}) or {},
    ))

    weight = {"agree": 1.0, "minor_conflict": 0.5, "major_conflict": 0.0, "missing": 0.5}
    overall = sum(weight[v.agreement] for v in validations) / len(validations)

    objective_majors = sum(
        1 for v in validations
        if v.agreement == "major_conflict" and v.field_name in OBJECTIVE_FIELDS
    )
    total_majors = sum(1 for v in validations if v.agreement == "major_conflict")

    if objective_majors >= 2:
        skeleton = "likely_wrong"
    elif total_majors >= 3:
        skeleton = "uncertain"
    elif total_majors == 0:
        skeleton = "reliable"
    else:
        skeleton = "uncertain"

    if   overall >= 0.75:            recommended = "blend"
    elif skeleton == "likely_wrong": recommended = "A"
    elif skeleton == "reliable":     recommended = "blend"
    else:                            recommended = "blend"

    conflict_fields  = [v.field_name for v in validations if "conflict" in v.agreement]
    high_conf_fields = [v.field_name for v in validations if v.agreement == "agree"]

    signal_text = {
        "reliable":     "骨架追踪可信。",
        "uncertain":    f"骨架追踪存疑（{total_majors} 项严重分歧）。",
        "likely_wrong": f"客观维度严重分歧（{objective_majors} 项），建议重选 target_lock。",
    }[skeleton]
    summary = (
        f"两路一致率 {overall:.0%}。{signal_text}"
        + (f" 分歧维度：{', '.join(conflict_fields)}。" if conflict_fields else " 无明显分歧。")
    )

    return CrossValidationReport(
        overall_agreement_rate=round(overall, 3),
        skeleton_reliability_signal=skeleton,
        field_validations=validations,
        high_confidence_fields=high_conf_fields,
        conflict_fields=conflict_fields,
        recommended_path=recommended,
        conflict_summary=summary,
    )


def compute_blend_weights(v: CrossValidationReport) -> tuple[float, float]:
    """返回 (a_weight, b_weight)。和为 1.0。单路情形显式 (1.0,0) 或 (0,1.0)。"""
    if v.recommended_path == "A":       return (1.0, 0.0)
    if v.recommended_path == "B":       return (0.0, 1.0)
    if v.recommended_path == "neither": return (0.5, 0.5)

    base = {
        "reliable":     (0.35, 0.65),
        "uncertain":    (0.50, 0.50),
        "likely_wrong": (0.75, 0.25),
        "unknown":      (0.50, 0.50),
    }[v.skeleton_reliability_signal]
    a, b = base
    bonus = (v.overall_agreement_rate - 0.5) * 0.2
    b = round(min(0.75, max(0.25, b + bonus)), 3)
    return round(1.0 - b, 3), b
```

### 验收

```
1. subscore diff≤6 → reliable / blend
2. rotation_axis+core_stability 同时 major → likely_wrong / A
3. 仅主观维度大分歧 → uncertain
4. path_a=None → recommended=B, weights=(0.0,1.0)
5. 两路 None → recommended=neither, weights=(0.5,0.5)
6. to_dict() 可被 json.dumps 序列化
7. blend_weights 之和恒为 1.0（±0.001）
```

---

## TASK-V08：修改 `report.py` — 加 `dual_path_meta` 可选 kwarg

### 约束

- 签名向后兼容（不传时 100% 旧行为）
- 不改输出 schema
- 仅在 `dual_path_meta` 存在时拼接交叉验证上下文
- 引导 LLM 根据 skeleton_signal 设置 `data_quality`

### 修改后函数

```python
async def generate_report(
    action_type:       str,
    vision_structured: dict[str, Any],
    provider:          ActiveProviderConfig,
    bio_data:          dict[str, Any] | None = None,
    memory_context:    str = "",
    *,
    dual_path_meta:    dict[str, Any] | None = None,   # ← 新增 kwarg
) -> dict[str, Any]:
    sys = REPORT_SYSTEM_PROMPT if not memory_context else f"{REPORT_SYSTEM_PROMPT}\n\n{memory_context}"

    dual_block = ""
    if dual_path_meta:
        dual_block = (
            "\n\n=== 双路交叉验证参考 ===\n"
            f"两路一致率：{float(dual_path_meta.get('overall_agreement_rate', 0)):.0%}\n"
            f"骨架追踪信号：{dual_path_meta.get('skeleton_reliability_signal', 'unknown')}"
            "（reliable=可信 / uncertain=存疑 / likely_wrong=追踪有问题）\n"
            f"推荐参考路径：{dual_path_meta.get('recommended_path', 'blend')}\n"
            f"冲突维度：{', '.join(dual_path_meta.get('conflict_fields', [])) or '无'}\n"
            f"分歧描述：{dual_path_meta.get('conflict_summary', '')}\n"
            "Path B 量化分析子分参考：\n"
            f"  {json.dumps(dual_path_meta.get('path_b_subscores') or {}, ensure_ascii=False)}\n"
            "\n注意：subscores 字段由后端融合计算，你不要自行加权。\n"
            "请根据骨架信号设置 data_quality：\n"
            "  reliable → good / uncertain → partial / likely_wrong → poor\n"
            "若 likely_wrong，请在 issues 末尾追加一条 severity=medium 的提示\n"
            "（category='追踪质量'，description 建议用户重选目标）。\n"
        )

    raw = await request_text_completion(provider, temperature=0.25, max_tokens=1800, messages=[
        {"role": "system", "content": sys},
        {"role": "user",   "content": (
            f"请根据花样滑冰【{action_type}】结构化帧分析和骨骼几何指标，生成结构化训练报告。\n\n"
            '返回 JSON 必须包含：\n'
            '{"summary":"总体评价 2-3 句","issues":[{"category":"问题类别","description":"具体描述",'
            '"severity":"high|medium|low","phase":"落冰","frames":["frame_0012"]}],'
            '"improvements":[{"target":"针对的问题","action":"具体改进动作"}],'
            '"training_focus":"本阶段训练重点",'
            '"subscores":{"takeoff_power":0,"rotation_axis":0,"arm_coordination":0,'
            '"landing_absorption":0,"core_stability":0},"data_quality":"good|partial|poor"}\n\n'
            f"结构化帧分析：\n{json.dumps(vision_structured, ensure_ascii=False)}\n\n"
            f"骨骼几何指标：\n{json.dumps(bio_data or {}, ensure_ascii=False)}"
            + dual_block
        )},
    ])

    cleaned = clean_json_text(raw)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise AnalysisPipelineError(
            AnalysisErrorCode.AI_RESPONSE_PARSE_FAIL,
            f"Report JSON parse failed: {exc}: {cleaned[:500]}",
        ) from exc

    report = normalize_report(parsed, bio_data)
    if not report["summary"] or not report["training_focus"]:
        raise AnalysisPipelineError(
            AnalysisErrorCode.AI_RESPONSE_PARSE_FAIL,
            f"Report missing fields: {cleaned[:500]}",
        )
    return report
```

### 验收

```
1. 不传 dual_path_meta → 与旧版输出等价（同一输入 → 相同 prompt 结构）
2. 传 dual_path_meta skeleton=likely_wrong → prompt 含"建议用户重选目标"
3. subscores 仍由 fuse_subscores 决定（LLM 不参与加权）
4. data_quality 字段存在
5. JSON 解析失败仍抛 AnalysisPipelineError(AI_RESPONSE_PARSE_FAIL)
6. dual_path_meta 中 overall_agreement_rate 为字符串/None 时不崩
```

---

## TASK-V09：新建 `vision_dual.py`

### 设计

- 单一入口 `analyze_frames_dual()`，宿主一行调用
- 额外暴露 `dual_path_summary()`：把 validation 转成给前端展示的精简卡片
- 整体 timeout 兜底（Path B 失败即可，Path A 失败抛硬错）

### 完整代码

```python
# skating_vision/vision_dual.py
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from skating_vision.bio_context import (
    build_frame_bio_context, extract_key_frame_stems, summarize_jump_metrics,
)
from skating_vision.cross_validator import (
    CrossValidationReport, compute_blend_weights, cross_validate,
)
from skating_vision.frame_annotator import annotate_frames_batch, build_pose_by_stem
from skating_vision.providers import ActiveProviderConfig
from skating_vision.types import FramePayload
from skating_vision.video import encode_frames
from skating_vision.vision_path_a import analyze_path_a
from skating_vision.vision_path_b import analyze_path_b

logger = logging.getLogger(__name__)

DUAL_PATH_TOTAL_TIMEOUT = 150.0


@dataclass(slots=True)
class DualPathResult:
    path_a:          dict[str, Any]
    path_b:          dict[str, Any] | None
    validation:      CrossValidationReport
    blend_weights:   tuple[float, float]
    dual_path_meta:  dict[str, Any]
    annotated_dir:   Path | None
    used_key_frames: set[str]


async def analyze_frames_dual(
    action_type:        str,
    frame_paths:        list[Path],
    raw_frame_payloads: list[FramePayload],
    pose_data:          dict[str, Any] | None,
    bio_data:           dict[str, Any] | None,
    provider_path_a:    ActiveProviderConfig,
    provider_path_b:    ActiveProviderConfig,
    *,
    action_subtype:     str | None = None,
    analysis_profile:   str | None = None,
    profile_evidence:   dict[str, Any] | None = None,
    memory_context:     str = "",
    annotated_dir:      Path | None = None,
    timestamps:         dict[str, float] | None = None,
    total_timeout:      float = DUAL_PATH_TOTAL_TIMEOUT,
) -> DualPathResult:
    """
    双路并发分析 + 交叉验证。
    - Path A 失败 → 抛 AnalysisPipelineError（与 analyze_frames 一致）
    - Path B 失败 → 软失败，结果含 'error'，不影响整体
    - 整体超时 → Path B 视为失败，仍尝试单独跑 Path A
    """
    pose_by_stem = build_pose_by_stem(pose_data)
    if annotated_dir is None:
        annotated_dir = (frame_paths[0].parent.parent / "annotated") if frame_paths else Path("/tmp/annotated")
    annotated_paths    = annotate_frames_batch(frame_paths, pose_by_stem, annotated_dir)
    annotated_payloads = await encode_frames(annotated_paths, timestamps=timestamps)

    frame_stems       = [fp.frame_id for fp in raw_frame_payloads]
    key_stems         = extract_key_frame_stems(bio_data)
    bio_ctx           = build_frame_bio_context(bio_data, frame_stems)
    jump_metrics_text = summarize_jump_metrics(bio_data)

    async def _run_a():
        return await analyze_path_a(
            action_type=action_type,
            frame_payloads=raw_frame_payloads,
            provider=provider_path_a,
            action_subtype=action_subtype,
            analysis_profile=analysis_profile,
            profile_evidence=profile_evidence,
            memory_context=memory_context,
        )

    async def _run_b():
        return await analyze_path_b(
            action_type=action_type,
            annotated_frame_payloads=annotated_payloads,
            provider=provider_path_b,
            frame_bio_context=bio_ctx,
            key_frame_stems=key_stems,
            jump_metrics_text=jump_metrics_text,
            action_subtype=action_subtype,
            analysis_profile=analysis_profile,
            profile_evidence=profile_evidence,
            memory_context=memory_context,
        )

    try:
        path_a_result, path_b_result = await asyncio.wait_for(
            asyncio.gather(_run_a(), _run_b()),
            timeout=total_timeout,
        )
    except asyncio.TimeoutError:
        logger.warning("Dual path total timeout > %.0fs, retrying Path A alone", total_timeout)
        path_a_result = await _run_a()   # 仍可能抛硬错
        path_b_result = {"path": "B", "error": "total_timeout"}

    validation = cross_validate(path_a_result, path_b_result)
    weights    = compute_blend_weights(validation)

    dual_meta: dict[str, Any] = {
        "overall_agreement_rate":      validation.overall_agreement_rate,
        "skeleton_reliability_signal": validation.skeleton_reliability_signal,
        "recommended_path":            validation.recommended_path,
        "conflict_fields":             validation.conflict_fields,
        "conflict_summary":            validation.conflict_summary,
        "weight_a":                    weights[0],
        "weight_b":                    weights[1],
        "path_b_subscores":            (path_b_result or {}).get("subscores"),
        "path_b_failed":               bool(path_b_result and path_b_result.get("error")),
    }

    return DualPathResult(
        path_a=path_a_result, path_b=path_b_result,
        validation=validation, blend_weights=weights,
        dual_path_meta=dual_meta,
        annotated_dir=annotated_dir,
        used_key_frames=key_stems,
    )


def dual_path_summary(result: DualPathResult) -> dict[str, Any]:
    """
    给前端的精简摘要。可直接 JSON.stringify 喂给报告页"分析质量"卡片。
    """
    v = result.validation
    return {
        "agreement_rate":  v.overall_agreement_rate,
        "skeleton_signal": v.skeleton_reliability_signal,
        "recommended":     v.recommended_path,
        "weight_a":        result.blend_weights[0],
        "weight_b":        result.blend_weights[1],
        "conflict_fields": v.conflict_fields,
        "summary_text":    v.conflict_summary,
        "path_b_failed":   result.dual_path_meta.get("path_b_failed", False),
        "n_frames_a":      len(result.path_a.get("frame_analysis") or []),
        "n_frames_b":      (result.path_b or {}).get("n_frames", 0),
    }
```

### 验收

```
1. happy path → path_a/path_b 都非空，validation.recommended_path∈{blend,A,B}
2. Path B provider 错误 → DualPathResult.path_b['error'] 非空，path_a 正常
3. Path A provider 错误 → 抛 AnalysisPipelineError（与 analyze_frames 一致）
4. bio_data=None → bio_ctx={}, key_stems=set(), jump_metrics_text=""
5. pose_data=None → 标注帧全为源帧复制（不抛）
6. timestamps 透传给两次 encode_frames
7. dual_path_meta 可直接传给 generate_report(dual_path_meta=...)
8. dual_path_summary(result) 返回 dict 可被 json.dumps（无 dataclass/set 等不可序列化对象）
```

---

## TASK-V10：修改 `__init__.py`

### 追加导出

```python
from skating_vision.frame_annotator import (
    annotate_frame, annotate_frames_batch, build_pose_by_stem,
)
from skating_vision.bio_context import (
    build_frame_bio_context, extract_key_frame_stems, summarize_jump_metrics,
)
from skating_vision.vision_path_a import analyze_path_a
from skating_vision.vision_path_b import analyze_path_b, sample_frames_path_b
from skating_vision.cross_validator import (
    cross_validate, compute_blend_weights,
    CrossValidationReport, FieldValidation,
    SUBSCORE_KEYS as DUAL_SUBSCORE_KEYS,
    OBJECTIVE_FIELDS,
)
from skating_vision.vision_dual import (
    analyze_frames_dual, dual_path_summary,
    DualPathResult, DUAL_PATH_TOTAL_TIMEOUT,
)
from skating_vision.video import build_timestamp_map
```

> **注意**：`cross_validator.SUBSCORE_KEYS` 与 `report.SUBSCORE_KEYS` 同名。
> 为避免歧义，导出时重命名为 `DUAL_SUBSCORE_KEYS`。
> 它们值相同，但语义来源不同，未来若分裂可独立演进。

把所有新符号追加到 `__all__`。

### 验收

```
1. from skating_vision import analyze_frames_dual, DualPathResult, dual_path_summary 正常
2. from skating_vision import analyze_frames（旧符号）仍正常
3. from skating_vision import SUBSCORE_KEYS 仍是 report 的（不被覆盖）
4. mypy/pyright 无未解析符号
```

---

## TASK-V11：新增 `tests/test_dual_path.py`

### 用例清单

```python
import pytest
import respx
from httpx import Response

from skating_vision import (
    analyze_frames_dual, cross_validate, compute_blend_weights,
    build_frame_bio_context, extract_key_frame_stems, summarize_jump_metrics,
    dual_path_summary,
)
from skating_vision.analysis_errors import AnalysisPipelineError


async def test_happy_path():
    """A/B 均返回合法 JSON → recommended_path='blend'，path_b_failed=False"""

async def test_path_b_soft_failure_isolation():
    """Path B mock 抛 ConnectionError → path_b['error'] 非空，
       但 path_a.frame_analysis 完整、未受污染（关键隔离断言）"""

async def test_path_a_hard_failure_raises():
    """Path A mock 返回非 JSON → analyze_frames_dual 抛 AnalysisPipelineError"""

async def test_objective_disagreement_triggers_likely_wrong():
    """rotation_axis 差 30、core_stability 差 25
       → skeleton='likely_wrong', recommended='A'"""

async def test_subjective_only_disagreement_stays_uncertain():
    """arm_coordination 差 30，客观维度一致
       → skeleton != 'likely_wrong'"""

async def test_blend_weights_sum_invariant():
    """4 种 signal × 3 种一致率组合，weight_a + weight_b == 1.0 ± 0.001"""

async def test_bio_context_skips_missing():
    """某帧 left/right knee 都 None → 该 stem 不出现"""

async def test_key_frame_stems_jump_vs_spiral():
    """jump bio_data → 非空 set
       spiral bio_data key_frames={} → set()"""

async def test_summarize_jump_metrics_non_jump_returns_empty():
    """非 jump 或 jump_metrics_status='invalid' → 返回 ''"""

async def test_annotator_handles_lost_keypoints():
    """pose_by_stem 中某 stem 对应 keypoints=[] → 原样复制，不抛"""

async def test_encode_frames_backward_compat():
    """encode_frames(paths) 不传 timestamps → 与旧版字节等价；timestamp_sec 全 0.0"""

async def test_dual_path_summary_serializable():
    """dual_path_summary(result) 输出可被 json.dumps，不含 set/dataclass"""

async def test_total_timeout_does_not_lose_path_a():
    """gather wait_for 超时 → Path B 标记 total_timeout，
       Path A 重新尝试单独跑，成功则正常返回"""
```

### 验收

```
全部 13 个用例通过，coverage 覆盖：
- vision_path_a / vision_path_b / vision_dual
- cross_validator
- bio_context / frame_annotator
- video.encode_frames 向后兼容
```

---

## 附录 A：宿主侧改造提示（参考，不在本任务书内）

```python
from skating_vision import (
    analyze_frames_dual, encode_frames, build_timestamp_map,
    dual_path_summary, generate_report,
)

raw_payloads = await encode_frames(
    frame_paths, timestamps=build_timestamp_map(sampling_payload),
)

dual = await analyze_frames_dual(
    action_type=action_type,
    frame_paths=frame_paths,
    raw_frame_payloads=raw_payloads,
    pose_data=pose_data, bio_data=bio_data,
    provider_path_a=provider_for_slot("vision_path_a"),
    provider_path_b=provider_for_slot("vision_path_b"),
    action_subtype=action_subtype,
    analysis_profile=analysis_profile,
    profile_evidence=profile_evidence,
    memory_context=memory_context,
)

# 持久化（DB 迁移由宿主负责）
analysis.vision_structured = dual.path_a
analysis.vision_path_a     = dual.path_a
analysis.vision_path_b     = dual.path_b
analysis.cross_validation  = dual.validation.to_dict()

report = await generate_report(
    action_type, dual.path_a, provider_report,
    bio_data=bio_data, memory_context=memory_context,
    dual_path_meta=dual.dual_path_meta,
)

# 给前端的摘要
ui_summary = dual_path_summary(dual)
```

---

## 附录 B：相对 v2.4 的精修

| # | v2.4 | v2.5 |
|---|------|------|
| 1 | Path A `temperature=0.05` | `temperature=0.1`（与 analyze_frames 对齐） |
| 2 | Path B 内联 `extra_body={"enable_thinking":False}` | 统一用 `default_extra_body(provider.model_id)` |
| 3 | 扩展字段在 analyze_path_a 末尾直接赋值 | 抽 `_normalize_path_a_payload()` 包装函数显式化 |
| 4 | 无 jump_metrics 摘要 | 新增 `summarize_jump_metrics()` 进 Path B prompt 顶部 |
| 5 | `sample_frames_path_b` 邻域可能超过 max_frames | 增加 `[:max_frames]` 裁剪 |
| 6 | 无 dual_path_summary 工具 | 新增，供前端"分析质量"卡片直接消费 |
| 7 | 未声明 Claude 兼容限制 | 文档显式声明 |
| 8 | 未声明 timestamp fallback bug | 文档 §一.7 声明 |
| 9 | 测试缺"Path B 软失败隔离" | 增加显式断言用例 |
| 10 | 整体超时后未重试 Path A | 现在会单独重试 Path A |

---

## 附录 C：成本与延迟参考

| 模式 | Path A | Path B | 报告 | 总延迟 | 成本倍数 |
|------|--------|--------|------|--------|---------|
| 单路 legacy | 45s | — | 15s | ~60s | 1.0× |
| 双路·单模型 | 45s（并发） | 25s（并发） | 18s | ~65s | ~1.4× |
| 双路·双模型 | 45s（并发） | 30s（并发） | 18s | ~65s | ~1.7× |

Path B 因帧数少（≤10），通常先完成，不构成瓶颈。

---

## 附录 D：已知预存问题清单（**不在本任务范围**，仅记录）

| ID | 文件:行 | 问题 | 建议 |
|----|--------|------|------|
| KP-1 | `report.py::normalize_report` | bio_subscores 仅在 `bio_data["key_frames"]` 非空时参与融合 → spiral/spin/step 的 bio 计算结果**永远不会**进入最终 subscores | 移除 `if bio_data.get("key_frames")` 这一前置条件，或对非 jump 用 `discipline_metrics` 接管 |
| KP-2 | `video.py::extract_motion_sampled_frames` 异常 fallback 路径 | `timestamp=round(i/FRAME_RATE,3)` 未加 `window_start` 偏移 | 改为 `round(window_start + i/FRAME_RATE, 3)` |
| KP-3 | `vision.py::analyze_frames` + 新增 path_a/b | 均直连 `AsyncOpenAI`，**不支持 Claude 兼容 provider** | 重构为复用 `request_text_completion`（需扩展该函数支持 vision content list） |
| KP-4 | `biomechanics.py::analyze_biomechanics` | 非 jump profile 的 `bio_subscores.takeoff_power / rotation_axis / landing_absorption` 硬编码 65（无信号） | 走 `discipline_metrics` 派生，或显式标记为 N/A |

---

*按 V01 → V02 → ... → V11 顺序执行。SDK 完整发布后再着手宿主侧（FastAPI routers / SettingsPage / ReportPage / DB 迁移）。*
```

---

## 四、几个值得你拍板的细节

1. **`temperature=0.1` 还是 `0.05`？**
   v2.5 我选了 0.1（对齐现有 `analyze_frames`），但牺牲了一点 Path A/B 的差异化。如果你希望 Path A 更"稳"，告诉我我改回 0.05，并加注释说明这是与 `analyze_frames` 的有意分裂。

2. **要不要顺手修 KP-1（spiral bug）？**
   `bio_subscores` 在非 jump profile 时永远不进 `fuse_subscores`——这是 spiral/spin/step 用户实际遭遇的 bug。修起来就一行：
   ```python
   bio_sub = bio_data.get("bio_subscores") if isinstance(bio_data, dict) else None
   ```
   如果你要修，告诉我加成 **TASK-V12**。

3. **`dual_path_summary` 字段是否够用？**
   我目前给的字段是给"分析质量"小卡片用的。如果你前端还需要展示每个维度的 diff，可以扩展 `field_validations`（dataclass→dict 列表）。需要的话告诉我。

4. **整体 timeout 后重试 Path A 的策略合适吗？**
   v2.4 是直接放弃，v2.5 改成"超时 → Path B 标失败 → 单独重试 Path A"。代价是最坏 90s+90s=180s，可能比单纯放弃用户体验更糟。如果你倾向"超时即整体失败"，改回去即可。

要不要把这次 v2.5 的几个关键决策（temperature 与现有对齐 / jump_metrics 摘要进 Path B / dual_path_summary 给前端 / 已知预存问题清单 KP-1~4）存进记忆？后续任何一次迭代都能继承。