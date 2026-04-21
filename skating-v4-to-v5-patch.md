# 花样滑冰训练分析系统 — v4 → v5 迭代更新文档

> **使用方式**：将本文档发给 Codex，在开头说明：
> ```
> 这是一个已有完整 v4 代码的项目，请在现有代码基础上按顺序实现以下更新。
> 不要重写已有文件，只新增或修改涉及的文件。
> 每个 Patch 独立可验证，完成一个后再发下一个。
> ```

---

## 目录

| Patch | 涉及模块 | 核心变更 |
|---|---|---|
| **Patch A** | 全局 + Phase 4 | 弟弟→昭昭，坦坦/昭昭生肖头像 SVG |
| **Patch B** | Phase 1 + Phase 2 | 分析报告手动删除；训练计划续期 + 家/冰过滤 |
| **Patch C** | Phase 4 | PIN 4-6位自定义 + 可修改 |
| **Patch D** | Phase 4 + Phase 5 | 技能「尝试中」第三状态；Analysis 与技能树自动联动；儿童模式星级评分 |
| **Patch E** | Phase 3 | 改造六：动作窗口定位 + 慢动作帧率自适应 |
| **Patch F** | Phase 6 | 记忆过期机制（expires_at）+ AI 自动建议 |
| **Patch G** | Phase 7（新） | TrainingSession 课次表；SQLite 自动备份；视频归档策略 |

> **推荐 Codex 推理设置**：Patch A/B/C 默认推理；Patch D/E/F 中等推理；Patch G 默认推理

---

---

# Patch A：全局重命名 + 生肖头像

> **目标**：将「弟弟」重命名为「昭昭」（2022年生，属虎），
> 为坦坦（2020年生，属鼠）和昭昭各自引入生肖 SVG 头像组件，
> 替换原有的 emoji 头像方案。

---

## A-1 数据库：Skater 表更新

### 修改文件：`backend/app/models.py`

在 `Skater` 模型新增字段：
```python
avatar_type: Mapped[str] = mapped_column(String, default="emoji")
# 取值："zodiac_rat" | "zodiac_tiger" | "emoji"
```

### 修改文件：`backend/app/main.py`（或 startup 初始化逻辑所在文件）

将系统初始化的选手数据从：
```python
# 旧
{"name": "didi", "display_name": "弟弟", "avatar_emoji": "🐨", "birth_year": 2023, ...}
```
改为：
```python
# 新
{"name": "zhaozao", "display_name": "昭昭",
 "avatar_type": "zodiac_tiger", "avatar_emoji": "🐯",
 "birth_year": 2022, "current_level": "snowplow", "is_default": False}
```

坦坦同步更新：
```python
{"name": "tantan", "display_name": "坦坦",
 "avatar_type": "zodiac_rat", "avatar_emoji": "🐭",
 "birth_year": 2020, "current_level": "fs1", "is_default": True}
```

### 数据库迁移（Patch A）
```python
async def run_migrations_patch_a(engine):
    async with engine.begin() as conn:
        await conn.execute(text(
            "ALTER TABLE skaters ADD COLUMN avatar_type TEXT NOT NULL DEFAULT 'emoji'"
        ))
        # 更新现有记录
        await conn.execute(text(
            "UPDATE skaters SET avatar_type='zodiac_rat',   display_name='坦坦', "
            "avatar_emoji='🐭', birth_year=2020 WHERE name='tantan'"
        ))
        await conn.execute(text(
            "UPDATE skaters SET avatar_type='zodiac_tiger', display_name='昭昭', "
            "name='zhaozao', avatar_emoji='🐯', birth_year=2022 WHERE name='didi'"
        ))
```

---

## A-2 前端：ZodiacAvatar 组件

### 新增文件：`frontend/src/components/ZodiacAvatar.tsx`

```tsx
interface ZodiacAvatarProps {
  avatarType: "zodiac_rat" | "zodiac_tiger" | "emoji";
  avatarEmoji?: string;
  size?: "sm" | "md" | "lg" | "xl";
  animate?: boolean;  // 开启弹跳动画
}

// size 对应像素：sm=32, md=48, lg=96, xl=120
```

**坦坦（zodiac_rat）SVG 设计规范：**
- 圆润身体，米色 `#F5E6C8` + 浅灰 `#D4C4A8`
- 大耳朵，内耳粉色 `#F4A0B0`（半透明）
- 细长尾巴绕在身后
- 穿冰刀鞋：深蓝鞋身 `#2C3E7A` + 银色刀刃 `#C0C0C0`
- 弯眉 + 圆眼点，表情憨萌

**昭昭（zodiac_tiger）SVG 设计规范：**
- 圆润身体，橙黄 `#F5A623` + 额头「王」字黑色条纹
- 小圆耳，白色腹部 `#FAFAFA`
- 穿冰刀鞋（同款配色）
- 圆眼，略带威风的神情

**动画（animate=true 时生效）：**
```css
@keyframes avatar-bounce {
  0%, 100% { transform: translateY(0px); }
  50%       { transform: translateY(-4px); }
}
/* 通过 CSS class 控制，不影响无动画场景 */
```

**使用示例：**
```tsx
// 儿童模式首页大图（96px，带动画）
<ZodiacAvatar avatarType="zodiac_rat" size="lg" animate />

// 报告页顶部小图（48px）
<ZodiacAvatar avatarType="zodiac_rat" size="md" />

// 底部导航角标（32px）
<ZodiacAvatar avatarType="zodiac_tiger" size="sm" />
```

### 修改文件：所有用到选手头像 emoji 的地方

搜索并替换所有 `skater.avatar_emoji` 渲染为 `<ZodiacAvatar>` 组件调用，
传入 `avatarType={skater.avatar_type}` 和 `avatarEmoji={skater.avatar_emoji}`。

涉及文件（按 v4 结构）：
- 选手选择页（SkaterSelectPage 或类似）
- BottomNav（角标位置）
- ReportPage 顶部
- ArchivePage 统计卡片
- SkillTreePage 顶部

---

## ✅ Patch A 验证清单

