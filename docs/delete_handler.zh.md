# delete_handler.py — DELETE 拦截与文件清理

拦截 `DELETE /message` 和 `DELETE /application/{id}/message`，在代理删除到 Gotify 后端之前将网关管理的文件移动到 pending 目录。删除确认后标记文件以供最终清理；失败时恢复文件。

## 数据流

```
DELETE /message{/id}
  │
  ├─ 从路径或 ?ids= 查询参数解析 ID 列表
  ├─ 并发获取每个 ID 的 extras.gateway::files
  │   （吞吐量由共享的 _DELETE_CONCURRENCY_SEM 控制）
  ├─ 收集 files_by_id 映射
  ├─ 将文件移入 pending → 追加 manifest 条目
  ├─ 代理 DELETE 到后端
  │
  ├─ 200/204 → 保留在 pending（cleanup_loop 负责过期清理）
  └─ 其他 → 恢复文件至 upload_dir，删除 manifest 条目
```

## 函数

### `handle_message_delete(request, http_client, file_store=None, msg_id=None)`

单条/批量消息删除。消息 ID 来源：
- 路径参数 `msg_id`（如 `/message/123`）
- 查询参数 `?ids=[1,2,3]`

并发获取每个 ID 的文件描述符（吞吐量由共享的 `DELETE_CONCURRENCY` 信号量控制，与 `handle_app_delete` 共用同一对象池），然后委托给 `PendingStore.safe_delete()`。

### `handle_app_delete(request, app_id, http_client, file_store=None)`

整个应用的批量删除（`DELETE /application/{id}/message`）。

1. 通过 `GET /application/{id}/message` 枚举所有消息
2. 并发获取每条消息的 `extras.gateway::files`（吞吐量由共享的 `DELETE_CONCURRENCY` 信号量控制，与 `handle_message_delete` 共用同一对象池）
3. 一次性将所有文件移入 pending
4. 代理 DELETE 请求
5. 失败时恢复所有文件并移除 manifest 条目

### `_collect_ids(request, msg_id) -> list[int]`

从请求参数中解析消息 ID。优先级：`msg_id` 参数 > `?ids=` JSON 数组 > 空列表。

### `_fetch_gateway_files(msg_id, token, auth_header, http_client) -> list[dict]`

GET `/message?limit=1&since={msg_id + 1}` — Gotify 按降序返回消息（最新在前），`since=msg_id+1&limit=1` 精确定位目标消息。验证 `msg.id == msg_id` 后提取 `extras.gateway::files`。任何错误（404、超时、非 JSON 响应、ID 不匹配）均返回 `[]`。

### `_enumerate_app_messages(app_id, token, auth_header, http_client) -> list[dict]`

GET `/application/{id}/message`。解包 Gotify 的嵌套响应格式（`{"messages": [...], "paging": {...}}`），提取 `messages` 键。任何错误均返回 `[]`。

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
| `pending_store.PendingStore` | 文件移动、manifest CRUD、恢复 |
| `proxy.HttpClient` | GET 消息文件列表、代理 DELETE |
| `proxy.proxy_to_backend` | 文件拦截后转发 DELETE |

## 配置

| 常量 | 来源 | 说明 |
|---|---|---|
| `_DELETE_CONCURRENCY` | `cfg.delete_concurrency` | 获取文件描述符时的最大并发 GET 数。模块级共享信号量（`_DELETE_CONCURRENCY_SEM`），`handle_message_delete` 和 `handle_app_delete` 共用。 |
| `_PENDING_TIMEOUT_SECONDS` | `cfg.pending_timeout_minutes * 60` | 文件在 pending 中保留的时间，超时后由 `cleanup_loop` 清理 |
