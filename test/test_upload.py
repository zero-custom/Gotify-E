import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from upload import FileProcessingResult, _process_files, handle_message_post
from storage import StoredFile


@pytest.mark.asyncio
class TestProcessFiles:
    @staticmethod
    def _upload_file(filename: str, content: bytes):
        f = AsyncMock(spec=["filename", "read"])
        f.filename = filename
        f.read = AsyncMock(return_value=content)
        return f

    async def test_upload_file_success(self):
        store = MagicMock()
        store.save.return_value = StoredFile(
            marker_url="{gateway}/uploads/ab/cd/photo.png",
            markdown="![photo](http://gw/uploads/ab/cd/photo.png)",
            uuid="abcdef1234567890abcdef1234567890", path="ab/cd/abcdef1234567890abcdef1234567890_photo.png", size=4,
            original_name="photo.png",
        )
        files = [self._upload_file("photo.png", b"data")]
        result = await _process_files(files, store)
        assert isinstance(result, FileProcessingResult)
        assert len(result.injected_lines) == 1
        assert result.injected_lines[0] == "![photo](http://gw/uploads/ab/cd/photo.png)"
        assert len(result.stored_files) == 1
        assert result.stored_files[0].uuid == "abcdef1234567890abcdef1234567890"

    async def test_rejected_file_is_skipped_not_raised(self):
        store = MagicMock()
        store.save.side_effect = RuntimeError("disk full")
        files = [self._upload_file("photo.png", b"data")]
        result = await _process_files(files, store)
        assert len(result.injected_lines) == 0
        assert len(result.stored_files) == 0

    async def test_mixed_success_and_failure(self):
        store = MagicMock()

        def _save(filename, body, **_kw):
            if b"bad" in body:
                raise RuntimeError("bad file")
            return StoredFile(
                marker_url=f"{{gateway}}/uploads/xy/zz/{filename}",
                markdown=f"![{filename}](http://gw/{filename})",
                uuid=filename.split(".")[0], path=f"xy/zz/{filename}",
                size=len(body), original_name=filename,
            )

        store.save.side_effect = _save
        files = [
            self._upload_file("good.png", b"good-data"),
            self._upload_file("bad.png", b"bad-data"),
            self._upload_file("ok.png", b"ok-data"),
        ]
        result = await _process_files(files, store)
        assert len(result.injected_lines) == 2
        assert len(result.stored_files) == 2

    async def test_no_files(self):
        result = await _process_files([], MagicMock())
        assert result.injected_lines == []
        assert result.stored_files == []

    async def test_raw_string_saved(self):
        store = MagicMock()
        store.save.return_value = StoredFile(
            marker_url="{gateway}/uploads/ab/cd/raw",
            markdown="[uploaded_file]({gateway}/uploads/ab/cd/raw)",
            uuid="r0", path="ab/cd/r0_raw", size=14,
            original_name="uploaded_file",
        )
        result = await _process_files(["raw text content"], store)
        assert len(result.injected_lines) == 1

    async def test_mime_mismatch_mock_returns_file(self):
        """MIME mismatch in storage.py now returns saved file with .bin ext.
        This test validates that _process_files handles a stored .bin result."""
        store = MagicMock()
        store.save.return_value = StoredFile(
            marker_url="{gateway}/uploads/ab/cd/abcdef1234567890abcdef1234567890_photo.bin",
            markdown="[evil.png]({gateway}/uploads/ab/cd/abcdef1234567890abcdef1234567890_photo.bin)",
            uuid="abcdef1234567890abcdef1234567890", path="ab/cd/abcdef1234567890abcdef1234567890_photo.bin", size=12,
            original_name="evil.png",
        )
        files = [self._upload_file("evil.png", b"not-really-png")]
        result = await _process_files(files, store)
        assert len(result.injected_lines) == 1
        assert ".bin" in result.injected_lines[0]
        assert "evil.png" in result.injected_lines[0]

    async def test_raw_bytes_saved(self):
        store = MagicMock()
        store.save.return_value = StoredFile(
            marker_url="{gateway}/uploads/ab/cd/raw",
            markdown="[uploaded_file]({gateway}/uploads/ab/cd/raw)",
        )
        result = await _process_files([b"raw bytes"], store)
        assert len(result.injected_lines) == 1


