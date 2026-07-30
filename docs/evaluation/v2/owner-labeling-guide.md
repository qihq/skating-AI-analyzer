# Golden V2 家长标注指南

在家长模式打开 `/me/advanced?tool=golden`。这里只接收新选择的私有视频，不要导入以前的 debug 素材池。

1. 上传视频，填写录制场次和分组。上传后会自动选中该视频；也可以从“已上传视频”切回旧视频继续编辑。
2. 选择视频并播放。记录关键时刻、人物框或 Pose 前，先用上一帧/下一帧锁定精确源帧和 PTS。
3. 每个完整动作建立一个事件区间。普通事件预计 3-6 分钟；交叉、遮挡、出画重入或旋转不确定事件预计 8-15 分钟。
4. 确认主滑手。在“主滑手框”中点击“在视频上画主滑手框”，直接用鼠标、触控笔或手指拖框，再添加到当前帧。普通事件标 3-8 个稀疏框；只有交叉、遮挡等困难区间才需要更密集。
5. Select family, optional subtype, observability, scene strata, and split. The profile panel changes with the family: jumps expose T/A/L plus rotation; spins expose entry/main/exit plus rotation; steps and spirals expose one phase and representative moment. Use the capture buttons at the exact source frame. Do not enter profile-specific labels for an unobservable event.
6. Pose 是全数据集 50-100 个代表帧的抽样项，不需要每个事件、每一帧都标。只添加真正看得见的关节；看不清时留空，不要猜。
7. Review the queue, save only when the form is complete, and resolve a conflict by reloading before retrying. Offline or unavailable-frame messages never mean a label was confirmed.
8. 删除事件、bbox 或 Pose 后需要保存才生效。删除整个视频会同时删除其当前事件/bbox/Pose 和私有视频文件，需要明确确认；历史 revision 审计仍保留，但视频文件不可恢复。
9. 只有真正完成复核后才能记录复核：延迟复标至少间隔 24 小时；模糊旋转与 frozen-test 交叉场景使用独立复核记录。

Protocol: collect at least five recording sessions (prefer eight or more), never split a source or session across development/validation/frozen-test, re-label at least 10 percent after a delay, and double-review ambiguous rotation and frozen-test crossings. Unobservable fields are excluded from ordinary accuracy denominators but are counted and reported. The first pose pass covers 50-100 representative frames across the whole dataset, not every frame.

当前先完成 G1 的 36 个真实动作事件，不需要为了凑 60-80 个而复制或重复使用素材。之后只按 profile、场景和录制场次缺口补拍；没有足够素材时保持 gate 未通过，不用伪造覆盖率。

Suggestions are never Ground Truth. Frozen-test first-pass suggestions are rejected by the server; all human-confirmed fields carry annotator, timestamp, and revision history.

## Iteration 3 pilot

The dashboard at `/golden` shows the exact G1 profile and scene gaps, raw denominators, confidence intervals, review requirements, and failed-event links. The 36-event pilot is diagnostic only and cannot be presented as release approval. Evaluator runs remain blocked as `waiting_for_owner_labels` until all real-event, grouping, duplicate, source-frame, delayed-review, and double-review checks pass.
