# Skating Analyzer | 花样滑冰训练分析系统

<p align="center">
  <b>AI-powered figure skating video analysis & biomechanics scoring</b><br>
  <b>基于 AI 视觉与生物力学的花样滑冰视频分析评分系统</b>
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> •
  <a href="#features">Features</a> •
  <a href="#tech-stack">Tech Stack</a> •
  <a href="#api">API</a> •
  <a href="README.zh.md">中文</a>
</p>

---

## Overview | 项目简介

**Skating Analyzer** is a full-stack application that analyzes figure skating training videos using computer vision and LLMs. It extracts motion frames, detects 33 skeletal keypoints via MediaPipe, calculates biomechanical metrics (air time, jump height, rotation speed), and fuses AI visual scoring with geometric pose scoring to generate structured training reports.

**花样滑冰训练分析系统**是一套全栈应用，利用计算机视觉与大模型分析花样滑冰训练视频。系统通过 FFmpeg + OpenCV 进行运动密度抽帧，使用 MediaPipe 提取 33 个骨骼关键点，计算生物力学指标（滞空时间、跳跃高度、转速），并将 AI 视觉评分与骨骼几何评分融合，生成结构化训练报告。

---

## Features | 核心功能

| Feature | Description |
|---------|-------------|
| 🎬 **Video Upload** | Upload `mp4 / mov / avi` and trigger async analysis. |
| 🧠 **Motion Frame Sampling** | FFmpeg + OpenCV motion-density sampling (default 20 frames). |
| 🦴 **Pose Detection** | MediaPipe 33-keypoint skeleton tracking with playback viewer. |
| 📐 **Biomechanics** | Takeoff / Apex / Landing keyframes; air time, jump height, velocity, rotation speed. |
| 🤖 **AI Scoring** | Structured itemized scoring via vision LLMs (Qwen / DeepSeek / etc.). |
| ⚖️ **Fused Score** | 40 % AI visual + 60 % skeletal geometry weighted fusion. |
| 📝 **Report Generation** | Structured Chinese training report JSON via text LLM. |
| 🔐 **Secure Key Storage** | AES-256 encryption for API keys using `SECRET_KEY`. |
| ⚙️ **Provider Management** | Built-in AI provider config & activation switching. |

---

## Tech Stack | 技术栈

- **Backend** — Python 3.11, FastAPI, SQLAlchemy (async), SQLite, FFmpeg, OpenAI SDK, MediaPipe, OpenCV
- **Frontend** — React 18, Vite, TypeScript, Tailwind CSS, React Router, Recharts, Axios
- **Deploy** — Docker Compose, nginx, volume mount `./data:/data`

---

## Quick Start | 快速开始

### Prerequisites | 前置要求

- Docker & Docker Compose **or** Python 3.11 + Node.js 18+
- API keys for at least one AI provider (Qwen / DeepSeek / etc.)

### 1. Clone & Configure | 克隆与配置

```bash
git clone https://github.com/<your-username>/skating-analyzer.git
cd skating-analyzer
cp .env.example .env
# Edit .env and fill in your API keys
```

### 2. Docker (Recommended) | Docker 启动（推荐）

```bash
docker compose up --build
```

- Frontend: http://localhost:8080
- Health check: http://localhost:8080/api/health

### 3. Local Development | 本地开发

**Backend | 后端**

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

**Frontend | 前端**

```bash
cd frontend
npm install
npm run dev
```

**Default Dev URLs | 默认开发地址**

- Frontend: `http://localhost:5173`
- Backend: `http://localhost:8000`

---

## Environment Variables | 环境变量

Copy `.env.example` to `.env` and configure at least these required fields:

```bash
# Required | 必填
QWEN_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
SECRET_KEY=replace-with-a-random-32-char-secret
```

`QWEN_API_KEY` also accepts `DASHSCOPE_API_KEY` as an alias.

Optional overrides | 可选覆盖：

```bash
FRAME_SAMPLE_COUNT=20
FRAME_THUMB_SIZE=160x90
FRAME_FULL_SIZE=854x480
MAX_UPLOAD_SIZE_MB=500
DATA_DIR=/data
DATABASE_URL=sqlite+aiosqlite:////data/skating-analyzer.db
```

---

## API Overview | 接口概览

### Analysis Flow | 分析流程

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/analysis/upload` | Upload video |
| GET | `/api/analysis/` | List analyses |
| GET | `/api/analysis/{id}` | Get analysis detail |
| GET | `/api/analysis/{id}/pose` | Get pose data |
| GET | `/api/frames/{analysis_id}/{filename}` | Get frame image |
| PATCH | `/api/analysis/{id}/note` | Update note |
| GET | `/api/health` | Health check |

### AI Provider Management | AI 供应商管理

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/providers` | List providers |
| POST | `/api/providers` | Add provider |
| PATCH | `/api/providers/{id}` | Update provider |
| PATCH | `/api/providers/{id}/activate` | Activate provider |
| DELETE | `/api/providers/{id}` | Delete provider |
| POST | `/api/providers/{id}/test` | Test connectivity |

---

## Project Structure | 项目结构

```
skating-analyzer/
├── backend/               # FastAPI backend
│   ├── app/
│   │   ├── main.py
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── routers/
│   │   └── services/      # analysis, vision, report, providers, pose, etc.
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/              # React + Vite frontend
│   ├── src/
│   ├── Dockerfile
│   └── nginx.conf
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Data & Privacy | 数据与隐私

- Runtime data is written to the `./data` directory:
  - SQLite database: `./data/skating-analyzer.db`
  - Uploaded videos & extracted frames: `./data/uploads/<analysis_id>/`
- The `./data` directory is **gitignored** to prevent accidental commits of user data.
- API keys are encrypted with AES-256-GCM before being stored in the database.

---

## License | 许可

MIT License

---

<p align="center">
  Built with ❤️ for figure skating coaches and athletes.<br>
  为花样滑冰教练与运动员精心打造。
</p>
