# 花样滑冰训练分析系统 — Patch H：手机端体验 + 产品打磨

> **使用方式**：将本文档发给 Codex，在开头说明：
> ```
> 这是一个已有完整代码的项目（花样滑冰训练分析系统，React 前端 + FastAPI 后端，Docker 部署）。
> 请在现有代码基础上按顺序实现以下更新。
> 不要重写已有文件，只新增或修改涉及的文件。
> 每个 Patch 独立可验证，完成一个后再发下一个。
> ```

---

## 目录

| Patch | 涉及模块 | 核心变更 |
|---|---|---|
| **H-1** | 后端 + ReportPage + HistoryPage | 视频分析失败重试按钮 |
| **H-2** | Header / BottomNav / Layout | 手机端模式切换器重设计（Bottom Sheet） |
| **H-3** | 全局 CSS | 触控目标尺寸统一优化 |
| **H-4** | manifest.json + index.html + 全局 CSS | PWA 主屏模式页面"飘"修复 |
| **H-5** | 多页面 | 产品深度优化（5条） |
| **H-6** | 多页面 | 评分图案显示错位修复 |
| **H-7** | HistoryPage / ArchivePage / UploadPage | 视频列表操作图标（查看分析 + 再次分析） |
| **H-8** | 家长端 Layout / 导航 | 家长端补充「进展」入口 |
| **H-9** | 后端 + 前端错误展示 | API 报错信息细化与前端清晰展示 |

> **推荐 Codex 推理设置**：H-1 / H-2 / H-3 / H-4 / H-6 / H-7 / H-8 → 默认推理；H-5 / H-9 → 中等推理

---

---

# Patch H-1：视频分析失败重试

> **目标**：分析失败时不强制重新上传，允许直接对已有视频文件触发重试。

---

## H-1 后端：新增 retry 接口

### 修改文件：`backend/app/routers/analysis.py`

```python
@router.post("/{analysis_id}/retry")
async def retry_analysis(
    analysis_id: str,
    db: AsyncSession = Depends(get_db),
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    """
    重新触发对已有视频文件的分析。
    - 查找 analysis 记录，status 必须为 "failed"，否则返回 400
    - 检查 /data/uploads/{analysis_id}/ 下是否存在原始视频文件（.mp4/.mov/.avi/.mkv）
    - 若视频不存在，返回 404，body: {"detail": "原始视频文件已不存在，请重新上传"}
    - 重置 status → "pending"，清空 error_message，更新 updated_at
    - 以 background_tasks 重新触发现有的分析 pipeline（复用 run_analysis 或同等函数）
    - 返回 200，body: {"message": "已重新提交分析任务"}
    """
```

---

## H-1 前端：ReportPage.tsx

当 `analysis.status === "failed"` 时，错误提示卡下方显示两个操作按钮：

```
┌─────────────────────────────────┐
│  ❌ 分析失败                      │
│  {error_message}                │
│                                 │
│  [ 🔄 重新分析 ]  [ 📤 重新上传 ] │
└─────────────────────────────────┘
```

**「重新分析」按钮逻辑：**
1. 点击 → 立即进入 loading（disabled + spinner），文案改为「提交中…」
2. 调用 `POST /api/analysis/{id}/retry`
3. 成功 → toast「已重新提交，请稍候」，页面切换为 processing 轮询 UI（复用现有 polling 逻辑）
4. 后端返回 404（视频不存在）→ toast「原始视频已清理，请点击"重新上传"」，「重新分析」按钮隐藏

**「重新上传」按钮逻辑：**
- 跳转上传页（`/upload` 或 ReviewPage Step 1），传入 `skater_id`

---

## H-1 前端：HistoryPage.tsx / ArchivePage.tsx

`status=failed` 的条目右侧，删除图标旁追加「🔄」重试图标：
- 触控区：44×44px
- 图标颜色：warning/orange 色系（与删除的 red 系区分）
- 点击逻辑与 ReportPage 一致（retry 接口 + toast）

---

## ✅ Patch H-1 验证清单