- [ ] 数据库中「弟弟」记录已更新为「昭昭」，name='zhaozao'，birth_year=2022
- [ ] 选手选择页显示「坦坦」+ 小老鼠SVG，「昭昭」+ 小老虎SVG
- [ ] 两个头像均无像素感，SVG 在 Retina 屏清晰
- [ ] 儿童模式首页头像有弹跳动画（2.5s loop）
- [ ] 报告页、底部导航等各尺寸场景均正确渲染
- [ ] 「减少动画」系统设置开启时，弹跳动画停止

---

---

# Patch B：报告删除 + 训练计划续期/过滤

---

## B-1 分析报告手动删除

### 新增接口：`backend/app/routers/analysis.py`

```python
@router.delete("/{analysis_id}")
async def delete_analysis(
    analysis_id: str,
    x_parent_pin: str = Header(..., alias="X-Parent-Pin"),
    db: AsyncSession = Depends(get_db)
):
    """
    删除一条分析记录。
    - 验证 PIN（调用现有 verify_pin 逻辑）
    - 拒绝删除 status='processing' 的记录，返回 400
    - 级联删除：
        1. 关联的 TrainingPlan 记录
        2. /data/uploads/{analysis_id}/ 目录（视频文件 + 帧图）
        3. Analysis 记录本身
    - 成功返回 204 No Content
    """
```

**文件删除逻辑：**
```python
import shutil, os

upload_dir = f"/data/uploads/{analysis_id}"
if os.path.exists(upload_dir):
    shutil.rmtree(upload_dir)
```

### 修改文件：`frontend/src/pages/ReportPage.tsx`

在 completed/failed 状态下，右上角新增「删除」按钮（**仅家长模式可见**）：

```
页面顶部行布局：
← 返回                              🗑️ 删除（家长模式）
```

**删除流程（前端）：**
1. 点击「🗑️ 删除」→ 弹出确认 Modal
   ```
   ⚠️ 确认删除？
   删除后将同时移除视频文件和分析数据，无法恢复。
   [ 取消 ]  [ 确认删除 ]
   ```
2. 点击「确认删除」→ 弹出 PIN 输入框（格子数与设置位数一致，见 Patch C）
3. PIN 验证通过 → 调用 `DELETE /api/analysis/{id}`，header 带 `X-Parent-Pin`
4. 成功 → 跳转 `/archive`，显示 toast「已删除这条分析记录」
5. 若状态为 processing → 按钮置灰，hover 提示「分析进行中，无法删除」

### 修改文件：`frontend/src/pages/HistoryPage.tsx`

每条记录右侧新增删除图标（**家长模式专属**）：
- 图标：`🗑️`，触控区 44×44px
- 点击触发与 ReportPage 相同的确认 + PIN 流程
- 删除成功后该条目从列表消失，顶部统计数字 -1

---

## B-2 训练计划续期

### 新增接口：`backend/app/routers/plan.py`（或现有 plan router）

```python
@router.post("/{plan_id}/extend")
async def extend_plan(plan_id: str, body: ExtendPlanBody, db: AsyncSession = Depends(get_db)):
    """
    根据已完成情况，用 AI 重新生成未完成的天数。
    body: { "completed_days": [1, 2, 3] }
    """
```

**plan.py 续期 Prompt（追加到现有 plan.py service）：**

System prompt（同原计划生成，强制 JSON）：
```
你是专业花样滑冰教练，请根据分析报告生成7天个性化训练计划。
只输出 JSON，不含任何 markdown 包裹或额外说明。
```

User prompt：
```
原训练计划已完成前 {completed_days} 天。
以下是已完成的训练摘要：
{completed_sessions_summary}

请重新生成第 {remaining_days} 天的训练内容，
保持原有7天主题顺序（Day {N}: {theme}），
只输出需要更新的天数的 JSON 数组，格式与原计划相同。
参考原始报告背景：{original_report_summary}
```

接口返回更新后的完整 `plan_json`（合并已完成天 + 新生成天）。

### 修改文件：`frontend/src/pages/PlanPage.tsx`

**新增①：顶部「今天在家/在冰场」切换器**

```
┌──────────────────────────────┐
│  🏠 今天在家   ⛸️ 今天在冰场  │
└──────────────────────────────┘
（Segmented Control，切换状态存 localStorage key: 'plan_location_mode'）
```

- 「今天在家」：只显示 `is_office_trainable=true` 的 session
- 「今天在冰场」：显示所有 session
- Day 7 在家模式下：显示「今天需要上冰才能练，切换到「在冰场」模式查看」提示

**新增②：「计划续期」按钮**

显示条件：已完成的 session 覆盖的天数 ≥ 3 天（即至少3天内有完成的 session）

```
位置：页面底部，整体进度条下方
文案：「📅 根据进度续期计划」
样式：蓝色描边按钮（非填充，避免和主操作混淆）
```

点击流程：
1. 计算 `completed_days` 列表
2. 调用 `POST /api/plan/{plan_id}/extend`，显示 loading
3. 成功 → toast「冰宝（IceBuddy）已根据你的进度更新了后续安排 ✨」，刷新页面数据

---

## ✅ Patch B 验证清单

### B-1 删除功能
- [ ] 家长模式 ReportPage 右上角显示「删除」按钮，坦坦/昭昭模式不显示
- [ ] 点击弹出确认 Modal，「确认删除」后弹出 PIN 输入框
- [ ] 正确 PIN → 删除成功 → 跳转 `/archive` + toast
- [ ] 检查 NAS：`/data/uploads/{uuid}/` 目录已被清空删除
- [ ] HistoryPage 对应条目消失
- [ ] processing 状态的记录，删除按钮置灰并有提示
- [ ] HistoryPage 每条记录（家长模式）显示删除图标，流程同上

### B-2 训练计划
- [ ] PlanPage 顶部切换器正常，切换状态在刷新后保留（localStorage）
- [ ] 「今天在家」模式：只有 🏠 session 可见，Day 7 显示提示
- [ ] 完成 3 天后「计划续期」按钮出现
- [ ] 点击续期后 toast 文案正确，新内容替换旧内容

