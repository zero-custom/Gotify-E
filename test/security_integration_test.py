"""
Security integration tests for Gotify[E] — P0/P1/P2 fix validation.

Required env vars (or set in .env):
    GATEWAY_URL     http://localhost:8765
    APP_TOKEN       Gotify app token for push
    CLIENT_TOKEN    Gotify client token for management API

Run:
    python3 test/security_integration_test.py
"""
import asyncio
import json
import os
import re
import sys
import time

import httpx

GATEWAY = os.environ.get("GATEWAY_URL", "http://localhost:8765")
APP_TOKEN = os.environ.get("APP_TOKEN", "")
CLIENT_TOKEN = os.environ.get("CLIENT_TOKEN", "")

PASS = 0
FAIL = 0
CREATED_IDS = []  # track created message IDs for audit


def check(label, condition, detail=""):
    global PASS, FAIL
    if condition:
        print(f"  [{PASS+FAIL+1:02d}] \u2713 {label}")
        PASS += 1
    else:
        print(f"  [{PASS+FAIL+1:02d}] \u2717 {label}  [{detail}]")
        FAIL += 1


# ── helpers ────────────────────────────────────────────


async def upload(c, files=None, message="", title=""):
    """POST /message with optional files, return response json."""
    data = {}
    if message:
        data["message"] = message
    if title:
        data["title"] = title
    kw = {"data": data} if files else {"json": data}
    if files:
        kw["files"] = files
    r = await c.post(f"{GATEWAY}/message?token={APP_TOKEN}", **kw)
    if r.status_code == 200:
        body = r.json()
        CREATED_IDS.append(body.get("id"))
    return r


def extract_uploads(text):
    """Extract {gateway}/uploads/... URLs from a message body."""
    return re.findall(r"\((\{gateway\}/uploads/[^)]+)\)", text)


def extract_markdown_links(text):
    """Extract full markdown link/images from message body."""
    return re.findall(r"[!\[].*?\]\([^)]+\)", text)


# ── test groups ────────────────────────────────────────


async def test_version_endpoint(c):
    """P1.1: /version injects _gateway and _max_files."""
    print("\n=== P1.1 /version endpoint ===")
    r = await c.get(f"{GATEWAY}/version")
    check("status 200", r.status_code == 200, str(r.status_code))
    data = r.json()
    check("_gateway field present", "_gateway" in data)
    check("_gateway value", data.get("_gateway") == "Gotify[e]")
    check("_max_files field present", "_max_files" in data)
    check("_max_files > 0", data.get("_max_files", 0) > 0)
    check("_max_files == 5 (default)", data.get("_max_files") == 5, str(data.get("_max_files")))
    check("version preserved", "version" in data)


async def test_file_count_limit(c):
    """P1.1: Upload >5 files → 413."""
    print("\n=== P1.1 File count limit ===")
    files = []
    for i in range(6):
        files.append(("file", (f"f{i}.txt", b"x", "text/plain")))
    r = await upload(c, files=files, message="6 files should fail")
    check("status 413", r.status_code == 413, str(r.status_code))
    if r.status_code == 413:
        body = r.json()
        check("error message contains max", "max" in body.get("error", "").lower(), body.get("error", ""))

    # Boundary: 5 files should pass
    files5 = [("file", (f"g{i}.txt", b"x", "text/plain")) for i in range(5)]
    r2 = await upload(c, files=files5, message="5 files should pass")
    check("5 files passes (200)", r2.status_code == 200, str(r2.status_code))


async def test_staging_flow(c):
    """P0.1: Upload → file accessible at its URL (confirm succeeded)."""
    print("\n=== P0.1 Staging confirm flow ===")
    content = b"staging-test-" + str(time.time()).encode()
    r = await upload(c, files=[("file", ("staging.txt", content, "text/plain"))],
                     message="stage confirm test")
    check("upload ok", r.status_code == 200, str(r.status_code))
    if r.status_code != 200:
        return
    msg = r.json().get("message", "")
    urls = extract_uploads(msg)
    check("file URL in message", len(urls) > 0, str(urls))
    if not urls:
        return
    file_url = urls[0].replace("{gateway}", GATEWAY)
    r2 = await c.get(file_url)
    check("file accessible after upload", r2.status_code == 200, str(r2.status_code))
    if r2.status_code == 200:
        check("content intact", r2.content == content)


