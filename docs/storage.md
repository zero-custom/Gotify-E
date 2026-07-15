# storage.py — File Storage Engine

Implements file persistence with security validation (MIME check, filename sanitization) and Markdown link generation.

## Classes

### `StoredFile`

Data class returned by `FileStore.save()`.

| Attribute | Type | Description |
|---|---|---|
| `marker_url` | `str` | The marker-prefixed URL, e.g. `{gateway}/uploads/ab/cd/uuid_photo.png` |
| `markdown` | `str` | Ready-to-use Markdown: `![]({marker_url})` for images, `[name]({marker_url})` otherwise |
| `uuid` | `str` | UUID hex (used as the file identifier) |
| `path` | `str` | Relative path inside upload dir: `{subdir}/{uuid}_{safe_stem}{ext}` |
| `size` | `int` | File size in bytes |
| `original_name` | `str` | Original filename as provided by the client |

### `FileStore`

Core storage engine. Instantiated once at module level in `app.py`:

```python
file_store = FileStore(UPLOAD_DIR, MARKER_PREFIX, IMAGE_EXTS, STAGING_DIR)
```

#### `save(filename: str, body: bytes) -> StoredFile`

Persists a file and returns its StoredFile descriptor. The save pipeline:

```
save(filename, body)
  │
  ├─ 1. Extract stem + extension from filename
  │
  ├─ 2. Validate extension: /^\.[a-zA-Z0-9]{1,10}$/
  │     └── Fail → fallback to ".bin"
  │
  ├─ 3. MIME check: magic.from_buffer(body, mime=True)
  │     └── If ext in image_exts AND mime doesn't start with "image/"
  │         → rename to ".bin" (file is NOT rejected, just saved as binary)
  │     └── On detection failure (magic exception)
  │         → rename to ".bin" (graceful degradation)
  │
  ├─ 4a. Sanitize stem: unicodedata.normalize("NFKC", stem)
  │      → re.sub(r"[^\w.\-]", "_", safe_stem)
  │
  ├─ 4b. Truncate to MAX_FILENAME_BYTES (200 bytes):
  │      Encode as UTF-8, truncate at byte boundary without breaking
  │      multi-byte chars, re-decode. Preserves extension.
  │
  ├─ 5. Generate path: UUID hex → subdir "{hex[:2]}/{hex[2:4]}"
  │     → filename "{uuid}_{safe_stem}{ext}"
  │
  ├─ 6. Write to staging dir: staging_dir / subdir / filename
  │
  └─ 7. Return StoredFile:
          marker_url = "{marker_prefix}{subdir}/{filename}"
          markdown   = markdown_escape("[name](...)" or "![](...)")
```

**Markdown escape**: The generated `markdown` field escapes characters `\`, `[`, `]`, `(`, `)` with leading backslash. This prevents Markdown renderers from interpreting file URLs as formatting syntax. The `marker_url` is never escaped — only the Markdown representation.

#### `confirm(stored: StoredFile) -> None`

Moves a single confirmed file from the staging directory to the permanent `upload_dir`. Called after the Gotify backend returns a 2xx response.

```python
# staging/<uuid[:2]>/<uuid[2:4]>/<uuid>_photo.png
#   → upload/<uuid[:2]>/<uuid[2:4]>/<uuid>_photo.png
```

Uses `shutil.move` for cross-filesystem safety. Silently skips if the staging file no longer exists.

#### `cancel(stored: StoredFile) -> None`

Deletes a single staging file and its metadata. Called after the Gotify backend returns a non-2xx response.

## Security

| Check | When | Action |
|---|---|---|
| Extension format | Always | Rejects non-alphanumeric extensions longer than 10 chars, falls back to `.bin` |
| MIME mismatch | Extension in `IMAGE_EXTS` | Re‑names to `.bin` and saves (does NOT reject — data is never lost) |
| MIME detection failure | Always | Re‑names to `.bin` and saves (graceful degradation) |
| Filename normalization | Always | NFKC normalization + replace non-`\w.\-` chars with `_` |
| Filename truncation | Always | UTF-8 safe truncation to 200 bytes |
| Markdown escape | Always | Backslash-escape `\` `[` `]` `(` `)` in the `markdown` field |

## Storage Layout

```
/data/
├── upload/
│   ├── ab/cd/                  ← UUID-subdir (permanent storage)
│   │   └── uuid_photo.png
│   └── ...
├── staging/                    ← Temp directory for in-flight uploads
│   ├── ab/cd/                  ← Mirrors the same UUID-subdir layout
│   │   └── uuid_photo.png
│   └── ...
└── pending/                    ← Pending DELETE directory (see pending_store.md)
    ├── manifest.jsonl
    └── ...
```

**Upload/staging flow**: `save()` writes to `staging_dir/{uuid[:2]}/{uuid[2:4]}/{uuid}_{stem}{ext}`. After the Gotify backend confirms the message POST (2xx), `confirm()` moves the file to `upload_dir/{uuid[:2]}/{uuid[2:4]}/`. On failure, `cancel()` removes the staging file.

Path structure for all directories: `{BASE_DIR}/{uuid[:2]}/{uuid[2:4]}/{uuid}_{sanitized_stem}{ext}`.

The two-level subdirectory (first 2 + next 2 hex chars) distributes files across up to 256×256 = 65,536 directories, avoiding any single directory exceeding filesystem limits.
