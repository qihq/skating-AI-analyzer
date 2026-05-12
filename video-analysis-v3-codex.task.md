# 花滑视频 AI 分析模块 —— 迭代优化开发提示词(Codex 用)

## 0. 项目背景与必读上下文
## 重要修正:代码位置说明(必须先读)

`ai_skating_analysis_pack/` 是为了便于审查、整理出来的**代码快照与文档包**,**不是实际运行的源码目录**,Codex 不要在这个目录下做任何修改。所有改动必须落到 `skating-analyzer/` 仓库根目录下的真实工程位置。

### 路径映射(快照路径 → 实际工程路径)

由于实际目录结构在仓库内,Codex 必须先做以下两件事:

1. **第一步:定位实际代码**
   - 在仓库根目录运行 `grep -r "run_analysis_pipeline" --include="*.py" -l` 找到真正的 pipeline.py 实际路径(很可能在 `backend/app/services/` 或 `backend/app/analysis/` 之类目录)。
   - 类似地,用模块内的标志性函数名定位每个模块的真实位置:
     - `extract_motion_sampled_frames` → 实际的 video.py
     - `build_target_preview` → 实际的 target_lock.py
     - `extract_pose` → 实际的 pose.py
     - `infer_analysis_profile`、`JUMP_CHARACTERISTICS` → 实际的 action_profiles.py
     - `analyze_biomechanics`、`FPS = 5` → 实际的 biomechanics.py
     - `analyze_frames`、`normalize_vision_payload` → 实际的 vision.py
     - `generate_report`、`fuse_subscores` → 实际的 report.py
     - `smooth_phases` → 实际的 phase_smoother.py
     - `get_active_provider`、`request_text_completion` → 实际的 providers.py
     - `PIPELINE_VERSION` → 实际的 pipeline_version.py

2. **第二步:在 PR 描述中明确列出"快照路径 → 实际路径"对照表**,例如:
   ```
   ai_skating_analysis_pack/src/quality_assessment/biomechanics.py
     → backend/app/analysis/biomechanics.py  (实际路径,以 grep 结果为准)
   ```
   所有后续任务描述里出现的 `src/...` 路径,都按此对照表替换为真实路径再动手。

### 测试目录同理

- 上一份提示词里写的 `ai_skating_analysis_pack/tests/test_*.py`,实际应落到仓库真实测试目录,例如 `backend/tests/` 或 `backend/app/tests/`,**保持与现有测试同目录、同 pytest 收集规则**。
- 新增 `tests/regression/` 也对应到实际后端测试目录下的 `regression/` 子目录,而不是快照包里。

### 配置文件同理

- `ai_skating_analysis_pack/configs/action_profiles.json`、`vision_prompt.txt` 等——实际工程里很可能位于 `backend/app/configs/` 或 `backend/configs/`,以代码内 `open("configs/action_profiles.json")` 之类的引用为准。修改实际工程内的那一份。

### 前端路径无歧义

- 前端 (`frontend/src/`) 在仓库内是真实位置,任务 1 中"前端"部分按已写路径执行即可,无需映射。

### 文档与错误案例

- `ai_skating_analysis_pack/error_cases_and_metrics.md`、`README.md` 这类文档**继续在快照目录维护**(它是给人看的对外说明包)。每个任务完成后:
  - **代码改动**:落到实际工程路径。
  - **文档更新**:同步更新 `ai_skating_analysis_pack/error_cases_and_metrics.md` 中对应行的 `[已修复 v{version}]` 标记,以及 `ai_skating_analysis_pack/README.md` 中的环境变量、版本号等说明。
  - 这样快照包始终反映最新对外契约,实际代码与之保持一致。

### 同步校验脚本(可选但推荐)

任务 12 的回归基线中,增加一个 `scripts/check_snapshot_sync.py`:
- 读取 `ai_skating_analysis_pack/src/` 下所有 Python 文件。
- 与实际工程路径下的同名文件做 diff。
- 若不一致,CI 报警(允许快照过时,但要在 PR 描述中显式说明并更新快照)。

这样能保证下次再让 AI 看代码时,快照包仍然准确反映真实工程状态。

---

特别提醒 Codex:

- 不要被"涉及文件:`src/quality_assessment/biomechanics.py`"这样的路径误导而去 `ai_skating_analysis_pack/` 下改文件——那是只读快照。
- 若 grep 后发现实际工程的目录组织与快照不一致(例如实际是平铺在 `backend/app/analyzer/` 下,而非按 preprocessing/pose_estimation/quality_assessment 子目录拆分),**以实际为准**,不要为了贴合快照结构而重组实际工程目录。
- 若实际工程里某个函数名/类名与快照不一致(例如快照里叫 `analyze_biomechanics` 但实际叫 `run_biomechanics`),**以实际为准**,且在 PR 描述里指出快照已过时,顺手更新快照包。

### 0.1 模块定位

本仓库为 `skating-analyzer`,核心 AI 分析模块位于 `ai_skating_analysis_pack/`。该模块接收一段花样滑冰训练视频(mp4/mov/avi,通常 5-60 秒,源帧率 30/60/120/240 fps),输出五维评分(起跳发力/旋转轴心/手臂配合/落冰缓冲/核心稳定)、综合发力分(0-100)、跳跃指标(滞空时间/高度/转速/估算周数)、关键帧(T 起跳 / A 顶点 / L 落冰)、以及结构化训练报告。

主入口:`ai_skating_analysis_pack/src/pipeline.py::run_analysis_pipeline()`。

流水线 8 步:`video.py` 抽帧 → `target_lock.py` 目标锁定 → `pose.py` 骨骼提取 → `action_profiles.py` profile 推断 → `biomechanics.py` 生物力学 → `vision.py` LLM 视觉分析 → `report.py` LLM 报告 → `phase_smoother.py` 阶段平滑。

### 0.2 部署环境(硬性约束,不可违背)

