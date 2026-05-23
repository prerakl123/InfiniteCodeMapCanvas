from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws/echo")
async def echo(ws: WebSocket) -> None:
    await ws.accept()
    await ws.send_json({"type": "hello", "message": "connected"})
    try:
        while True:
            data = await ws.receive_text()
            await ws.send_json({"type": "echo", "message": data})
    except WebSocketDisconnect:
        return