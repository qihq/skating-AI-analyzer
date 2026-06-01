# CodeGraph 使用说明

本项目已经初始化 [CodeGraph](https://github.com/colbymchenry/codegraph)，本地索引位于 `.codegraph/codegraph.db`。这个数据库只用于本机代码检索和调用关系分析，已经通过 `.gitignore` 忽略，不需要提交。

CodeGraph 的作用不是生成一张静态图片，而是把仓库解析成本地代码知识图谱，方便查询符号、调用链、影响范围，并为 AI 任务生成更聚焦的上下文。

## 环境要求

- Node.js 24 已验证可用。
- 当前项目验证版本：`@colbymchenry/codegraph` `0.9.8`。
- 可以直接使用 `npx`，无需全局安装。

进入项目根目录：

```powershell
cd C:\Users\qihq\Documents\skating-analyzer
```

## 常用命令

查看索引状态：

```powershell
npx -y @colbymchenry/codegraph status
```

代码变更后同步索引：

```powershell
npx -y @colbymchenry/codegraph sync
```

搜索函数、类、变量等符号：

```powershell
npx -y @colbymchenry/codegraph query analyze_frames
npx -y @colbymchenry/codegraph query vision_path_a --limit 10
```

查看项目文件结构：

```powershell
npx -y @colbymchenry/codegraph files
```

查询谁调用了某个函数：

```powershell
npx -y @colbymchenry/codegraph callers analyze_frames
```

查询某个函数调用了哪些函数：

```powershell
npx -y @colbymchenry/codegraph callees analyze_path_a
```

分析修改某个符号会影响哪些代码：

```powershell
npx -y @colbymchenry/codegraph impact analyze_frames
```

为一个开发任务生成 AI 上下文：

```powershell
npx -y @colbymchenry/codegraph context "修复视频分析里 analyze_frames 的错误处理"
```

## 推荐工作流

1. 改代码前，用 `query` 找入口函数或相关类。
2. 用 `callers` 和 `callees` 查看调用关系，确认改动边界。
3. 大改共享函数前，用 `impact` 检查影响范围。
4. 改完代码后，运行 `sync` 更新本地索引。
5. 需要让 AI 处理复杂任务时，用 `context` 生成任务上下文。

## 本项目示例

查找主视觉分析入口：

```powershell
npx -y @colbymchenry/codegraph query analyze_frames
```

分析 `analyze_frames` 的上游调用：

```powershell
npx -y @colbymchenry/codegraph callers analyze_frames
```

分析 Path A 视觉流程会调用哪些函数：

```powershell
npx -y @colbymchenry/codegraph callees analyze_path_a
```

评估修改目标锁定逻辑的影响范围：

```powershell
npx -y @colbymchenry/codegraph impact target_lock
```

为 AI 生成视频分析管线修复上下文：

```powershell
npx -y @colbymchenry/codegraph context "定位视频语义时间戳和关键帧抽取之间的数据流"
```

## 当前索引概况

最近一次索引结果：

- 文件：`232`
- 节点：`5,308`
- 边：`11,935`
- 数据库大小：`13.67 MB`
- 主要语言：Python、TSX、TypeScript、JavaScript、YAML

如果 `status` 显示索引过期，运行：

```powershell
npx -y @colbymchenry/codegraph sync
```

如果索引锁异常，可以解除 stale lock：

```powershell
npx -y @colbymchenry/codegraph unlock
```

## 可选：全局安装

如果不想每次输入完整的 `npx -y @colbymchenry/codegraph`，可以全局安装：

```powershell
npm install -g @colbymchenry/codegraph
```

之后可以直接运行：

```powershell
codegraph status
codegraph query analyze_frames
codegraph sync
```
