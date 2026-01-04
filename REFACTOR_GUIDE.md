# 重构指南 - Media Server 代码审查

**审查者视角：Linus Torvalds**
**审查日期：2026-01-04**
**品味评分：🟡 凑合 - 能用但充满坏品味**

---

## 核心判断

这个代码库能跑，但到处都是坏品味的痕迹。最大的问题不是"它不工作"，而是**数据结构一团糟、到处都是重复代码、特殊情况满天飞**。任何一个看过优秀代码的人都会看出这是仓促拼凑的产物。

### 关键洞察

1. **数据结构混乱**：`MediaRequestHandler` 中有 7 个类级别的共享状态，这是灾难性的设计
2. **复杂度爆炸**：重复的路由匹配、重复的 S3 客户端代码、重复的配置解析
3. **风险点**：`BaseHTTPRequestHandler` 的类变量在多线程环境下会炸，SQLite 连接管理是定时炸弹

---

## 第一层：数据结构分析

> "Bad programmers worry about the code. Good programmers worry about data structures."

### 致命问题 #1：Handler 的全局状态混乱

**垃圾代码：**
```python
class MediaRequestHandler(BaseHTTPRequestHandler):
    server_version = "FCMediaServer/0.1"
    tiny_fingerprint_index = {}                # 类变量！
    pending_tiny_by_fingerprint = {}           # 多线程会炸！
    uploaded_fingerprints = set()              # 竞态条件！
    object_key_by_fingerprint = {}             # 为什么这里存一份？
    object_key_by_tiny = {}                    # 为什么又存一份？
    upload_records = []                        # list 在多线程下不安全
    config = None                              # 这个倒还行
    db = None                                  # 这个也行
```

**问题分析：**
- 前面 5 个字典和 1 个列表是**状态的重复**：DB 里已经存了，为什么还要在内存里再存一份？
- 这些类变量在 `BaseHTTPRequestHandler` 的多线程模型下是**共享的**，会有竞态条件
- `pending_tiny_by_fingerprint` 只在 `fast-upload` 时写入，`upload-callback` 时读取，这是临时状态，应该用更好的方式传递

**好品味方案：**
```python
class MediaRequestHandler(BaseHTTPRequestHandler):
    server_version = "FCMediaServer/0.1"
    config = None  # 只读配置
    db = None      # 数据库接口

    # 删除所有内存缓存！数据库就是单一真相来源。
    # 如果性能不够，加一个正确的缓存层，而不是这种随意的字典。
```

**核心原则：**
- **单一真相来源（Single Source of Truth）**：数据要么在数据库，要么在缓存，不要既在内存又在 DB
- **无状态处理器**：每个请求应该是独立的，不依赖类变量
- 如果真的需要临时状态传递（如 tiny_fingerprint），用 DB 的事务或者请求级别的 context

---

### 致命问题 #2：数据库连接管理是定时炸弹

**垃圾代码：**
```python
class MediaDB:
    def _connect(self):
        return sqlite3.connect(self.path, check_same_thread=False)  # 每次都新建连接！

    def upsert_file(self, ...):
        with self._lock, self._connect() as conn:  # 锁和连接混在一起
            conn.execute(...)
```

**问题分析：**
- 每次操作都打开新连接，性能垃圾
- `check_same_thread=False` 是在用胶带修补多线程问题，而不是解决问题
- `with self._connect() as conn` 每次都新建连接，连接池呢？

**好品味方案：**
```python
class MediaDB:
    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self._conn = None
        self._init_connection()

    def _init_connection(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._conn = sqlite3.connect(
            self.path,
            check_same_thread=False,
            isolation_level=None  # 自动提交模式
        )
        self._init_schema()

    def _execute(self, query, params=()):
        with self._lock:
            return self._conn.execute(query, params)
```

**如果真的在意性能，用连接池：**
```python
from queue import Queue

class MediaDB:
    def __init__(self, path, pool_size=5):
        self._pool = Queue(maxsize=pool_size)
        for _ in range(pool_size):
            conn = sqlite3.connect(path, check_same_thread=False)
            self._pool.put(conn)

    def _execute(self, query, params=()):
        conn = self._pool.get()
        try:
            return conn.execute(query, params)
        finally:
            self._pool.put(conn)
```

