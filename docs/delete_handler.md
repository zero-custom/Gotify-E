# delete_handler.py — DELETE Interception & File Cleanup

Intercepts `DELETE /message` and `DELETE /application/{id}/message` to move gateway-managed files to a pending directory before proxying the delete to the Gotify backend. On delete confirmation, files are marked for eventual cleanup; on failure, files are restored.

Delegates the move–execute–rollback transaction to `PendingStore.safe_delete()`.

## Flow

```
DELETE /message{/id}
  │
  ├─ Parse IDs from path or ?ids= query
  ├─ Concurrently fetch extras.gateway::files for each ID
  │   (throughput capped by shared _DELETE_CONCURRENCY_SEM)
  ├─ Collect files_by_id mapping
  ├─ PendingStore.safe_delete(msg_ids, files_by_id, delete_coro)
  │     ├─ move_to_pending() + append_manifest() for each msg_id
  │     ├─ Await delete_coro (proxy DELETE to backend)
  │     ├─ 200/204 → success, files stay in pending (cleanup_loop handles expiry)
  │     └─ anything else → restore files to upload_dir, remove manifest entries
  └─ Return response
```

## Functions

### `handle_message_delete(request, http_client, file_store=None, msg_id=None)`

Single / batch message delete. Accepts message IDs from:
- Path parameter `msg_id` (e.g., `/message/123`)
- Query parameter `?ids=[1,2,3]`

Concurrently fetches file descriptors for each ID (throughput capped by the shared `DELETE_CONCURRENCY` semaphore — same pool used by `handle_app_delete`), then delegates to `PendingStore.safe_delete()`.

### `handle_app_delete(request, app_id, http_client, file_store=None)`

Bulk delete for an entire application (`DELETE /application/{id}/message`).

1. Enumerates all messages via `GET /application/{id}/message`
2. Concurrently fetches each message's `extras.gateway::files` (throughput capped by the shared `DELETE_CONCURRENCY` semaphore — same pool used by `handle_message_delete`)
3. Delegates to `PendingStore.safe_delete()` with the aggregated `files_by_id`

### `_collect_ids(request, msg_id) -> list[int]`

Parses message IDs from request parameters. Priority: `msg_id` argument > `?ids=` JSON array > empty.

### `_fetch_gateway_files(msg_id, token, auth_header, http_client) -> list[dict]`

Performs a GET on `/message?limit=1&since={msg_id + 1}` — since Gotify returns messages sorted descending (newest first), `since=msg_id+1&limit=1` pinpoints exactly the target message. Verifies `msg.id == msg_id` before extracting `extras.gateway::files`. Returns `[]` on any error (404, timeout, non-JSON response, ID mismatch).

### `_enumerate_app_messages(app_id, token, auth_header, http_client) -> list[dict]`

Performs a GET on `/application/{id}/message`. Unwraps Gotify's nested response format (`{"messages": [...], "paging": {...}}`) by extracting the `messages` key. Returns `[]` on any error.

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
| `_DELETE_CONCURRENCY` | `cfg.delete_concurrency` | Max concurrent GET requests during file descriptor fetching. Shared module-level semaphore (`_DELETE_CONCURRENCY_SEM`) used by both `handle_message_delete` and `handle_app_delete`. |
| `_PENDING_TIMEOUT_SECONDS` | `cfg.pending_timeout_minutes * 60` | How long files stay in pending before `cleanup_loop` removes them |
