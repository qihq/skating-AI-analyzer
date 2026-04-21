# 花样滑冰训练分析系统 — 完整开发手册 v3
# 为坦坦（5岁，一级自由滑）及弟弟（3岁）量身定制
# 部署：群晖 Synology NAS · Docker Compose · 局域网家庭使用

> **v3 整合说明**：在 v2 基础上新增 Phase 6（冰宝（IceBuddy）与长期记忆系统），
> 并对 Phase 2/4/5 进行以下更新：
> - 全局：AI角色命名为「冰宝（IceBuddy）」，底部四标签导航重构
> - Phase 2：训练计划改为7天结构 + 练习档案时间轴
> - Phase 3：生物力学显示增加 T/A/L 关键帧面板
> - Phase 4：路径页增加学习阶段进度条 + 冰面路线图视图
> - Phase 5：API设置页重设计，新增冰宝（IceBuddy）记忆管理页

---

## 目录

| Phase | 内容 | 新增/变更功能 |
|---|---|---|
| **Phase 1** | 核心系统基础 | 视频上传→分析→报告，AI供应商管理，480p转码 |
| **Phase 2** | 历史与训练 | 练习档案时间轴、进步对比、趋势折线图、**7天训练计划** |
| **Phase 3** | 分析准确性增强 | 结构化Prompt、骨骼可视化、密度采样、**T/A/L关键帧面板** |
| **Phase 4** | 技能树与成就 | ISU FS1-FS10技能树、坦坦/弟弟双档案、家长PIN解锁、**学习路径阶段/冰面路线图** |
| **Phase 5** | 三端UI适配 | iPhone/iPad/Web响应式、DESIGN.md规范、动效、**四标签底部导航** |
| **Phase 6** | 冰宝（IceBuddy）系统 | **AI角色命名、长期记忆、Context注入、Memory管理页、API设置重设计** |

> **开发规则**：按 Phase 顺序发给 Codex，每个 Phase 通过验证后再开始下一个。

---

# 从零开始：环境准备与项目初始化

> **阅读对象**：第一次在群晖 NAS 上启动本项目的用户。
> 完成本节后，你的机器上会有一个空的项目骨架，可以开始向 Codex 发送 Phase 1。

---

## Step 0：前置条件检查

在 NAS 或本地开发机上确认以下工具已就绪：

| 工具 | 最低版本 | 检查命令 | 说明 |
|---|---|---|---|
| Docker Engine | 24+ | `docker --version` | 群晖 DSM 7.2 内置，或手动安装 Container Manager |
| Docker Compose | v2（内置于 Docker） | `docker compose version` | 注意是 `compose`（空格），不是旧版 `docker-compose` |
| Git | 任意 | `git --version` | 用于版本管理；NAS 可通过套件中心安装 |
| Node.js | 18+ | `node --version` | **仅本地开发调试用**；生产运行不需要，前端由 Docker 构建 |
| Python | 3.11+ | `python3 --version` | 同上，生产由 Docker 构建 |

**群晖 NAS 特别说明：**
- 在 DSM 中打开「套件中心」→ 搜索「Container Manager」→ 安装（已包含 Docker + Compose）
- SSH 进入 NAS：`ssh admin@<NAS_IP> -p 22`
- 推荐将项目放在 `/volume1/docker/skating-analyzer/`（根据你的实际共享文件夹调整）

---

## Step 1：创建项目目录骨架

在终端（或 NAS SSH）中执行：

```bash
# 选择你的工作目录（NAS 示例）
cd /volume1/docker

# 新建项目根目录
mkdir skating-analyzer && cd skating-analyzer

# 创建顶层目录结构（Codex 会自动填充文件，这里只建空目录）
mkdir -p backend/app/routers
mkdir -p backend/app/services
mkdir -p frontend/src/pages
mkdir -p frontend/src/components
mkdir -p frontend/src/api
mkdir -p data/uploads

# 初始化 Git 仓库（可选，但强烈推荐）
git init
echo "data/" >> .gitignore
echo ".env" >> .gitignore
echo "__pycache__/" >> .gitignore
echo "node_modules/" >> .gitignore
```

完成后目录看起来是这样：
```
skating-analyzer/
├── backend/
│   └── app/
│       ├── routers/
│       └── services/
├── frontend/
│   └── src/
│       ├── api/
│       ├── components/
│       └── pages/
├── data/
│   └── uploads/
└── .gitignore
```

---

## Step 2：准备 API Key

本项目需要两个大陆境内可用的 API Key（境内无需代理）：

| 用途 | 供应商 | 申请地址 | 环境变量名 |
|---|---|---|---|
| 视觉分析（默认）| 阿里云通义千问 | https://dashscope.console.aliyun.com/ | `QWEN_API_KEY` |
| 报告生成（默认）| DeepSeek | https://platform.deepseek.com/ | `DEEPSEEK_API_KEY` |

> **备注**：两个 Key 均有免费额度，开发阶段足够使用。
> Phase 1 验证完成后，可在系统后台切换为豆包、MiniMax 等其他供应商。

---

## Step 3：创建 `.env` 文件

在项目根目录创建 `.env`（**不要提交到 Git**）：

```bash
# 在 skating-analyzer/ 目录下
cat > .env << 'EOF'
# ── AI 供应商 Key（必填）──────────────────────────────────────
QWEN_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# ── 安全密钥（必填，用于加密存储 API Key）────────────────────
# 用任意32位随机字符串，例如：openssl rand -hex 16
SECRET_KEY=请替换为32位随机字符串

# ── 可选：覆盖默认值 ─────────────────────────────────────────
# FRAME_FULL_SIZE=854x480      # 抽帧分辨率（默认 480p）
# MAX_UPLOAD_SIZE_MB=500       # 最大上传文件大小
EOF
```

生成 `SECRET_KEY` 的方法（选一种）：
```bash
# 方法 A（推荐，需 openssl）
openssl rand -hex 16

# 方法 B（Python）
python3 -c "import secrets; print(secrets.token_hex(16))"
```

---

## Step 4：让 Codex 生成 Phase 1 代码

打开 Codex（https://chatgpt.com/codex 或 OpenAI API），**新建一个任务**，粘贴以下内容：

```
这是一个全新的花样滑冰训练分析系统项目。
请根据以下规格从头生成完整的 Phase 1 代码。
项目目录骨架已建好，请填充所有文件内容。

[在此粘贴本手册的"Phase 1：核心系统基础"完整章节内容]
```

**Codex 推理设置**：默认推理即可（Phase 1 不涉及复杂逻辑）。

Codex 完成后，将生成的所有文件按路径放到项目目录中。

---

## Step 5：首次构建与启动

```bash
# 确保在 skating-analyzer/ 根目录
cd /volume1/docker/skating-analyzer

# 首次构建（需要下载基础镜像，约 5-10 分钟，视网速）
docker compose up --build

# 或在后台运行
docker compose up --build -d
```

**构建过程说明：**
- `skating-backend`：下载 `python:3.11-slim` → 安装 FFmpeg → 安装 Python 依赖
- `skating-frontend`：下载 `node:18-alpine` 构建前端 → `nginx:alpine` 托管静态文件

**首次启动验证（对应 Phase 1 验证清单 1-A）：**
```bash
# 检查两个容器是否都在运行
docker compose ps

# 检查后端健康
curl http://localhost:8000/api/health
# 期望返回：{"status":"ok"}

# 浏览器访问前端
open http://localhost:8080
# 或在 NAS 上：http://<NAS_IP>:8080
```

---

## Step 6：常用运维命令

```bash
# 查看实时日志
docker logs -f skating-backend
docker logs -f skating-frontend

# 重新构建（修改了 Dockerfile 或 requirements.txt 后）
docker compose up --build -d

# 仅重启服务（修改了 .env 后）
docker compose restart

# 停止但保留数据
docker compose stop

# 完全停止并删除容器（数据在 ./data/ 目录，不会丢失）
docker compose down

# 查看数据目录（视频文件 + SQLite 数据库）
ls -la data/
ls -la data/uploads/
```

---

## Step 7：后续 Phase 的发送方式

每完成一个 Phase 的验证，进入下一个 Phase 时，在 Codex 开头加这段说明：

```
这是一个已有 Phase N 代码的项目，请在现有代码基础上继续开发
Phase N+1，不要重写已有文件，只新增或修改涉及的文件。
所有 API Key 由我手动填入 .env，Codex 使用占位符即可。

[在此粘贴对应 Phase 章节内容]
```

> **提示**：每次 Codex 输出完成后，用 `git add . && git commit -m "Phase N done"` 保存进度，
> 方便出问题时回滚。

---

## 环境准备检查清单

在开始 Phase 1 之前，确认以下都已就绪：

- [ ] Docker 和 Docker Compose 已安装（`docker compose version` 有输出）
- [ ] 项目骨架目录已创建（`ls skating-analyzer/` 可见 backend/frontend/data）
- [ ] `.env` 文件已创建，`QWEN_API_KEY` 和 `DEEPSEEK_API_KEY` 已填入真实 Key
- [ ] `SECRET_KEY` 已填入（32位随机字符串）
- [ ] Codex 已生成 Phase 1 所有文件并放置到正确路径
- [ ] `docker compose up --build` 无报错
- [ ] `curl http://localhost:8000/api/health` 返回 `{"status":"ok"}`
- [ ] 浏览器可访问 `http://<NAS_IP>:8080`

✅ 全部勾选后，进入 **Phase 1 验证清单（1-A ～ 1-G）**。

---

# Phase 1：核心系统基础（视频分析闭环）

> **目标**：跑通完整链路——上传视频 → 抽帧 → AI分析 → 生成报告 → 前端展示

---

## 技术栈

### 后端
- Python 3.11+，FastAPI（异步），FFmpeg（subprocess），OpenAI SDK
- SQLAlchemy async + aiosqlite（SQLite），python-multipart，aiofiles

### 前端
- React 18 + Vite + TypeScript，Tailwind CSS，React Router v6，axios

### 部署
- Docker Compose，backend + frontend 两个 service
- frontend：nginx 托管，反向代理 `/api` → backend
- volume mount：`./data:/data`（视频文件 + SQLite）
- 对外端口：**8080**

### 外部 API（大陆境内，OpenAI 兼容接口）
```
视觉分析：
  base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
  model:    qwen-vl-max-latest
  env:      QWEN_API_KEY

报告生成：
  base_url: https://api.deepseek.com/v1
  model:    deepseek-chat
  env:      DEEPSEEK_API_KEY
```

---

## 项目结构

