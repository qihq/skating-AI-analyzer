# Skating Analyzer：V2 续建与 V3 演进路线（当前主计划 r2）

> 2026-09-08 文档复核修订。沿用已确认的“不做全量 V3 重写”方向；本次修订不等于代码、数据、freeze 或上线授权。
> 执行限制：不调用任何 Superpowers skill；直接按文档执行，旧文档中的 skill 调用建议不适用。
> 当前进度以台账第46节为准：I5合同与状态停止review接受最新partial停止记录，不接受独立诊断完成。原UTF-8交付已生成35目标/35 edge/F202诊断，但后续两次review先后因相对路径owner与漏计packet-manifest停止。最新确定P2：合同235应由补manifest恢复236，及partial checkpoint的next_action错误指向家长裁定；不改236为235，不改历史封存。原34/35目标、33/35双端仍是交付报告，尚未独立完整重算。本review独立核验四封存29/93/27/20、当前两树844/774、ledger725/734和原前后各236回执通过，不补称失败任务完成了未执行保护。下一唯一入口为合同与状态有界续接（未执行）：新工具完整构造→回执整集合→checkpoint分支合成通过后一次正式独立核验；通过才中性询问F200，未答等待，不自动改raw[1]/创建overlay。I3/I3.1/I4、图包和35条局部断言保留。当前保护使用[本review基线](<runtime-dir>/m2-2i5-contract-stop-review/20260926-112057-a540d855/continuation-baseline.json)：文档五改两增后主846/隔离774、documents25；历史236仍绑定原B的documents23及原manifest25，禁止混用。视频/CLI/validate-only/模型/网络/Git写全0；I4 CLI/I5解码累计均1/1、剩余0。diagnostic_only=true、family_usable=false、technical_conclusion/accuracy=null，不开放B2/Pose/UI/M4/V3。
> 家庭自用政策（2026-09-10用户修订）：本地完整数据/报告不要求脱敏；准备上传GitHub时再排除或脱敏私人内容。此条替代历史本地脱敏前置，预测输入与GT评分答案仍分开。

## 1. 决策与边界

保留 V1 产品、历史数据和用户体验；保留 V2 Golden、PTS、revision、provenance、评估契约及有效代码。局部改造能从源视频重新推理的算法链路，先闭环跳跃，再逐步扩展。发布可以命名为 V3，但不另起目录重写整套产品。

现在要解决的是**基线不清、预测来源混用、诊断与正式评估混淆**，不是缺一套新模块命名。

- V1 上传、播放器、档案、家长权限、报告、训练计划、成长与导出默认保留。
- Legacy 仅作独立记录的比较对象，不作为新内核预测或真值来源。
- 不以测试通过、拒答减少、tracked ratio 增加或样本数量达标代替准确率证据。
- 不用当前有限样本训练或宣称可泛化的大模型，不为版本号增加产品迁移工作。

## 2. 证据分层：保留进度，但不冒充本轮新结果

| 项目 | 已知证据 | 本轮的正确解释 |
|---|---|---|
| V2 主工作树 | HEAD `cec9be9dbfeb416c600440f8da52edfd913bb940`，存在 tracked/untracked 修改 | 本轮已读本地状态；dirty 内容不能冒充干净 commit |
| accepted G1 | 独立工作树 accepted commit `b0b9c08`，历史 focused 83 passed | 历史代码/验收证据，不是当前工作树或当前 Golden 的重跑结果 |
| D1 / D2 / D3 | 旧进度文档记录 pose-only bridge、局部 proposal、统一分类确认 | 保留并审计后复用；不清零，不整体合并 |
| D2 v1.20.0 | 历史记录 localized proposals 10→15，focused 65 passed | source-only 诊断，不是全量事件召回已通过 |
| D3 v1.21.0 | 历史记录 confirmed 3→5、ambiguous 12→10，focused 91 passed | 分类确认状态改善，不是 Golden 分类准确率证明 |
| Golden revision 117 | 上一轮快照：22 视频、24 事件、21 场次；event split 16/4/4 | 本轮未访问线上；M1-A 经授权刷新后以实际 revision 为准 |
| Golden 质量状态 | 上一轮：Pose 人工真值 0；13 条 review 提示；5 个事件跟踪框少于 3；步法仅在 development | 指标缺口，不把历史计数写成当前在线状态 |
| freeze / evaluator | 上一轮：ready_for_evaluator / ready_to_freeze，未完成针对该 revision 的重跑，实际未 freeze | readiness、执行、通过和冻结是四个不同事实 |
| 测试 / ledger | 上轮专项 409 passed / 1 failed，前端 80 passed、TS 通过；ledger 725/729 | 不是本轮新测；只读生成差异为新增 4 项、无删除、无既有条目改变，M0-A 仍需正式解释 |

