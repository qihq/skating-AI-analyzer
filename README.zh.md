# Skating Analyzer

花样滑冰训练分析系统，基于 React、FastAPI 和 Docker 构建。

[English README](./README.md)

[贡献指南](./CONTRIBUTING.md) · [许可证](./LICENSE) · [截图说明](./SCREENSHOT_GUIDE.md)

## Banner 预留区

等仓库封面图准备好之后，可以把横幅图放在这里：

```md
![Skating Analyzer banner](./docs/banner-placeholder.png)
```

## 项目简介

Skating Analyzer 是一个用于花样滑冰训练视频分析的全栈项目，支持上传视频、自动抽帧、姿态估计、生物力学指标分析、AI 诊断报告生成，以及通过技能树、训练计划和历史档案持续跟踪训练进展。

## 功能概览

- 视频上传与异步分析
- Pipeline v5.1.0：新增独立 Pose Debug 大屏回放页，并适配手机、iPad、网页端和 PWA 安全区
- Pose Debug 页面集中展示骨架回放、当前帧 bbox、追踪置信度、候选数量、pose diagnostics、追踪缩略图和生物力学关键帧联动
- 设置页已拆分姿态运行时与 YOLO 追踪运行时检查，两者拥有独立的重新检查按钮、加载状态、检查时间和错误提示
- Qwen 3.6 Plus 视频语义时间定位，输出阶段区间和 key_frame_hint
- 时间戳仲裁层结合视频 AI 区间、运动密度和骨架候选，再由 FFmpeg 精准抽取语义关键帧
- 语义关键帧图片 AI 精析，prompt 中携带 `video_context`
- 关键帧抽取与 MediaPipe 姿态识别
- 生物力学指标计算与结构化评分
- AI 训练诊断报告
- 阶段感知重试流程，支持缓存帧复用
- 处理日志、管线计时、报告页调试信息
- YOLO + ByteTrack 目标追踪，支持挂载 `yolov8n.pt` 并在设置页查看运行时状态
- 报告页 Pose Replay 可打开 `/report/:id/pose-debug`，用于大屏查看骨架和追踪调试数据
- 自动检测过期任务并恢复失败状态
- 模糊过滤与动作感知帧采样，提升视觉输入质量
- 独立 `skating_vision` Python 包，可脱离主应用复用
- 儿童模式 / 家长模式双视角
- 技能树、训练计划、历史档案、成长追踪
- Docker 一体化部署

## 截图预留区

后续可替换为真实产品截图：

```md
![技能树](./docs/screenshots/skill-tree.png)
![上传与分析流程](./docs/screenshots/review-flow.png)
![报告页](./docs/screenshots/report-page.png)
![历史档案](./docs/screenshots/archive.png)
```

## 技术栈

- 前端：React 18、TypeScript、Vite、Tailwind CSS、React Router、Recharts
- 后端：FastAPI、SQLAlchemy Async、SQLite
- 多媒体与视觉：FFmpeg、OpenCV、MediaPipe
- AI 接入：兼容 OpenAI SDK 的视觉 / 文本模型供应商
- 部署：Docker、nginx

## 目录结构

```text
skating-analyzer/
├─ backend/                  # FastAPI 后端
│  ├─ app/
│  │  ├─ routers/            # API 路由
│  │  ├─ services/           # 分析、报告、供应商、技能等服务
│  │  ├─ main.py
│  │  ├─ models.py
│  │  └─ schemas.py
│  └─ requirements.txt
├─ frontend/                 # React 前端
│  ├─ src/
│  └─ public/
├─ skating_vision/           # 独立视觉分析 Python 包
├─ docs/
│  └─ ai-analysis-flow.md   # 完整 10 阶段管线文档
├─ docker/
│  └─ allinone/              # allinone 镜像构建配置
├─ data/                     # 运行时数据（已忽略）
├─ backups/                  # 备份目录（数据库文件已忽略）
├─ .env.example
├─ docker-compose.yml
└─ README.zh.md
```

## 环境变量

