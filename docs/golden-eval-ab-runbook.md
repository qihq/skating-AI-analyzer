# Golden Eval & A/B 运行手册（Phase 0）

> 你已经建好了 golden 标注工作台（`/golden`）和离线 eval 脚本（`backend/scripts/eval_against_gt.py`），但还没标样本也还没跑出基线。这份手册把「标 → 跑 → A/B → 决策」四步串起来。完成后你就有了验证后续所有改动（Phase 1.1 平滑、1.4 软打分、1.5 错锁检测等）是否真的变好的判据。

## 前置条件

- 你在 `C:\Users\qihq\Pictures\skate testing video\` 已有真实测试视频（5 月 30 日还跑过 8 段 baseline，那段历史指标在 `tmp/skate-video-iteration/baseline-head.json`，可作为参照但不是真值对齐评估）。
- `eval_against_gt.py` 是**对齐真值**的评估，能算关键帧时间误差(秒)、身份切换次数、按 stratum 分层、failure tags。它是后续所有改动的判据。

## 0.1 标 3–5 段 golden 样本（约 2 小时，你自己操作）

走前端 `/golden` 工作台（`DebugPage workspace="golden"`）。挑代表性视频：

1. **单人 1 段**——A 侧（关键帧）基线。任一跳跃视频。
2. **两人并排/前后 1 段**——B 侧（套错人）基线。两个儿子同框的段落。
3. **旋转自遮挡 1 段**——A5 场景（旋转时关键点乱跳）。
4. **(可选) 不同机型/角度各 1 段**。

每段标：
- **T/A/L 时间戳**（jump）或 spin_entry/main/exit（spin）。把视频拖到对应帧点「记录时间戳」。
- **target bbox**：在「易锁错」的两人段画框（每段约 30–80 帧，不必全程标）。
- **stratum**：`single_skater` / `multi_skater` / `small_target` / `occlusion` / `known_bad_keyframes`。
- **expected_review_flags**（可选）：你预期应该出现的质量标志。

保存即写 `golden_label.json` + `prediction.json` + 共享 `golden_manifest.json`（在 `data/uploads/_debug/golden_manifest.json`）。

## 0.2 跑回归基线

```bash
cd C:\Users\qihq\Documents\skating-analyzer
python backend/scripts/eval_against_gt.py data/uploads/_debug/golden_manifest.json \
    --output tmp/golden/baseline_v5.2.313_off.json \
    --iou-threshold 0.3 --switch-frames 3
```

输出 `baseline_v5.2.313_off.json` 含：summary（mean/median/max 时间误差、身份切换、failure 数）+ stratum_summary（分层）+ failures + top_quality_flags。

**这就是你后续每次改动的判据。把它 commit 进 git 做版本锚点。**

## 0.3 外观 relock A/B（关键，决定 B 侧下一步走多远）

要做两次：一次默认关（已经跑了，`_off.json`），一次开。

```bash
# A 组: APPEARANCE_RELOCK=0 (默认) ——已是 0.2 的 baseline_v5.2.313_off.json
# B 组: APPEARANCE_RELOCK=1 (硬阈值)
PERSON_TRACKER_APPEARANCE_RELOCK=1 python backend/scripts/eval_against_gt.py \
    data/uploads/_debug/golden_manifest.json \
    --output tmp/golden/baseline_v5.2.313_relock_hard.json

# C 组 (可选): APPEARANCE_RELOCK=1 + SOFT=1 (Phase 1.4 软打分)
PERSON_TRACKER_APPEARANCE_RELOCK=1 PERSON_TRACKER_APPEARANCE_RELOCK_SOFT=1 \
    python backend/scripts/eval_against_gt.py \
    data/uploads/_debug/golden_manifest.json \
    --output tmp/golden/baseline_v5.2.313_relock_soft.json
```

> 注意：`PERSON_TRACKER_APPEARANCE_RELOCK_*` 是在**跑分析生成 prediction.json 时**生效的 env，不是在跑 eval 时。如果你的 golden manifest 里 `prediction.json` 已经是默认关跑出来的，那把 env 设成 1 重跑 eval 不会变。**正确做法**：先在 `/debug` 用对应 env 重跑 debug analysis 生成新 prediction.json，再保存为新的 golden label（同一段视频可保存多份 prediction），或保存到不同 sample id。

最简实操：在 `/debug>` 页开「重跑」按钮前，先在后端启动 env 里设好 `PERSON_TRACKER_APPEARANCE_RELOCK=1`（和可选 `SOFT=1`），让生成的 prediction.json 带着对应模式的 quality_flags，再在 `/golden` 标 golden label 时关联到这份新 prediction。

## 0.4 对比两份 baseline

```bash
python backend/scripts/diff_baselines.py \
    tmp/golden/baseline_v5.2.313_off.json \
    tmp/golden/baseline_v5.2.313_relock_hard.json
```

输出每层的「指标 delta + 方向（good/bad/flat）+ 失败样本增减 + 质量标志计数变化」。判读规则（路线图 §12）：

- **任一 stratum 退化 >10% → 不合并**（防止「多人变差被单人平均掉」）。
- 时间误差 median 改善 <0.05s → 视为无显著改善。

## A/B 结果怎么用来决策（路线图 §5/§6 的分叉）

| A/B 结果 | 含义 | 下一步 |
|---|---|---|
| `_relock_hard` 比 `_off` 身份切换少、且 keyframe 没退化 | HSV 够用，硬阈值OK | 跳 Phase 2.3/2.4 补 A 侧 |
| `_relock_hard` 身份切换少**但 keyframe 退化** | 硬阈值 fail-closed 误拒了正确 relock 导致 tracker 丢→pose 丢 | 走 Phase 1.4 软打分（`SOFT=1`），重跑 `_relock_soft` 验证 |
| `_relock_soft` 比 `_relock_hard` keyframe 不退化、身份切换仍减少 | 软打分治了 fail-closed 命门 | Phase 1.4 确认，进 Phase 1.5 manual_lock 错锁检测 |
| 任何模式下 HSV 完全没用（切换没减少） | HSV 对你家场景区分度不够（同色衣服？） | Phase 1.4 第二步：上 OSNet-x0.25 embedding |

## 后续每次改动的回归流程

每次实现一个 Phase 1.x 改动（如 `KEYFRAME_ONE_EURO_SMOOTHING=1`）：

1. 设好对应 env，在 `/debug` 重跑 golden 集 → 生成新 prediction.json。
2. 跑 `eval_against_gt.py` 产出 `tmp/golden/baseline_<改动名>.json`。
3. 跑 `diff_baselines.py` 对比 `baseline_v5.2.313_off.json`。
4. 看 stratum 分层 + failure tags + 质量标志变化，确认没退化。
5. 挑改善最大/退化最大各 1 段肉眼复核（路线图 §12.5）。

**改动单独回滚**（feature flag），不要揉在一起提交——揉在一起就不知道是哪项起的作用。