- **目标硬件**:Synology DS918+,Intel Celeron J3455,4 核 1.5GHz,无 AVX2,无 GPU,8GB DDR3L 上限。
- **运行形态**:Docker 容器。CPU 是唯一算力,任何超过 MediaPipe BlazePose 单帧 300ms 量级的本地推理都不可接受。
- **网络**:中国大陆,**不可使用 Gemini / OpenAI / Anthropic 官方 API**。
- **现有云端模型**:
  - 视觉:Qwen-VL Plus / Max(阿里云 DashScope,已在 `src/utils/providers.py` 接入,环境变量 `QWEN_API_KEY`)。
  - 文本报告:DeepSeek V3.2 / V4 Pro(已接入,`DEEPSEEK_API_KEY`)。

### 0.3 当前最大瓶颈(本次迭代要解决的根因)

1. **目标锁定经常选错人**——冰场多人,`target_lock.py` 自动锁定阈值 0.72 在群体训练场景下错率高;且 bbox 只用于第一帧,中后段人物移动后骨架会跟到错的人,且**错误是静默的**。
2. **慢动作视频指标系统性失真**——`biomechanics.py:18` 写死 `FPS = 5`,240fps 源视频滞空时间被算大约 ~3-10 倍,直接触发 `MAX_AIR_TIME_SECONDS=1.5` / `MAX_HEIGHT_CM=120` 限幅,被 `sanitize_biomechanics_data` 标 invalid。
3. **关键点抖动 + 角度不解缠绕**——MediaPipe 在旋转/高速场景关键点跳变,`rotation_rps` 累积肩膀 atan2 角度时缺 `numpy.unwrap`,频繁触发 `MAX_ROTATION_RPS=6.0` 限幅。
4. **5fps 抽帧时间分辨率不足**——`FRAME_SAMPLE_COUNT=20`,3 秒跳跃窗口仅 ~5fps,T/A/L 帧误差 ±200-400ms。
5. **LLM phase 非确定 + 幻觉**——`vision.py::analyze_frames()` 单次调用、temperature 不固定,同视频多次结果方差大。
6. **vision 接口仍在用"20 帧 base64 拼图"**——Qwen-VL-Max 已原生支持视频文件输入,我们没用上。
7. **跳跃种类(Axel/Lutz/Flip/Loop/Salchow/Toe Loop)无判别特征**——完全交给 LLM 猜,Lutz/Flip 混淆率高。

### 0.4 量化目标

| 指标 | 当前 | 目标 |
|---|---|---|
| 选错人导致的静默错评分率 | 未知,估计 ≥ 10% | ≤ 1% |
| 慢动作视频 jump_metrics invalid 率 | ~60%(240fps) | ≤ 10% |
| 三周跳周数误差 | ±0.5 圈 | ±0.25 圈 |
| T/A/L 帧时间误差 | ±200-400ms | ≤ 80ms(短期)/ ≤ 40ms(中期) |
| Lutz vs Flip 混淆率 | ~60-70% | ≤ 35% |
| 同视频多次 subscores 方差 | 未知,估计 > 10 | ≤ 5 |
| 关键点帧间抖动 RMS(归一化) | 无测量 | ≤ 0.01 |

---

## 通用代码规范(所有任务遵守)

### 编码风格

- Python 3.11+,**严格遵循当前仓库已有风格**:`from __future__ import annotations`、PEP 8、类型注解(`dict[str, Any]` 而非 `Dict`)、4 空格缩进、单引号字符串不做强制(跟现有文件保持一致即可)。
- 模块顶部 docstring 用三引号中文描述「职责」「输入」「输出」,与现有 `biomechanics.py`、`action_profiles.py` 写法对齐。
- 函数命名:私有用 `_snake_case` 前缀下划线;公开 API 用 `snake_case`。常量全大写置于模块顶部。
- 不引入新的重型依赖(scikit-image、opencv-contrib 等需求经评审)。允许新增:`scipy>=1.10`(One-Euro Filter 系数计算可用)、`filterpy`(可选)。所有新依赖必须写进 `requirements.txt` 并钉版本。

### 错误处理

- 沿用 `src/utils/analysis_errors.py` 中的 `PipelineError` 与错误码常量;**禁止**新增裸 `raise Exception` 或 `assert` 用于运行时检查。
- 静默退化必须打 logger.warning 并在返回的 `bio_data` / `vision_structured` 里加 `quality_flags` 字段,前端可见,例如:`bio_data["quality_flags"].append("pose_smoothing_failed_fallback")`。
- 所有外部 API 调用(DashScope、火山方舟、DeepSeek)走 `src/utils/providers.py` 的统一封装,**不允许**在业务文件里直接 `httpx.post`。

### 注释要求

- 公开函数必须有 docstring,包含 `Args` / `Returns` / `Raises`。
- 涉及"为什么这么做"的非显然逻辑(如 One-Euro Filter 参数选择、慢动作 FPS 修正公式)必须有 `# 设计说明:` 行内注释。
- 不要写"# 这里循环 i 从 0 到 n"这类无效注释。

### 单元测试

- 新增/修改逻辑必须配 `ai_skating_analysis_pack/tests/test_*.py`,沿用现有 `test_biomechanics_jump_rotation_estimation.py` 的 fixture 风格(构造合成 pose 序列)。
- 测试不依赖网络、不依赖 GPU、不依赖外部权重文件。涉及 LLM 的部分用 monkeypatch 把 `providers.request_text_completion` 替换为 stub。
- 每个修复必须有一个**回归测试**:针对错误案例文档 `ai_skating_analysis_pack/error_cases_and_metrics.md` 中提到的具体场景写一个失败-修复对比 case。

### 流水线版本号

- 任何任务完成后,在 `src/utils/pipeline_version.py` 把 `PIPELINE_VERSION` patch 号 +1,并在文件末尾追加一行变更摘要注释。前端会展示该版本号。

---

