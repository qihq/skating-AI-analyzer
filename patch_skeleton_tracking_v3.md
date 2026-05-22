# Patch: 骨架追踪精准度提升 v3
**集成 roboflow/supervision + ByteTracker**  
**目标系统**：skating-AI-analyzer / DS918+（Intel Celeron J3455，无 GPU）  
**执行方式**：按 Phase 顺序逐步提交 Codex，每 Phase 验证后再继续

---

## 与 v2 的关键差异

| 模块 | v2 方案 | v3 方案 |
|---|---|---|
| 目标追踪 | 自定义 `_score_candidate()` + 动态 seed_bbox + Kalman | **supervision ByteTracker**（工业级，替代以上全部）|
| `kalman_tracker.py` | 新增 | **不再需要，删除** |
| 动态 seed_bbox 逻辑 | 在 `pose.py` 中手写 | **替换为 tracker_id 锁定** |
| YOLO 调用频率 | 仅首帧一次 | **每帧调用**（追踪需要逐帧检测）|
| 静止物体抑制 | 6 帧位移检测 | **保留**，作为 ByteTracker 前置过滤 |
| 速度硬拒绝 | 保留 | **保留**，作为 ByteTracker 前置过滤 |
| video_temporal 监控 | Phase 3 | **Phase 4**（内容不变）|

**架构变化**：
```
旧：抽帧 → MediaPipe 全帧检测 → _score_candidate() 打分选人 → 骨架
新：抽帧 → YOLOv8n 检测所有人 → sv.ByteTracker 锁定 ID
         → 根据 tracker_id 拿到目标 bbox → MediaPipe 处理目标区域 → 骨架
```

---

## Phase 1 — 安装依赖

在 `requirements.txt` 中追加：

```
supervision>=0.27.0
ultralytics>=8.0.0
```

在 `Dockerfile` 中确认已有（若无则追加）：

```dockerfile
RUN pip install supervision ultralytics --no-cache-dir
```

**验证**：
```python
import supervision as sv
from ultralytics import YOLO
print(sv.__version__)   # 应 >= 0.27.0
```

---

## Phase 2 — 新增 `person_tracker.py`

**路径**：`backend/app/services/person_tracker.py`  
**作用**：封装 YOLOv8n + supervision ByteTracker，对外暴露简洁接口，供 `pose.py` 调用。

