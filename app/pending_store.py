import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("gotify-gateway.pending_store")


class PendingStore:
    def __init__(self, upload_dir: Path, pending_dir: Path, pending_timeout_seconds: int):
        self._upload_dir = upload_dir
        self._pending_dir = pending_dir
        self._pending_timeout_seconds = pending_timeout_seconds

    def move_to_pending(self, msg_id: int, files: list) -> list[dict]:
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        moved = []
        for f in files:
            orig = f.get("path", "")
            if not orig:
                continue
            src = self._upload_dir / orig
            if not src.exists():
                log.warning("file not found: %s", src)
                continue
            pending_sub = self._pending_dir / date_str
            pending_sub.mkdir(parents=True, exist_ok=True)
            flat = orig.replace("/", "_")
            dst = pending_sub / flat
            try:
                os.rename(str(src), str(dst))
                moved.append({"msg_id": msg_id, "orig_path": orig, "pending_path": f"{date_str}/{flat}"})
            except OSError as e:
                log.error("move failed: %s -> %s: %s", src, dst, e)
        return moved

    def restore(self, entries: list[dict]) -> None:
        for item in entries:
            src = self._pending_dir / item["pending_path"]
            dst = self._upload_dir / item["orig_path"]
            if not src.exists():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.rename(str(src), str(dst))
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
            self._pending_dir.mkdir(parents=True, exist_ok=True)
            with open(manifest_path, "w") as fp:
                for e in entries:
                    fp.write(json.dumps(e) + "\n")

    def remove_entries(self, msg_ids: list) -> None:
        manifest_path = self._pending_dir / "manifest.jsonl"
        if not manifest_path.exists():
            return
        idset = set(msg_ids)
        entries = [e for e in self.read_manifest() if e.get("msg_id") not in idset]
        with open(manifest_path, "w") as fp:
            for e in entries:
                fp.write(json.dumps(e) + "\n")

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
        manifest_path = self._pending_dir / "manifest.jsonl"
        with open(manifest_path, "w") as fp:
            for e in remaining:
                fp.write(json.dumps(e) + "\n")

    async def safe_delete(self, msg_ids: list, files_by_id: dict, delete_coro):
        """Move files to pending, execute delete, rollback on failure.

        Parameters:
            msg_ids: all message IDs for manifest cleanup on rollback.
            files_by_id: mapping of msg_id to list of file descriptors.
            delete_coro: awaitable that performs the DELETE and returns a response.

        Returns: the response from delete_coro.
        """
        all_moved = []
        for mid, files in files_by_id.items():
            moved = self.move_to_pending(mid, files)
            if moved:
                self.append_manifest(mid, moved)
                all_moved.extend(moved)

        resp = await delete_coro

        if resp.status_code not in (200, 204) and all_moved:
            self.restore(all_moved)
            self.remove_entries(msg_ids)

        return resp
