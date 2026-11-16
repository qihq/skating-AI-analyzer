# Skating Analyzer — V2

[English](./README.md) | **中文**

一个以证据为先的花样滑冰分析管线，基于 FastAPI、React、MediaPipe、YOLO/ByteTrack 和 Docker 构建。
V2 **与稳定的 `v5.2.x` 管线并行运行**：legacy 管线仍是产品对外权威，V2 在同一仓库内构建自己的、
可重建、带版本号的证据产物，并与冻结的评测基线做对照。

[贡献指南](./CONTRIBUTING.md) | [许可证](./LICENSE) | [群晖部署指南](./SYNOLOGY_STEP_BY_STEP.md) | [Golden A/B 运行手册](./docs/golden-eval-ab-runbook.md)

---

## 这个分支是什么

`v2` 分支包含 V2 分析管线及其工具链。它**不替代** `v5.2.x` 产品管线——两者位于同一仓库，
共用同一套数据库、模型和 Docker 打包方式。

| | Legacy（`v5.2.x`） | V2 |
|---|---|---|
| 对外权威 | 是——所有用户可见的报告 | 否——`public_authority = "legacy"` |
| 写入用户数据 | 是 | 否——`writes_user_data = false` |
| 产出 | 报告、计划、档案 | 隔离运行时下的带版本 JSON 产物 |
| 运行时 | 常规应用运行时 | 隔离 shadow 运行时，有界本地队列 |
| 目的 | 已交付产品 | 可被证据门禁约束、可度量的管线 |

切换管线是配置变更，而不是分叉：

```env
SKATING_ANALYSIS_PIPELINE=legacy   # legacy | shadow | v2
```

## 设计原则

以下原则在代码中强制执行，不只是文档约定。

- **阶段顺序即契约。** 一个阶段只能消费位于其左侧阶段的产物。任一阶段失效，其所有下游阶段
  随之失效，因此陈旧缓存无法悄悄喂给下游结论。
- **不就地修改。** 已完成的 legacy 分析作为**不可变输入**传入 shadow 运行。一次 shadow 运行
  就是一个可重建、带版本号的 JSON 产物。
- **结论之前先有证据。** 报告只被允许解释已经融合好的 claim；无法引用其输入证据的 claim
  不允许被打印出来。
- **拒绝是合法结果。** 旋转、身份和关键时刻估计器在证据不足时返回显式拒绝或不足标记，
  而不是一个没有限定的数字。
- **失败即关闭。** 试用门禁、运行时预检和污染哨兵在前置条件不满足时默认拒绝。

## 分析管线

阶段顺序在 `SHADOW_STAGE_ORDER` 中只定义一次，且属于契约：

```
timebase → observations → candidates → identity → pose → events → moments → rotation → path_reviews → claims
```

| 阶段 | 确立什么 | 主要模块 |
|---|---|---|
| `timebase` | 请求时间、解码帧与媒体之间精确的源 PTS 映射 | `timebase.py` |
| `observations` | 有界解码观测流，保留空洞与不连续点 | `detection.py`、`pose_observations.py` |
| `candidates` | 带资格判定与排除规则的人物跟踪候选 | `detection.py`、`tracking_states.py` |
| `identity` | 身份时间线、冲突区间、人工锚点与分段重锚 | `identity.py`、`evaluation/identity_anchor.py`、`services/segment_reanchor.py` |
| `pose` | 经身份授权的姿态样本，含逐点质量 | `pose_v2.py`、`services/pose_quality.py`、`services/pose_geometry.py` |
| `events` | 按 profile 划分的事件提案与带修订的动作标签事实 | `event_proposals.py`、`event_label_facts.py`、`action_classification.py` |
| `moments` | 带修订、事件作用域的起跳 / 腾空 / 落冰提案 | `profile_moments.py`、`moment_selectors.py`、`event_moment_facts.py` |
| `rotation` | 基于精确源 PTS 的保守多线索投影转体估计 | `rotation.py`、`rotation_facts.py`、`services/jump_rotation.py` |
| `path_reviews` | 对 legacy 视觉载荷的有界语义复核适配层 | `path_review.py`、`fusion_inputs.py` |
| `claims` | 确定性 claim 融合，以及解释这些 claim 的报告边界 | `claim_fusion.py`、`claim_report.py`、`facts.py` |

