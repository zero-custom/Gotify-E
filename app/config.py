import os
import dataclasses
from dataclasses import dataclass


@dataclass(frozen=True)
class EnvConfig:
    # Backend
    gotify_backend: str = "http://localhost:8080"
    """Gotify 后端地址（默认 http://localhost:8080）"""
    public_url: str = ""
    """网关公网地址，用于替换消息中的文件 URL。留空自动从请求推断"""

    # Server
    host: str = "0.0.0.0"
    """监听地址"""
    port: int = 8765
    """监听端口"""

    # Storage
    upload_dir: str = "/data/upload"
    """上传文件存储目录"""
    pending_dir: str = "/data/pend"
    """待删除文件暂存目录（与 upload_dir 相互独立）"""
    stored_marker: str = "{gateway}"
    """消息正文中的标记字符串，用于标识文件 URL 所在位置"""

    # Limits
    max_upload_mb: int = 50
    """单文件上传大小上限（MB）"""
    pending_timeout_minutes: int = 120
    """暂存文件超时时间（分钟），超时后自动删除"""
    cleanup_interval_minutes: int = 30
    """暂存目录清理间隔（分钟）"""
    delete_concurrency: int = 10
    """应用删除时并发请求数"""

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
        upload_dir=os.environ.get("UPLOAD_DIR", "/data/upload"),
        pending_dir=os.environ.get("PENDING_DIR", "/data/pend"),
        stored_marker=os.environ.get("STORED_MARKER", "{gateway}"),
        max_upload_mb=int(os.environ.get("MAX_UPLOAD_MB", "50")),
        pending_timeout_minutes=int(os.environ.get("PENDING_TIMEOUT_MINUTES", "120")),
        cleanup_interval_minutes=int(os.environ.get("CLEANUP_INTERVAL_MINUTES", "30")),
        delete_concurrency=int(os.environ.get("DELETE_CONCURRENCY", "10")),
    )


# ── Version ──────────────────────────────────────────

VERSION = "1.0.0"


# ── Hardcoded constants ──────────────────────────────

class GatewayConfig:
    IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".ico"}
    GATEWAY_DIR_NAME = "_gateway"


