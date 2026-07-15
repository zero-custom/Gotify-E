# config.py — Configuration

## Architecture

`config.py` is organized in three parts:

| Part | What | How to use |
|---|---|---|
| **EnvConfig** | Environment-variable config (9 fields) | Constructed via `load_env_config()` at app startup. |
| **GatewayConfig** | Hard-coded design constants (storage paths, file safety, version) | Imported directly: `from config import GatewayConfig` |
| **`load_env_config()`** | Factory function that reads env vars and returns `EnvConfig` | Called once at startup in `app.py` |

## EnvConfig Fields

| Env variable | Field | Default | Description |
|---|---|---|---|
| `GOTIFY_BACKEND` | `gotify_backend` | `http://localhost:8080` | Gotify backend base URL. Trailing slash stripped. |
| `PUBLIC_HOST` | `public_host` | `""` | Public gateway domain whitelist (comma-separated) for file URL rewriting. Empty = auto-detect from request headers. |
| `HOST` | `host` | `0.0.0.0` | Listen address. |
| `PORT` | `port` | `8765` | Listen port. |
| `MAX_UPLOAD_MB` | `max_upload_mb` | `50` | Per-file upload size limit in megabytes. |
| `MAX_FILES_PER_REQUEST` | `max_files_per_request` | `5` | Maximum number of files allowed per upload request. |
| `PENDING_TIMEOUT_MINUTES` | `pending_timeout_minutes` | `120` | How long files stay in pending before cleanup removes them. |
| `CLEANUP_INTERVAL_MINUTES` | `cleanup_interval_minutes` | `30` | Interval for periodic cleanup sweep. |
| `DELETE_CONCURRENCY` | `delete_concurrency` | `10` | Max concurrent GET requests during app-level bulk delete. |

## GatewayConfig

| Constant | Value | Description |
|---|---|---|
| `UPLOAD_DIR` | `"/data/upload"` | Permanent file storage directory. The only directory users should mount as a volume. |
| `STAGING_DIR` | `"/data/staging"` | Temporary upload staging directory. Derived from storage design — files saved here first, moved to upload_dir after Gotify confirms. |
| `PENDING_DIR` | `"/data/pending"` | Staging directory for files pending DELETE confirmation. |
| `STORED_MARKER` | `"{gateway}"` | Placeholder prefix stored in message bodies. Replaced with gateway URL on read. |
| `MAX_FILENAME_BYTES` | `200` | Maximum filename byte length (truncated to fit, extension preserved). |
| `IMAGE_EXTS` | `{".jpg", ".jpeg", ".png", ".gif", ...}` | File extensions treated as images (rendered as `![](...)` in messages). |
| `DANGEROUS_EXTS` | `{".html", ".htm", ".js", ...}` | Extensions that force `Content-Disposition: attachment` to prevent in-browser rendering XSS. |
| `GATEWAY_DIR_NAME` | `"_gateway"` | Directory name for gateway static assets (i18n scripts). |

## `__repr__` Security

`EnvConfig.__repr__` masks sensitive fields (`gotify_backend`, `public_host`) with `"******"` to prevent credential leakage in logs.

## Module-level vs Class-level

Prior to v1.1.0, storage paths and VERSION were module-level constants or part of `EnvConfig`. They were moved into `GatewayConfig` to clarify the boundary between deployment-configurable parameters and architectural design decisions.
