# app.py — FastAPI 应用与入口

FastAPI 应用。定义 HTTP 路由、请求体大小中间件、WebSocket 中继、定时清理循环及 `main()` 入口函数。

## 应用

`FastAPI` 实例，`title="Gotify[E]"`，带版本号（`config.py` 中的 `VERSION`）。`lifespan` 上下文管理器负责：

- **启动**：运行 `recover_staging()` 清理上次崩溃遗留的过期文件；创建 `cleanup_loop()` asyncio 任务；运行 `recover_on_startup()` 处理崩溃后遗留的 pending 文件。
- **关闭**：取消清理任务；关闭 `RealHttpClient` 连接池。

`TokenSanitizingFilter`（来自 `log_filter.py`）在模块级安装在根日志记录器上，用于屏蔽日志输出中的凭据。

请求体大小检查中间件在每个 `POST`/`PUT`/`PATCH` 上运行：若 `Content-Length` 超过 `MAX_UPLOAD`，通过 `format_error` 返回 413 JSON 错误。

## 路由

| 路径 | 方法 | 处理器 | 说明 |
|---|---|---|---|
| `/uploads/{path}` | GET | `serve_upload()` | 上传文件服务，含路径穿越防护。 |
| `/_gateway/{path}` | GET | `StaticFiles` 挂载 | 网关静态资源（i18n JS 脚本）。 |
| `/message` | GET/PUT | `handle_message_default()` | 透明代理到后端。 |
| `/message` | DELETE | `handle_message_delete_route()` | 拦截删除 → 移动文件到 pending → 代理 DELETE。 |
| `/message/{msg_id}` | DELETE | `handle_message_delete_by_id()` | 单条消息删除拦截。 |
| `/message` | POST | `handle_message_post_route()` | 拦截 `multipart/form-data` 文件上传；其他 POST 正文透明代理。委托给 `upload.py`。 |
| `/stream` | WebSocket | `stream_proxy()` | WebSocket 双向中继，含消息 URL 重写。 |
| `/application/{app_id}/message` | DELETE | `handle_app_delete_route()` | 应用批量删除拦截。委托给 `delete_handler.py`。 |
| `/{path:path}` | 全部 | `catch_all()` | 兜底透明代理。必须最后注册。 |

## 路由处理器

### `serve_upload(file_path: str)`

从 `UPLOAD_DIR` 提供上传文件。将请求路径解析并验证其在 `UPLOAD_DIR` 范围内（路径穿越防护）。

| 头 | 值 | 条件 |
|---|---|---|
| `Access-Control-Allow-Origin` | `*` | 始终设置 |
| `Cache-Control` | `public, max-age=3600` | 始终设置 |
| `Content-Security-Policy` | `sandbox` | 仅当扩展名不在 `DANGEROUS_EXTS` 中时（安全文件） |
| `Content-Disposition` | `attachment; filename="..."` | 扩展名在 `DANGEROUS_EXTS` 中时（`.html`、`.htm`、`.js`、`.php` 等） |

返回 `FileResponse`；文件不存在或路径穿越时抛出 `HTTPException(404)`。

**危险扩展名行为**：扩展名在 `DANGEROUS_EXTS` 中的文件以 `Content-Disposition: attachment` 方式提供，防止浏览器内联渲染（XSS 防护）。其他文件使用默认的内联方式。

### `handle_message_default(request)`

GET/PUT 在 `/message` 上的透明代理，委托给 `proxy_to_backend`。

### `handle_message_delete_route(request)` / `handle_message_delete_by_id(request, msg_id)`

DELETE 拦截。在代理 DELETE 到 Gotify 前，读取消息的 `extras.gateway::files`，将文件移动到 pending 目录，写入 manifest 条目，然后继续代理。DELETE 失败时恢复文件。

委托给 `delete_handler.handle_message_delete`。

### `handle_message_post_route(request)`

POST 文件上传拦截。非 multipart 请求直接透传。Multipart 请求由 `upload.handle_message_post` 处理——保存文件、追加 Markdown 链接、以紧凑 JSON 代理。

### `stream_proxy_route(websocket)`

委托给 `websocket_relay.stream_proxy` 处理 WebSocket 双向中继。详见下方"WebSocket 中继"章节。

### `handle_app_delete_route(request, app_id)`

批量删除拦截，`DELETE /application/{app_id}/message`。委托给 `delete_handler.handle_app_delete`。

### `catch_all(request, path)`

兜底代理，所有其余 HTTP 方法（GET/POST/PUT/DELETE/PATCH/HEAD/OPTIONS）。最后注册以确保特定路由优先匹配。

