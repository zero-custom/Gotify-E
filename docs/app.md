# app.py — Tornado Application & Entrypoint

Main Tornado application. Defines HTTP routes, reverse proxy pipeline, file upload interception, WebSocket relay, and the `main()` entrypoint.

## Routes

| Path | Handler | Description |
|---|---|---|
| `/uploads/(.*)` | `UploadedFileHandler` | Static file serving for uploaded files. Sets CORS, Cache-Control, and SVG CSP header. |
| `/_gateway/(.*)` | `UploadedFileHandler` | Static file serving for gateway assets (i18n scripts). |
| `/message` | `MessageHandler` | Intercepts `multipart/form-data` POST for file uploads; GET/DELETE/PUT transparently proxied. |
| `/stream` | `StreamProxyHandler` | WebSocket bidirectional relay with message URL rewriting. |
| `/.*` | `ProxyHandler` | Catch-all transparent proxy for all remaining requests. |

## Handler Classes

### `UploadedFileHandler(tornado.web.StaticFileHandler)`

Serves static files from `UPLOAD_DIR` (uploads) and `GATEWAY_DIR` (gateway assets).

| Header | Value | Condition |
|---|---|---|
| `Access-Control-Allow-Origin` | `*` | Always |
| `Cache-Control` | `public, max-age=3600` | Always |
| `Content-Security-Policy` | `script-src 'none'` | Only for `.svg` files |

### `ProxyHandler(tornado.web.RequestHandler)`

Generic transparent proxy. Delegates all 7 HTTP methods (GET, POST, PUT, DELETE, PATCH, HEAD, OPTIONS) to `proxy_to_backend`. Sets `Content-Type: application/json` on write errors with uniform `_format_error` response.

### `MessageHandler(tornado.web.RequestHandler)`

Handles GET/DELETE/PUT by transparent proxy. POST has two code paths:

| Content-Type | Behavior |
|---|---|
| Not `multipart/form-data` | Transparent proxy to Gotify backend |
| `multipart/form-data` + files | Saves each file via `FileStore.save()`, appends Markdown links to message body, then proxies JSON payload to backend |
| `multipart/form-data` + no files | Transparent proxy (falls through) |

The Markdown separator between existing message text and file links is omitted when the message body is empty.

### `StreamProxyHandler(tornado.websocket.WebSocketHandler)`

WebSocket bidirectional relay between client and Gotify backend `/stream`. On `open()`, constructs a WebSocket URL from `BACKEND` (http→ws protocol swap) and connects. Client→backend messages pass through unmodified. Backend→client messages are decoded, file markers rewritten to public URLs via `rewrite_file_urls`, then forwarded.

## Response Pipeline (`proxy_to_backend`)

```
Client → proxy_to_backend → Gotify backend
                                ↓
                         Response body
                                ↓
        ┌───────────┬────────────┬───────────┐
        ↓           ↓            ↓           ↓
   rewrite_   _inject_    _inject_    _format_
   file_urls  i18n       gateway_    error
   (GET msg)  (HTML)     info        (on error)
                         (GET /ver)
```

| Step | Trigger | Effect |
|---|---|---|
| `rewrite_file_urls` | GET + message endpoint + body non-empty | Replaces `{gateway}/uploads/` with `{current_base}/uploads/` |
| `_inject_i18n` | `text/html` Content-Type | Inserts `<script src="/_gateway/i18n.js">` before `</body>` (case-insensitive) |
| `_inject_gateway_info` | GET `/version` + JSON Content-Type | Injects `_gateway`, `_upload_max` fields into JSON response |
| `_format_error` | HTTPClientError | Returns `{error, code, backend}` |
| `_format_error` | Other Exception | Returns `{error, code, backend}` with 502 |

## Helper Functions

| Function | Arguments | Return | Description |
|---|---|---|---|
| `build_backend_url` | `path, query=""` | `str` | Constructs full backend URL: `{BACKEND}{path}?{query}` |
| `build_gateway_url` | `handler` | `str` | Returns `PUBLIC_URL` if set, else infers from `X-Forwarded-Proto` + `Host` headers |
| `_is_message_endpoint` | `path: str` | `bool` | True for `/message`, `/message/`, `/application/{id}/message` |
| `_is_version_endpoint` | `path: str` | `bool` | True for `/version` |
| `rewrite_file_urls` | `body: bytes, current_base: str` | `bytes` | Replaces `MARKER_PREFIX` with `{current_base}/uploads/` in response body |
| `_inject_i18n` | `output: bytes` | `bytes` | Case-insensitive `</body>` → inject i18n script tag |
| `_inject_gateway_info` | `output: bytes` | `bytes` | JSON parse→inject `_gateway`+`_upload_max`→JSON serialize |
| `_format_error` | `status_code, message, backend_url=""` | `dict` | Returns `{error, code, backend?}` |

## Application Factory

`make_app()` builds the `tornado.web.Application` with route table and `max_buffer_size=MAX_UPLOAD`.

## Entrypoint

`main()` — Logs startup configuration, calls `make_app()`, listens on `{HOST}:{PORT}`, starts IOLoop. Catches `KeyboardInterrupt` for clean shutdown.
