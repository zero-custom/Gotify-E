import re
import json
import logging

import tornado.web
import tornado.httpclient
import tornado.websocket
import tornado.ioloop
from tornado.httpclient import AsyncHTTPClient

from config import (
    BACKEND, PUBLIC_URL, HOST, PORT,
    UPLOAD_DIR, GATEWAY_DIR, MAX_UPLOAD, IMAGE_EXTS,
    MARKER_PREFIX,
)
from storage import FileStore, FileRejectedError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("gotify-gateway")

UPLOAD_DIR.mkdir(exist_ok=True)
file_store = FileStore(UPLOAD_DIR, MARKER_PREFIX, IMAGE_EXTS)


def build_backend_url(path, query=""):
    url = f"{BACKEND}{path}"
    if query:
        url += f"?{query}"
    return url


def build_gateway_url(handler):
    if PUBLIC_URL:
        return PUBLIC_URL
    req = handler.request
    scheme = req.headers.get("X-Forwarded-Proto", req.protocol)
    host = req.headers.get("Host", f"localhost:{PORT}")
    return f"{scheme}://{host}"


class UploadedFileHandler(tornado.web.StaticFileHandler):

    def set_extra_headers(self, path):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Cache-Control", "public, max-age=3600")
        if path.lower().endswith(".svg"):
            self.set_header("Content-Security-Policy", "script-src 'none'")


_MESSAGE_PATHS = {"/message", "/message/"}


def _is_message_endpoint(path: str) -> bool:
    p = path.rstrip("/")
    if p in _MESSAGE_PATHS:
        return True
    parts = p.split("/")
    return bool(len(parts) == 4 and parts[1] == "application" and parts[3] == "message")


def _is_version_endpoint(path: str) -> bool:
    return path.rstrip("/") == "/version"


def rewrite_file_urls(body: bytes, current_base: str) -> bytes:
    if not current_base or not body:
        return body
    text = body.decode("utf-8")
    text = text.replace(MARKER_PREFIX, f"{current_base}/uploads/")
    return text.encode("utf-8")


def _inject_i18n(output: bytes) -> bytes:
    body_str = output.decode("utf-8")
    script = '<script src="/_gateway/i18n.js"></script></body>'
    replaced = re.sub(r'(?i)(</body>)', script, body_str, count=1)
    if replaced == body_str:
        return output
    return replaced.encode("utf-8")


def _inject_gateway_info(output: bytes) -> bytes:
    try:
        data = json.loads(output)
        if isinstance(data, dict):
            data["_gateway"] = "Gotify[E]"
            data["_upload_max"] = MAX_UPLOAD
            return json.dumps(data, ensure_ascii=False).encode("utf-8")
    except json.JSONDecodeError:
        pass
    return output


_http_client = AsyncHTTPClient(max_body_size=MAX_UPLOAD)


def _format_error(status_code: int, message: str, backend_url: str = "") -> dict:
    err: dict[str, object] = {"error": message, "code": status_code}
    if backend_url:
        err["backend"] = backend_url
    return err


async def proxy_to_backend(
    handler: tornado.web.RequestHandler,
    method: str = None,
    headers: dict = None,
    body: bytes = None,
):
    method = method or handler.request.method
    backend_url = build_backend_url(handler.request.path, handler.request.query)

    if headers is None:
        headers = {}
        for k, v in handler.request.headers.items():
            kl = k.lower()
            if kl not in ("host", "transfer-encoding", "content-encoding"):
                headers[k] = v

    if body is None and method in ("POST", "PUT", "PATCH"):
        body = handler.request.body

    try:
        resp = await _http_client.fetch(
            backend_url, method=method, headers=headers,
            body=body, follow_redirects=False,
        )
        handler.set_status(resp.code)
        for k, v in resp.headers.items():
            kl = k.lower()
            if kl not in ("transfer-encoding", "content-encoding", "alt-svc"):
                handler.set_header(k, v)

        output = resp.body or b""
        content_type = resp.headers.get("Content-Type", "")
        path = handler.request.path

        if output and method == "GET" and _is_message_endpoint(path):
            current = PUBLIC_URL or build_gateway_url(handler)
            output = rewrite_file_urls(output, current)

        if output and "text/html" in content_type:
            output = _inject_i18n(output)
            handler.clear_header("Content-Length")

        if output and method == "GET" and _is_version_endpoint(path) and "json" in content_type:
            output = _inject_gateway_info(output)
            handler.clear_header("Content-Length")

        if output:
            handler.write(output)
    except tornado.httpclient.HTTPClientError as e:
        handler.set_status(e.code or 502)
        if e.response and e.response.body:
            handler.write(e.response.body)
        else:
            handler.write(_format_error(e.code or 502, str(e), backend_url))
    except Exception as e:
        log.error("proxy error %s: %s", backend_url, e)
        handler.set_status(502)
        handler.write(_format_error(502, f"gateway proxy error: {e}", backend_url))


