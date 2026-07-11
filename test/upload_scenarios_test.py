"""
Comprehensive upload scenario tests against deployed Gotify[E].

Required env vars (or set in .env):
    GATEWAY_URL  http://localhost:8765
    APP_TOKEN    Gotify app token for push
"""
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx

GATEWAY = os.environ.get("GATEWAY_URL", "http://localhost:8765")
APP_TOKEN = os.environ.get("APP_TOKEN", "")
DATA_DIR = Path("/tmp/gw-test-files")

PASS = 0
FAIL = 0
TEST_MESSAGE_IDS = []


def ok(label, condition, detail=""):
    global PASS, FAIL
    if condition:
        print(f"  [{PASS+FAIL+1:02d}] ok {label}")
        PASS += 1
    else:
        print(f"  [{PASS+FAIL+1:02d}] FAIL {label}  [{detail}]")
        FAIL += 1


async def send(c, files=None, message="", title="", raw_json=None):
    kw = {}
    if raw_json:
        kw["json"] = raw_json
    elif files:
        data = {}
        if message:
            data["message"] = message
        if title:
            data["title"] = title
        kw["data"] = data
        kw["files"] = files
    else:
        payload = {}
        if message:
            payload["message"] = message
        if title:
            payload["title"] = title
        kw["json"] = payload

    r = await c.post(f"{GATEWAY}/message?token={APP_TOKEN}", **kw)
    if r.status_code == 200:
        body = r.json()
        TEST_MESSAGE_IDS.append(body.get("id"))
    return r


def file_field(name):
    """Open a test file and return (field_name, (filename, content, mime))."""
    path = DATA_DIR / name
    ext = name.rsplit(".", 1)[-1].lower()
    mime_map = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
        "svg": "image/svg+xml",
        "txt": "text/plain",
        "csv": "text/csv",
        "pdf": "application/pdf",
        "bin": "application/octet-stream",
    }
    mime = mime_map.get(ext, "application/octet-stream")
    return ("file", (name, path.read_bytes(), mime))