accepted 工作树：`<runtime-dir>/iteration-3-g1-canonical-worktree`。

封存证据：`<runtime-dir>/iteration-3-g1-canonicalization-20260828`。

完整历史进度：G1 completion progress。其中包含早期 51/22 测试与后续 D1/D2/D3 证据，不能只取早期数字判断最新进度。历史 D1 记录曾有 frozen-test verification；须审计暴露范围，不能宣称整套测试集从未被看过。

## 3. r2 执行顺序

```text
M0-A 只读审计、私有内容快照、基线选项
  → 停止，用户选择基线及允许纳入的修改
M0-B 授权后的隔离运行、回归、运行身份与 ledger 处置
  → M1-A 开发数据准入 + M3-A 比较协议定义
  → M2 先在 development/validation 上完成独立跳跃链路
  → 候选及协议锁定 + M1-B owner 批准正式数据 freeze
  → M3-B 封存预测、正式评分、有限样本替换决策
  → M4 经授权接入产品
```

M1-B 的数据治理准备可与 M2 开发并行推进；这里“并行”是阶段关系，不是授权创建代理、任务或后台运行。**M2 的开发契约不必等待完整 G2 freeze。** 如果 G2 类别配额、步法覆盖或 Pose 真值不足，则对应正式 gate/质量结论仍受阻，不能降门槛或绕过 freeze。

### M0-A：只读保护现场（已执行；保留阶段定义）

- [ ] 在私有 runtime 新建唯一审计目录，保存 staged/unstaged 二进制补丁、变更内容、untracked 内容及 SHA-256，不只保存文件名。
- [ ] 保存 HEAD、branch、worktree、Git 原始状态与 index 状态；记录删除文件、恢复来源、链接、超大文件和采集期间变动。
- [ ] 只读比较当前 dirty、干净 HEAD、accepted G1 的代码及 D2/D3 证据关系。
- [ ] 记录现有解释器、声明/实际依赖、模型元数据与 hash；不安装、升级或下载。
- [ ] 导入现有 ledger 生成函数并写私有候选，逐项解释差异；不覆盖 checked ledger。
- [ ] 给出推荐基线与替代方案，写脱敏审计结论后停下。

**退出条件：**可恢复性验证通过，或明确列出不可恢复项并阻止 M0-B；用户作出基线选择。审计完成不等于运行基线已建立。

### M0-B：建立可运行、可追溯的基线

- [ ] 只在已批准的基线/工作目录/修改白名单上运行；单独保留 accepted G1 原件。
- [ ] 复用现有 RunManifest；环境、dirty patch digest 与 adapter/fallback 审计写关联 sidecar，不重复造 manifest 核心类。
- [ ] 运行专项回归，说明 ledger 差异并经确认更新；记录真实失败，不自动修依赖。
- [ ] 明确现有 G1 能评估的 mask，不把 source-only 诊断包装成完整第三套 baseline。

**退出条件：**代码、环境、模型、配置、输入的身份可解释；回归结果和阻塞项均有证据。全预测稳定性在 M2/M3 再验证，不写成 M0-A 的完成条件。

### M1-A：开发数据准入

- [ ] 直接复用现有本地Golden完整数据，记录实际revision、计数、split、review和既有evaluator状态；本地报告无需脱敏，GitHub上传前再做发布检查。线上刷新和触发评估按具体任务执行，不默认包含。
- [ ] 按 source / recording session / grouping 检查开发和验证数据及历史暴露。
- [ ] review queue 保留歧义和不可观察事实；修改标注另行授权并走新 revision。
- [ ] 24–40 帧 Pose 是现有政策的标注范围，不是未标完便禁止所有跳跃契约开发。
- [ ] 单帧身份 anchor 先做输入许可与公平性审计；当前 diagnostic-only anchor 不自动升级为正式输入。

**退出条件：**开发可用范围、禁用范围、指标分母缺口和暴露状态清楚；禁止访问未批准测试标签。

### M3-A：提前定义比较协议

在大规模实现/调参前写明 source/session/event 单位、matching、mask、分母、缺预测/错人/拒答处理、指标公式、阈值、资源上限与容差。开发中修改协议需版本记录；正式候选比较前 owner 锁定协议与候选。

**退出条件：**没有“明显改善”这种无阈值验收项；正式评分前所有适用阈值、允许退化上限与适用范围均已明确批准。未定项必须阻断正式比较，不能自动补默认通过值。

### M2：复用已有模块构建独立跳跃核心

`source video + source PTS + 经协议批准的单帧身份输入 → 重新检测/跟踪 → 有效 pose → 局部动作区间 → takeoff/landing → 带来源的结构化结果`