## 配置

所有配置在模块级通过 `load_env_config()` 加载：

```python
_cfg = load_env_config()
_BACKEND = _cfg.gotify_backend
_HOST = _cfg.host
_PORT = _cfg.port
_PUBLIC_HOST = _cfg.public_host
_UPLOAD_DIR = Path(GatewayConfig.UPLOAD_DIR)
_STAGING_DIR = Path(GatewayConfig.STAGING_DIR)
_MAX_UPLOAD = _cfg.max_upload_mb * 1024 * 1024
_MARKER_PREFIX = f"{GatewayConfig.STORED_MARKER.rstrip('/')}/uploads/"
_IMAGE_EXTS = GatewayConfig.IMAGE_EXTS
_GATEWAY_DIR = Path(__file__).parent.resolve() / GatewayConfig.GATEWAY_DIR_NAME
```

## 生命周期

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    await recover_staging()                      # 清理上次崩溃遗留的过期 staging 文件
    cleanup_task = asyncio.create_task(cleanup_loop())
    await recover_on_startup(_http_client)
    yield
    cleanup_task.cancel()
    await _http_client.aclose()
```

### `stream_proxy`（位于 `websocket_relay.py`）

客户端与 Gotify 后端 `/stream` 之间的 WebSocket 双向中继。

```
客户端 WebSocket ↔ FastAPI ↔ 后端 WebSocket (通过 websockets 库)
```

接受连接后，将 `BACKEND` 地址做 http→ws 协议转换。从客户端的 WebSocket cookie 中提取 `gotify-client-token`，作为 `?token=` 查询参数传递给后端——这是因为浏览器 `new WebSocket()` 无法发送自定义请求头，cookie 是唯一的凭据载体。`?token=` 查询参数与 Gotify 后端的最高优级认证检查相匹配。

通过 `websockets.connect(backend_url)` 连接后端。两个 `asyncio` 任务并发运行：

- **client_to_backend**：将客户端消息转发到后端。
- **backend_to_client**：接收后端消息，通过 `rewrite_file_urls` 改写文件标记，然后发送给客户端。

断开或出错时两个任务结束，`finally` 块关闭客户端 WebSocket。

详见 `docs/websocket_relay.zh.md` 了解中继逻辑，及 `docs/websocket-auth-proxy.zh.md` 了解 WebSocket 认证问题的根因分析。

### `cleanup_loop`（位于 `cleanup.py`）

定期扫描 pending manifest，删除过期文件。应用生命周期内后台持续运行。间隔：`cleanup_interval_minutes`。直接使用 `PendingStore`。

### `recover_on_startup`（位于 `delete_handler.py`）

扫描 manifest 中 `status: "moved"` 的条目，检查 Gotify 消息是否存在：
- **200** → 将文件恢复至 `upload_dir`
- **404** → 条目标记为 `"deleted"`
- **错误** → 保留在 pending，记录警告

## 入口

### 生产 (uvicorn)

```bash
uvicorn app:app --host 0.0.0.0 --port 8765 --proxy-headers
```

环境变量 `HOST` 和 `PORT` 可覆盖默认绑定地址（Dockerfile 通过 shell 展开实现）。

### 开发 (auto-reload)

```bash
uvicorn app:app --reload --port 8765
```

### `main()`

打印启动配置（版本、后端地址、监听地址、上传目录），调用 `uvicorn.run("app:app", ...)` 使用 `--proxy-headers`。直接执行 `python3 app.py` 时使用（备用入口，Docker 直接使用 uvicorn）。

## 模块依赖

| 模块 | 导入 | 用途 |
|---|---|---|
| `config` | `load_env_config, GatewayConfig, VERSION` | 配置加载与类型化设置 |
| `pending_store` | `PendingStore` | 文件 pending 状态机（`cleanup_loop` 使用） |
| `proxy` | `RealHttpClient, build_gateway_url, format_error, proxy_to_backend, rewrite_file_urls` | HTTP 客户端、代理管道、URL 辅助 |
| `storage` | `FileStore` | 文件持久化引擎 |
| `upload` | `handle_message_post` | Multipart 上传拦截 |
| `delete_handler` | `handle_app_delete, handle_message_delete, recover_on_startup` | DELETE 文件清理与崩溃恢复 |
| `cleanup` | `cleanup_loop` | 定时过期 pending 文件清理 |
| `websocket_relay` | `stream_proxy` | WebSocket 双向中继与 URL 重写 |
| `log_filter` | `TokenSanitizingFilter` | 日志凭据脱敏（模块级安装） |
