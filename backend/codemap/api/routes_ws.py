from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..event_bus import event_bus
from ..session import registry

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


@router.websocket("/ws/project/{project_id}/events")
async def project_events(ws: WebSocket, project_id: str) -> None:
    """Per-project event channel.

    Optional query parameter `since_seq` lets a client request replay of
    missed events. If the server can't fulfil it (events too old), the client
    receives `{"type": "resync_required"}` and should refetch from REST.
    """
    await ws.accept()
    session = registry.get(project_id)
    if session is None:
        await ws.send_json({"type": "error", "error": "unknown project"})
        await ws.close()
        return

    since_seq_raw = ws.query_params.get("since_seq")
    since_seq: int | None
    try:
        since_seq = int(since_seq_raw) if since_seq_raw is not None else None
    except ValueError:
        since_seq = None

    sub, replay = event_bus.subscribe(project_id, since_seq=since_seq)

    last_seq = event_bus.last_seq(project_id)
    await ws.send_json({
        "type": "hello",
        "project_id": project_id,
        "last_seq": last_seq,
        "indexing": {
            "fraction": session.indexing.fraction,
            "current": session.indexing.current,
            "done": session.indexing.done,
            "error": session.indexing.error,
        },
    })

    for evt in replay:
        await ws.send_json(evt)

    async def reader() -> None:
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            return

    reader_task = asyncio.create_task(reader())
    get_task = asyncio.create_task(sub.queue.get())
    try:
        while True:
            done, _ = await asyncio.wait(
                [get_task, reader_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            if reader_task in done:
                get_task.cancel()
                return
            evt = get_task.result()
            await ws.send_json(evt)
            get_task = asyncio.create_task(sub.queue.get())
    except WebSocketDisconnect:
        return
    finally:
        event_bus.unsubscribe(sub)
        for task in (reader_task, get_task):
            if not task.done():
                task.cancel()