## 任务 1:前端手动目标锁定 + 后端多帧 bbox 跟踪

**目标**:消除"冰场多人时骨架加错人"的静默错误,把选错人导致的错评分率从 ≥10% 降到 ≤1%。

**涉及文件**:
- 后端:`src/preprocessing/target_lock.py`、`src/pose_estimation/pose.py`、`src/pipeline.py`、`backend/app/routers/`(FastAPI 路由,需新增 manual_bbox 端点)。
- 前端:`frontend/src/`(在上传流程后、轮询分析结果前插入"目标确认"步骤)。

**修改方案**:

### 1.1 后端:接受手动 bbox

- `target_lock.py::build_target_lock_payload()` 增加可选参数 `manual_bbox: dict | None`。当传入 `manual_bbox = {"x":..,"y":..,"w":..,"h":..}`(归一化 0-1)时:
  - 跳过自动评分,直接 `selected_bbox = manual_bbox`,`status = "manual"`,`lock_confidence = 1.0`。
  - 保留 `candidates` 字段供前端调试。
- `target_lock.py` 增加 `validate_manual_bbox(bbox)` 函数:检查 x/y/w/h ∈ [0,1] 且 w,h ≥ 0.05(防止用户误点选到一个点)。不合法走 `PipelineError(code="TARGET_BBOX_INVALID")`。

### 1.2 后端:bbox 多帧跟踪(整段视频持续约束 pose 候选)

当前 `pose.py::_score_candidate()` 的 IoU 项用的是第一帧静态 bbox,跨帧不更新,人物位移大时失效。

实现一个 OpenCV CSRT 单目标跟踪器:
- 新文件:`src/preprocessing/bbox_tracker.py`。
- 入口:`track_bbox(frame_paths: list[Path], initial_bbox: dict) -> list[dict]`,返回每帧的 bbox(归一化坐标)。
- 用 `cv2.TrackerCSRT_create()`(OpenCV 已是依赖,无需新增包),失败帧(`tracker.update()` 返回 False)用前一帧 bbox + 线性外推填充并打 quality_flag。
- `pose.py::extract_pose()` 改成接收 `bbox_per_frame: list[dict]` 而不是单一 bbox。`_score_candidate()` 的 IoU 参考框按当前帧 idx 取 `bbox_per_frame[idx]`。

### 1.3 流水线串接

`pipeline.py::run_analysis_pipeline()` 流程改为:

```python
# 1. 抽帧 → motion_scores, frame_paths
# 2. 第一阶段:返回 target preview 给前端(若 lock_confidence < 0.72 则 pause)
preview = build_target_preview(analysis_id, frame_names)
if preview.lock_confidence < TARGET_LOCK_AUTO_THRESHOLD and not manual_bbox:
    # 写入 DB,状态置为 awaiting_target_selection,返回 202 给前端
    return PendingTargetSelection(preview=preview)

# 3. 拿到 manual_bbox(或自动锁定的 bbox)后:
bbox_initial = manual_bbox or preview.auto_candidate.bbox
bbox_per_frame = track_bbox(frame_paths, bbox_initial)
pose_data = extract_pose(frames_dir, bbox_per_frame=bbox_per_frame)
# ... 后续不变
```

### 1.4 API 端点

`backend/app/routers/analysis.py` 新增:

- `GET /api/analysis/{id}/target_preview` → 返回 `{first_frame_url, candidates: [{id, bbox, confidence}], auto_candidate_id, lock_confidence}`。
- `POST /api/analysis/{id}/target_lock` body `{candidate_id: str | None, manual_bbox: {x,y,w,h} | None}` → 触发后续分析继续执行。

### 1.5 前端

在上传完成后插入一个步骤:
- 拉第一关键帧(从 `frame_motion_scores` 取分数最高的一帧)、画候选框、用户点选或自由拉框。
- 若 `lock_confidence >= 0.72` 默认选中 auto_candidate,显示"自动识别,确认即可"按钮;否则强制必须选。

### 1.6 验证

- 单元测试:`tests/test_bbox_tracker.py` 用合成的"红方块在帧间移动"图片序列验证 CSRT 跟踪精度 IoU > 0.7。
- 单元测试:`tests/test_target_lock.py` 增加 manual_bbox 路径覆盖。
- 端到端:用错误案例 1.2 中的"多人画面"测试视频(若无,需让用户提供 1-3 段)对比改前/改后的 pose_data 主目标稳定性。

### 1.7 风险

- CSRT 在快速旋转的花滑选手身上可能漂移。**缓解**:每 8 帧用 MediaPipe 检测结果重新校准 bbox(取所有候选 pose 与 tracker 输出 IoU 最高者重置 tracker)。

---

## 任务 2:慢动作视频 FPS 修正

**目标**:消除 `biomechanics.py:18` 硬编码 `FPS = 5` 导致的慢动作视频指标系统性失真,把 240fps 视频 `jump_metrics` invalid 率从 ~60% 降到 ≤10%。

**涉及文件**:
- `src/preprocessing/video.py`(暴露 effective_fps)
- `src/quality_assessment/biomechanics.py`(消除 FPS 常量)
- `src/pipeline.py`(传参)

**修改方案**:

### 2.1 暴露 effective_fps

`video.py::VideoSamplingMetadata` dataclass 增加字段:
- `source_fps: float`(已由 `detect_video_fps` 拿到,确认透出)
- `window_start_sec: float`、`window_end_sec: float`(动作窗口起止秒)
- `effective_fps: float`,计算公式:`effective_fps = (FRAME_SAMPLE_COUNT - 1) / (window_end_sec - window_start_sec)`(注意是间隔数 = 帧数-1)

`extract_motion_sampled_frames()` 把这三个字段填上。

### 2.2 重构 biomechanics.py

