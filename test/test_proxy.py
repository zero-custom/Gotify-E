import json

import httpx
import pytest

from proxy import (
    RealHttpClient,
    build_backend_url,
    build_gateway_url,
    format_error,
    inject_gateway_info,
    inject_i18n,
    is_message_endpoint,
    is_version_endpoint,
    proxy_to_backend,
    rewrite_file_urls,
)


# ── Endpoint helpers ─────────────────────────────────────


class TestIsMessageEndpoint:
    def test_message_root(self):
        assert is_message_endpoint("/message") is True

    def test_message_root_trailing(self):
        assert is_message_endpoint("/message/") is True

    def test_application_message(self):
        assert is_message_endpoint("/application/1/message") is True

    def test_application_message_trailing(self):
        assert is_message_endpoint("/application/1/message/") is True

    def test_other_path(self):
        assert is_message_endpoint("/version") is False
        assert is_message_endpoint("/health") is False
        assert is_message_endpoint("/application/1/other") is False


class TestIsVersionEndpoint:
    def test_version(self):
        assert is_version_endpoint("/version") is True

    def test_version_trailing(self):
        assert is_version_endpoint("/version/") is True

    def test_other(self):
        assert is_version_endpoint("/message") is False
        assert is_version_endpoint("/health") is False


class TestBuildBackendUrl:
    def test_without_query(self):
        url = build_backend_url("/message")
        assert url == "http://gotify-test:8080/message"

    def test_with_query(self):
        url = build_backend_url("/message", "token=abc")
        assert url == "http://gotify-test:8080/message?token=abc"


class TestBuildGatewayUrl:
    def test_uses_public_url_when_set(self):
        from config import load_env_config
        cfg = load_env_config()
        assert cfg.public_url == "http://gw-test:8765"

    def test_fallback_without_public_url(self, monkeypatch):
        import proxy
        monkeypatch.setattr(proxy, "_PUBLIC_URL", "")
        url = build_gateway_url(MockConn())
        assert "localhost" in url

    def test_x_forwarded_proto(self, monkeypatch):
        import proxy
        monkeypatch.setattr(proxy, "_PUBLIC_URL", "")
        conn = MockConn(headers={"X-Forwarded-Proto": "https", "Host": "gw.example.com"})
        url = build_gateway_url(conn)
        assert url == "https://gw.example.com"


class MockConn:
    """Minimal stand-in for starlette.requests.HTTPConnection."""
    def __init__(self, headers=None):
        self.headers = headers or {}
        self.url = type("URL", (), {"scheme": "http", "hostname": "localhost"})()


# ── URL rewriting ────────────────────────────────────────


class TestRewriteFileUrls:
    def test_replace_marker(self):
        body = b"prefix {gateway}/uploads/abc/def.jpg suffix"
        result = rewrite_file_urls(body, "http://gw:8765")
        assert result == b"prefix http://gw:8765/uploads/abc/def.jpg suffix"

    def test_empty_body(self):
        assert rewrite_file_urls(b"", "http://gw:8765") == b""

    def test_no_marker(self):
        body = b"no marker here"
        assert rewrite_file_urls(body, "http://gw:8765") == body


# ── Response injection ───────────────────────────────────


class TestInjectI18n:
    def test_basic_html(self):
        html = b"<html><head></head><body>hello</body></html>"
        result = inject_i18n(html)
        assert b'i18n.js' in result
        assert b"</body><script" in result

    def test_no_body_tag(self):
        assert inject_i18n(b"no body here") == b"no body here"

    def test_case_insensitive(self):
        html = b"<HTML><BODY>hello</BODY></HTML>"
        result = inject_i18n(html)
        assert b"</BODY><script" in result

    def test_whitespace_in_tag(self):
        html = b"<html><body >hello</body ></html>"
        result = inject_i18n(html)
        assert b"</body ><script" in result

    def test_multiline_html(self):
        html = b"<html>\n<head></head>\n<body>\nhello\n</body>\n</html>"
        result = inject_i18n(html)
        assert b"\n</body>\n<script" in result or b"i18n.js" in result


class TestInjectGatewayInfo:
    def test_injects_fields(self):
        original = json.dumps({"version": 3}).encode()
        result = inject_gateway_info(original)
        data = json.loads(result)
        assert data["_gateway"] == "Gotify[e]"
        assert data["_upload_max"] > 0
        assert data["version"] == 3

    def test_non_json_body(self):
        assert inject_gateway_info(b"not json") == b"not json"

    def test_non_dict_json(self):
        assert inject_gateway_info(b"[1,2,3]") == b"[1,2,3]"


class TestFormatError:
    def test_without_backend(self):
        err = format_error(502, "bad gateway")
        assert err == {"error": "bad gateway", "code": 502}

    def test_with_backend(self):
        err = format_error(500, "fail", "http://backend")
        assert err == {"error": "fail", "code": 500, "backend": "http://backend"}


# ── Proxy pipeline ───────────────────────────────────────


class FakeRequest:
    def __init__(self, method="GET", path="/message", query="", headers=None, body=b""):
        self.method = method
        self.url = type("URL", (), {"path": path, "query": query, "scheme": "http", "hostname": "localhost"})()
        self.headers = headers or {}
        self._body = body

    async def body(self):
        return self._body

    @property
    def query_params(self):
        return {}


@pytest.mark.asyncio
class TestProxyToBackend:
    async def test_simple_proxy(self, fake_http, any_response):
        fake_http.responses = [any_response(status_code=200, content=b"hello")]
        req = FakeRequest(method="GET", path="/version")
        resp = await proxy_to_backend(req, http_client=fake_http)
        assert resp.status_code == 200
        assert resp.body == b"hello"

    async def test_strips_origin_header(self, fake_http, any_response):
        fake_http.responses = [any_response(content=b"ok")]
        req = FakeRequest(method="GET", path="/message", headers={"Origin": "http://evil.com", "Host": "gw"})
        await proxy_to_backend(req, http_client=fake_http)
        meth, url, headers, body = fake_http.requests[0]
        assert headers.get("Origin") is None or "Origin" not in str(headers)

    async def test_502_on_connection_error(self, fake_http):
        req = FakeRequest(method="GET", path="/message")
        resp = await proxy_to_backend(req, http_client=fake_http)
        assert resp.status_code == 502
        body = json.loads(resp.body)
        assert "proxy error" in body["error"]

    async def test_injects_i18n_on_html(self, fake_http, any_response):
        html = b"<html><body>hi</body></html>"
        fake_http.responses = [any_response(content=html, headers={"content-type": "text/html"})]
        req = FakeRequest(method="GET", path="/some/page")
        resp = await proxy_to_backend(req, http_client=fake_http)
        assert b"i18n.js" in resp.body

    async def test_injects_gateway_info_on_version(self, fake_http, any_response):
        data = json.dumps({"version": 3}).encode()
        fake_http.responses = [any_response(content=data, headers={"content-type": "application/json"})]
        req = FakeRequest(method="GET", path="/version")
        resp = await proxy_to_backend(req, http_client=fake_http)
        parsed = json.loads(resp.body)
        assert parsed["_gateway"] == "Gotify[e]"

    async def test_rewrites_file_urls_on_message(self, fake_http, any_response):
        body = b"file at {gateway}/uploads/abc.jpg"
        fake_http.responses = [any_response(content=body, headers={"content-type": "application/json"})]
        req = FakeRequest(method="GET", path="/message")
        resp = await proxy_to_backend(req, http_client=fake_http)
        assert b"http://gw-test:8765/uploads/abc.jpg" in resp.body
