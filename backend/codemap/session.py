from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .config import settings
from .storage.store import Store


def _project_id(project_path: Path) -> str:
    return hashlib.blake2b(str(project_path.resolve()).encode(), digest_size=8).hexdigest()


@dataclass
class IndexingState:
    fraction: float = 0.0
    current: str = ""
    done: bool = False
    error: str | None = None


@dataclass
class ProjectSession:
    project_id: str
    project_root: Path
    codemap_dir: Path
    store: Store
    indexing: IndexingState = field(default_factory=IndexingState)
    # Lazily attached at index-completion time.
    watcher: object | None = None


class SessionRegistry:
    def __init__(self) -> None:
        self._sessions: dict[str, ProjectSession] = {}

    def open(self, project_path: Path) -> ProjectSession:
        pid = _project_id(project_path)
        if pid in self._sessions:
            return self._sessions[pid]
        codemap_dir = settings.project_codemap_dir(project_path)
        codemap_dir.mkdir(parents=True, exist_ok=True)
        store = Store(codemap_dir / "index.db")
        session = ProjectSession(
            project_id=pid,
            project_root=project_path.resolve(),
            codemap_dir=codemap_dir,
            store=store,
        )
        self._sessions[pid] = session
        return session

    def get(self, project_id: str) -> ProjectSession | None:
        return self._sessions.get(project_id)

    def close(self, project_id: str) -> None:
        session = self._sessions.pop(project_id, None)
        if session:
            if session.watcher is not None:
                try:
                    session.watcher.stop()  # type: ignore[attr-defined]
                except Exception:
                    pass
            session.store.close()

    def force_reset(self, project_path: Path) -> None:
        """Wipe the cached index for `project_path` so the next `.open()`
        rebuilds from scratch.

        Closes any active session, then deletes the contents of the
        per-project codemap dir (index.db plus its WAL/SHM sidecars).
        The dir itself is left in place so MD5/path-hashed children stay
        addressable. Never touches files under the user's project tree.
        """
        pid = _project_id(project_path)
        self.close(pid)
        codemap_dir = settings.project_codemap_dir(project_path)
        if not codemap_dir.exists():
            return
        for child in codemap_dir.iterdir():
            try:
                if child.is_file() or child.is_symlink():
                    child.unlink()
                elif child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
            except OSError:
                # Best-effort wipe; a leftover .db-shm that can't be deleted
                # will get overwritten on the next open.
                pass


registry = SessionRegistry()
