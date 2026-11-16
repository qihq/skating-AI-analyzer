# Golden V2 数据准入、冻结与 A/B 运行手册 r2

> 2026-09-08 修订；当前入口是[路线图 r2](docs/superpowers/plans/2026-09-08-v2-v3-evolution-roadmap.md)和[实施计划 r2](docs/superpowers/plans/2026-09-08-v2-v3-development-implementation-plan.md)。不调用任何 Superpowers skill。
> 原 Phase 0/V1 操作全文已原样归档，本文件不再把“先标 3–5 段、立即调参”作为默认开发路径。

## 1. 当前本地盘点与历史线上快照分开

上一轮 review 保存的 revision 117 摘要为：22 视频、24 事件、21 录制场次；event split 为 development 16、validation 4、frozen_test 4；Pose 人工真值 0、13 条 review 提示、5 个事件跟踪框少于 3；步法仅在 development。该 revision 尚未完成对应 evaluator 重跑，readiness 为 ready_for_evaluator / ready_to_freeze，实际未 freeze。

**2026-09-10本地盘点已独立review通过，未访问线上。** 实际使用2026-08-29保存的完整r101：22源、24事件、session/group各22个ID、77框、0 pose；22源均匹配本地媒体hash。ID数量不等于物理录制场次数，r117/21场次仍是历史摘要；配置r1空库未初始化。截至2026-09-26（Asia/Shanghai），I5合同与状态停止review接受最新partial停止记录，不接受独立诊断完成。原UTF-8交付已生成35目标/35 edge/F202诊断，但后续两次review先后因相对路径owner与漏计packet-manifest停止。最新确定P2：合同235应由补manifest恢复236，及partial checkpoint的next_action错误指向家长裁定；不改236为235，不改历史封存。原34/35目标、33/35双端仍是交付报告，尚未独立完整重算。本review独立核验四封存29/93/27/20、当前两树844/774、ledger725/734和原前后各236回执通过，不补称失败任务完成了未执行保护。下一唯一入口为合同与状态有界续接（未执行）：新工具完整构造→回执整集合→checkpoint分支合成通过后一次正式独立核验；通过才中性询问F200，未答等待，不自动改raw[1]/创建overlay。I3/I3.1/I4、图包和35条局部断言保留。当前保护使用[本review基线](<runtime-dir>/m2-2i5-contract-stop-review/20260926-112057-a540d855/continuation-baseline.json)：文档五改两增后主846/隔离774、documents25；历史236仍绑定原B的documents23及原manifest25，禁止混用。视频/CLI/validate-only/模型/网络/Git写全0；I4 CLI/I5解码累计均1/1、剩余0。diagnostic_only=true、family_usable=false、technical_conclusion/accuracy=null，不开放B2/Pose/UI/M4/V3。 本轮未刷新Golden/evaluator，不是新的预测封存或准确率评估；主代码/accepted G1/线上revision身份分开。

> 当前开发边界：source009三精确框与source001/F166分别保留。I4 CLI与I5视频解码均累计1/1、剩余0。35条F167–F201家长答案已冻结并有限review接受，不重复采集；下一只读比较既有候选，按source/帧键检查目标端与edge两端，F202拒答单列，不能充35分母。当前比较尚未执行，不调参、不写业务confirmed、不改代码。只在初始化/收口做有界保护，不逐帧全仓审计。不访问Golden/线上/DB/视频，不改split/evaluator/freeze，不接identity/Pose/UI，R3原48视觉未验；家庭本地不脱敏，GitHub上传前另查。

## 2. 四种动作与状态必须分开

| 动作 | 作用 | 不能证明 |
|---|---|---|
| 数据审计 / readiness | 检查标注、分组、split、review、数量与可测指标 | 不是 evaluator 执行、算法通过或 freeze 授权 |
| G2 freeze | 固定批准的数据与 legacy pipeline 身份 | 不是预测已经生成，也不是 baseline/算法通过 |
| 预测封存 / baseline record | 保存某候选实际输出及失败、身份与 digest；legacy record 引用 freeze | 不是正式评分已经通过 |
| evaluator / gate 判定 | 用批准真值、固定协议计算适用分母与指标 | 有限样本通过不是泛化或发布授权 |

M0-A 只保护本地现场，不访问线上、不运行上述数据动作。M1-A 的开发准入可以先于完整 G2 freeze；正式 G2/gate 仍必须满足已有全部条件。

## 3. M1-A：开发准入的只读流程