但说实话，对于这个项目，单个连接 + 锁就够了。**过度设计和设计不足一样糟糕**。

---

### 致命问题 #3：配置对象是个巨大的 Bag

**垃圾代码：**
```python
@dataclass
class ServerConfig:
    host: str
    port: int
    token: str
    storage_endpoint: str
    storage_bucket: str
    storage_region: str
    storage_access_key: str
    storage_secret_key: str
    storage_session_token: str
    storage_provider: str
    storage_sts_role_arn: str
    storage_sts_policy: str
    storage_sts_duration: int
    db_path: str
    log_level: str
```

**问题分析：**
- 这是个 15 字段的大杂烩，没有逻辑分组
- `host`、`port` 是服务器配置，`storage_*` 是存储配置，混在一起
- 每次需要传整个 `config` 对象，实际上只需要一部分

**好品味方案：**
```python
@dataclass
class ServerConfig:
    host: str
    port: int
    token: str
    log_level: str
    db_path: str

@dataclass
class StorageConfig:
    endpoint: str
    bucket: str
    region: str
    access_key: str
    secret_key: str
    session_token: str = ""
    provider: str = "minio"

@dataclass
class STSConfig:
    role_arn: str
    policy: str = ""
    duration: int = 3600

@dataclass
class AppConfig:
    server: ServerConfig
    storage: StorageConfig
    sts: STSConfig
```

**数据结构清晰 = 代码自然清晰**。当你需要传 S3 配置时，只传 `StorageConfig`，而不是整个 `AppConfig`。

---

## 第二层：特殊情况识别

> "好代码没有特殊情况"

### 问题 #1：路由匹配的重复代码

**垃圾代码：**
```python
def match_fast_upload(path):
    parts = [p for p in path.split("/") if p]
    if len(parts) != 6:
        return None
    if parts[0] != "media" or parts[1] != "api" or parts[2] != "v1":
        return None
    if parts[3] != "workspaces" or parts[5] != "fast-upload":
        return None
    return parts[4]

def match_tiny_fingerprints(path):
    parts = [p for p in path.split("/") if p]
    if len(parts) != 7:  # 唯一的区别！
        return None
    if parts[0] != "media" or parts[1] != "api" or parts[2] != "v1":
        return None
    if parts[3] != "workspaces" or parts[5] != "files" or parts[6] != "tiny-fingerprints":
        return None
    return parts[4]

def match_upload_callback(path):
    # 又来一遍！
    ...

def match_sts(path):
    # 再来一遍！只是 media 变成 storage！
    ...
```

**问题分析：**
- 4 个函数，几乎完全相同的逻辑
- 每个函数都在重复 `parts[0-3]` 的检查
- 这是教科书级别的代码坏味道

**好品味方案：**
```python
def parse_workspace_path(path, prefix, endpoint):
    """
    解析类似 /{prefix}/api/v1/workspaces/{workspace_id}/{endpoint} 的路径。
    返回 workspace_id，失败返回 None。
    """
    parts = [p for p in path.split("/") if p]

    # 期望的长度根据 endpoint 中的斜杠数量决定
    endpoint_parts = [p for p in endpoint.split("/") if p]
    expected_len = 5 + len(endpoint_parts)

    if len(parts) != expected_len:
        return None
    if parts[0] != prefix or parts[1] != "api" or parts[2] != "v1":
        return None
    if parts[3] != "workspaces":
        return None

    # 检查 endpoint 部分
    for i, ep in enumerate(endpoint_parts):
        if parts[5 + i] != ep:
            return None

    return parts[4]  # workspace_id

# 使用
workspace_id = parse_workspace_path(path, "media", "fast-upload")
workspace_id = parse_workspace_path(path, "media", "files/tiny-fingerprints")
workspace_id = parse_workspace_path(path, "storage", "sts")
```

