import json
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from delete_handler import (
    _collect_ids, _fetch_gateway_files, _enumerate_app_messages,
    recover_on_startup, handle_message_delete, handle_app_delete,
    _DELETE_CONCURRENCY_SEM,
)
from pending_store import PendingStore
from proxy import HttpResponse


def _gw_files(*suffixes):
    return [
        {"uuid": f"{i:032x}", "path": f"ab/cd/{i:032x}_{s}", "name": s, "size": 100}
        for i, s in enumerate(suffixes)
    ]


def _make_response(status=200, content=b"{}", headers=None):
    return HttpResponse(
        status_code=status,
        headers=headers or {"content-type": "application/json"},
        content=content,
    )


def _make_gotify_msg(msg_id, files=None):
    extras = {"client::display": {"contentType": "text/markdown"}}
    if files:
        extras["gateway::files"] = files
    body = json.dumps({
        "messages": [{
            "id": msg_id, "message": "test", "title": "", "priority": 5,
            "extras": extras,
        }],
        "paging": {"limit": 100, "since": max(0, msg_id - 1), "size": 1},
    }).encode()
    return _make_response(content=body)


def _store_for(upload_dir, pending_dir, timeout=7200):
    return PendingStore(upload_dir, pending_dir, timeout)


@pytest.mark.asyncio
class TestCollectIds:
    async def test_from_query_param(self):
        req = MagicMock()
        req.query_params = {"ids": "[1,2,3]"}
        assert _collect_ids(req, None) == [1, 2, 3]

    async def test_from_path_param(self):
        req = MagicMock()
        req.query_params = {}
        assert _collect_ids(req, 42) == [42]

    async def test_empty_when_no_ids(self):
        req = MagicMock()
        req.query_params = {}
        assert _collect_ids(req, None) == []

    async def test_invalid_ids_param(self):
        req = MagicMock()
        req.query_params = {"ids": "not-json"}
        assert _collect_ids(req, None) == []


@pytest.mark.asyncio
class TestFetchGatewayFiles:
    async def test_returns_files_when_present(self, fake_http):
        files = _gw_files("photo.png")
        fake_http.responses = [_make_gotify_msg(1, files)]
        result = await _fetch_gateway_files(1, None, None, fake_http)
        assert len(result) == 1
        assert result[0]["path"] == "ab/cd/00000000000000000000000000000000_photo.png"

    async def test_returns_empty_when_no_extras(self, fake_http):
        fake_http.responses = [_make_response(content=json.dumps({
            "messages": [{"id": 1, "message": "no extras"}],
            "paging": {"limit": 100, "since": 0, "size": 1},
        }).encode())]
        result = await _fetch_gateway_files(1, None, None, fake_http)
        assert result == []

    async def test_returns_empty_on_404(self, fake_http):
        fake_http.responses = [_make_response(status=404)]
        result = await _fetch_gateway_files(99, None, None, fake_http)
        assert result == []

    async def test_passes_auth_token(self, fake_http, any_response):
        fake_http.responses = [_make_gotify_msg(1)]
        await _fetch_gateway_files(1, "mytoken", None, fake_http)
        assert any(
            "token=mytoken" in url
            for _, url, _, _ in fake_http.requests
        )

    async def test_passes_auth_header(self, fake_http, any_response):
        fake_http.responses = [_make_gotify_msg(1)]
        await _fetch_gateway_files(1, None, {"X-Gotify-Key": "myheader"}, fake_http)
        assert any(
            h and h.get("X-Gotify-Key") == "myheader"
            for _, _, h, _ in fake_http.requests
        )


@pytest.mark.asyncio
class TestEnumerateAppMessages:
    async def test_returns_messages(self, fake_http):
        body = json.dumps({"messages": [{"id": 1}, {"id": 2}], "paging": {"limit": 100, "since": 0, "size": 2}}).encode()
        fake_http.responses = [_make_response(content=body)]
        result = await _enumerate_app_messages(1, None, None, fake_http)
        assert len(result) == 2

    async def test_returns_empty_on_error(self, fake_http):
        fake_http.responses = [_make_response(status=403)]
        result = await _enumerate_app_messages(1, None, None, fake_http)
        assert result == []