---

---

# Patch C：家长 PIN 4-6 位自定义 + 可修改

---

## C-1 后端

### 修改文件：`backend/app/models.py`

`ParentAuth` 表新增字段：
```python
pin_length: Mapped[int] = mapped_column(Integer, default=4)
# 记录当前 PIN 的位数，用于前端动态渲染格子数
```

### 修改文件：`backend/app/routers/auth.py`

**更新现有接口：**

```python
# GET /api/auth/has-pin
# 响应新增 pin_length 字段
{"has_pin": true, "pin_length": 4}

# POST /api/auth/setup-pin
# body: {"pin": "123456"}  → 支持 4~6 位
# 验证：len(pin) in [4, 5, 6]，否则返回 422
# 写入时同时保存 pin_length = len(pin)

# POST /api/auth/verify-pin（无变化，直接比对 hash）
```

**新增接口：**
```python
# POST /api/auth/change-pin
# body: {"old_pin": "1234", "new_pin": "654321"}
# 逻辑：
#   1. 验证 old_pin 与存储 hash 匹配
#   2. 验证 new_pin 长度 4~6 位
#   3. 更新 pin_hash 和 pin_length
#   4. 返回 {"success": true}
# 错误：旧 PIN 错误返回 {"success": false, "reason": "旧PIN不正确"}
```

### 数据库迁移（Patch C）
```python
async def run_migrations_patch_c(engine):
    async with engine.begin() as conn:
        await conn.execute(text(
            "ALTER TABLE parent_auth ADD COLUMN pin_length INTEGER NOT NULL DEFAULT 4"
        ))
```

---

## C-2 前端

### 修改文件：`frontend/src/components/PinInput.tsx`（或现有 PIN 输入组件）

将固定4格改为动态渲染：

```tsx
interface PinInputProps {
  length: number;        // 4 | 5 | 6，从 /api/auth/has-pin 获取
  onComplete: (pin: string) => void;
  error?: boolean;       // 输入错误时红色闪动
  locked?: boolean;      // 锁定状态（输错3次后）
  lockSecondsLeft?: number;
}
```

**格子渲染：**
```tsx
Array.from({ length }).map((_, i) => (
  <input key={i} type="password" maxLength={1} inputMode="numeric"
         className={`w-14 h-14 text-center text-2xl font-bold rounded-2xl
                     border-2 transition-all duration-150
                     ${error ? 'border-red-400 bg-red-50 animate-shake'
                              : 'border-gray-200 bg-gray-50 focus:border-violet-400 focus:bg-violet-50'}`}
  />
))
```

**锁定状态显示：**
```
输错3次后显示：
🔒 已锁定，请 {N} 秒后重试
（倒计时 30 秒，期间所有格子 disabled）
```

### 修改文件：`frontend/src/pages/SettingsPage.tsx`

在家长模式 Settings 页新增「修改家长 PIN」区块：

```
──────────────────────────────────
安全设置

家长 PIN
当前位数：4位          [ 修改 PIN ]
──────────────────────────────────
```

点击「修改 PIN」弹出 Modal：
```
修改家长 PIN

旧 PIN（N格）
● ● ● ●

新 PIN 位数
[ 4位 ]  [ 5位 ]  [ 6位 ]   ← Segmented Control

新 PIN
● ● ● ●（格子数随上面选择变化）

确认新 PIN
● ● ● ●

[ 取消 ]  [ 保存 ]
```

保存逻辑：
1. 调用 `POST /api/auth/change-pin`
2. 成功 → Modal 关闭，toast「PIN 已更新」，页面刷新 pin_length
3. 旧 PIN 错误 → 旧 PIN 格子红色闪动 + 提示「旧 PIN 不正确」

---

## ✅ Patch C 验证清单

- [ ] 首次设置 PIN：输入 6 位数字可正常保存
- [ ] 输入 3 位时「保存」按钮置灰（未满位数）
- [ ] 设置 6 位 PIN 后，进入家长模式的输入框变为 6 格
- [ ] Settings 页显示「修改 PIN」入口，当前位数正确
- [ ] 修改 PIN 弹窗：旧PIN验证失败时红色提示，正确后可保存新PIN
- [ ] 修改后使用新 PIN 登录成功，旧 PIN 失败
- [ ] `docker compose down` 再 `up`，新 PIN 仍有效
- [ ] 所有需要 PIN 验证的地方（删除报告、手动解锁技能）格子数均与当前设置一致

---

---

# Patch D：技能「尝试中」第三状态 + 自动联动 + 儿童星级评分

---

## D-1 技能三状态

### 修改文件：`backend/app/models.py`

`SkillNode`（或 `SkaterSkill`）模型更新：
```python
# 原来：is_unlocked: bool
# 改为：
status: Mapped[str] = mapped_column(String, default="locked")
# 取值："locked" | "attempting" | "unlocked"

attempt_count: Mapped[int] = mapped_column(Integer, default=0)
# 该选手在此技能节点上，force_score 达到 threshold 的累计次数

best_score: Mapped[int] = mapped_column(Integer, default=0)
# 历史最高 force_score

unlocked_by: Mapped[str | None] = mapped_column(String, nullable=True)
# "auto" | "parent" | None
```

### 数据库迁移（Patch D）
```python
async def run_migrations_patch_d(engine):
    async with engine.begin() as conn:
        # 假设技能状态存在 skater_skills 关联表
        await conn.execute(text(
            "ALTER TABLE skater_skills ADD COLUMN status TEXT NOT NULL DEFAULT 'locked'"
        ))
        await conn.execute(text(
            "ALTER TABLE skater_skills ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0"
        ))
        await conn.execute(text(
            "ALTER TABLE skater_skills ADD COLUMN best_score INTEGER NOT NULL DEFAULT 0"
        ))
        await conn.execute(text(
            "ALTER TABLE skater_skills ADD COLUMN unlocked_by TEXT"
        ))
        # 将原来 is_unlocked=True 的记录迁移为 status='unlocked'
        await conn.execute(text(
            "UPDATE skater_skills SET status='unlocked', unlocked_by='parent' "
            "WHERE is_unlocked=1"
        ))
```