```
skating-analyzer/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── database.py
│   │   ├── models.py
│   │   ├── schemas.py
│   │   └── routers/
│   │       └── analysis.py
│   │   └── services/
│   │       ├── video.py       # FFmpeg 抽帧
│   │       ├── vision.py      # Qwen-VL-Max
│   │       └── report.py      # DeepSeek 报告
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── main.tsx
│   │   ├── index.css
│   │   ├── api/client.ts
│   │   ├── pages/
│   │   │   ├── UploadPage.tsx
│   │   │   └── ReportPage.tsx
│   │   └── components/
│   │       └── ReportCard.tsx
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── tailwind.config.js
│   ├── postcss.config.js
│   ├── index.html
│   ├── nginx.conf
│   └── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## 数据模型

### AIProvider 表（AI 供应商配置）
```python
id:           str (UUID, PK)
slot:         str   # "vision"（视觉分析槽）| "report"（报告/计划生成槽）
name:         str   # 显示名，如 "Qwen-VL-Max"
provider:     str   # 供应商标识，如 "qwen" | "kimi" | "glm" | "deepseek" | "minimax" | "doubao"
base_url:     str   # API base_url
model_id:     str   # 模型 ID，如 "qwen-vl-max-latest"
api_key:      str   # 加密存储（AES-256，密钥来自 SECRET_KEY 环境变量）
is_active:    bool  # 当前激活的供应商（每个 slot 同时只有一个 active）
notes:        str | None  # 备注，如 "备用"
created_at:   datetime
updated_at:   datetime
```

**slot 说明：**
- `vision` 槽：必须支持图像输入。适合：Qwen-VL-Max、Kimi K2.5、Doubao-Seed-2.0
- `report` 槽：纯文本生成。适合：DeepSeek-V3、GLM-5、MiniMax M2.7、Qwen-Max

**预置供应商列表（系统初始化时写入，用户可在后台切换）：**
```python
PRESET_PROVIDERS = [
    # vision 槽
    {"slot":"vision", "name":"Qwen-VL-Max（推荐）",
     "provider":"qwen", "base_url":"https://dashscope.aliyuncs.com/compatible-mode/v1",
     "model_id":"qwen-vl-max-latest", "is_active":True},
    {"slot":"vision", "name":"Kimi K2.5",
     "provider":"kimi", "base_url":"https://api.moonshot.cn/v1",
     "model_id":"kimi-k2.5", "is_active":False},
    {"slot":"vision", "name":"Doubao Seed 2.0（豆包/火山方舟）",
     "provider":"doubao", "base_url":"https://ark.cn-beijing.volces.com/api/v3",
     "model_id":"doubao-seed-2-0-250615", "is_active":False},
    # report 槽
    {"slot":"report", "name":"DeepSeek-V3（推荐）",
     "provider":"deepseek", "base_url":"https://api.deepseek.com/v1",
     "model_id":"deepseek-chat", "is_active":True},
    {"slot":"report", "name":"MiniMax M2.7",
     "provider":"minimax", "base_url":"https://api.minimax.chat/v1",
     "model_id":"MiniMax-Text-01", "is_active":False},
    {"slot":"report", "name":"GLM-5",
     "provider":"glm", "base_url":"https://open.bigmodel.cn/api/paas/v4",
     "model_id":"glm-5", "is_active":False},
    {"slot":"report", "name":"Qwen-Max",
     "provider":"qwen", "base_url":"https://dashscope.aliyuncs.com/compatible-mode/v1",
     "model_id":"qwen-max-latest", "is_active":False},
]
```

**API 调用改造（vision.py / report.py / plan.py）：**
原来 hardcode `base_url` 和 `model` 的地方，改为启动时从 DB 读取当前 active 供应商：
```python
async def get_active_provider(slot: str) -> AIProvider:
    # 从 DB 查询 slot=slot AND is_active=True 的记录
    # 解密 api_key 后返回
```
所有三个 service 文件统一调用此函数，不再硬编码。

---

### Analysis 表
```python
id:             str (UUID, PK)
skater_id:      str | None (FK → Skater.id)  # Phase 4 关联
skill_category: str | None   # 复盘时选择的技能分类（对应 Phase 6 复盘流程）
action_type:    str           # 跳跃 / 旋转 / 步法 / 自由滑
video_path:     str
status:         str           # pending | processing | completed | failed
vision_raw:     str | None    # Qwen 原始返回文本
report:         JSON | None   # 结构化报告
force_score:    int | None    # 发力综合评分 0-100
error_message:  str | None
note:           str | None    # 用户训练备注
created_at:     datetime
updated_at:     datetime
```

---

## 后端接口

```
POST  /api/analysis/upload     上传视频，触发后台分析
GET   /api/analysis/           历史列表（支持 ?action_type= 过滤）
GET   /api/analysis/{id}       单条详情
PATCH /api/analysis/{id}/note  更新备注 body: { "note": "..." }
GET   /api/health              健康检查

# AI 供应商管理
GET    /api/providers                    获取所有供应商配置（api_key 脱敏返回 ***）
GET    /api/providers/{slot}/active      获取当前激活的供应商（slot=vision|report）
POST   /api/providers                    新增供应商
       body: {slot, name, provider, base_url, model_id, api_key, notes}
PATCH  /api/providers/{id}               更新供应商信息（可更新 api_key）
PATCH  /api/providers/{id}/activate      切换为激活（同 slot 其他自动停用）
DELETE /api/providers/{id}               删除供应商（不可删除唯一激活的）
POST   /api/providers/{id}/test          测试连通性（发送一条简单请求验证 Key 是否有效）
```

---

## 视频转码策略（节省 token）

**结论：抽帧分辨率从 720p 降为 480p，可节省约 55% 图像 token，分析质量无损。**

| 分辨率 | 单帧 tokens | 20帧总计 | 估算每次费用 | 月费用(8次) |
|---|---|---|---|---|
| 1080p | ~2025 | ~40,500 | ~0.85¥ | ~6.8¥ |
| 720p（原方案）| ~900 | ~18,000 | ~0.38¥ | ~3.0¥ |
| **480p（新方案）**| **~400** | **~8,000** | **~0.17¥** | **~1.3¥** |
| 360p | ~256 | ~5,120 | ~0.11¥ | ~0.9¥ |

**video.py 修改：抽帧尺寸改为 480p**
```python
FRAME_FULL_SIZE = os.getenv("FRAME_FULL_SIZE", "854x480")
```

---

## 后台处理流程（BackgroundTasks）

```
1. status → processing
2. FFmpeg 抽帧：5fps，480p，最多前 60 秒
   输出：/data/uploads/{uuid}/frames/frame_%04d.jpg
3. 均匀采样最多 20 帧，base64 编码
4. 调用 Qwen-VL-Max（System + User prompt，见下）
5. 将 Qwen 返回文本传给 DeepSeek 生成结构化报告 JSON
6. 从 report.issues 计算 force_score
   high=-15, medium=-8, low=-3，基准 100，最低 0
7. 写入 report、force_score，status → completed
8. 任意步骤失败：status → failed，写 error_message
```

### vision.py — Qwen-VL-Max Prompt

**System prompt：**
```
你是专业花样滑冰技术分析师，熟悉 ISU 评分体系和生物力学。
分析运动员的发力技术，输出清晰的中文技术分析。
```

**User prompt：**
```
这是一段花样滑冰【{action_type}】动作的训练视频帧序列，共 {frame_count} 帧，按时间顺序排列。

请分析以下维度：
1. 起跳/蹬冰发力时机与角度
2. 手臂收拢与展开的时序配合
3. 核心稳定性与重心控制
4. 冰刃使用（外刃/内刃）
5. 落冰缓冲与平衡

请引用帧编号支撑判断，给出具体的技术描述。
```

### report.py — DeepSeek 报告结构
```json
{
  "summary": "总体评价 2-3 句",
  "issues": [
    {
      "category": "问题类别",
      "description": "具体描述",
      "severity": "high | medium | low"
    }
  ],
  "improvements": [
    { "target": "针对的问题", "action": "具体改进动作" }
  ],
  "training_focus": "本阶段训练重点（1句）"
}
```
**要求**：DeepSeek System prompt 强制要求只输出 JSON，不含 markdown 包裹。
report.py 加 JSON 清洗逻辑（去除 ` ```json ` 等包裹后再解析）。

---

## 前端页面

### UploadPage（路由：/upload）
- 拖拽或点击上传（mp4/mov/avi，最大 500MB）
- 下拉选动作类型（跳跃/旋转/步法/自由滑）
- 可选填训练备注输入框
- 上传成功后跳转 `/report/:id`

### ReportPage（路由：/report/:id）
- 每 3 秒轮询状态，completed 前显示加载动画
- 加载时显示：⛸️ + 状态文字（「冰宝（IceBuddy）正在分析，通常需要 1-2 分钟…」）
- completed 后展示：
  - 顶部：发力评分圆环（`<60` 红，`60-80` 黄，`>80` 绿）+ 动作类型 + 日期
  - 总体评价卡片
  - 问题列表（high=红边，medium=黄边，low=蓝边）
  - 改进建议列表
  - 训练重点高亮蓝色卡片
- failed：红色错误卡片 + error_message
- 左上角返回按钮

---

## Docker 配置

### backend/Dockerfile
```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
RUN mkdir -p /data/uploads
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### frontend/nginx.conf
```nginx
server {
    listen 80;
    client_max_body_size 500m;
    location /api/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_read_timeout 300s;
    }
    location / {
        root /usr/share/nginx/html;
        index index.html;
        try_files $uri $uri/ /index.html;
    }
}
```

### docker-compose.yml
```yaml
version: "3.9"
services:
  backend:
    build: { context: ./backend, dockerfile: Dockerfile }
    container_name: skating-backend
    env_file: .env
    volumes: ["./data:/data"]
    ports: ["8000:8000"]
    restart: unless-stopped
  frontend:
    build: { context: ./frontend, dockerfile: Dockerfile }
    container_name: skating-frontend
    ports: ["8080:80"]
    depends_on: [backend]
    restart: unless-stopped
```

### requirements.txt
```
fastapi==0.115.5
uvicorn[standard]==0.32.1
python-multipart==0.0.12
sqlalchemy[asyncio]==2.0.36
aiosqlite==0.20.0
httpx==0.28.0
openai==1.57.0
pydantic==2.10.3
python-dotenv==1.0.1
aiofiles==24.1.0
```

---

## ✅ Phase 1 验证清单

### 1-A 基础启动
```bash
cp .env.example .env
# 填入 QWEN_API_KEY 和 DEEPSEEK_API_KEY
docker compose up --build
```
- [ ] build 无报错，两个容器均启动
- [ ] `curl http://localhost:8000/api/health` 返回 `{"status":"ok"}`
- [ ] 浏览器打开 `http://localhost:8080` 显示上传页面

### 1-B 文件上传
- [ ] 拖拽一个 mp4 文件到上传区，文件名正确显示
- [ ] 点击上传区也能弹出文件选择器
- [ ] 上传 600MB 文件，显示「文件超过 500MB 限制」错误
- [ ] 上传 .txt 文件，显示格式错误提示
- [ ] 上传合法视频后，页面跳转到 `/report/:id`

### 1-C 分析流程
- [ ] ReportPage 显示加载动画（⛸️ + 状态文字，提及「冰宝（IceBuddy）」）
- [ ] 后端日志可见抽帧过程（`docker logs skating-backend`）
- [ ] `/data/uploads/{uuid}/frames/` 目录下有 jpg 文件
- [ ] 状态轮询正常，processing → completed 自动刷新
- [ ] 报告页显示：评分圆环 + 总评 + 问题列表 + 改进建议 + 训练重点