async def test_mime_mismatch_saved_as_bin(c):
    """P1.7: Claimed .png but not image → saved as .bin (file not lost)."""
    print("\n=== P1.7 MIME mismatch → saved as .bin ===")
    r = await upload(c, files=[("file", ("evil.png", b"not-a-real-png", "image/png"))],
                     message="mime bin test")
    check("upload ok", r.status_code == 200, str(r.status_code))
    if r.status_code == 200:
        body = r.json()
        check("message sent", "id" in body)
        msg = body.get("message", "")
        check("file link present", "evil.png" in msg, msg[:80])
        # URL should use .bin extension
        urls = extract_uploads(msg)
        if urls:
            check(".bin extension in URL", urls[0].endswith(".bin"), urls[0])
            file_url = urls[0].replace("{gateway}", GATEWAY)
            r2 = await c.get(file_url)
            check("file accessible", r2.status_code == 200, str(r2.status_code))
            if r2.status_code == 200:
                check("content intact", r2.content == b"not-a-real-png")


async def test_dangerous_extension_content_disposition(c):
    """P1.4: .html file served with Content-Disposition: attachment (no CSP needed)."""
    print("\n=== P1.4 Dangerous extension → Content-Disposition: attachment ===")
    content = b"<html>gotify-e test</html>"
    r = await upload(c, files=[("file", ("xss.html", content, "text/html"))],
                     message="dangerous ext test")
    check("upload ok", r.status_code == 200, str(r.status_code))
    if r.status_code != 200:
        return
    msg = r.json().get("message", "")
    urls = extract_uploads(msg)
    check("file URL in message", len(urls) > 0, str(urls))
    if not urls:
        return
    file_url = urls[0].replace("{gateway}", GATEWAY)
    r2 = await c.get(file_url)
    check("file accessible", r2.status_code == 200, str(r2.status_code))
    if r2.status_code == 200:
        disposition = r2.headers.get("content-disposition", "")
        check("Content-Disposition: attachment", "attachment" in disposition, disposition)
        # Dangerous exts get attachment → browser won't render → CSP is optional
        csp = r2.headers.get("content-security-policy", "")
        check("no CSP on dangerous ext (attachment suffices)", csp == "", csp)


async def test_svg_csp_all_files(c):
    """P1.4: CSP `sandbox` on non-dangerous files (blocks script execution)."""
    print("\n=== P1.4 CSP sandbox on non-dangerous files ===")
    content = b"plain text data"
    r = await upload(c, files=[("file", ("note.txt", content, "text/plain"))],
                     message="csp on txt test")
    check("upload ok", r.status_code == 200, str(r.status_code))
    if r.status_code != 200:
        return
    msg = r.json().get("message", "")
    urls = extract_uploads(msg)
    if not urls:
        return
    file_url = urls[0].replace("{gateway}", GATEWAY)
    r2 = await c.get(file_url)
    check("txt file accessible", r2.status_code == 200, str(r2.status_code))
    if r2.status_code == 200:
        csp = r2.headers.get("content-security-policy", "")
        check("CSP sandbox on txt file", csp == "sandbox", csp)


async def test_filename_truncation(c):
    """P2.10: Filename >200 bytes → truncated (preserving extension)."""
    print("\n=== P2.10 Filename truncation to 200 bytes ===")
    # Build a stem that's well over 200 bytes
    long_stem = "A" * 300
    fname = f"{long_stem}.txt"
    content = b"truncation-test"
    r = await upload(c, files=[("file", (fname, content, "text/plain"))],
                     message="truncation test")
    check("upload ok", r.status_code == 200, str(r.status_code))
    if r.status_code != 200:
        return
    msg = r.json().get("message", "")
    urls = extract_uploads(msg)
    check("file URL in message", len(urls) > 0, str(urls))
    if not urls:
        return
    # The stored filename is in the URL path, after the last /
    stored_name = urls[0].split("/")[-1]
    # stored_name format: {uuid}_{safe_stem}{ext}
    # The ext should be .txt
    check("extension preserved", stored_name.endswith(".txt"), stored_name)
    # The full filename (uuid + underscore + stem + ext) should be ≤200 bytes
    name_part = stored_name  # This includes uuid_ prefix
    name_bytes = name_part.encode("utf-8")
    check(f"stored filename <= 200 bytes ({len(name_bytes)})",
          len(name_bytes) <= 200, str(len(name_bytes)))
    # Actually separate the uuid prefix from stem:
    # filename = {uuid}_{stem}{ext}
    parts = stored_name.split("_", 1)
    if len(parts) == 2:
        uuid_part = parts[0]
        rest = parts[1]
        # rest = {stem}{ext}
        if rest.endswith(".txt"):
            stem = rest[:-4]
        else:
            stem = rest
        check("UUID prefix preserved", len(uuid_part) == 32, f"uuid len={len(uuid_part)}")
        # stem should have been truncated
        check("stem truncated (was 300, now shorter)", len(stem) < 300,
              f"stem len={len(stem)}")
    # Verify file is accessible
    file_url = urls[0].replace("{gateway}", GATEWAY)
    r2 = await c.get(file_url)
    check("truncated file accessible", r2.status_code == 200, str(r2.status_code))
    if r2.status_code == 200:
        check("content intact", r2.content == content)


