# 模型权重文件说明

## 概述

本分析模块使用的 AI 模型均为**云端 API 调用**，不包含本地训练的模型权重文件。
唯一的本地模型是 MediaPipe Pose Landmarker（骨骼姿态估计）。

---

## 1. MediaPipe Pose Landmarker（本地模型）

### 用途
从视频帧中提取 33 个人体骨骼关键点（归一化坐标）。

### 模型架构
- Google MediaPipe Pose Landmarker
- 基于 BlazePose 架构（轻量级 CNN）
- 输入：RGB 图像（任意分辨率，内部 resize 到 256x256）
- 输出：33 个关键点的 (x, y, z, visibility) 归一化坐标

### 权重来源
- **默认模式（单人）**：MediaPipe 库内置权重，随 `mediapipe==0.10.14` pip 包自动下载
  - 路径：`~/.mediapipe/modules/pose_landmark/pose_landmark_lite.tflite`（自动管理）
  - 无需手动下载

- **多人模式（可选）**：需要额外下载 Tasks API 模型文件
  - 模型文件名：`pose_landmarker.task`
  - 下载地址：https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker/float16/latest/pose_landmarker.task
  - 代码中通过环境变量 `MEDIAPIPE_POSE_TASK_PATH` 指定路径
  - 若未配置或文件不存在，自动回退到单人模式

### 配置方式
```bash
# 可选：启用多人姿态检测
export MEDIAPIPE_POSE_TASK_PATH=/path/to/pose_landmarker.task
export POSE_NUM_POSES=4  # 最多检测人数，默认 4
```

### 性能特征
- 单人模式：每帧约 30-50ms（CPU）
- 多人模式：每帧约 80-120ms（CPU）
- 关键点精度：visibility > 0.5 的关键点可信度较高

---

## 2. 多模态 LLM（云端 API）

### 视觉分析槽（vision slot）
- **默认供应商**：阿里云通义千问 Qwen 3.6 Plus
  - API：`https://dashscope.aliyuncs.com/compatible-mode/v1`
  - 模型 ID：`qwen3.6-plus`
  - 能力：图像理解 + 结构化 JSON 输出
  - 输入：最多 20 帧 480p 图片（base64） + 文本 prompt
  - 输出：逐帧 phase/observations/issues 结构化 JSON

- **备选供应商**：
  - Kimi K2.5（`https://api.moonshot.cn/v1`）
  - GLM-4.5V（`https://open.bigmodel.cn/api/paas/v4`）
  - Doubao Seed 2.0（`https://ark.cn-beijing.volces.com/api/v3`）

### 报告生成槽（report slot）
- **默认供应商**：DeepSeek-V3
  - API：`https://api.deepseek.com/v1`
  - 模型 ID：`deepseek-chat`
  - 能力：纯文本生成 + 结构化 JSON 输出
  - 输入：视觉分析结果 JSON + 生物力学指标 JSON
  - 输出：结构化训练报告 JSON

- **备选供应商**：
  - Doubao Seed 2.0
  - MiniMax M2.7
  - GLM-5
  - Qwen-Max

### API Key 配置
```bash
# 视觉分析（至少配置一个）
export QWEN_API_KEY=sk-xxxxxxxx
# 或
export DASHSCOPE_API_KEY=sk-xxxxxxxx

# 报告生成（至少配置一个）
export DEEPSEEK_API_KEY=sk-xxxxxxxx

# 其他可选
export KIMI_API_KEY=sk-xxxxxxxx
export DOUBAO_API_KEY=sk-xxxxxxxx
export MINIMAX_API_KEY=sk-xxxxxxxx
export GLM_API_KEY=sk-xxxxxxxx

# API Key 加密密钥（必填）
export SECRET_KEY=your-32-char-random-string
```

---

## 3. 不包含的权重

以下模型在当前版本中**未使用**，但可作为未来优化方向：

| 模型类型 | 可选方案 | 用途 |
|---------|---------|------|
| 动作分类 CNN | SlowFast / VideoMAE | 替代 LLM 做端到端动作识别 |
| 跳跃检测时序模型 | LSTM / TCN | 从关键点序列自动检测跳跃事件 |
| 周数估算模型 | 回归 CNN | 从旋转角速度曲线估算跳跃周数 |
| 旋转定级模型 | GCN (图卷积) | 从骨骼姿态序列评估旋转等级 |
| 人体检测 YOLO | YOLOv8-pose | 替代 MediaPipe 做多人检测 |

---

## 4. 权重文件大小参考

| 文件 | 大小 | 来源 |
|------|------|------|
| pose_landmark_lite.tflite | ~5.5 MB | MediaPipe 内置 |
| pose_landmarker.task | ~12 MB | Google Storage（可选） |
| Qwen 3.6 Plus | N/A（云端） | 阿里云 |
| DeepSeek-V3 | N/A（云端） | DeepSeek |
