# delete_handler.py — DELETE Interception & File Cleanup

Intercepts `DELETE /message` and `DELETE /application/{id}/message` to move gateway-managed files to a pending directory before proxying the delete to the Gotify backend. On delete confirmation, files are marked for eventual cleanup; on failure, files are restored.

Delegates the move–execute–rollback transaction to `PendingStore.safe_delete()`.

## Flow

### `DELETE /message` (no ids — "delete all")

```
DELETE /message
  │
  ├─ _enumerate_all_message_files() — paginated scan of ALL messages
  │     ├─ _iter_messages(paginate=True) page 1:  GET /message?limit=100
  │     ├─ _iter_messages(paginate=True) page N:  GET /message?limit=100&since=N
  │     └─ collect extras.gateway::files from each message
  ├─ If no messages → transparent proxy (pass through)
  ├─ PendingStore.safe_delete(all_ids, files_by_id, delete_coro)
  └─ Return response
```

### `DELETE /message/{msg_id}` / `DELETE /message?ids=[...]`

```
DELETE /message{/id}?ids=[...]
  │
  ├─ Parse IDs from path or ?ids= query
  ├─ Concurrently fetch extras.gateway::files for each ID
  │   (throughput capped by shared _DELETE_CONCURRENCY_SEM)
  ├─ Collect files_by_id mapping
  ├─ PendingStore.safe_delete(msg_ids, files_by_id, delete_coro)
  └─ Return response
```

### `DELETE /application/{id}/message`

```
DELETE /application/{id}/message
  │
  ├─ _enumerate_app_messages() — GET /application/{id}/message
  ├─ Concurrently fetch extras.gateway::files for each message
  │   (throughput capped by shared _DELETE_CONCURRENCY_SEM)
  ├─ PendingStore.safe_delete(msg_ids, files_by_id, delete_coro)
  └─ Return response
```

## Functions

### `handle_message_delete(request, http_client, file_store=None, msg_id=None)`

Single / batch / all message delete. Behaviour depends on whether message IDs are present:

| IDs present | Action |
|---|---|
| No (`ids=[]`) | Calls `_enumerate_all_message_files()` to paginate through ALL messages, collect `gateway::files`, then `safe_delete()` |
| Yes (path param or `?ids=`) | Concurrently fetches file descriptors for each ID, then `safe_delete()` |

Throughput for concurrent fetches is capped by the shared `DELETE_CONCURRENCY` semaphore (same pool used by `handle_app_delete`).

### `handle_app_delete(request, app_id, http_client, file_store=None)`

Bulk delete for an entire application (`DELETE /application/{id}/message`).

1. Calls `_enumerate_app_messages()` via `_iter_messages(paginate=False)`
2. Concurrently fetches each message's `extras.gateway::files` (throughput capped by the shared `DELETE_CONCURRENCY` semaphore)
3. Delegates to `PendingStore.safe_delete()`

### `_collect_ids(request, msg_id) -> list[int]`

Parses message IDs from request parameters. Priority: `msg_id` argument > `?ids=` JSON array > empty.

### `_fetch_gateway_files(msg_id, token, auth_header, http_client) -> list[dict]`

Performs a GET on `/message?limit=1&since={msg_id + 1}` — since Gotify returns messages sorted descending (newest first), `since=msg_id+1&limit=1` pinpoints exactly the target message. Verifies `msg.id == msg_id` before extracting `extras.gateway::files`. Returns `[]` on any error (404, timeout, non-JSON response, ID mismatch).

### `_iter_messages(url, token, auth_headers, http_client, *, paginate=False)`

Async generator that yields messages from the backend GET response. Two modes:

| `paginate` | Behaviour | Usage |
|---|---|---|
| `False` | Single request, yields all messages at once | `_enumerate_app_messages()` |
| `True` | Paginated traversal: first request without `since`, subsequent requests with `paging.since` from response. Stops when `since` is None or result count < limit. | `_enumerate_all_message_files()` |

Auth is passed via `?token=` query param (when token is present) and `auth_headers` dict.

### `_enumerate_all_message_files(token, auth_headers, http_client) -> tuple[list[int], dict[int, list]]`

Paginates through ALL messages on the backend using `_iter_messages(paginate=True)`. Collects every message ID and its `extras.gateway::files` list. Returns `(all_ids, files_by_id)`.

### `_enumerate_app_messages(app_id, token, auth_headers, http_client) -> list[dict]`

Lists all messages for a given application using `_iter_messages(paginate=False)`. Returns `[]` on any error.

### `recover_on_startup(http_client)`

Called during app lifespan startup. Scans the manifest for entries with `status: "moved"` and verifies the corresponding Gotify message still exists:

| GET result | Action |
|---|---|
| 200 (message exists) | Restore files to `upload_dir`, remove manifest entries |
| 404 (message deleted) | Mark manifest entry as `deleted` (cleanup_loop will eventually unlink) |
| Error (network) | Leave in pending, log warning |

## Dependencies

| Module | Usage |
|---|---|
| `pending_store.PendingStore` | File move, manifest CRUD, restore, `safe_delete` |
| `proxy.HttpClient` | GET message file list |
| `proxy.proxy_to_backend` | Forward DELETE as `delete_coro` to `safe_delete` |

## Configuration

| Constant | Source | Description |
|---|---|---|
| `_DELETE_CONCURRENCY` | `cfg.delete_concurrency` | Max concurrent GET requests during file descriptor fetching. Shared module-level semaphore used by both `handle_message_delete` and `handle_app_delete`. |
| `_LIST_LIMIT` | `100` | Page size for `_iter_messages` paginated traversal. |
| `_PENDING_TIMEOUT_SECONDS` | `cfg.pending_timeout_minutes * 60` | How long files stay in pending before `cleanup_loop` removes them |