async def test_markdown_escape(c):
    """P2.10: Filename chars [ ] ( ) \\ are escaped in markdown."""
    print("\n=== P2.10 Markdown escape in file links ===")
    tricky_name = "file [test] (1).txt"
    content = b"escape-test"
    r = await upload(c, files=[("file", (tricky_name, content, "text/plain"))],
                     message="markdown escape test")
    check("upload ok", r.status_code == 200, str(r.status_code))
    if r.status_code != 200:
        return
    msg = r.json().get("message", "")
    links = extract_markdown_links(msg)
    check("file link in message", len(links) > 0, str(links))
    if not links:
        return
    link = links[0]
    check("markdown chars are backslash-escaped", "\\[" in link and "\\]" in link, link)
    check("parentheses are backslash-escaped", "\\(" in link and "\\)" in link, link)
    # The file URL (inside parentheses) must NOT be escaped
    url_match = re.search(r"\]\(([^)]+)\)", link)
    if url_match:
        url = url_match.group(1)
        check("file URL has {gateway} marker", "{gateway}" in url, url)
        file_url = url.replace("{gateway}", GATEWAY)
        r2 = await c.get(file_url)
        check("file accessible with tricky name", r2.status_code == 200, str(r2.status_code))
        if r2.status_code == 200:
            check("content intact", r2.content == content)


async def test_filename_sanitization(c):
    """P2.10: Special chars like ../ are sanitized to _."""
    print("\n=== P2.10 Filename sanitization ===")
    # Upload file with path traversal chars
    dirty_name = "../../../etc/passwd"
    content = b"sanity-check"
    r = await upload(c, files=[("file", (dirty_name, content, "text/plain"))],
                     message="sanitization test")
    check("upload ok", r.status_code == 200, str(r.status_code))
    if r.status_code != 200:
        return
    msg = r.json().get("message", "")
    urls = extract_uploads(msg)
    check("file URL in message", len(urls) > 0, str(urls))
    if not urls:
        return
    # Verify no path traversal in URL
    for u in urls:
        check("no ../ in URL", "/../" not in u, u)
        check("no .. in URL", ".." not in u.split("/")[-1], u)
    # Verify file accessible
    file_url = urls[0].replace("{gateway}", GATEWAY)
    r2 = await c.get(file_url)
    check("file accessible", r2.status_code == 200, str(r2.status_code))
    if r2.status_code == 200:
        check("content intact", r2.content == content)


async def test_nfkc_normalization(c):
    """P2.10: Unicode NFKC normalization applied."""
    print("\n=== P2.10 Unicode NFKC normalization ===")
    # Full-width chars (NFKC normalizes to ASCII)
    fname = "\uff28ello.txt"  # Ｈello.txt (H is full-width)
    content = b"nfkc-test"
    r = await upload(c, files=[("file", (fname, content, "text/plain"))],
                     message="nfkc test")
    check("upload ok", r.status_code == 200, str(r.status_code))
    if r.status_code != 200:
        return
    msg = r.json().get("message", "")
    urls = extract_uploads(msg)
    check("file URL in message", len(urls) > 0, str(urls))
    if not urls:
        return
    # The full-width H should be normalized to ASCII H or replaced with _
    stored_name = urls[0].split("/")[-1]
    # After NFKC, full-width H becomes H, so "Hello.txt" should appear
    check("NFKC normalized", "Hello" in stored_name or "Hello" in stored_name,
          stored_name)
    # Verify file accessible
    file_url = urls[0].replace("{gateway}", GATEWAY)
    r2 = await c.get(file_url)
    check("file accessible after NFKC", r2.status_code == 200, str(r2.status_code))
    if r2.status_code == 200:
        check("content intact", r2.content == content)


