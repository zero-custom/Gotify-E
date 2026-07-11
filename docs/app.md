# app.py — FastAPI Application & Entrypoint

FastAPI application. Defines HTTP routes, body size middleware, WebSocket relay, periodic cleanup loop, and the `main()` entrypoint.

## Application

`FastAPI` instance created with `title="Gotify[E]"`, versioned (`VERSION` from `config.py`). A `lifespan` context manager manages:

- **Startup**: Creates `cleanup_loop()` asyncio task; runs `recover_on_startup()` to resolve any pending files left from a crash.
- **Shutdown**: Cancels cleanup task; closes `RealHttpClient` connection pool.

A body-size check middleware runs on every `POST`/`PUT`/`PATCH`: if `Content-Length` exceeds `MAX_UPLOAD`, it returns a 413 JSON error via `format_error`.

## Routes

| Path | Method(s) | Handler | Description |
|---|---|---|---|
| `/uploads/{path}` | GET | `serve_upload()` | Static file serving with path traversal protection. |
| `/_gateway/{path}` | GET | `StaticFiles` mount | Gateway static assets (i18n JS scripts). |
| `/message` | GET/PUT | `handle_message_default()` | Transparent proxy to backend. |
| `/message` | DELETE | `handle_message_delete_route()` | Intercepts delete → moves files to pending → proxies DELETE. |
| `/message/{msg_id}` | DELETE | `handle_message_delete_by_id()` | Single-message delete interception. |
| `/message` | POST | `handle_message_post_route()` | Intercepts `multipart/form-data` for file uploads; other POST bodies transparently proxied. Delegates to `upload.py`. |
| `/stream` | WebSocket | `stream_proxy()` | Bidirectional WebSocket relay with message URL rewriting. |
| `/application/{app_id}/message` | DELETE | `handle_app_delete_route()` | Bulk delete interception for an application. Delegates to `delete_handler.py`. |
| `/{path:path}` | ALL | `catch_all()` | Catch-all transparent proxy for all remaining requests. Must be registered last. |

## Route Handlers

### `serve_upload(file_path: str)`

Serves uploaded files from `UPLOAD_DIR`. Resolves the requested path and validates it stays within `UPLOAD_DIR` (path traversal protection).

| Header | Value | Condition |
|---|---|---|
| `Access-Control-Allow-Origin` | `*` | Always |
| `Cache-Control` | `public, max-age=3600` | Always |
| `Content-Security-Policy` | `script-src 'none'` | Only for `.svg` files |

Returns `FileResponse` with the resolved file path. Raises `HTTPException(404)` when not found or path traversal is detected.

### `handle_message_default(request)`

Transparent proxy for GET/PUT on `/message`. Delegates to `proxy_to_backend`.

### `handle_message_delete_route(request)` / `handle_message_delete_by_id(request, msg_id)`

DELETE interception. Before proxying the DELETE to Gotify, reads the message's `extras.gateway::files`, moves those files to a pending directory, writes a manifest entry, then proceeds with the proxy. On DELETE failure, files are restored.

Delegates to `delete_handler.handle_message_delete`.

### `handle_message_post_route(request)`

POST interception for file uploads. Non-multipart requests pass through transparently. Multipart requests are processed by `upload.handle_message_post` which saves files, appends Markdown links, and proxies a compact JSON payload.

### `stream_proxy_route(websocket)`

Delegates to `websocket_relay.stream_proxy` for bidirectional WebSocket relay. See `WebSocket Relay` section below.

### `handle_app_delete_route(request, app_id)`

Bulk delete interception for `DELETE /application/{app_id}/message`. Delegates to `delete_handler.handle_app_delete`.

### `catch_all(request, path)`

Catch-all that proxies all remaining HTTP methods (GET, POST, PUT, DELETE, PATCH, HEAD, OPTIONS) via `proxy_to_backend`. Registered last so specific routes take priority.

## Configuration

All configuration is loaded via `load_env_config()` at module level:

```python
_cfg = load_env_config()
_BACKEND = _cfg.gotify_backend
_HOST = _cfg.host
_PORT = _cfg.port
_PUBLIC_URL = _cfg.public_url
_UPLOAD_DIR = Path(_cfg.upload_dir)
_MAX_UPLOAD = _cfg.max_upload_mb * 1024 * 1024
_MARKER_PREFIX = f"{_cfg.stored_marker.rstrip('/')}/uploads/"
_IMAGE_EXTS = GatewayConfig.IMAGE_EXTS
_GATEWAY_DIR = Path(__file__).parent.resolve() / GatewayConfig.GATEWAY_DIR_NAME
```

## Lifespan

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    cleanup_task = asyncio.create_task(cleanup.cleanup_loop())
    await delete_handler.recover_on_startup(_http_client)
    yield
    cleanup_task.cancel()
    await _http_client.aclose()
```

### `stream_proxy` (in `websocket_relay.py`)

Bidirectional WebSocket relay between client and Gotify backend `/stream`.

```
Client WebSocket ↔ FastAPI ↔ Backend WebSocket (via websockets library)
```

On accept, constructs a WebSocket URL from `BACKEND` (http→ws protocol swap) and connects via `websockets.connect`. Two `asyncio` tasks run concurrently:

- **client_to_backend**: forwards client messages to backend.
- **backend_to_client**: receives from backend, rewrites file markers via `rewrite_file_urls`, then sends to client.

On disconnect or error, both tasks finish and the client WebSocket is closed in `finally`.

### `cleanup_loop` (in `cleanup.py`)

Periodically scans the pending manifest and removes expired files. Runs in the background for the lifetime of the application. Interval: `cleanup_interval_minutes`. Uses `PendingStore` directly.

### `recover_on_startup` (in `delete_handler.py`)

Scans the manifest for entries with status `"moved"` and checks if the corresponding Gotify message still exists:
- **200** → restores files to `upload_dir`
- **404** → marks entry as `"deleted"`
- **Error** → leaves in pending, logs warning

## Entrypoint

### Production (uvicorn)

```bash
uvicorn app:app --host 0.0.0.0 --port 8765 --proxy-headers
```

Environment variables `HOST` and `PORT` override the default bind address (Dockerfile wraps this via shell expansion).

### Development (auto-reload)

```bash
uvicorn app:app --reload --port 8765
```

### `main()`

Logs startup configuration (version, backend, listen address, upload dir), then calls `uvicorn.run("app:app", ...)` with `--proxy-headers`. Used when `python3 app.py` is invoked directly (fallback entrypoint, Docker uses `uvicorn` directly).

## Module Dependencies

| Module | Import | Purpose |
|---|---|---|
| `config` | `load_env_config, GatewayConfig, VERSION` | Configuration loading and typed settings |
| `pending_store` | `PendingStore` | File pending state machine (used by `cleanup_loop`) |
| `proxy` | `RealHttpClient, build_gateway_url, format_error, proxy_to_backend, rewrite_file_urls` | HTTP client, proxy pipeline, URL helpers |
| `storage` | `FileStore` | File persistence engine |
| `upload` | `handle_message_post` | Multipart upload interception |
| `delete_handler` | `handle_app_delete, handle_message_delete, recover_on_startup` | DELETE file cleanup and crash recovery |
| `cleanup` | `cleanup_loop` | Periodic expiration sweep of pending files |
| `websocket_relay` | `stream_proxy` | Bidirectional WebSocket relay with URL rewriting |
