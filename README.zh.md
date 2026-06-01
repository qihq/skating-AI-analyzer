# Skating Analyzer

基于 React、FastAPI、MediaPipe、YOLO/ByteTrack 和 Docker 的花样滑冰训练视频分析系统。

[English README](./README.md) | [贡献指南](./CONTRIBUTING.md) | [许可证](./LICENSE) | [截图说明](./SCREENSHOT_GUIDE.md)

## 项目简介

Skating Analyzer 面向滑冰学员、家长和教练，用一套可复现的分析流程辅助复盘训练视频。系统会上传视频、抽取运动采样帧、锁定目标滑行者、运行姿态与人体跟踪、解析起跳/腾空/落冰关键时刻，并在配置 AI 供应商后调用视觉模型生成结构化报告、训练计划、档案和进度视图。

当前分析管线版本为 `v5.2.10`。

## 最近更新

最新版本重点避免 NAS 升级时旧 AI 供应商数据阻塞容器启动，同时保留通过 UI 配置模型实例的流程。

- `v5.2.10`：后端启动不再自动 seed AI provider；请在 `/settings/api` 创建模型实例。旧数据库里重复的历史 provider 行不会再阻塞容器启动。
- `v5.2.9`：Path A 会请求更严格的 JSON、恢复非标准模型输出、追加一次 JSON-only 修复重试；报告在 Path A 不可用时会回退使用 Path B/top issues 证据和动作专项训练建议。
- `v5.2.8`：丢失后复用的 tracker bbox 可作为带 padding 的 pose crop hint，用于远距离小目标滑行者。
- `v5.2.7`：当 overlap-safe rejected tracker hint 成为 reference bbox 时，应用 tracker 风格的 crop padding。
- `v5.2.6`：overlap-safe continuity-rejected tracker bbox 可作为 pose crop hint 复用，但不会接受目标身份切换。
- `v5.2.5`：当同时尝试 motion-predicted crop 时，regular pose crop 会按真实 reference bbox 校验。
- `v5.2.4`：保留完整有序的可见 T/A/L 候选，同时保留低置信度关键帧警告。
- `v5.2.3`：未确认但通过 gate 的 tracker relock bbox 可辅助 pose crop，不切换目标身份。
- `v5.2.2`：快速目标运动中保留 tracker-aligned crop pose，避免过度惩罚 seed bbox drift。
- `v5.2.1`：收紧跳跃动作窗口 padding，目标预览优先锚定高运动采样帧。
- `v5.2.0`：Debug 回放复用正式采样流程，并从关键帧评分中排除不可靠 pose 帧。

## 核心功能

- 视频上传、异步分析与阶段感知重试。
- 运动采样、视频预检、模糊过滤和更大的 nginx 上传限制。
- 目标预览、手动目标锁定、YOLO + ByteTrack 人体跟踪和逐帧 bbox 诊断。
- MediaPipe 姿态提取，支持平滑、多候选和 crop 回退逻辑。
- 生物力学指标，包括阶段时序、跳跃证据、旋转估算和姿态质量。
- Qwen 3.6 Plus 视频语义时间定位，解析起跳/腾空/落冰区间。
- 结合视频 AI、运动密度和骨架候选的语义关键帧时间戳仲裁。
- 双路径视觉分析，支持 video context、供应商回退、非标准 JSON 恢复、重试处理和成本限制。
- AI 辅助报告、训练计划、技能树、历史档案、进度追踪、儿童模式和家长模式；报告兜底会使用 Path B 证据和动作专项训练建议。
- Pose Debug 与 Debug 页面，用于骨架回放、tracker 缩略图、候选数量、姿态诊断、耗时和日志检查。
- Docker Compose 与 all-in-one Docker 部署，适合 NAS 或本地单容器运行。

## 分析流程

