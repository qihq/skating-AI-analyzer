# 模型权重说明

本模块使用的模型权重均为外部服务托管，无需本地下载。

## MediaPipe Pose (姿态估计)

- **来源**: Google MediaPipe (内置权重)
- **安装方式**: `pip install mediapipe==0.10.14`
- **权重位置**: MediaPipe 包内自动管理，无需手动下载
- **单人模式**: `mediapipe.solutions.pose.Pose` (model_complexity=1)
- **多人模式**: 需要单独配置 `MEDIAPIPE_POSE_TASK_PATH` 环境变量指向 `.task` 模型文件
  - 下载地址: https://developers.google.com/mediapipe/solutions/vision/pose_landmarker
  - 文件名: `pose_landmarker_heavy.task` (~30MB)
  - 配置方式: `MEDIAPIPE_POSE_TASK_PATH=/path/to/pose_landmarker_heavy.task`

## LLM 视觉模型 (远程 API)

本模块不使用本地权重，而是通过 API 调用远程大语言模型：

| 角色 | 默认模型 | API 端点 |
|------|---------|---------|
| Vision (视觉分析) | qwen3.6-plus | https://dashscope.aliyuncs.com/compatible-mode/v1 |
| Report (报告生成) | deepseek-chat | https://api.deepseek.com/v1 |

## CSRT 跟踪器 (bbox_tracker)

- **来源**: OpenCV 内置
- **安装方式**: `pip install opencv-python-headless==4.10.0.84`
- **权重位置**: OpenCV 包内自动管理