---

## D-2 Analysis 与技能节点自动联动

### 修改文件：`backend/app/models.py`

`Analysis` 表新增字段：
```python
skill_node_id: Mapped[str | None] = mapped_column(
    String, ForeignKey("skill_nodes.id"), nullable=True
)
```

### 数据库迁移
```python
await conn.execute(text(
    "ALTER TABLE analyses ADD COLUMN skill_node_id TEXT REFERENCES skill_nodes(id)"
))
```

### 修改文件：`backend/app/routers/analysis.py`

上传接口 `POST /api/analysis/upload` 新增可选参数：
```python
skill_node_id: Optional[str] = Form(None)
# 前端复盘页（ReviewPage）的技能分类下拉，选中时传入对应 skill_node_id
```

### 新增文件：`backend/app/services/skill_progress.py`

```python
async def auto_update_skill_progress(
    analysis_id: str,
    db: AsyncSession
) -> None:
    """
    在 background task 分析完成的最后一步调用。
    逻辑：
    1. 读取 analysis.skill_node_id, skater_id, force_score
    2. 若 skill_node_id 为空 → 直接返回，不影响任何技能
    3. 查询 skill_node 的 unlock_config（threshold, consecutive）
    4. 更新 best_score（若本次更高）
    5. 若 force_score >= threshold：
         attempt_count += 1
         若 attempt_count >= consecutive：
           status = 'unlocked'，unlocked_by = 'auto'
           给 skater 加 XP（skill_node.xp）
           在 analysis 记录上设置 auto_unlocked_skill = skill_node_id（用于前端庆祝）
         否则：
           status = 'attempting'（仅当原来是 locked 时才升级，不降级）
    6. 若 force_score < threshold：保持原 status 不变（不降级）
    """
```

### 修改文件：`backend/app/routers/analysis.py`（background task）

在 `process_analysis` background task 最后一步追加：
```python
await auto_update_skill_progress(analysis_id, db)
```

### 修改文件：`backend/app/schemas.py`

`AnalysisResponse` 新增字段：
```python
auto_unlocked_skill: Optional[str] = None  # skill_node_id，非空时前端触发庆祝动画
```

---

## D-3 前端技能节点三状态 UI

### 修改文件：`frontend/src/components/SkillNode.tsx`（或现有节点组件）

**三状态渲染规范：**

```tsx
// 已点亮（unlocked）
<div className="bg-[#E0F7F4] border-2 border-[#4CAF50]/30 rounded-3xl p-4 min-w-[88px]">
  <div className="w-3 h-3 rounded-full bg-[#4CAF50]" />
  <span className="text-[#4CAF50] font-medium text-xs">已点亮</span>
  {skill.unlocked_by === 'parent' && <span>👑</span>}
</div>

// 尝试中（attempting）
<div className="bg-[#FFF3E0] border-2 border-[#F59E0B]/30 rounded-3xl p-4 min-w-[88px]">
  <div className="w-3 h-3 rounded-full bg-[#F59E0B]" />
  <span className="text-[#F59E0B] font-medium text-xs">🔥 尝试中</span>
  {/* 进度条 */}
  <div className="mt-1 h-1.5 bg-orange-100 rounded-full overflow-hidden">
    <div className="h-full bg-[#F59E0B] rounded-full"
         style={{ width: `${(skill.attempt_count / skill.unlock_config.consecutive) * 100}%` }} />
  </div>
  <span className="text-[10px] text-orange-400">
    {skill.attempt_count}/{skill.unlock_config.consecutive} 次
  </span>
</div>

// 未开始（locked）
<div className="bg-gray-50 border-2 border-gray-100 rounded-3xl p-4 min-w-[88px] opacity-70">
  <div className="w-3 h-3 rounded-full bg-gray-300" />
  <span className="text-gray-400 text-xs">未开始</span>
</div>
```

**「尝试中」展开详情卡（点击节点后显示）：**
```
华尔兹跳  🔥 尝试中
最高分：72    目标分：65
已达标：2 / 3 次
再来一次就能点亮！⭐
```

### 修改文件：`frontend/src/pages/ReportPage.tsx`

分析完成后，检查 `response.auto_unlocked_skill`：
- 非空 → 触发现有庆祝动画（`UnlockCelebration`），传入刚解锁的技能名

---

## D-4 儿童模式星级评分

### 修改文件：`frontend/src/pages/ReportPage.tsx`

儿童模式（坦坦/昭昭）下，`force_score` 不显示数字圆环，改为星级展示：

```tsx
function ForceScoreStars({ score }: { score: number }) {
  const stars =
    score >= 85 ? 5 :
    score >= 70 ? 4 :
    score >= 56 ? 3 :
    score >= 40 ? 2 : 1;

  const encouragements = [
    "继续加油，你做到了！💪",
    "不错哦，再练几次就更好了！",
    "今天的动作有进步！⭐",
    "超棒！冰宝（IceBuddy）为你骄傲！🎉",
    "完美！你是冰上小明星！🌟",
  ];

  return (
    <div className="flex flex-col items-center gap-2">
      <div className="flex gap-1 text-4xl">
        {Array.from({ length: 5 }).map((_, i) =>
          <span key={i}>{i < stars ? "⭐" : "☆"}</span>
        )}
      </div>
      <p className="text-lg font-bold text-[#6C63FF]">
        {encouragements[stars - 1]}
      </p>
    </div>
  );
}
```

显示条件：`isKidMode === true` 时用 `ForceScoreStars` 替换 `ForceScoreRing`。

---

## ✅ Patch D 验证清单

### D-1/D-2 技能联动
- [ ] 数据库新增4个字段（status/attempt_count/best_score/unlocked_by）
- [ ] 分析报告与技能节点关联：上传时选择「华尔兹跳」，分析完成后该节点 attempt_count +1
- [ ] force_score 达到 threshold 但不满 consecutive：节点变「尝试中」橙色
- [ ] 满足条件后自动变「已点亮」绿色，触发庆祝动画
- [ ] 家长手动解锁后 unlocked_by='parent'，节点显示 👑
- [ ] 分析不关联技能时（skill_node_id 为空），所有技能状态不受影响

