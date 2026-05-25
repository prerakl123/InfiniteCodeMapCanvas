from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .ignore import IgnoreMatcher

# Windows' os.DirEntry.stat() always reports st_ino=0 and st_dev=0, which would
# collapse the inode-based dedup below into "everything is the first entry".
# On Windows we fall back to os.stat(), which queries the file index properly.
_NEEDS_FULL_STAT = sys.platform == "win32"

# os.path.isjunction was added in Python 3.12; on older interpreters we fall
# back to a stat-based reparse-point check.
_HAS_ISJUNCTION = hasattr(os.path, "isjunction")


def _is_windows_junction(entry_path: str, stat_result) -> bool:
    if not _NEEDS_FULL_STAT:
        return False
    if _HAS_ISJUNCTION:
        return os.path.isjunction(entry_path)
    # Fallback for Python 3.11: check the reparse-point bit directly.
    import stat as _stat_mod
    file_attrs = getattr(stat_result, "st_file_attributes", 0)
    return bool(file_attrs & _stat_mod.FILE_ATTRIBUTE_REPARSE_POINT)


@dataclass
class WalkEntry:
    path: Path
    is_dir: bool
    size: int
    mtime_ns: int


def walk(root: Path, ignore: IgnoreMatcher) -> Iterator[WalkEntry]:
    seen_inodes: set[tuple[int, int]] = set()
    yield from _walk_dir(root, ignore, seen_inodes)


def _walk_dir(
    directory: Path,
    ignore: IgnoreMatcher,
    seen_inodes: set[tuple[int, int]],
) -> Iterator[WalkEntry]:
    try:
        entries = list(os.scandir(directory))
    except PermissionError:
        return

    for entry in entries:
        path = Path(entry.path)

        if ignore.matches(path):
            continue

        try:
            if _NEEDS_FULL_STAT:
                stat = os.stat(entry.path, follow_symlinks=False)
            else:
                stat = entry.stat(follow_symlinks=False)
        except OSError:
            continue

        if entry.is_symlink():
            continue
        # Windows junctions are reparse points that don't always report as
        # symlinks via entry.is_symlink(); skip them so we don't walk into
        # OneDrive / WindowsApps loops.
        if _is_windows_junction(entry.path, stat):
            continue

        inode_key = (stat.st_dev, stat.st_ino)
        if inode_key in seen_inodes:
            continue
        seen_inodes.add(inode_key)

        if entry.is_dir(follow_symlinks=False):
            yield WalkEntry(
                path=path,
                is_dir=True,
                size=0,
                mtime_ns=stat.st_mtime_ns,
            )
            yield from _walk_dir(path, ignore, seen_inodes)
        else:
            yield WalkEntry(
                path=path,
                is_dir=False,
                size=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
            )