### 1-D 报告内容
- [ ] `force_score` 数值在 0-100 之间
- [ ] 评分圆环颜色正确（测试：人为改 DB force_score 为 55/72/85 验证三种颜色）
- [ ] issues 列表颜色区分正确（高=红边，中=黄边，低=蓝边）
- [ ] 训练备注可以填写并在报告页显示

### 1-E 异常处理
- [ ] 断开网络后上传视频，status 变为 failed，页面显示错误信息
- [ ] `docker compose down` 再 `up`，历史数据仍存在（SQLite volume 持久化）

### 1-F AI 供应商管理
- [ ] `GET /api/providers` 返回所有预置供应商，api_key 显示为 `***`
- [ ] 切换 vision 槽到 Doubao，上传视频后分析正常运行
- [ ] 新增自定义供应商：手填 base_url + model_id + api_key，保存后可激活
- [ ] `POST /api/providers/{id}/test` 返回连通性结果（成功/失败+错误信息）
- [ ] 删除非激活供应商成功，删除唯一激活的供应商返回报错

### 1-G 视频转码分辨率
- [ ] 抽帧输出分辨率为 480p（854×480），检查 frames/ 目录下 jpg 文件尺寸
  ```bash
  identify /data/uploads/{uuid}/frames/frame_0001.jpg
  # 应显示 854x480 或接近值
  ```

---

# Phase 2：历史记录 + 进步对比 + 训练计划 + 练习档案

> **目标**：在 Phase 1 基础上增加历史管理、对比分析、7天训练计划、练习档案时间轴

---

## 新增数据模型

### TrainingPlan 表（**7天结构**）
```python
id:          str (UUID, PK)
analysis_id: str (FK → Analysis.id)
skater_id:   str (FK → Skater.id)
plan_json:   JSON   # 见下方结构
created_at:  datetime
```

**plan_json 结构（7天，每天一个主题）：**
```json
{
  "title": "7天个性化训练计划",
  "focus_skill": "华尔兹跳",
  "days": [
    {
      "day": 1,
      "theme": "核心稳定 + 轴心",
      "sessions": [
        {
          "id": "d1s1",
          "title": "训练项目名",
          "duration": "15分钟",
          "description": "具体动作说明",
          "is_office_trainable": true,
          "completed": false
        }
      ]
    },
    { "day": 2, "theme": "起跳发力",    "sessions": [] },
    { "day": 3, "theme": "落冰平衡",    "sessions": [] },
    { "day": 4, "theme": "柔韧恢复",    "sessions": [] },
    { "day": 5, "theme": "旋转速度",    "sessions": [] },
    { "day": 6, "theme": "综合模拟",    "sessions": [] },
    { "day": 7, "theme": "冰面验证",    "sessions": [] }
  ]
}
```

**7天主题约定（每次生成计划时固定此顺序，DeepSeek 根据当前问题填充具体训练内容）：**
| 天 | 主题 | 说明 |
|---|---|---|
| Day 1 | 核心稳定 + 轴心 | 平衡与核心肌群激活 |
| Day 2 | 起跳发力 | 蹬冰、膝盖折叠、爆发力 |
| Day 3 | 落冰平衡 | 缓冲吸收、单腿稳定 |
| Day 4 | 柔韧恢复 | 拉伸、放松、柔韧性训练 |
| Day 5 | 旋转速度 | 手臂收拢、轴心保持 |
| Day 6 | 综合模拟 | 完整动作串联演练 |
| Day 7 | 冰面验证 | 在冰上完整验收本周训练成果 |

---

## 新增后端接口

```
# 历史与对比
GET   /api/analysis/               历史列表（?action_type= 可选过滤）
GET   /api/analysis/compare        ?id_a=uuid&id_b=uuid，两条均需 completed
GET   /api/analysis/progress       进步趋势数据点列表

# 训练计划
POST  /api/analysis/{id}/plan      生成7天训练计划（已存在则直接返回）
GET   /api/analysis/{id}/plan      获取训练计划
GET   /api/plan/{plan_id}          通过 plan_id 获取
PATCH /api/plan/{plan_id}/session/{session_id}   更新完成状态 body: {"completed": true}

# 练习档案
GET   /api/skaters/{id}/archive    练习档案时间轴（按时间倒序）
      返回格式见下
```

### GET /api/skaters/{id}/archive 返回格式
```json
{
  "stats": {
    "total_records": 12,
    "recent_7days": 3,
    "current_streak": 5
  },
  "timeline": [
    {
      "id": "uuid",
      "created_at": "2026-03-28T23:55:00",
      "entry_type": "video_review",
      "skill_category": "安全摔倒与起立",
      "action_type": "跳跃",
      "force_score": 72,
      "report_snippet": "起势与准备：一般 → 进入动作前预留半拍...",
      "analysis_id": "uuid"
    }
  ]
}
```

### plan.py — DeepSeek 7天训练计划 Prompt

System prompt（强制 JSON 输出）：
```
你是专业花样滑冰教练，请根据分析报告生成7天个性化训练计划。
只输出 JSON，不含任何 markdown 包裹或额外说明。
```

User prompt：
```
动作类型：{action_type}
总体评价：{report.summary}
主要问题：{issues 列表，格式化为文字}
训练重点：{report.training_focus}

请生成7天训练计划，严格按以下主题顺序安排：
Day 1: 核心稳定 + 轴心
Day 2: 起跳发力
Day 3: 落冰平衡
Day 4: 柔韧恢复
Day 5: 旋转速度
Day 6: 综合模拟
Day 7: 冰面验证

每天安排 2-3 个训练项目，每项 10-20 分钟。
is_office_trainable=true 表示可在家/办公室练习（无需冰场）。
Day 7 的所有项目 is_office_trainable=false（需上冰）。
```

---

## 新增前端页面

### HistoryPage（路由：/history）
- 顶部动作类型筛选 Tab（全部/跳跃/旋转/步法/自由滑）
- 每条记录显示：动作类型标签、评分徽章、状态徽章、日期时间、备注预览
- 对比选择逻辑（同 v2，只能选同 action_type）
- 底部「查看进步趋势」→ `/progress`

### ArchivePage（路由：/archive，对应「进展」标签）
统计卡片行（三格）：
```
累计档案 N 条    近 7 天 N 次    连续记录 N 天
```
时间轴（按时间倒序）：每条包含时间戳、entry_type 图标、技能分类标签、报告摘要片段、「查看诊断详情」按钮。

### ComparePage（路由：/compare/:id_a/:id_b）
- 左右两栏，复用 ReportCard
- 底部总结：改善/新增/未变化分类
- 窄屏（< 768px）切换为上下布局

### PlanPage（路由：/plan/:plan_id）
- 顶部：计划标题 + 7天主题总览横条
- 每天一个折叠卡片，显示主题标签 + session 列表
  - Day 1 默认展开
  - 居家可练的 session 显示 🏠 徽章
- session 可勾选，乐观更新进度
- 整体进度条（已完成 session / 总数）

### ProgressPage（路由：/progress）
- recharts 折线图：X轴日期，Y轴评分 0-100
- 数据点可点击弹出摘要卡片
- 底部统计：总次数、最近评分、历史最高、近5次均值

---

## ✅ Phase 2 验证清单

### 2-A 历史记录
- [ ] `/history` 正常显示所有历史分析记录
- [ ] 动作类型 Tab 筛选有效
- [ ] 点击「查看报告」跳转对应 ReportPage

### 2-B 进步对比
- [ ] 选择同类型两条，底部出现「开始对比」按钮
- [ ] 选择不同类型两条，出现错误提示
- [ ] ComparePage 总结卡片改善/新增/未变化分类正确

### 2-C 进步趋势
- [ ] ProgressPage 折线图正常渲染（至少2条 completed 记录）
- [ ] 数据点点击弹出摘要卡片，统计卡片数值正确

### 2-D 7天训练计划
- [ ] ReportPage 底部「生成训练计划」点击后触发 POST
- [ ] PlanPage 显示7天，每天有对应主题标签
- [ ] Day 7 所有项目无 🏠 标记（需上冰）
- [ ] 勾选 session 后整体进度条更新
- [ ] `docker compose down` 再 `up`，勾选状态保留

### 2-E 练习档案
- [ ] `/archive` 页面三格统计数据正确
- [ ] 时间轴条目按时间倒序，摘要文字显示正常
- [ ] 「查看诊断详情」跳转对应 ReportPage

---

# Phase 3：视频分析准确性增强

> **目标**：将分析从「纯 AI 主观判断」升级为「结构化 AI(40%) + 客观骨骼几何计算(60%)」
> **注意**：本 Phase 包含 4 项独立改造 + 1 项 T/A/L 关键帧面板，建议按顺序逐一实现和验证

---

## 改造一：Prompt 结构化约束

### 改动文件：`backend/app/services/vision.py`

**新 System prompt：**
```
你是专业花样滑冰技术分析师，熟悉 ISU 评分体系和生物力学。
你的输出必须严格遵循指定 JSON 格式，不得输出任何格式之外的文字。
```

**新 User prompt（结构化帧分析）：**
```
分析以下【{action_type}】动作帧序列（共 {frame_count} 帧，按时间顺序排列）。

对每一帧，输出以下结构化数据：

{
  "frame_analysis": [
    {
      "frame_id": "frame_0001",
      "phase": "准备|起跳|腾空|落冰|滑出|旋转入|旋转中|旋转出|步法|不可分析",
      "observations": {
        "knee_bend":          "充分|不足|过度|不适用",
        "arm_position":       "正确|偏高|偏低|不对称|不适用",
        "axis_alignment":     "垂直|前倾|后仰|侧倾|不适用",
        "blade_edge":         "外刃|内刃|平刃|不适用",
        "core_stability":     "稳定|轻微晃动|明显晃动|不适用",
        "landing_absorption": "良好|不足|过度|不适用"
      },
      "issues":    ["问题描述1"],
      "positives": ["优点描述1"],
      "confidence": 0.0
    }
  ],
  "action_phase_summary": {
    "detected_phases": ["起跳", "腾空", "落冰"],
    "weakest_phase":   "最需改进的阶段",
    "strongest_phase": "表现最好的阶段"
  },
  "overall_raw_text": "综合文字描述 2-3 句"
}
```

### Analysis 模型新增字段
```python
vision_structured: Mapped[dict | None] = mapped_column(JSON, nullable=True)
```

### 报告结构扩展
```json
{
  "summary": "...",
  "issues": [{
    "category": "...",
    "description": "...",
    "severity": "high|medium|low",
    "phase": "落冰",
    "frames": ["frame_0012", "frame_0015"]
  }],
  "improvements": [{"target": "...", "action": "..."}],
  "training_focus": "...",
  "subscores": {
    "takeoff_power":      0,
    "rotation_axis":      0,
    "arm_coordination":   0,
    "landing_absorption": 0,
    "core_stability":     0
  },
  "data_quality": "good | partial | poor"
}
```

