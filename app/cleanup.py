import asyncio
import logging
from pathlib import Path

from config import load_env_config
from pending_store import PendingStore

_cfg = load_env_config()
_UPLOAD_DIR = Path(_cfg.upload_dir)
_CLEANUP_INTERVAL_SECONDS = _cfg.cleanup_interval_minutes * 60

log = logging.getLogger("gotify-gateway.cleanup")


async def cleanup_loop():
    store = PendingStore(_UPLOAD_DIR, Path(_cfg.pending_dir), _cfg.pending_timeout_minutes * 60)
    while True:
        await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)
        store.clean_expired()
