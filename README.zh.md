# Skating Analyzer

基于 React、FastAPI、MediaPipe、YOLO/ByteTrack 和 Docker 的花样滑冰训练视频分析系统。

[English README](./README.md) | [贡献指南](./CONTRIBUTING.md) | [许可证](./LICENSE) | [截图说明](./SCREENSHOT_GUIDE.md)

## 项目简介

Skating Analyzer 面向滑冰学员、家长和教练，用一套可复现的分析流程辅助复盘训练视频。系统会上传视频、抽取运动采样帧、锁定目标滑行者、运行姿态与人体跟踪、解析起跳/腾空/落冰关键时刻，并在配置 AI 供应商后调用视觉模型生成结构化报告、训练计划、档案和进度视图。

当前分析管线版本为 `v5.2.307`。

## 最近更新

当前分支新增了可持久化的对比工作台，明确拆分视频 AI 与文字报告 AI，并加强训练计划兜底：

- 对比生成改为后台任务，点击开始后会立即保存一条 `analysis_comparisons` 记录，支持 pending、processing、completed、failed 状态。
- 对比工作台只把两个完整源视频交给当前激活的 `vision` provider。`vision=mimo` 时使用当前激活的视频模型，例如 `mimo-v2.5`；`vision=qwen` 时使用配置中的 Qwen video model，避免隐藏写死。
- `report` provider 只接收结构化对比 JSON，再基于文字数据生成家长可读总结；不会接收视频，也不会调用多模态能力。
- 对比结果会融合视频 AI 输出、已有评分、报告、生物力学、关键帧和同步播放数据，再生成最终结构化结果。
- 历史页新增“分析记录 / 对比结果”tab，对比结果支持状态展示、轮询、失败重试和详情入口。
- 对比页新增与普通分析一致的分享能力：生成分享图预览、复制图片、下载图片，以及在支持的平台调用系统分享。
- 同步播放现在会等待两侧视频 metadata，同时 seek、同时 play/pause，并避免单侧 pause 事件误改全局播放状态。
- 新建和续期训练计划在 AI 失败、JSON 不完整、报告结构异常或只有最小动作上下文时，都会返回安全可用的兜底计划。
- 追问聊天现在能识别“只用视频 AI 重新识别关键帧”等请求，也可以点击“视频 AI 重识别关键帧”；系统会只用完整原视频重新定位 T/A/L，并生成待确认关键帧修正卡，不重置主人物锁定、不重跑 pose/生物力学/Path A/B、不自动应用数据，也不覆盖报告。
- 追问聊天仍会区分完整重新分析请求，并提供明确的确认操作；确认后会重置主人物锁定，从目标定位开始重新跑完整管线。
- 分析重试接口支持 `reset_target_lock=true`，Archive/History 重试和追问触发的完整重新分析都会重新选定主人物，不复用可能过期的 skater lock。
- 报告和追问分享图支持更长的总结、问题、回答和修正说明，卡片高度会自适应，并导出压缩 JPEG，便于复制或分享文件。
- 报告页和独立 `/analysis-chat` 工作台现在支持围绕任意已完成分析进行持久化多轮 AI 追问。
- AI 或手动提出的动作识别、动作确认、关键帧、报告说明和重新生成报告都会先保存为可审计修正卡，确认应用后才生效。
- 报告读取、导出、追问上下文和分享都会读取“原始分析 + 已应用修正”的有效数据层，同时保留原始分析 JSON 不覆盖。
- 追问分享现在返回可复制文字和图片卡数据，包含最新问答、已应用修正、待确认修正和报告链接。
- 追问 UI 已适配手机、平板和桌面：手机使用紧凑视频选择器和底部固定输入，平板混排，桌面为列表/聊天/证据三栏。
- Review 上传可以只选动作大类，不知道精确动作名称也能提交，上传前填写的 comments 会进入最早的动作识别 prompt。
- 训练计划会记录来源是 AI 还是安全兜底，兜底计划在页面上明显标注。
- 家长模式的报告分享改为生成含关键重要信息的分享图，便于发给教练或家人。
- Pose Replay 播放不再因为报告页回写当前帧而只播一帧就停。
- Archive 改为紧凑响应式指标条，并把查看对象、动作筛选、时间范围、列表/日历视图合并到记录区工具条；时间轴继续使用 `limit`/`offset` 分页首屏加载，保留总数统计并支持“加载更多”。
- Report 主页面聚焦 Force Score、结论、训练重点、问题建议、分项评分、Quality Check 和常用操作；Pose Replay、Evidence、Diagnostics、Follow-up 已迁移到 `/report/:id/workspace?tab=pose|evidence|diagnostics|followup`。
- Debug 日志会修复已知 mojibake 文本，例如分析流程完成状态。

最新版本降低了复盘上传时对“精确动作名称”的要求：只知道动作大类也可以提交，技能分类可保持不确定，上传前填写的补充说明会进入最早的视频语义动作识别提示词。