**更好的方案（正则表达式）：**
```python
import re

ROUTES = {
    "fast_upload": re.compile(r"^/media/api/v1/workspaces/([^/]+)/fast-upload$"),
    "tiny_fingerprints": re.compile(r"^/media/api/v1/workspaces/([^/]+)/files/tiny-fingerprints$"),
    "upload_callback": re.compile(r"^/media/api/v1/workspaces/([^/]+)/upload-callback$"),
    "sts": re.compile(r"^/storage/api/v1/workspaces/([^/]+)/sts$"),
}

def match_route(path):
    """返回 (route_name, workspace_id) 或 (None, None)"""
    for name, pattern in ROUTES.items():
        match = pattern.match(path)
        if match:
            return name, match.group(1)
    return None, None
```

**使用：**
```python
def do_POST(self):
    route, workspace_id = match_route(urlparse(self.path).path)
    if not route:
        json_response(self, HTTPStatus.NOT_FOUND, {"code": 404, ...})
        return

    handlers = {
        "fast_upload": handle_fast_upload,
        "tiny_fingerprints": handle_tiny_fingerprints,
        "upload_callback": handle_upload_callback,
        "sts": handle_sts,
    }
    handlers[route](self, workspace_id)
```

**从 40 行重复代码变成 15 行清晰逻辑**。这就是好品味。

---

### 问题 #2：S3 客户端的重复

**垃圾代码分布在 3 个文件：**
- `src/media_server/s3_client.py::head_object()`
- `web/app.py::s3_request()`
- `web/fetch_one.py::s3_request()`

**所有三个函数都在做同样的事情：**
1. 解析 endpoint
2. 构建 canonical_uri
3. 调用 `aws_v4_headers()`
4. 发送 HTTP 请求

**好品味方案：**

统一一个 `S3Client` 类：
```python
# src/media_server/s3_client.py
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen
from .aws_sigv4 import aws_v4_headers

class S3Client:
    def __init__(self, endpoint, bucket, region, access_key, secret_key, session_token=""):
        parsed = urlparse(endpoint)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(f"invalid endpoint: {endpoint}")

        self.scheme = parsed.scheme
        self.host = parsed.netloc
        self.bucket = bucket
        self.region = region
        self.access_key = access_key
        self.secret_key = secret_key
        self.session_token = session_token

    def _canonical_uri(self, object_key):
        path = f"/{self.bucket}/{object_key.lstrip('/')}"
        return quote(path, safe="/-_.~")

    def _headers(self, method, canonical_uri, payload=b""):
        extra = {}
        if self.session_token:
            extra["x-amz-security-token"] = self.session_token
        return aws_v4_headers(
            self.access_key, self.secret_key, self.region, "s3",
            method, self.host, canonical_uri, payload, extra
        )

    def _request(self, method, object_key, payload=b"", timeout=10):
        canonical_uri = self._canonical_uri(object_key)
        url = f"{self.scheme}://{self.host}{canonical_uri}"
        headers = self._headers(method, canonical_uri, payload)

        req = Request(url, data=payload or None, headers=headers, method=method)
        with urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), resp.headers

    def head(self, object_key):
        try:
            status, _, _ = self._request("HEAD", object_key, timeout=5)
            return status == 200
        except HTTPError as e:
            if e.code == 404:
                return False
            raise

    def get(self, object_key):
        return self._request("GET", object_key, timeout=30)

    def delete(self, object_key):
        return self._request("DELETE", object_key)
```

**使用：**
```python
# 在 app.py 初始化时
s3 = S3Client(
    config.storage_endpoint,
    config.storage_bucket,
    config.storage_region,
    config.storage_access_key,
    config.storage_secret_key,
    config.storage_session_token
)

# 使用
if s3.head(object_key):
    ...

status, body, headers = s3.get(object_key)
```

**从 3 份重复代码变成 1 个清晰的类**。

---

### 问题 #3：候选路径的特殊情况

**垃圾代码：**
```python
def head_object(config, object_key):
    # ...
    bucket_prefix = f"{config.storage_bucket}/"
    candidates = [object_key.lstrip("/")]
    if not object_key.startswith(bucket_prefix):
        candidates.append(f"{bucket_prefix}{object_key.lstrip('/')}")

    for candidate in candidates:
        # 尝试两次 HEAD...
```

