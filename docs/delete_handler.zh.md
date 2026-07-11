# delete_handler.py — DELETE 拦截与文件清理

拦截 `DELETE /message` 和 `DELETE /application/{id}/message`，在代理删除到 Gotify 后端之前将网关管理的文件移动到 pending 目录。删除确认后标记文件以供最终清理；失败时恢复文件。

## 数据流

```
DELETE /message/{id}
  │
  ├─ 从路径或 ?ids= 查询参数解析 ID 列表
  ├─ GET /message/{id}（复用认证信息）→ 读取 extras.gateway::files
  ├─ os.rename() 文件 → pending_dir/YYYYMMDD/
  ├─ 追加 manifest.jsonl 条目（status: "moved"）
  ├─ 代理 DELETE 到后端
  │
  ├─ 200/204 → 保留在 pending（cleanup_loop 负责过期清理）
  └─ 其他 → 将文件恢复至 upload_dir，删除 manifest 条目
```

## 函数

### `handle_message_delete(request, http_client, file_store=None, msg_id=None)`

单条/批量消息删除。消息 ID 来源：
- 路径参数 `msg_id`（如 `/message/123`）
- 查询参数 `?ids=[1,2,3]`

初步 GET 和后续 DELETE 使用相同的认证（`token` 查询参数或 `X-Gotify-Key` 请求头）。DELETE 代理前文件已移入 pending。DELETE 非 2xx 时，所有已移动的文件恢复，manifest 条目移除。

### `handle_app_delete(request, app_id, http_client, file_store=None)`

整个应用的批量删除（`DELETE /application/{id}/message`）。

1. 通过 `GET /application/{id}/message` 枚举所有消息
2. 并发获取每条消息的 `extras.gateway::files`（并发度由 `DELETE_CONCURRENCY` 控制）
3. 一次性将所有文件移入 pending
4. 代理 DELETE 请求
5. 失败时恢复所有文件并移除 manifest 条目

### `_collect_ids(request, msg_id) -> list[int]`

从请求参数中解析消息 ID。优先级：`msg_id` 参数 > `?ids=` JSON 数组 > 空列表。

### `_fetch_gateway_files(msg_id, token, auth_header, http_client) -> list[dict]`

GET `/message/{msg_id}` 并提取 `extras.gateway::files`。返回文件描述符的原始列表。任何错误（404、超时、非 JSON 响应）均返回 `[]`。

### `_enumerate_app_messages(app_id, token, auth_header, http_client) -> list[dict]`

GET `/application/{id}/message` 并返回响应体（消息列表）。任何错误均返回 `[]`。

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
| `_DELETE_CONCURRENCY` | `cfg.delete_concurrency` | 应用级批量删除时的最大并发 GET 数 |
| `_PENDING_TIMEOUT_SECONDS` | `cfg.pending_timeout_minutes * 60` | 文件在 pending 中保留的时间，超时后由 `cleanup_loop` 清理 |