**force_score 计算改为 subscores 加权均值：**
```
force_score =
  takeoff_power      × 0.25
  + rotation_axis    × 0.25
  + arm_coordination × 0.15
  + landing_absorption × 0.25
  + core_stability   × 0.10
```

---

## 改造二：骨骼姿态可视化（PoseViewer）

### 新增依赖
```
mediapipe==0.10.14
opencv-python-headless==4.10.0.84
```

### 新增文件：`backend/app/services/pose.py`
```python
def extract_pose(frames_dir: str) -> dict:
    """
    对 frames_dir 下所有 frame_*.jpg 提取 MediaPipe 33 关键点
    返回：
    {
      "connections": [[0,1], [1,2], ...],
      "frames": [
        {
          "frame": "frame_0001.jpg",
          "keypoints": [
            {"id": 0, "name": "nose", "x": 0.52, "y": 0.31,
             "z": -0.08, "visibility": 0.99}
          ]
        }
      ]
    }
    坐标归一化 0~1，visibility < 0.5 标为不可信
    """
```

### Analysis 模型新增字段
```python
pose_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
```

### 新增接口
```
GET /api/analysis/{id}/pose
  返回：{ connections, frames, frame_urls }

GET /api/frames/{analysis_id}/{filename}
  FileResponse 返回 /data/uploads/{id}/frames/{filename}
```

### 前端新增组件：PoseViewer.tsx
- Canvas 渲染骨骼，关键点彩色（上半身绿、下半身橙、中轴白）
- 控制栏：⏮ ⏪ ▶/⏸ ⏩ ⏭ + 进度条 + 帧号
- 5fps 播放，requestAnimationFrame 驱动

---

## 改造三：运动密度采样抽帧

### 新抽帧流程：
```
Step 1：FFmpeg 抽全部缩略图（160×90，全程）
Step 2：OpenCV 逐帧计算相邻帧像素差均值 → 运动分数 0-1
Step 3：将视频分 10 个区段，按运动强度分配采样配额
Step 4：对选中帧单独提取 480p 高清版
Step 5：base64 → 返回
```

### Analysis 模型新增字段
```python
frame_motion_scores: Mapped[dict | None] = mapped_column(JSON, nullable=True)
```

### 新增环境变量
```
FRAME_SAMPLE_COUNT=20
FRAME_THUMB_SIZE=160x90
FRAME_FULL_SIZE=854x480
```

---

## 改造四：骨骼几何计算（生物力学融合评分）

### 新增文件：`backend/app/services/biomechanics.py`

```python
def calc_knee_angle(keypoints, frame_idx) -> dict: ...
def calc_trunk_tilt(keypoints, frame_idx) -> dict: ...
def calc_arm_symmetry(keypoints, frame_idx) -> dict: ...
def calc_center_of_mass_trajectory(pose_data) -> dict: ...
def calc_rotation_axis_stability(pose_data, start_frame, end_frame) -> dict: ...

def analyze_biomechanics(pose_data: dict, action_type: str) -> dict:
    """
    综合调用以上函数，返回：
    {
      "knee_angles": [...],
      "trunk_tilts": [...],
      "arm_symmetry": [...],
      "com_trajectory": {...},
      "rotation_stability": {...},
      "bio_subscores": {
        "takeoff_power": int,
        "rotation_axis": int,
        "arm_coordination": int,
        "landing_absorption": int,
        "core_stability": int
      },
      "key_frames": {
        "T": "frame_0005",   # 起跳帧 Takeoff
        "A": "frame_0009",   # 顶点帧 Apex
        "L": "frame_0013"    # 落冰帧 Landing
      },
      "jump_metrics": {
        "air_time_seconds": 0.4,
        "estimated_height_cm": 28.4,
        "takeoff_speed_mps": 2.1,
        "rotation_rps": 4.2
      }
    }
    """
```

**T/A/L 关键帧检测逻辑：**
- **T（起跳）**：重心 Y 坐标开始上升的帧（com_trajectory 中 Y 由大变小的转折点）
- **A（顶点 Apex）**：重心 Y 坐标最小值的帧（最高点）
- **L（落冰）**：重心 Y 坐标迅速下降后的稳定帧

**jump_metrics 估算公式：**
```python
# 滞空时间（秒）= 腾空帧数 / 视频帧率
air_time_seconds = air_time_frames / fps

# 跳跃高度估算（cm）= 0.5 × g × (air_time/2)²
estimated_height_cm = 0.5 * 9.8 * (air_time_seconds / 2) ** 2 * 100

# 起跳速度估算（m/s）= √(2 × g × h)
takeoff_speed_mps = (2 * 9.8 * estimated_height_cm / 100) ** 0.5

# 转速（圈/秒）= rotation_axis_stability 计算段内的旋转角速度
rotation_rps = calc_rotation_rps(pose_data, T_frame, L_frame)
```

### Analysis 模型新增字段
```python
bio_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
```

### AI + 骨骼融合评分
```python
final_subscore = round(ai_subscore * 0.4 + bio_subscore * 0.6)  # pose_data 存在
final_subscore = ai_subscore                                      # pose_data 为 None
```

---

## 改造五：T/A/L 关键帧面板（**新增**）

### 前端新增组件：BiomechanicsPanel.tsx

**展示内容（仅当 `bio_data.key_frames` 存在时渲染）：**

顶部关键帧标签行：
```
[ T 起跳 ]  [ A 顶点 ]  [ L 落冰 ]
（点击可在 PoseViewer 中跳转到该帧）
```

指标数据卡片（2×2 网格）：
```
┌──────────────────┬──────────────────┐
│  滞空时间         │  跳跃高度         │
│  0.4 s           │  28.4 cm         │
├──────────────────┼──────────────────┤
│  起跳速度         │  转速             │
│  2.1 m/s         │  4.2 rev/s       │
└──────────────────┴──────────────────┘
```

**颜色规则：**
- T 标签：橙色 `#F59E0B`
- A 标签：蓝色 `#3B82F6`
- L 标签：红色 `#EF4444`
- 指标卡片背景：深色（`#1A1A2E`），数值白色大字，单位灰色小字

**显示位置：**
- 家长模式 ReportPage：「骨骼姿态回放」区块内，PoseViewer 下方
- 坦坦模式：仅显示 跳跃高度 和 滞空时间（两个卡片），无技术指标

---

## 数据库迁移

Phase 3 共新增 5 个 Analysis 字段：
```python
NEW_COLUMNS = [
    ("vision_structured",   "JSON"),
    ("pose_data",           "JSON"),
    ("bio_data",            "JSON"),
    ("frame_motion_scores", "JSON"),
    ("skill_category",      "TEXT"),
]
```

---

## ✅ Phase 3 验证清单

### 3-A 改造一：结构化 Prompt
- [ ] `vision_structured` 字段非空，有逐帧 phase/observations/confidence
- [ ] 报告页显示五维雷达图
- [ ] 低质量视频时 data_quality=poor 顶部橙色提示条

### 3-B 改造二：骨骼可视化
- [ ] `pose_data` 非空，PoseViewer 正常播放
- [ ] 骨骼颜色区分：上半身绿、下半身橙、中轴白
- [ ] 高分屏下画面不模糊

### 3-C 改造三：运动密度采样
- [ ] `frame_motion_scores` 非空
- [ ] 高动作段抽帧比例明显高于静止段

### 3-D 改造四：生物力学融合
- [ ] `bio_data.bio_subscores` 5个维度均有数值
- [ ] `bio_data.key_frames` 包含 T/A/L 三个帧 ID
- [ ] `bio_data.jump_metrics` 包含 4 个指标值
- [ ] force_score = AI × 0.4 + 骨骼 × 0.6（手算验证）
- [ ] 家长模式显示「生物力学数据」折叠区块

### 3-E T/A/L 关键帧面板
- [ ] BiomechanicsPanel 显示 T/A/L 三个标签（橙/蓝/红）
- [ ] 点击标签，PoseViewer 跳转到对应帧
- [ ] 四个指标卡片数据与 bio_data.jump_metrics 一致
- [ ] 坦坦模式只显示跳跃高度和滞空时间两个卡片

---

# Phase 4：技能树 + 家长解锁 + 双模式账号

> **目标**：为坦坦和弟弟建立基于 ISU 标准的完整技能成长系统，
> 家长可手动解锁技能，支持家长模式 ↔ 坦坦模式切换
> **v3 新增**：路径页新增「学习阶段进度」和「冰面路线图」两种视图

---

## 用户设定

- **坦坦**：5周岁，2021年生，当前进度一级自由滑（Free Skate 1）
  - 系统初始化时自动将 snowplow + basic 章节标记为完成
  - FS1 章节节点全部 locked，等待 AI 或家长解锁
- **弟弟**：3周岁，2023年生，暂未开始
  - 所有节点初始 locked

---

## 双模式账号系统

| 功能 | 坦坦模式 | 家长模式 |
|---|---|---|
| 上传视频 | ✗ | ✅ |
| 查看报告 | ✅（简化版） | ✅（完整版+生物力学） |
| 技能树 | ✅（只看） | ✅（可解锁） |
| 手动解锁技能 | ✗ | ✅ |
| 生物力学详情 + T/A/L面板 | 部分 | ✅ 完整 |
| 历史/对比/趋势 | ✅ | ✅ |
| 冰宝（IceBuddy）长期记忆管理 | ✗ | ✅ |
| AI供应商设置 | ✗ | ✅ |

### ParentAuth 表
```python
id:         str (UUID, PK)
pin_hash:   str   # bcrypt 哈希
created_at: datetime
```

### 认证接口
```
GET  /api/auth/has-pin       → {"has_pin": bool}
POST /api/auth/setup-pin     body: {"pin": "1234"}
POST /api/auth/verify-pin    body: {"pin": "1234"} → {"valid": bool}
```

---

## 多选手系统

### Skater 表
```python
id:               str (UUID, PK)
name:             str           # 内部名
display_name:     str           # 前台显示名
avatar_emoji:     str           # 🦁 / 🐨
birth_year:       int
current_level:    str           # "fs1" / "snowplow"
avatar_level:     int           # 1-10
total_xp:         int
current_streak:   int
longest_streak:   int
last_active_date: str
is_default:       bool
```

系统初始化自动创建：
```python
skaters = [
    {"name": "tantan", "display_name": "坦坦",
     "avatar_emoji": "🦁", "birth_year": 2021,
     "current_level": "fs1", "is_default": True},
    {"name": "didi", "display_name": "弟弟",
     "avatar_emoji": "🐨", "birth_year": 2023,
     "current_level": "snowplow", "is_default": False},
]
```

---

## 技能树数据模型（与 v2 相同，补充路径阶段映射）

### SkillNode 表（同 v2）

### 学习路径阶段映射（**v3 新增**）

将技能章节映射到4个大阶段，供「学习路径」标签页展示：

