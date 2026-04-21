# 花样滑冰训练分析系统 Design System v3

## 颜色系统

### 儿童模式

```css
--kid-primary:   #6C63FF;
--kid-secondary: #FF6B9D;
--kid-accent:    #FFD93D;
--kid-success:   #4CAF50;
--kid-bg:        #F8F6FF;
```

### 家长模式

```css
--parent-primary: #0F172A;
--parent-accent:  #3B82F6;
--parent-success: #22C55E;
--parent-warning: #F59E0B;
--parent-danger:  #EF4444;
--parent-bg:      #FAFAFA;
--parent-surface: #FFFFFF;
--parent-border:  #E5E7EB;
```

### 技能分支固定色

```css
--branch-jump:     #6C63FF;
--branch-spin:     #3B82F6;
--branch-step:     #F59E0B;
--branch-basic:    #22C55E;
--branch-snowplow: #EC4899;
```

### 发力评分颜色

```css
--score-high: #22C55E;
--score-mid:  #F59E0B;
--score-low:  #EF4444;
```

### 路径技能状态颜色

```css
--node-unlocked-bg:  #E0F7F4;
--node-unlocked-dot: #4CAF50;
--node-inprogress-bg:  #FFF3E0;
--node-inprogress-dot: #F59E0B;
--node-locked-bg:  #F3F4F6;
--node-locked-dot: #9CA3AF;
```

## 字体系统

```css
--font-sans: -apple-system, BlinkMacSystemFont, "PingFang SC",
             "Hiragino Sans GB", "Helvetica Neue", sans-serif;
--text-xs:       12px;
--text-sm:       14px;
--text-base:     16px;
--text-lg:       18px;
--text-xl:       20px;
--text-2xl:      24px;
--text-3xl:      30px;
--text-kid-emoji: 48px;
--text-kid-hero:  64px;
```

## 三端断点

```js
screens: {
  phone: "375px",
  tablet: "768px",
  ipad: "1024px",
  web: "1280px",
  wide: "1440px",
}
```

## 触控目标规范

```css
--touch-min: 44px;
--touch-kid: 56px;
```

## 布局规范

- `BottomNav`：手机和 iPad 固定底部，高度 `49px + safe-area`。
- `BottomNav`：网页端切换为左侧 `240px` 固定侧边导航。
- `ReviewPage`：手机单列，iPad 居中单列，网页端左流程右预览。
- `ArchivePage`：手机统计 + 时间轴，网页端左筛选右时间轴。
- `SkillTreePage`：学习路径与冰面路线图双视图，网页端阶段导航置左。
- `ReportPage`：手机单列，iPad 上下分区，网页端左右双列。

## 动效

```css
@keyframes shimmer {
  0%   { transform: translateX(-100%) skewX(-12deg); }
  100% { transform: translateX(400%) skewX(-12deg); }
}

@keyframes float {
  0%, 100% { transform: translateY(0px); }
  50%       { transform: translateY(-8px); }
}

@keyframes unlock-pop {
  0%   { transform: scale(0) rotate(-10deg); opacity: 0; }
  60%  { transform: scale(1.2) rotate(5deg);  opacity: 1; }
  100% { transform: scale(1) rotate(0deg);    opacity: 1; }
}
```