```python
# backend/app/services/person_tracker.py
"""
Person tracker: YOLOv8n detection + supervision ByteTracker.

Responsibilities
----------------
- Detect all persons in each frame with YOLOv8n (CPU, class=0 only)
- Track detected persons across frames with ByteTracker (persistent ID)
- Lock onto a single target person (by seed_bbox overlap or frame center)
- Suppress static objects (lamp posts, boards) via displacement history
- Return target bbox per frame for downstream MediaPipe processing

NOT responsible for
-------------------
- Pose/skeleton estimation (MediaPipe handles that)
- TAL or biomechanics (downstream modules)
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────
_YOLO_MODEL_NAME = "yolov8n.pt"          # ~6 MB, auto-downloaded on first run
_YOLO_CONF_THRESHOLD = 0.40              # detection confidence threshold
_BYTETRACK_ACTIVATION_THRESHOLD = 0.35  # minimum confidence to activate a new track
_BYTETRACK_LOST_BUFFER = 30             # frames to hold a lost track before dropping
_BYTETRACK_MATCH_THRESHOLD = 0.80       # IoU threshold for matching detections to tracks
_BYTETRACK_FRAME_RATE = 2               # extracted frames are ~2 fps
_STATIC_HISTORY = 6                     # frames of history for static object detection
_STATIC_DISPLACEMENT_RATIO = 0.02       # < 2% of frame width = static object
_MAX_VELOCITY_RATIO = 0.25              # > 25% of diagonal per frame = reject (passerby)
_LOST_RELOCK_THRESHOLD = 8             # frames without target before re-locking
# ─────────────────────────────────────────────────────────────────────────────


def _iou(a: tuple, b: tuple) -> float:
    """Compute IoU between two (x1,y1,x2,y2) boxes."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter == 0.0:
        return 0.0
    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    return inter / (area_a + area_b - inter)


class PersonTracker:
    """
    Stateful tracker for a single target person across a sequence of frames.

    Usage
    -----
    tracker = PersonTracker(seed_bbox=(x1, y1, x2, y2))
    for frame_bgr in frames:
        result = tracker.process_frame(frame_bgr)
        if result is not None:
            target_bbox, tracker_id = result
            # pass target_bbox to MediaPipe
    quality_flags = tracker.quality_flags
    """

    def __init__(
        self,
        seed_bbox: Optional[tuple[float, float, float, float]] = None,
        prefer_center: bool = True,
    ) -> None:
        """
        Parameters
        ----------
        seed_bbox      : (x1,y1,x2,y2) from manual selection, or None
        prefer_center  : if no seed, lock onto person closest to frame center
        """
        self._seed_bbox = seed_bbox
        self._prefer_center = prefer_center
        self._target_tracker_id: Optional[int] = None
        self._last_known_bbox: Optional[tuple] = seed_bbox
        self._lost_frames = 0
        self._frame_idx = 0
        # history: tracker_id → deque of center points
        self._center_history: dict[int, list[tuple[float, float]]] = {}
        self.quality_flags: list[str] = []

        # lazy-init to avoid import cost when tracker not used
        self._yolo_model = None
        self._byte_tracker = None

    # ── private: lazy init ───────────────────────────────────────────────────

    def _get_yolo(self):
        if self._yolo_model is None:
            try:
                from ultralytics import YOLO  # type: ignore
                self._yolo_model = YOLO(_YOLO_MODEL_NAME)
                logger.info("YOLOv8n loaded (CPU mode)")
            except Exception as exc:
                logger.error("Failed to load YOLOv8n: %s", exc)
                self._yolo_model = False
        return self._yolo_model if self._yolo_model is not False else None

    def _get_tracker(self):
        if self._byte_tracker is None:
            try:
                import supervision as sv  # type: ignore
                self._byte_tracker = sv.ByteTracker(
                    track_activation_threshold=_BYTETRACK_ACTIVATION_THRESHOLD,
                    lost_track_buffer=_BYTETRACK_LOST_BUFFER,
                    minimum_matching_threshold=_BYTETRACK_MATCH_THRESHOLD,
                    frame_rate=_BYTETRACK_FRAME_RATE,
                )
                logger.info("supervision ByteTracker initialized")
            except Exception as exc:
                logger.error("Failed to init ByteTracker: %s", exc)
                self._byte_tracker = False
        return self._byte_tracker if self._byte_tracker is not False else None

    # ── private: detection + pre-filtering ──────────────────────────────────

    def _detect(self, frame_bgr: np.ndarray) -> list[tuple[float, float, float, float, float]]:
        """Run YOLOv8n, return list of (x1,y1,x2,y2,conf) for class=person."""
        model = self._get_yolo()
        if model is None:
            return []
        try:
            results = model(
                frame_bgr,
                classes=[0],
                conf=_YOLO_CONF_THRESHOLD,
                verbose=False,
            )
            boxes = []
            for r in results:
                for box in r.boxes:
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    conf = float(box.conf[0])
                    boxes.append((x1, y1, x2, y2, conf))
            return boxes
        except Exception as exc:
            logger.warning("YOLO inference failed on frame %d: %s", self._frame_idx, exc)
            return []

    def _is_static(self, tracker_id: int, frame_w: int) -> bool:
        """Return True if this tracked object has barely moved (lamp post etc.)."""
        history = self._center_history.get(tracker_id, [])
        if len(history) < _STATIC_HISTORY:
            return False
        recent = history[-_STATIC_HISTORY:]
        xs = [p[0] for p in recent]
        ys = [p[1] for p in recent]
        displacement = ((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2) ** 0.5
        return displacement < frame_w * _STATIC_DISPLACEMENT_RATIO

    def _is_too_fast(
        self,
        bbox: tuple,
        frame_w: int,
        frame_h: int,
    ) -> bool:
        """Return True if this detection jumped too far from last known position."""
        if self._last_known_bbox is None:
            return False
        prev_cx = (self._last_known_bbox[0] + self._last_known_bbox[2]) / 2.0
        prev_cy = (self._last_known_bbox[1] + self._last_known_bbox[3]) / 2.0
        cur_cx = (bbox[0] + bbox[2]) / 2.0
        cur_cy = (bbox[1] + bbox[3]) / 2.0
        dist = ((cur_cx - prev_cx) ** 2 + (cur_cy - prev_cy) ** 2) ** 0.5
        diagonal = (frame_w ** 2 + frame_h ** 2) ** 0.5
        return dist > diagonal * _MAX_VELOCITY_RATIO

    # ── private: target selection ─────────────────────────────────────────────

    def _select_initial_target(
        self,
        tracked_detections,   # sv.Detections with tracker_id
        frame_w: int,
        frame_h: int,
    ) -> Optional[int]:
        """
        Pick the initial target tracker_id from the first frame's tracked detections.
        Priority: seed_bbox overlap > frame center proximity.
        """
        import supervision as sv  # type: ignore

        if len(tracked_detections) == 0 or tracked_detections.tracker_id is None:
            return None

        best_id = None
        best_score = -1.0
        frame_cx, frame_cy = frame_w / 2.0, frame_h / 2.0

        for i, tid in enumerate(tracked_detections.tracker_id):
            x1, y1, x2, y2 = tracked_detections.xyxy[i]
            bbox = (x1, y1, x2, y2)
            cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0

            if self._seed_bbox is not None:
                score = _iou(bbox, self._seed_bbox)
            elif self._prefer_center:
                # closer to center → higher score (inverted distance, normalized)
                max_dist = (frame_cx ** 2 + frame_cy ** 2) ** 0.5
                dist = ((cx - frame_cx) ** 2 + (cy - frame_cy) ** 2) ** 0.5
                score = 1.0 - dist / max(max_dist, 1.0)
            else:
                score = (x2 - x1) * (y2 - y1)  # largest area

            if score > best_score:
                best_score = score
                best_id = int(tid)

        return best_id

    # ── public API ───────────────────────────────────────────────────────────

    def process_frame(
        self,
        frame_bgr: np.ndarray,
    ) -> Optional[tuple[tuple[float, float, float, float], int]]:
        """
        Process one frame. Returns (target_bbox, tracker_id) or None if target lost.

        Parameters
        ----------
        frame_bgr : OpenCV BGR frame (full resolution)

        Returns
        -------
        (x1, y1, x2, y2), tracker_id   — target found
        None                             — target lost this frame
        """
        import supervision as sv  # type: ignore

        frame_h, frame_w = frame_bgr.shape[:2]
        self._frame_idx += 1

        tracker = self._get_tracker()
        if tracker is None:
            logger.warning("ByteTracker unavailable, skipping frame %d", self._frame_idx)
            return None

        # 1. Detect
        raw_boxes = self._detect(frame_bgr)
        if not raw_boxes:
            self._lost_frames += 1
            self._maybe_flag_lost()
            return None

        # 2. Build sv.Detections
        xyxy = np.array([[b[0], b[1], b[2], b[3]] for b in raw_boxes], dtype=np.float32)
        confs = np.array([b[4] for b in raw_boxes], dtype=np.float32)
        detections = sv.Detections(xyxy=xyxy, confidence=confs)

        # 3. ByteTracker update
        tracked = tracker.update_with_detections(detections)

        if len(tracked) == 0 or tracked.tracker_id is None:
            self._lost_frames += 1
            self._maybe_flag_lost()
            return None

        # 4. Update center history for static suppression
        for i, tid in enumerate(tracked.tracker_id):
            x1, y1, x2, y2 = tracked.xyxy[i]
            cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
            tid_int = int(tid)
            if tid_int not in self._center_history:
                self._center_history[tid_int] = []
            self._center_history[tid_int].append((cx, cy))

        # 5. Initial target lock (first frame only)
        if self._target_tracker_id is None:
            self._target_tracker_id = self._select_initial_target(tracked, frame_w, frame_h)
            if self._target_tracker_id is None:
                return None
            logger.info("Target locked: tracker_id=%d", self._target_tracker_id)

        # 6. Find target in current frame
        target_bbox = None
        for i, tid in enumerate(tracked.tracker_id):
            if int(tid) != self._target_tracker_id:
                continue
            x1, y1, x2, y2 = tracked.xyxy[i]
            bbox = (float(x1), float(y1), float(x2), float(y2))

            # Static suppression
            if self._is_static(int(tid), frame_w):
                logger.debug("Frame %d: target appears static, skipping", self._frame_idx)
                continue

            # Velocity hard reject (passerby suddenly at target position)
            if self._lost_frames > 0 and self._is_too_fast(bbox, frame_w, frame_h):
                logger.debug("Frame %d: bbox jump too large, possible ID swap", self._frame_idx)
                continue

            target_bbox = bbox
            break

        # 7. Handle lost / found
        if target_bbox is None:
            self._lost_frames += 1
            self._maybe_flag_lost()
            # Try re-lock if lost too long
            if self._lost_frames >= _LOST_RELOCK_THRESHOLD:
                logger.info("Re-locking after %d lost frames", self._lost_frames)
                self._target_tracker_id = self._select_initial_target(tracked, frame_w, frame_h)
                self._lost_frames = 0
                if "target_relock" not in self.quality_flags:
                    self.quality_flags.append("target_relock")
            return None

        self._last_known_bbox = target_bbox
        self._lost_frames = 0
        return target_bbox, self._target_tracker_id

    def _maybe_flag_lost(self) -> None:
        if self._lost_frames == 1 and "target_lost_frames" not in self.quality_flags:
            self.quality_flags.append("target_lost_frames")
```

