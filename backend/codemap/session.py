from __future__ import annotations

import hashlib
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
            session.store.close()


registry = SessionRegistry()