@pytest.mark.asyncio
class TestHandleMessagePost:
    async def test_non_multipart_passthrough(self, fake_http, any_response):
        fake_http.responses = [any_response(content=b"backend ok")]
        store = MagicMock()
        req = MagicMock()
        req.headers = {"content-type": "application/json"}
        resp = await handle_message_post(req, file_store=store, http_client=fake_http)
        assert resp.status_code == 200
        assert resp.body == b"backend ok"

    async def test_content_encoding_rejected(self, fake_http):
        store = MagicMock()
        req = MagicMock()
        req.headers = {
            "content-type": "multipart/form-data; boundary=xxx",
            "content-encoding": "gzip",
        }
        resp = await handle_message_post(req, file_store=store, http_client=fake_http)
        assert resp.status_code == 415
        body = resp.body
        assert b"compressed upload not supported" in body

    async def test_content_encoding_identity_allowed(self, fake_http, any_response):
        fake_http.responses = [any_response(content=b'{"id":2}')]
        store = MagicMock()
        store.confirm = AsyncMock()
        store.save.return_value = StoredFile(
            marker_url="{gateway}/uploads/ab/cd/photo.png",
            markdown="![photo](http://gw/photo.png)",
            uuid="abcdef1234567890abcdef1234567890", path="ab/cd/abcdef1234567890abcdef1234567890_photo.png", size=4,
            original_name="photo.png",
        )
        form_obj = MagicMock()
        form_obj.get.side_effect = lambda k, d=None: {
            "message": "hello",
            "title": "test",
            "priority": "5",
        }.get(k, d)
        form_obj.getlist.return_value = [self._make_upload_file()]
        req = MagicMock()
        req.headers = {
            "content-type": "multipart/form-data; boundary=xxx",
            "content-encoding": "identity",
        }
        req.query_params = {}
        req.form = AsyncMock(return_value=form_obj)
        resp = await handle_message_post(req, file_store=store, http_client=fake_http)
        assert resp.status_code == 200

    async def test_multipart_with_files(self, fake_http, any_response):
        fake_http.responses = [any_response(content=b'{"id":1}')]
        store = MagicMock()
        store.confirm = AsyncMock()
        store.save.return_value = StoredFile(
            marker_url="{gateway}/uploads/ab/cd/photo.png",
            markdown="![photo](http://gw/photo.png)",
            uuid="abcdef1234567890abcdef1234567890", path="ab/cd/abcdef1234567890abcdef1234567890_photo.png", size=4,
            original_name="photo.png",
        )

        form_obj = MagicMock()
        form_obj.get.side_effect = lambda k, d=None: {
            "message": "hello",
            "title": "test",
            "priority": "5",
        }.get(k, d)
        form_obj.getlist.return_value = [self._make_upload_file()]

        req = MagicMock()
        req.headers = {"content-type": "multipart/form-data; boundary=xxx"}
        req.query_params = {}
        req.form = AsyncMock(return_value=form_obj)

        resp = await handle_message_post(req, file_store=store, http_client=fake_http)
        assert resp.status_code == 200

        _, _, _, body = fake_http.requests[-1]
        payload = json.loads(body)
        assert "gateway::files" in payload["extras"]
        assert payload["extras"]["gateway::files"] == [
            {"uuid": "abcdef1234567890abcdef1234567890", "path": "ab/cd/abcdef1234567890abcdef1234567890_photo.png", "name": "photo.png", "size": 4},
        ]

    async def test_multipart_without_files(self, fake_http, any_response):
        fake_http.responses = [any_response(content=b'{"id":1}')]
        store = MagicMock()
        form_obj = MagicMock()
        form_obj.get.side_effect = lambda k, d=None: {
            "message": "hello", "title": "", "priority": "5",
        }.get(k, d)
        form_obj.getlist.return_value = []
        req = MagicMock()
        req.headers = {"content-type": "multipart/form-data; boundary=xxx"}
        req.query_params = {}
        req.form = AsyncMock(return_value=form_obj)
        resp = await handle_message_post(req, file_store=store, http_client=fake_http)
        assert resp.status_code == 200
        _, _, _, body = fake_http.requests[-1]
        payload = json.loads(body)
        assert "gateway::files" not in payload.get("extras", {})

    @staticmethod
    def _make_upload_file():
        f = AsyncMock(spec=["filename", "read"])
        f.filename = "photo.png"
        f.read = AsyncMock(return_value=b"data")
        return f
