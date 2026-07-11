import asyncio
import json
import logging
from pathlib import Path

from config import load_env_config
from pending_store import PendingStore

_cfg = load_env_config()
_BACKEND = _cfg.gotify_backend
_UPLOAD_DIR = Path(_cfg.upload_dir)
_PENDING_DIR = Path(_cfg.pending_dir)
_DELETE_CONCURRENCY = _cfg.delete_concurrency
_PENDING_TIMEOUT_SECONDS = _cfg.pending_timeout_minutes * 60
from proxy import HttpClient, format_error, proxy_to_backend

log = logging.getLogger("gotify-gateway.delete")

_store = PendingStore(_UPLOAD_DIR, _PENDING_DIR, _PENDING_TIMEOUT_SECONDS)


def _collect_auth(request):
    """Extract token/X-Gotify-Key/Authorization from request for backend calls."""
    token = request.query_params.get("token")
    x_key = request.headers.get("X-Gotify-Key")
    auth = request.headers.get("Authorization")
    headers = {}
    if x_key:
        headers["X-Gotify-Key"] = x_key
    elif auth:
        headers["Authorization"] = auth
    return token, headers


async def handle_message_delete(request, http_client, file_store=None, msg_id=None):
    ids = _collect_ids(request, msg_id)
    if not ids:
        return await proxy_to_backend(request, method="DELETE", http_client=http_client)
    token, auth_headers = _collect_auth(request)
    files_by_id = {}
    for mid in ids:
        files = await _fetch_gateway_files(mid, token, auth_headers, http_client)
        if files:
            files_by_id[mid] = files
    return await _store.safe_delete(
        ids, files_by_id,
        proxy_to_backend(request, method="DELETE", http_client=http_client),
    )


async def handle_app_delete(request, app_id, http_client, file_store=None):
    token, auth_headers = _collect_auth(request)
    messages = await _enumerate_app_messages(app_id, token, auth_headers, http_client)
    if not messages:
        return await proxy_to_backend(request, method="DELETE", http_client=http_client)
    sem = asyncio.Semaphore(_DELETE_CONCURRENCY)

    async def process_msg(msg):
        async with sem:
            mid = msg.get("id")
            if not mid:
                return mid, []
            files = await _fetch_gateway_files(mid, token, auth_headers, http_client)
            return mid, files

    results = await asyncio.gather(*[process_msg(m) for m in messages])
    files_by_id = {mid: files for mid, files in results if files}
    mids = [m.get("id") for m in messages if m.get("id")]

    return await _store.safe_delete(
        mids, files_by_id,
        proxy_to_backend(request, method="DELETE", http_client=http_client),
    )


def _collect_ids(request, msg_id):
    if msg_id is not None:
        return [msg_id]
    ids_str = request.query_params.get("ids")
    if ids_str:
        try:
            return json.loads(ids_str)
        except (json.JSONDecodeError, TypeError):
            return []
    return []


async def _fetch_gateway_files(msg_id, token, auth_headers, http_client):
    query = f"&token={token}" if token else ""
    try:
        # since=X → id < X, sorted descending → newest first.
        # since=msg_id+1&limit=1 pinpoints exactly the target message.
        resp = await http_client.request(
            "GET", f"{_BACKEND}/message?limit=1&since={msg_id + 1}{query}",
            headers=auth_headers,
        )
        if resp.status_code != 200:
            return []
        body = json.loads(resp.content)
        messages = body.get("messages") or []
        if not messages:
            return []
        msg = messages[0]
        if msg.get("id") != msg_id:
            return []
        extras = msg.get("extras") or {}
        raw = extras.get("gateway::files") or []
        return list(raw)
    except Exception:
        log.warning("failed to fetch message %s", msg_id, exc_info=True)
        return []


async def _enumerate_app_messages(app_id, token, auth_headers, http_client):
    path = f"{_BACKEND}/application/{app_id}/message"
    query = f"?token={token}" if token else ""
    try:
        resp = await http_client.request("GET", f"{path}{query}", headers=auth_headers)
        if resp.status_code != 200:
            return []
        body = json.loads(resp.content)
        # Gotify returns {"messages": [...], "paging": {...}}, unwrap.
        if isinstance(body, dict):
            return body.get("messages") or []
        if isinstance(body, list):
            return body
        return []
    except Exception:
        log.warning("failed to enumerate app %s messages", app_id, exc_info=True)
        return []


async def _message_exists(mid, token, auth_headers, http_client):
    query = f"&token={token}" if token else ""
    try:
        resp = await http_client.request(
            "GET", f"{_BACKEND}/message?limit=1&since={mid + 1}{query}",
            headers=auth_headers,
        )
        if resp.status_code != 200:
            return None
        body = json.loads(resp.content)
        messages = body.get("messages") or []
        if not messages:
            return None
        msg = messages[0]
        if msg.get("id") != mid:
            return None
        return msg
    except Exception:
        return None


async def recover_on_startup(http_client):
    entries = _store.read_manifest()
    for e in entries:
        if e.get("status") != "moved":
            continue
        mid = e.get("msg_id")
        if not mid:
            continue
        msg = await _message_exists(mid, None, None, http_client)
        if msg is None:
            _store.update_status([mid], "deleted")
        else:
            _store.restore([e])
            _store.remove_entries([mid])