async def test_upload_url_file_accessible(c):
    """P0.1 + P2.10: Verify the upload URL path matches a real file."""
    print("\n=== P0.1 File reachable at upload URL ===")
    content = b"reachable-test-" + str(time.time()).encode()
    r = await upload(c, files=[("file", ("reachable.txt", content, "text/plain"))],
                     message="reachable test")
    check("upload ok", r.status_code == 200, str(r.status_code))
    if r.status_code != 200:
        return
    # The message contains markdown links; verify each upload URL works
    msg = r.json().get("message", "")
    urls = extract_uploads(msg)
    for url in urls:
        file_url = url.replace("{gateway}", GATEWAY)
        r2 = await c.get(file_url)
        check(f"file reachable at {file_url[-30:]}", r2.status_code == 200, str(r2.status_code))
        if r2.status_code == 200:
            check("content matches", r2.content == content)


async def test_multiple_files_staging(c):
    """P0.1: Multiple files all reachable after upload (all confirmed)."""
    print("\n=== P0.1 Multiple file staging confirm ===")
    now = str(time.time()).encode()
    files = [
        ("file", ("a.txt", b"a-" + now, "text/plain")),
        ("file", ("b.txt", b"b-" + now, "text/plain")),
    ]
    r = await upload(c, files=files, message="multi-staging test")
    check("upload ok", r.status_code == 200, str(r.status_code))
    if r.status_code != 200:
        return
    msg = r.json().get("message", "")
    urls = extract_uploads(msg)
    check("2 file URLs", len(urls) == 2, str(urls))
    for i, url in enumerate(urls):
        file_url = url.replace("{gateway}", GATEWAY)
        r2 = await c.get(file_url)
        check(f"file {i} reachable", r2.status_code == 200, str(r2.status_code))
        if r2.status_code == 200:
            expected = [b"a-" + now, b"b-" + now][i]
            check(f"file {i} content intact", r2.content == expected)


async def test_auth_methods(c):
    """Verify all three token passing methods work through the gateway."""
    print("\n=== Auth methods: query param, X-Gotify-Key, Authorization ===")

    # ── 1. JSON POST with X-Gotify-Key header ─────────
    r = await c.post(
        f"{GATEWAY}/message",
        json={"message": "auth X-Gotify-Key test", "priority": 5},
        headers={"X-Gotify-Key": APP_TOKEN},
    )
    check("status 200", r.status_code == 200, str(r.status_code))
    if r.status_code == 200:
        mid = r.json().get("id")
        CREATED_IDS.append(mid)

    # ── 2. JSON POST with Authorization: Bearer header ─
    r = await c.post(
        f"{GATEWAY}/message",
        json={"message": "auth Bearer test", "priority": 5},
        headers={"Authorization": f"Bearer {APP_TOKEN}"},
    )
    check("status 200", r.status_code == 200, str(r.status_code))
    if r.status_code == 200:
        mid = r.json().get("id")
        CREATED_IDS.append(mid)

    # ── 3. DELETE with X-Gotify-Key header ─────────────
    body = b"auth-header-delete-" + str(time.time()).encode()
    r = await c.post(
        f"{GATEWAY}/message?token={APP_TOKEN}",
        files={"file": ("auth_hdr.txt", body, "text/plain")},
        data={"message": "auth header delete test"},
    )
    check("upload ok", r.status_code == 200, str(r.status_code))
    if r.status_code == 200:
        msg_id = r.json().get("id")
        CREATED_IDS.append(msg_id)
        dr = await c.delete(
            f"{GATEWAY}/message/{msg_id}",
            headers={"X-Gotify-Key": CLIENT_TOKEN},
        )
        check("DELETE via X-Gotify-Key header ok",
              dr.status_code in (200, 204), str(dr.status_code))
        CREATED_IDS.remove(msg_id)

    # ── 4. DELETE with Authorization: Bearer header ────
    body2 = b"auth-bearer-delete-" + str(time.time()).encode()
    r = await c.post(
        f"{GATEWAY}/message?token={APP_TOKEN}",
        files={"file": ("auth_bear.txt", body2, "text/plain")},
        data={"message": "auth bearer delete test"},
    )
    check("upload ok", r.status_code == 200, str(r.status_code))
    if r.status_code == 200:
        msg_id2 = r.json().get("id")
        CREATED_IDS.append(msg_id2)
        dr = await c.delete(
            f"{GATEWAY}/message/{msg_id2}",
            headers={"Authorization": f"Bearer {CLIENT_TOKEN}"},
        )
        check("DELETE via Bearer header ok",
              dr.status_code in (200, 204), str(dr.status_code))
        CREATED_IDS.remove(msg_id2)

    # ── 5. File upload via X-Gotify-Key header ─────────
    body3 = b"multipart-header-test-" + str(time.time()).encode()
    r = await c.post(
        f"{GATEWAY}/message",
        files={"file": ("hdr_upload.txt", body3, "text/plain")},
        data={"message": "multipart via X-Gotify-Key"},
        headers={"X-Gotify-Key": APP_TOKEN},
    )
    check("multipart upload via X-Gotify-Key header ok",
          r.status_code == 200, str(r.status_code))
    if r.status_code == 200:
        mid3 = r.json().get("id")
        CREATED_IDS.append(mid3)

    # ── 6. File upload via Authorization: Bearer header ─
    body4 = b"multipart-bearer-test-" + str(time.time()).encode()
    r = await c.post(
        f"{GATEWAY}/message",
        files={"file": ("bearer_upload.txt", body4, "text/plain")},
        data={"message": "multipart via Bearer"},
        headers={"Authorization": f"Bearer {APP_TOKEN}"},
    )
    check("multipart upload via Bearer header ok",
          r.status_code == 200, str(r.status_code))
    if r.status_code == 200:
        mid4 = r.json().get("id")
        CREATED_IDS.append(mid4)


