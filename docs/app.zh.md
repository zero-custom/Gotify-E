# app.py — Tornado 应用与入口

主 Tornado 应用。定义 HTTP 路由、反向代理管道、文件上传拦截、WebSocket 中继及 `main()` 入口函数。

## 路由

| 路径 | 处理器 | 说明 |
|---|---|---|
| `/uploads/(.*)` | `UploadedFileHandler` | 上传文件静态资源服务。设置 CORS、Cache-Control 以及 SVG CSP 头。 |
| `/_gateway/(.*)` | `UploadedFileHandler` | 网关静态资源（i18n 脚本）服务。 |
| `/message` | `MessageHandler` | 拦截 `multipart/form-data` POST 文件上传；GET/DELETE/PUT 透明代理。 |
| `/stream` | `StreamProxyHandler` | WebSocket 双向中继，含消息 URL 重写。 |
| `/.*` | `ProxyHandler` | 兜底透明代理，处理所有其余请求。 |

## 处理器类

### `UploadedFileHandler(tornado.web.StaticFileHandler)`

从 `UPLOAD_DIR`（上传文件）和 `GATEWAY_DIR`（网关资源）提供静态文件。

| 头 | 值 | 条件 |
|---|---|---|
| `Access-Control-Allow-Origin` | `*` | 始终设置 |
| `Cache-Control` | `public, max-age=3600` | 始终设置 |
| `Content-Security-Policy` | `script-src 'none'` | 仅 `.svg` 文件 |

### `ProxyHandler(tornado.web.RequestHandler)`

通用透明代理。7 种 HTTP 方法（GET/POST/PUT/DELETE/PATCH/HEAD/OPTIONS）全部委托给 `proxy_to_backend`。错误时设置 `Content-Type: application/json`，使用统一 `_format_error` 格式。

### `MessageHandler(tornado.web.RequestHandler)`

GET/DELETE/PUT 透明代理。POST 分两条路径：

| Content-Type | 行为 |
|---|---|
| 非 `multipart/form-data` | 透明代理到 Gotify 后端 |
| `multipart/form-data` + 文件 | 通过 `FileStore.save()` 保存文件，消息正文追加 Markdown 链接，然后以 JSON 格式代理到后端 |
| `multipart/form-data` + 无文件 | 透明代理（fallthrough） |

消息正文与文件链接之间的 `---` 分隔符在消息体为空时被省略。

### `StreamProxyHandler(tornado.websocket.WebSocketHandler)`

客户端与 Gotify 后端 `/stream` 之间的 WebSocket 双向中继。`open()` 时将 `BACKEND` 地址做 http→ws 协议转换后连接。客户端→后端消息透传；后端→客户端消息解码后通过 `rewrite_file_urls` 改写文件标记再转发。

## 代理管道 (`proxy_to_backend`)

```
客户端 → proxy_to_backend → Gotify 后端
                                ↓
                          响应正文
                                ↓
        ┌───────────┬────────────┬───────────┐
        ↓           ↓            ↓           ↓
   rewrite_   _inject_    _inject_    _format_
   file_urls  i18n       gateway_    error
   (GET 消息)  (HTML)     info        (错误时)
                         (GET /ver)
```

| 步骤 | 触发条件 | 效果 |
|---|---|---|
| `rewrite_file_urls` | GET + 消息端点 + body 非空 | 将 `{gateway}/uploads/` 替换为 `{current_base}/uploads/` |
| `_inject_i18n` | `text/html` Content-Type | 在 `</body>` 前注入 `<script src="/_gateway/i18n.js">`（大小写不敏感） |
| `_inject_gateway_info` | GET `/version` + JSON Content-Type | 向 JSON 响应注入 `_gateway`、`_upload_max` 字段 |
| `_format_error` | HTTPClientError | 返回 `{error, code, backend}` |
| `_format_error` | 其他异常 | 返回 `{error, code, backend}`，状态码 502 |

## 辅助函数

| 函数 | 参数 | 返回 | 说明 |
|---|---|---|---|
| `build_backend_url` | `path, query=""` | `str` | 构造后端完整 URL：`{BACKEND}{path}?{query}` |
| `build_gateway_url` | `handler` | `str` | 如果设置 `PUBLIC_URL` 则返回，否则从 `X-Forwarded-Proto` + `Host` 请求头推断 |
| `_is_message_endpoint` | `path: str` | `bool` | 匹配 `/message`、`/message/`、`/application/{id}/message` |
| `_is_version_endpoint` | `path: str` | `bool` | 匹配 `/version` |
| `rewrite_file_urls` | `body: bytes, current_base: str` | `bytes` | 将响应正文中的 `MARKER_PREFIX` 替换为 `{current_base}/uploads/` |
| `_inject_i18n` | `output: bytes` | `bytes` | 大小写不敏感搜索 `</body>` 并注入 i18n script 标签 |
| `_inject_gateway_info` | `output: bytes` | `bytes` | JSON 解析 → 注入 `_gateway`+`_upload_max` → JSON 序列化 |
| `_format_error` | `status_code, message, backend_url=""` | `dict` | 返回 `{error, code, backend?}` |

## 应用工厂

`make_app()` 构造 `tornado.web.Application`，注册路由表，设置 `max_buffer_size=MAX_UPLOAD`。

## 入口

`main()` — 打印启动配置，调用 `make_app()`，监听 `{HOST}:{PORT}`，启动 IOLoop。捕获 `KeyboardInterrupt` 优雅退出。