- [ ] 手动将一条记录 status 改为 failed，ReportPage 显示「重新分析」按钮
- [ ] 点击后按钮变 loading，后端日志出现重新分析 pipeline 入口
- [ ] 视频文件不存在时按钮消失，toast 提示正确
- [ ] HistoryPage 的 failed 条目有重试图标，可独立触发

---

---

# Patch H-2：手机端模式切换器重设计

> **目标**：将右上角突兀的文字切换按钮改为头像点击 + Bottom Sheet 交互。

---

## H-2 修改范围：Header 组件 / BottomNav / 全局 Layout

**移除**：右上角独立的「坦坦模式 / 家长模式」文字按钮（手机端）

**新增**：Header 右侧改为 32px ZodiacAvatar，点击弹出 Bottom Sheet：

```
点击头像 → 从底部弹出 Bottom Sheet：

┌───────────────────────────────┐
│  ▬▬▬  （drag handle）         │
│                               │
│   选择视角                     │
│                               │
│  🐭  坦坦         ← 当前选中行左侧蓝色竖条
│  🐯  昭昭
│  🔒  家长（输入 PIN）
│                               │
│  ────────────────────────────  │
│  [ 取消 ]                     │
└───────────────────────────────┘
```

**Bottom Sheet 样式规范：**
- 背景：白色，top-left / top-right 圆角 16px
- drag handle：4px × 40px，灰色，居中，margin-top 8px
- 每行高度：56px，图标 36px，文字 16px medium
- 支持下滑手势关闭（touch 事件监听）
- 遮罩：rgba(0,0,0,0.4)，点击遮罩关闭

**Header 右侧头像规则：**
- 坦坦模式 → zodiac_rat 头像（32px）
- 昭昭模式 → zodiac_tiger 头像（32px）
- 家长模式 → 🔐 图标（32px 圆形，深色背景）

**桌面端（≥768px）**：保持现有右上角文字切换方式不变，仅手机端使用 Bottom Sheet。

---

## ✅ Patch H-2 验证清单

- [ ] 手机端右上角显示头像/图标，无文字按钮
- [ ] 点击弹出 Bottom Sheet，三选项正确
- [ ] 当前模式有选中标记（蓝色竖条）
- [ ] 选择「家长」触发 PIN 输入流程
- [ ] 下滑或点遮罩关闭 Sheet
- [ ] 桌面端（768px+）保持原有切换逻辑

---

---

# Patch H-3：触控目标尺寸统一优化

> **目标**：按 WCAG AA 标准，统一所有交互元素的最小触控区域，改善 PWA 手指操作体验。

---

## H-3 全局 CSS 变量（index.css 或全局 tokens 文件）

```css
:root {
  --touch-target-min: 44px;
  --list-row-min-height: 64px;
  --bottom-nav-height: 56px;
}
```

## H-3 BottomNav

```css
/* 每个 Tab 项 */
.bottom-nav-item {
  min-height: var(--bottom-nav-height);   /* 56px */
  min-width: var(--touch-target-min);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}
.bottom-nav-item .icon { font-size: 24px; }
.bottom-nav-item .label { font-size: 10px; margin-top: 4px; }
.bottom-nav-item.active .icon,
.bottom-nav-item.active .label { color: var(--color-primary); }

/* 整体导航栏高度 + iOS safe area */
.bottom-nav {
  height: calc(var(--bottom-nav-height) + env(safe-area-inset-bottom, 0px));
  padding-bottom: env(safe-area-inset-bottom, 0px);
}
```

## H-3 列表行（HistoryPage / ArchivePage / PlanPage）

```css
.list-row {
  min-height: var(--list-row-min-height);   /* 64px */
  padding: 12px 16px;
}

/* 右侧操作按钮（删除/重试/箭头）统一 44×44px 触控区 */
.list-row-action {
  min-width: var(--touch-target-min);
  min-height: var(--touch-target-min);
  display: flex;
  align-items: center;
  justify-content: center;
}
```

## H-3 Settings / 表单类

```css
.settings-row {
  min-height: 52px;
  display: flex;
  align-items: center;
  padding: 0 16px;
}

/* Toggle/Switch（iOS 比例） */
.toggle-switch {
  width: 51px;
  height: 31px;
}
.toggle-thumb {
  width: 29px;
  height: 29px;
}
```