`claims` 之后的一切——呈现层与分析体验——都是消费者而非生产者：
`presentation.py`、`fact_consumers.py`、`comparison.py`。

### 分析体验（`analysis-experience.v2`）

V2 面向用户的产物是结构化的、带版本号的载荷，而不是自由文本：包含摘要、分区正文、
"更多"区域和报告视图。它由 `GET /api/analysis/{analysis_id}/experience-v2` 提供，
由 `frontend/src/analysis-v2/` 下的组件渲染。能力发现接口会声明某个部署支持哪些体验，
因此界面会优雅降级，而不是靠猜测。

## 仓库结构

```
backend/app/analysis_v2/     V2 管线：契约、阶段、编排、呈现
backend/app/analysis_v2/evaluation/
                             golden 存储、门禁策略、G2/G8/G9 评测器、适配层
backend/app/services/        共享服务，含 V2 跟踪 / 姿态 / 跳跃辅助模块
backend/app/trial.py         失败即关闭的试用门禁（见"试用模式"）
backend/app/routers/         analysis_v2.py、segment_reanchor.py 及 legacy 路由
frontend/src/analysis-v2/    分析体验、golden 工作台、shadow 工作台
frontend/src/components/     V2 面板：跳跃阶段回放、旋转、分段重锚、试用
docker/allinone/             all-in-one 镜像（标准、analysis、trial）
docs/                        架构说明、评测手册、计划与设计
scripts/                     发布、校验与模型溯源工具
```

## API 概览

V2 路由挂载在三个前缀下：`/api/analysis`（分析体验与带修订的事实）、
`/api/shadow`（shadow 编排运行）、`/api/golden/v2`（golden 评测）。
运行时能力由 `/api/capabilities` 报告。

下表所有路由均位于 `/api/analysis` 之下。

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/{analysis_id}/experience-v2` | 带版本号的分析体验载荷 |
| GET | `/{analysis_id}/experience-v2/diagnostic` | 同一体验的诊断视图 |
| POST | `/growth-admission` | 判定一次分析能否进入成长记录 |
| GET | `/{analysis_id}/event-proposals` | 按 profile 划分的事件提案 |
| POST | `/{analysis_id}/event-proposals/mutate` | 修订事件提案 |
| GET/POST | `/{analysis_id}/events/{event_id}/label-facts` | 读取 / 提出动作标签事实 |
| POST | `/{analysis_id}/events/{event_id}/label-facts/{revision}/apply` | 应用某个标签修订 |
| POST | `/{analysis_id}/events/{event_id}/label-facts/{revision}/dismiss` | 驳回某个标签修订 |
| GET/POST | `/{analysis_id}/events/{event_id}/moment-proposals` | 读取 / 提出 T/A/L 关键时刻 |
| POST | `/{analysis_id}/events/{event_id}/moment-proposals/{revision}/apply` | 应用某个关键时刻修订 |
| POST | `/{analysis_id}/events/{event_id}/moment-proposals/{revision}/dismiss` | 驳回某个关键时刻修订 |
| GET | `/{analysis_id}/source-frames/{index}/image` | 与某个观测绑定的源帧图像 |
| GET | `/{analysis_id}/observations` | 解码观测流 |
| GET | `/{analysis_id}/identity` | 身份时间线与冲突区间 |
| GET | `/{analysis_id}/pose-v2/detail` | 带质量元数据的姿态样本 |
| POST | `/{analysis_id}/identity/anchors/preview` | 预览人工身份锚点 |
| POST | `/{analysis_id}/identity/anchors/confirm` | 确认人工身份锚点 |
| GET | `/pilot12-detection`、`/pilot12-event-proposals`、`/pilot14-action-classification` | 冻结的 pilot 评测输入 |

人工分段重锚嵌套在同一前缀下：

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/{analysis_id}/identity/segments` | 基于已保存证据的分段候选 |
| GET | `/{analysis_id}/identity/segments/images/{observation_index}` | 候选图像 |
| POST | `/{analysis_id}/identity/segments/preview` | 预览重锚后的分段 |
| POST | `/{analysis_id}/identity/segments/confirm` | 确认重锚后的分段 |
| GET | `/{analysis_id}/identity/segments/revisions/{revision}` | 读取已保存的修订 |
| GET | `/{analysis_id}/identity/segments/revisions/{revision}/pose` | 该修订的姿态 |
| GET | `/{analysis_id}/identity/segments/revisions/{revision}/images/{filename}` | 该修订的图像 |

