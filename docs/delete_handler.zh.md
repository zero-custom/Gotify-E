# delete_handler.py — DELETE 拦截与文件清理

拦截 `DELETE /message` 和 `DELETE /application/{id}/message`，在代理删除到 Gotify 后端之前将网关管理的文件移动到 pending 目录。删除确认后标记文件以供最终清理；失败时恢复文件。

## 数据流

### `DELETE /message`（无 ids — "全部删除"）

```
DELETE /message
  │
  ├─ _enumerate_all_message_files() — 分页扫描全部消息
  │     ├─ _iter_messages(paginate=True) 第1页: GET /message?limit=100
  │     ├─ _iter_messages(paginate=True) 第N页: GET /message?limit=100&since=N
  │     └─ 从每条消息收集 extras.gateway::files
  ├─ 无消息 → 直接透传
  ├─ PendingStore.safe_delete(全部ID, files_by_id, delete_coro)
  └─ 返回响应
```

### `DELETE /message/{msg_id}` / `DELETE /message?ids=[...]`

```
DELETE /message{/id}?ids=[...]
  │
  ├─ 从路径或 ?ids= 查询参数解析 ID 列表
  ├─ 并发获取每个 ID 的 extras.gateway::files
  │   （吞吐量由共享的 _DELETE_CONCURRENCY_SEM 控制）
  ├─ 收集 files_by_id 映射
  ├─ PendingStore.safe_delete(msg_ids, files_by_id, delete_coro)
  └─ 返回响应
```

### `DELETE /application/{id}/message`

```
DELETE /application/{id}/message
  │
  ├─ _enumerate_app_messages() — GET /application/{id}/message
  ├─ 并发获取每条消息的 extras.gateway::files
  │   （吞吐量由共享的 _DELETE_CONCURRENCY_SEM 控制）
  ├─ PendingStore.safe_delete(msg_ids, files_by_id, delete_coro)
  └─ 返回响应
```

## 函数

### `handle_message_delete(request, http_client, file_store=None, msg_id=None)`

单条/批量/全部消息删除。行为取决于消息 ID 是否存在：

| 有 IDs | 行为 |
|---|---|
| 无（`ids=[]`） | 调用 `_enumerate_all_message_files()` 分页遍历所有消息，收集 `gateway::files`，然后 `safe_delete()` |
| 有（路径参数或 `?ids=`） | 并发获取每个 ID 的文件描述符，然后 `safe_delete()` |

并发获取的吞吐量由共享的 `DELETE_CONCURRENCY` 信号量控制（与 `handle_app_delete` 共用同一池）。

### `handle_app_delete(request, app_id, http_client, file_store=None)`

整个应用的批量删除（`DELETE /application/{id}/message`）。

1. 调用 `_enumerate_app_messages()`（通过 `_iter_messages(paginate=False)`）
2. 并发获取每条消息的 `extras.gateway::files`（吞吐量由共享的 `DELETE_CONCURRENCY` 信号量控制）
3. 委托给 `PendingStore.safe_delete()`

### `_collect_ids(request, msg_id) -> list[int]`

从请求参数中解析消息 ID。优先级：`msg_id` 参数 > `?ids=` JSON 数组 > 空列表。

### `_fetch_gateway_files(msg_id, token, auth_header, http_client) -> list[dict]`

GET `/message?limit=1&since={msg_id + 1}` — Gotify 按降序返回消息（最新在前），`since=msg_id+1&limit=1` 精确定位目标消息。验证 `msg.id == msg_id` 后提取 `extras.gateway::files`。任何错误（404、超时、非 JSON 响应、ID 不匹配）均返回 `[]`。

### `_iter_messages(url, token, auth_headers, http_client, *, paginate=False)`

从后端 GET 响应的消息列表中逐条 yield 的异步生成器。两种模式：

| `paginate` | 行为 | 用途 |
|---|---|---|
| `False` | 单次请求，一次性 yield 所有消息 | `_enumerate_app_messages()` |
| `True` | 分页遍历：首次请求不带 `since`，后续使用响应中的 `paging.since`。当 `since` 为 None 或结果数小于 limit 时停止。 | `_enumerate_all_message_files()` |

认证通过 `?token=` 查询参数（token 存在时）和 `auth_headers` 字典传递。

### `_enumerate_all_message_files(token, auth_headers, http_client) -> tuple[list[int], dict[int, list]]`

使用 `_iter_messages(paginate=True)` 分页遍历后端所有消息。收集每个消息 ID 及其 `extras.gateway::files`。返回 `(all_ids, files_by_id)`。

### `_enumerate_app_messages(app_id, token, auth_headers, http_client) -> list[dict]`

使用 `_iter_messages(paginate=False)` 列出指定应用的所有消息。错误时返回 `[]`。

### `recover_on_startup(http_client)`

在应用 lifespan 启动时调用。扫描 manifest 中 `status: "moved"` 的条目，检查对应的 Gotify 消息是否存在：

| GET 结果 | 处理 |
|---|---|
| 200（消息存在） | 将文件恢复至 `upload_dir`，移除 manifest 条目 |
| 404（消息已删除） | 将 manifest 条目标记为 `deleted`（cleanup_loop 最终将 unlink 文件） |
| 错误（网络） | 保留在 pending，记录警告 |

## 依赖

| 模块 | 用途 |
|---|---|
| `pending_store.PendingStore` | 文件移动、manifest CRUD、恢复、`safe_delete` |
| `proxy.HttpClient` | GET 消息文件列表 |
| `proxy.proxy_to_backend` | 将 DELETE 作为 `delete_coro` 传给 `safe_delete` |

## 配置

| 常量 | 来源 | 说明 |
|---|---|---|
| `_DELETE_CONCURRENCY` | `cfg.delete_concurrency` | 获取文件描述符时的最大并发 GET 数。模块级共享信号量，`handle_message_delete` 和 `handle_app_delete` 共用。 |
| `_LIST_LIMIT` | `100` | `_iter_messages` 分页遍历的每页大小。 |
| `_PENDING_TIMEOUT_SECONDS` | `cfg.pending_timeout_minutes * 60` | 文件在 pending 中保留的时间，超时后由 `cleanup_loop` 清理 |