### D-3 三状态 UI
- [ ] 三种状态颜色区分清晰（灰/橙/绿）
- [ ] 「尝试中」节点显示进度条和「N/M 次」
- [ ] 点击「尝试中」节点弹出详情，包含最高分和距离解锁剩余次数

### D-4 星级评分
- [ ] 儿童模式 ReportPage：数字圆环替换为5颗星
- [ ] score=45 → ⭐⭐☆☆☆，score=75 → ⭐⭐⭐⭐☆，score=90 → ⭐⭐⭐⭐⭐
- [ ] 星级下方显示对应鼓励语
- [ ] 家长模式仍显示数字圆环，不受影响

---

---

# Patch E：改造六——动作窗口定位 + 慢动作帧率自适应

> **背景**：上传的通常是整段训练录像（2-5分钟），而实际要分析的动作只有几秒。
> iPhone 慢动作视频（240fps）若直接 5fps 抽帧，20帧仅覆盖约 0.08 秒真实动作。

---

## E-1 后端

### 修改文件：`backend/app/models.py`

`Analysis` 表新增字段：
```python
action_window_start: Mapped[float | None] = mapped_column(Float, nullable=True)
action_window_end:   Mapped[float | None] = mapped_column(Float, nullable=True)
source_fps:          Mapped[float | None] = mapped_column(Float, nullable=True)
is_slow_motion:      Mapped[bool]         = mapped_column(Boolean, default=False)
```

### 数据库迁移（Patch E）
```python
async def run_migrations_patch_e(engine):
    async with engine.begin() as conn:
        for col, typ in [
            ("action_window_start", "REAL"),
            ("action_window_end",   "REAL"),
            ("source_fps",          "REAL"),
            ("is_slow_motion",      "INTEGER DEFAULT 0"),
        ]:
            await conn.execute(text(
                f"ALTER TABLE analyses ADD COLUMN {col} {typ}"
            ))
```

### 修改文件：`backend/app/services/video.py`

在现有文件中追加以下函数（不修改现有抽帧逻辑，只在调用处插入新步骤）：

```python
SLOW_MOTION_THRESHOLD_FPS = 60.0

# 动作类型对应的分析窗口大小（秒）
ACTION_WINDOW_SIZES = {
    "跳跃":  3.0,
    "旋转":  5.0,
    "步法":  8.0,
    "自由滑": None,  # 不截窗，沿用原有前60秒逻辑
}

def detect_video_fps(video_path: str) -> float:
    """
    用 FFprobe 读取视频实际帧率。
    解析 r_frame_rate（如 "240/1" → 240.0，"30000/1001" → 29.97）。
    """
    result = subprocess.run([
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", video_path
    ], capture_output=True, text=True)
    data = json.loads(result.stdout)
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            r = stream.get("r_frame_rate", "30/1")
            num, den = r.split("/")
            return float(num) / float(den)
    return 30.0


def detect_action_window(
    video_path: str,
    action_type: str,
    source_fps: float
) -> tuple[float, float]:
    """
    用运动密度曲线找到峰值区间。
    返回 (start_sec, end_sec)，包含前后各1秒缓冲。
    对慢动作视频，时间戳按视频时间计算（FFmpeg 负责展开）。
    """
    window_size = ACTION_WINDOW_SIZES.get(action_type)
    if window_size is None:
        # 自由滑：不截窗，返回 (0, 60)
        return 0.0, 60.0

    # Step 1：抽全程缩略图（2fps，160×90）
    thumb_dir = video_path + "_thumbs"
    os.makedirs(thumb_dir, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-i", video_path,
        "-vf", "scale=160:90", "-r", "2",
        f"{thumb_dir}/thumb_%04d.jpg", "-y", "-loglevel", "quiet"
    ])

    # Step 2：计算相邻帧像素差均值 → 运动强度序列
    thumbs = sorted(glob.glob(f"{thumb_dir}/thumb_*.jpg"))
    motion_scores = []
    prev = None
    for path in thumbs:
        frame = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if prev is not None:
            diff = cv2.absdiff(frame, prev).mean()
            motion_scores.append(diff)
        prev = frame
    shutil.rmtree(thumb_dir)

    if not motion_scores:
        return 0.0, min(60.0, window_size + 2.0)

    # Step 3：滑动窗口找峰值
    half_window_frames = int(window_size * 2)  # 2fps 下每秒2帧
    best_start_frame = 0
    best_score = -1
    for i in range(len(motion_scores) - half_window_frames):
        s = sum(motion_scores[i:i + half_window_frames])
        if s > best_score:
            best_score = s
            best_start_frame = i

    # 转换回秒（2fps 缩略图）
    start_sec = max(0.0, best_start_frame / 2.0 - 1.0)
    end_sec   = start_sec + window_size + 2.0  # +2 秒缓冲

    return start_sec, end_sec
```

**修改现有抽帧入口函数**（在 `extract_frames` 或 `process_video` 中）：

```python
# 在现有逻辑前插入：
source_fps = detect_video_fps(video_path)
is_slow_motion = source_fps >= SLOW_MOTION_THRESHOLD_FPS
start_sec, end_sec = detect_action_window(video_path, action_type, source_fps)

# 修改 FFmpeg 命令，加入时间截断：
# 原来：ffmpeg -i {video_path} -vf "fps=5,scale=854:480" ...
# 改为：ffmpeg -ss {start_sec} -to {end_sec} -i {video_path} -vf "fps=5,scale=854:480" ...

# 分析完成后写入字段：
analysis.action_window_start = start_sec
analysis.action_window_end   = end_sec
analysis.source_fps          = source_fps
analysis.is_slow_motion      = is_slow_motion
```

**需要新增的依赖（backend/requirements.txt 追加）：**
```
opencv-python-headless==4.10.0.84
```

