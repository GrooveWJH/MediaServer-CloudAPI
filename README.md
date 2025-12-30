# 媒体管理服务（DJI Pilot2 对接）

本目录提供一个可运行的媒体管理服务（Python 标准库实现），配合 MinIO 对象存储即可让 DJI Pilot2 自动上传媒体文件。

## 目录结构

- `src/media_server/server.py` 服务入口（保持原用法）
- `src/media_server/app.py` 服务启动与配置加载
- `src/media_server/handler.py` 路由分发与基础请求处理
- `src/media_server/handlers.py` 各接口处理逻辑
- `src/media_server/sts.py` MinIO STS 交互
- `src/media_server/aws_sigv4.py` SigV4 签名
- `src/media_server/s3_client.py` S3 HEAD 校验对象存在
- `src/media_server/db.py` SQLite 持久化
- `src/media_server/http_utils.py` 通用响应与 object_key 生成
- `src/media_server/router.py` 路径匹配
- `src/media_server/scripts/test_sts_upload.py` STS + MinIO 直传自测脚本
- `src/media_server/scripts/image_gen.py` 生成随机 PNG 测试图
- `doc/flow.md` 执行流程与架构图
- `doc/overview.md` 面向 AI/开发者的快速说明

## 依赖

- Python 3.8+
- Docker（启动 MinIO）
- SQLite（内置，无需额外安装）

## 端口说明

- 媒体服务：`8090`
- MinIO API：`9000`
- MinIO Console：`9001`

## 1. 启动 MinIO（Docker）

```bash
docker rm -f fc-minio 2>/dev/null || true

docker run -d --name fc-minio --restart unless-stopped \
  -p 9000:9000 -p 9001:9001 \
  -e MINIO_ROOT_USER=minioadmin \
  -e MINIO_ROOT_PASSWORD=minioadmin \
  minio/minio server /data --console-address ":9001"
```

命令说明：

- `docker rm -f fc-minio 2>/dev/null || true`：清理同名旧容器，避免端口冲突；如果不存在则忽略错误。
- `docker run -d --name fc-minio --restart unless-stopped ...`：以后台方式启动 MinIO 容器并设置自动重启。
- `-p 9000:9000 -p 9001:9001`：映射 API 端口与控制台端口到宿主机。
- `-e MINIO_ROOT_USER/ROOT_PASSWORD`：设置 MinIO 管理账号密码。
- `minio/minio server /data --console-address ":9001"`：启动对象存储服务并启用控制台端口。

打开 MinIO 控制台：`http://<你的电脑IP>:9001`（账号/密码：`minioadmin` / `minioadmin`）。

## 2. 创建 bucket

使用 MinIO 客户端创建 `media` 桶：

```bash
mkdir -p /tmp/mc

docker run --rm -v /tmp/mc:/root/.mc minio/mc \
  alias set local http://192.168.10.16:9000 minioadmin minioadmin

docker run --rm -v /tmp/mc:/root/.mc minio/mc mb local/media
```

命令说明：

- `mkdir -p /tmp/mc`：创建本机目录用于保存 `mc` 客户端配置（别名、凭证）。
- `docker run --rm -v /tmp/mc:/root/.mc minio/mc alias set ...`：用临时容器运行 `mc` 客户端，创建名为 `local` 的别名并保存到 `/tmp/mc`。
- `docker run --rm -v /tmp/mc:/root/.mc minio/mc mb local/media`：在 MinIO 上创建名为 `media` 的桶。

说明：macOS 上用 `host.docker.internal` 也可以访问宿主机端口。

## 3. 启动媒体管理服务

把 `storage-endpoint` 指向你电脑的局域网 IP（RC 需要访问），服务端会向 MinIO STS 申请临时凭证：

```bash
python3 src/media_server/server.py \
  --host 0.0.0.0 --port 8090 --token demo-token \
  --storage-endpoint http://yourIP:9000 \
  --storage-bucket media \
  --storage-region us-east-1 \
  --storage-access-key minioadmin \
  --storage-secret-key minioadmin \
  --storage-sts-role-arn arn:aws:iam::minio:role/dji-pilot \
  --db-path data/media.db \
  --log-level info
```

命令说明：

- `python3 src/media_server/server.py`：启动媒体管理服务入口。
- `--host 0.0.0.0 --port 8090`：对外监听地址与端口，便于 RC 访问。
- `--token demo-token`：Pilot2 调用媒体服务时使用的固定鉴权令牌。
- `--storage-endpoint http://yourIP:9000`：MinIO API 地址，必须是 RC 能访问到的局域网 IP。
- `--storage-bucket media`：对象存储桶名。
- `--storage-region us-east-1`：S3 兼容区域标识（MinIO 任意填写即可，保持一致）。
- `--storage-access-key/--storage-secret-key`：MinIO 管理账号密码。
- `--storage-sts-role-arn ...`：申请 STS 临时凭证时使用的 RoleArn。
- `--db-path`：SQLite 数据库文件路径（用于持久化 fingerprint / tiny_fingerprint）。

服务启动后会看到：`Media server listening on 0.0.0.0:8090`。

参数说明：

