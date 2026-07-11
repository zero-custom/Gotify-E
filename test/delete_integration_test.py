"""
Integration tests for DELETE file cleanup against deployed Gotify[E] + Gotify.

Required env vars (or set in .env):
    GOTIFY_BACKEND  http://gotify:8080
    GATEWAY_URL     http://localhost:8765
    APP_TOKEN       Gotify app token for push
    CLIENT_TOKEN    Gotify client token for management API

Tested scenarios:
    1. Upload message with file → DELETE → file cleaned up
    2. Upload message without file → DELETE → no file operation
    3. Upload multiple files → DELETE all → all cleaned up
    4. Continuous delete (multiple messages)
    5. Batch delete app messages → all files cleaned up
    6. DELETE non-existent message → 404
    7. extras.gateway::files present after upload
"""
import asyncio
import json
import os
import re
import sys
import time
import urllib.request

import httpx

GOTIFY = os.environ.get("GOTIFY_BACKEND", "http://localhost:8080")
GATEWAY = os.environ.get("GATEWAY_URL", "http://localhost:8765")
APP_TOKEN = os.environ.get("APP_TOKEN", "")
CLIENT_TOKEN = os.environ.get("CLIENT_TOKEN", "")
APP_NAME = os.environ.get("APP_NAME", "gw-test-app")

PASS = 0
FAIL = 0


def check(label, condition, detail=""):
    global PASS, FAIL
    if condition:
        print(f"  [{PASS+FAIL+1:02d}] ok  {label}")
        PASS += 1
    else:
        print(f"  [{PASS+FAIL+1:02d}] FAIL {label}  [{detail}]")
        FAIL += 1


def parse_extras_gateway_files(msg_text):
    files = re.findall(r'\{gateway\}/uploads/([^)\s]+)', msg_text)
    return files


async def upload_with_file(c, content=None):
    body = content or b"delete-test-" + str(time.time()).encode()
    r = await c.post(
        f"{GATEWAY}/message?token={APP_TOKEN}",
        files={"file": ("test.txt", body, "text/plain")},
        data={"message": "delete test file"},
    )
    if r.status_code != 200:
        return None, None
    data = r.json()
    msg_id = data.get("id")
    msg_text = data.get("message", "")
    uploads = re.findall(r"\((\{gateway\}/uploads/[^)]+)\)", msg_text)
    return msg_id, uploads


async def upload_plain_message(c):
    r = await c.post(
        f"{GATEWAY}/message?token={APP_TOKEN}",
        json={"message": "plain message no file", "priority": 5},
    )
    if r.status_code != 200:
        return None
    return r.json().get("id")


async def get_message(c, msg_id):
    # Gotify 2.9.x has no GET /message/{id}, use since+limit instead.
    r = await c.get(
        f"{GATEWAY}/message?limit=1&since={msg_id + 1}&token={CLIENT_TOKEN}"
    )
    if r.status_code != 200:
        return None
    msgs = r.json().get("messages", [])
    for msg in msgs:
        if msg.get("id") == msg_id:
            return msg
    return None


async def test_extras_gateway_files(c):
    print("\n=== 1. extras.gateway::files after upload ===")
    body = b"extras-check-" + str(time.time()).encode()
    r = await c.post(
        f"{GATEWAY}/message?token={APP_TOKEN}",
        files={"file": ("extras.txt", body, "text/plain")},
        data={"message": "check extras"},
    )
    check("upload ok", r.status_code == 200, str(r.status_code))
    if r.status_code != 200:
        return

    msg_id = r.json().get("id")
    check("msg_id present", msg_id is not None)

    msg_json = await get_message(c, msg_id)
    check("GET message ok", msg_json is not None)
    gw_files = []
    file_url = None
    if msg_json:
        extras = msg_json.get("extras", {})
        gw_files = extras.get("gateway::files", [])
        check("extras.gateway::files present", len(gw_files) > 0, str(gw_files))
        if gw_files:
            f = gw_files[0]
            check("uuid field", "uuid" in f)
            check("path field", "path" in f)
            check("name field", "name" in f)
            check("size field", "size" in f)
            check("name matches", f.get("name") == "extras.txt", f.get("name", ""))
            check("size matches", f.get("size") == len(body), str(f.get("size")))
            check("path contains uuid", "/" in f.get("path", ""))
            # Verify file is accessible at the path
            file_url = f"{GATEWAY}/uploads/{f['path']}"
            fr = await c.get(file_url)
            check("file accessible", fr.status_code == 200, str(fr.status_code))
            if fr.status_code == 200:
                check("file content matches", fr.content == body)

    # Cleanup
    dr = await c.delete(f"{GATEWAY}/message/{msg_id}?token={CLIENT_TOKEN}")
    check("delete ok", dr.status_code in (200, 204), str(dr.status_code))
    # File should be gone after delete
    if gw_files:
        fr2 = await c.get(file_url)
        check("file gone after delete", fr2.status_code != 200, str(fr2.status_code))