注意：Phase 3 如果已安装 mediapipe，opencv 可能已存在，检查后去重。

---

## E-2 前端

### 修改文件：`frontend/src/pages/ReportPage.tsx`

在报告顶部信息行（日期/动作类型旁），家长模式下新增：

```tsx
{report.action_window_start != null && (
  <div className="flex items-center gap-2 text-xs text-gray-400">
    <span>📍 分析窗口：{report.action_window_start.toFixed(1)}s — {report.action_window_end.toFixed(1)}s</span>
    {report.is_slow_motion && (
      <span className="bg-orange-100 text-orange-600 text-[10px] font-bold
                       px-2 py-0.5 rounded-full">
        慢动作 {Math.round(report.source_fps)}fps
      </span>
    )}
  </div>
)}
```

坦坦/昭昭模式下不显示此行。

---

## ✅ Patch E 验证清单

- [ ] 上传 2 分钟视频（跳跃约在第 40 秒），`action_window_start/end` 定位到跳跃段（误差 ≤ 5 秒）
- [ ] 家长模式 ReportPage 显示「分析窗口：X.Xs — X.Xs」
- [ ] 上传 iPhone 慢动作视频（240fps）：`is_slow_motion=true`，`source_fps=240`
- [ ] 慢动作视频报告页显示橙色「慢动作 240fps」徽章
- [ ] 自由滑类型：`action_window_start=0, action_window_end=60`（沿用原逻辑）
- [ ] 无法定位到明显动作时（静止视频）：不报错，退化为分析前 N 秒

---

---

# Patch F：冰宝记忆过期机制 + AI 自动建议

---

## F-1 记忆过期机制

### 修改文件：`backend/app/models.py`

`SnowballMemory` 表新增字段：
```python
expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
# None = 永不过期
# 到期后 is_pinned 在查询时自动降级（不物理修改字段）
```

### 数据库迁移（Patch F）
```python
async def run_migrations_patch_f(engine):
    async with engine.begin() as conn:
        await conn.execute(text(
            "ALTER TABLE snowball_memories ADD COLUMN expires_at TIMESTAMP"
        ))
```

### 修改文件：`backend/app/services/memory.py`（或 snowball service）

`build_memory_context` 过滤过期记忆：
```python
async def build_memory_context(skater_id: str, db: AsyncSession) -> str:
    now = datetime.utcnow()
    memories = await db.execute(
        select(SnowballMemory).where(
            SnowballMemory.skater_id == skater_id,
            SnowballMemory.is_pinned == True,
            or_(
                SnowballMemory.expires_at == None,
                SnowballMemory.expires_at > now
            )
        )
    )
    # 其余拼接逻辑不变
```

### 修改接口：`POST /api/skaters/{id}/memories` 和 `PATCH /api/skaters/{id}/memories/{mem_id}`

body 新增可选字段：
```python
expires_at: Optional[datetime] = None
# 前端传值约定：
# "1m"  → now + 1个月
# "3m"  → now + 3个月
# null  → 永不过期
# 后端将字符串转换为实际 datetime 后存储
```

### 修改文件：GET `/api/skaters/{id}/memories` 响应

每条记忆返回额外字段：
```python
"is_expired": bool  # expires_at 非空且已过期，但 is_pinned 仍为 True 的记录
```

---

## F-2 AI 自动建议

### 新增文件：`backend/app/services/memory_suggest.py`

```python
async def suggest_memory_updates(
    analysis_id: str,
    skater_id: str,
    db: AsyncSession
) -> list[dict]:
    """
    分析完成后调用（非强制，background task 末尾触发）。
    读取新报告 + 现有记忆，让 report 槽 AI 输出建议列表。
    建议只写入 memory_suggestions 临时表，不直接修改 SnowballMemory。
    """
```

**Prompt（调用 report 槽当前激活供应商）：**

System prompt：
```
你是冰宝（IceBuddy），请分析训练报告并与现有长期记忆对比，提出记忆更新建议。
只输出 JSON 数组，不含任何 markdown 包裹。
```

User prompt：
```
当前长期记忆：
{existing_memories_text}

本次训练报告：
- 动作类型：{action_type}
- 总体评价：{report.summary}
- 主要问题：{issues_text}
- 训练重点：{report.training_focus}

请对比分析，输出建议数组，每条建议格式如下：
[
  {"action": "add",    "title": "...", "content": "...", "category": "卡点|目标|总结|偏好|其他"},
  {"action": "update", "memory_id": "uuid", "new_content": "..."},
  {"action": "expire", "memory_id": "uuid", "reason": "目标似乎已完成，建议设为过期"}
]
若无建议则返回空数组 []。
最多输出 3 条建议，避免过度打扰。
```

### 新增数据模型：`MemorySuggestion` 表

```python
id:          str (UUID, PK)
analysis_id: str (FK → analyses.id)
skater_id:   str (FK → skaters.id)
suggestions: JSON   # 上述格式的建议数组
is_reviewed: bool   # 家长是否已查看（查看即消失通知角标）
created_at:  datetime
```

### 新增接口

```
GET    /api/skaters/{id}/memory-suggestions        未处理建议列表（is_reviewed=False）
POST   /api/skaters/{id}/memory-suggestions/apply  批量写入家长选中的建议
       body: { "suggestion_id": "uuid", "accepted_indices": [0, 2] }
       accepted_indices 对应 suggestions 数组的下标，未选中的忽略
PATCH  /api/skaters/{id}/memory-suggestions/{id}/dismiss  标记为已查看（不采纳）
```

### 修改文件：`frontend/src/pages/ReportPage.tsx`

分析完成后，若存在未处理建议（`GET /api/skaters/{id}/memory-suggestions` 返回非空），
在报告页底部显示提示卡：

```
┌─────────────────────────────────────────────┐
│ 💡 冰宝（IceBuddy）有 N 条记忆更新建议         │
│ 「发现新卡点：落冰单腿稳定」                   │
│ [ 查看建议 ]  [ 忽略 ]                        │
└─────────────────────────────────────────────┘
```

