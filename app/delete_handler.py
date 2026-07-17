import asyncio
import json
import logging
from pathlib import Path

from config import load_env_config, GatewayConfig
from pending_store import PendingStore

_cfg = load_env_config()
_BACKEND = _cfg.gotify_backend
_UPLOAD_DIR = Path(GatewayConfig.UPLOAD_DIR)
_PENDING_DIR = Path(GatewayConfig.PENDING_DIR)
_DELETE_CONCURRENCY = _cfg.delete_concurrency
_PENDING_TIMEOUT_SECONDS = _cfg.pending_timeout_minutes * 60
from proxy import HttpClient, format_error, proxy_to_backend

log = logging.getLogger("gotify-gateway.delete")

_store = PendingStore(_UPLOAD_DIR, _PENDING_DIR, _PENDING_TIMEOUT_SECONDS)
_DELETE_CONCURRENCY_SEM = asyncio.Semaphore(_DELETE_CONCURRENCY)


def _collect_auth(request):
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
    token, auth_headers = _collect_auth(request)

    if not ids:
        ids, files_by_id = await _enumerate_all_message_files(token, auth_headers, http_client)
        if not ids:
            return await proxy_to_backend(request, method="DELETE", http_client=http_client)
        return await _store.safe_delete(
            ids, files_by_id,
            proxy_to_backend(request, method="DELETE", http_client=http_client),
        )

    async def fetch(mid: int):
        async with _DELETE_CONCURRENCY_SEM:
            return mid, await _fetch_gateway_files(mid, token, auth_headers, http_client)

    results = await asyncio.gather(*[fetch(mid) for mid in ids])
    files_by_id = {mid: files for mid, files in results if files}
    return await _store.safe_delete(
        ids, files_by_id,
        proxy_to_backend(request, method="DELETE", http_client=http_client),
    )


async def handle_app_delete(request, app_id, http_client, file_store=None):
    token, auth_headers = _collect_auth(request)
    messages = await _enumerate_app_messages(app_id, token, auth_headers, http_client)
    if not messages:
        return await proxy_to_backend(request, method="DELETE", http_client=http_client)
    async def process_msg(msg):
        async with _DELETE_CONCURRENCY_SEM:
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


_LIST_LIMIT = 100


async def _iter_messages(url, token, auth_headers, http_client, *, paginate=False):
    since = None
    while True:
        query = f"?limit={_LIST_LIMIT}"
        if since is not None:
            query += f"&since={since}"
        query += f"&token={token}" if token else ""
        try:
            resp = await http_client.request(
                "GET", f"{url}{query}", headers=auth_headers,
            )
        except Exception:
            log.warning("iter messages failed for %s", url, exc_info=True)
            break
        if resp.status_code != 200:
            break
        body = json.loads(resp.content)
        if isinstance(body, dict):
            messages = body.get("messages") or []
        elif isinstance(body, list):
            messages = body
        else:
            break
        if not messages:
            break
        for msg in messages:
            yield msg
        if not paginate:
            break
        paging = body.get("paging") if isinstance(body, dict) else None
        since = paging.get("since") if isinstance(paging, dict) else None
        if since is None or len(messages) < _LIST_LIMIT:
            break


async def _enumerate_all_message_files(token, auth_headers, http_client):
    all_ids: list[int] = []
    files_by_id: dict[int, list] = {}
    url = f"{_BACKEND}/message"
    async for msg in _iter_messages(url, token, auth_headers, http_client, paginate=True):
        mid = msg.get("id")
        if mid is None:
            continue
        all_ids.append(mid)
        extras = msg.get("extras") or {}
        raw = extras.get("gateway::files") or []
        if raw:
            files_by_id[mid] = list(raw)
    return all_ids, files_by_id


async def _enumerate_app_messages(app_id, token, auth_headers, http_client):
    url = f"{_BACKEND}/application/{app_id}/message"
    messages: list[dict] = []
    async for msg in _iter_messages(url, token, auth_headers, http_client, paginate=False):
        messages.append(msg)
    return messages


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
            await _store.restore([e])
            _store.remove_entries([mid])
