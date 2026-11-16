# FreeMoCap 可行性评估（只读评估，未改动任何源码）

评估日期：2026-04（本次会话）
评估对象：https://github.com/freemocap/freemocap
评估问题：能否在当前系统上用起来？有没有改善？

**结论速览**

| 问题 | 结论 |
| --- | --- |
| 装得上吗？ | 技术上可以（Python 3.12 在支持范围内），但必须独立环境，且与现有依赖硬冲突 |
| 能接进现有上传式管线吗？ | **不能**。架构与工作流根本不匹配 |
| 对现有单摄像头路径有改善吗？ | **没有**。官方明确单相机不产出可靠 3D，只等于现有 MediaPipe 级别的 2D |
| 什么情况下才有改善？ | 只有改造为**多机位同步采集 + 标定**的现场拍摄流程，且必须在拍摄端做，存量视频永远补不回来 |
| 唯一值得单独考虑的软件升级 | RTMPose 级关键点（133 点）替代 MediaPipe BlazePose（33 点），但**不应经由 FreeMoCap**（许可证 + 依赖 + 未发布） |

---

## 一、当前机器实测情况

| 项目 | 实测值 |
| --- | --- |
| 机型 | HP EliteDesk 705 G4 DM 35W（迷你主机） |
| CPU | AMD Ryzen 5 PRO 2400GE，4 核 / 8 线程 @ 3.2GHz（2018 年，35W 低功耗 APU） |
| GPU | AMD Radeon RX Vega 11 核显（1GB 共享显存） |
| NVIDIA / CUDA | **无 `nvidia-smi`，无 CUDA 设备** |
| 内存 | 14.93 GB 可用；Docker(WSL2) 可见 8 CPU / 7.23 GiB |
| 系统 | Windows 10 Pro 19045 |
| Python | 3.12.10（宿主）；3.11.15（skating-backend 容器内） |
| PyTorch | 2.11.0+**cpu**（宿主）；2.3.1+**cpu**（容器）——均为纯 CPU 版 |
| 磁盘 | C: 剩余 101.7 GB |
| 已运行容器 | 10 个，含 `skating-backend`(8000) 与 `skating-frontend`(8080)，已连续运行 13 天 |

**要点：这台机器没有可用于深度学习推理的独立 GPU。** 现有分析管线本身就全部跑在 CPU 上。

---

## 二、FreeMoCap 的事实核对

### 2.1 版本与许可

- 最新版 **1.8.2**，`requires_python = >=3.10,<3.13` → **本机 Python 3.12.10 兼容**
- 开发状态：**Development Status :: 3 - Alpha**
- 许可证：**AGPL-3.0-or-later**（官方 FAQ 自称 "the most aggressively open source license available"）
- 本项目为 MIT

### 2.2 最关键的官方表述（单相机）

> "single-camera recordings **will not produce reliable 3D estimates** but will produce solid two-dimensional tracking, suitable for 2D animators. To get a viable multi-camera recording that will produce reliable estimates of 3D movement, users will need **at least two cameras** (one of which could be the laptop camera), however we recommend using **three cameras** for better results."

来源：https://docs.freemocap.org/documentation/software-hardware-prerequisites.html

**这句话基本决定了本次评估的答案。** FreeMoCap 的全部价值增量在于「多机位三角化出真 3D」，而单相机模式下它退化成一个 2D 追踪器——正是本项目现在已有的能力层级。

### 2.3 其他硬性限制

- **非实时**："Does FreeMoCap work in realtime? Not yet!"
- **同时只能追踪一个人**："FreeMoCap currently only tracks one person at a time"
  （来源：https://docs.freemocap.org/documentation/frequently-asked-questions-faq.html）
  对公共冰场场景是实质性限制——画面里常有其他学员。
- **3D 需要打印 Charuco 标定板并现场标定**
- 采集端是 **SkellyCam**：为每台 USB 摄像头开独立 OS 进程，用 grab/retrieve 两阶段协议保证**帧号级完美同步**（来源：https://github.com/freemocap/skellycam）

### 2.4 管线结构（已核对仓库）

```
freemocap/core/tasks/       calibration → mocap → triangulation
freemocap/core/pipeline/    posthoc（事后处理） / realtime
```

`triangulation` + 依赖 `aniposelib==0.4.3` 证实：**多相机标定与三角化是 3D 的必经环节**，不是可选优化。

### 2.5 一个决定性的代码级约束

`freemocap/core/pipeline/posthoc/video_group_helper.py` 中，`VideoGroupHelper` 的校验器强制要求：

```python
if len(set(video.metadata.frame_count for video in self.videos.values())) != 1:
    raise ValueError(_frame_count_mismatch_detail(self.videos))
```