1. 上传源视频并创建分析记录。
2. 执行视频预检、运动采样和动作窗口检测。
3. 生成目标预览候选；置信度不足时等待手动选择。
4. 使用 YOLO/ByteTrack 跟踪目标滑行者，并执行逐帧 bbox 连续性检查。
5. 从 regular、tracker-guided 和 fallback crop 中提取姿态点。
6. 平滑姿态信号，计算生物力学、跳跃特征和关键帧候选。
7. 在已配置供应商时运行视频语义 AI，解析 T/A/L 时间戳。
8. 用 FFmpeg 抽取语义关键帧，并把 video context 注入图片 AI。
9. 融合姿态、生物力学、视频 AI、Path A 纯视觉和 Path B 骨架量化证据，生成结构化报告。
10. 持久化帧、日志、耗时、调试摘要和重试检查点。

## 技术栈

- 前端：React 18、TypeScript、Vite、Tailwind CSS、React Router、Recharts。
- 后端：FastAPI、SQLAlchemy Async、SQLite、APScheduler。
- 视觉与媒体：FFmpeg、OpenCV、MediaPipe、YOLO/ByteTrack、PyTorch CPU。
- AI 接入：兼容 OpenAI SDK 的文本、图片和视频语义视觉供应商。
- 部署：Docker、nginx、Docker Compose、all-in-one 容器镜像。

## 目录结构

```text
skating-analyzer/
|-- backend/                  # FastAPI 后端
|   |-- app/
|   |   |-- configs/          # 动作 profile 与供应商配置
|   |   |-- routers/          # API 路由
|   |   |-- services/         # 分析、姿态、跟踪、视觉、报告、技能服务
|   |   |-- main.py
|   |   |-- models.py
|   |   `-- schemas.py
|   |-- tests/                # 后端回归测试
|   `-- requirements.txt
|-- frontend/                 # React 前端
|   |-- src/
|   `-- public/
|-- docker/
|   `-- allinone/             # all-in-one 镜像 Dockerfile、nginx 配置和启动脚本
|-- docs/                     # 管线文档
|-- skating_vision/           # 独立视觉分析包
|-- ai_skating_analysis_pack/ # 独立参考包
|-- scripts/                  # 诊断、批量分析、镜像导出脚本
|-- data/                     # 运行时数据，Git 忽略
|-- backups/                  # 运行时备份，Git 忽略
|-- models/                   # 本地模型权重，Git 忽略
|-- deliverables/             # 导出的镜像文件，Git 忽略
|-- .env.example
|-- docker-compose.yml
`-- README.zh.md
```

## 环境变量

复制 `.env.example` 为 `.env`，并填写自己的密钥：

```bash
cp .env.example .env
```

示例：

```bash
# AI Key 启动时可不填。推荐应用启动后进入
# 家长设置 -> API 设置，创建模型实例并保存 Key。
# QWEN_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
QWEN_VISION_MODEL=qwen3.6-plus
QWEN_VISION_DAILY_COST_LIMIT_CNY=30
QWEN_VISION_VIDEO_ESTIMATED_COST_CNY=0.6
# VIDEO_TEMPORAL_MAX_FRAMES=12
# DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
SECRET_KEY=replace-with-a-random-32-char-secret

# 可选：启用二期多姿态跟踪
# MEDIAPIPE_POSE_TASK_PATH=/models/pose_landmarker_heavy.task
# POSE_NUM_POSES=4