| 阶段 | 名称 | 包含章节 | 阶段说明 |
|---|---|---|---|
| 阶段 1 | 冰场启蒙 | snowplow, basic | 学会站稳、犁式刹车、基础前滑 |
| 阶段 2 | 基础转体、步法和停止 | fs1, fs2 | 前后方向转换、刃感、肩髋协调 |
| 阶段 3 | 单跳 + 联合旋转 | fs3, fs4, fs5 | 单周跳跃系列、蹲燕旋转组合 |
| 阶段 4 | 双跳 + 竞技 | fs6, fs7, fs8, fs9, fs10 | Axel、双周跳、竞技节目 |

### 路径阶段内技能群组（**v3 新增**）

每个阶段内的技能节点按「技能群」分组，用于冰面路线图显示。
以阶段 2 为例（参考截图布局）：

**群组 1：后滑安全感**（对应 fs1 基础移动类）
- 扶墙后滑起步
- 短距离后滑

**群组 2：弧线与刃感**（对应 fs1 刃感类）
- 前外刃圆

**群组 3：肩髋同步转体**（对应 fs1 转体类）
- 小弧转体
- 低速肩髋同步
- 前内刃圆

---

## 技能树后端接口（补充路径接口）

```
# 原有接口（同 v2）
GET  /api/skaters/{id}/skills
GET  /api/skaters/{id}/skills/recent
POST /api/skaters/{id}/skills/{skill_id}/unlock
POST /api/skaters/{id}/skills/{skill_id}/lock

# v3 新增：路径阶段数据
GET  /api/skaters/{id}/learning-path
  返回：{
    "stages": [
      {
        "stage": 1,
        "name": "冰场启蒙",
        "description": "...",
        "progress_pct": 100,
        "groups": [
          {
            "group_name": "后滑安全感",
            "nodes_total": 2,
            "nodes_unlocked": 2,
            "nodes": [...]
          }
        ]
      },
      ...
    ],
    "current_stage": 2
  }
```

---

## SkillTreePage 前端更新（**v3 重要修改**）

路径页（原 SkillTreePage）现分为两个子视图，通过顶部 Tab 切换：

### 子视图 A：学习路径（默认视图）

**阶段进度卡片组**（横向4格，可左右滑动）：
```
阶段 1    阶段 2（当前）    阶段 3    阶段 4
100%      100%              0%        0%
```
- 当前阶段高亮（蓝色进度条 + 白色背景卡片）
- 已完成阶段灰色实心，未开始灰色空心

**当前阶段详情卡片**：
- 阶段名称 + 进度百分比
- 阶段说明文字
- 状态统计行：未点亮 N / 推进中 N / 已点亮 N
- 「看已点亮图谱」按钮（切换到冰面路线图视图）+ 「阶段说明」按钮

### 子视图 B：冰面路线图

**页面标题**：整张冰面路线图（N 个节点）
**描述**：所有节点汇总在一张图里，直接看整体推进。

**技能群组卡片**（横向标题行 + 下方网格）：
```
后滑安全感 2/2     弧线与刃感 2/2     肩髋同步转体 2/2
```

**节点网格**（3列，虚线连接相关节点）：
每个节点卡片显示：
- 节点名称
- 已点亮 / 推进中 / 未点亮 状态标签
- 中央绿点（已点亮）/ 橙点（推进中）/ 空点（未点亮）

**状态颜色**：
- 已点亮：浅青绿卡片 + 绿点 `#4CAF50`
- 推进中：浅橙卡片 + 橙点 `#F59E0B`
- 未点亮：浅灰卡片 + 灰点 `#9CA3AF`

---

## 完整技能节点（FS1–FS10）

### 第零章 snowplow + 第一章 basic
坦坦初始化时自动 unlocked_parent，弟弟 locked：
- `ss_all`：犁式刹车全套 🐧
- `basic_all`：基础滑冰技能全套 ⛸️

### 第二章：一级自由滑 fs1

| id | name | emoji | unlock_config | xp | requires |
|---|---|---|---|---|---|
| fs1_stroking | 前向有力蹬冰 | ⛸️ | score:{threshold:60,consecutive:2,action_type:"步法"} | 60 | [basic_all] |
| fs1_fwd_edges | 前外/前内连续刃 | 🛤️ | score:{threshold:60,consecutive:2,action_type:"步法"} | 60 | [basic_all] |
| fs1_bk_three_turn | 后外三转弯 | 🔄 | score:{threshold:60,consecutive:2,action_type:"步法"} | 80 | [basic_all] |
| fs1_spin_scratch | 直立旋转3圈 | 💃 | score:{threshold:65,consecutive:3,action_type:"旋转"} | 100 | [basic_all] |
| fs1_step_intro | 步伐入门 | 🎵 | score:{threshold:60,consecutive:2,action_type:"步法"} | 60 | [basic_all] |
| fs1_waltz | 华尔兹跳 | 🌸 | score:{threshold:65,consecutive:3,action_type:"跳跃"} | 100 | [basic_all] |
| fs1_half_flip | 半翻转跳 | 🃏 | score:{threshold:65,consecutive:2,action_type:"跳跃"} | 80 | [basic_all] |

### 第三章：二级自由滑 fs2

| id | name | emoji | unlock_config | xp | requires |
|---|---|---|---|---|---|
| fs2_bk_edges | 后外/后内连续刃 | 🛤️ | score:{threshold:62,consecutive:2,action_type:"步法"} | 80 | [fs1_fwd_edges] |
| fs2_spirals | 前外/前内螺旋线 | 🦢 | score:{threshold:62,consecutive:2,action_type:"步法"} | 80 | [fs1_stroking] |
| fs2_waltz_three | 华尔兹三转弯 | 🔄 | score:{threshold:62,consecutive:2,action_type:"步法"} | 80 | [fs1_bk_three_turn] |
| fs2_backspin | 后旋入门2圈 | 🌀 | score:{threshold:65,consecutive:2,action_type:"旋转"} | 120 | [fs1_spin_scratch] |
| fs2_step_chasse | 沙塞步伐序列 | 🎵 | score:{threshold:62,consecutive:2,action_type:"步法"} | 80 | [fs1_step_intro] |
| fs2_toe | 点冰跳 | 🐾 | score:{threshold:65,consecutive:3,action_type:"跳跃"} | 100 | [fs1_waltz] |
| fs2_sal | 萨霍夫跳 | 🌙 | score:{threshold:65,consecutive:3,action_type:"跳跃"} | 100 | [fs1_waltz] |
| fs2_half_lutz | 半勾手跳 | ⚔️ | score:{threshold:65,consecutive:2,action_type:"跳跃"} | 80 | [fs2_toe] |
| fs2_combo_waltz_toe | 华尔兹+点冰连跳 | ⚡ | score:{threshold:65,consecutive:2,action_type:"跳跃"} | 150 | [fs1_waltz,fs2_toe] |

### 第四章：三级 fs3
| id | name | emoji | unlock_config | xp | requires |
|---|---|---|---|---|---|
| fs3_crossover_fig8 | 前后交叉步8字 | 8️⃣ | score:{threshold:65,consecutive:2,action_type:"步法"} | 100 | [fs2_bk_edges] |
| fs3_waltz_eight | 华尔兹8字 | 🎭 | score:{threshold:65,consecutive:2,action_type:"步法"} | 100 | [fs2_waltz_three] |
| fs3_backspin_cross | 后旋交叉腿3圈 | 🌀 | score:{threshold:68,consecutive:3,action_type:"旋转"} | 150 | [fs2_backspin] |
| fs3_step_circle | 圆圈步伐序列 | 🎵 | score:{threshold:65,consecutive:2,action_type:"步法"} | 120 | [fs2_step_chasse] |
| fs3_combo_waltz_toe | 华尔兹+点冰序列 | ⚡ | score:{threshold:68,consecutive:3,action_type:"跳跃"} | 200 | [fs2_sal,fs2_toe] |

### 第五章：四级 fs4
| id | name | emoji | unlock_config | xp | requires |
|---|---|---|---|---|---|
| fs4_spiral_seq | 螺旋线序列 | 🦢 | score:{threshold:68,consecutive:2,action_type:"步法"} | 120 | [fs3_crossover_fig8,fs2_spirals] |
| fs4_sit_spin | 蹲转3圈 | 🪑 | problem_gone:{category:"重心偏移",consecutive_clean:3} | 200 | [fs3_backspin_cross] |
| fs4_fwd_bk_spin | 前旋转后旋 | 🌀 | score:{threshold:70,consecutive:3,action_type:"旋转"} | 200 | [fs3_backspin_cross] |
| fs4_loop | 勾手跳 | 🔁 | score:{threshold:70,consecutive:3,action_type:"跳跃"} | 150 | [fs2_toe] |
| fs4_flip | 翻转跳 | 🃏 | score:{threshold:70,consecutive:3,action_type:"跳跃"} | 150 | [fs2_sal] |

### 第六章：五级 fs5
| id | name | emoji | unlock_config | xp | requires |
|---|---|---|---|---|---|
| fs5_camel | 燕式旋转3圈 | 🦅 | problem_gone:{category:"重心偏移",consecutive_clean:3} | 250 | [fs4_sit_spin] |
| fs5_spin_combo | 联合旋转 | 🌀 | score:{threshold:70,consecutive:3,action_type:"旋转"} | 200 | [fs4_fwd_bk_spin] |
| fs5_lutz | 勾手外跳 | ⚔️ | score:{threshold:72,consecutive:3,action_type:"跳跃"} | 200 | [fs4_flip] |
| fs5_loop_loop | 勾手+勾手连跳 | 🔁 | score:{threshold:72,consecutive:3,action_type:"跳跃"} | 250 | [fs4_loop] |

### 第七章：六级 fs6
| id | name | emoji | unlock_config | xp | requires |
|---|---|---|---|---|---|
| fs6_camel_sit | 燕转蹲转联合 | 🦅 | score:{threshold:72,consecutive:3,action_type:"旋转"} | 300 | [fs5_camel,fs4_sit_spin] |
| fs6_layback | 仰身旋转 | 🌟 | problem_gone:{category:"手臂松散",consecutive_clean:3} | 350 | [fs5_spin_combo] |
| fs6_axel_prep | Axel 预备 | 👑 | score:{threshold:70,consecutive:2,action_type:"跳跃"} | 400 | [fs5_lutz] |

### 第八章：七级 fs7
| id | name | emoji | unlock_config | xp | requires |
|---|---|---|---|---|---|
| fs7_camel_sit_bk | 燕转蹲转+换脚 | 🦅 | score:{threshold:75,consecutive:3,action_type:"旋转"} | 350 | [fs6_camel_sit] |
| fs7_flying_spin | 飞旋 | 🚀 | score:{threshold:75,consecutive:3,action_type:"旋转"} | 350 | [fs6_camel_sit] |
| fs7_axel | Axel 1.5周 | 👑 | score:{threshold:75,consecutive:3,action_type:"跳跃"} | 400 | [fs6_axel_prep] |

