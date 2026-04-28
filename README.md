# Skating Analyzer

花样滑冰训练分析系统。  
一个基于 React + FastAPI + Docker 的全栈项目，用于上传训练视频、自动抽帧、姿态估计、生物力学分析、AI 诊断、训练计划生成与成长档案管理。

## 功能概览

- 视频上传与异步分析
- 关键帧抽取与 MediaPipe 姿态识别
- 生物力学指标计算
- AI 结构化诊断报告
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
│  │  ├─ services/           # 分析、报告、技能、供应商等服务
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
├─ backups/                  # 备份目录（已忽略数据库文件）
├─ .env.example
├─ docker-compose.yml
└─ README.md
```

## 环境变量

复制 `.env.example` 为 `.env`，再手动填写你的密钥：

```bash
cp .env.example .env
```

关键变量示例：

```bash
QWEN_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
SECRET_KEY=replace-with-a-random-32-char-secret
```

说明：

- `.env` 不会提交到 Git 仓库
- `.env.example` 只保留占位符
- 运行期数据库、上传视频、备份文件默认也不会提交

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

导出镜像：

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
- `/settings`：系统设置、PIN、备份、供应商配置

## 数据与隐私

- 运行数据默认写入 `./data`
- 上传视频与抽帧素材不会进入 Git
- API Key 使用应用内加密存储
- 公开仓库前请只提交 `.env.example`，不要提交 `.env`

## 当前仓库说明

这个仓库包含当前项目代码与文档，不包含：

- 实际 API Key
- 本地数据库
- 训练视频与抽帧素材
- 导出的镜像 tar 包

## License

MIT
