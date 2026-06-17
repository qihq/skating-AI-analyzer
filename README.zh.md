# Skating Analyzer

面向滑冰学员、家长和教练的 AI 辅助花样滑冰训练复盘系统。项目把视频预检、目标跟踪、姿态估计、视频语义时序、双路径视觉分析和结构化报告整合到一套本地优先的训练工作流里。

[English README](./README.md) | [贡献指南](./CONTRIBUTING.md) | [许可证](./LICENSE) | [截图说明](./SCREENSHOT_GUIDE.md)

## 当前状态

- 当前分析管线版本：`v5.2.303`。
- 主分支：`master`。
- 运行时数据、上传视频、抽帧、备份、本地模型和导出的 Docker 包不会进入 Git。
- AI Key 启动时可不填。设置 `SECRET_KEY` 后，可在应用里的 `/settings/api` 配置供应商。

## 核心能力

- 在 `/review` 上传并分析训练视频。
- 不知道精确动作名称时，可以只选动作大类；技能分类可留空。
- 上传前填写的补充说明会进入最早的视频语义动作识别 prompt。
- 长视频可由家长手动指定 AI 重点看的起止秒数。
- 通过目标预览、手动画框、YOLO/ByteTrack 跟踪和身份安全门控锁定目标滑行者。
- 提取 MediaPipe 姿态，平滑信号，计算生物力学和跳跃/旋转证据。
- 使用兼容 Qwen 的视频语义定位识别动作大类和阶段时间。
- 语义关键帧通过可靠性检查后由 FFmpeg 精确抽取。
- 双路径视觉分析：
  - Path A：纯视觉 / 视频感知分析。
  - Path B：骨架叠加帧 + 生物力学 grounding。
- 生成结构化报告、Force Score、训练计划、技能进度、档案时间轴、调试日志和家长报告分享图。

## 视频分析流程

当前管线围绕源视频绝对时间戳运行，并记录实际 AI 输入范围：

```text
上传
  -> 视频预检与 AI 输入范围解析
  -> 运动采样与动作窗口元数据
  -> 目标预览或人工选人
  -> YOLO/ByteTrack 跟踪与 MediaPipe 姿态提取
  -> 生物力学、跳跃特征和关键帧候选
  -> 带用户备注的视频语义 AI
  -> 语义关键帧仲裁、重试、修复与 FFmpeg 抽取
  -> Path A / Path B 视觉分析
  -> 报告融合、评分融合、训练计划、档案和调试输出
```

关键行为：

- 用户填写手动起止秒数时优先使用手动片段；否则后端尽量使用全量上下文，并记录任何系统截断。
- 视频 AI 只提供语义时序和宏观判断，不会单独成为可信的逐帧裁判。
- 当 T/A/L 顺序、可见性、运动支持、骨架候选或重试结果不可靠时，语义关键帧会被降级或拒绝。
- 手动目标锁定具有身份权威性。tracker 诊断无法支持所选滑行者时，管线会 fail closed，避免把错误骨架画回报告。

完整模块说明见 [docs/ai-analysis-flow.md](./docs/ai-analysis-flow.md)。设计复盘和下一步迭代建议见 [docs/video-analysis-deep-review.md](./docs/video-analysis-deep-review.md)。

## 目录结构

```text
skating-analyzer/
|-- backend/                  # FastAPI 应用、分析编排和测试
|-- frontend/                 # React + Vite 前端
|-- docker/allinone/          # 单容器镜像配置
|-- docs/                     # 当前管线和复盘文档
|-- skating_vision/           # 独立视觉分析包
|-- ai_skating_analysis_pack/ # 参考包和实验内容
|-- scripts/                  # 诊断、批量分析、导出、备份脚本
|-- data/                     # 运行时数据，Git 忽略
|-- backups/                  # 运行时备份，Git 忽略
|-- models/                   # 本地 MediaPipe/YOLO 权重，Git 忽略
|-- deliverables/             # 导出镜像/交付物，Git 忽略
|-- .env.example
|-- docker-compose.yml
`-- README.zh.md
```

## 配置

复制 `.env.example` 为 `.env`，至少设置 `SECRET_KEY`：

```bash
cp .env.example .env
```

常用变量：

```bash
SECRET_KEY=replace-with-a-random-32-char-secret

# 可选 AI provider 默认值或环境变量 Key 兜底。
# 推荐启动后在 /settings/api 创建模型实例并保存 Key。
# QWEN_API_KEY=sk-...
# DASHSCOPE_API_KEY=sk-...
QWEN_VISION_MODEL=qwen3.6-plus
QWEN_VISION_DAILY_COST_LIMIT_CNY=30
QWEN_VISION_VIDEO_ESTIMATED_COST_CNY=0.6
# VIDEO_TEMPORAL_MAX_FRAMES=12

# 可选本地模型挂载。
# MEDIAPIPE_POSE_TASK_PATH=/models/pose_landmarker_heavy.task
# POSE_NUM_POSES=4
# YOLO_PERSON_MODEL_PATH=/models/yolov8n.pt
```

供应商说明：

- 后端启动不再自动 seed provider 行。
- 在 `/settings/api` 分别创建并激活 `report`、`vision`、`vision_path_a`、`vision_path_b`。
- NAS 旧数据库里的历史 provider 行可以保留；重复旧行不应再阻塞启动。
- `SECRET_KEY` 必填，因为应用会加密保存 provider API Key。

## 本地开发

后端：

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --no-use-colors
```

前端：

```bash
cd frontend
npm install
npm run dev
```

默认地址：

- 前端：`http://localhost:5173`
- 后端：`http://localhost:8000`
- 健康检查：`http://localhost:8000/api/health`

## Docker

Compose：

```bash
docker compose up --build
```

All-in-one 镜像：

```bash
docker build -f docker/allinone/Dockerfile -t skating-analyzer-allinone:latest .
docker run -d \
  --name skating-allinone \
  -p 8080:80 \
  -v "$(pwd)/data:/data" \
  -v "$(pwd)/backups:/backups" \
  -v "$(pwd)/models:/models:ro" \
  -v "$(pwd)/.env:/workspace/.env:ro" \
  skating-analyzer-allinone:latest
```

导出镜像：

```powershell
.\scripts\export-allinone-image.ps1
```

`data`、`backups`、`models` 建议始终保持宿主机挂载，避免运行时数据和模型文件被打进镜像。

## 测试

后端：

```bash
cd backend
pytest tests
```

前端：

```bash
cd frontend
npm run build
```

当前回归测试覆盖阶段重试、profile 推断、只填动作大类的上传、用户备注进入 prompt、视频语义解析、语义关键帧、目标锁定、人体跟踪、姿态平滑、双路径视觉、供应商回退、报告融合、训练计划和调试流程。

## 主要页面

- `/review`：上传视频、选择学员/动作上下文，可选手动 AI 输入片段。
- `/report/:id`：报告、评分、问题、建议、训练计划入口、分享图、重试/删除。
- `/report/:id/pose-debug`：骨架回放和 tracker 诊断。
- `/archive`：训练档案和分页时间轴。
- `/plan/:plan_id`：训练计划。
- `/settings/api`：provider slot 和 API Key 管理。
- `/debug`：debug run 回放、管线日志、语义帧、AI 输入范围和原始诊断。

## 数据与隐私

- 运行时数据默认写入 `./data`。
- 上传视频和抽帧素材不会提交到 Git。
- API Key 使用应用数据库加密存储。
- 对外共享时只应使用 `.env.example`。

## 许可证

MIT