## H-3 页面底部安全区

所有页面主内容容器统一添加底部 padding，防止被 Home Indicator 遮挡：

```css
.page-content {
  padding-bottom: calc(var(--bottom-nav-height) + env(safe-area-inset-bottom, 0px) + 16px);
}
```

---

## ✅ Patch H-3 验证清单

- [ ] iPhone Safari / PWA：底部导航每个 Tab 高度不低于 56px，手指轻触可命中
- [ ] 列表行高度不低于 64px
- [ ] 设置页 Toggle 触控区域不低于 44×44px
- [ ] 页面底部最后一条内容不被 Home Indicator 遮挡

---

---

# Patch H-4：PWA 主屏模式"飘"修复

> **目标**：修复「添加到主屏幕」后状态栏颜色不一致、弹性滚动白边、Header 跳动等问题。

---

## H-4 manifest.json

```json
{
  "display": "standalone",
  "background_color": "#FFFFFF",
  "theme_color": "#FFFFFF",
  "orientation": "portrait"
}
```
`background_color` 和 `theme_color` 必须与 App 主背景色一致。

## H-4 index.html `<head>`

```html
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover, maximum-scale=1.0, user-scalable=no">
```

## H-4 全局 CSS

```css
html, body {
  background-color: var(--bg-primary, #FFFFFF);
  overflow-x: hidden;
  overscroll-behavior: none;   /* 防止弹性滚动泄露白底 */
}

#root {
  min-height: 100dvh;          /* 动态视口高度，iOS Safari 更稳定 */
  display: flex;
  flex-direction: column;
  position: relative;
  overflow: hidden;
}

/* 页面滚动收归内部容器，不在 body 上滚动 */
.page-scroll-container {
  flex: 1;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
  overscroll-behavior-y: contain;
}
```

## H-4 Header 高度适配

```css
.app-header {
  padding-top: env(safe-area-inset-top, 0px);
  min-height: calc(44px + env(safe-area-inset-top, 0px));
}
```

## H-4 滚动位置重置

若项目中存在 `window.scrollTo(0, 0)` 的路由跳转逻辑，
改为对 `.page-scroll-container` 元素的 `scrollTop = 0`，
避免 PWA standalone 模式下 `window.scroll` 不生效。

## H-4 深色主题（如已实现）

```html
<meta name="theme-color" media="(prefers-color-scheme: dark)" content="#1A1A2E">
<meta name="theme-color" media="(prefers-color-scheme: light)" content="#FFFFFF">
```

---

## ✅ Patch H-4 验证清单

- [ ] iPhone 主屏打开：状态栏颜色与 Header 背景色一致，无白边
- [ ] 顶部内容不被刘海/灵动岛遮挡
- [ ] 上下拉动时无白色弹性区域泄露
- [ ] 切换页面时 Header 高度稳定，无跳动

---

---

# Patch H-5：产品深度优化（5条）

> 每条独立，可拆开单独发给 Codex。

---

## H5-1 视频上传进度感知

**问题**：上传大视频时只有转圈，用户不知道进度。

**修复**：
- 用 `XMLHttpRequest` 替换 `fetch` 发送上传请求，监听 `upload.onprogress`
- UploadPage 显示进度条（0~100%）+ 「18MB / 45MB」文字
- 上传完成后自动进入分析步骤指示器：
  ```
  ✅ 视频上传  →  ⏳ 画面提取  →  ⏳ AI 分析  →  ⏳ 生成报告
  ```
  每 3 秒轮询 `GET /api/analysis/{id}` 的 `status` 字段，步骤逐步点亮

---

## H5-2 报告分享/复制功能

**问题**：分析结果无法分享给教练。

**修复**：
- ReportPage 右上角新增「📤 分享」按钮（仅家长模式可见）
- 后端新增 `POST /api/analysis/{id}/export`，返回纯文字摘要：
  ```
  [冰宝诊断] 坦坦 · 华尔兹跳 · 2026-04-21
  综合评分：82分

  亮点：起跳节奏稳定，手臂配合自然
  待改善：落冰左脚稳定性不足，建议加强单腿平衡练习

  技术细节：[点冰时机 ★★★★☆] [腾空高度 ★★★☆☆] [落冰稳定 ★★☆☆☆]

  由冰宝（IceBuddy）生成 · 仅供参考
  ```