class ProxyHandler(tornado.web.RequestHandler):

    async def get(self): await proxy_to_backend(self)
    async def post(self): await proxy_to_backend(self)
    async def put(self): await proxy_to_backend(self)
    async def delete(self): await proxy_to_backend(self)
    async def patch(self): await proxy_to_backend(self)
    async def head(self): await proxy_to_backend(self)
    async def options(self): await proxy_to_backend(self)

    def write_error(self, status_code, **kwargs):
        if not self._finished:
            self.set_header("Content-Type", "application/json")
            self.write(
                _format_error(status_code, self._reason or "unknown error")
            )


class MessageHandler(tornado.web.RequestHandler):

    async def get(self):
        await proxy_to_backend(self)

    async def delete(self):
        await proxy_to_backend(self)

    async def put(self):
        await proxy_to_backend(self)

    async def post(self):
        content_type = self.request.headers.get("Content-Type", "")
        is_multipart = "multipart/form-data" in content_type

        if not is_multipart:
            return await proxy_to_backend(self)

        message = self.get_argument("message", "")
        title = self.get_argument("title", "")
        priority = self.get_argument("priority", None)
        files = self.request.files.get("file", [])

        if not files:
            return await proxy_to_backend(self)

        injected_lines = []

        for f in files:
            try:
                stored = file_store.save(f["filename"], f["body"])
                injected_lines.append(stored.markdown)
                log.info("saved %s → %s (%d bytes)", f["filename"], stored.marker_url, len(f["body"]))
            except FileRejectedError as e:
                log.info("rejected %s: %s", f["filename"], e)

        if injected_lines:
            sep = "\n\n---\n" if message.strip() else ""
            message = message.rstrip() + sep + "\n".join(injected_lines)

        payload = {
            "message": message,
            "title": title,
            "priority": int(priority) if priority else 5,
        }
        payload["extras"] = {
            "client::display": {"contentType": "text/markdown"}
        }

        req_headers = {"Content-Type": "application/json"}
        token = self.get_query_argument("token", None)
        if token:
            req_headers["X-Gotify-Key"] = token

        await proxy_to_backend(self, method="POST", headers=req_headers, body=json.dumps(payload).encode())
        log.info("pushed message with %d file(s)", len(files))


class StreamProxyHandler(tornado.websocket.WebSocketHandler):

    def check_origin(self, origin):
        return True

    async def open(self):
        self.backend_ws = None
        self.closed = False

        # 构造后端 WebSocket URL
        qs = self.request.query
        ws_backend = BACKEND.replace("http://", "ws://").replace("https://", "wss://")
        backend_url = f"{ws_backend}{self.request.path}"
        if qs:
            backend_url += f"?{qs}"

        try:
            self.backend_ws = await tornado.websocket.websocket_connect(
                backend_url,
                on_message_callback=self.on_backend_message,
            )
            log.info("websocket connected to backend %s", backend_url)
        except Exception as e:
            log.error("websocket connect failed: %s", e)
            self.close()

    async def on_message(self, message):
        if self.backend_ws and not self.closed:
            self.backend_ws.write_message(message)

    def on_backend_message(self, message):
        if self.closed:
            return
        if message is None:
            self.close()
            return
        try:
            # rewrite file markers in stream messages
            if isinstance(message, bytes):
                text = message.decode("utf-8")
            else:
                text = message
            current = PUBLIC_URL or build_gateway_url(self)
            text = rewrite_file_urls(text.encode("utf-8"), current)
            self.write_message(text)
        except Exception:
            self.close()

    def on_close(self):
        self.closed = True
        if self.backend_ws:
            self.backend_ws.close()


# ── 应用与启动 ──────────────────────────────────────────

def make_app():
    routes = [
        (r"/uploads/(.*)", UploadedFileHandler, {"path": str(UPLOAD_DIR)}),
        (r"/_gateway/(.*)", UploadedFileHandler, {"path": str(GATEWAY_DIR)}),
        (r"/message", MessageHandler),
        (r"/stream", StreamProxyHandler),
        (r"/.*", ProxyHandler),
    ]
    return tornado.web.Application(routes, max_buffer_size=MAX_UPLOAD)


def main():
    log.info("=" * 52)
    log.info("  Gotify[E]")
    log.info("  Backend: %s", BACKEND)
    log.info("  Listen : http://%s:%s", HOST, PORT)
    log.info("  Uploads: %s", UPLOAD_DIR)
    log.info("=" * 52)

    app = make_app()
    app.listen(PORT, address=HOST)
    try:
        tornado.ioloop.IOLoop.current().start()
    except KeyboardInterrupt:
        log.info("shutting down")


if __name__ == "__main__":
    main()