### 第八章：八级 fs8
| id | name | emoji | unlock_config | xp | requires |
|---|---|---|---|---|---|
| fs8_spin_4pos | 四位置联合旋转 | 🌟 | score:{threshold:78,consecutive:3,action_type:"旋转"} | 400 | [fs7_camel_sit_bk,fs6_layback] |
| fs8_2toe | 双周点冰跳 | 💎 | score:{threshold:78,consecutive:3,action_type:"跳跃"} | 400 | [fs7_axel] |
| fs8_2sal | 双周萨霍夫 | 💎 | score:{threshold:78,consecutive:3,action_type:"跳跃"} | 400 | [fs7_axel] |
| fs8_2loop | 双周勾手跳 | 💎 | score:{threshold:78,consecutive:3,action_type:"跳跃"} | 400 | [fs8_2toe] |

### 第九章：九级 fs9
| id | name | emoji | unlock_config | xp | requires |
|---|---|---|---|---|---|
| fs9_2flip | 双周翻转 | 🃏 | score:{threshold:80} | 500 | [fs8_2loop] |
| fs9_2lutz | 双周勾手外 | ⚔️ | score:{threshold:80} | 500 | [fs8_2loop] |
| fs9_2axel | 双 Axel 2.5周 | 👑 | score:{threshold:82} | 800 | [fs7_axel] |

### 第十章：十级 fs10（parent_only）
| id | name | emoji | xp |
|---|---|---|---|
| fs10_3toe | 三周点冰 | 🌈 | 1000 |
| fs10_3sal | 三周萨霍夫 | 🌈 | 1000 |
| fs10_3axel | 三 Axel | 🏆 | 2000 |
| fs10_quad | 四周跳 | 💫 | 3000 |

---

## 角色成长阶段

| Lv | XP门槛 | 称号 | emoji |
|---|---|---|---|
| 1 | 0 | 冰场小企鹅 | 🐧 |
| 2 | 200 | 冰上小熊猫 | 🐼 |
| 3 | 600 | 冰雪小狐狸 | 🦊 |
| 4 | 1500 | 冰雪小骑士 | 🏅 |
| 5 | 3000 | 冰雪小王子 | 👑 |
| 6 | 6000 | 冰雪勇士 | ⚔️ |
| 7 | 10000 | 冰上骑士长 | 🛡️ |
| 8 | 16000 | 冰雪传说 | 🌟 |
| 9 | 25000 | 冰上英雄 | 🦅 |
| 10 | 40000 | 冰雪大师 | 🏆 |

---

## ✅ Phase 4 验证清单

### 4-A PIN 与模式切换
- [ ] 首次点击家长模式，跳转 `/parent/setup` 设置PIN
- [ ] 进入家长模式需输入PIN，输错3次后提示
- [ ] `docker compose down` 再 `up`，PIN设置仍保留

### 4-B 选手档案与 display_name
- [ ] 系统启动后自动创建「坦坦🦁」和「弟弟🐨」两个档案
- [ ] 坦坦的 snowplow/basic 节点显示为已完成
- [ ] 家长模式下可修改 display_name 和 avatar_emoji

### 4-C 技能树显示
- [ ] 学习路径视图：4个阶段卡片，当前阶段高亮，百分比正确
- [ ] 当前阶段详情卡片显示「未点亮/推进中/已点亮」统计数正确
- [ ] 「看已点亮图谱」按钮切换到冰面路线图视图
- [ ] 冰面路线图：节点按群组分类，已点亮绿色，推进中橙色
- [ ] 节点三状态视觉区分清晰
- [ ] 家长解锁的节点显示小皇冠 👑

### 4-D 技能解锁
- [ ] 连续分析3次跳跃 force_score > 65，`fs1_waltz` 自动解锁
- [ ] 家长手动解锁：输入PIN + 备注，立即显示已解锁（皇冠标记）
- [ ] 解锁时触发庆祝动画
- [ ] XP 累加，成长卡片进度条更新

### 4-E 儿童友好性
- [ ] 坦坦模式文案使用鼓励语气
- [ ] 技能节点触控区域最小 88px
- [ ] 庆祝动画在手机上不卡顿

### 4-F Settings 页（家长模式专属）
- [ ] 选手管理：可修改 display_name、avatar_emoji、birth_year
- [ ] AI 供应商配置：vision/report 槽各自当前激活供应商，可切换
- [ ] 系统信息：版本号、DB 大小、上传文件占用空间

---

# Phase 5：三端 UI 适配 + 四标签导航

> **目标**：全面升级 UI 至三端自适应设计系统，实现底部四标签导航
> **v3 重要变化**：原来基于页面路由的导航，重构为四个底部标签

---

## 四标签底部导航（**v3 新增**）

全局底部 BottomNav 组件，所有主要视图共用：

```
┌──────────┬──────────┬──────────┬──────────┐
│  🛤️ 路径  │  ❄️ 冰宝（IceBuddy） │  🎬 复盘  │  📈 进展  │
└──────────┴──────────┴──────────┴──────────┘
```

| 标签 | 图标 | 对应视图 | 路由 |
|---|---|---|---|
| 路径 | ⛸️ | SkillTreePage（含学习路径+冰面路线图） | `/path` |
| 冰宝（IceBuddy） | ❄️ | SnowballPage（AI聊天 + 记忆管理入口） | `/snowball` |
| 复盘 | 🎬 | ReviewPage（视频复盘3步流程） | `/review` |
| 进展 | 📈 | ArchivePage（练习档案时间轴） | `/archive` |

**BottomNav 组件规范：**
- 高度：49px（iPhone HIG 标准）
- 激活标签：图标 + 文字，蓝色 `#3B82F6`
- 非激活：图标 + 文字，灰色 `#9CA3AF`
- 上方细分隔线 `#E5E7EB`
- iPhone 底部安全区（safe-area-inset-bottom）padding

---

## 视频复盘页（ReviewPage）—— **v3 重新设计**

路由 `/review`，对应「复盘」标签，3步流程：

```
REVIEW FLOW
视频复盘

上传视频后，冰宝（IceBuddy）会抽取关键帧做诊断。
你不再需要手填四段自评，只需补充你最在意的问题。

Step 1：选择训练视频
  [ 选择训练视频 ] ← 按钮

Step 2：告诉冰宝（IceBuddy）你在看什么
  下拉选框：技能分类（对应 SkillNode 列表）
  补充说明（可选）：文本输入框
  placeholder: "例如：我最想知道为什么落冰总是..."

Step 3：coach 视频诊断
  [ 开始 coach 诊断 ]（未上传时 disabled）
  [ 保存本条复盘 ]
```

**技能分类下拉选项**（从 SkillNode 动态读取，按章节分组）：
- 安全摔倒与起立
- 前向蹬冰
- 华尔兹跳
- ...（所有节点名称）

**点击「开始 coach 诊断」后的流程：**
1. 调用 `POST /api/analysis/upload`（带 skill_category 字段）
2. 跳转 `/report/:id`（ReportPage）
3. 分析完成后，结果自动进入练习档案时间轴

---

## DESIGN.md（项目根目录放置此文件，Codex 开发前读取）

### 一、颜色系统

#### 儿童模式（坦坦模式）
```css
--kid-primary:   #6C63FF;  /* 紫罗兰 */
--kid-secondary: #FF6B9D;  /* 粉玫瑰 */
--kid-accent:    #FFD93D;  /* 金黄，成就感 */
--kid-success:   #4CAF50;  /* 绿，解锁/完成 */
--kid-bg:        #F8F6FF;  /* 极淡紫白底 */
```

#### 家长模式
```css
--parent-primary: #0F172A;
--parent-accent:  #3B82F6;
--parent-success: #22C55E;
--parent-warning: #F59E0B;
--parent-danger:  #EF4444;
--parent-bg:      #FAFAFA;
--parent-surface: #FFFFFF;
--parent-border:  #E5E7EB;
```

#### 技能分支固定色
```css
--branch-jump:     #6C63FF;
--branch-spin:     #3B82F6;
--branch-step:     #F59E0B;
--branch-basic:    #22C55E;
--branch-snowplow: #EC4899;
```

#### 发力评分颜色
```css
--score-high: #22C55E;  /* 80+ */
--score-mid:  #F59E0B;  /* 60-79 */
--score-low:  #EF4444;  /* <60 */
```

#### 路径技能状态颜色（**v3 新增**）
```css
--node-unlocked-bg:  #E0F7F4;  /* 浅青绿 */
--node-unlocked-dot: #4CAF50;  /* 绿点 */
--node-inprogress-bg:  #FFF3E0;
--node-inprogress-dot: #F59E0B;
--node-locked-bg:  #F3F4F6;
--node-locked-dot: #9CA3AF;
```

### 二、字体系统
```css
--font-sans: -apple-system, BlinkMacSystemFont, "PingFang SC",
             "Hiragino Sans GB", "Helvetica Neue", sans-serif;
--text-xs:       12px;
--text-sm:       14px;
--text-base:     16px;
--text-lg:       18px;
--text-xl:       20px;
--text-2xl:      24px;
--text-3xl:      30px;
--text-kid-emoji: 48px;
--text-kid-hero:  64px;
```

### 三、三端断点
```js
screens: {
  'phone':  '375px',
  'tablet': '768px',
  'ipad':   '1024px',
  'web':    '1280px',
  'wide':   '1440px',
}
```

### 四、触控目标规范
```css
--touch-min: 44px;
--touch-kid: 56px;
/* 底部标签区域高度 49px，图标+文字总高度 */
```

### 五、三端页面布局规范

#### 底部导航（BottomNav）
```
iPhone:  固定底部，高度 49px + safe-area
iPad:    固定底部，同 iPhone
Web:     改为左侧固定侧边导航栏（240px），内容区右侧
```

#### ReviewPage（复盘）
```
iPhone:  单列，三个步骤块竖向堆叠
iPad:    单列居中 max-w-lg
Web:     两列（左：视频选择+技能选择；右：诊断结果快速预览）
```

#### ArchivePage（进展）
```
iPhone:  顶部3格统计 + 下方时间轴列表
iPad:    统计行更宽，时间轴居中 max-w-2xl
Web:     左列（统计面板+筛选）+ 右列（时间轴），max-w-4xl
```

#### SkillTreePage（路径，两个子视图）
```
iPhone:  学习路径：横滑4阶段卡片 + 当前阶段详情
         冰面路线图：群组标题行 + 3列节点网格
iPad:    学习路径：4格并排 + 详情右侧展开
         冰面路线图：4列节点网格
Web:     左侧阶段导航 + 右侧节点内容区
```

#### ReportPage
```
iPhone:  单列从上到下
iPad:    上半评分+总评，下半两列（雷达图 | 问题）
Web:     左列（评分+雷达图+生物力学+T/A/L面板）+ 右列（总评+问题+改进+训练重点）
```

### 六、核心组件 HTML/Tailwind 模板

