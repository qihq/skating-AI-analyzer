# 群晖部署 Step by Step

这个文档对应的是 `all-in-one` 单镜像方案。

你最终拿到的是一个 `tar` 镜像包，导入群晖后只需要创建 1 个容器，不需要再分别拉前端、后端、备份三个容器。

## 1. 你会用到的文件

请准备下面两个东西：

1. 镜像包：`dist/skating-analyzer-allinone-latest.tar`
2. 环境变量参考：`.env.example`

如果你已经让我导出过镜像，直接把 `tar` 上传到群晖即可。

## 2. 先在群晖创建目录

建议先在群晖的共享文件夹里创建下面两个目录：

1. `/volume1/docker/skating-analyzer/data`
2. `/volume1/docker/skating-analyzer/backups`

说明：

- `data` 用来放数据库、上传视频、抽帧图片、归档文件
- `backups` 用来放应用内创建的备份 zip

## 3. 导入镜像

在群晖 DSM 里操作：

1. 打开 `Container Manager`
2. 进入 `映像` 或 `镜像`
3. 点击 `新增` / `导入`
4. 选择 `从文件添加`
5. 选中 `skating-analyzer-allinone-latest.tar`
6. 等待导入完成

导入成功后，你会看到镜像名类似：

`skating-analyzer-allinone:latest`

## 4. 创建容器

1. 在镜像列表里选中 `skating-analyzer-allinone:latest`
2. 点击 `运行`
3. 容器名称建议填：`skating-analyzer`

## 5. 配置端口

这个 all-in-one 镜像容器内部只暴露一个端口：

- 容器端口：`80`

建议映射：

- 本地端口：`8080`
- 容器端口：`80`

这样浏览器访问：

`http://群晖IP:8080`

如果你想占用 80 端口，也可以把本地端口改成 `80`，但前提是群晖上没有别的服务占用它。

## 6. 配置卷映射

在 `存储空间` / `卷` / `Volume` 里添加 2 条映射：

1. 群晖目录 `/volume1/docker/skating-analyzer/data` 映射到容器 `/data`
2. 群晖目录 `/volume1/docker/skating-analyzer/backups` 映射到容器 `/backups`

这一步很重要。

如果不映射，数据库和上传的视频会留在容器里，删容器后数据就没了。

## 7. 配置环境变量

在 `环境` / `Environment` 里至少添加下面这些变量：

### 必填

- `SECRET_KEY=你自己生成的32位以上随机字符串`

### 推荐填写

- `QWEN_API_KEY=你的Qwen Key`
- `DEEPSEEK_API_KEY=你的DeepSeek Key`

### 可选

- `DASHSCOPE_API_KEY=你的DashScope Key`
- `DATA_DIR=/data`
- `DATABASE_URL=sqlite+aiosqlite:////data/skating-analyzer.db`

说明：

- `SECRET_KEY` 必填，否则应用无法加解密保存的 API Key
- `QWEN_API_KEY` 和 `DEEPSEEK_API_KEY` 现在都可以先不填，后续进系统后再在“API 设置”页面里分别配置文本模型和视觉模型
- `DATA_DIR` 和 `DATABASE_URL` 不填也通常可以跑，因为镜像默认就是按 `/data` 设计的

## 8. 启动容器

确认下面内容无误后启动：

1. 端口映射正确
2. `/data` 和 `/backups` 已映射
3. `SECRET_KEY` 已填写
4. AI Key 已按需填写

然后点击 `完成` 或 `启动`

## 9. 首次启动检查

启动后，打开浏览器访问：

`http://群晖IP:8080`

也可以直接检查健康接口：

`http://群晖IP:8080/api/health`

正常应返回类似：

```json
{"status":"ok"}
```

## 10. 首次启动后会生成什么

应用第一次启动后，通常会在 `/volume1/docker/skating-analyzer/data` 下看到：

- `skating-analyzer.db`
- `uploads/`
- `archive/`

在 `/volume1/docker/skating-analyzer/backups` 下，只有你手动做备份后才会出现 zip 备份文件。

## 10.1 首次进入系统后怎么配视觉模型

现在系统里已经有独立的视觉模型配置入口，不需要再把视觉 key 强行写进群晖环境变量。

操作顺序：

1. 先用浏览器打开系统
2. 进入 `家长设置`
3. 打开 `API 设置`
4. 在页面下半部分找到 `视觉模型配置`
5. 选择你要用的视觉供应商，例如 `Qwen 3.6 Plus`
6. 填入该视觉供应商的 `API Key`
7. 填入视觉主模型 ID
8. 点击 `保存配置`
9. 再点一次 `测试连接`
10. 如果需要，把它设为当前视觉供应商

说明：

- `文本模型配置` 和 `视觉模型配置` 现在是分开的
- 报告、训练计划、聊天走文本模型
- 视频抽帧识别和动作视觉分析走视觉模型
- 所有后来在系统里保存的 key，都会由 `SECRET_KEY` 加密后再写入数据库

## 11. 后续更新镜像怎么做

以后如果我给你重新导出一个新的 `tar`：

1. 先停止旧容器
2. 导入新的镜像 tar
3. 用新镜像重新创建容器
4. 继续复用原来的两个映射目录：
   `/volume1/docker/skating-analyzer/data`
   `/volume1/docker/skating-analyzer/backups`

只要这两个目录不变，数据库和历史视频数据就会保留。

## 12. 常见问题

### 打不开页面

先检查：

1. 群晖防火墙是否放行端口
2. 端口是不是映射成了 `8080 -> 80`
3. 是否访问了正确地址 `http://群晖IP:8080`

### 页面能开，但 AI 不能分析

先检查环境变量：

1. `SECRET_KEY` 是否存在
2. `QWEN_API_KEY` 或 `DEEPSEEK_API_KEY` 是否填了正确值

### 重建容器后数据丢了

通常是因为没有做卷映射，或者 `/data` 没映射到群晖目录。

### 上传视频失败

这个镜像已经把 Nginx 上传限制配成了 `500m`。如果你的视频超过 500MB，需要后续再调大。

## 13. 本地重新导出镜像命令

如果你以后要自己重新导出：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\export-allinone-image.ps1
```

导出完成后，镜像包默认在：

`dist/skating-analyzer-allinone-latest.tar`