@pytest.mark.asyncio
class TestMoveToPending:
    async def test_moves_file_and_returns_entry(self, tmp_path):
        uploads = tmp_path / "uploads"
        pending = tmp_path / "_pending"
        file_dir = uploads / "ab" / "cd"
        file_dir.mkdir(parents=True)
        src = file_dir / "00000000000000000000000000000000_photo.png"
        src.write_text("data")
        files = [{"path": "ab/cd/00000000000000000000000000000000_photo.png", "uuid": "00000000000000000000000000000000", "name": "photo.png", "size": 4}]
        store = _store_for(uploads, pending)
        moved = await store.move_to_pending(1, files)
        assert len(moved) == 1
        assert not src.exists()
        assert (pending / moved[0]["pending_path"]).exists()
        assert (pending / moved[0]["pending_path"]).read_text() == "data"
        assert moved[0]["orig_path"] == "ab/cd/00000000000000000000000000000000_photo.png"
        assert moved[0]["msg_id"] == 1

    async def test_skips_nonexistent_file(self, tmp_path):
        uploads = tmp_path / "uploads"
        pending = tmp_path / "_pending"
        (uploads / "ab" / "cd").mkdir(parents=True)
        files = [{"path": "ab/cd/00000000000000000000000000000000_missing.png", "uuid": "00000000000000000000000000000000", "name": "missing.png", "size": 4}]
        store = _store_for(uploads, pending)
        moved = await store.move_to_pending(1, files)
        assert moved == []


@pytest.mark.asyncio
class TestPathFormatValidation:
    async def test_rejects_short_uuid(self, tmp_path):
        uploads = tmp_path / "uploads"
        pending = tmp_path / "_pending"
        files = [{"path": "ab/cd/short_photo.png", "uuid": "short", "name": "photo.png", "size": 4}]
        store = _store_for(uploads, pending)
        moved = await store.move_to_pending(1, files)
        assert moved == []

    async def test_rejects_traversal_path(self, tmp_path):
        uploads = tmp_path / "uploads"
        pending = tmp_path / "_pending"
        files = [{"path": "../../../etc/passwd", "uuid": "evil", "name": "passwd", "size": 99}]
        store = _store_for(uploads, pending)
        moved = await store.move_to_pending(1, files)
        assert moved == []

    async def test_rejects_non_hex_prefix(self, tmp_path):
        uploads = tmp_path / "uploads"
        pending = tmp_path / "_pending"
        files = [{"path": "zz/qq/00000000000000000000000000000000_photo.png", "uuid": "00000000000000000000000000000000", "name": "photo.png", "size": 4}]
        store = _store_for(uploads, pending)
        moved = await store.move_to_pending(1, files)
        assert moved == []

    async def test_accepts_valid_format(self, tmp_path):
        uploads = tmp_path / "uploads"
        pending = tmp_path / "_pending"
        (uploads / "ab" / "cd").mkdir(parents=True)
        src = uploads / "ab" / "cd" / "00000000000000000000000000000000_photo.png"
        src.write_text("data")
        files = [{"path": "ab/cd/00000000000000000000000000000000_photo.png", "uuid": "00000000000000000000000000000000", "name": "photo.png", "size": 4}]
        store = _store_for(uploads, pending)
        moved = await store.move_to_pending(1, files)
        assert len(moved) == 1


@pytest.mark.asyncio
class TestRestoreFiles:
    async def test_moves_file_back(self, tmp_path):
        uploads = tmp_path / "uploads"
        pending = tmp_path / "_pending"
        (uploads / "ab" / "cd").mkdir(parents=True)
        pending_sub = pending / "20260709"
        pending_sub.mkdir(parents=True)
        (pending_sub / "ab_cd_00000000000000000000000000000000_photo.png").write_text("data")
        moved = [{"msg_id": 1, "orig_path": "ab/cd/00000000000000000000000000000000_photo.png", "pending_path": "20260709/ab_cd_00000000000000000000000000000000_photo.png"}]
        store = _store_for(uploads, pending)
        await store.restore(moved)
        assert (uploads / "ab/cd/00000000000000000000000000000000_photo.png").exists()
        assert not (pending_sub / "ab_cd_00000000000000000000000000000000_photo.png").exists()


