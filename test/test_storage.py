from storage import FileStore, StoredFile

MARKER_PREFIX = "{gateway}/uploads/"


class TestFileStore:
    def test_save_creates_file(self, tmp_path):
        store = FileStore(tmp_path, MARKER_PREFIX, {".jpg", ".png"})
        result = store.save("photo.bin", b"fake-image-data")
        assert isinstance(result, StoredFile)
        assert result.marker_url.startswith(MARKER_PREFIX)
        assert ".bin" in result.marker_url
        parts = result.marker_url.replace(MARKER_PREFIX, "").split("/")
        assert len(parts) == 3
        saved_path = tmp_path / parts[0] / parts[1] / parts[2]
        assert saved_path.exists()
        assert saved_path.read_bytes() == b"fake-image-data"

    def test_save_generates_image_markdown(self, tmp_path):
        store = FileStore(tmp_path, MARKER_PREFIX, {".jpg", ".png"})
        result = store.save("photo.bin", b"data")
        assert result.markdown.startswith("[photo.bin](")
        assert result.markdown.endswith(")")

    def test_save_generates_file_markdown(self, tmp_path):
        store = FileStore(tmp_path, MARKER_PREFIX, {".jpg"})
        result = store.save("doc.pdf", b"data")
        assert result.markdown.startswith("[doc.pdf](")
        assert result.markdown.endswith(")")

    def test_save_unknown_extension_becomes_bin(self, tmp_path):
        store = FileStore(tmp_path, MARKER_PREFIX, set())
        result = store.save("file.wierd_x", b"data")
        assert ".bin" in result.marker_url

    def test_save_sanitizes_filename(self, tmp_path):
        store = FileStore(tmp_path, MARKER_PREFIX, set())
        result = store.save("../../evil.txt", b"data")
        assert "/../" not in result.marker_url
        assert result.marker_url.endswith(".txt")

    def test_image_mime_mismatch_saved_as_bin(self, tmp_path):
        import magic
        magic.from_buffer.return_value = "application/zip"
        store = FileStore(tmp_path, MARKER_PREFIX, {".png"})
        result = store.save("photo.png", b"fake-zip-data")
        assert result.marker_url.endswith(".bin"), f"expected .bin, got {result.marker_url}"
        assert result.original_name == "photo.png"
        saved_path = tmp_path / result.path
        assert saved_path.exists()
        assert saved_path.read_bytes() == b"fake-zip-data"

    def test_non_image_extension_no_mime_check(self, tmp_path):
        store = FileStore(tmp_path, MARKER_PREFIX, {".png"})
        result = store.save("doc.pdf", b"any-data")
        assert result is not None

    def test_filename_nfkc_normalized(self, tmp_path):
        store = FileStore(tmp_path, MARKER_PREFIX, set())
        result = store.save("héllo\u200Bworld.txt", b"data")
        assert result.marker_url.endswith("h\u00e9llo_world.txt")
