from __future__ import annotations

import threading
import time
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .indexer.ignore import IgnoreMatcher
from .indexer.incremental import reindex_file
from .paths import canonical_path_str

if TYPE_CHECKING:
    from .session import ProjectSession


class _DebouncedReparseHandler(FileSystemEventHandler):
    def __init__(self, watcher: "ProjectWatcher") -> None:
        self._watcher = watcher

    def on_any_event(self, event) -> None:  # noqa: ANN001
        if event.is_directory:
            return
        path_str = str(event.src_path)
        if not path_str.endswith(".py"):
            return
        path = Path(path_str)
        if self._watcher._ignore.matches(path):
            return
        self._watcher._enqueue(path)

        if event.event_type == "moved" and getattr(event, "dest_path", None):
            dest = Path(event.dest_path)
            if not self._watcher._ignore.matches(dest) and dest.suffix == ".py":
                self._watcher._enqueue(dest)


class ProjectWatcher:
    """Watches a project root and reindexes affected files in a background thread.

    Debounces rapid successive events on the same path to avoid duplicate work.
    """

    def __init__(self, session: "ProjectSession", debounce_ms: int = 120) -> None:
        self._session = session
        self._observer = Observer()
        self._ignore = IgnoreMatcher.from_project(session.project_root)
        self._debounce_ms = debounce_ms
        self._queue: deque[Path] = deque()
        self._lock = threading.Lock()
        self._stop_evt = threading.Event()
        self._cond = threading.Condition(self._lock)
        self._worker = threading.Thread(
            target=self._worker_loop, name=f"codemap-watcher-{session.project_id}", daemon=True
        )

    def start(self) -> None:
        handler = _DebouncedReparseHandler(self)
        self._observer.schedule(handler, str(self._session.project_root), recursive=True)
        self._observer.start()
        self._worker.start()

    def stop(self) -> None:
        self._stop_evt.set()
        with self._cond:
            self._cond.notify_all()
        try:
            self._observer.stop()
            self._observer.join(timeout=2)
        except Exception:
            pass

    def _enqueue(self, path: Path) -> None:
        with self._cond:
            self._queue.append(path)
            self._cond.notify_all()

    def _worker_loop(self) -> None:
        while not self._stop_evt.is_set():
            with self._cond:
                while not self._queue and not self._stop_evt.is_set():
                    self._cond.wait()
                if self._stop_evt.is_set():
                    return
                # Drain & dedupe within the debounce window.
                time.sleep(self._debounce_ms / 1000)
                pending: dict[str, Path] = {}
                while self._queue:
                    p = self._queue.popleft()
                    # Canonicalize so watchdog events with different casing or
                    # path representation than the indexer's stored form still
                    # collapse to the same dedup key and hit SQL exact-match.
                    pending[canonical_path_str(p)] = p
            for path in pending.values():
                try:
                    reindex_file(self._session, path)
                except Exception:
                    pass