- 前端调用 `navigator.share()`，fallback 为复制到剪贴板，成功后 toast「报告内容已复制」

---

## H5-3 儿童模式「今日任务」入口强化

**问题**：孩子进入儿童模式后不知道今天该做什么。

**修复**：
- 儿童模式首页，有未完成 session 时，头像下方显示「今日任务」卡片：
  ```
  ┌───────────────────────────────┐
  │  ⛸️ 今天要练：                 │
  │  华尔兹跳 × 10 次              │
  │  单腿站立 × 3 组               │
  │       [ 出发！ →→ ]            │
  └───────────────────────────────┘
  ```
  卡片背景渐变（主题色），按钮高度 56px
- 点击「出发」→ 跳转 PlanPage，自动 scroll 到对应 session
- 今日已全完成 → 显示「今天超棒！✨ 休息一下」鼓励卡

---

## H5-4 历史页空状态引导

**问题**：新选手历史页一片空白，无引导。

**修复**：
```
[ZodiacAvatar 96px，bounce 动画]

坦坦还没有训练记录

拍一段练习视频，让冰宝来分析 🎬

[ + 上传第一个视频 ]
```
按钮跳转上传页，传入当前 `skater_id`。

---

## H5-5 技能树「正在练习」置顶

**问题**：儿童模式需要滚动才能找到当前专注技能。

**修复**：
- 儿童模式下，`status='in_progress'` 或标记为「专注」的技能提升到独立置顶区块（黄色边框卡片）
- 技能卡底部显示最近一次关联分析的得分：「上次得分：82分」

---

## ✅ Patch H-5 验证清单

- [ ] H5-1：上传 >20MB 视频时进度条正常递增；步骤指示器随 status 逐步点亮
- [ ] H5-2：报告页有分享按钮；手机端调起系统分享；桌面端显示复制按钮
- [ ] H5-3：有计划时今日任务卡片显示；点击跳转并定位到正确 session
- [ ] H5-4：历史空状态显示 ZodiacAvatar + 引导按钮
- [ ] H5-5：技能树儿童模式「正在练习」区块置顶，得分从历史数据正确取值

---

---

# Patch H-6：评分图案显示错位修复

> **目标**：修复报告页评分展示组件（星级 / 雷达图 / 环形进度等）在双端出现图案错位的问题。

---

## H-6 问题排查范围

以下是常见的错位原因，逐一检查：

### 1. SVG/Canvas 尺寸未响应容器宽度

评分组件若使用固定 `width`/`height` 属性（如 `width="300"`），
在不同屏幕尺寸下会溢出或错位。

**修复**：
```tsx
// 错误：固定尺寸
<svg width="300" height="300">

// 正确：响应式，宽度跟随父容器
<svg viewBox="0 0 300 300" style={{ width: "100%", height: "auto" }}>
```

对所有评分相关的 SVG 组件统一检查并替换为 `viewBox` + `width: 100%`。

### 2. CSS transform-origin 错误导致旋转偏移

若评分图使用 CSS `rotate` 或 `transform` 动画（如环形进度条从 -90° 开始），
需要确认 `transform-origin: center` 已设置。

```css
.score-ring {
  transform-origin: center center;
  transform: rotate(-90deg);
}
```

### 3. 多端字体渲染导致文字偏移

SVG 内的文字元素（`<text>`）在不同平台字体度量不同，
使用 `dominant-baseline="central"` + `text-anchor="middle"` 强制居中：

```svg
<text
  x="50%"
  y="50%"
  dominant-baseline="central"
  text-anchor="middle"
>82</text>
```

### 4. 雷达图 / 多边形坐标计算

若雷达图坐标通过 JS 三角函数计算，检查中心点是否正确传入：

```tsx
// 确保中心点与 viewBox 中心一致
const cx = viewBoxSize / 2;
const cy = viewBoxSize / 2;
```

### 5. 容器 padding 未被计入

