from __future__ import annotations

import os
from pathlib import Path


def canonical_path_str(p: Path | str) -> str:
    """Stable string form for a filesystem path used as a storage/lookup key.

    On Windows this lowercases the path (via os.path.normcase) so equality
    holds whether the path came from os.scandir (preserves disk casing),
    watchdog events (may differ), or user-supplied input. On POSIX it is a
    no-op beyond normpath collapsing redundant separators.
    """
    return os.path.normcase(os.path.normpath(str(p)))