**验证**：
```python
import numpy as np
from app.services.person_tracker import PersonTracker
# 用纯黑帧测试初始化不报错
tracker = PersonTracker(seed_bbox=(100, 100, 300, 400))
frame = np.zeros((720, 1280, 3), dtype=np.uint8)
result = tracker.process_frame(frame)
print("result:", result)          # 黑帧无人，应返回 None
print("flags:", tracker.quality_flags)
```

---

## Phase 3 — 修改 `pose.py`：集成 PersonTracker

### 3-A：在文件顶部导入

```python
from app.services.person_tracker import PersonTracker
```

### 3-B：删除以下已被替代的内容

从 `pose.py` 中移除（或注释掉）以下逻辑，ByteTracker 已完整替代：

- `_score_candidate()` 函数中的**动态 seed_bbox 相关代码**（原有权重打分逻辑可保留简化版，用于 ByteTracker 不可用时的降级）
- 原手写的候选打分循环
- 原 `_low_conf_streak` / `_dynamic_seed_bbox` 等追踪状态变量

> 注意：`_score_candidate()` 函数本身**不要删除**，保留作为 ByteTracker 不可用时的 fallback，但不再是主路径。

### 3-C：在帧循环外初始化 PersonTracker

在 `extract_pose()` 或帧处理主函数开头，加入：