- 删除模块级 `FPS = 5`。
- `analyze_biomechanics()` 签名增加 `effective_fps: float`,默认 5.0(向后兼容旧测试,但加 `DeprecationWarning` 提示传值)。
- 所有原本用 `FPS` 的地方(主要在 `_estimate_air_time`、`estimate_jump_rotations`、`_rotation_rps`)改用参数。
- `MAX_AIR_TIME_SECONDS = 1.5` 保留为物理上限校验(成年单人滑顶级跳跃滞空也罕见超过 0.8s,1.5s 是宽松容错),但**不再用 FPS 倒推帧上限**。

### 2.3 流水线传参

`pipeline.py` 在调 `analyze_biomechanics` 时:

```python
bio_data = analyze_biomechanics(
    pose_data=pose_data,
    action_type=action_type,
    analysis_profile=analysis_profile,
    effective_fps=sampling_metadata.effective_fps,
)
```

### 2.4 在 bio_data 中透传

`bio_data["sampling_context"] = {"effective_fps": ..., "source_fps": ..., "window_seconds": ...}`,前端报告页可显示"采样依据"。

### 2.5 验证

- 新增 `tests/test_biomechanics_fps_correction.py`:构造一个"模拟 240fps 源、5fps 采样、20 帧覆盖 3 秒窗口"的合成 pose 序列(T 帧 idx=5,L 帧 idx=15,所以滞空 = (15-5) / effective_fps 秒),验证 `air_time_seconds` 在合理范围(0.4-0.7s),`estimated_height_cm` 在 20-60cm 之间,而不是被标 invalid。
- 回归错误案例 1.5「慢动作源帧率未修正」,在 PR 描述中贴出修复前后的指标对比。

### 2.6 风险

- 老视频/老数据库已存的 bio_data 会因 effective_fps 变更而无法直接对比。**缓解**:`pipeline_version.py` patch +1,前端在报告页对版本差异作 disclaimer 提示。

---

## 任务 3:关键点 One-Euro 时序平滑 + 可见性插值

**目标**:把肩/髋归一化坐标帧间抖动 RMS 降到 ≤0.01;消除 `visibility < 0.5` 关键点被置零导致的下游计算崩溃。

**涉及文件**:
- 新文件:`src/pose_estimation/smoothing.py`
- 修改:`src/pose_estimation/pose.py::extract_pose()`(输出前过滤)、`src/quality_assessment/biomechanics.py::_point()`(插值后不再 visibility 门控置零)

**修改方案**:

### 3.1 One-Euro Filter 实现

不要引入新依赖,自己写约 50 行(One-Euro 算法很简单)。参考:

```python
# src/pose_estimation/smoothing.py
import math
from dataclasses import dataclass

@dataclass
class OneEuroFilter:
    """One-Euro Filter,适合人体关键点时序去抖。

    设计说明:min_cutoff=1.0、beta=0.05 是花滑动作下的推荐参数 ——
    旋转/腾空类高速场景下需要保留快速变化,beta 略高;
    静止/落冰类需要更强平滑,min_cutoff 不能太低。
    """
    min_cutoff: float = 1.0
    beta: float = 0.05
    d_cutoff: float = 1.0
    _prev_x: float | None = None
    _prev_dx: float = 0.0
    _prev_t: float | None = None

    def _alpha(self, cutoff: float, dt: float) -> float:
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def filter(self, x: float, t: float) -> float:
        if self._prev_t is None:
            self._prev_x = x
            self._prev_t = t
            return x
        dt = max(t - self._prev_t, 1e-6)
        dx = (x - self._prev_x) / dt
        a_d = self._alpha(self.d_cutoff, dt)
        dx_hat = a_d * dx + (1 - a_d) * self._prev_dx
        cutoff = self.min_cutoff + self.beta * abs(dx_hat)
        a = self._alpha(cutoff, dt)
        x_hat = a * x + (1 - a) * self._prev_x
        self._prev_x, self._prev_dx, self._prev_t = x_hat, dx_hat, t
        return x_hat
```

### 3.2 应用到 33 关键点

`smoothing.py::smooth_keypoint_sequence(frames: list[dict], effective_fps: float) -> list[dict]`:
- 为每个 keypoint 的 x、y 各维护一个 OneEuroFilter。
- 对 visibility < 0.5 的关键点先做线性插值(前后最近的 visible 帧),插值得到的点标 `interpolated: True`,visibility 保留原值供生物力学决策。
- 整段全 invisible 的关键点保持 None。
- 时间戳 t = frame_idx / effective_fps。

### 3.3 在 pose.py 中调用

`extract_pose()` 拿到原始 pose_data 后:

```python
from .smoothing import smooth_keypoint_sequence
pose_data["frames"] = smooth_keypoint_sequence(pose_data["frames"], effective_fps)
```

`extract_pose()` 因此需要从 pipeline 接 effective_fps,签名增加该参数。

### 3.4 biomechanics 适配

`biomechanics.py::_point()` 移除 visibility < 0.5 即置 None 的逻辑,改为:
- 若 keypoint 标记 `interpolated=True` 且 visibility < 0.3,仍置 None(完全无信号)。
- 否则返回插值/平滑后的坐标。

### 3.5 验证

- `tests/test_pose_smoothing.py`:构造一个"x 坐标按 0.1 + sin(t) + 抖动(±0.02)"的合成序列,验证平滑后高频抖动 RMS < 0.005、保留低频趋势(MAE < 0.02)。
- 验证缺失帧(中间 3 帧 visibility=0)能被线性插值填回。
- 回归:`MAX_ROTATION_RPS=6.0` 限幅触发频率应显著下降——可在 `_rotation_rps()` 加 telemetry log,统计有多少视频触发限幅。

### 3.6 风险

- 过度平滑可能让真实的 T 帧"被推迟一两帧"。**缓解**:在 `detect_key_frames()` 中,对 T 帧另用未平滑 CoM Y 序列做边沿检测(派生信号 du/dt 找零穿越),平滑序列仅用于角度/对称性等积分类指标。

---

## 任务 4:旋转角度解缠绕