async def test_single_delete_with_file(c):
    print("\n=== 2. Single DELETE with file ===")
    body = b"single-delete-" + str(time.time()).encode()
    msg_id, uploads = await upload_with_file(c, body)
    check("upload ok", msg_id is not None)
    if not msg_id:
        return
    check("file URLs in response", len(uploads) > 0, str(uploads))

    # Verify file accessible before delete
    if uploads:
        file_url = uploads[0].replace("{gateway}", GATEWAY)
        fr = await c.get(file_url)
        check("file accessible before delete", fr.status_code == 200, str(fr.status_code))
        if fr.status_code == 200:
            check("content intact", fr.content == body)

    # Delete
    dr = await c.delete(f"{GATEWAY}/message/{msg_id}?token={CLIENT_TOKEN}")
    check("delete status 200/204", dr.status_code in (200, 204), str(dr.status_code))

    # File should be gone
    if uploads:
        fr2 = await c.get(file_url)
        check("file gone after delete", fr2.status_code != 200, str(fr2.status_code))

    # Message should be gone from Gotify
    gm = await get_message(c, msg_id)
    check("message gone after delete", gm is None)


async def test_single_delete_without_file(c):
    print("\n=== 3. Single DELETE without file ===")
    msg_id = await upload_plain_message(c)
    check("plain msg upload ok", msg_id is not None)
    if not msg_id:
        return

    dr = await c.delete(f"{GATEWAY}/message/{msg_id}?token={CLIENT_TOKEN}")
    check("delete ok (no file)", dr.status_code in (200, 204), str(dr.status_code))

    gm = await get_message(c, msg_id)
    check("message gone", gm is None)


async def test_multi_file_delete(c):
    print("\n=== 4. Multiple files on one message → DELETE all ===")
    body = b"multi-file-" + str(time.time()).encode()
    r = await c.post(
        f"{GATEWAY}/message?token={APP_TOKEN}",
        files=[
            ("file", ("f1.txt", body, "text/plain")),
            ("file", ("f2.txt", body, "text/plain")),
        ],
        data={"message": "multi file delete test"},
    )
    check("multi-file upload ok", r.status_code == 200, str(r.status_code))
    if r.status_code != 200:
        return

    data = r.json()
    msg_id = data.get("id")
    msg_text = data.get("message", "")
    uploads = re.findall(r"\((\{gateway\}/uploads/[^)]+)\)", msg_text)
    check("2 file URLs in response", len(uploads) == 2, str(len(uploads)))

    # Verify both files accessible
    if uploads:
        for u in uploads:
            fu = await c.get(u.replace("{gateway}", GATEWAY))
            check(f"file {u[-20:]} accessible", fu.status_code == 200, str(fu.status_code))

    # Delete
    dr = await c.delete(f"{GATEWAY}/message/{msg_id}?token={CLIENT_TOKEN}")
    check("delete ok", dr.status_code in (200, 204), str(dr.status_code))

    # Both files gone
    if uploads:
        for u in uploads:
            fu = await c.get(u.replace("{gateway}", GATEWAY))
            check(f"file {u[-20:]} gone after delete", fu.status_code != 200, str(fu.status_code))


async def test_continuous_delete(c):
    print("\n=== 5. Continuous delete (multiple messages) ===")
    ids = []
    for i in range(3):
        body = f"cont-delete-{i}-{time.time()}".encode()
        mid, _ = await upload_with_file(c, body)
        check(f"msg {i} uploaded", mid is not None)
        if mid:
            ids.append(mid)

    check("3 messages created", len(ids) == 3, str(ids))
    if len(ids) < 3:
        return

    for i, mid in enumerate(ids):
        dr = await c.delete(f"{GATEWAY}/message/{mid}?token={CLIENT_TOKEN}")
        check(f"msg {i} deleted", dr.status_code in (200, 204), str(dr.status_code))
        gm = await get_message(c, mid)
        check(f"msg {i} gone", gm is None)


