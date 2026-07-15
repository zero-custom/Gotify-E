import json
import logging
from dataclasses import dataclass, field

from fastapi import Request
from fastapi.responses import JSONResponse

from config import load_env_config

_cfg = load_env_config()
_MAX_UPLOAD = _cfg.max_upload_mb * 1024 * 1024
from proxy import (
    HttpClient,
    format_error,
    proxy_to_backend,
)
from storage import FileStore

log = logging.getLogger("gotify-gateway.upload")


class _ContentEncodingError(Exception):
    pass


@dataclass
class FileProcessingResult:
    injected_lines: list[str] = field(default_factory=list)
    stored_files: list = field(default_factory=list)


async def handle_message_post(
    request: Request,
    file_store: FileStore,
    http_client: HttpClient,
) -> JSONResponse:
    try:
        return await _process_upload(request, file_store, http_client)
    except _ContentEncodingError:
        return JSONResponse(
            status_code=415,
            content=format_error(415, "compressed upload not supported"),
        )
    except Exception as e:
        log.error("handle_message_post failed", exc_info=True)
        return JSONResponse(
            status_code=500,
            content=format_error(500, "Internal server error"),
        )


async def _process_upload(
    request: Request,
    file_store: FileStore,
    http_client: HttpClient,
) -> JSONResponse:
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" not in content_type:
        return await proxy_to_backend(request, http_client=http_client)

    content_encoding = request.headers.get("content-encoding", "")
    if content_encoding.strip() and content_encoding.strip().lower() != "identity":
        log.warning("rejected compressed upload: content-encoding=%s", content_encoding)
        raise _ContentEncodingError()

    form = await request.form(max_part_size=_MAX_UPLOAD)

    message = form.get("message", "")
    title = form.get("title", "")
    priority_raw = form.get("priority", "")
    priority = int(priority_raw) if (priority_raw or "").strip() else 5
    extras_raw = form.get("extras", "")
    extras = {}
    if extras_raw:
        try:
            parsed = json.loads(extras_raw)
            if isinstance(parsed, dict):
                extras = parsed
        except json.JSONDecodeError:
            log.warning("invalid extras JSON in multipart form: %s", extras_raw[:200])

    file_fields = form.getlist("file")
    if len(file_fields) > _cfg.max_files_per_request:
        return JSONResponse(
            status_code=413,
            content=format_error(413, f"Too many files, max {_cfg.max_files_per_request}"),
        )
    result = await _process_files(file_fields, file_store)

    if result.injected_lines:
        sep = "\n\n---\n" if message.strip() else ""
        message = message.rstrip() + sep + "\n".join(result.injected_lines)

    payload = {
        "message": message,
        "title": title,
        "priority": priority,
        "extras": extras,
    }
    payload["extras"]["client::display"] = {"contentType": "text/markdown"}
    if result.stored_files:
        payload["extras"]["gateway::files"] = [
            {"uuid": s.uuid, "path": s.path, "name": s.original_name, "size": s.size}
            for s in result.stored_files
        ]

    proxy_headers = {}
    for k, v in request.headers.items():
        kl = k.lower()
        if kl not in ("host", "origin", "content-type", "content-length", "transfer-encoding", "content-encoding"):
            proxy_headers[kl] = v
    proxy_headers["content-type"] = "application/json"

    resp = await proxy_to_backend(
        request,
        http_client=http_client,
        method="POST",
        headers=proxy_headers,
        body=json.dumps(payload, ensure_ascii=False).encode(),
    )

    if resp.status_code == 200:
        for sf in result.stored_files:
            await file_store.confirm(sf)
    else:
        for sf in result.stored_files:
            file_store.cancel(sf)

    return resp


async def _process_files(
    file_fields: list,
    file_store: FileStore,
) -> FileProcessingResult:
    result = FileProcessingResult()

    for f in file_fields:
        is_file_obj = (
            hasattr(f, "filename")
            and hasattr(f, "read")
            and callable(f.read)
        )

        if is_file_obj:
            fname = f.filename or "unnamed"
            try:
                content = await f.read()
                stored = file_store.save(fname, content)
                result.injected_lines.append(stored.markdown)
                result.stored_files.append(stored)
                log.info("saved %s -> %s (%d bytes)", fname, stored.marker_url, len(content))
            except Exception as e2:
                log.error("unexpected error saving %s", fname, exc_info=True)

        elif isinstance(f, (str, bytes)):
            content = f.encode() if isinstance(f, str) else f
            try:
                marker = file_store.save("uploaded_file", content)
                result.injected_lines.append(marker.markdown)
                log.info("saved raw content %d bytes -> %s", len(content), marker.marker_url)
            except Exception as e2:
                log.error("unexpected error saving raw content", exc_info=True)

    return result