使用 `getBoundingClientRect()` 或 `offsetWidth` 计算尺寸时，
若父容器有 `padding`，需减去 padding 后再传给图表：

```tsx
const containerRef = useRef<HTMLDivElement>(null);
const [size, setSize] = useState(0);

useEffect(() => {
  if (!containerRef.current) return;
  const observer = new ResizeObserver(([entry]) => {
    setSize(entry.contentRect.width);  // contentRect 已排除 padding
  });
  observer.observe(containerRef.current);
  return () => observer.disconnect();
}, []);
```

---

## H-6 修改范围

搜索以下文件中的评分展示组件，逐一应用上述修复：
- `ScoreRing.tsx` 或类似环形评分组件
- `RadarChart.tsx` 或类似雷达图组件
- `StarRating.tsx`（儿童模式星级，检查 SVG star 图案对齐）
- `ReportPage.tsx` 中直接内联的评分 SVG

每处修复附上修改前 / 修改后注释，方便 review。

---

## ✅ Patch H-6 验证清单

- [ ] iPhone（Safari）ReportPage 评分环/雷达图居中显示，无错位
- [ ] 安卓 Chrome ReportPage 评分显示正常
- [ ] 桌面浏览器宽度变化时（拖拽窗口），评分图案自适应不变形
- [ ] 儿童模式星级图案对齐，不出现半颗星偏移
- [ ] 环形进度条起始位置在正上方（-90°），不出现起点错位

---

---

# Patch H-7：视频列表操作图标（查看分析 + 再次分析）

> **目标**：已完成分析的视频在列表中显示操作图标，一目了然，减少进入报告再返回的跳转成本。

---

## H-7 前端：HistoryPage.tsx / ArchivePage.tsx

### 现有列表行结构调整

每条分析记录右侧，根据 `status` 显示不同操作图标组合：

```
┌─────────────────────────────────────────────────────┐
│ 🎬  华尔兹跳         82分   2026-04-21              │
│     坦坦 · 冰场                          [📄] [🔄]  │
└─────────────────────────────────────────────────────┘

[📄] = 查看分析报告（status: completed）
[🔄] = 再次分析（status: completed 或 failed）
[⏳] = 分析进行中（status: processing，不可点击，仅展示状态）
[❌] = 分析失败（status: failed，显示红色，可点击触发 retry）
```

**图标规范：**
- 触控区：44×44px（padding 补足）
- 图标尺寸：20px
- 「📄 查看报告」：主色系（蓝色）
- 「🔄 再次分析」：warning 色系（橙色），需家长 PIN 确认（家长模式直接调用，坦坦/昭昭模式弹出 PIN）
- 「❌ 失败」：red 色系，点击触发 H-1 中的 retry 逻辑
- 图标之间间距 8px，整体右侧区域 padding-right: 8px

**「再次分析」确认流程（家长模式）：**
1. 点击 🔄 → 弹出 Bottom Sheet 确认：
   ```
   重新分析这个视频？
   将消耗一次 AI 调用额度，原有报告将被覆盖。
   [ 取消 ]  [ 确认分析 ]
   ```
2. 确认 → 调用 `POST /api/analysis/{id}/retry`（复用 H-1 接口）
3. 列表行状态图标切换为 ⏳

**「再次分析」确认流程（坦坦/昭昭模式）：**
- 弹出家长 PIN 输入框，验证通过后执行上述流程

---

## H-7 前端：UploadPage.tsx / ReviewPage.tsx（上传成功后）

上传完成且分析成功后，在「查看报告」主按钮旁边追加小图标：

```
[ 📄 查看报告 ]   [ 🔄 再次分析 ]
```

「再次分析」为次级按钮（outline 样式），触发流程同上。

---

## ✅ Patch H-7 验证清单

- [ ] HistoryPage completed 条目右侧显示 [📄][🔄] 两个图标
- [ ] 点击 📄 跳转对应 ReportPage
- [ ] 点击 🔄 弹出确认 Sheet，确认后触发 retry，图标切换为 ⏳
- [ ] failed 条目右侧显示红色 ❌，点击触发 retry
- [ ] processing 条目右侧显示 ⏳，不可点击
- [ ] 坦坦/昭昭模式下「再次分析」需 PIN 验证后才执行
- [ ] 所有图标触控区不小于 44×44px