async def main():
    global PASS, FAIL
    print(f"Gateway: {GATEWAY}")
    print(f"Files:   {DATA_DIR}")
    print("=" * 55)

    async with httpx.AsyncClient() as c:
        # Sanity
        r = await c.get(f"{GATEWAY}/version")
        print(f"Gateway reachable: {r.status_code}")

        # ── 1. 纯消息 ────────────────────────────────
        print("\n=== 1. 纯消息 (message only, no files) ===")
        r = await send(c, message="纯消息测试 no files at all")
        ok("status 200", r.status_code == 200, str(r.status_code))
        if r.status_code == 200:
            d = r.json()
            ok("has id", "id" in d)
            ok("message content", d.get("message") == "纯消息测试 no files at all")
            ok("no uploads in body", "uploads" not in (d.get("message") or ""))

        # ── 2. 消息+图片 ─────────────────────────────
        print("\n=== 2. 消息+图片 (message + 1 image) ===")
        r = await send(c, files=[file_field("photo1.png")], message="消息带一张图片")
        ok("status 200", r.status_code == 200, str(r.status_code))
        if r.status_code == 200:
            d = r.json()
            msg = d.get("message", "")
            ok("message prefix preserved", msg.startswith("消息带一张图片"), msg[:60])
            ok("image markdown present", "![](" in msg, msg[:100])
            ok("file URL in message", "{gateway}/uploads/" in msg)

        # ── 3. 消息+文件 ─────────────────────────────
        print("\n=== 3. 消息+文件 (message + 1 non-image file) ===")
        r = await send(c, files=[file_field("report.pdf")], message="消息带一个PDF文件")
        ok("status 200", r.status_code == 200, str(r.status_code))
        if r.status_code == 200:
            msg = r.json().get("message", "")
            ok("message preserved", "消息带一个PDF文件" in msg)
            ok("file link present", "report.pdf](" in msg, msg[:100])

        # ── 4. 消息+图片+文件 ────────────────────────
        print("\n=== 4. 消息+图片+文件 (message + image + file) ===")
        r = await send(c, files=[
            file_field("photo2.jpg"),
            file_field("doc1.txt"),
        ], message="混合：一张图片加一个文本文件")
        ok("status 200", r.status_code == 200, str(r.status_code))
        if r.status_code == 200:
            msg = r.json().get("message", "")
            links = re.findall(r"[!\[].*?\]\([^)]+\)", msg)
            ok("2 file references", len(links) == 2, f"got {len(links)}: {links}")
            ok("image markdown present", any(l.startswith("!") for l in links))
            ok("file link present", any(l.startswith("[") for l in links))

        # ── 5. 消息+多图片 ───────────────────────────
        print("\n=== 5. 消息+多图片 (message + 3 images) ===")
        r = await send(c, files=[
            file_field("photo1.png"),
            file_field("photo2.jpg"),
            file_field("photo3.webp"),
        ], message="三张图片一起上传")
        ok("status 200", r.status_code == 200, str(r.status_code))
        if r.status_code == 200:
            msg = r.json().get("message", "")
            imgs = re.findall(r"!\[.*?\]\([^)]+\)", msg)
            ok("3 image references", len(imgs) == 3, f"got {len(imgs)}")

        # ── 6. 消息+多文件 ───────────────────────────
        print("\n=== 6. 消息+多文件 (message + 3 files) ===")
        r = await send(c, files=[
            file_field("doc1.txt"),
            file_field("report.pdf"),
            file_field("data.csv"),
        ], message="三个文件一起上传")
        ok("status 200", r.status_code == 200, str(r.status_code))
        if r.status_code == 200:
            msg = r.json().get("message", "")
            file_links = re.findall(r"\[.*?\]\([^)]+\)", msg)
            ok("3 file references", len(file_links) == 3, f"got {len(file_links)}")

        # ── 7. 纯图片 ────────────────────────────────
        print("\n=== 7. 纯图片 (only image, no message text) ===")
        r = await send(c, files=[file_field("animation.gif")], message="")
        ok("status 200", r.status_code == 200, str(r.status_code))
        if r.status_code == 200:
            msg = r.json().get("message", "")
            ok("message starts with image", msg.startswith("![]("), msg[:40])

        # ── 8. 纯文件 ────────────────────────────────
        print("\n=== 8. 纯文件 (only file, no message text) ===")
        r = await send(c, files=[file_field("data.csv")], message="")
        ok("status 200", r.status_code == 200, str(r.status_code))
        if r.status_code == 200:
            msg = r.json().get("message", "")
            ok("message starts with file link", msg.startswith("[data.csv]("), msg[:40])

        # ── 9. 多图片 ────────────────────────────────
        print("\n=== 9. 多图片 (2 images, no message) ===")
        r = await send(c, files=[
            file_field("photo1.png"),
            file_field("photo2.jpg"),
        ], message="")
        ok("status 200", r.status_code == 200, str(r.status_code))
        if r.status_code == 200:
            msg = r.json().get("message", "")
            imgs = re.findall(r"!\[.*?\]\([^)]+\)", msg)
            ok("2 image references", len(imgs) == 2, f"got {len(imgs)}")

        # ── 10. 多文件 ───────────────────────────────
        print("\n=== 10. 多文件 (2 files, no message) ===")
        r = await send(c, files=[
            file_field("doc1.txt"),
            file_field("report.pdf"),
        ], message="")
        ok("status 200", r.status_code == 200, str(r.status_code))
        if r.status_code == 200:
            msg = r.json().get("message", "")
            flinks = re.findall(r"\[.*?\]\([^)]+\)", msg)
            ok("2 file references", len(flinks) == 2, f"got {len(flinks)}")

        # ── 11. 多图片+多文件 ────────────────────────
        print("\n=== 11. 多图片+多文件 (2 images + 2 files) ===")
        r = await send(c, files=[
            file_field("photo1.png"),
            file_field("photo2.jpg"),
            file_field("doc1.txt"),
            file_field("data.csv"),
        ], message="两图两文件混合")
        ok("status 200", r.status_code == 200, str(r.status_code))
        if r.status_code == 200:
            msg = r.json().get("message", "")
            all_links = re.findall(r"[!\[].*?\]\([^)]+\)", msg)
            ok("4 total references", len(all_links) == 4, f"got {len(all_links)}: {all_links}")
            imgs = [l for l in all_links if l.startswith("!")]
            files = [l for l in all_links if l.startswith("[")]
            ok(f"  -> {len(imgs)} images", len(imgs) >= 1)
            ok(f"  -> {len(files)} files", len(files) >= 1)

        # ── 12. 穿越路径文件名 ──────────────────────
        print("\n=== 12. 穿越路径文件名 (path traversal filenames) ===")
        # Files with traversal names placed directly on disk
        (DATA_DIR / "..%2F..%2Fetc%2Fpasswd").write_text("root:x:0:0:root")
        (DATA_DIR / "..\\..\\etc\\shadow").write_text("root:!:1:")
        (DATA_DIR / "subdir").mkdir(exist_ok=True)

        r = await send(c, files=[
            ("file", ("../../../etc/passwd", b"root:x:0:0", "text/plain")),
            ("file", ("..%2F..%2Fetc%2Fpasswd", b"not-real", "text/plain")),
            ("file", ("subdir\\..\\..\\evil.txt", b"test", "text/plain")),
        ], message="路径穿越尝试")
        ok("status 200", r.status_code == 200, str(r.status_code))
        if r.status_code == 200:
            msg = r.json().get("message", "")
            ok("files uploaded without crash", "uploads" in msg, msg[:80])
            links = re.findall(r"\[.*?\]\([^)]+\)", msg)
            ok("3 file links in message", len(links) == 3, f"got {len(links)}")
            urls = re.findall(r"\]\(([^)]+)\)", msg)
            all_urls_safe = all("/../" not in u and "..%2F" not in u for u in urls)
            ok("stored URLs sanitized", all_urls_safe, str(urls))

        # ── 13. SVG 上传 + CSP ──────────────────────
        print("\n=== 13. SVG upload + CSP header ===")
        r = await send(c, files=[file_field("icon.svg")], message="SVG图片")
        ok("status 200", r.status_code == 200, str(r.status_code))
        if r.status_code == 200:
            msg = r.json().get("message", "")
            svg_urls = re.findall(r"\((\{gateway\}/uploads/[^)]+\.svg)\)", msg)
            ok("SVG file uploaded", len(svg_urls) > 0)
            if svg_urls:
                url = svg_urls[0].replace("{gateway}", GATEWAY)
                r2 = await c.get(url)
                ok("SVG accessible", r2.status_code == 200, str(r2.status_code))
                ok("SVG has CSP script-src none",
                   r2.headers.get("content-security-policy") == "script-src 'none'")

        # ── 14. 大文件（超出限制）───────────────────
        print("\n=== 14. 大文件 (60MB, exceeds 50MB limit) ===")
        r = await send(c, files=[file_field("large.bin")], message="超大文件测试")
        ok("status 413 or 502", r.status_code in (413, 502), str(r.status_code))

        # ── 15. 空文件 ────────────────────────────────
        print("\n=== 15. 空文件 (empty file) ===")
        r = await send(c, files=[
            ("file", ("empty.txt", b"", "text/plain")),
        ], message="空文件")
        ok("status 200", r.status_code == 200, str(r.status_code))
        if r.status_code == 200:
            msg = r.json().get("message", "")
            ok("empty file link in message", "empty.txt](" in msg, msg[:60])

        print("\n" + "=" * 55)
        total = PASS + FAIL
        print(f"{PASS}/{total} passed, {FAIL}/{total} failed")

    if FAIL:
        sys.exit(1)
    print("All scenarios passed.")


if __name__ == "__main__":
    asyncio.run(main())
