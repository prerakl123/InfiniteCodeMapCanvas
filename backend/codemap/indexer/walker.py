from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .ignore import IgnoreMatcher


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
            stat = entry.stat(follow_symlinks=False)
        except OSError:
            continue

        if entry.is_symlink():
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
