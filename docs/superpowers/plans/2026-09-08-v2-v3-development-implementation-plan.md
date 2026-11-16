# V2 算法核心与后续 V3 演进实施计划 r2

> **执行方式：**直接按本文任务清单执行，不调用任何 Superpowers skill。默认在当前任务内逐项审查与执行；本文件不授权创建子代理或新任务。历史存储目录名不代表 skill 调用许可。

**Goal:** 保护已完成进度，先建立可审计基线，再复用现有模块形成独立跳跃链路，以锁定协议的有限样本比较决定产品替换。

**Architecture:** M0-A 只读保护与选基线，M0-B 授权隔离运行；M1-A 提供开发数据准入，M3-A 先定义比较协议，M2 在开发/验证范围迭代。M1-B 正式 freeze 与 M3-B 预测封存/评分分别验收，M4 才接入产品。

**Tech Stack:** 仓库已有 Python/FastAPI/Pydantic/pytest、React/TypeScript/Vitest、V2 Golden store/evaluator、Windows PowerShell。版本以 M0-A 现场记录为准，不为执行本计划自动升级依赖。

## Global Constraints

- 计划制定于2026-09-08；2026-09-26最新入口（台账第46节）：I5合同与状态停止review接受最新partial停止记录，不接受独立诊断完成。原UTF-8交付已生成35目标/35 edge/F202诊断，但后续两次review先后因相对路径owner与漏计packet-manifest停止。最新确定P2：合同235应由补manifest恢复236，及partial checkpoint的next_action错误指向家长裁定；不改236为235，不改历史封存。原34/35目标、33/35双端仍是交付报告，尚未独立完整重算。本review独立核验四封存29/93/27/20、当前两树844/774、ledger725/734和原前后各236回执通过，不补称失败任务完成了未执行保护。下一唯一入口为合同与状态有界续接（未执行）：新工具完整构造→回执整集合→checkpoint分支合成通过后一次正式独立核验；通过才中性询问F200，未答等待，不自动改raw[1]/创建overlay。I3/I3.1/I4、图包和35条局部断言保留。当前保护使用[本review基线](<runtime-dir>/m2-2i5-contract-stop-review/20260926-112057-a540d855/continuation-baseline.json)：文档五改两增后主846/隔离774、documents25；历史236仍绑定原B的documents23及原manifest25，禁止混用。视频/CLI/validate-only/模型/网络/Git写全0；I4 CLI/I5解码累计均1/1、剩余0。diagnostic_only=true、family_usable=false、technical_conclusion/accuracy=null，不开放B2/Pose/UI/M4/V3。
- 本计划服从[路线图 r2](docs/superpowers/plans/2026-09-08-v2-v3-evolution-roadmap.md)，实际进度只在台账中更新。
- 不 reset/clean/stash/强行 checkout、不覆盖已有修改、不批量合并 accepted G1、不创建新 V3 目录。
- V1 产品、历史数据库、家长权限与已存在的 V2 有效实现保留；旧 iteration 状态不得清零或批量勾选。
- 家庭自用：本地开发可使用完整视频/标签/框/真实ID/hash/路径，报告无需脱敏。仅准备上传GitHub时检查待提交文件和待推送历史，排除不公开的家庭数据/秘密，需公开内容再脱敏，保留本地原件。凭据不无谓复制进报告；本规则替代历史任务中的本地脱敏前置。
- `golden-gate-policy.v2` 的 G1/G2/24–40 帧 Pose/子型样本规则不变；M1-A 的跳跃开发准入不等于 G2 freeze 通过。
- Golden 的 source/timebase 等必要元数据可按协议使用；被评估的标签、框、动作、边界、关键时刻和圈数不能进入新预测器。
- 当前身份 anchor 是 diagnostic-only，不能自动转为正式 tracking 输入；各 baseline 的人工辅助条件必须一致或分组报告。
- 资格由协议与 evaluator 决定，不新增手工“指标有效”开关；缺真值沿用实际 null/denominator=0/insufficient_sample 语义，不臆造 API 枚举。
- 失败、缺预测、wrong-person 和 refusal 必须计入适用结果台账，不能删掉后只算成功样本。
- 测试通过只证明对应工程契约；正式比较、freeze、上线、legacy 退役分别需要自己的证据和授权。

---

## 0. 先读哪些文档、认清哪些进度

按顺序阅读：Review 修订记录 → 进度台账 → G1 历史进度 → 本计划当前 Task。

