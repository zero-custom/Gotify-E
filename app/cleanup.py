import asyncio
import logging
from pathlib import Path

from config import load_env_config, GatewayConfig
from pending_store import PendingStore

_cfg = load_env_config()
_UPLOAD_DIR = Path(GatewayConfig.UPLOAD_DIR)
_CLEANUP_INTERVAL_SECONDS = _cfg.cleanup_interval_minutes * 60

log = logging.getLogger("gotify-gateway.cleanup")


async def cleanup_loop():
    store = PendingStore(_UPLOAD_DIR, Path(GatewayConfig.PENDING_DIR), _cfg.pending_timeout_minutes * 60)
    while True:
        await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)
        store.clean_expired()