**目标**:消除 `rotation_rps` 因肩膀 atan2 跳变(−π → π)导致的角度累积错误,解决 `MAX_ROTATION_RPS=6.0` 限幅误判。

**涉及文件**:`src/quality_assessment/biomechanics.py::_rotation_rps()` 及任何累积肩膀/髋部连线角度的函数。

**修改方案**:

定位现有 `_rotation_rps` 实现,把逐帧 `atan2(dy, dx)` 序列改成:

```python
import numpy as np
angles = np.array([math.atan2(p2.y - p1.y, p2.x - p1.x) for p1, p2 in shoulder_pairs])
unwrapped = np.unwrap(angles)  # 关键:解缠绕
total_rotation_rad = abs(unwrapped[-1] - unwrapped[0])
duration_sec = (len(angles) - 1) / effective_fps
rotation_rps = total_rotation_rad / (2 * math.pi * max(duration_sec, 1e-6))
```

注意:`np.unwrap` 默认阈值 π,在正常旋转(每帧角度变化 < π)下足够;若 5fps 抽帧 + 5rps 旋转,每帧角度变化 = 2π × 5 / 5 = 2π,**已超 unwrap 上限会失效**——需检测每帧角度变化 > π/2 时触发降密度采样回退或在 vision 层用图像旋转检测做交叉校验,但此降级路径放到任务 5 解决(更密抽帧后单帧角度变化 < π)。

**验证**:
- `tests/test_biomechanics_rotation_unwrap.py`:构造肩膀绕 z 轴匀速旋转 720°(2 圈)的合成关键点序列,verify `rotation_rps` 计算结果 ≈ 真值 ±5%,而不是因为跳变被算成 0.5 圈。
- 回归现有 `tests/test_biomechanics_jump_rotation_estimation.py` 保证不破坏既有测试。

---

## 任务 5:自适应抽帧密度(按 profile)

**目标**:T/A/L 帧时间误差从 ±200-400ms 降到 ≤80ms,且为任务 4 提供单帧角度变化 < π 的前置条件。

**涉及文件**:`configs/action_profiles.json`、`src/preprocessing/video.py::_select_motion_weighted_indices()`、`extract_motion_sampled_frames()`。

**修改方案**:

### 5.1 配置驱动

在 `configs/action_profiles.json` 中给每个 profile 增加字段:

```json
{
  "jump":   {"frame_sample_count": 32, "window_seconds": 3.0, ...},
  "spin":   {"frame_sample_count": 24, "window_seconds": 6.0, ...},
  "step":   {"frame_sample_count": 20, "window_seconds": 8.0, ...},
  "spiral": {"frame_sample_count": 16, "window_seconds": 6.0, ...}
}
```

`video.py` 读取 profile 对应的 frame_sample_count,不再依赖环境变量 `FRAME_SAMPLE_COUNT`(保留为 fallback)。

### 5.2 加权采样改良

`_select_motion_weighted_indices()` 当前是运动密度加权均匀采样。改为:
- 强制覆盖运动峰值(top-2 局部极大值)± 1 帧 → 保证 T/L 瞬间被采到。
- 剩余配额按运动密度加权抽。

### 5.3 effective_fps 联动

任务 2 的 `effective_fps` 计算自动跟随新的 frame_sample_count,不需要额外改。

### 5.4 验证

- 用 fixture 视频(若无,新增合成视频生成脚本 `tests/fixtures/synth_jump_video.py`,用 ffmpeg 把简单的"球抛物运动 + 自旋"渲染成 mp4,T/A/L 真值已知)。
- 验证 T/L 帧选中误差从 ≥2 帧降到 ≤1 帧。

### 5.5 风险与成本

- jump 从 20 帧 → 32 帧,后续 vision 输入 token 涨 60%,**任务 11 切换原生视频输入后这部分成本会重新归 0**——任务 5 和任务 11 需在同一发布窗口完成或排好顺序。

---

## 任务 6:LLM phase detection 自一致投票

**目标**:同视频多次 subscores 方差降到 ≤5,phase 联合准确率从 ~70% 提到 ~80%。

**涉及文件**:`src/quality_assessment/vision.py::analyze_frames()`、`src/action_recognition/phase_smoother.py`。

**修改方案**:

### 6.1 多次调用投票

`analyze_frames()` 内增加参数 `n_votes: int = 3`、`vote_temperature: float = 0.2`(默认温度比当前低,允许少量多样性):

```python
async def analyze_frames(..., n_votes: int = 3) -> dict:
    tasks = [_single_vision_call(payload, temperature=0.2) for _ in range(n_votes)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    valid = [r for r in results if not isinstance(r, Exception)]
    if not valid:
        raise PipelineError(code=AI_RESPONSE_PARSE_FAIL)
    return _merge_vision_results(valid)
```

### 6.2 合并策略

`_merge_vision_results()`:
- 每帧 phase:多数投票,平票按 phase_smoother 合法转换链回退(优先选与前一帧相邻 phase)。
- observations / issues / positives:取并集后去重(相似度 > 0.7 视为同一项,用简单 token Jaccard 即可,不引入 sentence-transformers)。
- confidence:取平均。
- 在 `vision_structured["vote_metadata"]` 里记录每帧投票分布,便于调试。

### 6.3 phase_smoother 强化

`phase_smoother.py::smooth_phases()` 增加几何回退:当 LLM 投票仍分歧 + 该帧在 T/A/L 关键帧附近(±1帧)时,直接用 biomechanics 输出的 key_frames 强制赋 phase("起跳"/"顶点"/"落冰")。

### 6.4 验证

- monkeypatch `_single_vision_call` 返回 3 个不同结果,验证投票合并逻辑正确。
- 在真实视频上跑 5 次,前后对比 subscores 标准差(目标 ≤ 5)。

### 6.5 风险

