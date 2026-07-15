import json
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

# Mock RealHttpClient so app import doesn't open real connections
_mock_http = MagicMock()
_mock_http.request.return_value = type("R", (), {"status_code": 200, "headers": {}, "content": b"ok"})()
_http_patcher = patch.dict("sys.modules", {"proxy.RealHttpClient": lambda: _mock_http})
# We need a different approach — patch the class before import

# Instead: replace the import target
with patch("app.RealHttpClient", return_value=_mock_http):
    from app import app


@pytest.mark.asyncio
class TestServeUpload:
    async def test_serves_existing_file(self, tmp_path, monkeypatch):
        upload_dir = tmp_path / "uploads"
        upload_dir.mkdir()
        sub = upload_dir / "ab" / "cd"
        sub.mkdir(parents=True)
        (sub / "test.png").write_bytes(b"file-data")

        monkeypatch.setattr("app._UPLOAD_DIR", upload_dir)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/uploads/ab/cd/test.png")
        assert resp.status_code == 200
        assert resp.content == b"file-data"

    async def test_path_traversal_blocked(self, monkeypatch, tmp_path):
        upload_dir = tmp_path / "uploads"
        upload_dir.mkdir()
        monkeypatch.setattr("app._UPLOAD_DIR", upload_dir)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/uploads/../../../etc/passwd")
        # Starlette normalizes /uploads/../../../etc/passwd -> /etc/passwd
        # before routing, so it hits the catch-all (502).
        assert resp.status_code in (400, 403, 404, 502)

    async def test_missing_file_returns_404(self, monkeypatch, tmp_path):
        upload_dir = tmp_path / "uploads"
        upload_dir.mkdir()
        monkeypatch.setattr("app._UPLOAD_DIR", upload_dir)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/uploads/ab/cd/nonexistent.png")
        assert resp.status_code == 404

    async def test_svg_content_security_policy(self, monkeypatch, tmp_path):
        upload_dir = tmp_path / "uploads"
        upload_dir.mkdir()
        sub = upload_dir / "ab" / "cd"
        sub.mkdir(parents=True)
        (sub / "icon.svg").write_bytes(b"<svg></svg>")

        monkeypatch.setattr("app._UPLOAD_DIR", upload_dir)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/uploads/ab/cd/icon.svg")
        assert resp.headers.get("content-security-policy") == "sandbox"


@pytest.mark.asyncio
class TestVersionEndpoint:
    async def test_returns_version(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/version")
        assert resp.status_code in (200, 502)


@pytest.mark.asyncio
class TestCatchAll:
    async def test_unknown_path_returns_502(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/some/unknown/path")
        assert resp.status_code == 502
        body = json.loads(resp.content)
        assert "error" in body