主目录：`.`，review 时 HEAD 为 `cec9be9dbfeb416c600440f8da52edfd913bb940`，有未提交修改。accepted G1 工作树位于 `<runtime-dir>/iteration-3-g1-canonical-worktree`，accepted commit 为 `b0b9c08`。不要把这些身份和主 dirty patch 合写成一个版本。2026-09-09 已核实 D2/D3 测试与实现就在 cec9be9 HEAD，不需要重复迁移；另两项 untracked 测试及关联 dirty 实现仍保留原处。

Golden revision 117、22 视频/24 事件/21 场次、split 16/4/4、Pose 0、13 条 review、历史 409/1 和 80 测试均为上一轮快照，本次未线上刷新或重跑。D2/D3 后续历史证据见台账，不以早期 51/22 suite 代表全部最新进度。

## 1. M0-A：只读审计与基线决策包（任务定义保留；当前执行进度见台账）

### Task M0-A.1：保护现场，形成可恢复材料

**读取范围：**主 V2 工作树、其 Git 元数据、accepted G1 工作树和已有证据。V1 目录 `~\Documents\skating-analyzer` 仅在基线溯源确有需要时只读读取；不改变其运行状态。

**写入范围：**`<runtime-dir>/plan-m0-audit` 下新建唯一子目录（时间戳加随机 ID，create-new，禁止复用旧目录）；以及本 Task 的脱敏审计摘要/进度台账。runtime 内可能有家庭数据和密钥，先检查真实解析路径、是否为共享位置、已有访问边界；不扩大 ACL，不上传。

**Interfaces:** 输入是现场 Git/文件状态；输出为一份私有 snapshot manifest、内容副本、patch、异常清单，以及脱敏的完整性结论。它不是 RunManifest，也不声称保存全部忽略数据、外部数据库或模型大文件。

- [ ] 记录审计时间、根目录真实路径、HEAD、branch、所有相关 worktree 路径/HEAD/dirty 状态。先检查是否有正在改变工作树的进程迹象；不能停其他人的任务来掩盖并发。
- [ ] 使用 Git 原始字节输出保存 `git status --porcelain=v1 -z`、`git diff --cached --binary`、`git diff --binary`、`git ls-files --stage -z`、`git ls-files --others --exclude-standard -z`。通过 Python subprocess 的字节 stdout 写文件，不通过 PowerShell 文本重定向转换 binary patch。
- [ ] 对所有 staged/unstaged/renamed/deleted 路径与 untracked 路径建立条目，分别记录 index、工作区、HEAD 身份。保存当前内容副本，记录复制前、复制后原文件及副本 SHA-256；保存 Git index 原件和恢复所需 blob/commit 身份并验证对象可读。
- [ ] 记录删除条目的 tombstone、原路径、在 HEAD/index 的恢复来源；staged 新增后又 unstaged 删除等组合不能遗漏。路径由 NUL 格式解析，不按空格或逐行猜文件名。
- [ ] 遇 symlink/junction/reparse point，记录链接元数据，不递归跟随外部目标；遇单文件 >25 MiB，记录大小、hash/读取失败理由、是否复制、恢复来源，不擅自删除或静默忽略。
- [ ] 不全盘拷贝 ignored 的视频、数据库、缓存和 secrets；如果有必要保护但不在本范围内的 ignored 进度，单列扩展保护请求。私有快照本身也不能复制进 Git 文档目录。
- [ ] 采集后重读 Git 状态及所有被复制原文件 hash。文件变动、不可读、外部链接或未保护大文件均列为异常，不能用无限重试冒充一致快照。
- [ ] 核验 snapshot manifest 能逐条定位副本或明确恢复来源，检验副本 hash 和 patch 内容非空条件；验证仅在私有副本进行，不把 patch 应用回原工作树。

**Exit:** 保护范围内每个变更均可解释/恢复；未解决异常阻止 M0-B，但允许完成只读报告并请求用户决定。该 Task 不创建开发 worktree、不提交代码、不改原文件。

### Task M0-A.2：记录运行环境，不修环境

**读取：**解释器与可执行路径、已安装包元数据、声明依赖/锁文件、已存在模型和非敏感配置。

**输出：**同一私有审计目录中的 runtime inventory；仓库摘要只写版本、计数、缺失项及公开代码版本，不打印完整环境变量或私有配置内容。