- `storage-endpoint` 用你电脑的局域网 IP，RC 才能连到
- `storage-access-key/secret-key` 与 MinIO 启动参数一致
- `storage-provider` 默认 `minio`（对应 DJI 的 OssTypeEnum）
- `storage-sts-role-arn` 为 STS 颁发临时凭证使用的 RoleArn（MinIO 不强校验，可保持默认）
- `storage-sts-policy` 可选，JSON 字符串（用于限制临时凭证权限）
- `storage-sts-duration` 临时凭证有效期（秒）
- `db-path` SQLite 数据库文件路径（用于持久化 fingerprint / tiny_fingerprint）
- `log-level` 日志级别（debug/info/warning/error/critical），默认 `info`

## 4. RC WebView 配置

1) 媒体管理地址：`<你的电脑IP>:8090`  
2) Token：与服务端一致（默认 `demo-token`）  
3) 确保 RC 与电脑在同一局域网

## 4.1 Web 浏览器（Flask）

提供一个基础 Web 页面，实时读取 SQLite 并通过 MinIO 预览图片，支持删除（同时删除 DB 与对象存储）。

依赖安装（仅该页面需要）：

```bash
python3 -m pip install flask
```

启动（在 MinIO + `server.py` 启动后执行）：

```bash
python3 web/app.py \
  --db-path data/media.db \
  --storage-endpoint http://yourIP:9000 \
  --storage-bucket media \
  --storage-region us-east-1 \
  --storage-access-key minioadmin \
  --storage-secret-key minioadmin
```

访问：`http://<你的电脑IP>:8088`

## 5. 验证流程

### 5.1 服务连通性

在 RC 上点击“状态检查”，日志显示：

```
[Media模块] 服务可达: http://<你的电脑IP>:8090 (200)
[存储] 服务可达: http://<你的电脑IP>:9000 (200)
```

### 5.2 Pilot2 自动上传

在 Pilot2 上拍一张新照片，服务端日志应出现：

- `fast-upload`
- `tiny-fingerprints`
- `sts`
- `upload-callback`

### 5.3 STS + 上传自测脚本

先跑自测脚本，确认 STS 与 MinIO 直传链路可用：

```bash
python3 src/media_server/scripts/test_sts_upload.py \
  --media-host http://127.0.0.1:8090 \
  --workspace-id <你的workspace_id> \
  --token demo-token
```

命令说明：

- `--media-host`：媒体服务地址（本机测试用 `127.0.0.1`）。
- `--workspace-id`：工作空间 ID，用于生成 object_key 前缀。
- `--token`：与媒体服务一致的固定令牌。
- 默认上传随机 PNG 图片（约 10MB）；若要上传文本，额外加 `--text --payload "..."`。
- 可用 `--image-size 1024x1024` 指定尺寸，或 `--image-mb 10` 指定目标大小。

脚本会执行 PUT/HEAD/DELETE。删除是预期行为，因此 MinIO 控制台里可能看不到对象。

## 6. 调试指南

### 6.1 查看媒体服务日志

直接看 `server.py` 输出即可，常见关键字：

- `sts`：Pilot2 成功拿到临时凭证
- `fast-upload`：Pilot2 上报文件元信息
- `tiny-fingerprints`：Pilot2 查重
- `upload-callback`：上传完成回调

### 6.2 实时查看 MinIO 请求（强烈推荐）

MinIO 默认日志不会输出每条请求，使用 `mc admin trace`：

```bash
docker run --rm -v /tmp/mc:/root/.mc minio/mc \
  alias set local http://192.168.10.16:9000 minioadmin minioadmin

docker run --rm -v /tmp/mc:/root/.mc minio/mc \
  admin trace local --all
```

命令说明：

- `alias set ...`：确保 `mc` 有可用的 `local` 别名（会读取/写入 `/tmp/mc`）。
- `admin trace local --all`：实时追踪所有请求，便于确认 PUT/HEAD/DELETE 是否发生。

执行自测脚本或 Pilot2 上传时，你会看到 PUT/HEAD/DELETE。

### 6.3 查看桶内容

```bash
docker run --rm -v /tmp/mc:/root/.mc minio/mc ls local/media
```

命令说明：

- `mc ls local/media`：列出 `media` 桶中的对象，用于快速验证是否有上传结果。

### 6.4 精简 trace 输出（只看 S3 相关）

如果 trace 日志里噪声太多，可用 `rg` 过滤出 S3 请求：

```bash
docker run --rm -v /tmp/mc:/root/.mc minio/mc \
  admin trace local --all 2>&1 | rg 's3\.(PutObject|HeadObject|DeleteObject|GetObject)'
```

命令说明：

- `admin trace ...`：实时追踪 MinIO 请求。
- `2>&1`：合并 stderr，避免 trace 输出不进管道导致 `rg` 无结果。
- `rg ...`：只保留 S3 的 PUT/HEAD/DELETE/GET 相关行，忽略 `.minio.sys` 维护日志。

### 6.5 常见问题

- 只有 `sts`：凭证已发放，但 Pilot2 未上传（可能未触发拍照、网络不可达或 STS 签名无效）
- 没有 `upload-callback`：上传未完成或上传失败
- MinIO Console 看不到对象：自测脚本会 DELETE（正常）
- RC 连不上：检查防火墙是否阻止 `8090/9000` 端口
- 指纹持久化位置：默认 `data/media.db`

## object_key 规则

服务端生成：

```
media/{workspace_id}/{YYYYMMDD}/{filename}
```

文件名中的 `/` 会替换为 `_`。