**同一个视频组内所有视频必须帧数完全相同**，否则直接抛错。该文件虽然提供了 `from_video_folder_path()` / `from_video_paths()` 并带文件名启发式解析（可容纳非 SkellyCam 命名的文件），但**帧数必须逐一相等**这一条是硬门槛。

两台独立手机拍摄的视频帧数**不可能相等**，且没有 genlock、时钟各自漂移、起拍时刻不同。因此：

> **存量手机视频无法用于 FreeMoCap 的 3D 重建。** 即便人工裁到帧数相等，也只是对齐了帧数，没有对齐时间轴，三角化结果不可信。

---

## 三、与当前系统的匹配度

### 3.1 工作流根本不匹配（致命）

| | skating-analyzer-v2 | FreeMoCap |
| --- | --- | --- |
| 输入 | 家长**上传**手机拍的视频（Web 应用） | **现场实时**多 USB 摄像头同步采集 |
| 摄像头 | 1 台，任意来源 | ≥2（推荐 3）台，直连同一台电脑 |
| 标定 | 无 | 每次布机位都要 Charuco 标定 |
| 运行位置 | 服务器容器，异步后台任务 | 桌面 Qt GUI 应用，本机处理 |
| 人数 | 多人追踪 + 目标锁定 | 只能 1 人 |

现有产品形态是「拍完 → 上传 → 服务端分析」。FreeMoCap 要求「架好 2–3 台相机 → 现场标定 → 现场录制 → 本机处理」。这两者不是同一个产品，也不是加一个接口就能打通的。

### 3.2 依赖硬冲突（无法共存于同一环境）

FreeMoCap 1.8.2 / skellytracker 2025.10.1024 的钉死版本 vs 现有环境：

| 依赖 | FreeMoCap 要求 | 现有环境 | 冲突 |
| --- | --- | --- | --- |
| `opencv-contrib-python` | `==4.8.*` | 4.11.0.86（容器）/ 4.13.0.92（宿主） | 是 |
| `torch` | `==2.8.*` | 2.3.1+cpu / 2.11.0+cpu | 是 |
| `ultralytics` | `~=8.3.132` | 8.3.40 | 是 |
| `numpy` | `<2` | 1.26.4 | 否 |

结论：**只能建独立 venv 或独立容器**，绝不可能装进现有 backend 环境。另外 FreeMoCap 依赖 PySide6(Qt)、`skellycam`（numpy 钉死 1.26.2、Pillow 10.0.1、pandas 2.1.4），是典型桌面应用依赖树。

### 3.3 许可证风险（商业层面，非技术层面）

FreeMoCap / skellycam / skellytracker **全部是 AGPL-3.0-or-later**，本项目是 MIT。

AGPL 的关键在于**网络服务条款**：只要用户通过网络与衍生作品交互，就必须向这些用户提供完整对应源码。若把 FreeMoCap 或其组件并入这个对外提供服务的系统，**整个组合作品都会被 AGPL 覆盖**，而不只是新增的那部分。官方 FAQ 也明确表示，若 AGPL 不适用需要另行联系他们谈商业授权。

这不是可以靠技术手段规避的问题，需要你先做商业决策。

### 3.4 硬件与性能

- 无 CUDA。官方 GPU 加速路径（`[cuda]`、TensorRT、`onnx-cuda`）在这台机器上全部不可用。
- 这台 35W 4 核迷你主机目前已跑 10 个容器，Docker 上限 7.23 GiB 内存。
- FreeMoCap 的 GUI 是 Qt 桌面应用；即便只做单相机 2D，其链路（YOLOX + RTMPose 全尺寸模型）在这颗 2018 年的 4 核 APU 上也会**慢于**现有 MediaPipe 管线。

---

## 四、那么"改善"到底在哪里

诚实地说，FreeMoCap 指出的方向是对的，但它不是你能直接采用的那个方案。

### 4.1 现有管线真正的痛点，恰好是单视点的固有痛点

`backend/app/analysis_v2/rotation.py` 已经在用**多信号融合**估计跳跃/旋转周数：姿态朝向、躯干外观周期性、轮廓朝向、目标裁剪光流、相机滚转，各自带可靠性权重，并保留竞争假设。

它同时定义了 `RotationRefusalReason`——**当采样或可见性无法区分周数时，它选择拒答**。这个"拒答"是正确行为，但也正说明：**单摄像头 2D 在原理上无法可靠区分 1.5 周与 2.5 周**，尤其在有旋转、遮挡、运动模糊时。

多机位 3D 能真正解决这个问题。但代价是：

- 冰场要架 2–3 台同步相机 + 每次标定
- 采集必须在现场完成，**存量的、已经上传的历史视频永远无法补救**
- 需要换机器（要 CUDA 才跑得动 3D 重建）

