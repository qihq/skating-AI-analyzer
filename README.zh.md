# Skating Analyzer

花样滑冰训练分析系统，基于 React、FastAPI 和 Docker 构建。

[English README](./README.md)

[贡献指南](./CONTRIBUTING.md) · [许可证](./LICENSE) · [截图说明](./SCREENSHOT_GUIDE.md)

## 项目简介

Skating Analyzer 是一个用于花样滑冰训练视频分析的全栈项目，支持上传视频、自动抽帧、姿态估计、生物力学指标分析、AI 诊断报告生成，以及通过技能树、训练计划和历史档案持续跟踪训练进展。

## 功能概览

- 视频上传与异步分析
- 关键帧抽取与 MediaPipe 姿态识别
- 生物力学指标计算与结构化评分
- AI 训练诊断报告
- 儿童模式 / 家长模式双视角
- 技能树、训练计划、历史档案、成长追踪
- Docker 一体化部署

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
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
SECRET_KEY=replace-with-a-random-32-char-secret
```

说明：

- `.env` 不会提交到 Git 仓库
- `.env.example` 只保留占位符
- 运行期数据库、上传视频和备份文件不会被提交

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
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
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

## Docker 部署

### docker-compose

```bash
docker compose up --build
```

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
  -v "$(pwd)/.env:/workspace/.env:ro" \
  skating-analyzer-allinone:latest
```

导出：

```bash
docker save -o skating-analyzer-allinone-latest.tar skating-analyzer-allinone:latest
```

## 主要页面

- `/path`：技能树与学习路径
- `/review`：上传视频并发起分析
- `/report/:id`：分析报告
- `/archive`：历史档案 / 训练进展
- `/plan/:plan_id`：训练计划
- `/snowball`：冰宝陪练与记忆建议
- `/settings`：系统设置、PIN、备份、供应商管理

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

## 开源补充材料

- 封面图文案：[REPO_COVER_COPY.md](./REPO_COVER_COPY.md)
- GitHub About / Topics 文案：[GITHUB_PROFILE_COPY.md](./GITHUB_PROFILE_COPY.md)
- 截图规划：[SCREENSHOT_GUIDE.md](./SCREENSHOT_GUIDE.md)
- Release 文案草稿：[RELEASE_BODY_v1.0.0.md](./RELEASE_BODY_v1.0.0.md)

## 许可证

MIT
