import re
import uuid
import unicodedata
from pathlib import Path

import magic


class FileRejectedError(Exception):
    pass


class StoredFile:
    def __init__(self, marker_url: str, markdown: str):
        self.marker_url = marker_url
        self.markdown = markdown


class FileStore:
    def __init__(self, upload_dir: Path, marker_prefix: str, image_exts: set):
        self.upload_dir = upload_dir
        self.marker_prefix = marker_prefix
        self.image_exts = image_exts

    def save(self, filename: str, body: bytes) -> StoredFile:
        stem = Path(filename).stem
        ext = Path(filename).suffix or ""

        if not re.match(r"^\.[a-zA-Z0-9]{1,10}$", ext):
            ext = ".bin"

        mime = magic.from_buffer(body, mime=True)
        is_image = ext.lower() in self.image_exts
        if is_image and not mime.startswith("image/"):
            raise FileRejectedError(f"claimed image but mime={mime}")

        safe_stem = unicodedata.normalize("NFKC", stem)
        safe_stem = re.sub(r"[^\w.\-]", "_", safe_stem)

        unique = uuid.uuid4().hex
        sub = f"{unique[:2]}/{unique[2:4]}"
        name = f"{unique}_{safe_stem}{ext}"
        file_dir = self.upload_dir / sub
        file_dir.mkdir(parents=True, exist_ok=True)
        save_path = file_dir / name
        with open(save_path, "wb") as fp:
            fp.write(body)

        marker_url = f"{self.marker_prefix}{sub}/{name}"
        ext_lower = ext.lower()
        if ext_lower in self.image_exts:
            markdown = f"![]({marker_url})"
        else:
            markdown = f"[{filename}]({marker_url})"

        return StoredFile(marker_url, markdown)