#### 发力评分圆环（ForceScoreRing）
```html
<div class="relative w-24 h-24 tablet:w-28 tablet:h-28">
  <svg class="w-full h-full -rotate-90" viewBox="0 0 100 100">
    <circle cx="50" cy="50" r="42" fill="none"
            stroke="#E5E7EB" stroke-width="8"/>
    <circle cx="50" cy="50" r="42" fill="none"
            stroke="var(--score-color)" stroke-width="8"
            stroke-linecap="round"
            stroke-dasharray="263.9"
            stroke-dashoffset="calc(263.9 * (1 - var(--score) / 100))"
            class="transition-all duration-700 ease-out"/>
  </svg>
  <div class="absolute inset-0 flex flex-col items-center justify-center">
    <span class="text-2xl font-bold">{score}</span>
    <span class="text-xs text-gray-400">分</span>
  </div>
</div>
```

#### XP 进度条（流光动效）
```html
<div class="h-3 bg-gray-100 rounded-full overflow-hidden">
  <div class="h-full rounded-full bg-gradient-to-r from-violet-400 to-pink-400
              relative overflow-hidden transition-all duration-700"
       style="width: 56%">
    <div class="absolute inset-0 w-1/3 bg-white/30 skew-x-12
                animate-shimmer"></div>
  </div>
</div>
```

#### 技能节点（三状态）
```html
<!-- 已解锁（已点亮） -->
<div class="relative flex flex-col items-center gap-2 p-4
            bg-[#E0F7F4] rounded-3xl border-2 border-[#4CAF50]/30
            active:scale-95 transition-transform min-w-[88px]">
  <div class="w-3 h-3 rounded-full bg-[#4CAF50] absolute top-3 left-3"></div>
  <span class="text-xs font-bold text-gray-700 text-center">华尔兹跳</span>
  <span class="text-xs text-[#4CAF50] font-medium">已点亮</span>
</div>

<!-- 进行中（推进中） -->
<div class="flex flex-col items-center gap-2 p-4
            bg-[#FFF3E0] rounded-3xl border-2 border-[#F59E0B]/30 min-w-[88px]">
  <div class="w-3 h-3 rounded-full bg-[#F59E0B] absolute top-3 left-3"></div>
  <span class="text-xs font-bold text-gray-700 text-center">华尔兹跳</span>
  <span class="text-xs text-[#F59E0B] font-medium">推进中</span>
</div>

<!-- 锁定（未点亮） -->
<div class="flex flex-col items-center gap-2 p-4
            bg-gray-50 rounded-3xl border-2 border-gray-100
            min-w-[88px] opacity-70">
  <div class="w-3 h-3 rounded-full bg-gray-300 absolute top-3 left-3"></div>
  <span class="text-xs font-medium text-gray-400 text-center">华尔兹跳</span>
  <span class="text-xs text-gray-400">未点亮</span>
</div>
```

#### 学习路径阶段卡片（**v3 新增**）
```html
<!-- 当前阶段（激活状态） -->
<div class="bg-white rounded-2xl p-4 shadow-sm border border-blue-100 min-w-[140px]">
  <p class="text-xs text-blue-500 font-medium">阶段 2</p>
  <div class="h-1.5 bg-blue-100 rounded-full mt-1 overflow-hidden">
    <div class="h-full bg-blue-500 rounded-full" style="width: 100%"></div>
  </div>
  <p class="text-xl font-bold text-blue-600 mt-1">100%</p>
</div>

<!-- 已完成阶段 -->
<div class="bg-gray-50 rounded-2xl p-4 min-w-[140px]">
  <p class="text-xs text-gray-400">阶段 1</p>
  <div class="h-1.5 bg-gray-200 rounded-full mt-1">
    <div class="h-full bg-gray-400 rounded-full" style="width: 100%"></div>
  </div>
  <p class="text-xl font-bold text-gray-500 mt-1">100%</p>
</div>
```

#### PIN 输入格
```html
<div class="flex gap-3 justify-center">
  <input type="password" maxlength="1" inputmode="numeric"
         class="w-14 h-14 text-center text-2xl font-bold
                bg-gray-50 border-2 border-gray-200 rounded-2xl
                outline-none focus:border-violet-400 focus:bg-violet-50
                transition-all duration-150 tablet:w-16 tablet:h-16"/>
  <!-- × 4 -->
</div>
```

### 七、动效（globals.css 追加）
```css
@keyframes shimmer {
  0%   { transform: translateX(-100%) skewX(-12deg); }
  100% { transform: translateX(400%) skewX(-12deg); }
}
@keyframes float {
  0%, 100% { transform: translateY(0px); }
  50%       { transform: translateY(-8px); }
}
@keyframes unlock-pop {
  0%   { transform: scale(0) rotate(-10deg); opacity: 0; }
  60%  { transform: scale(1.2) rotate(5deg);  opacity: 1; }
  100% { transform: scale(1) rotate(0deg);    opacity: 1; }
}
@keyframes star-burst {
  0%   { transform: translate(0,0) scale(0); opacity: 1; }
  100% { transform: translate(var(--tx),var(--ty)) scale(0.5); opacity: 0; }
}
.star-1 { --tx:60px;  --ty:-60px; }  .star-2 { --tx:-60px; --ty:-60px; }
.star-3 { --tx:80px;  --ty:0px;   }  .star-4 { --tx:-80px; --ty:0px;   }
.star-5 { --tx:60px;  --ty:60px;  }  .star-6 { --tx:-60px; --ty:60px;  }
.star-7 { --tx:0px;   --ty:-80px; }  .star-8 { --tx:0px;   --ty:80px;  }
.star-particle { animation: star-burst 0.8s ease-out forwards; }

@media (prefers-reduced-motion: reduce) {
  .animate-shimmer, .animate-float,
  .unlock-pop, .star-particle { animation: none; }
}
```

### 八、tailwind.config.js 完整扩展
```js
module.exports = {
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      screens: {
        phone: '375px', tablet: '768px',
        ipad: '1024px', web: '1280px', wide: '1440px',
      },
      colors: {
        kid: {
          primary: '#6C63FF', secondary: '#FF6B9D',
          accent: '#FFD93D', success: '#4CAF50', bg: '#F8F6FF',
        },
        branch: {
          jump: '#6C63FF', spin: '#3B82F6',
          step: '#F59E0B', basic: '#22C55E', snowplow: '#EC4899',
        },
      },
      borderRadius: { '3xl': '24px', '4xl': '32px' },
      keyframes: {
        shimmer: {
          '0%': { transform: 'translateX(-100%) skewX(-12deg)' },
          '100%': { transform: 'translateX(400%) skewX(-12deg)' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0px)' },
          '50%': { transform: 'translateY(-8px)' },
        },
        'unlock-pop': {
          '0%': { transform: 'scale(0) rotate(-10deg)', opacity: '0' },
          '60%': { transform: 'scale(1.2) rotate(5deg)', opacity: '1' },
          '100%': { transform: 'scale(1) rotate(0deg)', opacity: '1' },
        },
      },
      animation: {
        shimmer: 'shimmer 2s infinite',
        float: 'float 2s ease-in-out infinite',
        'unlock-pop': 'unlock-pop 0.5s cubic-bezier(0.34,1.56,0.64,1)',
      },
    },
  },
}
```

---

## 组件重构清单

| 组件 | 重构内容 |
|---|---|
| BottomNav | **新建**，四标签，Web 版改为左侧侧边导航 |
| ReviewPage | **新建**，3步流程，替代旧 UploadPage |
| ArchivePage | **新建**，练习档案时间轴，替代旧 HistoryPage |
| SkillTreePage | 增加学习路径视图 + 冰面路线图视图切换 |
| ReportPage | 增加 T/A/L 面板区块，评分圆环 SVG |
| BiomechanicsPanel | **新建**，T/A/L 关键帧标签 + 4指标卡片 |
| SnowballPage | **新建（Phase 6）**，AI 对话 + 记忆管理入口 |
| ForceScoreRing | 新建，SVG 圆环 + 动态颜色 |
| XpProgressBar | 新建，流光动效进度条 |
| SkillNode | 三状态完整实现，88px 最小宽度 |
| UnlockCelebration | 全屏庆祝动画，8粒子 |
| ModeToggle | 右上角固定，双模式状态 |
| ParentUnlockModal | PIN 4格输入，备注输入 |

---

## ✅ Phase 5 验证清单

### 5-A 底部四标签导航
- [ ] 四标签正常显示，文字和图标对应
- [ ] 激活标签颜色蓝色，非激活灰色
- [ ] iPhone 底部安全区 padding 正常（不被 Home Bar 遮挡）
- [ ] Web 端左侧侧边导航出现（≥ 1280px）

### 5-B 复盘页（ReviewPage）
- [ ] 三步流程布局正确
- [ ] 技能分类下拉动态读取 SkillNode 列表
- [ ] 未选视频时「开始 coach 诊断」按钮置灰
- [ ] 点击诊断后跳转 ReportPage，保留 skill_category

### 5-C 进展页（ArchivePage）
- [ ] 三格统计数据正确（累计/近7天/连续）
- [ ] 时间轴按时间倒序
- [ ] 「查看诊断详情」跳转对应 ReportPage

### 5-D SkillTree 路径视图
- [ ] 学习路径视图：4阶段卡片水平排列，当前阶段高亮蓝色
- [ ] 「看已点亮图谱」按钮切换冰面路线图视图
- [ ] 冰面路线图：节点按群组 + 3列网格排布，颜色状态正确

### 5-E iPhone 适配
- [ ] 所有按钮高度 ≥ 44px
- [ ] 技能节点触控区最小 88px
- [ ] 键盘弹出时输入框不被遮挡

### 5-F 动效
- [ ] XP进度条流光动效正常
- [ ] 技能解锁庆祝动画8粒子正常
- [ ] 开启「减少动画」后所有动效关闭

---

# Phase 6：冰宝（IceBuddy）系统（AI角色 + 长期记忆 + API设置重设计）

> **目标**：赋予 AI 助手「冰宝（IceBuddy）」的角色身份，建立可持久化的长期记忆系统，
> 让每次分析都能感知训练历史、用户偏好和当前目标。
> 同时重设计 API 设置页面，新增冰宝（IceBuddy）记忆管理页。

---

## 冰宝（IceBuddy）角色设定

**名称**：冰宝（IceBuddy）（英文：IceBuddy）
**人设**：一只聪明温柔的雪白小雪豹，专门陪坦坦和弟弟练溜冰。
**口吻**：简洁、可执行、鼓励性。不说教，不废话，指出问题时像朋友一样直接。
**全局替换**：系统中所有「AI 助手」「教练」「分析师」等描述，在前端展示层统一替换为「冰宝（IceBuddy）」。

**在以下位置使用冰宝（IceBuddy）名称：**
- ReportPage 加载中文字：「冰宝（IceBuddy）正在分析，通常需要 1-2 分钟…」
- ReviewPage 第2步标题：「告诉冰宝（IceBuddy）你在看什么」
- ArchivePage 时间轴条目类型：「冰宝（IceBuddy）诊断」
- SnowballPage 页面标题
- 所有 toast/提示文案

---

## 新增数据模型