```python
# ── PersonTracker 初始化（ByteTracker 主路径）────────────────
_person_tracker = PersonTracker(
    seed_bbox=seed_bbox,       # 用户手动框选坐标，可为 None
    prefer_center=True,
)
_use_tracker = True            # 若 supervision 不可用则降级
# ─────────────────────────────────────────────────────────────
```

### 3-D：帧循环内：追踪优先，MediaPipe 接力

在每帧处理逻辑中，将目标 bbox 获取方式改为：

```python
target_bbox = None
tracker_id = None

if _use_tracker:
    try:
        track_result = _person_tracker.process_frame(frame_bgr)
        if track_result is not None:
            target_bbox, tracker_id = track_result
    except Exception as exc:
        logger.warning("PersonTracker failed on frame %d: %s", frame_idx, exc)
        _use_tracker = False   # 降级到原有逻辑

# target_bbox 有值时：传给 MediaPipe 作为 bbox hint 或裁剪 ROI
# target_bbox 为 None 时：跳过本帧或降级到 _score_candidate() 原有逻辑
if target_bbox is not None:
    # 将 bbox 传入 MediaPipe 的单人模式（fallback path B）
    # 或用于 Multi-Pose 结果过滤（取 bbox 内置信度最高的 pose）
    best_candidate_bbox = target_bbox
else:
    # 降级：使用原有 _score_candidate() 打分
    best_candidate_bbox = _original_score_candidate_logic(...)
```