class TestManifest:
    def test_write_and_read(self, tmp_path):
        pending = tmp_path / "_pending"
        store = _store_for(tmp_path / "uploads", pending)
        moved = [{"msg_id": 1, "orig_path": "ab/cd/p.png", "pending_path": "20260709/ab_cd_p.png"}]
        store.append_manifest(1, moved)
        entries = store.read_manifest()
        assert len(entries) == 1
        assert entries[0]["msg_id"] == 1
        assert entries[0]["status"] == "moved"

    def test_update_status(self, tmp_path):
        pending = tmp_path / "_pending"
        store = _store_for(tmp_path / "uploads", pending)
        moved = [{"msg_id": 1, "orig_path": "ab/cd/p.png", "pending_path": "20260709/ab_cd_p.png"}]
        store.append_manifest(1, moved)
        store.update_status([1], "deleted")
        entries = store.read_manifest()
        assert entries[0]["status"] == "deleted"

    def test_remove_entries(self, tmp_path):
        pending = tmp_path / "_pending"
        store = _store_for(tmp_path / "uploads", pending)
        store.append_manifest(1, [{"msg_id": 1, "orig_path": "a", "pending_path": "b"}])
        store.append_manifest(2, [{"msg_id": 2, "orig_path": "c", "pending_path": "d"}])
        store.remove_entries([1])
        entries = store.read_manifest()
        assert len(entries) == 1
        assert entries[0]["msg_id"] == 2


class TestCleanExpiredPending:
    def test_removes_expired_entries(self, tmp_path):
        pending = tmp_path / "_pending"
        manifest = pending / "manifest.jsonl"
        pending.mkdir(parents=True)
        store = _store_for(tmp_path / "uploads", pending, timeout=7200)
        old_time = time.time() - store._pending_timeout_seconds - 10
        old_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(old_time))
        entry = json.dumps({
            "msg_id": 1, "orig_path": "ab/cd/p.png",
            "pending_path": "20260709/ab_cd_p.png",
            "time": old_iso, "status": "moved",
        })
        manifest.write_text(entry + "\n")
        store.clean_expired()
        remaining = store.read_manifest()
        assert len(remaining) == 0

    def test_keeps_recent_entries(self, tmp_path):
        pending = tmp_path / "_pending"
        manifest = pending / "manifest.jsonl"
        pending.mkdir(parents=True)
        store = _store_for(tmp_path / "uploads", pending, timeout=7200)
        now_iso = datetime.now(timezone.utc).isoformat()
        entry = json.dumps({
            "msg_id": 1, "orig_path": "ab/cd/p.png",
            "pending_path": "20260709/ab_cd_p.png",
            "time": now_iso, "status": "moved",
        })
        manifest.write_text(entry + "\n")
        store.clean_expired()
        remaining = store.read_manifest()
        assert len(remaining) == 1


