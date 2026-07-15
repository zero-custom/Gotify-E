# proxy.py — Reverse Proxy Pipeline

Implements the HTTP client abstraction, backend URL construction, response transform pipeline, and the core `proxy_to_backend` function.

## Http Client Abstraction

### `HttpResponse` (dataclass)

```python
@dataclass
class HttpResponse:
    status_code: int
    headers: dict[str, str]
    content: bytes
```

### `HttpClient` (protocol)

Injectable interface for backend communication. All proxy functions depend on this protocol, enabling test doubles.

```python
class HttpClient(Protocol):
    async def request(self, method, url, *, headers=None, content=None, follow_redirects=False) -> HttpResponse
```

### `RealHttpClient`

Production implementation wrapping `httpx.AsyncClient`:

| Setting | Value |
|---|---|
| Timeout | 120s (connect: 10s) |
| Keepalive connections | 50 |
| Max connections | 100 |

Provides `aclose()` for graceful shutdown.

## URL Helpers

### `build_backend_url(path, query="") -> str`

Constructs a full backend URL: `{BACKEND}{path}?{query}`. Query string is omitted when empty.

### `build_gateway_url(conn) -> str`

Returns the public gateway URL for file link rewriting. Resolution order:

1. `PUBLIC_HOST` configured → resolve candidate URL from request headers, check against whitelist:
   - **Match**: return candidate URL (used for marker rewriting)
   - **No match**: return `""` (skip rewriting — don't expose internal URLs)
2. `PUBLIC_HOST` not configured → **trust mode**: auto-detect from request headers, log a warning about Host header injection risk
3. `X-Forwarded-Proto` header + `Host` header (handles reverse proxy)
4. WebSocket URL scheme normalisation (ws→http, wss→https)

### `is_message_endpoint(path) -> bool`

Returns `True` for paths: `/message`, `/message/`, `/application/{id}/message`.

### `is_version_endpoint(path) -> bool`

Returns `True` for `/version`.

## Response Injection Functions

### `rewrite_file_urls(body, current_base) -> bytes`

Replaces `{stored_marker}/uploads/` marker strings in the response body with `{current_base}/uploads/`. Used in both HTTP proxy (`proxy_to_backend`) and WebSocket relay (`stream_proxy` in app.py).

Skips processing when `current_base` is empty or `body` is empty.

### `inject_i18n(output) -> bytes`

Inserts `<script src="/_gateway/i18n.js"></script>` before `</body>` in HTML responses. Uses `html.parser.HTMLParser` (not regex) to locate the closing body tag.

- Skips injection when no `</body>` is found
- Logs a warning on `HTMLParseError` and returns the original output
- Currently the i18n scripts are stub files (no translation data has been populated)

### `inject_gateway_info(output) -> bytes`

Injects `_gateway`, `_upload_max`, and `_max_files` fields into JSON responses from `/version`. Handles non-dict or non-JSON bodies gracefully by returning the original output unchanged.

### `format_error(status_code, message, backend_url="") -> dict`

Returns a standard error dict: `{"error": message, "code": status_code}`. Adds `"backend"` key when `backend_url` is non-empty.

### Token Sanitization

A `TokenSanitizingFilter` (from `log_filter.py`, referencing the Gotify 2.9.1 `tokenRegexp` pattern) is attached to the root logger at module level. It masks bearer tokens and query-parameter tokens in log messages using the pattern `token=[^&\s]+` → `token=[masked]`. This prevents credential leakage in application logs.

## Response Transform Pipeline

The pipeline replaces the original if-chain in `proxy_to_backend` with a registered list of transforms.

### Transform Type

```python
_TransformFn = Callable[[bytes, str, str, str, Request], bytes]
#                        output  method path  content_type  request
```

### Registered Transforms

| Function | Trigger | Effect |
|---|---|---|
| `_rewrite_message_urls` | GET + message endpoint + body non-empty | Calls `rewrite_file_urls(output, current_base)` |
| `_inject_i18n_transform` | `text/html` in content-type | Calls `inject_i18n(output)` |
| `_inject_gateway_info_transform` | GET + `/version` + JSON content-type | Calls `inject_gateway_info(output)` |

Each transform returns the output unchanged when its trigger condition is not met. Transforms are processed in registration order.

### Adding a New Transform

```python
from proxy import _transforms, _TransformFn

def my_transform(output, method, path, content_type, request) -> bytes:
    if output and <condition>:
        return do_something(output)
    return output

_transforms.append(my_transform)
```

## Request Body Security

### `_strip_gateway_extras(body, content_type) -> bytes`

Strips all `gateway::*` keys from `extras` in proxied JSON request bodies. Applied only when the body originates from the incoming request (not when explicitly passed by `upload.py`'s multipart handler, which is the legitimate source of `gateway::files`).

| Condition | Behaviour |
|---|---|
| Body is empty or non-JSON | Returned unchanged |
| `extras` key starts with `gateway::` | Key removed, body re-encoded |
| No `gateway::*` keys found | Returned unchanged (no re-encode overhead) |

This prevents clients from injecting `gateway::files` through non-multipart `POST /message`, `PUT /message`, or any proxied endpoint. Combined with the path format validation in `pending_store.py`, only the multipart upload handler can author `gateway::files` entries.

## Core Proxy Function

### `proxy_to_backend(request, http_client, method=None, headers=None, body=None) -> Response`

Central request proxy pipeline:

```
request
  │
  ├─ Determine method, build backend URL
  ├─ Filter request headers (strip: host, transfer-encoding, content-encoding)
  ├─ Read request body (POST/PUT/PATCH only)
  ├─ Strip gateway::* extras keys from JSON bodies (security — see below)
  ├─ http_client.request(method, backend_url, headers, body)
  │
  ├─ On success:
  │     ├─ Filter response headers (strip: transfer-encoding, content-encoding, alt-svc, content-length)
  │     ├─ Apply ResponseTransform pipeline (for t in _transforms: output = t(...))
  │     └─ Return Response(content, status_code, headers)
  │
  └─ On httpx.RequestError:
        └─ Return 502 JSONResponse with format_error()
```

| Header filter | Direction | Stripped |
|---|---|---|
| Request headers | Outgoing to backend | `host`, `transfer-encoding`, `content-encoding` |
| Response headers | Incoming to client | `transfer-encoding`, `content-encoding`, `alt-svc`, `content-length` |

> Note: `origin` was explicitly removed from the request header blacklist. The gateway is a transparent proxy and must preserve the Origin header so the backend can perform its own CORS validation.

## Public Interface

Modules that import from `proxy.py` use:

```python
from proxy import (
    HttpClient,          # Protocol — for type annotations
    RealHttpClient,      # Production HTTP client
    build_gateway_url,   # URL helper (used in app.py WebSocket)
    format_error,        # Error response helper (used in app.py, upload.py)
    proxy_to_backend,    # Core proxy function (used in app.py, upload.py, delete_handler.py)
    rewrite_file_urls,   # Marker rewriting (used in app.py WebSocket)
)
```