点击「查看建议」跳转到 SnowballPage 的记忆管理区，建议卡片置顶显示。

### 修改文件：`frontend/src/pages/SnowballPage.tsx`

记忆管理区顶部（仅家长模式，若有待处理建议）：

```
── 待确认建议（N条）────────────────────────

[新增] 发现新卡点
「落冰时左脚单腿稳定性不足，建议重点练习」
分类：卡点
[ ✅ 采纳 ]  [ ❌ 忽略 ]

[更新] 当前目标 → 「点冰跳」（原「华尔兹」）
冰宝（IceBuddy）认为华尔兹已达到稳定水平
[ ✅ 采纳 ]  [ ❌ 忽略 ]

────────────────────────────────────────────
```

---

## ✅ Patch F 验证清单

### F-1 过期机制
- [ ] 新增记忆时，弹窗有「过期设置」选项（1个月/3个月/永不过期）
- [ ] 设置1个月过期的记忆，手动将 `expires_at` 改为过去时间，再次分析时不注入 context（查日志验证）
- [ ] GET memories 接口：过期记忆包含 `is_expired: true`
- [ ] SnowballPage 管理区：过期记忆显示灰色「已过期」标签，不显示「固定」徽章

### F-2 AI 自动建议
- [ ] 分析完成后 `memory_suggestions` 表有新记录
- [ ] `GET /api/skaters/{id}/memory-suggestions` 返回建议（需等 AI 调用完成）
- [ ] ReportPage 底部建议提示卡正常显示（有建议时才出现）
- [ ] 点击「查看建议」跳转 SnowballPage，建议卡片置顶
- [ ] 采纳「新增」建议后，记忆列表出现新条目
- [ ] 采纳「过期」建议后，对应记忆的 `expires_at` 设为当前时间
- [ ] 忽略后提示卡消失，下次进入 ReportPage 不再显示

---

---

# Patch G：数据管理与安全（新 Phase 7）

> **目标**：引入训练课次概念，实现 SQLite 自动备份，建立视频文件归档策略。
> 这是纯后端 + 运维工作，无复杂 AI 逻辑，工作量小但价值高。

---

## G-1 TrainingSession 训练课次表

### 新增文件：`backend/app/models.py`（追加）

```python
class TrainingSession(Base):
    __tablename__ = "training_sessions"

    id:               Mapped[str]      = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    skater_id:        Mapped[str]      = mapped_column(String, ForeignKey("skaters.id"))
    session_date:     Mapped[date]     = mapped_column(Date)
    location:         Mapped[str]      = mapped_column(String, default="冰场")
    # "冰场" | "家" | "体育馆"
    session_type:     Mapped[str]      = mapped_column(String, default="上冰")
    # "上冰" | "陆训"
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    coach_present:    Mapped[bool]     = mapped_column(Boolean, default=False)
    note:             Mapped[str | None] = mapped_column(String, nullable=True)
    created_at:       Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # 一个课次包含多个分析记录
    analyses: Mapped[list["Analysis"]] = relationship("Analysis", back_populates="session")
```

### 修改文件：`backend/app/models.py`（Analysis 表）

```python
# Analysis 表新增外键（可选关联）
session_id: Mapped[str | None] = mapped_column(
    String, ForeignKey("training_sessions.id"), nullable=True
)
```

### 数据库迁移（Patch G）
```python
async def run_migrations_patch_g(engine):
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS training_sessions (
                id               TEXT PRIMARY KEY,
                skater_id        TEXT NOT NULL REFERENCES skaters(id),
                session_date     DATE NOT NULL,
                location         TEXT NOT NULL DEFAULT '冰场',
                session_type     TEXT NOT NULL DEFAULT '上冰',
                duration_minutes INTEGER,
                coach_present    INTEGER NOT NULL DEFAULT 0,
                note             TEXT,
                created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await conn.execute(text(
            "ALTER TABLE analyses ADD COLUMN session_id TEXT REFERENCES training_sessions(id)"
        ))
```

### 新增接口

```
GET    /api/skaters/{id}/sessions               课次列表（按日期倒序）
POST   /api/skaters/{id}/sessions               新建课次
       body: {session_date, location, session_type, duration_minutes, coach_present, note}
GET    /api/sessions/{session_id}               单个课次详情（含关联分析列表）
PATCH  /api/sessions/{session_id}               更新课次信息
DELETE /api/sessions/{session_id}               删除课次（不删除关联分析，只解除关联）
PATCH  /api/analysis/{id}/session               将分析关联到课次
       body: {"session_id": "uuid"}
```

### 修改文件：`frontend/src/pages/ReviewPage.tsx`

Step 1「选择训练视频」下方新增可选课次关联：

```
关联到课次（可选）
[ + 今天新建课次 ]  或  [ 选择已有课次 ▾ ]

新建课次表单（折叠/展开）：
  📅 训练日期：[今天]
  📍 地点：[冰场 ▾]  （冰场/家/体育馆）
  ⏱ 时长：[      ] 分钟
  👨‍🏫 有教练陪同：[ 开关 ]
  📝 备注：[        ]
```

### 修改文件：`frontend/src/pages/ArchivePage.tsx`

进展页统计卡片扩展为四格：

```
累计档案  近7天  连续记录  本月课次
  N条      N次    N天      N次
```

时间轴中，属于同一课次的条目用细分隔线 + 日期标题归组：

```
─── 2026年4月15日  ⛸️ 冰场  60分钟 ─────────
  🎬 冰宝诊断  华尔兹跳  82分  →
  🎬 冰宝诊断  点冰跳    74分  →

─── 2026年4月12日  🏠 家  30分钟 ──────────
  🎬 冰宝诊断  步法练习  68分  →
```

---

## G-2 SQLite 自动备份

### 修改文件：`docker-compose.yml`

新增 backup service：