**问题分析：**
- 为什么需要两个候选？因为客户端可能传 `workspace/file.jpg` 或 `media/workspace/file.jpg`
- 这是在用 workaround 解决数据不一致问题：`object_key` 的格式没有统一

**好品味方案：**

在 `build_object_key()` 时就统一格式，HEAD 时不需要猜测：
```python
def build_object_key(workspace_id, filename):
    """
    始终返回不带 bucket 前缀的 key：workspace_id/YYYYMMDD/filename
    """
    safe_name = (filename or "unknown").replace("/", "_")
    date_part = time.strftime("%Y%m%d", time.localtime())
    return f"{workspace_id}/{date_part}/{safe_name}"

def head_object(s3_client, object_key):
    """object_key 应该不包含 bucket 名，S3Client 会自动处理"""
    return s3_client.head(object_key)
```

**不要在运行时猜测，在存储时就统一格式**。

---

## 第三层：复杂度审查

> "如果实现需要超过3层缩进，重新设计它"

### 问题 #1：`handle_sts()` 的复杂响应

**垃圾代码：**
```python
payload = {
    "code": 0,
    "message": "success",
    "data": {
        "provider": handler.config.storage_provider,
        "endpoint": handler.config.storage_endpoint,
        "bucket": handler.config.storage_bucket,
        "region": handler.config.storage_region,
        "object_key_prefix": f"{workspace_id}/",
        "access_key_id": access_key,
        "access_key_secret": secret_key,
        "security_token": security_token,
        "session_token": security_token,  # 重复
        "accessKeyId": access_key,        # 重复
        "accessKeySecret": secret_key,    # 重复
        "securityToken": security_token,  # 重复
        "sessionToken": security_token,   # 重复
        "expire": expire_seconds,
        "credentials": {
            "access_key_id": access_key,      # 又重复
            "access_key_secret": secret_key,  # 又重复
            "security_token": security_token, # 又重复
            "session_token": security_token,  # 又重复
            "accessKeyId": access_key,        # 又又重复
            "accessKeySecret": secret_key,    # 又又重复
            "securityToken": security_token,  # 又又重复
            "sessionToken": security_token,   # 又又重复
            "expire": expire_seconds
        }
    }
}
```

**问题分析：**
- 同一份数据重复了 **3 遍**：data 根级别、credentials 里、还有 snake_case/camelCase 两种命名
- 这是为了兼容客户端的不同读法，但这应该在**序列化层**处理，而不是在业务逻辑里

**好品味方案：**
```python
def build_sts_credentials(access_key, secret_key, security_token, expire_seconds):
    base = {
        "access_key_id": access_key,
        "access_key_secret": secret_key,
        "security_token": security_token,
        "expire": expire_seconds,
    }
    # 如果客户端需要 camelCase，在这里统一转换
    camel = {
        "accessKeyId": access_key,
        "accessKeySecret": secret_key,
        "securityToken": security_token,
        "sessionToken": security_token,
        "expire": expire_seconds,
    }
    return {**base, **camel}

def handle_sts(handler, workspace_id):
    # ...
    credentials = build_sts_credentials(access_key, secret_key, security_token, expire_seconds)

    payload = {
        "code": 0,
        "message": "success",
        "data": {
            "provider": handler.config.storage_provider,
            "endpoint": handler.config.storage_endpoint,
            "bucket": handler.config.storage_bucket,
            "region": handler.config.storage_region,
            "object_key_prefix": f"{workspace_id}/",
            **credentials,  # 展开
            "credentials": credentials,  # 如果客户端从 credentials 里读
        }
    }
```

**但说实话，最好的方案是：**

跟客户端团队确认，**到底需要哪些字段**，然后只返回那些。如果客户端既支持 snake_case 又支持 camelCase，选一个，删掉另一个。

**代码不是为了展示你会拷贝粘贴，而是为了解决问题**。

---

### 问题 #2：`handle_tiny_fingerprints()` 的循环