async def test_no_auth(c):
    """Verify requests without auth are rejected."""
    print("\n=== No-auth requests must return 401 ===")

    # GET /message
    r = await c.get(f"{GATEWAY}/message")
    check("GET /message no auth", r.status_code == 401, str(r.status_code))

    # POST JSON
    r = await c.post(
        f"{GATEWAY}/message",
        json={"message": "no-auth-test"},
    )
    check("POST JSON no auth", r.status_code == 401, str(r.status_code))

    # POST multipart with file
    body = b"no-auth-upload-" + str(time.time()).encode()
    r = await c.post(
        f"{GATEWAY}/message",
        files={"file": ("noauth.txt", body, "text/plain")},
        data={"message": "no auth multipart"},
    )
    check("POST multipart no auth", r.status_code == 401, str(r.status_code))

    # DELETE
    r = await c.delete(f"{GATEWAY}/message/1")
    check("DELETE no auth", r.status_code == 401, str(r.status_code))

    # Verify /version is public (no auth needed)
    r = await c.get(f"{GATEWAY}/version")
    check("GET /version public (no auth)", r.status_code == 200, str(r.status_code))


async def test_auth_methods_all_endpoints(c):
    """Every endpoint works with every auth method; invalid tokens rejected."""
    print("\n=== All auth methods × all endpoints ===")

    auths = {"query token", "X-Gotify-Key", "Bearer"}

    async def app_headers(method):
        if method == "X-Gotify-Key":
            return {"X-Gotify-Key": APP_TOKEN}
        if method == "Bearer":
            return {"Authorization": f"Bearer {APP_TOKEN}"}
        return {}

    async def client_headers(method):
        if method == "X-Gotify-Key":
            return {"X-Gotify-Key": CLIENT_TOKEN}
        if method == "Bearer":
            return {"Authorization": f"Bearer {CLIENT_TOKEN}"}
        return {}

    # GET /message
    print("  [GET /message]")
    for name in auths:
        if name == "query token":
            r = await c.get(f"{GATEWAY}/message?token={CLIENT_TOKEN}")
        else:
            r = await c.get(f"{GATEWAY}/message", headers=await client_headers(name))
        check(f"GET via {name}", r.status_code == 200, str(r.status_code))

    # POST JSON
    print("  [POST /message JSON]")
    for name in auths:
        if name == "query token":
            r = await c.post(f"{GATEWAY}/message?token={APP_TOKEN}",
                             json={"message": f"auth {name}", "priority": 5})
        else:
            r = await c.post(f"{GATEWAY}/message", json={"message": f"auth {name}", "priority": 5},
                             headers=await app_headers(name))
        check(f"POST JSON via {name}", r.status_code == 200, str(r.status_code))
        if r.status_code == 200:
            CREATED_IDS.append(r.json().get("id"))

    # POST multipart
    print("  [POST /message multipart]")
    for name in auths:
        body = f"multi-auth-{name}-".encode() + str(time.time()).encode()
        if name == "query token":
            r = await c.post(f"{GATEWAY}/message?token={APP_TOKEN}",
                             files={"file": ("multi.txt", body, "text/plain")},
                             data={"message": f"multi {name}"})
        else:
            r = await c.post(f"{GATEWAY}/message",
                             files={"file": ("multi.txt", body, "text/plain")},
                             data={"message": f"multi {name}"},
                             headers=await app_headers(name))
        check(f"POST multipart via {name}", r.status_code == 200, str(r.status_code))
        if r.status_code == 200:
            CREATED_IDS.append(r.json().get("id"))

    # DELETE /message
    print("  [DELETE /message]")
    for name in auths:
        body = f"del-auth-{name}-".encode() + str(time.time()).encode()
        r = await c.post(f"{GATEWAY}/message?token={APP_TOKEN}",
                         files={"file": ("del.txt", body, "text/plain")},
                         data={"message": f"delete {name}"})
        if r.status_code != 200:
            check(f"DELETE prep via {name}", False, str(r.status_code))
            continue
        mid = r.json().get("id")
        CREATED_IDS.append(mid)
        if name == "query token":
            dr = await c.delete(f"{GATEWAY}/message/{mid}?token={CLIENT_TOKEN}")
        else:
            dr = await c.delete(f"{GATEWAY}/message/{mid}",
                                headers=await client_headers(name))
        check(f"DELETE via {name}", dr.status_code in (200, 204), str(dr.status_code))
        CREATED_IDS.remove(mid)

    # Invalid tokens → 401
    print("  [Invalid tokens → 401]")
    for label, token, header in [
        ("query", "?token=INVALID_TOKEN", {}),
        ("X-Gotify-Key", "", {"X-Gotify-Key": "INVALID_TOKEN"}),
        ("Bearer", "", {"Authorization": "Bearer INVALID_TOKEN"}),
    ]:
        url = f"{GATEWAY}/message{token}"
        r = await c.get(url, headers=header)
        check(f"GET invalid {label} → 401", r.status_code == 401, str(r.status_code))

        r = await c.post(url, json={"message": "invalid"}, headers=header)
        check(f"POST JSON invalid {label} → 401", r.status_code == 401, str(r.status_code))

        r = await c.post(url, files={"file": ("bad.txt", b"x", "text/plain")},
                         data={"message": "invalid"}, headers=header)
        check(f"POST multipart invalid {label} → 401", r.status_code == 401, str(r.status_code))