复制 `.env.example` 为 `.env`，并填写你自己的密钥：

```bash
cp .env.example .env
```

示例：

```bash
QWEN_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
QWEN_VISION_MODEL=qwen3.6-plus
QWEN_VISION_DAILY_COST_LIMIT_CNY=30
QWEN_VISION_VIDEO_ESTIMATED_COST_CNY=0.6
# VIDEO_TEMPORAL_MAX_FRAMES=12
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
SECRET_KEY=replace-with-a-random-32-char-secret
# 可选：启用二期多姿态跟踪
# MEDIAPIPE_POSE_TASK_PATH=/models/pose_landmarker_heavy.task
# POSE_NUM_POSES=4

# 可选：使用挂载的 YOLO 人体检测权重，避免运行时下载
# YOLO_PERSON_MODEL_PATH=/models/yolov8n.pt
```

说明：

- `.env` 不会提交到 Git 仓库
- `.env.example` 只保留占位符
- 默认视觉模型为 `qwen3.6-plus`；`qwen-vl-max-latest` 仅作为历史迁移兼容输入，不再推荐作为默认模型
- `QWEN_VISION_DAILY_COST_LIMIT_CNY` 控制每日视觉成本上限，`QWEN_VISION_VIDEO_ESTIMATED_COST_CNY` 用于估算单次视频语义定位成本，`VIDEO_TEMPORAL_MAX_FRAMES` 控制进入图片 AI 的语义帧预算
- 运行期数据库、上传视频和备份文件不会被提交

## 二期姿态模型启用

二期多姿态和目标追踪通过宿主机挂载模型文件启用。

- 将模型文件放到 `./models`，例如 `./models/pose_landmarker_heavy.task`
- 在 `.env` 中设置 `MEDIAPIPE_POSE_TASK_PATH=/models/pose_landmarker_heavy.task`
- 可选设置 `POSE_NUM_POSES=4`
- 如需 YOLO 目标追踪，将 `yolov8n.pt` 放到 `./models`，并可选设置 `YOLO_PERSON_MODEL_PATH=/models/yolov8n.pt`。如果未设置该变量，后端会先检查 `/models/yolov8n.pt`，再允许 Ultralytics 自动下载 `yolov8n.pt`
- 设置页会分别显示姿态运行时和 YOLO 运行时状态，并提供独立重新检查按钮，方便确认模型文件和依赖是否已生效
- 模型文件不提交到当前仓库
- 如果模型缺失或加载失败，后端会自动降级回一期单人 pose 流程

## 分析管线更新

最近的迭代聚焦于让关键帧更准确、长时间运行的视频分析更可观测、更容易恢复：

- 视频 AI 先做语义阶段定位，不直接充当逐帧裁判
- 时间戳仲裁层在阶段区间内结合运动峰值和 MediaPipe 骨架候选确认最终切帧点
- 图片 AI 分析仲裁后的语义关键帧，并可对视频上下文做 agree / shifted / disagree / uncertain 验证
- 报告层融合视频宏观评价、图片微观帧级观察和 MediaPipe 生物力学数值，冲突时保守表达
- 基于阶段的管线状态（抽帧、姿态、生物力学、视觉、报告生成）
- 从最后一个安全阶段重试，而非每次从头开始
- API 和报告页返回处理日志与各阶段耗时
- 自动检测过期的进行中分析，提供失败恢复提示
- 重试时复用缓存的抽帧和已恢复帧
- 跳跃、旋转、燕式、步法等动作的感知提示
- 跳跃专属启发式：腾空检测、旋转信号、跳跃类型推断
- 视觉编码前的模糊帧过滤，减少低质量输入噪声

## skating_vision 独立模块

`skating_vision` 目录是一个独立的 Python 包，将核心分析模块抽取出来，可在主 FastAPI 应用之外复用。包含：

