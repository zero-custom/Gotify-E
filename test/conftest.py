"""Env vars set at module level so config.py picks them up
before any test module is imported.
"""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

os.environ.setdefault("GOTIFY_BACKEND", "http://gotify-test:8080")
os.environ.setdefault("PUBLIC_HOST", "gw-test:8765")
os.environ.setdefault("HOST", "0.0.0.0")
os.environ.setdefault("PORT", "8765")

APP_DIR = Path(__file__).parent.parent / "app"
sys.path.insert(0, str(APP_DIR))

_magic = MagicMock()
_magic.from_buffer.return_value = "application/octet-stream"
sys.modules["magic"] = _magic

import pytest
from pytest import fixture

from proxy import HttpClient, HttpResponse


class FakeHttpClient:
    """In-memory HttpClient with FIFO response queue.

    When all responses are consumed, .request() raises httpx.RequestError
    so proxy_to_backend returns its JSON 502 error format.
    """

    def __init__(self):
        self.responses: list[HttpResponse] = []
        self.requests: list[tuple] = []

    async def request(self, method, url, *, headers=None, content=None, follow_redirects=False):
        self.requests.append((method, url, headers, content))
        if self.responses:
            return self.responses.pop(0)
        import httpx
        raise httpx.RequestError("fake connection error", request=httpx.Request(method, url))

    async def aclose(self):
        pass


@fixture
def fake_http():
    return FakeHttpClient()


@fixture
def any_response():
    def _build(**kw):
        return HttpResponse(
            status_code=kw.get("status_code", 200),
            headers=kw.get("headers", {"content-type": "text/plain"}),
            content=kw.get("content", b"ok"),
        )
    return _build


@fixture
def tmp_upload_dir(tmp_path):
    d = tmp_path / "uploads"
    d.mkdir()
    return d
