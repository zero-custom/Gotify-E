# upload.py — Multipart 上传拦截

拦截 `POST /message` 处理文件上传。非 multipart 请求透明透传至 Gotify 后端。

## 入口函数

### `handle_message_post(request, file_store, http_client) -> Response`

`app.py` 在 `POST /message` 路由上调用的唯一公开函数。

```
request
  │
  ├─ Content-Type 是否为 multipart/form-data？
  │     └── 否 → proxy_to_backend(request, 直接透传)
  │
  ├─ Content-Encoding 已设置且 ≠ "identity"？
  │     └── 是 → 返回 415（不支持压缩上传）
  │
  ├─ 解析表单数据（max_part_size = MAX_UPLOAD）
  │
  ├─ 提取字段：message, title, priority
  │
  ├─ 通过 form.getlist("file") 获取文件字段
  │     └── _process_files(file_fields, file_store)
  │           ├── 每个 UploadFile → FileStore.save()
  │           └── 每个 str/bytes → 以 "uploaded_file" 调用 FileStore.save()
  │
  ├─ 构建 JSON 负载，含 extras.client::display.contentType = "text/markdown"
  │     ├── 若有文件保存 → extras.gateway::files[] 含 uuid, path, name, size
  │     └── 若消息非空 → 在 "---" 后追加注入的 Markdown 链接
  │
  └─ proxy_to_backend(POST, JSON body)
```

## 响应修改

| 条件 | 行为 |
|---|---|
| 非 `multipart/form-data` | 透明代理，无修改 |
| `Content-Encoding` 已设置（非 identity） | 立即返回 415 错误 |
| Multipart + 有文件 | 文件保存到磁盘，消息追加 Markdown 链接，以紧凑 JSON 代理 |
| Multipart + 无文件（部分客户端发送空文件列表） | 原始表单字段以 JSON 转发，不注入 |

## 文件处理

### `_process_files(file_fields, file_store) -> FileProcessingResult`

遍历表单字段，按类型分别处理：

| 类型 | 处理方式 |
|---|---|
| `UploadFile`（有 `.filename`、`.read()`） | 通过 `FileStore.save(filename, content)` 保存。`FileRejectedError` 记录日志并跳过（尽力而为）。 |
| `str` / `bytes`（原始表单字段，不常见） | 以 `"uploaded_file"` 通过 `FileStore.save()` 保存。主要用于向后兼容。 |

**错误策略**：尽力而为。单个文件被拒不影响整个上传。未预期的错误同样记录日志并跳过。

## 负载格式

```python
{
    "message": str,          # 原始消息 + 追加的 Markdown 文件链接
    "title": str,
    "priority": int,         # 默认为 5
    "extras": {
        "client::display": {"contentType": "text/markdown"},
        "gateway::files": [               # 仅在有文件保存时出现
            {"uuid": str, "path": str, "name": str, "size": int}
        ],
    },
}
```

## 配置

| 常量 | 来源 | 说明 |
|---|---|---|
| `_MAX_UPLOAD` | `cfg.max_upload_mb * 1024 * 1024` | `request.form()` 的最大 form part 大小（字节）。 |
