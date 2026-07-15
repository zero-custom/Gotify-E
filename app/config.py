import os
import dataclasses
from dataclasses import dataclass


_SENSITIVE_REPR_FIELDS = {"gotify_backend", "public_host"}


@dataclass(frozen=True)
class EnvConfig:
    gotify_backend: str = "http://localhost:8080"
    host: str = "0.0.0.0"
    port: int = 8765
    public_host: str = ""
    max_upload_mb: int = 50
    max_files_per_request: int = 5
    pending_timeout_minutes: int = 120
    cleanup_interval_minutes: int = 30
    delete_concurrency: int = 10

    def __repr__(self) -> str:
        cls = self.__class__.__name__
        fields = []
        for f in dataclasses.fields(self):
            val = getattr(self, f.name)
            if f.name in _SENSITIVE_REPR_FIELDS:
                val = "******" if val else ""
            fields.append(f"{f.name}={val!r}")
        return f"{cls}({', '.join(fields)})"


def load_env_config() -> EnvConfig:
    return EnvConfig(
        gotify_backend=os.environ.get("GOTIFY_BACKEND", "http://localhost:8080").rstrip("/"),
        public_host=os.environ.get("PUBLIC_HOST", ""),
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8765")),
        max_upload_mb=int(os.environ.get("MAX_UPLOAD_MB", "50")),
        max_files_per_request=int(os.environ.get("MAX_FILES_PER_REQUEST", "5")),
        pending_timeout_minutes=int(os.environ.get("PENDING_TIMEOUT_MINUTES", "120")),
        cleanup_interval_minutes=int(os.environ.get("CLEANUP_INTERVAL_MINUTES", "30")),
        delete_concurrency=int(os.environ.get("DELETE_CONCURRENCY", "10")),
    )


class GatewayConfig:
    UPLOAD_DIR = "/data/upload"
    STAGING_DIR = "/data/staging"
    PENDING_DIR = "/data/pending"
    STORED_MARKER = "{gateway}"

    MAX_FILENAME_BYTES = 200
    IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".ico"}
    DANGEROUS_EXTS = {
        ".html", ".htm", ".js", ".php", ".php3", ".php4", ".php5",
        ".phtml", ".asp", ".aspx", ".cgi", ".pl", ".py", ".rb",
        ".jsp", ".war", ".shtml", ".shtm",
    }

    GATEWAY_DIR_NAME = "_gateway"
    VERSION = "1.1.0"