- [ ] 保存 Python executable/version、Node/npm executable/version、OS、CPU/GPU/运行设备及线程相关已知配置。未检测到就记未确认，不调用未知会下载的工具。
- [ ] 使用已安装包元数据分别记录 numpy/FastAPI/Pydantic/推理框架实际版本与 requirements/lock 声明版本；不 import 会初始化模型、数据库或服务的业务入口。
- [ ] 记录现有模型文件名、大小和 SHA-256，无法读取或无权使用的模型列为阻塞；不下载模型、不执行推理。
- [ ] 记录 manifest/fingerprints/timebase 模块位置与现有接口；M0-A 不生成虚构预测 RunManifest。

**Exit:** 能解释“当前环境是什么”，而不是“已安装成推荐环境”。依赖问题只记录，后续修复必须进入批准的 M0-B 小任务。

### Task M0-A.3：只读解释 ledger 漂移

**读取：**[生成器](scripts/generate_feature_preservation_ledger.py)、[checked ledger](docs/feature-preservation/ledger.json)、[保护测试](backend/tests/analysis_v2/test_feature_preservation.py)。

**Interfaces:** 现有 `generate_ledger() -> dict[str, Any]` 返回候选；M0-A 仅将候选写私有审计目录。

- [ ] 先查看生成器 import/顶层行为，确认无写入副作用。用 importlib 从文件加载并调用 generate_ledger()，不得执行 `__main__`。
- [ ] 比较 checked/candidate 的条目 ID、字段与顶层 metadata，列出 added/removed/changed，而不是只比较总数。
- [ ] 上轮得到 checked 725、generated 729、新增 4、删除 0、既有条目改变 0；本次审计若不同，按真实差异报告，不把历史数字硬编码为预期。
- [ ] 每项差异记录来源、是否生产表面/测试表面、owner iteration 与拟处置；本轮不批量重写 owner 编号。
- [ ] 核验 checked ledger hash 不变。生成器已有只读函数，不为这个审计新加业务 CLI。

**Exit:** 差异有可复核解释和批准需求；测试仍可能因 drift 失败，不能靠直接覆盖 ledger 抹平。

### Task M0-A.4：输出选择建议并停止

**Create（脱敏报告）：**`docs\development\2026-09-08-m0-baseline-audit.md`（下一轮执行 M0-A 时创建；若当时已存在则另存新日期/运行 ID 文件，不覆盖）。

- [ ] 对比干净 `cec9be9`、accepted G1 `b0b9c08`、当前 dirty snapshot 的代码、环境可追溯性、D1/D2/D3 包含关系、回归风险和可比 mask。
- [ ] 给一个基于证据的推荐和至少一个替代方案。未完成映射前，不预先决定“整包 dirty 合入”或“回到 G1 清零重来”。
- [ ] 输出必须保留、需逐项迁移、仍待解释、暂不纳入四类修改清单，并列出影响。
- [ ] 报告命令、退出码、hash 核验摘要和范围缺口；完整 patch、源码副本及敏感摘要只留 runtime。
- [ ] 更新进度台账：完整审计后为 `m0_a_reviewed_waiting_owner_baseline`；存在保护缺口则记明确阻塞。二者都不是 M0-B 完成。
- [ ] 停止并问用户选择基线与允许纳入的修改。不连续运行测试、安装依赖、访问线上 Golden、freeze 或编码。

## 2. M0-B：用户批准后才运行基线

> 当前边界：fixture/ledger 有限工程子集已验收，见返工 review。以下为完整任务定义，不批量勾选；缺真实运行身份/完整适用回归不靠伪造模型或 stage hash 补齐，也不要求为只读准备重跑已通过的 fixture。

### Task M0-B.1：建立批准的开发工作目录和运行身份

**入口条件：**用户确认 baseline commit/snapshot、允许纳入的修改、工作目录和运行范围；M0-A 可恢复材料通过。新分支若获批准创建，默认使用 `codex/` 前缀，但不替用户发明长期 V3 分支。

**复用：**[RunManifest](backend/app/analysis_v2/manifest.py)、[fingerprints](backend/app/analysis_v2/fingerprints.py)、[manifest 测试](backend/tests/analysis_v2/test_fingerprints_manifest.py)。

- [ ] 在批准目录验证 HEAD 与 patch set；移植必须逐文件/逐模块审查，不批量覆盖当前主工作树或 accepted 原件。
- [ ] 复用 create/with_stage_hashes/persist/load，记录真实 source_identity、pipeline_fingerprint、stage_hashes；没有预测阶段就不伪造 stage hash。
- [ ] 环境/代码 patch digest、模型/config identity、device/threads、adapter/fallback/人工输入记录在私有 audit sidecar，并以 manifest 文件 hash 关联。不要无测试修改序列化协议。
- [ ] 若确需扩展现有接口，单独开契约小任务：先写 load/persist 兼容失败测试，再最小实现，保证旧 manifest 可读；该变更需独立 review。
- [ ] 运行第 7 节适用测试，记录真实退出码。已有环境不兼容则先提出最小环境修复方案，不自动安装。