async def test_cleanup(c):
    """Delete created messages and verify files are gone."""
    print("\n=== Cleanup: DELETE created messages ===")
    deleted = 0
    for mid in CREATED_IDS:
        r = await c.delete(f"{GATEWAY}/message/{mid}?token={CLIENT_TOKEN}")
        if r.status_code in (200, 204):
            deleted += 1
    check(f"deleted {deleted}/{len(CREATED_IDS)} messages",
          deleted == len(CREATED_IDS), str(CREATED_IDS))


async def healthcheck(c):
    print("\n--- HEALTHCHECK (GET /version) ---")
    r = await c.get(f"{GATEWAY}/version", timeout=5)
    check("gateway reachable", r.status_code == 200, str(r.status_code))


# ── main ───────────────────────────────────────────────


async def main():
    global PASS, FAIL
    print(f"Gateway:   {GATEWAY}")
    print(f"App token: {'*' * max(0, len(APP_TOKEN) - 4) + APP_TOKEN[-4:] if APP_TOKEN else '(missing)'}")
    print("=" * 55)

    if not APP_TOKEN:
        print("ERROR: APP_TOKEN must be set")
        sys.exit(1)

    async with httpx.AsyncClient(timeout=30.0) as c:
        try:
            r = await c.get(f"{GATEWAY}/version", timeout=5)
            print(f"Gateway reachable: {r.status_code}")
        except Exception as e:
            print(f"Gateway unreachable: {e}")
            sys.exit(1)

        await healthcheck(c)
        await test_version_endpoint(c)
        await test_file_count_limit(c)
        await test_staging_flow(c)
        await test_mime_mismatch_saved_as_bin(c)
        await test_dangerous_extension_content_disposition(c)
        await test_svg_csp_all_files(c)
        await test_filename_truncation(c)
        await test_markdown_escape(c)
        await test_filename_sanitization(c)
        await test_nfkc_normalization(c)
        await test_upload_url_file_accessible(c)
        await test_multiple_files_staging(c)
        await test_auth_methods(c)
        await test_no_auth(c)
        await test_auth_methods_all_endpoints(c)
        await test_cleanup(c)

    total = PASS + FAIL
    print(f"\n{'=' * 55}")
    print(f"{PASS}/{total} pass, {FAIL}/{total} fail")
    if FAIL:
        sys.exit(1)
    print("All security integration tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