**垃圾代码：**
```python
found = []
for fp in requested:
    object_key = handler.db.get_object_key_by_tiny(workspace_id, fp)
    if not object_key:
        continue
    try:
        exists = head_object(handler.config, object_key)
    except RuntimeError as exc:
        logging.error("tiny-fingerprints head check failed: %s", exc)
        exists = False
    if exists:
        found.append(fp)
        continue
    handler.db.delete_by_tiny(workspace_id, fp)
```

**问题分析：**
- 对每个 fingerprint 都单独查数据库，单独 HEAD 请求，性能垃圾
- 如果 `requested` 有 100 个，就是 100 次数据库查询 + 100 次 HTTP 请求
- DB 有批量查询，S3 也可以批量（虽然这里可能不需要）

**好品味方案：**
```python
# 数据库层面支持批量查询
class MediaDB:
    def get_objects_by_tinies(self, workspace_id, tiny_fingerprints):
        """返回 {tiny_fp: object_key} 字典"""
        if not tiny_fingerprints:
            return {}

        placeholders = ",".join("?" * len(tiny_fingerprints))
        query = f"""
            SELECT tiny_fingerprint, object_key
            FROM media_files
            WHERE workspace_id=? AND tiny_fingerprint IN ({placeholders})
        """
        params = [workspace_id] + list(tiny_fingerprints)

        with self._lock:
            cursor = self._conn.execute(query, params)
            return {row[0]: row[1] for row in cursor.fetchall()}

# 处理函数
def handle_tiny_fingerprints(handler, workspace_id):
    # ...
    requested = payload.get("tiny_fingerprints") or []

    # 一次查询
    object_keys = handler.db.get_objects_by_tinies(workspace_id, requested)

    # HEAD 检查可以并行（但对于这个项目可能过度了）
    found = []
    to_delete = []

    for fp, object_key in object_keys.items():
        try:
            if head_object(handler.config, object_key):
                found.append(fp)
            else:
                to_delete.append(fp)
        except RuntimeError:
            to_delete.append(fp)

    # 批量删除
    if to_delete:
        handler.db.delete_tinies(workspace_id, to_delete)

    # ...
```

**从 O(N²) 变成 O(N)**。

---

## 第四层：破坏性分析

> "Never break userspace" - 向后兼容是铁律

### 风险点 #1：类变量的多线程竞态

**当前代码：**
```python
class MediaRequestHandler(BaseHTTPRequestHandler):
    pending_tiny_by_fingerprint = {}  # 多个请求共享！
```

**场景：**
1. 请求 A 调用 `fast-upload`，写入 `pending_tiny_by_fingerprint[fp_a] = tiny_a`
2. 请求 B 调用 `fast-upload`，写入 `pending_tiny_by_fingerprint[fp_b] = tiny_b`
3. 请求 A 调用 `upload-callback`，`pop(fp_a)` 成功
4. 请求 B 调用 `upload-callback`，`pop(fp_b)` 也成功

**看起来没问题？错了！**

5. 请求 C 和请求 D 同时 `pop(fp_c)`，一个成功，一个返回 `None`
6. 或者更糟：在 dict resize 时发生竞态，直接 crash

**修复方案：**
- 方案 1：用锁保护 `pending_tiny_by_fingerprint`（治标不治本）
- 方案 2：**把 tiny_fingerprint 存到数据库**（正确方案）

```python
# 在 fast-upload 时就写入 DB（允许 tiny 为空）
handler.db.upsert_file(
    workspace_id, fingerprint, tiny_fingerprint=tiny_fp,
    object_key="", file_name=name, file_path=path
)

# 在 upload-callback 时更新 object_key
handler.db.update_object_key(workspace_id, fingerprint, object_key)
```

**数据库已经处理了并发，不要自己造轮子**。

---

### 风险点 #2：`object_key` 路径注入

**当前代码：**
```python
def build_object_key(workspace_id, filename):
    safe_name = (filename or "unknown").replace("/", "_")
    date_part = time.strftime("%Y%m%d", time.localtime())
    return f"{workspace_id}/{date_part}/{safe_name}"
```

**问题分析：**
- 只过滤了 `/`，没有过滤 `..`、`\0`、控制字符
- `workspace_id` 没有验证，可以传入 `../../etc/passwd`

