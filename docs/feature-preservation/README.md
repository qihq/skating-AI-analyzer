# Feature Preservation Ledger

Iteration 0 generates `ledger.json` from production routes, frontend API exports, ORM models, startup and scheduled work, environment settings, artifacts, packaging entrypoints, and focused tests at baseline commit `c291324`.

Regenerate only after a documented, owner-approved inventory change in M0-B or a later approved task. Do not run this command during the read-only M0-A audit:

```powershell
python scripts/generate_feature_preservation_ledger.py
```

The checked fingerprint makes unexplained removal of an inventoried production surface fail tests. Entries move only through:

```text
inventoried -> characterized -> adapted -> verified -> retirement-approved
```

`retirement-approved` requires explicit owner approval. Iteration 0 does not use that state.

## Characterization Index

The ledger points each surface to an existing focused test when a name-based match exists, or to an explicit test task in its owning iteration. The following cross-domain fixture groups protect the current product until their semantic inputs migrate:

| Domain | Current fixture groups | Owning migration |
|---|---|---:|
| Analysis lifecycle and media | `test_analysis_*`, `test_target_lock.py`, media frontend tests | 5-14 |
| Chat and corrections | `test_analysis_chat.py`, `test_analysis_corrections.py` | 5, 10-14 |
| Plans and sessions | `test_plan_generation.py`, plan page/hub tests | 5, 11-14 |
| Growth, compare, skills | `test_growth_*`, `test_analysis_compare.py`, `test_skills.py` | 5, 11-14 |
| Memories | Snowball router/service inventory and frontend route smoke; additional fixture task recorded | 5, 14 |
| Monthly and annual | `test_monthly_*`, `test_annual_*`, annual frontend tests | 5, 11-14 |
| Providers and settings | `test_provider_*`, settings/provider route inventory | 0, 5, 14-16 |
| Pose and tracking runtime | `test_person_tracker.py`, pose tests, pipeline tests | 0, 7-9 |
| Backup, restart, packaging | database/archive/provider startup/pack generation tests | 0, 15-17 |
| Historical routes and exports | navigation tests and artifact inventory | 0, 5, 14, 17 |
## 当前路线（2026-09-08，r2）

功能保留用于隔离产品迁移与算法验证风险，不阻止局部核心改进，也不把已有模块归零。保留上表旧 owner iteration，作为历史责任索引；不批量改成 M 编号。

当前入口：[路线图 r2](docs/superpowers/plans/2026-09-08-v2-v3-evolution-roadmap.md)、[实施计划 r2](docs/superpowers/plans/2026-09-08-v2-v3-development-implementation-plan.md)、实际进度。不调用任何 Superpowers skill。

| 新阶段 | 产品保护责任 |
|---|---|
| M0-A | 保护当前 tracked/untracked 内容；只读生成候选 ledger，解释每项差异，不刷新 checked ledger |
| M0-B | 确认基线与逐项迁移范围，授权后运行回归/处置 ledger，不混入已有未知变更 |
| M1-A / M1-B | 开发数据准入与正式 freeze 分开；保留家长权限、revision、隐私与历史数据 |
| M3-A | 提前明确比较规则与各 baseline 能力，缺预测/拒答不被隐藏 |
| M2 | 复用 D1/D2/D3 与核心模块，仅从源视频重算新结果；旧 bridge 仍是诊断证据 |
| M3-B | 按封存协议验证可替换字段，不以测试变绿或 tracked ratio 替代准确率 |
| M4 | 逐字段接入，验证报告/成长/训练/权限/导出不退化，保留 rollback；legacy retirement 另行批准 |

### 已知状态与 ledger 更新边界

revision 117、22 视频/24 事件、Pose 0、未针对该 revision 重评/未 freeze 是上一轮快照，本轮未刷新线上。当前审阅前的只读 ledger 比较为 checked 725、candidate 729、新增 4、删除 0、既有条目改变 0；这些不是自动批准更新 ledger 的理由。

M0-A 使用 [generate_ledger()](scripts/generate_feature_preservation_ledger.py) 的已有返回值接口，将结果写到私有 runtime 唯一目录。不要运行脚本主入口，它会覆盖 [checked ledger](docs/feature-preservation/ledger.json)。

差异必须逐项说明 ID、来源、生产/测试类别、owner、原因与处置。生产表面减少要单独审查；retirement-approved 保留显式 owner 批准。仅在 M0-B 或之后获准 inventory 变更时重生成，并跑 [feature-preservation 测试](backend/tests/analysis_v2/test_feature_preservation.py)。本次文档 review 不修改 ledger 本身。

本次替换的原文与 hash 见Review/归档记录。