1. 家庭自用开发可使用本项目已有本地完整数据，不要求先脱敏或另行导出匿名摘要。先按代码/配置定位数据与实际版本，确实不明再问；线上访问和写入/运行仍按具体任务范围。不无谓将PIN/token复制进报告或命令。
2. 只读现有catalog/workspace及相关记录，允许查看完整标签/框/pose用于开发检查，记录实际revision、时间、policy、readiness、既有evaluator所属revision与freeze/baseline。不要为读取缺失文件触发store初始化写入；不自动调用线上API或运行evaluator。
3. 本地runtime和报告可保留完整source ID、路径、hash、标签/框与具体缺口，无需脱敏。准备上传GitHub时再检查待提交文件和待推送历史，排除不公开的家庭数据/秘密，确需公开内容另做脱敏；不要改坏本地原件。
4. 检查 source、recording session、grouping、重复片段与 split 的关系。一个视频的多个片段不能跨集合伪装独立样本；多次运行不增加独立 N。
5. 开发可以查看标签并据此检查/调参/选问题样本；记录实际使用和历史暴露。已看过或用于调参的数据可作开发回归，但不得冒充未接触的独立holdout。正式独立测试需另行保留隔离数据；本地开发不因正式审计缺口停止，不自动修改原split/freeze。
6. 列出跳跃允许输入、mask、GT 分母与缺口；没有 Pose 真值时不能报告 Pose 准确率，但不阻止 source/PTS/输入隔离契约开发。

review queue 和少框事件先产生处置建议；补标/确认/保留歧义/不可观察需要实际权限和 revision 审计。不能为了满足数量造框或强行确定答案。

## 4. 数据政策、Pose 与 anchor

政策以 [gate_policy.py](backend/app/analysis_v2/evaluation/gate_policy.py) 的 `golden-gate-policy.v2` 为准，不在本次改计划时降低：

- G1：至少 18 source 视频、18 valid events，jump/spin/step/spiral 至少 10/4/2/2；场景、场次、去重与复核要求保留。
- G2：24–30 events，jump 10–14、spin 6–8、step 4–5、spiral 4–5，以及 grouped split 等实际 freeze 检查。
- Pose：24–40 代表性源帧；子型独立报告至少 4 个适用样本，6 为目标。不能把帧数等同于独立视频/场次 N。

先制定Pose分层抽样、观测状态和复核计划，再标注；GT不可观察点不造坐标。家庭开发可以查看已有标注，但要记录用途；已经用于调参或修复的数据不再声称未接触独立测试。正式评估选定的隔离标签不能作为待评估预测输入。

当前 [identity_anchor.py](backend/app/analysis_v2/evaluation/identity_anchor.py) 输出明确标为 diagnostic-only。它可以作为研究候选，不是正式 tracking 输入许可：

- 单帧身份辅助与整段 Golden track/事件标签分开；审计框来源与选帧是否利用了目标事件。
- 不包含 event ID、profile、动作边界、关键时刻、圈数或完整跟踪时间线。
- 当前 anchor 对 tracking 存在真值泄漏风险；未批准独立身份选择协议，不进入正式 tracking 比较。
- 若后续批准人工初始化，所有分支采用相同辅助条件或单独报告；初始化帧不能同时用同一个 GT 框自评分。

## 5. M3-A：先锁比较规则，不照抄旧 V1 阈值

按[实施计划第 4 节](docs/superpowers/plans/2026-09-08-v2-v3-development-implementation-plan.md)明确单位、matching、适用 mask、固定分母、错人/拒答/运行失败处理、IoU、Pose 尺度、PTS 误差、rotation 定义、资源、阈值与容差。

旧 Phase 0 的“分层退化 10% / 时间 0.05 秒”不自动成为本轮 M3 晋级条件。先核对真实 evaluator 和既有 gate 定义，再由 owner 明确批准本次比较门槛；不能为了新核心更好看换统计口径。

不同 baseline 能力不全相同。accepted G1/D2/D3 的 action/moment/rotation 诊断不能凭空变成 tracking/pose 预测。无适用预测或无统一语义时注明不可比，不伪造第三列基线数值。

## 6. M1-B：owner 确认后正式 freeze

owner 确认至少覆盖：实例、实际 dataset revision、完整 snapshot fingerprint、split/membership、policy、legacy pipeline fingerprint、用途和时间。

[G2BaselineStore](backend/app/analysis_v2/evaluation/g2_baseline.py) 的真实行为必须保留：