---

---

# Patch H-8：家长端补充「进展」入口

> **目标**：坦坦/昭昭端有「进展」（ArchivePage）底部导航入口，家长端缺失，导致家长需要切换视角才能查看统计，体验割裂。

---

## H-8 问题定位

检查 `BottomNav.tsx`（或家长模式专用的导航组件），确认家长模式的 Tab 配置是否遗漏了「进展」Tab。

家长模式底部导航应包含以下四个 Tab（与儿童模式对齐，但标签措辞更专业）：

```
[📹 分析]   [📋 计划]   [📊 进展]   [⚙️ 设置]
```

对照儿童模式（坦坦/昭昭）：

```
[📹 分析]   [📋 计划]   [🏆 进展]   [🌟 成就]
```

---

## H-8 修改范围

### 修改文件：`frontend/src/components/BottomNav.tsx`（或家长模式 Layout）

**定位家长模式的 Tab 配置数组**，补充「进展」Tab：

```tsx
const parentTabs = [
  { path: "/analysis",  icon: "📹", label: "分析"  },
  { path: "/plan",      icon: "📋", label: "计划"  },
  { path: "/archive",   icon: "📊", label: "进展"  },  // ← 补充此项
  { path: "/settings",  icon: "⚙️", label: "设置"  },
];
```

### 修改文件：`frontend/src/pages/ArchivePage.tsx`

确认 ArchivePage 对家长模式有完整视图，包括：
- 顶部四格统计卡（累计档案 / 近7天 / 连续记录 / 本月课次）
- 两个孩子的切换 Tab（坦坦 / 昭昭），可各自查看进展
- 时间轴列表
- 若已实现 Patch G-1，显示训练课次归组视图

**家长模式视图额外信息（在儿童模式基础上扩展）：**
- 每条分析记录显示「AI 评分」数字（儿童模式可能只显示星级）
- 支持按时间范围筛选（近 7 天 / 近 30 天 / 全部）
- 右上角可切换「坦坦 / 昭昭 / 全部」视图

---

## ✅ Patch H-8 验证清单

- [ ] 家长模式底部导航出现「📊 进展」Tab，与儿童模式对齐
- [ ] 点击「进展」跳转 ArchivePage，显示统计卡和时间轴
- [ ] ArchivePage 家长模式下可切换坦坦/昭昭视图
- [ ] 显示评分数字（不仅是星级）
- [ ] 四格统计数值正确（与儿童模式数据一致）

---

---

# Patch H-9：API 报错信息细化与前端清晰展示

> **目标**：目前 API 调用失败时前端显示「分析失败」但无法定位是哪个环节出错（视频处理？AI 调用超时？Key 无效？），让错误诊断更快速。

---

## H-9 后端：结构化错误码

### 修改文件：`backend/app/services/analysis_service.py`（或分析 pipeline 入口）

**定义错误码枚举：**

```python
from enum import Enum

class AnalysisErrorCode(str, Enum):
    VIDEO_DECODE_FAILED    = "VIDEO_DECODE_FAILED"     # 视频解码/转码失败
    FRAME_EXTRACT_FAILED   = "FRAME_EXTRACT_FAILED"    # 帧提取失败
    AI_API_TIMEOUT         = "AI_API_TIMEOUT"          # AI 接口超时（>60s）
    AI_API_AUTH_ERROR      = "AI_API_AUTH_ERROR"       # API Key 无效（401/403）
    AI_API_QUOTA_EXCEEDED  = "AI_API_QUOTA_EXCEEDED"   # 额度不足（429）
    AI_API_CONTENT_FILTER  = "AI_API_CONTENT_FILTER"   # 内容审核拦截
    AI_RESPONSE_PARSE_FAIL = "AI_RESPONSE_PARSE_FAIL"  # AI 返回无法解析为 JSON
    REPORT_SAVE_FAILED     = "REPORT_SAVE_FAILED"      # 报告写入数据库失败
    UNKNOWN_ERROR          = "UNKNOWN_ERROR"           # 其他未知错误
```

