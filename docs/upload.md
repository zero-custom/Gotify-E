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
  ├─ File count check: form.getlist("file") length > MAX_FILES_PER_REQUEST?
  │     └── Yes → return 413 with sanitized error
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
  ├─ Proxy to backend (POST, JSON body)
  │
  ├─ On 2xx response from backend:
  │     └── FileStore.confirm() → move files from staging to upload_dir
  │
  └─ On non-2xx response or error:
        └── FileStore.cancel() → delete staging files
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
|---|---|---|
| `UploadFile` (has `.filename`, `.read()`) | Save via `FileStore.save(filename, content)`. MIME mismatches are saved as `.bin` (best-effort, files never lost). |
| `str` / `bytes` (raw form fields, uncommon) | Save as `"uploaded_file"` with `FileStore.save()`. Primarily for backward compatibility. |

**Error strategy**: Best-effort. A single problematic file does not abort the entire upload. Unexpected errors are logged and the file is skipped.

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

## Error Handling

| Condition | HTTP Status | Description |
|---|---|---|---|
| `ContentEncodingError` | 415 | Compressed upload not supported |
| Too many files | 413 | `{"error": "Too many files (max: 5)", "code": 413}` |
| MIME mismatch | Saved as `.bin` | File renamed to `.bin`, never lost |
| MIME detection failure | Saved as `.bin` | Graceful degradation |
| Any other | 500 | Generic error boundary |

**Error sanitization**: Filenames in error messages have `[` and `]` stripped to prevent log injection in JSON error bodies.

## Configuration

| Constant | Source | Description |
|---|---|---|
| `_MAX_UPLOAD` | `cfg.max_upload_mb * 1024 * 1024` | Maximum form part size (bytes) for `request.form()`. |
| `_MAX_FILES` | `cfg.max_files_per_request` | Maximum number of files allowed per request. |
