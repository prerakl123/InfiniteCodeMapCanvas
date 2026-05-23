from __future__ import annotations

from fastapi import APIRouter

from ..config import settings

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "version": "0.1.0",
        "codemap_root": str(settings.codemap_root),
    }