**在 Analysis 表新增字段（`models.py`）：**

```python
error_code:    Mapped[str | None] = mapped_column(String, nullable=True)
error_detail:  Mapped[str | None] = mapped_column(String, nullable=True)
# error_detail 记录原始异常信息（供调试，不直接展示给儿童）
```

**数据库迁移（Patch H）：**
```python
await conn.execute(text(
    "ALTER TABLE analyses ADD COLUMN error_code TEXT"
))
await conn.execute(text(
    "ALTER TABLE analyses ADD COLUMN error_detail TEXT"
))
```

**分析 pipeline 各阶段 try/except 包裹：**

```python
try:
    frames = await extract_frames(video_path)
except Exception as e:
    analysis.status = "failed"
    analysis.error_code = AnalysisErrorCode.FRAME_EXTRACT_FAILED
    analysis.error_detail = str(e)
    await db.commit()
    return

try:
    ai_result = await call_ai_api(frames)
except httpx.TimeoutException:
    analysis.error_code = AnalysisErrorCode.AI_API_TIMEOUT
    ...
except httpx.HTTPStatusError as e:
    if e.response.status_code in (401, 403):
        analysis.error_code = AnalysisErrorCode.AI_API_AUTH_ERROR
    elif e.response.status_code == 429:
        analysis.error_code = AnalysisErrorCode.AI_API_QUOTA_EXCEEDED
    ...
```

---

## H-9 后端：错误信息随接口返回

### 修改文件：`backend/app/routers/analysis.py`（GET 单个分析接口）

在返回的 Analysis schema 中包含 `error_code` 字段（`error_detail` 仅家长模式请求时返回，或单独提供 admin 接口）：

```python
class AnalysisResponse(BaseModel):
    id: str
    status: str
    error_code: str | None = None
    error_detail: str | None = None   # 仅在 is_parent_request=True 时填充
    # ... 其他字段
```

---

## H-9 前端：错误信息展示（ReportPage.tsx）

**各 error_code 对应的用户友好提示文案（中文）：**

```tsx
const ERROR_MESSAGES: Record<string, { title: string; hint: string; action: string }> = {
  VIDEO_DECODE_FAILED: {
    title: "视频格式无法识别",
    hint: "请确认视频文件未损坏，建议使用 MP4（H.264）格式",
    action: "重新上传",
  },
  FRAME_EXTRACT_FAILED: {
    title: "视频帧提取失败",
    hint: "视频可能过短（需至少 3 秒）或分辨率过低",
    action: "重新上传",
  },
  AI_API_TIMEOUT: {
    title: "AI 分析超时",
    hint: "可能是网络波动导致，通常重试一次即可解决",
    action: "重新分析",
  },
  AI_API_AUTH_ERROR: {
    title: "API Key 验证失败",
    hint: "请前往「设置 → API 配置」检查 API Key 是否正确填写",
    action: "去设置",
  },
  AI_API_QUOTA_EXCEEDED: {
    title: "API 额度不足",
    hint: "当前 API Key 的调用次数或 Token 额度已用完，请检查账户余额",
    action: "去设置",
  },
  AI_API_CONTENT_FILTER: {
    title: "内容被 AI 安全过滤",
    hint: "视频内容触发了 AI 供应商的安全检查，可尝试更换 AI 供应商",
    action: "重新分析",
  },
  AI_RESPONSE_PARSE_FAIL: {
    title: "AI 返回格式异常",
    hint: "AI 返回了无法解析的内容，通常重试一次即可",
    action: "重新分析",
  },
  REPORT_SAVE_FAILED: {
    title: "报告保存失败",
    hint: "可能是存储空间不足，请检查 NAS 磁盘剩余空间",
    action: "重新分析",
  },
  UNKNOWN_ERROR: {
    title: "未知错误",
    hint: "请查看系统日志，或联系开发者",
    action: "重新分析",
  },
};
```

**错误卡片 UI（ReportPage.tsx，status=failed）：**

