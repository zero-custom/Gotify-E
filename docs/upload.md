# upload.py — Multipart Upload Interception

Intercepts `POST /message` to handle file uploads. Non-multipart requests pass through transparently to the Gotify backend.

## Entry Point

### `handle_message_post(request, file_store, http_client) -> Response`

The sole public function, called from `app.py` on `POST /message`. Acts as an error boundary — delegates to `_process_upload` and maps exceptions to standard responses:

| Exception | HTTP Status |
|---|---|
| `ContentEncodingError` | 415 |
| Any other `Exception` | 500 |


### `_process_upload(request, file_store, http_client) -> Response`

Business logic extracted from `handle_message_post`. Raises `ContentEncodingError` instead of constructing an HTTP response directly.

```
request
request
  │
  ├─ Content-Type: multipart/form-data?
  │     └── No → proxy_to_backend(request, passthrough)
  │
  ├─ Content-Encoding set and ≠ "identity"?
  │     └── Yes → return 415 (compressed upload not supported)
  │
  ├─ Parse form data (max_part_size = MAX_UPLOAD)
  │
  ├─ Extract fields: message, title, priority
  │
  ├─ Get file fields via form.getlist("file")
  │     └── _process_files(file_fields, file_store)
  │           ├── For each UploadFile → FileStore.save()
  │           └── For each str/bytes → FileStore.save() as "uploaded_file"
  │
  ├─ Build JSON payload with extras.client::display.contentType = "text/markdown"
  │     ├── If files saved → extras.gateway::files[] with uuid, path, name, size
  │     └── If message non-empty → append injected Markdown links after "---"
  │
  └─ proxy_to_backend(POST, JSON body)
```

## Response Modification

| Condition | Modification |
|---|---|
| Not `multipart/form-data` | Transparent proxy, no changes |
| `Content-Encoding` set (not identity) | 415 error immediately |
| Multipart + files | Files saved to disk, Markdown links appended to message, compact JSON proxied |
| Multipart + no files (some clients send empty file list) | Original form fields forwarded as JSON, no injection |

## File Processing

### `_process_files(file_fields, file_store) -> FileProcessingResult`

Iterates over form fields and processes each as either:

| Type | Treatment |
|---|---|
| `UploadFile` (has `.filename`, `.read()`) | Save via `FileStore.save(filename, content)`. `FileRejectedError` logged and skipped (best-effort). |
| `str` / `bytes` (raw form fields, uncommon) | Save as `"uploaded_file"` with `FileStore.save()`. Primarily for backward compatibility. |

**Error strategy**: Best-effort. A single rejected file does not abort the entire upload. Unexpected errors are logged and also skipped.

## Payload Shape

```python
{
    "message": str,          # original message + appended Markdown file links
    "title": str,
    "priority": int,         # defaults to 5
    "extras": {
        "client::display": {"contentType": "text/markdown"},
        "gateway::files": [               # only when files were stored
            {"uuid": str, "path": str, "name": str, "size": int}
        ],
    },
}
```

## Configuration

| Constant | Source | Description |
|---|---|---|
| `_MAX_UPLOAD` | `cfg.max_upload_mb * 1024 * 1024` | Maximum form part size (bytes) for `request.form()`. |