@pytest.mark.asyncio
class TestHandleMessageDelete:
    async def test_single_msg_with_files_success(self, fake_http, any_response, tmp_path):
        fake_http.responses = [
            _make_gotify_msg(1, _gw_files("photo.png")),
            any_response(status_code=200, content=b'{"id":1}'),
        ]
        req = MagicMock()
        req.query_params = {}
        req.headers = {}
        uploads = tmp_path / "uploads"
        pending = tmp_path / "_pending"
        store = _store_for(uploads, pending)
        (uploads / "ab/cd").mkdir(parents=True)
        (uploads / "ab/cd/00000000000000000000000000000000_photo.png").write_text("data")
        import delete_handler
        old_store = delete_handler._store
        delete_handler._store = store
        try:
            resp = await handle_message_delete(req, fake_http, msg_id=1)
            assert resp.status_code == 200
            entries = store.read_manifest()
            assert len(entries) == 1
            assert entries[0]["status"] == "moved"
        finally:
            delete_handler._store = old_store

    async def test_single_msg_no_files(self, fake_http, any_response, tmp_path):
        fake_http.responses = [
            _make_response(content=json.dumps({"id": 1, "message": "no attachments", "extras": {}}).encode()),
            any_response(status_code=200, content=b'{"id":1}'),
        ]
        req = MagicMock()
        req.query_params = {}
        req.headers = {}
        store = _store_for(tmp_path / "uploads", tmp_path / "_pending")
        import delete_handler
        old = delete_handler._store
        delete_handler._store = store
        try:
            resp = await handle_message_delete(req, fake_http, msg_id=1)
            assert resp.status_code == 200
            entries = store.read_manifest()
            assert len(entries) == 0
        finally:
            delete_handler._store = old

    async def test_msg_not_found_still_proxies(self, fake_http, any_response):
        fake_http.responses = [
            _make_response(status=404, content=b"not found"),
            any_response(status_code=200, content=b'ok'),
        ]
        req = MagicMock()
        req.query_params = {}
        req.headers = {}
        resp = await handle_message_delete(req, fake_http, msg_id=99)
        assert resp.status_code == 200

    async def test_delete_failure_restores_files(self, fake_http, any_response, tmp_path):
        fake_http.responses = [
            _make_gotify_msg(1, _gw_files("doc.pdf")),
            any_response(status_code=500, content=b'server error'),
        ]
        req = MagicMock()
        req.query_params = {}
        req.headers = {}
        uploads = tmp_path / "uploads"
        pending = tmp_path / "_pending"
        store = _store_for(uploads, pending)
        (uploads / "ab/cd").mkdir(parents=True)
        (uploads / "ab/cd/00000000000000000000000000000000_doc.pdf").write_text("data")
        import delete_handler
        old = delete_handler._store
        delete_handler._store = store
        try:
            resp = await handle_message_delete(req, fake_http, msg_id=1)
            assert resp.status_code == 500
            assert (uploads / "ab/cd/00000000000000000000000000000000_doc.pdf").exists()
            entries = store.read_manifest()
            assert len(entries) == 0
        finally:
            delete_handler._store = old

    async def test_multi_ids_from_query(self, fake_http, any_response):
        fake_http.responses = [
            _make_gotify_msg(1),
            _make_gotify_msg(2),
            any_response(status_code=200, content=b'ok'),
        ]
        req = MagicMock()
        req.query_params = {"ids": "[1,2]"}
        req.headers = {}
        resp = await handle_message_delete(req, fake_http)
        assert resp.status_code == 200

    async def test_continuous_delete(self, fake_http, any_response):
        req = MagicMock()
        req.query_params = {}
        req.headers = {}
        for i in range(3):
            fake_http.responses = [
                _make_gotify_msg(i),
                any_response(status_code=200, content=b'ok'),
            ]
            resp = await handle_message_delete(req, fake_http, msg_id=i)
            assert resp.status_code == 200

    async def test_multi_ids_concurrent_fetch(self, fake_http, any_response):
        fake_http.responses = [
            _make_gotify_msg(1, _gw_files("a.png")),
            _make_gotify_msg(2, _gw_files("b.png")),
            _make_gotify_msg(3, _gw_files("c.png")),
            _make_gotify_msg(4, _gw_files("d.png")),
            _make_gotify_msg(5, _gw_files("e.png")),
            any_response(status_code=200, content=b'ok'),
        ]
        req = MagicMock()
        req.query_params = {"ids": "[1,2,3,4,5]"}
        req.headers = {}
        resp = await handle_message_delete(req, fake_http)
        assert resp.status_code == 200
        fetch_count = sum(1 for m, u, _, _ in fake_http.requests if "message?limit=1&since=" in u)
        assert fetch_count == 5


@pytest.mark.asyncio
class TestConcurrencySemaphore:
    async def test_module_level_semaphore_is_asyncio_semaphore(self):
        import asyncio
        assert isinstance(_DELETE_CONCURRENCY_SEM, asyncio.Semaphore)

    async def test_module_level_semaphore_visible_via_import(self):
        import delete_handler as dh
        assert dh._DELETE_CONCURRENCY_SEM is _DELETE_CONCURRENCY_SEM