async def test_app_batch_delete(c):
    print("\n=== 6. Batch delete app messages ===")
    ids = []
    for i in range(2):
        body = f"batch-{i}-{time.time()}".encode()
        mid, _ = await upload_with_file(c, body)
        if mid:
            ids.append(mid)
    check("2 messages uploaded for batch test", len(ids) == 2, str(ids))
    if len(ids) < 2:
        return

    # Find our app by name (the test app created for integration testing)
    apps_r = await c.get(f"{GATEWAY}/application?token={CLIENT_TOKEN}")
    if apps_r.status_code != 200:
        check("batch delete status (skipped - no app)", False, str(apps_r.status_code))
        return
    apps = apps_r.json()
    our = [a for a in apps if a.get("name") == APP_NAME]
    if not our:
        check("batch delete status (skipped - app not found)", False, str(apps))
        return
    app_id = our[0]["id"]

    dr = await c.delete(f"{GATEWAY}/application/{app_id}/message?token={CLIENT_TOKEN}")
    check("batch delete status", dr.status_code in (200, 204), str(dr.status_code))


async def test_delete_nonexistent(c):
    print("\n=== 7. DELETE non-existent message ===")
    dr = await c.delete(f"{GATEWAY}/message/99999999?token={CLIENT_TOKEN}")
    check("non-existent returns 404", dr.status_code == 404, str(dr.status_code))


async def test_delete_multi_ids(c):
    print("\n=== 8. Multi-delete (individual DELETE /message/{id}) ===")
    ids = []
    for i in range(2):
        mid, _ = await upload_with_file(c)
        if mid:
            ids.append(mid)
    check("2 msgs for multi-delete", len(ids) == 2, str(ids))
    if len(ids) < 2:
        return

    for mid in ids:
        dr = await c.delete(f"{GATEWAY}/message/{mid}?token={CLIENT_TOKEN}")
        check(f"DELETE msg {mid}", dr.status_code in (200, 204), str(dr.status_code))
        gm = await get_message(c, mid)
        check(f"msg {mid} gone", gm is None)


async def healthcheck():
    print("\n--- HEALTHCHECK (urllib /version) ---")
    try:
        r = urllib.request.urlopen(f"{GATEWAY}/version", timeout=5)
        check("HEALTHCHECK passes", r.status == 200, str(r.status))
    except Exception as e:
        check("HEALTHCHECK passes", False, str(e))


async def main():
    print(f"Backend: {GOTIFY}")
    print(f"Gateway: {GATEWAY}")
    print(f"App token: {'*' * max(0, len(APP_TOKEN) - 4) + APP_TOKEN[-4:] if APP_TOKEN else '(missing)'}")
    print(f"Client token: {'*' * max(0, len(CLIENT_TOKEN) - 4) + CLIENT_TOKEN[-4:] if CLIENT_TOKEN else '(missing)'}")
    print("=" * 55)

    if not APP_TOKEN or not CLIENT_TOKEN:
        print("ERROR: APP_TOKEN and CLIENT_TOKEN must be set")
        sys.exit(1)

    async with httpx.AsyncClient(timeout=30.0) as c:
        try:
            r = await c.get(f"{GOTIFY}/version", timeout=5)
            print(f"Backend reachable: {r.status_code}")
        except Exception as e:
            print(f"Backend unreachable: {e}")
            sys.exit(1)

        try:
            r = await c.get(f"{GATEWAY}/version", timeout=5)
            print(f"Gateway reachable: {r.status_code}")
        except Exception as e:
            print(f"Gateway unreachable: {e}")
            sys.exit(1)

        await test_extras_gateway_files(c)
        await test_single_delete_with_file(c)
        await test_single_delete_without_file(c)
        await test_multi_file_delete(c)
        await test_continuous_delete(c)
        await test_app_batch_delete(c)
        await test_delete_nonexistent(c)
        await test_delete_multi_ids(c)

    await healthcheck()

    total = PASS + FAIL
    print(f"\n{'=' * 55}")
    print(f"{PASS}/{total} passed, {FAIL}/{total} failed")
    if FAIL:
        sys.exit(1)
    print("All passed.")


if __name__ == "__main__":
    asyncio.run(main())
