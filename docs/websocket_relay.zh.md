# websocket_relay.py — WebSocket 认证中继

实现 `/stream` 端点的 WebSocket 双向中继，支持从浏览器 cookie 中提取认证 token 并透传给后端。

## 入口函数

### `stream_proxy(websocket: WebSocket)`

唯一公开函数，由 `app.py` 在 `/stream` WebSocket 路由上调用。

```
客户端 WebSocket ──→ FastAPI WebSocket ──→ 后端 WebSocket (通过 websockets 库)
```

**认证流：**

```
浏览器 Cookie: gotify-client-token=xxxx
       │
       ▼
websocket.cookies["gotify-client-token"] = "xxxx"
       │
       ▼
backend_url = "ws://host:8083/stream?token=xxxx"
       │
       ▼
后端 readTokenFromRequest: ?token=xxxx → ✅ 认证通过
```

Gotify 后端的认证检查顺序：
1. `?token=` 查询参数
2. `X-Gotify-Key` 请求头
3. `Authorization: Bearer` 请求头
4. `Cookie: gotify-client-token` 请求头

由于浏览器 `new WebSocket()` API 无法发送自定义请求头，cookie 是唯一的凭据载体。本中继从入站 WebSocket 的 cookie 中提取 `gotify-client-token`，并将其作为 `?token=` 查询参数附加到后端 URL 上——与后端最高优先级的认证检查匹配。

**为何选择查询参数方案而非 Cookie 透传（extra_headers）：**

| 方面 | Cookie 透传（方案 B） | Token 查询参数（方案 A — 已采纳） |
|------|----------------------|-----------------------------------|
| 精确性 | 发送所有 cookie（潜在信息泄露） | 仅发送认证 token |
| 后端匹配 | 匹配第 4 优先级的检查 | 匹配第 1 优先级的检查 |
| 库兼容性 | `websockets` 库对 `extra_headers` 中 `Cookie` 的行为因版本而异 | 通用兼容 |
| 浏览器 `new WebSocket()` | 不发送 `Authorization: Basic` | 不适用 |

## 中继逻辑

接受连接后，函数：

1. 从 `_BACKEND` 构造后端 WebSocket URL（http→ws 协议转换）
2. 从 `websocket.cookies` 提取 `gotify-client-token`，追加为 `?token=` 查询参数（如果查询参数中尚未存在 `token`）
3. 通过 `websockets.connect(backend_url)` 连接后端
4. 启动两个并发 `asyncio` 任务：

### `client_to_backend()`

将客户端消息转发到后端。通过 `websocket.receive()` 监听，将文本/字节消息通过后端 WebSocket 转发。捕获 `WebSocketDisconnect` 以检测客户端断开。

### `backend_to_client()`

通过 `backend_ws.recv()` 接收后端消息。在转发给客户端之前，使用 `proxy.py` 中的 `rewrite_file_urls()` 改写文件标记 URL。捕获 `websockets.ConnectionClosed` 处理后端断开。

### 清理

当任一方向断开时，通过 `closed` 标志通知两个任务，在 `finally` 块中关闭客户端 WebSocket：

```python
finally:
    closed = True
    try:
        await websocket.close()
    except Exception:
        pass
```

## 错误处理

| 条件 | 行为 |
|---|---|
| `WebSocketDisconnect`（客户端） | 设置 `closed = True`，跳出循环 |
| `websockets.ConnectionClosed`（后端） | 设置 `closed = True`，跳出循环 |
| 连接/中继期间的任意 `Exception` | 记录日志 `"websocket error: {e}"` |
| 最终 `websocket.close()` 异常 | 静默忽略（连接已断开） |

## 配置

| 常量 | 来源 | 说明 |
|---|---|---|
| `_BACKEND` | `load_env_config().gotify_backend` | 后端 URL，进行 http→ws 或 https→wss 转换 |

## 相关文档

- `proxy.rewrite_file_urls()` — 文件 URL 标记替换（用于消息中的 `_gateway` 文件链接）
- `app.py` — 路由注册：`@app.websocket("/stream")`
- `docs/websocket-auth-proxy.zh.md` — 根因分析与方案决策记录
