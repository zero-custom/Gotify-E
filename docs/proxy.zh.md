# proxy.py — 反向代理管道

实现 HTTP 客户端抽象、后端 URL 构建、响应转换管道以及核心 `proxy_to_backend` 函数。

## HTTP 客户端抽象

### `HttpResponse` (数据类)

```python
@dataclass
class HttpResponse:
    status_code: int
    headers: dict[str, str]
    content: bytes
```

### `HttpClient` (协议)

可注入的接口，用于与后端通信。所有代理函数依赖此协议，便于在测试中使用 `FakeHttpClient`。

```python
class HttpClient(Protocol):
    async def request(self, method, url, *, headers=None, content=None, follow_redirects=False) -> HttpResponse
```

### `RealHttpClient`

封装 `httpx.AsyncClient` 的生产实现：

| 参数 | 值 |
|---|---|
| 超时 | 120s（连接 10s） |
| 长连接数 | 50 |
| 总连接数 | 100 |

提供 `aclose()` 用于优雅关闭。

## URL 辅助函数

### `build_backend_url(path, query="") -> str`

构造后端完整 URL：`{BACKEND}{path}?{query}`。查询字符串为空时省略 `?`。

### `build_gateway_url(conn) -> str`

返回网关公网地址，用于文件链接重写。解析顺序：

1. `_PUBLIC_URL`（来自 `PUBLIC_URL` 环境变量）若已设置
2. `X-Forwarded-Proto` 头 + `Host` 头（处理反向代理场景）
3. WebSocket URL 协议归一化（ws→http, wss→https）

### `is_message_endpoint(path) -> bool`

匹配路径：`/message`、`/message/`、`/application/{id}/message`。

### `is_version_endpoint(path) -> bool`

匹配路径：`/version`。

## 响应注入函数

### `rewrite_file_urls(body, current_base) -> bytes`

将响应正文中的 `{stored_marker}/uploads/` 标记替换为 `{current_base}/uploads/`。同时用于 HTTP 代理（`proxy_to_backend`）和 WebSocket 中继（`stream_proxy`）。

`current_base` 为空或 `body` 为空时跳过处理。

### `inject_i18n(output) -> bytes`

在 HTML 响应的 `</body>` 之前插入 `<script src="/_gateway/i18n.js"></script>`。使用 `html.parser.HTMLParser`（非正则）定位闭合 body 标签。

- 未找到 `</body>` 时跳过注入
- `HTMLParseError` 时记录警告并返回原始输出
- 目前 i18n 脚本为占位文件（尚无翻译数据）

### `inject_gateway_info(output) -> bytes`

向 `/version` 的 JSON 响应中注入 `_gateway` 和 `_upload_max` 字段。若正文非 JSON 或非对象，则直接返回原始输出。

### `format_error(status_code, message, backend_url="") -> dict`

返回标准错误字典：`{"error": message, "code": status_code}`。`backend_url` 非空时额外添加 `"backend"` 键。

## 响应转换管道

将 `proxy_to_backend` 中原有的 if 链替换为注册式转换列表。

### 转换器类型

```python
_TransformFn = Callable[[bytes, str, str, str, Request], bytes]
#                        output  method path  content_type  request
```

### 已注册的转换器

| 函数 | 触发条件 | 效果 |
|---|---|---|
| `_rewrite_message_urls` | GET + 消息端点 + body 非空 | 调用 `rewrite_file_urls(output, current_base)` |
| `_inject_i18n_transform` | `text/html` 在 content-type 中 | 调用 `inject_i18n(output)` |
| `_inject_gateway_info_transform` | GET + `/version` + JSON content-type | 调用 `inject_gateway_info(output)` |

条件不满足时直接返回原始 output。转换器按注册顺序依次执行。

### 新增转换器

```python
from proxy import _transforms, _TransformFn

def my_transform(output, method, path, content_type, request) -> bytes:
    if output and <条件>:
        return do_something(output)
    return output

_transforms.append(my_transform)
```

## 核心代理函数

### `proxy_to_backend(request, http_client, method=None, headers=None, body=None) -> Response`

请求代理管道：

```
request
  │
  ├─ 确定方法，构建后端 URL
  ├─ 过滤请求头（剔除：host, origin, transfer-encoding, content-encoding）
  ├─ 读取请求体（仅 POST/PUT/PATCH）
  ├─ http_client.request(method, backend_url, headers, body)
  │
  ├─ 成功：
  │     ├─ 过滤响应头（剔除：transfer-encoding, content-encoding, alt-svc, content-length）
  │     ├─ 应用 ResponseTransform 管道（for t in _transforms: output = t(...)）
  │     └─ 返回 Response(content, status_code, headers)
  │
  └─ httpx.RequestError：
        └─ 返回 502 JSONResponse，使用 format_error()
```

| 头过滤 | 方向 | 剔除的头 |
|---|---|---|
| 请求头 | 发往后端 | `host`, `origin`, `transfer-encoding`, `content-encoding` |
| 响应头 | 返回客户端 | `transfer-encoding`, `content-encoding`, `alt-svc`, `content-length` |

## 公开接口

其他模块从 `proxy.py` 导入：

```python
from proxy import (
    HttpClient,          # 协议——用于类型标注
    RealHttpClient,      # 生产用 HTTP 客户端
    build_gateway_url,   # URL 辅助（app.py WebSocket 中使用）
    format_error,        # 错误响应辅助（app.py、upload.py 中使用）
    proxy_to_backend,    # 核心代理函数（app.py、upload.py、delete_handler.py 中使用）
    rewrite_file_urls,   # 标记替换（app.py WebSocket 中使用）
)
```
