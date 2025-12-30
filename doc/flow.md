# 媒体服务执行流程说明

本文档描述 `media_server` 的整体执行逻辑、关键状态与上传链路，便于理解 Pilot2 与对象存储的交互方式。

## 核心组件

- `src/media_server/server.py`：入口，负责启动服务
- `src/media_server/app.py`：解析配置并初始化 HTTPServer
- `src/media_server/handler.py`：路由分发与基础请求处理
- `src/media_server/handlers.py`：业务逻辑（fast-upload / tiny-fingerprints / sts / upload-callback）
- `src/media_server/sts.py` + `src/media_server/aws_sigv4.py`：向 MinIO STS 获取临时凭证
- `src/media_server/s3_client.py`：HEAD 校验对象是否真实存在

## 服务内存状态

- `uploaded_fingerprints`：已确认上传成功的 fingerprint 集合
- `tiny_fingerprint_index`：已确认上传成功的 tiny 指纹集合
- `pending_tiny_by_fingerprint`：fast-upload 收到的 fingerprint → tiny 指纹映射（尚未确认上传）
- `object_key_by_fingerprint`：fingerprint → object_key
- `object_key_by_tiny`：tiny 指纹 → object_key

这些状态只存在于内存中，服务重启会清空。

## 关键逻辑规则

1) **fast-upload**  
   - 先判断 fingerprint 是否已记录为上传成功  
   - 若已记录，会对 MinIO 执行 HEAD 校验  
   - HEAD 成功 → 返回 success（表示已存在）  
   - HEAD 失败 → 删除指纹记录并返回 “don’t exist”  

2) **tiny-fingerprints**  
   - 对每个 tiny 指纹执行 HEAD 校验  
   - HEAD 成功 → 返回该 tiny 指纹  
   - HEAD 失败 → 从内存索引删除该 tiny 指纹  

3) **sts**  
   - 向 MinIO STS 请求临时凭证  
   - 返回 `credentials` 给 Pilot2  

4) **upload-callback**  
   - 仅在文件真实上传成功后触发  
   - 写入 fingerprint/tiny 指纹索引与 object_key 映射  

## 执行流程（PlantUML）

```plantuml
@startuml
title DJI Pilot2 媒体上传流程（当前实现）

participant Client as "DJI Pilot2"
participant Server as "Cloud Server"
participant OSS as "Object Storage (MinIO)"

== fast-upload 判定 ==
Client -> Server: POST /media/.../fast-upload
Server -> Server: 记录 fingerprint -> tiny 映射\n(仅缓存，不标记已存在)
Server -> Server: 若 fingerprint 已上传过\n则 HEAD OSS 校验
alt 文件已存在
  Server --> Client: success (已存在)
else 文件不存在
  Server -> Server: 清理 fingerprint 记录
  Server --> Client: error (don't exist)
end

== tiny-fingerprints 判定 ==
Client -> Server: POST /media/.../files/tiny-fingerprints
Server -> Server: 对每个 tiny 指纹 HEAD OSS 校验
alt tiny 指纹存在
  Server --> Client: 返回 tiny 指纹列表
else tiny 指纹缺失
  Server -> Server: 删除 tiny 指纹记录
  Server --> Client: 不返回该指纹
end

== 获取 STS ==
Client -> Server: POST /storage/.../sts
Server -> OSS: AssumeRole (STS)
OSS --> Server: 临时凭证
Server --> Client: credentials

== 上传 ==
Client -> OSS: PUT Object (上传媒体文件)
OSS --> Client: 200 OK

== 回调 ==
Client -> Server: POST /media/.../upload-callback
Server -> Server: 记录 fingerprint/tiny/object_key\n标记为已上传
Server --> Client: success
@enduml
```

## 架构图（PlantUML）

```plantuml
@startuml
title media_server 架构图

package "media_server" {
  [server.py] --> [app.py]
  [app.py] --> [config.py]
  [app.py] --> [handler.py]

  [handler.py] --> [router.py]
  [handler.py] --> [handlers.py]

  [handlers.py] --> [http_utils.py]
  [handlers.py] --> [sts.py]
  [handlers.py] --> [s3_client.py]

  [sts.py] --> [aws_sigv4.py]
  [s3_client.py] --> [aws_sigv4.py]
}

database "MinIO (OSS)" as OSS
[sts.py] ..> OSS : STS AssumeRole
[s3_client.py] ..> OSS : HEAD Object

@enduml
```

## 常见现象

- 只有 fast-upload / tiny-fingerprints：说明上传未触发或被判定为已存在
- 没有 upload-callback：上传没完成或 OSS 不可达
- MinIO 没有 PUT：检查 fast-upload 是否误返回 success
