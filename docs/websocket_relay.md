# websocket_relay.py — WebSocket Authentication Relay

Implements the bidirectional WebSocket relay for the `/stream` endpoint, with authentication token passthrough from the client's browser cookies.

## Entry Point

### `stream_proxy(websocket: WebSocket)`

The sole public function, called from `app.py` on the `/stream` WebSocket route.

```
Client WebSocket ──→ FastAPI WebSocket ──→ Backend WebSocket (via websockets library)
```

**Authentication flow:**

```
Browser Cookie: gotify-client-token=xxxx
       │
       ▼
websocket.cookies["gotify-client-token"] = "xxxx"
       │
       ▼
backend_url = "ws://host:8083/stream?token=xxxx"
       │
       ▼
Backend readTokenFromRequest: ?token=xxxx → ✅ Authorized
```

The Gotify backend checks authentication in this order:
1. `?token=` query parameter
2. `X-Gotify-Key` header
3. `Authorization: Bearer` header
4. `Cookie: gotify-client-token` header

Since browser `new WebSocket()` cannot send custom headers (a browser API limitation), cookies are the only vehicle for credentials. This relay extracts the `gotify-client-token` from the incoming WebSocket's cookies and appends it as a `?token=` query parameter to the backend URL — matching the backend's first-priority auth check.

**Why query param over Cookie passthrough (extra_headers):**

| Aspect | Cookie passthrough (方案 B) | Token query param (方案 A — chosen) |
|--------|---------------------------|-------------------------------------|
| Precision | Sends all cookies (potential info leak) | Sends only the auth token |
| Backend match | Matches 4th-priority check | Matches 1st-priority check |
| Library compatibility | `websockets` library behaviour with `Cookie` in `extra_headers` varies by version | Works universally |
| Browser API `new WebSocket()` | Does not send `Authorization: Basic` | N/A |

## Relay Logic

On accept, the function:

1. Constructs the backend WebSocket URL from `_BACKEND` (http→ws protocol swap)
2. Extracts `gotify-client-token` from `websocket.cookies` and appends as `?token=` query parameter (if not already present in query params)
3. Connects to the backend via `websockets.connect(backend_url)`
4. Runs two concurrent `asyncio` tasks:

### `client_to_backend()`

Forwards messages from the client to the backend. Listens via `websocket.receive()` and forwards text/bytes messages through the backend WebSocket. Handles `WebSocketDisconnect` to detect client disconnection.

### `backend_to_client()`

Receives messages from the backend via `backend_ws.recv()`. Before forwarding to the client, rewrites file marker URLs using `rewrite_file_urls()` from `proxy.py`. Handles `websockets.ConnectionClosed` for backend disconnection.

### Cleanup

When either direction disconnects, both tasks are signalled via the `closed` flag, and the client WebSocket is closed in a `finally` block:

```python
finally:
    closed = True
    try:
        await websocket.close()
    except Exception:
        pass
```

## Error Handling

| Condition | Behaviour |
|---|---|
| `WebSocketDisconnect` (client) | Sets `closed = True`, breaks the loop |
| `websockets.ConnectionClosed` (backend) | Sets `closed = True`, breaks the loop |
| Any `Exception` during connect/relay | Logged as `"websocket error: {e}"` |
| Exception during final `websocket.close()` | Silently ignored (connection already dead) |

## Configuration

| Constant | Source | Description |
|---|---|---|
| `_BACKEND` | `load_env_config().gotify_backend` | Backend URL, transformed from http→ws or https→wss |

## Related

- `proxy.rewrite_file_urls()` — File URL marker replacement (for `_gateway` file links in messages)
- `app.py` — Route registration: `@app.websocket("/stream")`
- `docs/websocket-auth-proxy.zh.md` — Root cause analysis and solution decision record
