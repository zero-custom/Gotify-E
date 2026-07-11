# config.py — Configuration

## Architecture

`config.py` is organized in three parts:

| Part | What | How to use |
|---|---|---|
| **PART 1: EnvConfig** | Environment-variable config (7 fields) | Constructed once via `load_env_config()` at app startup. Module-level derived constants exported for direct import. |
| **PART 2: GatewayConfig** | Hard-coded tunables (image extensions, gateway dir name) | Imported by modules that need them: `from config import GatewayConfig` |
| **PART 3: Derived** | Computed from EnvConfig + GatewayConfig | `MAX_UPLOAD`, `UPLOAD_DIR` (Path), `GATEWAY_DIR`, `MARKER_PREFIX` — exported as module-level constants |

## EnvConfig Fields (PART 1)

| Env variable | Field | Default | Description |
|---|---|---|---|
| `GOTIFY_BACKEND` | `gotify_backend` | `http://localhost:8080` | Gotify backend base URL. Trailing slash stripped. |
| `PUBLIC_URL` | `public_url` | `""` | Public gateway URL for file URL rewriting. Auto-detected from request headers when empty. |
| `HOST` | `host` | `0.0.0.0` | Listen address. |
| `PORT` | `port` | `8765` | Listen port. |
| `UPLOAD_DIR` | `upload_dir` | `/data` | File upload storage path. Separated from `/app` for storage/compute decoupling. |
| `STORED_MARKER` | `stored_marker` | `{gateway}` | Placeholder prefix stored in message bodies. Replaced with `PUBLIC_URL` on read. |
| `MAX_UPLOAD_MB` | `max_upload_mb` | `50` | Per-file upload size limit in megabytes. |

## GatewayConfig (PART 2)

| Constant | Value | Description |
|---|---|---|
| `IMAGE_EXTS` | `{".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".ico"}` | File extensions treated as images (rendered as `![](...)` in messages). |
| `GATEWAY_DIR_NAME` | `"_gateway"` | Directory name for gateway static assets (i18n scripts). |

## Derived Constants (PART 3)

| Constant | Derivation | Example value |
|---|---|---|
| `BASE_DIR` | `Path(__file__).parent.resolve()` | `/app` |
| `cfg` | `load_env_config()` | `EnvConfig(...)` |
| `BACKEND` | `cfg.gotify_backend` | `http://localhost:8080` |
| `PUBLIC_URL` | `cfg.public_url` | `http://example.com:8765` |
| `HOST` | `cfg.host` | `0.0.0.0` |
| `PORT` | `cfg.port` | `8765` |
| `UPLOAD_DIR` | `Path(cfg.upload_dir)` | `Path("/data")` |
| `GATEWAY_DIR` | `BASE_DIR / GATEWAY_DIR_NAME` | `Path("/app/_gateway")` |
| `MAX_UPLOAD` | `cfg.max_upload_mb * 1024 * 1024` | `52428800` |
| `IMAGE_EXTS` | `GatewayConfig.IMAGE_EXTS` | `{".png", ".jpg", ...}` |
| `STORED_MARKER` | `cfg.stored_marker` | `{gateway}` |
| `MARKER_PREFIX` | `{stored_marker}/uploads/` | `{gateway}/uploads/` |

## Usage

```python
# Modules import only what they need
from config import BACKEND, UPLOAD_DIR, MAX_UPLOAD

# Or import the full config object for programmatic access
from config import cfg
# cfg.host, cfg.port, cfg.max_upload_mb, ...
```

## `__repr__` Security

`EnvConfig.__repr__` automatically masks any field whose name contains `password` or `secret` (case-insensitive) — displays `"******"` instead of the actual value when non-empty.
