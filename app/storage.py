import asyncio
import json
import logging
import re
import shutil
import uuid
import unicodedata
from pathlib import Path

import magic

from config import GatewayConfig

log = logging.getLogger(__name__)


def _escape_markdown_link_label(text: str) -> str:
    return text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]").replace("(", "\\(").replace(")", "\\)")


class StoredFile:
    def __init__(self, marker_url: str, markdown: str, uuid: str = "",
                 path: str = "", size: int = 0, original_name: str = ""):
        self.marker_url = marker_url
        self.markdown = markdown
        self.uuid = uuid
        self.path = path
        self.size = size
        self.original_name = original_name


class FileStore:
    def __init__(self, upload_dir: Path, marker_prefix: str, image_exts: set, staging_dir: Path | None = None):
        self.upload_dir = upload_dir
        self.staging_dir = staging_dir
        self.marker_prefix = marker_prefix
        self.image_exts = image_exts

    def save(self, filename: str, body: bytes) -> StoredFile:
        stem = Path(filename).stem
        ext = Path(filename).suffix or ""

        if not re.match(r"^\.[a-zA-Z0-9]{1,10}$", ext):
            ext = ".bin"

        try:
            mime = magic.from_buffer(body, mime=True)
            is_image = ext.lower() in self.image_exts
            if is_image and not mime.startswith("image/"):
                log.info("MIME mismatch for %s: claimed image but mime=%s, saving as .bin", filename, mime)
                ext = ".bin"
        except Exception:
            log.warning("MIME detection failed for %s, saving as .bin", filename, exc_info=True)
            ext = ".bin"

        safe_stem = unicodedata.normalize("NFKC", stem)
        safe_stem = re.sub(r"[^\w.\-]", "_", safe_stem)

        uuid_overhead = 32 + 1
        safe_stem_bytes = safe_stem.encode("utf-8")
        ext_bytes = ext.encode("utf-8")
        stem_ext_len = len(safe_stem_bytes) + len(ext_bytes)
        max_stem_ext = GatewayConfig.MAX_FILENAME_BYTES - uuid_overhead
        if stem_ext_len > max_stem_ext:
            max_stem = max(0, max_stem_ext - len(ext_bytes))
            safe_stem = safe_stem_bytes[:max_stem].decode("utf-8", errors="ignore")

        unique = uuid.uuid4().hex
        sub = f"{unique[:2]}/{unique[2:4]}"
        name = f"{unique}_{safe_stem}{ext}"
        relative_path = f"{sub}/{name}"

        base_dir = self.staging_dir or self.upload_dir
        file_dir = base_dir / sub
        file_dir.mkdir(parents=True, exist_ok=True)
        save_path = file_dir / name
        with open(save_path, "wb") as fp:
            fp.write(body)

        if self.staging_dir:
            meta = {"uuid": unique, "relative_path": relative_path, "original_name": filename}
            meta_path = file_dir / f".{name}.meta"
            with open(meta_path, "w") as fp:
                json.dump(meta, fp)

        marker_url = f"{self.marker_prefix}{sub}/{name}"
        ext_lower = ext.lower()
        if ext_lower in self.image_exts:
            markdown = f"![]({marker_url})"
        else:
            safe_label = _escape_markdown_link_label(filename)
            markdown = f"[{safe_label}]({marker_url})"

        return StoredFile(
            marker_url=marker_url,
            markdown=markdown,
            uuid=unique,
            path=relative_path,
            size=len(body),
            original_name=filename,
        )

    @staticmethod
    def _rmdir_parents(path: Path) -> None:
        try:
            path.rmdir()
        except OSError:
            return
        try:
            path.parent.rmdir()
        except OSError:
            pass

    async def confirm(self, stored: StoredFile) -> None:
        if not self.staging_dir:
            return
        src = self.staging_dir / stored.path
        dst = self.upload_dir / stored.path
        if not src.exists():
            return
        dst.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.move, str(src), str(dst))
        leaf = self.staging_dir / Path(stored.path).parent
        meta = leaf / f".{Path(stored.path).name}.meta"
        meta.unlink(missing_ok=True)
        self._rmdir_parents(leaf)

    def cancel(self, stored: StoredFile) -> None:
        if not self.staging_dir:
            return
        src = self.staging_dir / stored.path
        src.unlink(missing_ok=True)
        leaf = self.staging_dir / Path(stored.path).parent
        meta = leaf / f".{Path(stored.path).name}.meta"
        meta.unlink(missing_ok=True)
        self._rmdir_parents(leaf)
