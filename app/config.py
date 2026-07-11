import os
import dataclasses
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EnvConfig:
    # Backend
    gotify_backend: str = "http://localhost:8080"
    public_url: str = ""

    # Server
    host: str = "0.0.0.0"
    port: int = 8765

    # Storage
    upload_dir: str = "/data"
    stored_marker: str = "{gateway}"

    # Limits
    max_upload_mb: int = 50

    def __repr__(self) -> str:
        cls = self.__class__.__name__
        fields = []
        for f in dataclasses.fields(self):
            val = getattr(self, f.name)
            if "password" in f.name.lower() or "secret" in f.name.lower():
                val = "******" if val else ""
            fields.append(f"{f.name}={val!r}")
        return f"{cls}({', '.join(fields)})"


def load_env_config() -> EnvConfig:
    return EnvConfig(
        gotify_backend=os.environ.get("GOTIFY_BACKEND", "http://localhost:8080").rstrip("/"),
        public_url=os.environ.get("PUBLIC_URL", "").rstrip("/"),
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8765")),
        upload_dir=os.environ.get("UPLOAD_DIR", "/data"),
        stored_marker=os.environ.get("STORED_MARKER", "{gateway}"),
        max_upload_mb=int(os.environ.get("MAX_UPLOAD_MB", "50")),
    )


# ── Hardcoded constants ──────────────────────────────

class GatewayConfig:
    IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".ico"}
    GATEWAY_DIR_NAME = "_gateway"


# ── Derived (computed once at import time) ────────────

BASE_DIR = Path(__file__).parent.resolve()
cfg = load_env_config()

BACKEND = cfg.gotify_backend
PUBLIC_URL = cfg.public_url
HOST = cfg.host
PORT = cfg.port

UPLOAD_DIR = Path(cfg.upload_dir)
GATEWAY_DIR = BASE_DIR / GatewayConfig.GATEWAY_DIR_NAME
MAX_UPLOAD = cfg.max_upload_mb * 1024 * 1024
IMAGE_EXTS = GatewayConfig.IMAGE_EXTS

STORED_MARKER = cfg.stored_marker
MARKER_PREFIX = f"{STORED_MARKER.rstrip('/')}/uploads/"