# 可选：使用挂载的 YOLO 人体检测权重，避免运行时下载
# YOLO_PERSON_MODEL_PATH=/models/yolov8n.pt
```

说明：

- `.env` 不会提交到 Git。
- 后端启动时不会再自动写入 AI provider 行。请在 `/settings/api` 创建文本报告、主视觉、Path A 和 Path B 模型实例，并按 slot 激活需要使用的供应商。
- NAS 上已有的旧数据库可以继续复用；重复的历史 provider 行不会再导致容器启动失败。
- 默认视觉模型为 `qwen3.6-plus`；`qwen-vl-max-latest` 只作为历史迁移输入保留。
- `QWEN_VISION_DAILY_COST_LIMIT_CNY` 控制每日视觉成本上限。
- `QWEN_VISION_VIDEO_ESTIMATED_COST_CNY` 用于估算单次视频语义调用成本。
- `VIDEO_TEMPORAL_MAX_FRAMES` 控制进入图片 AI 的语义帧数量。
- 运行时数据库、上传视频、抽帧、备份、Docker tar 包和本地模型文件不会提交。

## 双路径报告韧性

分析流程会同时保存 `vision_path_a` 和 `vision_path_b`，便于审计和调试。

- Path A 是纯视觉判断。现在会要求供应商返回 JSON 对象，从带噪输出中抽取合法 JSON，并在失败时追加一次低温 JSON 修复请求，再标记 Path A 不可用。
- Path B 使用叠加骨架的关键帧和生物力学数值。它的 `top_issues`、`top_positives`、阶段摘要和帧级问题会注入报告上下文。
- 如果 Path A 失败，或报告模型输出过于模板化，后端会用 Path B 证据替换“数据质量有限”类占位问题，并按跳跃、旋转、燕式、步法 profile 生成更具体的训练动作。
- 当证据不完整时，报告仍会保持 `data_quality=partial`，但问题列表和改进建议应继续绑定到可见或可量化的技术结论。

## 本地模型

二期多姿态和人体跟踪通过宿主机挂载模型文件启用。

- 将 MediaPipe task 文件放到 `./models`，例如 `./models/pose_landmarker_heavy.task`。
- 在 `.env` 中设置 `MEDIAPIPE_POSE_TASK_PATH=/models/pose_landmarker_heavy.task`。
- 可选设置 `POSE_NUM_POSES=4`。
- 将 YOLO 权重放到 `./models`，例如 `./models/yolov8n.pt`。
- 可选设置 `YOLO_PERSON_MODEL_PATH=/models/yolov8n.pt`。
- 如果没有设置 `YOLO_PERSON_MODEL_PATH`，后端会先检查 `/models/yolov8n.pt`，再允许 Ultralytics 下载 `yolov8n.pt`。
- 设置页会分别展示姿态运行时和 YOLO 运行时状态。
- 如果模型缺失或加载失败，后端会回退到可用的更保守流程。

## skating_vision 独立包

`skating_vision` 目录是一个可脱离 FastAPI 主应用复用的独立 Python 包。

- `video`：抽帧、运动采样、动作窗口检测、模糊过滤。
- `pose`：MediaPipe 姿态提取，支持多候选回退。
- `biomechanics`：几何指标和跳跃旋转估算。
- `vision`：基于 LLM 的视觉分析。
- `report`：结构化报告生成和评分融合。
- `providers`：兼容 OpenAI SDK 的供应商抽象。
- `target_lock`：主滑行者候选锁定。
- `action_profiles`：跳跃、旋转、燕式和步法序列的动作类型推断。

```python
from skating_vision.video import extract_motion_sampled_frames
from skating_vision.pose import extract_pose
from skating_vision.biomechanics import analyze_biomechanics
from skating_vision.report import generate_report
```

完整管线说明见 [docs/ai-analysis-flow.md](./docs/ai-analysis-flow.md)。

## 本地开发

后端：

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

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

## 测试

后端回归测试覆盖：

- 根据用户输入推断动作 profile。
- 阶段重试和管线版本行为。
- debug run 持久化和回放流程。
- 视频预检、精准抽帧和语义时间解析。
- bbox tracking、target lock、person tracking 和 pose smoothing。
- 关键帧候选、T/A/L 顺序和生物力学时序。
- 双路径视觉、Path A 非标准 JSON 恢复、供应商重试、报告融合和内容归一化。

运行后端测试：

```bash
cd backend
pytest tests
```

构建前端：

```bash
cd frontend
npm run build
```

## Docker Compose

```bash
docker compose up --build
```

如果要启用二期姿态或 YOLO 跟踪，请在启动 Docker Compose 前把模型文件放入 `./models`。

默认地址：

- 应用：`http://localhost:8080`
- API 健康检查：`http://localhost:8000/api/health`

## all-in-one 镜像

构建：

```bash
docker build -f docker/allinone/Dockerfile -t skating-analyzer-allinone:latest .
```

运行：

```bash
docker run -d \
  --name skating-allinone \
  -p 8080:80 \
  -v "$(pwd)/data:/data" \
  -v "$(pwd)/backups:/backups" \
  -v "$(pwd)/models:/models:ro" \
  -v "$(pwd)/.env:/workspace/.env:ro" \
  skating-analyzer-allinone:latest
```