### 3-E：流程结束后，合并 quality_flags

```python
# 将 PersonTracker 产生的 flags 合并到分析结果的 quality_flags
if _use_tracker:
    for flag in _person_tracker.quality_flags:
        if flag not in quality_flags:
            quality_flags.append(flag)
```

### 3-F：兼容性确认

- `extract_pose()` 返回结构**不变**
- `seed_bbox` 为 `None` 时，PersonTracker 自动用帧中心策略
- supervision / ultralytics 任一不可用时，自动降级到原 `_score_candidate()` 逻辑
- `biomechanics.py`、`keyframe_candidates.py`、`smoothing.py` **完全不改动**

---

## Phase 4 — video_temporal 失败监控

内容与 v2 Phase 3 完全相同，此处简述：

**修改 `video_temporal.py` 或 `analysis.py`：**

1. 确认 `resolve_semantic_keyframes()` 返回的 `keyframe_source` 字段被持久化到数据库
2. 视频 AI 失败时写入 `quality_flags`：

```python
if keyframe_source in ("skeleton_fallback", "skeleton_only"):
    if "video_temporal_failed" not in quality_flags:
        quality_flags.append("video_temporal_failed")
```

---

## DS918+ 性能预估

| 步骤 | 原耗时 | v3 耗时 |
|---|---|---|
| 帧提取（FFmpeg） | ~3s | ~3s（不变）|
| MediaPipe 姿态 | ~8s/20帧 | ~8s/20帧（不变）|
| **YOLOv8n 检测** | 仅首帧 ~0.4s | **全部帧 ~8s**（+7.6s）|
| ByteTracker 更新 | 无 | ~0.01s（可忽略）|
| 总额外耗时 | — | **+7~10s/视频** |

这是用追踪质量换时间，离线批处理场景可接受。若后续觉得太慢，可把 YOLOv8n 换成更小的 `yolov8n-pose.pt`（同时输出 person bbox + 关键点，省去 MediaPipe，但精度略低）。

---

## 需通过的测试

- `backend/tests/test_pose_smoothing.py`（不受影响）
- `backend/tests/test_target_lock.py`（**需更新**：原测试基于 `_score_candidate()`，需补充 PersonTracker 的测试用例）
- `backend/tests/test_bbox_tracker.py`（**需更新**：原测试基于 Kalman，改为测试 PersonTracker）
- `backend/tests/test_video_temporal.py`（不受影响）

**新增测试用例建议**（在 `test_target_lock.py` 或新建 `test_person_tracker.py`）：

```python
def test_static_object_suppressed():
    """灯柱检测应被静止物体抑制过滤。"""

def test_passerby_rejected():
    """从画面另一侧出现的路人应被速度硬拒绝过滤。"""

def test_relock_after_loss():
    """连续 8 帧失跟后应触发重新锁定，并写入 quality_flags。"""

def test_fallback_when_supervision_unavailable():
    """supervision 不可用时应降级到原 _score_candidate() 逻辑。"""
```

---

## 人工验证场景

| 场景 | 期望结果 |
|---|---|
| 路人从正前方滑过 | 骨架始终跟随目标，不跟路人 |
| 跳跃腾空后落冰 | 全程锁定目标，落冰后骨架即时恢复 |
| 高速旋转 | 骨架不飘走，quality_flags 中可能出现 `target_lost_frames` |
| 灯柱在背景中 | 骨架不吸附到灯柱 |
| 未手动框选 seed_bbox | 自动锁定画面中央的人（通常是选手）|

---

*Patch 版本：skeleton-tracking-v3（supervision + ByteTracker 集成）*  
*适配硬件：Synology DS918+（Intel Celeron J3455，无 GPU）*  
*依赖：supervision>=0.27.0，ultralytics>=8.0.0*
