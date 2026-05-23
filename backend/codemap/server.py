from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import (
    routes_fs,
    routes_graph,
    routes_health,
    routes_project,
    routes_ws
)
from .config import settings


def create_app() -> FastAPI:
    app = FastAPI(title="InfiniteCodeMapCanvas", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.dev_frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(routes_health.router)
    app.include_router(routes_ws.router)
    app.include_router(routes_project.router)
    app.include_router(routes_graph.router)
    app.include_router(routes_fs.router)
    return app


app = create_app()