**Exit:** 运行身份与实际工作目录一致，回归结果和异常清楚；不以代码 SHA 掩盖 dirty 内容。

### Task M0-B.2：批准后处置 ledger

- [ ] 先提交逐项解释供 owner 确认；生产表面删除、retirement-approved 与普通新增测试条目区分处理。
- [ ] 只有经批准的 inventory 变更才更新 [ledger.json](docs/feature-preservation/ledger.json)；生成器缺陷另加最小回归测试，不顺带重构。
- [ ] 跑 feature-preservation focused 测试，保留前后 ledger 及差异说明；无授权就保持 drift 可见并记录下一阶段是否受阻。
- [ ] 确认 patch scope、无其他人的变更混入后，才按授权提交可回滚小 commit；不使用 `git add .`。

## 3. M1-A：Golden 开发数据准入，不强制提前 freeze

**入口条件：**已确认基线与本任务权限。M0-A 不含线上访问权限；开始本任务时确认允许读取的实例、revision 与数据范围，不在文档保存登录凭据。

**复用：**[Golden router](backend/app/routers/golden_v2.py)、[g2_baseline](backend/app/analysis_v2/evaluation/g2_baseline.py)、[Golden runbook](docs/golden-eval-ab-runbook.md)。

- [x] 本地完整数据盘点与首批开发选择已验收，见review：r101/22源/24事件，22源媒体hash匹配，三候选均development。配置r1空库未初始化；不声称线上最新。
- [ ] 明确 source/recording session/grouping 的 split 隔离与重复片段关系；历史暴露区分标注、开发、验证、holdout，无法证实则记录 exposure_unknown。
- [ ] 正式比较前锁定适用集合与评价mask。家庭本地可保留完整标签作开发对照；禁止评分答案进入预测调用，不以“测试标签不能在本地目录”替代真正输入隔离。
- [ ] 对 review queue 和少框事件先写处置建议，确认/歧义/不可观察/不适用使用 UI/API 实际支持的状态；它们是审阅结论，不强造新 enum。
- [ ] 获准改标注时走现有 revision 审计，不硬编码结论。Pose 24–40 代表帧先制定分层抽样，再由有权限的 reviewer 标注；没有 Pose 真值不报告准确率。
- [ ] 审计 [identity_anchor](backend/app/analysis_v2/evaluation/identity_anchor.py)：只允许协议批准的单帧身份信息，不含事件 ID/类别/边界/关键时刻/圈数或整段 track。单帧框的选择时机也要审计，不能偷偷依赖事件时刻。
- [ ] 当前 diagnostic-only anchor 不能进入正式 tracking 评估：必须另行批准非测试真值来源的身份选择协议，排除初始化帧的同值自评分，并规定之后帧的独立评分；缺此条件就保持诊断用途。

**Exit:** 有可用开发范围、输入许可、暴露记录及指标缺口清单。步法测试覆盖不足阻止步法泛化结论，不阻止跳跃契约开发；G2 官方 freeze 门槛不放宽。

## 4. M3-A：先定义比较协议，再大量迭代

**交付：**在批准基线工作树内建立跳跃比较协议与私有 machine-readable 草案。当前已选 cec9be9 + 已验收 patch，本地准备已交付并经 review；协议/阈值仍未批准，不伪造已锁定状态或 runnable evaluator CLI。协议由实现者整理、owner 确认后锁定；未明确项阻断 M3-B，不通过默认值跳过。源码事实以已选隔离基线为准；下文原主目录源码链接仅用于导航，不代表其中 dirty 改动已获纳入。

### Task M3-A.1：能力矩阵与公平性

| 分支 | 可考虑的输入/结果 | 不得默认具备的能力 |
|---|---|---|
| V1 baseline | 可追溯的旧算法预测，旧格式先核验/显式 adapter | 不能把 V1 manifest 直接交给 V2 evaluator |
| accepted G1 / D1–D3 | 实际存在的 source-only/bridge 诊断与限定 mask | source-only 不是完整 tracking/pose baseline；stored bridge 不是新一次端到端推理 |
| 独立跳跃核心 | 源视频重算、合法身份输入、逐阶段 provenance | 不能读取 legacy 结果或 Golden 真值填空 |

