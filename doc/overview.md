# media_server 快速上手说明

本文档面向新的 AI/开发者读者，帮助快速理解 `media_server` 的架构、流程与关键实现。

## 目标与边界

- 目标：为 DJI Pilot2 提供媒体管理接口，签发 STS 临时凭证，让 Pilot2 直传 MinIO，并在回调时记录指纹与对象信息。
- 边界：媒体文件不经过本服务转发；本服务只处理元数据与鉴权。

## 目录结构与职责

- `src/media_server/server.py`：入口脚本，负责修正 `sys.path` 并启动服务
- `src/media_server/app.py`：解析配置并启动 HTTPServer，初始化 SQLite
- `src/media_server/config/`：命令行参数与配置对象
- `src/media_server/handler.py`：路由分发与基础请求处理
- `src/media_server/handlers/`：四个核心接口逻辑
- `src/media_server/http_layer/router.py`：URL 匹配
- `src/media_server/storage/sts.py`：向 MinIO STS 请求临时凭证
- `src/media_server/utils/aws_sigv4.py`：SigV4 签名实现
- `src/media_server/storage/s3_client.py`：S3 HEAD 校验对象是否存在
- `src/media_server/utils/http.py`：统一 JSON 响应与 object_key 生成
- `src/media_server/scripts/`：测试脚本与图片生成
- `doc/flow.md`：流程图与架构图

## 验证状态

- 已通过 `src/media_server/scripts/test_refactor_smoke.py`（结构与核心接口解析自检）
- 已通过 `src/media_server/scripts/test_sts_upload.py`（STS -> PUT/HEAD/DELETE 端到端链路）

## 核心接口（已实现）

1) `POST /media/api/v1/workspaces/{workspace_id}/fast-upload`  
   - 输入：`fingerprint`, `name`, `path`, `ext.tinny_fingerprint`  
   - 逻辑：  
     - 若 DB 中已有 fingerprint，则 HEAD OSS 校验；存在则返回 success，否则删除记录并返回 "don't exist"  
     - 若 DB 无记录，返回 "don't exist"

2) `POST /media/api/v1/workspaces/{workspace_id}/files/tiny-fingerprints`  
   - 输入：`tiny_fingerprints[]`  
   - 逻辑：  
     - 对每个 tiny 指纹从 DB 查 object_key  
     - HEAD OSS 成功才返回该 tiny 指纹，否则删除 DB 记录

3) `POST /storage/api/v1/workspaces/{workspace_id}/sts`  
   - 逻辑：向 MinIO STS (AssumeRole) 请求临时凭证并返回

4) `POST /media/api/v1/workspaces/{workspace_id}/upload-callback`  
   - 逻辑：写入数据库（fingerprint/tiny/object_key/name/path）

> `folderUploadCallback` 在 DJI Demo 中为空实现，当前未支持。

## SQLite 持久化

默认路径：`data/media.db`（可通过 `--db-path` 指定）

表：`media_files`

字段：

- `workspace_id`（分区维度）
- `fingerprint`（完整指纹，唯一）
- `tiny_fingerprint`（精简指纹）
- `object_key`（OSS 对象路径）
- `file_name` / `file_path`
- `created_at`

索引：

- `UNIQUE(workspace_id, fingerprint)`
- `idx_media_tiny(workspace_id, tiny_fingerprint)`

写入时机：

- 仅在 `upload-callback` 时写入（确保文件真实上传成功）

删除时机：

- `fast-upload` / `tiny-fingerprints` 中 HEAD 失败会删除对应记录

## object_key 规则

当前规则：

```txt
media/{workspace_id}/{YYYYMMDD}/{filename}
```

`filename` 来自 Pilot2 的 `name` 字段。

## 运行依赖

- Python 3.8+（标准库）
- MinIO（Docker 启动）
- SQLite（Python 内置，无需安装）

## 常见调试入口

- 媒体服务日志：查看 `fast-upload / tiny-fingerprints / sts / upload-callback`
- MinIO trace：`mc admin trace local --all`（可用 `rg` 过滤 `s3.PutObject/HeadObject/DeleteObject`）
- SQLite：直接查看 `data/media.db`

## 与 Pilot2 的交互顺序

1) `fast-upload`（是否存在）  
2) `tiny-fingerprints`（批量查重）  
3) `sts`（临时凭证）  
4) Pilot2 直传 MinIO  
5) `upload-callback`（落库）
