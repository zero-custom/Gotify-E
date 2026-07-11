import html.parser
import json
import logging
from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, Response
from starlette.requests import HTTPConnection

from config import load_env_config, GatewayConfig

_cfg = load_env_config()
_BACKEND = _cfg.gotify_backend
_PUBLIC_URL = _cfg.public_url
_PORT = _cfg.port
_MARKER_PREFIX = f"{_cfg.stored_marker.rstrip('/')}/uploads/"
_MAX_UPLOAD = _cfg.max_upload_mb * 1024 * 1024

log = logging.getLogger("gotify-gateway.proxy")


# ── HttpClient abstraction ──────────────────────────────


@dataclass
class HttpResponse:
    status_code: int
    headers: dict[str, str]
    content: bytes


@runtime_checkable
class HttpClient(Protocol):
    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        content: bytes | None = None,
        follow_redirects: bool = False,
    ) -> HttpResponse:
        ...


class RealHttpClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=10.0),
            limits=httpx.Limits(max_keepalive_connections=50, max_connections=100),
        )

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        content: bytes | None = None,
        follow_redirects: bool = False,
    ) -> HttpResponse:
        resp = await self._client.request(
            method, url,
            headers=headers,
            content=content,
            follow_redirects=follow_redirects,
        )
        return HttpResponse(
            status_code=resp.status_code,
            headers=dict(resp.headers),
            content=resp.content or b"",
        )

    async def aclose(self) -> None:
        await self._client.aclose()


# ── Endpoint helpers ────────────────────────────────────


_MESSAGE_PATHS = {"/message", "/message/"}


def is_message_endpoint(path: str) -> bool:
    p = path.rstrip("/")
    if p in _MESSAGE_PATHS:
        return True
    parts = p.split("/")
    return bool(len(parts) == 4 and parts[1] == "application" and parts[3] == "message")


def is_version_endpoint(path: str) -> bool:
    return path.rstrip("/") == "/version"


def build_backend_url(path: str, query: str = "") -> str:
    url = f"{_BACKEND}{path}"
    if query:
        url += f"?{query}"
    return url


def build_gateway_url(conn: HTTPConnection) -> str:
    if _PUBLIC_URL:
        return _PUBLIC_URL
    scheme = conn.headers.get("X-Forwarded-Proto", conn.url.scheme)
    http_scheme = scheme.replace("ws://", "http://").replace("wss://", "https://")
    if http_scheme == scheme:
        http_scheme = scheme.replace("ws", "http").replace("wss", "https")
    host = conn.headers.get("Host", conn.url.hostname or f"localhost:{_PORT}")
    return f"{http_scheme}://{host}"


def rewrite_file_urls(body: bytes, current_base: str) -> bytes:
    if not current_base or not body:
        return body
    text = body.decode("utf-8")
    text = text.replace(_MARKER_PREFIX, f"{current_base}/uploads/")
    return text.encode("utf-8")


# ── Response injection ─────────────────────────────────


def inject_i18n(output: bytes) -> bytes:
    text = output.decode("utf-8")
    script_tag = '<script src="/_gateway/i18n.js"></script>'

    # Pre-compute line start offsets for converting (line, col) → char index
    lines = text.split("\n")
    line_offsets = [0]
    for line in lines[:-1]:
        line_offsets.append(line_offsets[-1] + len(line) + 1)  # +1 for newline

    class BodyFinder(html.parser.HTMLParser):
        def __init__(self):
            super().__init__()
            self.body_end_char = -1

        def handle_endtag(self, tag: str) -> None:
            if tag == "body":
                lineno, col = self.getpos()  # 1-indexed line, 0-indexed col
                if 0 < lineno <= len(line_offsets):
                    self.body_end_char = line_offsets[lineno - 1] + col

    finder = BodyFinder()
    try:
        finder.feed(text)
        finder.close()
    except html.parser.HTMLParseError:
        log.warning("i18n: HTML parse error, skipping injection")
        return output

    if finder.body_end_char < 0:
        log.warning("i18n: no </body> tag found in response, skipping injection")
        return output

    close_pos = text.index(">", finder.body_end_char) + 1
    result = text[:close_pos] + script_tag + text[close_pos:]
    return result.encode("utf-8")


def inject_gateway_info(output: bytes) -> bytes:
    try:
        data = json.loads(output)
        if isinstance(data, dict):
            data["_gateway"] = "Gotify[e]"
            data["_upload_max"] = _MAX_UPLOAD
            return json.dumps(data, ensure_ascii=False).encode("utf-8")
    except json.JSONDecodeError:
        pass
    return output


def format_error(status_code: int, message: str, backend_url: str = "") -> dict:
    err: dict[str, object] = {"error": message, "code": status_code}
    if backend_url:
        err["backend"] = backend_url
    return err


# ── Response transform pipeline ──────────────────────────


_TransformFn = Callable[[bytes, str, str, str, Request], bytes]


def _rewrite_message_urls(output: bytes, method: str, path: str, content_type: str, request: Request) -> bytes:
    if output and method == "GET" and is_message_endpoint(path):
        current = _PUBLIC_URL or build_gateway_url(request)
        return rewrite_file_urls(output, current)
    return output


def _inject_i18n_transform(output: bytes, method: str, path: str, content_type: str, request: Request) -> bytes:
    if output and "text/html" in content_type:
        return inject_i18n(output)
    return output


def _inject_gateway_info_transform(output: bytes, method: str, path: str, content_type: str, request: Request) -> bytes:
    if output and method == "GET" and is_version_endpoint(path) and "json" in content_type:
        return inject_gateway_info(output)
    return output


_transforms: list[_TransformFn] = [
    _rewrite_message_urls,
    _inject_i18n_transform,
    _inject_gateway_info_transform,
]


# ── Proxy pipeline ─────────────────────────────────────


_BLOCKED_RESPONSE_HEADERS = frozenset({
    "transfer-encoding", "content-encoding", "alt-svc", "content-length",
})


async def proxy_to_backend(
    request: Request,
    http_client: HttpClient,
    method: str | None = None,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
) -> Response:
    method = method or request.method
    backend_url = build_backend_url(request.url.path, request.url.query)

    if headers is None:
        headers = {}
        for k, v in request.headers.items():
            kl = k.lower()
            if kl not in ("host", "origin", "transfer-encoding", "content-encoding"):
                headers[k] = v

    if body is None and method in ("POST", "PUT", "PATCH"):
        body = await request.body()

    try:
        resp = await http_client.request(
            method, backend_url,
            headers=headers,
            content=body,
            follow_redirects=False,
        )

        resp_headers = {
            k: v
            for k, v in resp.headers.items()
            if k.lower() not in _BLOCKED_RESPONSE_HEADERS
        }

        output = resp.content
        content_type = resp.headers.get("content-type", "")
        path = str(request.url.path)

        for t in _transforms:
            output = t(output, method, path, content_type, request)

        return Response(content=output, status_code=resp.status_code, headers=resp_headers)

    except httpx.RequestError as e:
        log.error("proxy error %s: %s", backend_url, e)
        return JSONResponse(
            status_code=502,
            content=format_error(502, f"gateway proxy error: {e}", backend_url),
        )