- [ ] 逐指标记录 supported / diagnostic-only / 不可比较及原因；这些是协议表述，不新增后端枚举。
- [ ] 每个可比分支使用相同授权 source 范围、人工辅助预算、时间基准和资源条件；条件不同单独分组，不声称纯算法公平优势。
- [ ] adapter 仅做格式/坐标/时间转换，必须记录版本与转换损失；不能借真值补充缺失预测或在推理阶段读取 event ID。
- [ ] source-only recall envelope 和 localized interval 分列，整段视频命中不能冒充事件定位准确。

### Task M3-A.2：必须签定的计分定义

| 协议项 | 必须写清楚的内容 |
|---|---|
| 统计单位与 N | 独立 source、录制场次、event 各有多少；同场次相关性、重复片段及多次运行不增加独立 N |
| matching | source PTS 单位；候选/事件一对一还是现有 evaluator 规则；重复候选、重叠事件、tie-break、unmatched FP/FN；先核验当前实现，不把自定义 matcher 当现有能力 |
| 分母与异常 | 依据有真值且适用的固定集合；运行失败/缺预测/拒答为失败或覆盖缺口，不删样本；不适用来自预先声明的定义，不来自算法失败 |
| identity | 错人、切换、false relock、lost 的定义；bbox 坐标规范；IoU=交集面积/并集面积、退化框处理；anchor 初始化帧和后续评估帧分开 |
| pose | 可观察人工点分母、归一化尺度、missing/interpolated/wrong-person 处理；当前 evaluator 的 PCK 0.2 以同帧 GT bbox 最大边为尺度，缺同帧框会用 1.0，正式比较须预先批准此规则或先做统一 evaluator 修订 |
| action | proposal recall 与 localized recall、误报、分类准确率与确认覆盖分别报告；unknown/refusal 不能从适用 event 分母删除 |
| moments | source frame index 与 PTS；误差单位为秒、frame accuracy 单列；缺时间预测计入 coverage；仅 matched 子集的误差均值不能独立证明整体更好 |
| rotation | exact/range/refusal 分列，包含率/区间宽度/拒答率同时报告，统一身体转动与竞赛圈数约定；跳跃首轮可不申请 rotation 晋级 |
| 判定与退化 | 每项主要指标的绝对门槛、相对改善目标、分层允许退化上限、非劣要求、样本不足判定与 owner；不得继承旧 Phase 0 阈值当默认 |
| 资源与重复性 | 目标设备、运行时/内存上限、warm/cold 区分、重试次数、重复次数、浮点容差；明确哪些输出应字节一致，哪些允许数值容差 |
| 锁定信息 | 协议版本/hash、candidate commit+patch digest、配置/模型/环境 hash、批准者和时间、允许数据范围、re-run 规则 |

- [ ] 核验 [evaluate_pilot](backend/app/analysis_v2/evaluation/pilot_evaluator.py) 的实际匹配和 mask；对不支持的比较列出最小 adapter/evaluator 契约任务。
- [ ] 若要改 evaluator，先在 synthetic 或 development/validation 上写失败测试，完成统一版本后所有 baseline 同算；不得只给新内核换有利口径。
- [ ] development/validation 的协议探索与调参记版本；正式比较前候选、阈值、mask 与排除项全部锁定。若测试结果后反向改协议，保留旧结果并明确失去未见测试性质。

**Exit:** 开发协议与能力范围可执行；正式锁定前的未决项保持显式阻塞，不以“明显改善”作为通过标准。

## 5. M2：独立跳跃核心，按现有模块做最小任务

这一节是基线选择后的任务边界，不授权现在改代码。每个代码小任务在实际基线上先补失败测试和精确 patch 计划，再执行；不能提前虚构新类/函数要求整套重写。

### Task M2.1：输入隔离与编排

> 2026-09-11的synthetic、真实源/PTS与M2.2-A验收保持，完整M2.1编排仍未验收。R1–R3.2/R3-CLOSE/I1/I2/I3/I3.1已验范围保留；I4有限验收通过，CLI预算1/1已耗尽。I5本次已生成37源PNG与编号图，字段/预算问题关闭，因标签遮挡partial；下一只复用PNG修布局，视频解码预算1/1已耗尽，不读取视频。不是继续修I4或重写V3。

**复用/审查：**[contracts](backend/app/analysis_v2/contracts.py)、[timebase](backend/app/analysis_v2/timebase.py)、[shadow_pipeline](backend/app/analysis_v2/shadow_pipeline.py)、[orchestration](backend/app/analysis_v2/orchestration.py)。

