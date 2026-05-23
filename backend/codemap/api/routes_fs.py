from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/fs")


@router.get("/browse")
def browse(path: str = "~") -> dict:
    resolved = Path(path).expanduser().resolve()

    if not resolved.exists():
        raise HTTPException(status_code=404, detail="Path does not exist")
    if not resolved.is_dir():
        resolved = resolved.parent

    try:
        raw_entries = list(os.scandir(resolved))
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")

    entries = []
    for e in sorted(raw_entries, key=lambda x: (not x.is_dir(follow_symlinks=False), x.name.lower())):
        try:
            entries.append({
                "name": e.name,
                "path": str(Path(e.path).resolve()),
                "isDir": e.is_dir(follow_symlinks=False),
            })
        except OSError:
            continue

    parent = str(resolved.parent) if resolved.parent != resolved else None

    return {
        "path": str(resolved),
        "parent": parent,
        "entries": entries,
    }
