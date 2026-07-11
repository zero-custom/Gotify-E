# storage.py — File Storage Engine

Implements file persistence with security validation (MIME check, filename sanitization, extension whitelist) and Markdown link generation.

## Classes

### `StoredFile`

Data class returned by `FileStore.save()`.

| Attribute | Type | Description |
|---|---|---|
| `marker_url` | `str` | The marker-prefixed URL, e.g. `{gateway}/uploads/ab/cd/uuid_photo.png` |
| `markdown` | `str` | Ready-to-use Markdown: `![]({marker_url})` for images, `[filename]({marker_url})` otherwise |

### `FileRejectedError(Exception)`

Raised when a file claims an image extension but its MIME type is not `image/*`. Contains a descriptive message with the detected MIME type.

### `FileStore`

Core storage engine. Instantiated once at module level in `app.py`:

```python
file_store = FileStore(UPLOAD_DIR, MARKER_PREFIX, IMAGE_EXTS)
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
  │         → raise FileRejectedError
  │
  ├─ 4. Sanitize stem: unicodedata.normalize("NFKC", stem)
  │     → re.sub(r"[^\w.\-]", "_", safe_stem)
  │
  ├─ 5. Generate path: UUID hex → subdir "{hex[:2]}/{hex[2:4]}"
  │     → filename "{uuid}_{safe_stem}{ext}"
  │
  ├─ 6. Write to disk: upload_dir / subdir / filename
  │
  └─ 7. Return StoredFile:
          marker_url = "{marker_prefix}{subdir}/{filename}"
          markdown   = "![](...)" if image else "[name](...)"
```

## Security

| Check | When | Action |
|---|---|---|
| Extension format | Always | Rejects non-alphanumeric extensions longer than 10 chars, falls back to `.bin` |
| MIME mismatch | Extension in `IMAGE_EXTS` | Rejects if `magic.from_buffer()` doesn't return `image/*` |
| Filename normalization | Always | NFKC normalization + replace non-`\w.\-` chars with `_` |

## Storage Layout

```
/data/
├── ab/
│   └── cd/
│       └── a1b2c3d4e5f6_photo.png
├── ef/
│   └── 01/
│       └── 7890abcdef_document.pdf
└── ...
```

Path structure: `{UPLOAD_DIR}/{uuid[:2]}/{uuid[2:4]}/{uuid}_{sanitized_stem}{ext}`.

The two-level subdirectory (first 2 + next 2 hex chars) distributes files across up to 256×256 = 65,536 directories, avoiding any single directory exceeding filesystem limits.