这是一个**硬件 + 拍摄流程改造项目**，不是软件替换。

### 4.2 唯一值得单独评估的软件升级：RTMPose 关键点

FreeMoCap 的追踪后端 `skellytracker` 把多种姿态模型收在统一 API 下：MediaPipe、**RTMPose**、YOLOX、Aruco、Charuco。其中：

- MediaPipe BlazePose：**33 个关键点**（本项目现用）
- **RTMPose `rtmw-x-l`：133 个全身关键点**（含手部、脚部、面部）

RTMPose 系列在快速运动和旋转姿态上通常比 BlazePose 更稳，这对花滑的跳跃/旋转环节是有实际意义的。

但有两个必须知道的前提：

1. **skellytracker 已发布版（PyPI 2025.10.1024）的 extras 只有 `all / dev / mediapipe / yolo`。** 其 GitHub README 里描述的 `recommended-cpu`、`all-directml`、`onnx`、`onnx-cpu`、`onnx-directml` 等 extras **尚未发布**，属于开发分支内容。也就是说 README 描述的 RTMPose/DirectML 能力**现在 pip 装不到**。
   （`all-directml` 那条"Windows 任意 GPU"本来看起来很适合这台 AMD 核显机器，可惜未发布。）
2. 许可证问题同上——`skellytracker` 也是 AGPL-3.0。

**因此更合理的路径是：绕开 FreeMoCap/skellytracker，直接用 ONNX Runtime 接入 RTMPose 模型。** 本机已装 `onnxruntime 1.24.4`、`ultralytics 8.3.40`、`opencv`，检测器可以复用现有 YOLO，只替换关键点回归部分。这样既拿到 133 点精度，又避开 AGPL 与依赖冲突。

这一项属于**独立的、可控的、低风险的**优化，值得单独立项评估——但它和 FreeMoCap 已经没有关系了。

---

## 五、最终判断

**1. FreeMoCap 能在当前系统上"用起来"吗？**

能装上（Python 3.12 兼容、磁盘够），但**用不到现有业务里**。它要么作为一个完全独立的桌面工具存在（需要你现场架多机位），要么根本不产生价值。

**2. 有没有改善？**

对**现有单摄像头上传式管线：没有改善**。官方自己说明单相机不产出可靠 3D，输出等价于现有 MediaPipe 2D 层级，而且更慢、只能单人、依赖冲突、许可证不兼容。

**3. 什么条件下才有改善？**

只有你决定把产品从「上传视频分析」扩展为「冰场多机位现场采集」时。那时 FreeMoCap 是一个可参考的开源实现（也可以看 OpenCap 等同类方案），但仍需先解决：AGPL 授权、CUDA 机器、标定流程、单人限制、以及教练/家长是否愿意配合架机位。

**4. 建议的下一步（按性价比排序）**

1. **单独立项评估 RTMPose 关键点替换**（绕开 FreeMoCap，直接 ONNX，复用现有 YOLO）——低风险、不动架构、直接提升快速动作下的关键点质量。
2. 若确实要攻"旋转周数"难题，先做**拍摄规范**而非换算法：固定机位、缩短拍摄距离、提高快门速度、避免逆光和运动模糊。这往往比换模型收益更大，且零成本。
3. FreeMoCap / 多机位 3D 仅作为**长期方向**保留，需先明确硬件预算与现场配合方案。

---

## 附：本次评估依据

- FreeMoCap 仓库与 README：https://github.com/freemocap/freemocap
- 硬件/软件前置要求（单相机结论出处）：https://docs.freemocap.org/documentation/software-hardware-prerequisites.html
- 单相机录制指南：https://docs.freemocap.org/documentation/single-camera-recording.html
- FAQ（非实时、单人限制、AGPL）：https://docs.freemocap.org/documentation/frequently-asked-questions-faq.html
- 安装文档（Python 3.12 推荐）：https://docs.freemocap.org/documentation/installation.html
- PyPI 元数据（版本/依赖/许可/`requires_python`）：https://pypi.org/pypi/freemocap/json 、https://pypi.org/pypi/skellytracker/json 、https://pypi.org/pypi/skellycam/json
- skellytracker（RTMPose / 133 点 / extras）：https://github.com/freemocap/skellytracker
- SkellyCam（帧级同步机制）：https://github.com/freemocap/skellycam
- 代码级帧数约束：`freemocap/core/pipeline/posthoc/video_group_helper.py`
- 本机实测：CPU/GPU/内存/Python/Docker/PyPI 包版本（见第一节）
- 本项目现状：`README.md`、`backend/app/services/pose.py`、`backend/app/analysis_v2/rotation.py`、`backend/app/services/video.py`

> 本次评估全程只读：未修改任何源码，未安装任何软件包，未启动或重启任何服务。本文件为新增文档。
