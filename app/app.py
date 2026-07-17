import asyncio
import logging
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from cleanup import cleanup_loop
from config import load_env_config, GatewayConfig
from log_filter import TokenSanitizingFilter

_cfg = load_env_config()
_BACKEND = _cfg.gotify_backend
_HOST = _cfg.host
_PORT = _cfg.port
_UPLOAD_DIR = Path(GatewayConfig.UPLOAD_DIR)
_STAGING_DIR = Path(GatewayConfig.STAGING_DIR)
_MAX_UPLOAD = _cfg.max_upload_mb * 1024 * 1024
_MARKER_PREFIX = f"{GatewayConfig.STORED_MARKER.rstrip('/')}/uploads/"
_IMAGE_EXTS = GatewayConfig.IMAGE_EXTS
_GATEWAY_DIR = Path(__file__).parent.resolve() / GatewayConfig.GATEWAY_DIR_NAME
from proxy import (
    RealHttpClient,
    format_error,
    proxy_to_backend,
)
from storage import FileStore
from upload import handle_message_post
from delete_handler import handle_app_delete, handle_message_delete, recover_on_startup
from websocket_relay import stream_proxy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
for handler in logging.getLogger().handlers:
    handler.addFilter(TokenSanitizingFilter())
log = logging.getLogger("gotify-gateway")

_UPLOAD_DIR.mkdir(exist_ok=True)
_STAGING_DIR.mkdir(exist_ok=True)
file_store = FileStore(_UPLOAD_DIR, _MARKER_PREFIX, _IMAGE_EXTS, staging_dir=_STAGING_DIR)

_http_client = RealHttpClient()


async def _clean_staging_dirs() -> None:
    for sub_dir in list(_STAGING_DIR.iterdir()):
        if not sub_dir.is_dir():
            continue
        for sub_sub in list(sub_dir.iterdir()):
            if not sub_sub.is_dir():
                continue
            FileStore._rmdir_parents(sub_sub)


async def recover_staging() -> None:
    if not _STAGING_DIR.exists():
        return
    recovered = 0
    for sub_dir in _STAGING_DIR.iterdir():
        if not sub_dir.is_dir():
            continue
        for sub_sub in sub_dir.iterdir():
            if sub_sub.is_dir():
                for f in sub_sub.iterdir():
                    if f.suffix == ".meta" or not f.is_file():
                        continue
                    relative = f.relative_to(_STAGING_DIR)
                    dst = _UPLOAD_DIR / relative
                    if dst.exists():
                        f.unlink(missing_ok=True)
                        meta = f.with_name(f".{f.name}.meta")
                        meta.unlink(missing_ok=True)
                    else:
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        await asyncio.to_thread(shutil.move, str(f), str(dst))
                        meta = f.with_name(f".{f.name}.meta")
                        meta.unlink(missing_ok=True)
                        recovered += 1
    if recovered:
        log.info("staging recovery: moved %d orphaned files to uploads", recovered)
    await _clean_staging_dirs()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await recover_staging()
    cleanup_task = asyncio.create_task(cleanup_loop())
    await recover_on_startup(_http_client)
    yield
    cleanup_task.cancel()
    await _http_client.aclose()


app = FastAPI(title="Gotify[E]", version=GatewayConfig.VERSION, lifespan=lifespan)


@app.middleware("http")
async def check_body_size(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH"):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > _MAX_UPLOAD:
            log.warning("request too large: %s bytes", content_length)
            return JSONResponse(
                status_code=413,
                content=format_error(413, f"Request too large, max {_MAX_UPLOAD} bytes"),
            )
    return await call_next(request)


@app.get("/uploads/{file_path:path}")
async def serve_upload(file_path: str):
    resolved = (_UPLOAD_DIR / file_path).resolve()
    if not str(resolved).startswith(str(_UPLOAD_DIR.resolve())):
        raise HTTPException(status_code=404, detail="Not found")
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="Not found")

    ext = Path(file_path).suffix.lower()
    is_dangerous = ext in GatewayConfig.DANGEROUS_EXTS
    disposition = "attachment" if is_dangerous else "inline"

    headers = {
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "public, max-age=3600",
        "Content-Disposition": f'{disposition}; filename="{Path(file_path).name}"',
    }
    if not is_dangerous:
        headers["Content-Security-Policy"] = "sandbox"

    return FileResponse(path=resolved, headers=headers)


app.mount("/_gateway", StaticFiles(directory=str(_GATEWAY_DIR)), name="gateway")


@app.get("/message")
@app.put("/message")
async def handle_message_default(request: Request):
    return await proxy_to_backend(request, http_client=_http_client)

@app.delete("/message")
async def handle_message_delete_route(request: Request):
    return await handle_message_delete(request, http_client=_http_client, file_store=file_store)

@app.delete("/message/{msg_id}")
async def handle_message_delete_by_id(request: Request, msg_id: int):
    return await handle_message_delete(request, http_client=_http_client, file_store=file_store, msg_id=msg_id)


@app.post("/message")
async def handle_message_post_route(request: Request):
    return await handle_message_post(request, file_store=file_store, http_client=_http_client)


@app.websocket("/stream")
async def stream_proxy_route(websocket: WebSocket):
    return await stream_proxy(websocket)


@app.delete("/application/{app_id}/message")
async def handle_app_delete_route(request: Request, app_id: int):
    return await handle_app_delete(request, app_id, http_client=_http_client)

@app.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
)
async def catch_all(request: Request, path: str):
    return await proxy_to_backend(request, http_client=_http_client)


def main():
    import uvicorn
    log.info("=" * 52)
    log.info("  Gotify[E] v%s", GatewayConfig.VERSION)
    log.info("  Backend: %s", _BACKEND)
    log.info("  Listen : http://%s:%s", _HOST, _PORT)
    log.info("  Uploads: %s", _UPLOAD_DIR)
    log.info("=" * 52)

    uvicorn.run(
        "app:app",
        host=_HOST,
        port=_PORT,
        proxy_headers=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()
