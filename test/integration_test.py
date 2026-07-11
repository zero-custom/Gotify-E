"""
Integration tests against deployed Gotify[E] + Gotify backend.

Required env vars (or set in .env):
    GOTIFY_BACKEND  http://gotify:8080
    GATEWAY_URL     http://localhost:8765
    APP_TOKEN       Gotify app token for push
    CLIENT_TOKEN    Gotify client token for management API
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

PASS = 0
FAIL = 0


def check(label, condition, detail=""):
    global PASS, FAIL
    if condition:
        print(f"  [{PASS+FAIL+1:02d}] ok {label}")
        PASS += 1
    else:
        print(f"  [{PASS+FAIL+1:02d}] FAIL {label}  [{detail}]")
        FAIL += 1


async def version_endpoint(c):
    print("\n--- /version ---")
    r = await c.get(f"{GATEWAY}/version")
    check("status 200", r.status_code == 200, str(r.status_code))
    data = r.json()
    check("_gateway field", "_gateway" in data)
    check("_upload_max field", "_upload_max" in data)
    check("_gateway value", data.get("_gateway") == "Gotify[e]")
    check("_upload_max > 0", data.get("_upload_max", 0) > 0)
    check("version preserved", "version" in data)


async def app_list(c):
    print("\n--- GET /application (proxy) ---")
    r = await c.get(f"{GATEWAY}/application",
                    headers={"X-Gotify-Key": CLIENT_TOKEN})
    check("status 200", r.status_code == 200, str(r.status_code))
    data = r.json()
    check("response is list", isinstance(data, list))
    names = [a.get("name") for a in data]
    check("gw-test-app visible", "gw-test-app" in names, str(names))


async def post_json(c):
    print("\n--- POST /message JSON ---")
    r = await c.post(
        f"{GATEWAY}/message?token={APP_TOKEN}",
        json={"message": "json test no file", "title": "test", "priority": 5},
    )
    check("status 200", r.status_code == 200, str(r.status_code))
    data = r.json()
    check("has id", "id" in data)
    check("message preserved", data.get("message") == "json test no file")


async def upload_single(c):
    print("\n--- POST /message 1 file ---")
    content = b"integration test " + str(time.time()).encode()
    r = await c.post(
        f"{GATEWAY}/message?token={APP_TOKEN}",
        files={"file": ("test.txt", content, "text/plain")},
        data={"message": "single file"},
    )
    check("status 200", r.status_code == 200, str(r.status_code))
    data = r.json()
    check("has id", "id" in data)
    msg = data.get("message", "")
    check("file URL in message", "uploads" in msg, msg[:80])
    uploaded = re.findall(r"\((\{gateway\}/uploads/[^)]+)\)", msg)
    if uploaded:
        file_url = uploaded[0].replace("{gateway}", GATEWAY)
        r2 = await c.get(file_url)
        check("file accessible", r2.status_code == 200)
        if r2.status_code == 200:
            check("content matches", r2.content == content)


async def upload_multi(c):
    print("\n--- POST /message 2 files ---")
    r = await c.post(
        f"{GATEWAY}/message?token={APP_TOKEN}",
        files=[
            ("file", ("photo.png", b"fake-png-data", "image/png")),
            ("file", ("doc.txt", b"doc content", "text/plain")),
        ],
        data={"message": "multi file"},
    )
    check("status 200", r.status_code == 200, str(r.status_code))
    msg = r.json().get("message", "")
    links = re.findall(r"\]\([^)]+\)", msg)
    check("2 file references", len(links) == 2, f"got {len(links)}")


async def upload_rejected(c):
    print("\n--- POST /message rejected file ---")
    r = await c.post(
        f"{GATEWAY}/message?token={APP_TOKEN}",
        files={"file": ("evil.png", b"not-really-png", "image/png")},
        data={"message": "rejected test"},
    )
    check("status 200 best-effort", r.status_code == 200, str(r.status_code))
    check("message sent", "id" in r.json())


async def get_docs(c):
    print("\n--- GET /docs ---")
    r = await c.get(f"{GATEWAY}/docs")
    check("status 200", r.status_code == 200, str(r.status_code))
    check("text/html", "text/html" in r.headers.get("content-type", ""))
    # i18n.js injection runs on proxied pages only,
    # /docs is served by FastAPI directly, not proxied.


async def docs_cn(c):
    print("\n--- GET /docs?lang=zh_CN ---")
    r = await c.get(f"{GATEWAY}/docs?lang=zh_CN")
    check("status 200", r.status_code == 200, str(r.status_code))


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
    print("=" * 50)

    async with httpx.AsyncClient() as c:
        r = await c.get(f"{GOTIFY}/version", timeout=5)
        print(f"Backend reachable: {r.status_code}")
        r = await c.get(f"{GATEWAY}/version", timeout=5)
        print(f"Gateway reachable: {r.status_code}")

        await version_endpoint(c)
        await app_list(c)
        await post_json(c)
        await upload_single(c)
        await upload_rejected(c)
        await upload_multi(c)
        await get_docs(c)
        await docs_cn(c)

    await healthcheck()

    total = PASS + FAIL
    print(f"\n{'=' * 50}")
    print(f"{PASS}/{total} passed, {FAIL}/{total} failed")
    if FAIL:
        sys.exit(1)
    print("All passed.")


if __name__ == "__main__":
    asyncio.run(main())