@pytest.mark.asyncio
class TestHandleAppDelete:
    async def test_deletes_all_messages(self, fake_http, any_response):
        msgs = json.dumps([{"id": 1}, {"id": 2}]).encode()
        fake_http.responses = [
            _make_response(content=msgs),
            _make_gotify_msg(1),
            _make_gotify_msg(2),
            any_response(status_code=200, content=b'ok'),
        ]
        req = MagicMock()
        req.query_params = {}
        req.headers = {}
        resp = await handle_app_delete(req, 1, fake_http)
        assert resp.status_code == 200

    async def test_empty_app(self, fake_http, any_response):
        fake_http.responses = [
            _make_response(content=b"[]"),
            any_response(status_code=200, content=b'ok'),
        ]
        req = MagicMock()
        req.query_params = {}
        req.headers = {}
        resp = await handle_app_delete(req, 1, fake_http)
        assert resp.status_code == 200

    async def test_failure_restores(self, fake_http, any_response, tmp_path):
        msgs = json.dumps([{"id": 1}]).encode()
        fake_http.responses = [
            _make_response(content=msgs),
            _make_gotify_msg(1, _gw_files("f.png")),
            any_response(status_code=500, content=b'error'),
        ]
        req = MagicMock()
        req.query_params = {}
        req.headers = {}
        uploads = tmp_path / "uploads"
        pending = tmp_path / "_pending"
        store = _store_for(uploads, pending)
        (uploads / "ab/cd").mkdir(parents=True)
        (uploads / "ab/cd/00000000000000000000000000000000_f.png").write_text("data")
        import delete_handler
        old = delete_handler._store
        delete_handler._store = store
        try:
            resp = await handle_app_delete(req, 1, fake_http)
            assert resp.status_code == 500
            assert (uploads / "ab/cd/00000000000000000000000000000000_f.png").exists()
        finally:
            delete_handler._store = old


@pytest.mark.asyncio
class TestRecovery:
    async def test_recovery_msg_still_exists_restores(self, fake_http, tmp_path):
        pending = tmp_path / "_pending"
        pending.mkdir(parents=True)
        pending_sub = pending / "20260709"
        pending_sub.mkdir()
        (pending_sub / "ab_cd_p.png").write_text("data")
        entry = json.dumps({
            "msg_id": 1, "orig_path": "ab/cd/p.png",
            "pending_path": "20260709/ab_cd_p.png",
            "time": "2026-07-09T12:00:00", "status": "moved",
        })
        (pending / "manifest.jsonl").write_text(entry + "\n")
        uploads = tmp_path / "uploads"
        (uploads / "ab/cd").mkdir(parents=True)
        fake_http.responses = [_make_gotify_msg(1)]
        store = _store_for(uploads, pending)
        import delete_handler
        old = delete_handler._store
        delete_handler._store = store
        try:
            await recover_on_startup(fake_http)
            assert (uploads / "ab/cd/p.png").exists()
            assert not (pending_sub / "ab_cd_p.png").exists()
        finally:
            delete_handler._store = old

    async def test_recovery_msg_deleted_marks_orphan(self, fake_http, tmp_path):
        pending = tmp_path / "_pending"
        pending.mkdir(parents=True)
        entry = json.dumps({
            "msg_id": 1, "orig_path": "ab/cd/p.png",
            "pending_path": "20260709/ab_cd_p.png",
            "time": "2026-07-09T12:00:00", "status": "moved",
        })
        (pending / "manifest.jsonl").write_text(entry + "\n")
        fake_http.responses = [_make_response(status=404)]
        store = _store_for(tmp_path / "uploads", pending)
        import delete_handler
        old = delete_handler._store
        delete_handler._store = store
        try:
            await recover_on_startup(fake_http)
            entries = store.read_manifest()
            assert entries[0]["status"] == "deleted"
        finally:
            delete_handler._store = old
