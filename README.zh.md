# Skating Analyzer

基于 React、FastAPI、MediaPipe、YOLO/ByteTrack 和 Docker 的花样滑冰训练视频分析系统。

[English README](./README.md) | [贡献指南](./CONTRIBUTING.md) | [许可证](./LICENSE) | [截图说明](./SCREENSHOT_GUIDE.md)

## 项目简介

Skating Analyzer 面向滑冰学员、家长和教练，用一套可复现的分析流程辅助复盘训练视频。系统会上传视频、抽取运动采样帧、锁定目标滑行者、运行姿态与人体跟踪、解析起跳/腾空/落冰关键时刻，并在配置 AI 供应商后调用视觉模型生成结构化报告、训练计划、档案和进度视图。

当前分析管线版本为 `v5.2.319`。

## 动森成长岛现代界面

系统新增可选的**动森风格现代界面**，面向家庭使用场景。经典界面保持原样，且可随时在顶部切换。

- **四个清楚空间**：今日岛屿（`/home`）、开始复盘 / 冰场小屋（`/review`）、成长群岛（`/growth`）、居民服务处（`/me`）。原先分散的功能入口已聚合，同时保留旧 URL 兼容。
- **统一复盘工作台**：报告总结、关键时刻、身体与姿态、AI 追问和诊断都收在同一次分析详情中；旧 workspace 的 `tab` 链接会自动映射到对应分区。
- **三端适配**：手机 PWA 使用固定在视口底部、适配安全区的底部 Dock；iPad 竖屏保留 Dock 并采用双栏；iPad 横屏和桌面端则显示固定左侧导航。所有入口仅在当前页面显示选中态，包括“开始复盘”。
- **家庭友好氛围**：晨间、白天、傍晚和夜间主题会自动切换，也可手动固定；场景使用动森草地纹理、海面和树线素材，并随时段改变色调；夜间模式为顶栏和页头使用独立的高对比文字颜色。儿童/家长模式共享布局，仅调整文案、信息密度和受保护的高级工具。
- **优化的导航素材**：四个一级入口使用适配自动森的地图、相机、里程和设计图标；“开始复盘”在非复盘空间保持中性色，只在复盘空间激活为日光黄色。
- **PWA 支持**：生产版会注册同源 Service Worker，提供可安装 Manifest 和已缓存应用壳的导航离线回退；API 和写操作不会被缓存。