1. `freeze()` 检查 ready_to_freeze 和 legacy_pipeline_fingerprint，保存完整 dataset fingerprint、membership fingerprint 和 policy；已有不同数据 freeze 会报错。
2. `assert_compatible()` 主要校验 frozen membership，**不能单独证明标签内容没有变化**。操作前还要核验完整 snapshot hash/approved revision；不要仅信任调用者传来的 fingerprint 字符串。
3. `record_baseline()` 要求已有 freeze 且传入 dataset fingerprint 与 freeze 匹配，保存结果 fingerprint；这不是 candidate 预测自动封存或评分通过。
4. 数据改变时明确记录新 revision、授权与后续验证；禁止删除 freeze 文件再“试一次”。

缺步法覆盖或其他 G2 条件时，不进行官方 G2 freeze。可以继续已批准的跳跃 development/validation 开发，但正式 G2/gate 不能借局部开发成功绕过。

## 7. M3-B：先封存预测，再读取测试真值

1. 记录锁定的协议与候选：commit+patch digest、模型/config/environment、mask、比较范围、允许的人工输入及批准时间。
2. 预测器只接触批准的源视频/PTS/身份输入；GT 由 evaluator 侧读取，不按 Golden event windows 预裁视频给模型。
3. 各分支保存完整预测、运行失败/缺预测/拒答台账、RunManifest 和审计 sidecar，并封存 digest。
4. evaluator 使用批准 snapshot 对所有分支按统一版本评分；必要 adapter 只做格式/时间/坐标转换，不补造预测。event ID 对齐仅在评估侧进行。
5. 所有适用 GT 样本保留在对应分母；只有事先定义的不适用情况能排除，模型失败不是排除理由。缺 GT 沿用实际 null、denominator=0、insufficient_sample 等输出，不手写不存在的状态字段。
6. 分别报告覆盖、错人、误报/漏报、拒答、误差与资源；matched 子集误差和整体覆盖必须一起读。source envelope recall 与 localized interval quality 分开。
7. 只按锁定阈值作有限样本晋级或不晋级结论；未达标不替换生产，失败记录不删除。

### holdout 与复跑规则

- development/validation 可调参、选候选，但保留版本和每轮结果。
- frozen_test 若曾用于调参或根据结果选择候选，对受影响开发流程已不是未见测试；保留历史用途，并申请未见录制场次或只报告已暴露有限样本验证。
- 标注人员看视频不等于算法开发者按结果调参；审计谁、何时、看了什么、用于什么决定。历史证据不足记 `exposure_unknown`（审计分类，不是新增 API enum）。
- 历史 G1 D1 文档已有一次 frozen-test verification 记录，必须核验其范围；不能默认现有全部 frozen_test 未见，也不能武断认定全部污染。
- 同一候选、同一协议的技术复跑可测稳定性，不增加独立 N；若改模型、阈值、输入筛选或 matching，重新记录候选与暴露关系，不能当同一次未见测试复跑。

## 8. 评估入口与旧工具用途

| 工具 | 实际用途 | 本轮限制 |
|---|---|---|
| [V2 pilot_evaluator](backend/app/analysis_v2/evaluation/pilot_evaluator.py) | `evaluate_pilot(dataset, bundle)` 与真实 V2 mask/分母/指标 | 先核验 bundle/GT snapshot/匹配，M3-A 确定正式调用流程 |
| [pilot_store](backend/app/analysis_v2/evaluation/pilot_store.py) / [Golden router](backend/app/routers/golden_v2.py) | 已存在的 V2 存储/路由契约 | 读取与写入/触发评估区别授权，不猜 endpoint 执行 |
| [source diagnostic dry-run](scripts/g1_source_diagnostic_dry_run.py) | 有范围的 G1 source-only 诊断 | 不是通用三路正式 runner，保留 diagnostic-only 限制 |
| [V1 eval_against_gt](backend/scripts/eval_against_gt.py) | 旧 manifest 与 prediction 格式的离线 evaluator | 不直接用于 V2 bundle，不是“后续所有改动”的统一判据 |
| [diff_baselines](backend/scripts/diff_baselines.py) | 对比其支持的旧 baseline 格式 | 不能把不兼容 V2 输出拼成可比结果 |

环境开关只有在生成预测时才影响预测；给离线评分临时设 tracker 开关不会改变已保存输出。保留这条旧手册有效经验，但不因此沿用旧步骤/阈值。

旧 V1 完整操作见原样归档，仅供历史兼容研究，不能直接当本轮执行脚本。