- API 调用次数 ×3,成本上升。**缓解**:任务 11 切换到 Qwen-VL-Max 视频原生输入后,可改为「视频原生 1 次主 + 帧拼图 1 次副」双源投票,而不是同输入投 3 次。

---

## 任务 7:Lutz/Flip 刃型几何证据 + prompt evidence 通道

**目标**:在不换模型的前提下,Lutz vs Flip 混淆率从 ~60-70% 降到 ≤35%。

**涉及文件**:
- 新文件:`src/quality_assessment/jump_features.py`
- 修改:`src/action_recognition/action_profiles.py`(增加 `infer_jump_subtype_evidence()`)
- 修改:`configs/vision_prompt.txt`(增加 evidence 字段说明)
- 修改:`src/quality_assessment/vision.py`(把 evidence 塞入 prompt)

**修改方案**:

### 7.1 几何特征提取

`jump_features.py::compute_jump_evidence(pose_data, key_frames, effective_fps) -> dict`,返回:

```python
{
    "takeoff_foot": "left" | "right" | "unknown",  # T 帧前 0.2s 内 visibility 更高、Z 更靠前的脚
    "toe_pick_pulse": bool,                         # T 帧前 0.1-0.2s 脚踝 Y 出现向下脉冲(点冰)
    "toe_pick_strength": float,                     # 脉冲幅值(归一化)
    "feet_together_at_takeoff": bool,               # T 帧两脚踝距离 / 肩宽 < 0.3(Loop 标志)
    "free_leg_swing_amplitude": float,              # 起跳前 0.5s 自由腿髋-踝向量摆动幅度(Salchow 标志)
    "approach_direction": "forward" | "backward",   # 起跳前 0.5s CoM 速度向量与身体朝向夹角
    "pre_takeoff_edge_score": float,                # 滑行轨迹曲率符号 → 推断内/外刃(0=外刃,1=内刃,0.5=不确定)
}
```

每项实现都是纯 numpy,详见以下要点:
- **toe_pick_pulse**:对 T 帧前 1-2 帧的脚踝 y 序列做一阶差分,差分绝对值 > 阈值(经验值 0.04 归一化坐标)且方向先负后正 → True。
- **pre_takeoff_edge_score**:用 CoM XY 在起跳前 0.5s 的轨迹拟合圆弧曲率,曲率方向与身体朝向(左肩-右肩向量)叉乘符号判断内外刃。**注意**:480p 下这是弱信号,边缘分类输出概率而非硬标签,信心 ≤ 0.6 时标 unknown。

### 7.2 写入 evidence

`vision.py::analyze_frames()` 调用前先算 evidence,塞进 user prompt 的结构化区:

```
<evidence>
takeoff_foot: left
toe_pick_pulse: true (strength=0.07)
feet_together_at_takeoff: false
free_leg_swing_amplitude: 0.42
approach_direction: backward
pre_takeoff_edge_score: 0.71 (likely_inside_edge)
</evidence>
```

`configs/vision_prompt.txt` 增加段落:"参考 evidence 中的几何线索做跳跃种类判别,evidence 字段优先级高于纯视觉印象;若 evidence 与画面矛盾请明确指出"。

### 7.3 验证

- `tests/test_jump_features.py`:用合成 pose 序列分别构造典型 Toe Loop(明显点冰脉冲)、Loop(双脚并拢)、Salchow(自由腿大幅摆动)、Axel(前向起跳),验证 evidence 字段输出正确。
- 端到端:收集 5-10 段标注好跳跃种类的真实视频,统计前后混淆矩阵。

### 7.4 风险

- 几何特征本身有噪声,evidence 错可能误导 LLM。**缓解**:evidence 字段都附信心值,信心 < 0.5 不输出该字段。

---

## 任务 8:AI Provider 重试 + 降级

**目标**:消除"LLM 失败 → 整个 pipeline raise"的脆弱性,确保有降级报告输出。

**涉及文件**:`src/utils/providers.py`、`src/quality_assessment/vision.py`、`src/quality_assessment/report.py`。

**修改方案**:

### 8.1 重试

`providers.py::request_text_completion()` 增加指数退避重试(3 次,间隔 1s、2s、4s),仅对 5xx / 429 / 网络超时重试,4xx auth/quota 直接抛 `AI_API_AUTH_ERROR` / `AI_API_QUOTA_EXCEEDED`。

### 8.2 vision 降级

`vision.py` 在所有重试失败后,返回最小可用结构:

```python
{
    "frame_analysis": [{"frame_id": ..., "phase": "不可分析", "confidence": 0.0} for each frame],
    "action_phase_summary": "AI 视觉分析暂不可用,以下评分基于生物力学数据。",
    "overall_raw_text": "",
    "fallback_used": True,
}
```

### 8.3 report 降级

`report.py::generate_report()` 在 LLM 失败时,基于 `bio_data["bio_subscores"]` 模板化生成最简报告:

```python
{
    "summary": f"{action_type}动作生物力学评分:起跳发力 {takeoff} / 旋转轴心 {rot} ...",
    "issues": [<从 quality_flags 翻译>],
    "improvements": [],
    "training_focus": [],
    "subscores": bio_subscores,
    "data_quality": "degraded_no_ai",
    "fallback_used": True,
}
```

### 8.4 验证

- `tests/test_provider_retry.py`:monkeypatch httpx 模拟 5xx、429、auth_err、网络超时,验证重试次数与最终行为符合预期。
- 验证 vision/report 降级输出能被 pipeline 正常消费、`force_score` 仍可计算(基于 bio_subscores)。

---

## 任务 9:视频与帧预检

**目标**:消除错误案例 1.1 / 1.2 中的静默退化,在 pipeline 入口快速失败并给出明确错误。

**涉及文件**:`src/preprocessing/video.py`(新增预检函数)、`src/preprocessing/target_lock.py`(增加人体存在检查)。

**修改方案**:

### 9.1 视频预检