**好品味方案：**
```python
import re

def sanitize_path_component(s):
    """移除所有危险字符，只保留安全字符"""
    if not s:
        return "unknown"
    # 只保留字母、数字、下划线、连字符、点
    safe = re.sub(r'[^a-zA-Z0-9_\-.]', '_', s)
    # 移除开头的点（防止隐藏文件）
    safe = safe.lstrip('.')
    return safe or "unknown"

def build_object_key(workspace_id, filename):
    workspace_id = sanitize_path_component(workspace_id)
    filename = sanitize_path_component(filename)
    date_part = time.strftime("%Y%m%d", time.localtime())
    return f"{workspace_id}/{date_part}/{filename}"
```

**安全不是可选项**。

---

## 第五层：实用性验证

> "Theory and practice sometimes clash. Theory loses. Every single time."

### 问题：这些内存缓存真的需要吗？

**当前代码有 5 个内存缓存：**
1. `tiny_fingerprint_index`
2. `pending_tiny_by_fingerprint`
3. `uploaded_fingerprints`
4. `object_key_by_fingerprint`
5. `object_key_by_tiny`

**实用性分析：**
- 这个服务的 QPS 是多少？100？1000？10000？
- SQLite 在本地文件系统上，查询延迟 < 1ms
- 这些缓存带来的性能提升：**几乎为零**
- 这些缓存带来的复杂度：**巨大**
- 这些缓存带来的 bug 风险：**极高**

**结论：删掉所有内存缓存。**

如果真的有性能问题（实测，不是猜测），加一个正确的 LRU 缓存：
```python
from functools import lru_cache

class MediaDB:
    @lru_cache(maxsize=1024)
    def get_object_key_by_fingerprint(self, workspace_id, fingerprint):
        # ...
```

但我打赌你不需要。

---

## 具体重构步骤

### 优先级 P0（立即修复，否则会出现生产事故）

1. **删除所有类变量缓存**
   - 删除 `MediaRequestHandler` 中的 5 个字典/列表
   - 所有数据从 DB 读取

2. **修复数据库连接管理**
   - 使用单个持久连接 + 锁
   - 移除 `_connect()` 中的重复连接创建

3. **修复路径注入漏洞**
   - 在 `build_object_key()` 中添加 `sanitize_path_component()`

### 优先级 P1（重要，但不紧急）

4. **统一路由匹配**
   - 将 4 个 `match_*()` 函数合并为一个基于正则的路由器

5. **统一 S3 客户端**
   - 创建 `S3Client` 类
   - 删除 3 个文件中的重复代码

6. **分离配置结构**
   - 将 `ServerConfig` 拆分为 `ServerConfig`、`StorageConfig`、`STSConfig`

### 优先级 P2（改进代码质量）

7. **简化 STS 响应**
   - 提取 `build_sts_credentials()` 函数
   - 跟客户端确认是否真的需要所有字段

8. **批量查询优化**
   - 在 `MediaDB` 中添加 `get_objects_by_tinies()`
   - 优化 `handle_tiny_fingerprints()`

---

## 代码对比示例

### 示例 1：从混乱到清晰的 Handler

**垃圾版本（当前）：**
```python
def do_POST(self):
    parsed = urlparse(self.path)
    workspace_id = match_fast_upload(parsed.path)
    if workspace_id:
        handle_fast_upload(self, workspace_id)
        return
    workspace_id = match_tiny_fingerprints(parsed.path)
    if workspace_id:
        handle_tiny_fingerprints(self, workspace_id)
        return
    workspace_id = match_upload_callback(parsed.path)
    if workspace_id:
        handle_upload_callback(self, workspace_id)
        return
    workspace_id = match_sts(parsed.path)
    if workspace_id:
        handle_sts(self, workspace_id)
        return
    json_response(self, HTTPStatus.NOT_FOUND, {"code": 404, ...})
```