自然色、圆润卡片和导航语言参考并适配自 [guokaigdg/animal-island-ui](https://github.com/guokaigdg/animal-island-ui)。原仓库使用 CC BY-NC 4.0 许可证；本适配仅供个人非商业使用，并保留原作者署名。

## 最近更新（P0 — P2）

当前版本交付三条核心产品线：**P0 成长看板**、**P1 月度故事与分享**、**P2 年度合集与事件时间线**，以及 Golden 评测工具链、人物追踪改进和 OpenCode API 兼容修复。

### P0 — 成长看板

面向家长的成长仪表盘，全景展示孩子的训练轨迹：

- **成长摘要 API**：聚合课次数量、完成分析数、当月分析数、里程碑总数、最新分析及其训练重点，以及 Force Score 趋势数据，供前端看板消费。
- **GrowthKpiBar**：雷达式 KPI 条带，一目了然地展示 Force Score 趋势、课次计数、完成分析数和里程碑总数。
- **MilestoneTimeline**：按时间排列的里程碑列表，带有系统检测 / 家长确认 / 教练确认验证徽章、解锁时间戳和关联分析链接。
- **ActionPhaseStrip**：根据分析类型展示不同阶段的关键帧——跳跃显示 T/A/L，旋转显示 entry/main/exit，燕式显示 hold，步法显示覆盖帧，支持视频回放。
- **成长首页** (`/home`)：统一看板，整合 KPI、最新分析摘要、当前重点、下一步动作、关键帧阶段条、里程碑时间线及各成长工具导航入口。

### P1 — 月度故事与分享

可审核的月度成长章节，配备家庭金句引用和里程碑分享卡片：

- **家庭金句引用**：复盘上传表单新增可选字段——`highlight_quote`（最多 280 字）和 `quote_speaker`（孩子本人/家长/教练）。持久化在 `Analysis` 表，并在详情和月度事实快照中展示。
- **月度事实引擎** (`monthly_facts.py`)：按滑行者/月份的确定性事实聚合——课次计数、可比较跳跃指标（前后值、样本数、关联分析 ID）、当月里程碑解锁、报告问题类别的重复观察、训练重点追踪，以及逐字保留的金句。全部事实按确定性顺序排列。当无可靠趋势时自动标记 `insufficient_comparable_evidence` 等质量标志。从里程碑关联或高质量分析中选取最多四张代表性帧引用。
- **结构化章节生成** (`monthly_chapters.py`)：调用活跃的 `report` 供应商，传入确定性事实快照和结构化 JSON schema。验证每个亮点都引用存在的事实 ID、金句文本逐字复制、叙事不超过 1600 字，且禁止推断受伤、恐惧、疲劳诊断、一定能升级、教练确认等结论（除非该表述在供给事实中逐字出现）。供应商失败时保留 `facts_ready` 修订——快照永不删除。
- **成长 API** (`/api/growth`)：六个端点——`POST facts`、`POST generate`、`GET list`、`GET by ID`、`PATCH final_text`、`POST publish`。已发布的修订不可变；重新生成会创建下一个修订。
- **月度章节工作台** (`/chapters`)：滑行者/月份选择器、显式流程按钮（整理本月事实 → 生成叙事初稿 → 编辑 → 发布）、修订历史选择器、MonthlyFactPreview 按 count/metric/milestone/observation/quote 分组事实并显示来源/质量徽章，MonthlyChapterEditor 分离 AI 初稿与家长可编辑最终文字，含字符计数器和发布确认弹窗。
- **里程碑分享卡片** (`milestoneShareCanvas.ts`)：1080×1350 JPEG 分享图生成器，包含标题、日期、滑行者名称、验证徽章、金句引用、可选指标面板和可选关键帧图片。渐变主题设计；图片缺失时优雅降级为无图片面板。每个里程碑卡片上设有下载、复制到剪贴板和系统分享按钮。

### P2 — 年度合集与事件时间线

将月度章节汇编为可下载 PDF 的年度成长合集：

- **年度合集 API** (`/api/annual`)：预览合集（选中章节 + 里程碑的快照）、创建合集并记录来源哈希以保证可复现性、按滑行者/年份列出合集、列出含封面元数据的年度里程碑。
- **年度 PDF 导出** (`annual_pdf.py`)：基于 ReportLab 生成 A4 排版 PDF，包含封面页、目录、月度章节叙事、里程碑时间线和代表性帧图片。通过 `BackgroundTasks` 后台导出，状态跟踪（`pending` → `processing` → `completed`/`failed`）。
- **断点续传**：服务器崩溃/重启后的未完成导出任务会在启动时自动恢复。续传导出追踪 `resumed_at` 时间戳，保留原始 `created_at` 以维持排序。
- **年度合集界面** (`/annual`)：多步骤页面——从已发布月度章节中选取、选择里程碑、预览合集、触发 PDF 导出。显示实时导出状态，包括进度、成功/失败状态和下载链接。成长首页"制作年度合集"入口仅在存在已发布章节时显示。

### 基础设施与工具

- **MiMo/OpenCode API 修复**：移除 MiMo 聊天补全请求中多余的 `api-key` header；OpenCode 新 `sk-` 格式 Key 拒绝双 header 认证模式。新增诊断日志，输出活跃供应商 ID、类型、Base URL、模型和已解密 Key 前缀，方便排查认证问题。
- **Golden 评测工具链**：新增 `golden_overrides.py`（逐样本覆盖逻辑）、`diff_baselines.py`（评测运行对比）、对应测试套件，以及 `golden-eval-ab-runbook.md` A/B 评测流程文档。
- **人物追踪**：改进目标重锁定决策逻辑，新增手动锁定目标丢失后的自愈恢复，扩展重锁定场景测试覆盖。
- **关键帧候选**：增强仲裁诊断和垂直极值置信度阈值。
- **Debug 页面**：Golden 标注锚点现在捕获跟踪锚元数据（bbox、时间戳、帧 ID）、动作窗口边界和修订版本号，支持更精细的标注。

## 版本历史

- `v5.2.319`：P0 成长看板，含 KPI 雷达图、里程碑时间线、技能演进和按类型展示阶段数据；P1 月度成长章节，含家庭金句、确定性事实聚合、结构化章节生成、章节工作台和里程碑分享卡；P2 年度合集，含章节/里程碑选择、预览、后台 PDF 导出、断点续传和下载；移除多余 `api-key` header 兼容 OpenCode 新 `sk-` 格式 Key；新增 golden overrides、diff baselines 和 A/B 评测手册；改进人物追踪重锁定和自愈逻辑；增强关键帧仲裁诊断；debug golden 标注支持跟踪锚点和动作窗口边界。
- `v5.2.318`：已应用的动作识别和关键帧修正会写回 `analyses`；启动时自动回填历史已应用修正；报告/追问聊天工作台会在显示成功前刷新当前分析详情。
- `v5.2.315`：从 `codex/face-identity-target-lock` 导出 all-in-one Docker 镜像，包含人脸身份模型层、滑行者人脸档案 API、目标诊断、父级 UI 及档案删除功能。
- `v5.2.313`：已完成的进展/档案记录可直接跳转到 `/golden`；Golden 工作台按 URL 自动选中正式分析，不再强行打开无关 debug run。
- `v5.2.308`：手机端主角框选支持双指放大、平移和重置；手动动作区间启用更高密度采样；关键帧按 jump/spin/step/spiral 展示；分项评分统一修正来源和回退逻辑；报告/进展分享图加入 comments 与分项条，追问分享改为清晰多轮时间线。
- `v5.2.307`：对比生成持久化为 `analysis_comparisons` 后台任务；完整源视频只交给激活的 `vision` 模型；`report` provider 只基于结构化 JSON 文本生成总结；新增对比结果历史、重试、分享、手机端全静音同步播放。
- `v5.2.306`：追问聊天能识别用户备注中的多个问题并逐一回答；训练计划改用儿童安全低冲击提示词并强制 JSON schema；Archive 新增家长模式聚合接口、日历详情弹窗和快速导航。
- `v5.2.305`：追问可只跑视频 AI 全量视频关键帧重识别，生成待确认关键帧修正卡，不重跑 pose/生物力学/视觉报告。
- `v5.2.304`：追问聊天可提交重置主人物锁定的完整视频重新分析；重试确认会说明是否重新建立 skater lock；分享图可随长文本自适应高度。
- `v5.2.303`：Review 上传不再要求精确动作子类或技能节点；支持"不确定 / 只知道大类"，并把用户补充说明传入动作识别。
- `v5.2.11`：默认使用全量视频上下文；Review 和 Debug 支持可选手动起止点；Path A 使用生成的 AI clip。
- `v5.2.10`：后端启动不再自动 seed AI provider；请在 `/settings/api` 创建模型实例。
- `v5.2.9`：Path A 请求更严格的 JSON、恢复非标准模型输出、追加 JSON-only 修复重试；并回退 Path B/top-issue 兜底。
- `v5.2.8`：丢失后复用的 tracker bbox 可作为带 padding 的 pose crop hint，用于远距离小目标滑行者。

更早版本（v5.2.1 — v5.2.7）聚焦跟踪稳定性、姿态平滑、关键帧置信度和管线鲁棒性。完整历史见 [git log](https://github.com/qihq/skating-AI-analyzer/commits/master)。

## 核心功能

- 视频上传、异步分析与阶段感知重试；不知道精确动作名时可只提交动作大类。
- 运动采样、视频预检、模糊过滤。
- 目标预览、手动 bbox 框选、YOLO + ByteTrack 人体跟踪和逐帧 bbox 诊断。
- MediaPipe 姿态提取，支持平滑、多候选和 crop 回退逻辑。
- 生物力学指标，包括阶段时序、跳跃证据、旋转估算和姿态质量。
- Qwen 3.6 Plus 视频语义时间定位，用于动作大类识别与起跳/腾空/落冰区间解析。
- 语义关键帧时间戳仲裁，融合视频 AI、运动密度和骨架候选。
- 双路径视觉分析，支持 video context、供应商回退、非标准 JSON 恢复和成本限制。
- AI 辅助报告、训练计划、技能树、历史档案、进度追踪、儿童模式和家长模式。
- 后台对比工作台——持久化对比历史、完整源视频 AI 对比、同步播放和分享图导出。
- 成长看板 (P0) —— KPI 雷达、里程碑时间线、当前重点、下一步动作和技能演进视图。
- 月度成长章节 (P1) —— 家庭金句、确定性事实、AI 生成可审核章节、章节工作台和里程碑分享卡片。
- 年度合集导出 (P2) —— 月度章节汇编为 PDF，含封面、目录、叙事和里程碑，支持断点续传。
- 已完成视频的持久化 AI 追问，基于现有证据回答，支持 AI/手动修正卡和报告重新生成。
- 响应式 archive/report 工作台：archive 支持分页列表和日历 tab；report 保持主报告简洁，高级内容通过 workspace tab 展示。
- Pose Debug 与 Debug 页面，用于骨架回放、tracker 诊断和日志检查。
- Docker Compose 与 all-in-one Docker 部署，适合 NAS 或本地单容器运行。

## 分析流程

1. 上传源视频并创建分析记录；不知道精确动作名称时，可以只填写动作大类。
2. 解析 AI 输入范围：填写手动起止点时使用手动片段，否则默认使用完整源视频时间轴。
3. 执行视频预检、运动采样和关键帧/动作时序解析，时间戳保持源视频绝对时间。
4. 生成目标预览候选；置信度不足或存在多人/人工复核标记时等待手动选择。
5. 使用 YOLO/ByteTrack 跟踪目标滑行者，并执行逐帧 bbox 连续性检查。
6. 运行 MediaPipe 姿态提取和平滑处理。
7. 根据分析类型（跳跃/旋转/步法/燕式/自由滑）计算生物力学指标。
8. 如果在 `/settings/api` 中配置了 AI 供应商，系统会通过双路径视觉分析生成结构化报告和训练计划。
9. 完成的分析记录可在报告、追问、档案和进度视图中复查。
10. 成长看板、月度章节和年度合集可按自身节奏依次使用。

## 部署

### All-in-one Docker

```bash
docker run -d \
  --name skating-allinone \
  -p 8080:80 \
  -v /path/to/data:/data \
  -v /path/to/backups:/backups \
  -v /path/to/.env:/workspace/.env:ro \
  skating-analyzer-allinone:latest
```

### Docker Compose

```bash
docker compose up -d
```

`.env` 文件至少需包含：

```env
SECRET_KEY=你的随机密钥
```

## 开发

```bash
# 后端
cd backend
pip install -r requirements.txt
PYTHONPATH=backend uvicorn app.main:app --reload

# 前端
cd frontend
npm install
npm run dev
```

### 运行测试

```bash
# 后端
PYTHONPATH=backend pytest backend/tests -q

# 前端
cd frontend && npm test
```

## 许可证

MIT License。详见 [LICENSE](./LICENSE)。