`video.py::precheck_video(video_path)`:
- 文件头 magic bytes 检查(mp4/mov 前 8 字节、avi RIFF 头)。
- ffprobe 读时长 > 0.5s、有视频流、分辨率 ≥ 320×180。
- 抽 3 帧检查不全为纯黑(亮度方差 > 5)。
- 失败时分别抛 `VIDEO_FORMAT_INVALID` / `VIDEO_NO_VIDEO_STREAM` / `VIDEO_BLANK_FRAMES`。

### 9.2 人体存在预检

`target_lock.py::build_target_preview()` 中,若所有候选 bbox 置信度 < 0.15,**不再 fallback 到中心区域**,而是返回 `status="no_person_detected"`,前端展示提示让用户重新选择视频。

### 9.3 验证

- `tests/test_video_precheck.py`:用空 mp4、纯黑视频、损坏头部的 mp4 各跑一次,验证错误码正确。

---

## 任务 10:Qwen-VL-Max 视频原生输入

**目标**:把 vision 接口从「20 帧 base64 拼图」迁移到「Qwen-VL-Max 直接吃 mp4 短片」,提升时序理解、降低任务 5 抽帧成本压力。

**涉及文件**:`src/quality_assessment/vision.py`、`src/utils/providers.py`、`src/preprocessing/video.py`(新增动作窗口切片)。

**修改方案**:

### 10.1 动作窗口切片

`video.py::cut_action_window_clip(video_path, window_start_sec, window_end_sec, out_path)`:用 ffmpeg(已是依赖)直接切片:

```python
subprocess.run([
    "ffmpeg", "-y", "-ss", str(start), "-to", str(end),
    "-i", str(video_path), "-c", "copy", str(out_path),
], check=True)
```

如 `-c copy` 因关键帧对齐失败,fallback `-c:v libx264 -preset ultrafast -crf 28`。输出限制 480p 以下、≤ 10 秒,避免 API token 爆。

### 10.2 vision.py 增加视频模式

`vision.py::analyze_frames()` 增加参数 `mode: Literal["frames", "video"] = "video"`(默认走视频)。

视频模式 payload(DashScope multimodal generation 接口):

```python
messages = [
    {"role": "system", "content": SYSTEM_PROMPT},
    {"role": "user", "content": [
        {"video": f"file://{clip_path}"},  # 或先上传到 OSS 再传 URL
        {"text": user_prompt_with_evidence},
    ]},
]
```

注意:DashScope 视频输入有两种方式——本地 file:// 上传(适合 ≤100MB 短片,直接走 SDK)或 OSS 公网 URL。**NAS 部署优先用本地上传**,避免维护 OSS。

### 10.3 模型选择

环境变量增加 `QWEN_VISION_MODEL`(默认 `qwen-vl-max-latest`,可配置为 `qwen2.5-vl-72b-instruct` 或 `qwen3-vl-plus` 等)。`providers.py::get_active_provider("vision")` 读取该变量。

### 10.4 保留 frames 模式作为降级

若视频上传失败(网络 / 文件 > 100MB),自动 fallback 到 frames 模式,打 `quality_flag: vision_fallback_to_frames`。

### 10.5 prompt 调整

视频模式下,`configs/vision_prompt.txt` 不再要求"逐帧 frame_id"——改为按时间秒数定位关键事件。返回 JSON schema 调整为:

```json
{
  "phase_segments": [
    {"start_sec": 0.2, "end_sec": 0.6, "phase": "准备", ...},
    {"start_sec": 0.6, "end_sec": 0.75, "phase": "起跳", ...}
  ],
  "observations": [...], "issues": [...], "positives": [...],
}
```

后续 `phase_smoother.py` 需要把 phase_segments 映射回采样帧索引(给定 `effective_fps` 和 window_start 就是简单插值)。

### 10.6 验证

- 用真实 mp4 在 dev 环境跑通一次端到端;DashScope 控制台核对计费。
- `tests/test_vision_video_mode.py`:monkeypatch providers,验证 video 模式与 frames 模式输出能被同一份下游消费(契约测试)。

### 10.7 风险

- 视频模式 API 单价高(¥0.3-0.6/段),需要 `providers.py` 加每日成本上限,超额自动降级到 frames 模式。
- 视频上传时间在国内网络下可能 5-15s,需要把超时从当前 90s 提到 180s。

---

## 任务 11:豆包 Doubao-1.5-vision-pro 第二路投票

**目标**:消除单一 LLM 幻觉,subscores 方差 ≤5;Lutz/Flip 混淆率进一步降到 ≤25%。

**涉及文件**:`src/utils/providers.py`、`src/quality_assessment/vision.py`。

**修改方案**:

### 11.1 多 provider 支持

`providers.py` 重构 `get_active_provider("vision")` 为 `get_vision_providers() -> list[ActiveProviderConfig]`,允许配置多个并发 slot。环境变量:

```bash
VISION_PROVIDERS=qwen,doubao
QWEN_API_KEY=...
DOUBAO_API_KEY=...
DOUBAO_VISION_MODEL=doubao-1.5-vision-pro-32k
```

新增 `_call_doubao_vision()`(火山方舟,OpenAI 兼容 API,base_url `https://ark.cn-beijing.volces.com/api/v3`)。

### 11.2 投票合并

`vision.py::analyze_frames()` 并发调多家,合并策略同任务 6(phase 多数投票、issues 取并集去重)。任务 6 的"同模型 3 次投票"在此可降为"每家 1 次,两家共 2 票",再加 biomechanics 几何回退作为决断票。

### 11.3 验证

- monkeypatch 双 provider 返回不同结果,验证投票合并。
- 在真实视频上对比单 provider vs 双 provider 的 subscores 跨次方差。

### 11.4 风险

- 豆包视频输入有自身限制(单文件 ≤50MB / 时长 ≤60s),需在 `_call_doubao_vision` 内做尺寸校验,超限自动跳过该 slot。

---

## 任务 12:综合验证 + 回归基线