```yaml
  backup:
    image: alpine:3.19
    container_name: skating-backup
    volumes:
      - ./data:/data:ro          # 只读挂载数据目录
      - ./backups:/backups       # 写入备份目录
    command: >
      sh -c "
        echo '备份服务启动' &&
        while true; do
          TIMESTAMP=$$(date +%Y%m%d_%H%M) &&
          cp /data/skating.db /backups/skating_$${TIMESTAMP}.db &&
          echo \"备份完成: skating_$${TIMESTAMP}.db\" &&
          find /backups -name '*.db' -mtime +7 -delete &&
          echo '清理7天前备份完成' &&
          sleep 86400;
        done
      "
    restart: unless-stopped
```

> 每天自动备份一次 SQLite，保留最近 7 天。备份目录 `./backups/` 独立于 `./data/`。

### 新增目录（项目根）

```bash
mkdir -p backups
echo "*.db" >> backups/.gitignore   # 备份文件不提交 git
```

---

## G-3 视频文件归档策略

### 新增文件：`backend/app/services/archive_policy.py`

```python
import os, shutil
from datetime import datetime, timedelta

ARCHIVE_DAYS = 90        # 超过 90 天的原始视频移入 archive
DATA_DIR     = "/data/uploads"
ARCHIVE_DIR  = "/data/archive"

async def run_archive_policy():
    """
    定期任务：将超过 ARCHIVE_DAYS 天的分析记录的原始视频移至归档目录。
    报告 JSON、frames/ 帧图仍保留在原位（占用空间小，用于报告展示）。
    原始视频文件（.mp4/.mov 等）移至 /data/archive/{uuid}/original.*
    """
    cutoff = datetime.utcnow() - timedelta(days=ARCHIVE_DAYS)
    os.makedirs(ARCHIVE_DIR, exist_ok=True)

    for uuid_dir in os.listdir(DATA_DIR):
        full_path = os.path.join(DATA_DIR, uuid_dir)
        if not os.path.isdir(full_path):
            continue
        # 检查目录修改时间（粗略判断）
        mtime = datetime.utcfromtimestamp(os.path.getmtime(full_path))
        if mtime > cutoff:
            continue
        # 找原始视频文件（非 frames/ 目录下的视频）
        for fname in os.listdir(full_path):
            if fname.lower().endswith((".mp4", ".mov", ".avi", ".mkv")):
                src  = os.path.join(full_path, fname)
                dest_dir = os.path.join(ARCHIVE_DIR, uuid_dir)
                os.makedirs(dest_dir, exist_ok=True)
                shutil.move(src, os.path.join(dest_dir, fname))
```

### 修改文件：`backend/app/main.py`

在 startup 事件中注册定期任务（每天执行一次）：

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.services.archive_policy import run_archive_policy

scheduler = AsyncIOScheduler()

@app.on_event("startup")
async def start_scheduler():
    scheduler.add_job(run_archive_policy, "interval", hours=24)
    scheduler.start()

@app.on_event("shutdown")
async def stop_scheduler():
    scheduler.shutdown()
```

**新增依赖（requirements.txt）：**
```
apscheduler==3.10.4
```

### 新增接口

```
GET  /api/admin/storage-stats
     返回：{
       "uploads_mb":  120.5,   # /data/uploads/ 占用
       "archive_mb":  340.2,   # /data/archive/ 占用
       "backups_mb":  8.1,     # /backups/ 占用
       "total_mb":    468.8,
       "archived_count": 23    # 已归档的分析数量
     }
```

在家长模式 Settings 页「系统信息」区块中调用此接口展示。

---

## ✅ Patch G 验证清单

### G-1 训练课次
- [ ] `POST /api/skaters/{id}/sessions` 创建课次成功
- [ ] ReviewPage 显示「关联到课次」区域，新建课次表单可展开
- [ ] 上传视频时关联课次，分析完成后 `analysis.session_id` 有值
- [ ] ArchivePage 时间轴：同一课次的分析按日期标题归组
- [ ] ArchivePage 四格统计「本月课次」数值正确

### G-2 自动备份
- [ ] `docker compose up --build` 后 backup 容器正常启动
- [ ] `docker logs skating-backup` 显示「备份完成」日志
- [ ] `ls backups/` 可见 `skating_YYYYMMDD_HHMM.db` 文件
- [ ] 手动将某 .db 文件日期改为 8 天前，重启 backup 容器后该文件被清理

### G-3 视频归档
- [ ] 手动将某分析目录修改时间改为 91 天前，调用 `run_archive_policy()`，原始视频移入 `/data/archive/`
- [ ] 帧图（`frames/`）仍在原位，报告页骨骼播放不受影响
- [ ] Settings 页「系统信息」显示存储统计数字

---

---

# 附：Patch 发送顺序与 Codex 建议

## 推荐顺序
```
Patch A（全局重命名 + 头像）→ 验证 A
→ Patch B（删除 + 计划续期）→ 验证 B
→ Patch C（PIN 4-6位）→ 验证 C
→ Patch D（三状态 + 联动 + 星级）→ 验证 D
→ Patch E（动作窗口 + 慢动作）→ 验证 E
→ Patch F（记忆过期 + AI建议）→ 验证 F
→ Patch G（课次 + 备份 + 归档）→ 验证 G
```

## 每次发送 Codex 时的开头模板
```
这是一个已有完整 v4 代码的项目（花样滑冰训练分析系统）。
请在现有代码基础上实现以下 Patch X 的内容。
不要重写已有文件，只新增或修改涉及的文件。
所有 API Key 由我手动填入 .env，使用占位符即可。

[粘贴对应 Patch 内容]
```

## Codex 推理设置建议
| Patch | 推理强度 | 原因 |
|---|---|---|
| A | 默认 | SVG 绘制 + 数据迁移，逻辑简单 |
| B | 默认 | 增删接口 + 前端交互，无复杂逻辑 |
| C | 默认 | PIN 长度动态化，改动集中 |
| D | 中等 | 三状态转换逻辑 + 自动解锁条件判断 |
| E | 中等 | 视频处理管线改造 + 运动密度算法 |
| F | 中等 | AI 调用 + 建议格式解析 + 多表联动 |
| G | 默认 | 数据结构 + Docker 配置，无 AI 逻辑 |

---

*坦坦和昭昭加油！🐭🐯⛸️*