```
┌─────────────────────────────────────────┐
│  ❌  AI 分析超时                          │  ← error_code 对应 title
│                                         │
│  可能是网络波动导致，通常重试一次即可解决   │  ← hint
│                                         │
│  错误代码：AI_API_TIMEOUT               │  ← 家长模式显示，方便排查
│                                         │
│  [ 🔄 重新分析 ]   [ ⚙️ 去设置 ]        │  ← action 决定按钮文案和跳转
└─────────────────────────────────────────┘
```

**坦坦/昭昭模式**：只显示 title + 简化提示（「冰宝遇到了一点问题，请让爸爸妈妈来看看 🤔」），不显示技术细节和错误代码。

---

## H-9 前端：Settings 页 API 状态检测

### 修改文件：`frontend/src/pages/SettingsPage.tsx`

家长模式「API 配置」区块，新增「测试连接」按钮，点击后调用后端接口验证 Key 是否可用：

**后端新增接口：`GET /api/settings/test-api`**

```python
@router.get("/test-api")
async def test_api_connection(db: AsyncSession = Depends(get_db)):
    """
    用已保存的 API Key 发送一个极小的 test prompt，
    返回：{"status": "ok", "latency_ms": 342}
    或   {"status": "error", "error_code": "AI_API_AUTH_ERROR", "message": "..."}
    """
```

**前端按钮：**
```
[ 🔌 测试连接 ]
→ loading：「连接中…」
→ 成功：✅ 连接正常（延迟 342ms）
→ 失败：❌ API Key 验证失败 — 请检查 Key 是否正确
```

---

## ✅ Patch H-9 验证清单

- [ ] 数据库新增 `error_code` / `error_detail` 字段，迁移正常
- [ ] 模拟视频解码失败：ReportPage 显示「视频格式无法识别」+ 正确 hint
- [ ] 模拟 API Key 错误（填入无效 Key）：ReportPage 显示「API Key 验证失败」+ 「去设置」按钮
- [ ] 模拟超时（设置极短超时）：显示「AI 分析超时」+ 「重新分析」按钮
- [ ] 坦坦/昭昭模式下错误卡片只显示简化文案，不暴露技术细节
- [ ] Settings 页「测试连接」正常 Key 返回延迟；无效 Key 返回具体错误
- [ ] `error_detail`（原始异常）仅在家长模式下随接口返回，儿童模式 API 不返回该字段

---

---

# 附：Patch H 发送顺序与 Codex 建议

## 推荐顺序

```
H-9（API 报错）→ 验证 H-9      ← 后端改动，先做，后续 UI 依赖结构化 error_code
→ H-6（评分错位）→ 验证 H-6
→ H-1（重试）→ 验证 H-1
→ H-7（列表图标）→ 验证 H-7    ← 依赖 H-1 的 retry 接口
→ H-8（家长进展）→ 验证 H-8
→ H-4（PWA 飘）→ 验证 H-4
→ H-3（触控区域）→ 验证 H-3
→ H-2（模式切换）→ 验证 H-2
→ H-5（产品优化，逐条发）→ 验证
```

## 每次发送 Codex 时的开头模板

```
这是一个已有完整代码的项目（花样滑冰训练分析系统，React 前端 + FastAPI 后端，Docker 部署）。
请在现有代码基础上实现以下 Patch H-X 的内容。
不要重写已有文件，只新增或修改涉及的文件。
所有 API Key 由我手动填入 .env，使用占位符即可。

[粘贴对应 Patch 内容]
```

## Codex 推理设置建议

| Patch | 推理强度 | 原因 |
|---|---|---|
| H-1 | 默认 | 新增接口 + 按钮交互，逻辑清晰 |
| H-2 | 默认 | UI 交互改造，无复杂逻辑 |
| H-3 | 默认 | 纯 CSS 调整 |
| H-4 | 默认 | 配置 + CSS，改动集中 |
| H-5 | 中等（逐条） | 涉及多页面交互和后端接口 |
| H-6 | 默认 | SVG 属性修复，有明确 checklist |
| H-7 | 默认 | 列表 UI 扩展 + 复用 H-1 接口 |
| H-8 | 默认 | 导航配置补充 + 页面视图扩展 |
| H-9 | 中等 | 后端枚举 + 多阶段 try/catch + 前端多 case 处理 |

---

*坦坦和昭昭加油！🐭🐯⛸️*