- `v5.2.307`：对比生成持久化为 `analysis_comparisons` 后台任务；完整源视频只交给激活的 `vision` 模型，`report` provider 只基于结构化 JSON 文本生成总结；新增对比结果历史、重试、分享、同步播放修复，并加强训练计划兜底。
- `v5.2.306`：追问聊天能识别用户备注中的多个问题并逐一回答，区分能/不能从证据确认的内容；训练计划改用儿童安全低冲击提示词，强制 JSON schema 并记录 `generation_status`；报告自动解析上传备注中的问题并逐条 Q&A；KeyframeEvidencePanel 逻辑抽取到 `keyframeEvidence.ts` 工具模块，支持响应式布局；Archive 新增家长模式聚合 `fetchArchiveSummary` 接口、可点开的日历日详情弹窗和"回到最近记录月份"导航；新增帧回填测试。
- `v5.2.305`：追问可只跑“视频 AI 全量视频关键帧重识别”，生成待确认关键帧修正卡；不重置主人物锁定、不重跑 pose/生物力学/视觉报告、不自动应用数据，也不覆盖报告。
- `v5.2.304`：追问聊天可提交重置主人物锁定的完整视频重新分析；重试确认会说明是否重新建立 skater lock；报告/追问分享图可随长文本自适应高度并导出压缩 JPEG。
- `v5.2.303`：Review 上传不再要求精确动作子类或技能节点；支持“不确定 / 只知道大类”，并把用户补充说明传入 video-temporal 动作识别，再进入关键帧和报告生成。
- `v5.2.302`：手动目标锁定缺少 tracker 诊断时 fail closed，避免 pose 回填把错误滑行者的骨架画回报告。
- `v5.2.11`：默认使用全量视频上下文；Review 和 Debug 支持可选手动起止点；报告和 Debug 页面显示实际 AI 输入范围；Path A 使用生成的 AI clip；带多人/人工复核标记的目标锁定必须进入手动选人。
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

- 视频上传、异步分析与阶段感知重试；不知道精确动作名时可只提交动作大类，技能分类可选。
- 运动采样、视频预检、模糊过滤和更大的 nginx 上传限制。
- 目标预览、默认隐藏候选框、手动 bbox 框选、YOLO + ByteTrack 人体跟踪和逐帧 bbox 诊断。
- MediaPipe 姿态提取，支持平滑、多候选和 crop 回退逻辑。
- 生物力学指标，包括阶段时序、跳跃证据、旋转估算和姿态质量。
- Qwen 3.6 Plus 视频语义时间定位，用于动作大类识别与起跳/腾空/落冰区间解析，并会参考用户上传备注。
- 结合视频 AI、运动密度和骨架候选的语义关键帧时间戳仲裁。
- 双路径视觉分析，支持 video context、供应商回退、非标准 JSON 恢复、重试处理和成本限制。
- AI 辅助报告、训练计划、技能树、历史档案、进度追踪、儿童模式和家长模式；报告兜底会使用 Path B 证据和动作专项训练建议。
- 后台对比工作台支持持久化对比历史、通过 `vision` 槽进行完整源视频 AI 对比、通过 `report` 槽生成纯文本家长总结、同步播放、失败重试和分享图导出。
- 已完成视频的持久化 AI 追问，基于现有证据回答，支持 AI/手动修正卡、视频 AI 关键帧轻量重跑修正卡、应用/忽略确认，以及基于已应用修正重新生成报告。
- 独立 `/analysis-chat` 工作台，可选择任意已完成分析，查看有效识别、关键帧、partial semantic candidates、修正历史，并分享文字/图片复盘内容。
- 响应式 archive/report 工作台：archive 支持分页列表和日历 tab；report 保持主报告简洁，高级内容通过姿态、证据、诊断、追问 tab 展示。
- Pose Debug 与 Debug 页面，用于骨架回放、tracker 缩略图、候选数量、姿态诊断、AI 输入范围、耗时和日志检查。
- Docker Compose 与 all-in-one Docker 部署，适合 NAS 或本地单容器运行。

## 分析流程

1. 上传源视频并创建分析记录；不知道精确动作名称时，可以只填写动作大类。
2. 解析 AI 输入范围：填写手动起止点时使用手动片段，否则默认使用完整源视频时间轴；只有硬性兜底才允许系统截断并记录原因。
3. 执行视频预检、运动采样和关键帧/动作时序解析，时间戳保持源视频绝对时间。
4. 生成目标预览候选；置信度不足或存在多人/人工复核标记时等待手动选择。
5. 使用 YOLO/ByteTrack 跟踪目标滑行者，并执行逐帧 bbox 连续性检查。
6. 从 regular、tracker-guided 和 fallback crop 中提取姿态点。
7. 平滑姿态信号，计算生物力学、跳跃特征和关键帧候选。
8. 在已配置供应商时运行视频语义 AI，把上传备注作为上下文，识别实际动作大类并解析 T/A/L 时间戳。
9. 用 FFmpeg 抽取语义关键帧，并把 video context 或 AI clip 注入视觉模型。
10. 融合姿态、生物力学、视频 AI、Path A 纯视觉和 Path B 骨架量化证据，生成结构化报告。
11. 持久化帧、日志、耗时、调试摘要、AI 输入范围元数据和重试检查点。

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
- 仅提交动作大类的复盘上传，以及用户备注进入 AI 提示上下文。
- 阶段重试和管线版本行为。
- debug run 持久化和回放流程。
- 视频预检、精准抽帧和语义时间解析。
- bbox tracking、target lock、person tracking 和 pose smoothing。
- 关键帧候选、T/A/L 顺序和生物力学时序。
- 双路径视觉、Path A 非标准 JSON 恢复、供应商重试、报告融合和内容归一化。
- AI 追问持久化、包含 comments/action confirmation/partial semantic candidates 的 prompt 上下文、建议修正卡、有效修正层和分享 payload 生成。

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
- `/report/:id`：简洁版分析报告。
- `/report/:id/workspace?tab=pose|evidence|diagnostics|followup`：报告详情工作台，展示姿态回放、证据、诊断和 AI 追问。
- `/analysis-chat`：独立家长/教练追问工作台，可选择任意已完成分析。
- `/report/:id/pose-debug`：大屏骨架回放与 tracker 诊断。
- `/archive`：分页历史档案，支持列表和日历视图。
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