**目标**:建立可持续运行的回归测试集,确保未来迭代不破坏指标。

**涉及文件**:`ai_skating_analysis_pack/tests/regression/`(新增目录)。

**修改方案**:

### 12.1 fixture 视频集

- 创建 `tests/regression/fixtures/` 存放 5-10 段标注视频(实际视频文件不入 git,用 LFS 或外部 OSS 链接,git 内只存 `manifest.json` 标注 ground truth)。
- 每段 fixture 标注:T/A/L 帧时间戳、跳跃种类(若有)、估算周数、专家打分(可选)。

### 12.2 回归脚本

`tests/regression/run_regression.py`:跑完整 pipeline,输出指标 CSV:

```
video_id, T_error_ms, A_error_ms, L_error_ms, rotation_count_error, jump_type_correct, subscores_std_across_3_runs
```

阈值在 `tests/regression/thresholds.yaml` 中配置,任一超阈 CI 失败。

### 12.3 文档同步

`ai_skating_analysis_pack/error_cases_and_metrics.md` 增加"v{new_version} 实测指标"章节,替换原推测值。

---

## 整体依赖与注意事项

### 依赖变更

- **新增 Python 包**:`scipy>=1.10`(numpy.unwrap 已在 numpy 内,scipy 仅当需要更高阶滤波时引入,可选;请优先用纯 numpy 实现 One-Euro)、无需引入 filterpy / scikit-image。
- **OpenCV**:`opencv-python` 当前已是依赖,CSRT tracker 在 `opencv-contrib-python` 中——**需要在 `requirements.txt` 增加 `opencv-contrib-python==<同主版本>`**,并在 Dockerfile 中验证可装。
- **ffmpeg**:任务 10 切片依赖,容器内必须可用(检查 `backend/Dockerfile` 是否已 apt install ffmpeg,如无需要补)。

### 模型权重

- 本次迭代**不引入任何本地模型权重**(MediaPipe Pose 保持现状)。`weights/` 目录与 `WEIGHTS_README.md` 不变。
- 任务 10/11 涉及云端模型版本切换,在 `WEIGHTS_README.md` 末尾追加"云端模型版本登记"小节。

### 环境变量新增清单

```bash
# 任务 5/10/11
VISION_PROVIDERS=qwen,doubao
QWEN_VISION_MODEL=qwen-vl-max-latest
DOUBAO_API_KEY=...
DOUBAO_VISION_MODEL=doubao-1.5-vision-pro-32k

# 任务 8
AI_RETRY_MAX_ATTEMPTS=3
AI_RETRY_BASE_DELAY_SEC=1.0

# 任务 10
VISION_VIDEO_MODE_DEFAULT=true
VISION_VIDEO_DAILY_COST_LIMIT_CNY=20

# 任务 6
VISION_VOTE_COUNT=3
VISION_VOTE_TEMPERATURE=0.2
```

所有新增项必须在 `README.md` 的「环境变量配置」一节同步更新。

### 跨模块影响风险

- **任务 1(target_lock 异步化)**:`pipeline.py` 从单次同步执行变为两阶段(target 选择 → 实际分析),后端路由层 `backend/app/routers/analysis.py` 需新增中间状态 `awaiting_target_selection`,DB schema 可能需要 migration(增加 `target_lock_payload`、`status` 字段若未有)。前端轮询逻辑必须同步改造。
- **任务 2(effective_fps)**:所有写过 `bio_data` 的下游代码(report.py、subscores 计算)需要确认未直接读取旧的 `FPS=5` 常量。
- **任务 3(pose 平滑)**:`biomechanics.py` 中所有 `_point()` 返回 None 的分支保护逻辑需逐一过一遍,确保插值后非 None 但 visibility 仍低的关键点不会污染计算。
- **任务 5(抽帧增至 32)**:任务 5 与任务 10 互相依赖——若先发任务 5 再发任务 10,中间会有约 1-2 周的高 token 成本期;**建议两个任务同 release,或先发任务 10 再发任务 5**。
- **任务 6 与任务 11**:都是投票机制,任务 11 上线后任务 6 的「同模型投 3 次」应降级为「每家 1 次」,避免成本叠加。
- **错误案例文档**:每个任务完成后必须在 PR 中说明对应消灭了 `error_cases_and_metrics.md` 中的哪些行,并在该 md 文件中将对应行标记 `[已修复 v{version}]`。

### 发布顺序建议

阶段 A(本周):任务 1、任务 2、任务 4、任务 8、任务 9。皆为低风险纯逻辑修复,无需 API 调用结构变更。
阶段 B(第 2 周):任务 3、任务 7。需要更细致的回归。
阶段 C(第 3 周):任务 10、任务 5 同时上线;任务 6 临时启用 n_votes=2。
阶段 D(第 4 周):任务 11 上线后,任务 6 调整为单次双 provider。
阶段 E:任务 12 持续运行,作为后续迭代守门。

### 不允许做的事

- 不允许引入任何本地 GPU/NPU 推理模型(SlowFast / VideoMAE / RTMPose / X-CLIP 等)。
- 不允许调用 Gemini / OpenAI / Anthropic 官方 API。
- 不允许把生物力学逻辑前移到前端 JS。
- 不允许移除 `src/utils/snowball.py` 长期记忆机制(`skater_id` 注入链路要保持完整)。
- 不允许修改前端 node_modules 内容。

### 验收标准

- 所有新增/修改函数 100% 覆盖测试。
- 全部回归测试(任务 12 的 fixture 集)通过且达成第 0.4 节量化目标的至少 80%。
- `error_cases_and_metrics.md` 中 1.1-1.7 节列出的错误场景,至少 70% 标记为 `[已修复]`。
- `pipeline_version.py` 版本号递增,前端报告页可见。
- 在 DS918+ 实机 Docker 内端到端跑通 5 段不同时长/帧率的视频,无 OOM、无 CPU 持续 100% 超过 60s。