- [ ] 建立最小输入契约测试：只有源视频/PTS/获准单帧身份输入可被消费；读取 legacy/Ground Truth 路径必须使测试失败。
- [ ] 测试外部缺依赖、缺输入、非单调 PTS 和缺失证据时明确失败/拒答，不用旧快照兜底。
- [ ] 复用现有结构与 RunManifest。只有现有编排无法隔离 legacy 输入时才批准新增薄入口；CLI 和服务调用共用同一实现。
- [ ] 定义 synthetic source fixture 和无真值 smoke 范围；完成输入依赖审计再运行实际视频。

### Task M2.2：重新检测、跟踪与 pose

> 2026-09-25（Asia/Shanghai）执行切片更新：I5视觉停止review接受本次partial停止及37张源PNG复用，旧编号图包仍不可供家长作答：37源图/37编号图/4总览/35空答案已生成，但packet_ready=false、可回答0。I5-REV-01保持关闭，I5-REV-02字段映射与I5-REV-03预算分类已关闭；新I5-REV-04/P2为标签碰撞，37/37帧存在正面积相交、共88对。I5视频解码累计1/1、剩余0；I4真实CLI累计1/1、剩余0，均不重跑。下一唯一入口为PNG-only布局续接（未执行）：只读复用封存37PNG，在新runtime先做密集/贴边合成、全部37帧独立布局检查及真实预览，再冻结并一次正式验收；禁止读取视频、解码、模型、CLI、validate-only和Git写操作。两树只读，不代家长认人，不开放B2/Pose/UI/M4/V3。I3/I3.1/I4已验进度保留。[本review final](<runtime-dir>/m2-2i5-visual-stop-review/20260925-b8571e94/final.json)及[续接基线](<runtime-dir>/m2-2i5-visual-stop-review/20260925-b8571e94/continuation-baseline.json)绑定文档更新后的after（主838/隔离774，ledger725/734）；不再使用旧836文档基线。
> B1.4历史61帧/377框、36可选/25锁住、5采样仅F166有raw Pose保持。I4实际35candidate＋1策略拒答与参考core严格5730节点一致，不等于36帧身份确认。I5已有37源PNG/37编号图/4总览/35空答案；旧图标签遮挡，不可作答。下一PNG-only修布局、复制源图原字节，新解码0。F202拒答，不复跑CLI/validate-only/旧套件，不接业务facts。

**复用：**[detection](backend/app/analysis_v2/detection.py)、[identity](backend/app/analysis_v2/identity.py)、[pose_v2](backend/app/analysis_v2/pose_v2.py)。

**已有测试：**[identity tracking](backend/tests/analysis_v2/test_identity_tracking.py)、[pose](backend/tests/analysis_v2/test_pose_v2.py)、[detection proposals](backend/tests/analysis_v2/test_detection_proposals.py)。

- [ ] 先测试遮挡、多人交叉、丢失重锁和 stale bbox 不得 confirmed；不得用人工真值 track 替代算法 track。
- [ ] 在实际选定基线上从源视频重算，复用低层实现而不是加载旧 target lock/pose frames。
- [ ] D1 pose-only bridge 的思想可经审计纳入，但保持 tracker 语义边界并验证开关关闭的基线复现；已有 bridge artifact 只作回归输入。
- [ ] pose 只消费合规身份轨迹；measured/smoothed/interpolated-display-only/missing 等遵循实际契约；插值展示不进入确定性技能/生物力学事实。
- [ ] 报告可用率、错人风险与真值缺口，不能以 tracked ratio 等同 Pose 准确率。

### Task M2.3：复用 D2/D3，形成局部动作与关键时刻

**复用：**[event_proposals](backend/app/analysis_v2/event_proposals.py)、[action_classification](backend/app/analysis_v2/action_classification.py)、[profile_moments](backend/app/analysis_v2/profile_moments.py)。

**已有测试：**[D2 diagnostic](backend/tests/analysis_v2/test_g1_d2_localized_proposal_diagnostic.py)、[classification](backend/tests/analysis_v2/test_action_classification.py)、[moments](backend/tests/analysis_v2/test_profile_moments.py)。

- [ ] 先核验 D2/D3 实际包含关系，保留 off-switch baseline 回归，不重新实现已存在的 source-only 规则。
- [ ] 测试同源多 proposal 独立分类、短脉冲拒答、弱证据/身份未确认不升级；unlocalized envelope 不生成伪确定关键时刻。
- [ ] 输出真实 source frame/PTS、有效局部区间、takeoff/landing 与拒答原因；不读取 Golden event window 缩小推理范围。
- [ ] 新的 downstream 调整与原 D3 切片分别记录；D3 的 confirmed 3→5 不得写成准确率提升。
- [ ] 首轮不以精确圈数为目标；range/refusal 保留，不用 LLM 或 legacy 数值填空。