重锚**只使用已保存证据**。它不会重跑检测器、不会恢复已删除媒体，也不会凭空生成已保存观测
无法支撑的分段。

Shadow 编排运行位于 `/api/shadow`，golden 存储、评测器状态与 G2 基线位于 `/api/golden/v2`。

## Golden 评测

V2 只有可度量才有意义，因此评测是一等子系统，而不是测试夹具。

- **冻结的 golden 存储**（`evaluation/golden_store.py`、`golden_schema.py`）——带版本号的
  标注样本，含源媒体身份与内容哈希。
- **门禁策略**（`evaluation/gate_policy.py`）——`golden-gate-policy.v2` 定义候选必须通过的
  阈值与容差。策略带版本号，因此任何结果都能追溯到判定它的那份策略。
- **指标族**——`g2_baseline.py`（基线回归）、`g8_moments.py`（防泄漏的关键时刻聚合）、
  `g9_rotation.py`（约定安全、能识别拒绝的旋转评分）。
- **Pilot 评测器**（`evaluation/pilot_evaluator.py`）配合适配层，仅从源观测构建提案，
  因此评测器看不到已解出的标注。

工作流见 [docs/golden-eval-ab-runbook.md](./docs/golden-eval-ab-runbook.md)。

## 试用模式

`backend/app/trial.py` 为隔离试用部署实现失败即关闭的门禁。profile 可以被烘焙进镜像
（`/etc/skating-trial-profile`），从而无法在运行时用环境变量改动：

| Profile | 行为 |
|---|---|
| `off` | 常规安装；全部功能可用 |
| `web-preview` | 只读预览；禁止上传视频与分析 |
| `legacy-analysis-preview` | 仅既有 legacy 本地分析；新诊断、shadow、受控评测和外部 AI 全部关闭 |

`docker/allinone/Dockerfile.trial` 用固定且带哈希锁的依赖
（`requirements-trial-web.lock`、`requirements-trial-analysis.lock`）构建试用镜像，
因此试用安装不会悄悄解析到不同的依赖版本。

试用部署在其能力载荷中报告 `target_nas_verified=false` 与 `new_diagnostics=false`，
直到有人在目标硬件上真正验证过。系统不会因为一次构建成功就推断验证已通过。

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

`.env` 至少需要：

```env
SECRET_KEY=your-random-secret
```

完整变量见 [.env.example](./.env.example)；隔离 V2 开发布局见
[.env.v2.example](./.env.v2.example)。切勿把 V2 的路径指向生产数据。

群晖分步部署见 [SYNOLOGY_STEP_BY_STEP.md](./SYNOLOGY_STEP_BY_STEP.md)。

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

若要隔离运行 V2，把 `.env.v2.example` 复制为 `.env.v2.local`，将所有路径指向独立的运行时
目录，并设置 `SKATING_ANALYSIS_PIPELINE=shadow`。

## 测试

```bash
# 后端——192 个测试模块，其中 55 个位于 tests/analysis_v2/
cd backend
pip install -r requirements-test.txt
python -m pytest tests -q -n 4 --dist loadfile

# 前端——76 个测试模块（Vitest）
cd frontend
npm test
```

## 隐私与数据处理

- 上传的视频、抽帧图片、数据库和备份都属于运行时数据，永不提交。`.gitignore` 排除
  `data/`、`backups/`、`models/`、`deliverables/`、`*.pt` 以及镜像归档。
- API 密钥加密存储，且不会完整写入日志。
- V2 shadow 运行只写入自己的隔离运行时目录。污染哨兵（`contamination_inventory.py`）
  在运行前后对家庭状态做快照，从而**检测**到意外写入，而不是假定它不存在。
- 本仓库不包含家庭媒体、真实训练视频或任何个人数据。

## 许可证

MIT License——见 [LICENSE](./LICENSE)。

可选的动森风格界面参考并适配自
[guokaigdg/animal-island-ui](https:/github.com/guokaigdg/animal-island-ui)，
原仓库使用 CC BY-NC 4.0 许可证；本适配仅供个人非商业使用，并保留原作者署名。
