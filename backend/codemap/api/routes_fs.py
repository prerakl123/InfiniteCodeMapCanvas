from __future__ import annotations

import os
import string
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/fs")

# Synthetic path token used to expose a "list of available drives" view on
# Windows. When the user is at a drive root (e.g. C:\) we set the parent to
# this token; the browser endpoint recognizes it and returns each available
# drive letter as an entry. POSIX has a single filesystem root and never
# emits this token.
_WINDOWS_DRIVES_TOKEN = "::drives::"
_IS_WINDOWS = sys.platform == "win32"


def _list_windows_drives() -> list[dict]:
    drives = []
    for letter in string.ascii_uppercase:
        root = f"{letter}:\\"
        if Path(root).exists():
            drives.append({"name": root, "path": root, "isDir": True})
    return drives


@router.get("/browse")
def browse(path: str = "~") -> dict:
    if _IS_WINDOWS and path == _WINDOWS_DRIVES_TOKEN:
        return {
            "path": _WINDOWS_DRIVES_TOKEN,
            "parent": None,
            "entries": _list_windows_drives(),
        }

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

    if resolved.parent != resolved:
        parent: str | None = str(resolved.parent)
    elif _IS_WINDOWS:
        # At a drive root on Windows: expose the synthetic "drives" view as
        # the parent so the user can switch between C:, D:, etc.
        parent = _WINDOWS_DRIVES_TOKEN
    else:
        parent = None

    return {
        "path": str(resolved),
        "parent": parent,
        "entries": entries,
    }