### Task M2.4：开发/验证闭环

- [ ] 对已批准 source 范围运行各阶段，记录参数版本、结果 provenance、失败和资源开销；先保存预测再评分。
- [ ] 开发/验证集可迭代，但每轮固定比较口径并保留结果；禁止选择性隐藏退化。
- [ ] 按 M3-A 重复性规则重跑，差异分为输入/模型/环境/浮点/算法，不用“基本一致”代替容差。
- [ ] 保存候选及未通过指标；需要扩大范围先改协议和批准范围，不直接打开 frozen_test 调参。

**Exit:** 真实独立链路与开发/验证证据成立；正式 gate、frozen holdout 和产品上线仍未通过。

## 6. M1-B → M3-B → M4：分别验收，不能一键跨阶段

### M1-B：正式 freeze

- [ ] owner 明确批准实际 revision、完整 snapshot fingerprint、membership、policy、legacy pipeline fingerprint 与数据范围；readiness 不等于批准。
- [ ] 按 [G2BaselineStore](backend/app/analysis_v2/evaluation/g2_baseline.py) 当前规则 freeze；缺 G2 profile/分组等条件则保持阻塞，不改政策绕过。
- [ ] 核验 freeze artifact 与批准内容一致。assert_compatible 只验证 membership 不够，还要检查完整标签 snapshot/approved revision。
- [ ] 不删除既有 freeze 重新跑；变更必须走显式授权的新 revision/数据集流程。

### M3-B：预测封存与正式有限样本比较

- [ ] 候选与协议已锁定；holdout 历史暴露有结论。标注人员接触视频不自动等于污染，但用于调参/选候选的测试样本不能再当相同开发流程的未见测试。
- [ ] 对所有分支保存完整预测与失败台账、manifest 和 digest，再让 evaluator 读取批准的真值；标注/比较与预测器输入分离。
- [ ] freeze、legacy baseline record、candidate prediction seal、evaluator result 是四个独立产物，分别记录 ID/hash/时间。
- [ ] V2 通过 evaluate_pilot(dataset, bundle)、pilot_store 和对应 router 的真实契约评估；现有 source diagnostic dry-run 只保留原 mask/诊断范围，不是正式通用三路 runner。
- [ ] 缺预测/拒答保留适用分母；无真值返回实际空指标语义；真实样本不足保持 insufficient_sample，不宣称零误差。
- [ ] 同一锁定候选技术复跑允许查稳定性，但不增加 N。看测试结果再改模型/参数/协议，记录新的开发暴露与验证需求。
- [ ] 按锁定阈值与分层退化规则写晋级或不晋级结论；有限样本通过不扩大为泛化/发布宣称。

### M4：产品接入与可回滚扩展

- [ ] 先在 [presentation](backend/app/analysis_v2/presentation.py) / [fact_consumers](backend/app/analysis_v2/fact_consumers.py) 的实际消费边界确定最小接入范围，不现在重构所有页面。
- [ ] 仅接入获准字段，保留旧结果读取、版本区分和 rollback 开关；演练回滚后再申请上线。
- [ ] 对上传、档案、权限、报告、训练、成长、导出跑功能保护回归；不确定字段不写确定结论。
- [ ] 跳跃之后再分别批准旋转、步法、燕式；每类重复数据准入、协议与验证。legacy 退役和产品命名 V3 都是单独决策。

## 7. 验证命令与工作目录

### 本轮文档 review / 后续 M0-A

只使用 Git/文件/包元数据只读检查和私有快照，不运行下方业务 suite、模型或 evaluator。本轮文档检查从主目录执行：

```powershell
Set-Location '.'
git status --short
git diff --check -- docs
```

### M0-B 及已批准代码小任务

以下代码块**只能在用户已选定的开发工作树根目录**运行。先核对 Get-Location、HEAD 与 M0-A 决策记录；如果选的是隔离工作树，就不能在主 dirty 目录执行。Python 必须是 M0-A 记录并在 M0-B 批准的解释器。

```powershell
Get-Location
git rev-parse HEAD
git status --short
(Get-Command python -ErrorAction Stop).Source
python -m pytest backend/tests/analysis_v2/test_feature_preservation.py -q
# 记录退出码后再决定是否继续；失败不是安装/覆盖 ledger 的授权。
```