- **video** — 抽帧、运动采样、动作窗口检测、模糊过滤
- **pose** — MediaPipe 姿态提取，支持多候选回退
- **biomechanics** — 几何启发式指标、跳跃旋转估算
- **vision** — 基于 LLM 的逐帧视觉分析
- **report** — 结构化报告生成与评分融合
- **providers** — 兼容 OpenAI SDK 的供应商抽象
- **target_lock** — 主滑行者候选锁定
- **action_profiles** — 跳跃、旋转、燕式、步法序列的动作推断

安装为本地包或直接导入：

```python
from skating_vision.video import extract_motion_sampled_frames
from skating_vision.pose import extract_pose
from skating_vision.biomechanics import analyze_biomechanics
from skating_vision.report import generate_report
```

详见 [docs/ai-analysis-flow.md](./docs/ai-analysis-flow.md) 完整 10 阶段管线文档。

## 本地开发

### 后端

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

### 前端

```bash
cd frontend
npm install
npm run dev
```

默认地址：

- 前端：`http://localhost:5173`
- 后端：`http://localhost:8000`

## 测试

后端回归测试覆盖新增的管线和启发式逻辑，包括：

- 动作推断（根据用户输入推断分析类型）
- 阶段重试与管线版本行为
- 模糊过滤与视觉回退处理
- 相位平滑
- 生物力学归一化与跳跃旋转估算

运行：

```bash
cd backend
pytest tests
```

## Docker 部署

### docker-compose

```bash
docker compose up --build
```

如果要启用二期多姿态跟踪，启动 Docker Compose 前请先将模型文件放入 `./models`。

默认地址：

- 应用首页：`http://localhost:8080`
- 健康检查：`http://localhost:8080/api/health`

### allinone 镜像

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

说明：

- 如果使用 `.env` 文件方式运行 allinone，请确保其中包含 `MEDIAPIPE_POSE_TASK_PATH=/models/pose_landmarker_heavy.task`；使用挂载 YOLO 权重时，也加入 `YOLO_PERSON_MODEL_PATH=/models/yolov8n.pt`
- 如果在 NAS / Container Manager 中直接手动配置环境变量，可以不挂载 `.env`，但仍需额外设置同名环境变量，并挂载 `models` 目录
- 旧的分析记录如果保存的是 Windows 本地绝对路径，allinone 会自动回退到 `/data/uploads/<analysis_id>/source.*` 查找原始视频

导出：

```bash
docker save -o skating-analyzer-allinone-latest.tar skating-analyzer-allinone:latest
```

## 主要页面

- `/path`：技能树与学习路径
- `/review`：上传视频并发起分析
- `/report/:id`：分析报告
- `/report/:id/pose-debug`：大屏姿态回放、追踪 diagnostics 与生物力学调试页
- `/archive`：历史档案 / 训练进展
- `/plan/:plan_id`：训练计划
- `/snowball`：冰宝陪练与记忆建议
- `/settings`：系统设置、PIN、备份、供应商管理、姿态与 YOLO 运行时状态独立检查
- `/debug`：分析调试日志，支持自动刷新最新分析状态

## 数据与隐私

- 运行数据默认写入 `./data`
- 上传视频与抽帧素材不会进入 Git
- API Key 使用应用内加密存储
- 对外公开时请只提交 `.env.example`

## 当前仓库不包含

- 真实 API Key
- 本地数据库
- 训练视频与媒体素材
- 导出的 Docker tar 包
- 本地 worktree 元数据如 `.claude/`
- 交付物打包产物

## 开源补充材料

- 封面图文案：[REPO_COVER_COPY.md](./REPO_COVER_COPY.md)
- GitHub About / Topics 文案：[GITHUB_PROFILE_COPY.md](./GITHUB_PROFILE_COPY.md)
- 截图规划：[SCREENSHOT_GUIDE.md](./SCREENSHOT_GUIDE.md)
- Release 文案草稿：[RELEASE_BODY_v1.0.0.md](./RELEASE_BODY_v1.0.0.md)
- AI 分析流程文档：[docs/ai-analysis-flow.md](./docs/ai-analysis-flow.md)
- 迭代开发指南：[video-analysis-iteration-guide.md](./video-analysis-iteration-guide%20(1).md)

## 许可证

MIT
