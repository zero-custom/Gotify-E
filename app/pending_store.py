import asyncio
import json
import logging
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("gotify-gateway.pending_store")

_PATH_PATTERN = re.compile(r"^[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{32}_.+$")


class PendingStore:
    def __init__(self, upload_dir: Path, pending_dir: Path, pending_timeout_seconds: int):
        self._upload_dir = upload_dir
        self._pending_dir = pending_dir
        self._pending_timeout_seconds = pending_timeout_seconds

    async def move_to_pending(self, msg_id: int, files: list) -> list[dict]:
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        moved = []
        upload_root = str(self._upload_dir.resolve())
        for f in files:
            orig = f.get("path", "")
            if not orig:
                continue
            if not _PATH_PATTERN.match(orig):
                log.warning("invalid path format in move_to_pending: %s", orig)
                continue
            src = (self._upload_dir / orig).resolve()
            if not str(src).startswith(upload_root):
                log.warning("path traversal blocked in move_to_pending: %s", orig)
                continue
            if not src.exists():
                log.warning("file not found: %s", src)
                continue
            pending_sub = self._pending_dir / date_str
            pending_sub.mkdir(parents=True, exist_ok=True)
            flat = orig.replace("/", "_")
            dst = pending_sub / flat
            try:
                await asyncio.to_thread(shutil.move, str(src), str(dst))
                moved.append({"msg_id": msg_id, "orig_path": orig, "pending_path": f"{date_str}/{flat}"})
            except OSError as e:
                log.error("move failed: %s -> %s: %s", src, dst, e)
        return moved

    async def restore(self, entries: list[dict]) -> None:
        upload_root = str(self._upload_dir.resolve())
        for item in entries:
            src = self._pending_dir / item["pending_path"]
            dst = (self._upload_dir / item["orig_path"]).resolve()
            if not str(dst).startswith(upload_root):
                log.warning("path traversal blocked in restore: %s", item.get("orig_path"))
                continue
            if not src.exists():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                await asyncio.to_thread(shutil.move, str(src), str(dst))
            except OSError as e:
                log.error("restore failed: %s -> %s: %s", src, dst, e)

    def append_manifest(self, msg_id: int, moved: list[dict]) -> None:
        manifest_path = self._pending_dir / "manifest.jsonl"
        self._pending_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc).isoformat()
        with open(manifest_path, "a") as fp:
            for item in moved:
                entry = json.dumps({
                    "msg_id": item["msg_id"], "orig_path": item["orig_path"],
                    "pending_path": item["pending_path"], "time": now, "status": "moved",
                })
                fp.write(entry + "\n")

    def read_manifest(self) -> list[dict]:
        manifest_path = self._pending_dir / "manifest.jsonl"
        if not manifest_path.exists():
            return []
        entries = []
        with open(manifest_path) as fp:
            for line in fp:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return entries

    def _write_manifest(self, entries: list[dict]) -> None:
        manifest_path = self._pending_dir / "manifest.jsonl"
        self._pending_dir.mkdir(parents=True, exist_ok=True)
        tmp = manifest_path.with_suffix(".jsonl.tmp")
        with open(tmp, "w") as fp:
            for e in entries:
                fp.write(json.dumps(e) + "\n")
        os.replace(str(tmp), str(manifest_path))

    def update_status(self, msg_ids: list, new_status: str) -> None:
        manifest_path = self._pending_dir / "manifest.jsonl"
        if not manifest_path.exists():
            return
        entries = self.read_manifest()
        idset = set(msg_ids)
        changed = False
        for e in entries:
            if e.get("msg_id") in idset:
                e["status"] = new_status
                changed = True
        if changed:
            self._write_manifest(entries)

    def remove_entries(self, msg_ids: list) -> None:
        manifest_path = self._pending_dir / "manifest.jsonl"
        if not manifest_path.exists():
            return
        idset = set(msg_ids)
        entries = [e for e in self.read_manifest() if e.get("msg_id") not in idset]
        self._write_manifest(entries)

    def clean_expired(self, now: float | None = None) -> None:
        entries = self.read_manifest()
        now = now or time.time()
        remaining = []
        for e in entries:
            try:
                t = datetime.fromisoformat(e.get("time", "")).timestamp()
            except (ValueError, TypeError):
                t = 0
            if now - t > self._pending_timeout_seconds:
                p = self._pending_dir / e.get("pending_path", "")
                p.unlink(missing_ok=True)
            else:
                remaining.append(e)
        self._write_manifest(remaining)

    async def safe_delete(self, msg_ids: list, files_by_id: dict, delete_coro):
        all_moved = []
        for mid, files in files_by_id.items():
            moved = await self.move_to_pending(mid, files)
            if moved:
                self.append_manifest(mid, moved)
                all_moved.extend(moved)

        resp = await delete_coro

        if resp.status_code not in (200, 204) and all_moved:
            await self.restore(all_moved)
            self.remove_entries(msg_ids)

        return resp
