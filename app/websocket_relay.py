import asyncio
import logging

import websockets
from fastapi import WebSocket, WebSocketDisconnect

from config import load_env_config
from proxy import build_gateway_url, rewrite_file_urls

_cfg = load_env_config()
_BACKEND = _cfg.gotify_backend

log = logging.getLogger("gotify-gateway.websocket")


async def stream_proxy(websocket: WebSocket):
    await websocket.accept()
    closed = False

    qs = websocket.query_params
    ws_backend = _BACKEND.replace("http://", "ws://").replace("https://", "wss://")
    backend_url = f"{ws_backend}/stream"

    # 从 cookie 中提取 gotify-client-token 作为查询参数传递
    params = dict(qs)
    client_token = websocket.cookies.get("gotify-client-token")
    if client_token and "token" not in params:
        params["token"] = client_token

    if params:
        query_string = "&".join(f"{k}={v}" for k, v in params.items())
        backend_url += f"?{query_string}"

    try:
        async with websockets.connect(backend_url) as backend_ws:

            async def client_to_backend():
                nonlocal closed
                while not closed:
                    try:
                        msg = await websocket.receive()
                        if msg["type"] == "websocket.disconnect":
                            closed = True
                            break
                        data = msg.get("text") or msg.get("bytes")
                        if data is not None:
                            await backend_ws.send(data)
                    except WebSocketDisconnect:
                        closed = True
                        break

            async def backend_to_client():
                nonlocal closed
                while not closed:
                    try:
                        message = await backend_ws.recv()
                        if message is None:
                            closed = True
                            break
                        current = build_gateway_url(websocket)
                        text = message if isinstance(message, str) else message.decode("utf-8")
                        text = rewrite_file_urls(text.encode("utf-8"), current).decode("utf-8")
                        await websocket.send_text(text)
                    except websockets.ConnectionClosed:
                        closed = True
                        break

            await asyncio.gather(
                client_to_backend(),
                backend_to_client(),
            )

    except Exception as e:
        log.error("websocket error: %s", e)
    finally:
        closed = True
        try:
            await websocket.close()
        except Exception:
            pass