后端专项：

```powershell
python -m pytest backend/tests/analysis_v2 -q
```

前端从批准工作树的 frontend 子目录运行，不在仓库根直接 npm、不使用可能下载包的 npx：

```powershell
Push-Location (Join-Path (Get-Location).Path 'frontend')
try {
    if (!(Test-Path -LiteralPath '.\node_modules\.bin\vitest.cmd')) { throw '本地 Vitest 缺失：记录阻塞，不安装依赖' }
    if (!(Test-Path -LiteralPath '.\node_modules\.bin\tsc.cmd')) { throw '本地 TypeScript 缺失：记录阻塞，不安装依赖' }
    npm.cmd test -- --reporter=dot src/analysis-v2
    if ($LASTEXITCODE -ne 0) { throw "前端测试失败：$LASTEXITCODE" }
    .\node_modules\.bin\tsc.cmd --noEmit
    if ($LASTEXITCODE -ne 0) { throw "TypeScript 失败：$LASTEXITCODE" }
} finally {
    Pop-Location
}
```

当前主目录对应的前端 package 绝对路径是 `frontend\package.json`，但这不指定最终批准的运行工作树。

**不要执行通用 evaluator 占位命令。** [eval_against_gt.py](backend/scripts/eval_against_gt.py) 与 [diff_baselines.py](backend/scripts/diff_baselines.py) 仅适用于其旧格式；正式 V2 invocation 在 M3-A 根据真实 bundle/store/权限确定并记录完整命令及格式测试。

## 8. 每个后续代码小任务的固定闭环

1. 确认批准 baseline 与独立文件写入范围，先读该范围的当前改动。
2. 针对一个契约写失败测试；运行并确认是正确的失败原因，不是依赖/路径错误。
3. 最小实现，不顺手改其他层；再跑 focused tests 和相邻模块回归。
4. 运行批准的 smoke/评估范围，记录命令、退出码、manifest、适用分母、失败/未测项与资源。
5. review diff，确认无真值输入、无隐式 legacy fallback、无秘密或私有证据进入 Git。
6. 经批准后以独立文件列表提交可回滚 commit；不混入他人的已有修改，不自动推送。
7. 更新台账的具体 Task 与证据，不根据计划顺序自动勾选后续 gate。

## 9. 启动与改计划规则

既有M0/准备/主体实现/边界修补、本地盘点、真实源输入、家长锚点及有界候选/Pose诊断均保留。家庭本地不脱敏；I3.1/I4已review通过，不重复修I4 timestamp/ledger/核验工具。I5-REV-01/02/03关闭；下一只修I5-REV-04编号标签遮挡，准备期允许四份固定JSON与37白名单PNG只读联调/预览，全部37帧独立布局检查通过再冻结，正式预检/成品一次失败即停。F166不重复问，F167–F201新确认仍未发生；始终零视频读取/解码，不进入后续阶段。

旧 Task 1.1–1.3 归入 M0-A/M0-B；旧 Task 2.1–2.4 分为 M1-A/M1-B；原 M3 比较任务拆成开发前协议与候选后正式比较。旧文件原样归档与完整变更原因见 Review。不得删除历史证据，也不得把本次重排解释为 D2/D3 已失效。

当前入口：I5视觉停止review接受本次partial停止及37张源PNG复用，旧编号图包仍不可供家长作答：37源图/37编号图/4总览/35空答案已生成，但packet_ready=false、可回答0。I5-REV-01保持关闭，I5-REV-02字段映射与I5-REV-03预算分类已关闭；新I5-REV-04/P2为标签碰撞，37/37帧存在正面积相交、共88对。I5视频解码累计1/1、剩余0；I4真实CLI累计1/1、剩余0，均不重跑。下一唯一入口为PNG-only布局续接（未执行）：只读复用封存37PNG，在新runtime先做密集/贴边合成、全部37帧独立布局检查及真实预览，再冻结并一次正式验收；禁止读取视频、解码、模型、CLI、validate-only和Git写操作。两树只读，不代家长认人，不开放B2/Pose/UI/M4/V3。I3/I3.1/I4已验进度保留。[本review final](<runtime-dir>/m2-2i5-visual-stop-review/20260925-b8571e94/final.json)及[续接基线](<runtime-dir>/m2-2i5-visual-stop-review/20260925-b8571e94/continuation-baseline.json)绑定文档更新后的after（主838/隔离774，ledger725/734）；不再使用旧836文档基线。