- [ ] 复用现有 contracts、manifest、fingerprints、timebase、detection、identity、pose、proposal、classification 和 profile moments；先隔离输入来源，再谈拆文件。
- [ ] 保留 D1/D2/D3 作为候选代码与诊断证据，逐项纳入并验证开关关闭时的基线一致性。
- [ ] 不读取 legacy result/target lock/pose frames、Golden 框/动作标签或 fallback bbox 充当新结果。
- [ ] 可以复用低层算法实现，但必须从源视频重新推理；读取历史 observation bridge 只算诊断/回归。
- [ ] 保留各模块真实状态契约，不合并成臆造的通用枚举；拒答不会自动转成成功。

**退出条件：**开发/验证范围内有独立来源证据、重复性和逐阶段回归；尚不代表正式 gate 或产品发布通过。

### M1-B 与 M3-B：freeze、预测封存和评分分别验收

- [ ] owner 明确批准 dataset revision、完整 snapshot fingerprint、split、policy、legacy pipeline fingerprint 后才 freeze。
- [ ] 检查完整标签 snapshot，而不只核验 frozen membership；不得删 freeze 文件强行重冻。
- [ ] 锁定候选与协议，从批准输入运行并封存完整预测（含失败、缺预测和拒答），再由 evaluator 读取适用测试真值。
- [ ] 按能力分别报告 V1、accepted G1、独立内核；无真实 tracking/pose 预测的分支不可比较这些指标。
- [ ] 报告适用 N、分层表现、误差、覆盖率、错人、拒答、资源与退化；没有通过已批准门槛，不替换生产。

development/validation 可调参并记录版本。frozen_test 用于调参或候选选择后，不再是该开发流程的未见 holdout；同一候选的技术复跑不增加独立 N。标注者看视频不等于调参污染；历史无法证实时记录 `exposure_unknown`（审计值，不新增 API 枚举）。

### M4：接入与扩展

仅将经 M3-B 验证的字段接入报告，保留历史结果与回滚。uncertain、unknown、lost、unavailable 等状态按实际模块契约传递，不自动变成技能、成长或确定训练结论。跳跃之后按旋转、步法、燕式扩展，每一类重新完成数据准入、比较协议和验证。

## 4. 文档导航与优先级

1. 本路线图管方向和依赖；[实施计划 r2](docs/superpowers/plans/2026-09-08-v2-v3-development-implementation-plan.md)管具体任务。
2. 当前进度台账管“实际做到了哪一步”，不由计划 checkbox 自动推断完成。
3. 本轮 Review 与替换记录记录修改原因、归档与回滚。
4. [Golden 运行手册](docs/golden-eval-ab-runbook.md)管数据/评估操作；[功能保护说明](docs/feature-preservation/README.md)及 checked ledger 管产品保留。
5. [2026-07-29 历史计划](docs/superpowers/plans/2026-07-29-skating-analysis-v2-shadow-pipeline-iteration-plan.md)保留约束和证据；旧 checkbox 不再自动触发开发或清退 legacy。

有冲突先记录并停止相应动作，不能借路线图放宽现有权限、数据保护或 gate policy。

## 5. 现在怎么开始

历史M0-A启动入口保留供追溯；已验进度不重复执行。I4有限通过，原CLI预算耗尽；下一按PNG-only布局续接修复家长核验包，不重跑parity/CLI，不另起V3。旧字段/预算提示词已执行，I5解码1/1耗尽；37源PNG可复用，旧图包视觉失败、可回答仍0。

> 2026-09-25（Asia/Shanghai）当前入口：I5视觉停止review接受本次partial停止及37张源PNG复用，旧编号图包仍不可供家长作答：37源图/37编号图/4总览/35空答案已生成，但packet_ready=false、可回答0。I5-REV-01保持关闭，I5-REV-02字段映射与I5-REV-03预算分类已关闭；新I5-REV-04/P2为标签碰撞，37/37帧存在正面积相交、共88对。I5视频解码累计1/1、剩余0；I4真实CLI累计1/1、剩余0，均不重跑。下一唯一入口为PNG-only布局续接（未执行）：只读复用封存37PNG，在新runtime先做密集/贴边合成、全部37帧独立布局检查及真实预览，再冻结并一次正式验收；禁止读取视频、解码、模型、CLI、validate-only和Git写操作。两树只读，不代家长认人，不开放B2/Pose/UI/M4/V3。I3/I3.1/I4已验进度保留。[本review final](<runtime-dir>/m2-2i5-visual-stop-review/20260925-b8571e94/final.json)及[续接基线](<runtime-dir>/m2-2i5-visual-stop-review/20260925-b8571e94/continuation-baseline.json)绑定文档更新后的after（主838/隔离774，ledger725/734）；不再使用旧836文档基线。