导出：

```powershell
.\scripts\export-allinone-image.ps1
```

导出脚本会重新构建 `skating-analyzer-allinone:latest`，从 `backend/app/services/pipeline_version.py` 读取当前管线版本，并在 `./deliverables` 下生成带时间戳的 tar 文件。

all-in-one 说明：

- 如果挂载 `.env`，启用 MediaPipe task 模型时请包含 `MEDIAPIPE_POSE_TASK_PATH=/models/pose_landmarker_heavy.task`。
- 使用挂载 YOLO 权重时请包含 `YOLO_PERSON_MODEL_PATH=/models/yolov8n.pt`。
- 如果在 NAS 或 Container Manager 里直接配置环境变量，可以不挂载 `.env`。
- AI provider 的 API Key 可以在启动后进入 `/settings/api` 配置；容器启动只要求 `SECRET_KEY` 用于加密保存的 Key。
- `data`、`backups` 和 `models` 应保持宿主机挂载，避免运行时数据和模型文件被打进镜像。
- 旧分析记录如果保存的是 Windows 绝对路径，all-in-one 会回退到容器内 `/data/uploads/<analysis_id>/source.*` 查找原视频。

## 镜像体积说明

all-in-one 镜像比拆分前端镜像大是预期现象，因为它同时包含后端、前端、FFmpeg、nginx、MediaPipe、OpenCV、PyTorch CPU、Ultralytics YOLO 和跟踪依赖。

最近检查 `skating-analyzer-allinone:latest` 的结果：

- Docker 镜像大小约 `3.72GB`。
- 最大镜像层是 `pip install` 安装 Python 依赖，约 `2.25GB`。
- 系统媒体/服务层包含 `ffmpeg`、`nginx`、`curl`，约 `467MB`。
- 最大 Python 包包括：`torch` 约 `724MB`、`jaxlib` 约 `330MB`、`scipy` 约 `113MB`、OpenCV 相关包与 libs 合计约 `337MB`、`mediapipe` 约 `66MB`。
- `tmp/` 诊断产物会让 Docker build context 和 Git 历史变得很吵，但 all-in-one Dockerfile 最终只复制 `backend/app`、`backend/requirements.txt`、`frontend` 和 `docker/allinone` 文件。现在 `tmp/` 已加入 Git 和 Docker 忽略规则。

## 主要页面

- `/path`：技能树与学习路径。
- `/review`：上传视频并发起分析。
- `/report/:id`：分析报告。
- `/report/:id/pose-debug`：大屏骨架回放与 tracker 诊断。
- `/archive`：历史档案与训练进度。
- `/plan/:plan_id`：训练计划。
- `/snowball`：陪练聊天和记忆建议。
- `/settings`：PIN、备份、供应商、成本限制、姿态运行时和 YOLO 运行时检查。
- `/debug`：分析调试日志和 debug run 回放。

## 数据与隐私

- 运行时数据默认写入 `./data`。
- 上传视频和抽帧素材不会进入 Git。
- API Key 使用应用内加密存储。
- 对外公开时只应共享 `.env.example`。

## 当前仓库不包含

- 真实 API Key。
- 本地数据库。
- 训练视频或抽帧素材。
- 导出的 Docker tar 包。
- 本地模型权重。
- 本地 worktree 元数据。
- 临时诊断和交付物打包产物。

## 开源补充材料

- 封面图文案：[REPO_COVER_COPY.md](./REPO_COVER_COPY.md)
- GitHub About / Topics 文案：[GITHUB_PROFILE_COPY.md](./GITHUB_PROFILE_COPY.md)
- 截图规划：[SCREENSHOT_GUIDE.md](./SCREENSHOT_GUIDE.md)
- Release 文案草稿：[RELEASE_BODY_v1.0.0.md](./RELEASE_BODY_v1.0.0.md)
- AI 分析流程：[docs/ai-analysis-flow.md](./docs/ai-analysis-flow.md)
- 迭代开发指南：[video-analysis-iteration-guide.md](./video-analysis-iteration-guide%20(1).md)

## 许可证

MIT