**好品味版本：**
```python
ROUTES = {
    "fast_upload": (re.compile(r"^/media/api/v1/workspaces/([^/]+)/fast-upload$"), handle_fast_upload),
    "tiny_fingerprints": (re.compile(r"^/media/api/v1/workspaces/([^/]+)/files/tiny-fingerprints$"), handle_tiny_fingerprints),
    "upload_callback": (re.compile(r"^/media/api/v1/workspaces/([^/]+)/upload-callback$"), handle_upload_callback),
    "sts": (re.compile(r"^/storage/api/v1/workspaces/([^/]+)/sts$"), handle_sts),
}

def do_POST(self):
    path = urlparse(self.path).path
    for pattern, handler in ROUTES.values():
        match = pattern.match(path)
        if match:
            handler(self, match.group(1))
            return
    json_response(self, HTTPStatus.NOT_FOUND, {"code": 404, "message": "not found", "data": {}})
```

**从 16 行重复代码变成 5 行清晰逻辑**。

---

### 示例 2：从函数式到 OOP 的 S3 客户端

**垃圾版本（当前分散在 3 个文件）：**
```python
# s3_client.py
def head_object(config, object_key):
    parsed = urlparse(config.storage_endpoint)
    # ... 20 行代码

# web/app.py
def s3_request(config, method, object_key, payload=b""):
    path = f"/{config.storage_bucket}/{object_key.lstrip('/')}"
    # ... 15 行代码

# web/fetch_one.py
def s3_request(config, method, object_key, payload=b""):
    path = f"/{config.storage_bucket}/{object_key.lstrip('/')}"
    # ... 15 行代码（完全重复！）
```

**好品味版本：**
```python
class S3Client:
    def __init__(self, endpoint, bucket, region, access_key, secret_key, session_token=""):
        # 初始化

    def head(self, object_key):
        return self._request("HEAD", object_key, timeout=5)[0] == 200

    def get(self, object_key):
        return self._request("GET", object_key)

    def delete(self, object_key):
        return self._request("DELETE", object_key)

    def _request(self, method, object_key, payload=b"", timeout=10):
        # 通用逻辑
```

**从 50 行重复代码变成 20 行可复用类**。

---

## 最终评语

这个项目的核心问题不是"不能用"，而是**充满了糟糕的设计决策**：

1. **数据结构混乱**：类变量、内存缓存、数据库，三者之间没有清晰的边界
2. **重复代码泛滥**：路由匹配、S3 客户端、配置解析，到处都是 copy-paste
3. **特殊情况太多**：候选路径、重复字段、临时状态传递，每个都是坏品味的标志

如果是我来写这个项目，**我会从数据结构开始**：
- 明确每份数据的所有者（DB or cache）
- 消除所有重复逻辑（路由、S3、配置）
- 用最简单的方式解决问题（单连接 + 锁，而不是连接池）

**好代码不是写出来的，是删出来的**。这个项目需要的不是添加功能，而是删除复杂性。

最后用 Linus 的话总结：

> "Talk is cheap. Show me the code."

现在你有了这份指南。动手吧。

---

**附录：推荐的文件结构**

```
src/media_server/
├── __init__.py
├── app.py              # 入口，初始化配置和服务
├── config.py           # 配置类（ServerConfig, StorageConfig, STSConfig）
├── server.py           # HTTP 服务器
├── handler.py          # 请求处理器（无状态）
├── router.py           # 路由匹配（基于正则）
├── handlers/           # 拆分 handlers.py
│   ├── __init__.py
│   ├── fast_upload.py
│   ├── tiny_fingerprints.py
│   ├── upload_callback.py
│   └── sts.py
├── storage/            # 存储层
│   ├── __init__.py
│   ├── s3_client.py    # 统一的 S3Client 类
│   └── db.py           # 数据库访问
├── utils/
│   ├── __init__.py
│   ├── http.py         # HTTP 响应工具
│   ├── security.py     # 路径清理、验证
│   └── aws_sigv4.py    # AWS 签名
└── scripts/            # 测试脚本
    ├── test_sts_upload.py
    └── image_gen.py
```

**核心原则：**
- 一个文件一个职责
- 数据结构清晰分离
- 无全局状态（除了只读配置）
- 代码可测试、可复用

这就是好品味。