### SnowballMemory 表
```python
id:           str (UUID, PK)
skater_id:    str (FK → Skater.id)
title:        str           # 记忆标题，如「当前目标」
content:      str           # 记忆正文
category:     str           # "目标" | "偏好" | "总结" | "卡点" | "其他"
is_pinned:    bool          # 固定（始终注入到 AI context）
created_at:   datetime
updated_at:   datetime
```

**预置记忆示例（坦坦初始化时写入）：**
```python
DEFAULT_MEMORIES = [
    {
        "title": "当前目标",
        "content": "华尔兹",
        "category": "目标",
        "is_pinned": True
    },
    {
        "title": "提醒风格",
        "content": "更喜欢简洁、可执行的练习提示，而不是太长的说教。",
        "category": "偏好",
        "is_pinned": True
    },
    {
        "title": "安全优先",
        "content": "涉及跳跃、旋转和高风险动作时，要优先提醒保护和线下教练确认。",
        "category": "总结",
        "is_pinned": True
    }
]
```

---

## 新增后端接口

```
# 冰宝（IceBuddy）记忆 CRUD
GET    /api/skaters/{id}/memories            获取所有记忆（按 is_pinned 置顶）
POST   /api/skaters/{id}/memories            新增记忆
       body: {title, content, category, is_pinned}
PATCH  /api/skaters/{id}/memories/{mem_id}   更新记忆
DELETE /api/skaters/{id}/memories/{mem_id}   删除记忆
PATCH  /api/skaters/{id}/memories/{mem_id}/pin  切换 is_pinned
```

---

## 冰宝（IceBuddy）记忆 Context 注入

**所有 AI 调用（vision.py / report.py / plan.py）在发送前，自动注入固定记忆到 System Prompt：**

```python
async def build_memory_context(skater_id: str) -> str:
    """
    获取该选手所有 is_pinned=True 的记忆，拼接成文字块。
    返回示例：
    ---
    关于这位选手的长期背景信息：
    [当前目标] 华尔兹
    [提醒风格] 更喜欢简洁、可执行的练习提示，而不是太长的说教。
    [安全优先] 涉及跳跃、旋转和高风险动作时，要优先提醒保护和线下教练确认。
    ---
    """
```

**注入位置：System Prompt 末尾追加**
```python
system_prompt = BASE_SYSTEM_PROMPT + "\n\n" + await build_memory_context(skater_id)
```

**若 skater_id 为空（未关联选手），memory_context 为空字符串，正常分析不受影响。**

---

## 前端新增页面

### SnowballPage（路由：/snowball，对应「冰宝（IceBuddy）」标签）

页面分两个区块：

**区块 A：冰宝（IceBuddy）聊天**
- 顶部：冰宝（IceBuddy）头像（❄️ 或自定义雪豹 SVG）+ 「冰宝（IceBuddy）」标题 + 「SNOWBALL COACH」副标题
- 聊天输入框（底部固定）+ 历史对话（上方可滚动）
- 初始欢迎消息：「嗨！我是冰宝（IceBuddy） ☃️ 今天想练什么？」
- 调用 `/api/snowball/chat` 接口（见下）

**区块 B：冰宝（IceBuddy）记忆（家长模式可见）**
- 标题：长期记忆（SNOWBALL MEMORY）
- 描述：这里保存冰宝（IceBuddy）长期参考的信息，比如你的目标、偏好、常见卡点，以及你想固定留下来的摘要。
- 「新增一条记忆」蓝色按钮
- 记忆卡片列表（is_pinned 的置顶）：
  ```
  ┌──────────────────────────────────────────┐
  │ 当前目标                        固定  目标 │
  │ 华尔兹                                   │
  │ [编辑]  [删除]                           │
  └──────────────────────────────────────────┘
  ```
  - 右上角：「固定」徽章（is_pinned=True）+ 分类标签（目标/偏好/总结/卡点）
  - 「编辑」→ 内联编辑 或 弹窗
  - 「删除」→ 二次确认后删除

**新增记忆弹窗字段：**
- 标题（文本框）
- 内容（文本域）
- 分类（单选：目标/偏好/总结/卡点/其他）
- 固定开关（toggle）

---

### 冰宝（IceBuddy）聊天接口

```
POST /api/snowball/chat
body: {
  "skater_id": "uuid",
  "message": "用户消息",
  "history": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ]
}
response: { "reply": "冰宝（IceBuddy）的回复" }
```

**chat service 实现要点：**
- 调用 report 槽当前激活供应商
- System prompt：
  ```
  你是冰宝（IceBuddy），一只专业的花样滑冰AI教练助手。
  你的风格：简洁、可执行、鼓励性，像朋友一样直接。
  不说教，不废话。涉及高风险动作时优先建议线下教练确认。
  ```
- System prompt 末尾追加 `build_memory_context(skater_id)` 输出
- 将 `history` + 新 `message` 传入 messages 数组

---

## API 设置页重设计（**v3 重新设计**）

路由：`/settings/api`（从家长模式冰宝（IceBuddy）页面或设置入口进入）

**页面结构：**

```
← 返回

PRIVATE KEYS
API 设置
在这里配置豆包、MiniMax、DeepSeek 的 Key、模型和根地址。
Key 保存在本机数据库。

当前使用的服务商
[ 豆包（火山方舟） ]  [ MiniMax ]  [ DeepSeek ✓ ]
（Segmented Control，选中的有白色底）

说明：若你的 DeepSeek 接口支持视觉模型，请填写视觉模型字段；否则仅保留文本能力。

─────────────────────────────────
豆包（火山方舟）

豆包走 OpenAI 兼容接口；模型请填写方舟接入点 ID，通常以 ep- 开头。

豆包 API Key
[ 请输入 ]

接入点模型 ID
[ 请输入模型名，如 ep-xxxxxxxx-xxxxx ]

多模态模型（视频诊断，可选）
[ 可选：填写支持视觉的模型名/接入点 ]

API 根地址
[ https://ark.cn-beijing.volces.com/api/v3 ]

─────────────────────────────────
MiniMax / DeepSeek（同上结构）
```

**Segmented Control 规范：**
- 3个选项：豆包（火山方舟）/ MiniMax / DeepSeek
- 选中项：白色卡片 + 加粗文字 + 阴影
- 未选：透明背景 + 灰色文字
- 点击切换下方表单区域内容（动态切换，不是页面跳转）

**供应商配置字段统一结构：**
```
provider_tab: "doubao" | "minimax" | "deepseek"
fields:
  api_key:       必填
  model_id:      必填（豆包填 ep- 开头的接入点 ID）
  vision_model:  可选（支持视觉时填写）
  base_url:      预填默认值，可修改
```

**底部操作按钮：**
- 「保存」按钮（调用 PATCH /api/providers/{id} 接口）
- 「测试连接」按钮（调用 POST /api/providers/{id}/test）

---

## 数据库迁移（Phase 6）

```python
NEW_TABLES = ["snowball_memories"]

async def run_migrations_phase6(engine):
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS snowball_memories (
                id TEXT PRIMARY KEY,
                skater_id TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT '其他',
                is_pinned INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (skater_id) REFERENCES skaters(id)
            )
        """))
```

---

## ✅ Phase 6 验证清单

### 6-A 冰宝（IceBuddy）角色
- [ ] ReportPage 加载文字包含「冰宝（IceBuddy）」（不再说「AI 分析中」）
- [ ] ReviewPage 第2步标题是「告诉冰宝（IceBuddy）你在看什么」
- [ ] ArchivePage 时间轴条目类型显示「冰宝（IceBuddy）诊断」

### 6-B 长期记忆管理
- [ ] SnowballPage 的记忆管理区（家长模式下）显示默认3条记忆
- [ ] 「新增一条记忆」弹窗字段完整（标题/内容/分类/固定开关）
- [ ] 新增记忆后立即出现在列表，is_pinned 的置顶
- [ ] 编辑记忆后内容更新，删除记忆后消失（二次确认）
- [ ] 坦坦模式下，记忆管理区不可见

### 6-C Context 注入
- [ ] 上传视频分析，查看后端日志：System prompt 末尾包含固定记忆内容
- [ ] 修改「当前目标」记忆为「点冰跳」，再次分析，报告 training_focus 应偏向点冰跳方向
- [ ] 删除所有固定记忆后，分析仍正常运行（memory_context 为空字符串）

### 6-D 冰宝（IceBuddy）聊天
- [ ] SnowballPage 聊天区可以发送消息并收到冰宝（IceBuddy）回复
- [ ] 历史对话正确传入（上下文连贯）
- [ ] 回复包含固定记忆中的目标信息（如目标是华尔兹，冰宝（IceBuddy）聊天时会结合这个背景）

### 6-E API 设置页
- [ ] Segmented Control 三个供应商切换正常
- [ ] 豆包选项提示「接入点 ID 通常以 ep- 开头」
- [ ] 「若接口支持视觉模型」说明文字存在
- [ ] 「保存」调用正确接口，「测试连接」返回结果
- [ ] api_key 存储后再打开显示 `***`

---

# 附：开发顺序与 Codex 使用建议

## 推荐发送顺序
```
Phase 1 → 验证 1-A～1-G
→ Phase 2 → 验证 2-A～2-E
→ Phase 3（先改造一+四，再改造五+三+二）→ 验证 3-A～3-E
→ Phase 4 → 验证 4-A～4-F
→ Phase 5 → 验证 5-A～5-F
→ Phase 6 → 验证 6-A～6-E
```

## 每次发送时在开头加的说明
```
这是一个已有 Phase N 代码的项目，请在现有代码基础上继续开发
Phase N+1，不要重写已有文件，只新增或修改涉及的文件。
所有 API Key 由我手动填入 .env，Codex 使用占位符即可。
```

## Phase 3 改造顺序提醒
```
请按以下顺序实现，每个改造独立可验证：
1. 改造一：Prompt 结构化约束（vision.py + report.py）
2. 改造四：骨骼几何计算（biomechanics.py）+ T/A/L 关键帧
3. 改造五：T/A/L 面板（BiomechanicsPanel.tsx）
4. 改造三：运动密度采样（video.py）
5. 改造二：骨骼可视化（pose.py + PoseViewer.tsx）
```

## Phase 6 发送时的特别说明
```
Phase 6 涉及以下新内容：
1. 新建 SnowballMemory 数据模型和 CRUD 接口
2. 在所有 AI 调用中注入长期记忆 context（不破坏现有逻辑）
3. 前端新建 SnowballPage（聊天 + 记忆管理）
4. 重设计 API 设置页为三供应商 Segmented Control 界面
请先跑 run_migrations_phase6 后再做前端。
```

## GPT 推理设置建议
- Phase 1-2：默认推理
- Phase 3（几何计算/T/A/L逻辑）：中等推理
- Phase 4（技能解锁逻辑）：中等推理
- Phase 5（三端布局）：默认推理
- Phase 6（记忆注入逻辑）：中等推理
- 遇到 Codex 输出逻辑错误时临时调高

---
*坦坦加油！☃️🦁*
