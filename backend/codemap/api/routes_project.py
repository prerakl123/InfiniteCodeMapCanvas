from __future__ import annotations

import hashlib
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from ..indexer.ids import make_node_id
from ..indexer.ignore import IgnoreMatcher
from ..indexer.walker import walk
from ..session import IndexingState, ProjectSession, registry
from ..stats import compute_stats

router = APIRouter(prefix="/api")


class OpenProjectRequest(BaseModel):
    path: str


def _run_indexing(session: ProjectSession) -> None:
    root = session.project_root
    project_id = session.project_id
    state = session.indexing
    state.fraction = 0.0
    state.current = ""
    state.done = False
    state.error = None

    try:
        ignore = IgnoreMatcher.from_project(root)
        entries = list(walk(root, ignore))

        total = len(entries) + 1
        processed = 0

        root_id = make_node_id(str(root), "")
        root_node = {
            "id": root_id,
            "kind": "directory",
            "name": root.name,
            "path": str(root),
            "parent_id": None,
            "meta": {"project_id": project_id, "child_counts": {}, "loc_total": 0},
        }
        session.store.upsert_node(root_node)
        processed += 1
        state.fraction = processed / total
        state.current = str(root)

        dir_ids: dict[str, str] = {str(root): root_id}

        for entry in entries:
            path_str = str(entry.path)
            state.current = path_str

            parent_str = str(entry.path.parent)
            parent_id = dir_ids.get(parent_str)

            node_id = make_node_id(path_str, "")

            if entry.is_dir:
                dir_ids[path_str] = node_id
                node = {
                    "id": node_id,
                    "kind": "directory",
                    "name": entry.path.name,
                    "path": path_str,
                    "parent_id": parent_id,
                    "meta": {"child_counts": {}, "loc_total": 0},
                }
                session.store.upsert_node(node)
            else:
                content_hash: str | None = None
                try:
                    raw = entry.path.read_bytes()
                    content_hash = hashlib.blake2b(raw, digest_size=8).hexdigest()
                except OSError:
                    pass

                node = {
                    "id": node_id,
                    "kind": "file",
                    "name": entry.path.name,
                    "path": path_str,
                    "parent_id": parent_id,
                    "content_hash": content_hash,
                    "meta": {"loc": 0, "loc_code": 0},
                }
                session.store.upsert_node(node)
                session.store.upsert_file_record(
                    path=path_str,
                    content_hash=content_hash or "",
                    mtime_ns=entry.mtime_ns,
                    size=entry.size,
                )

            processed += 1
            state.fraction = processed / total

        session.store.set_meta("last_full_sync_at", datetime.now(timezone.utc).isoformat())
        state.fraction = 1.0
        state.done = True

    except Exception as exc:
        state.error = str(exc)
        state.done = True


@router.post("/project")
def open_project(body: OpenProjectRequest, background_tasks: BackgroundTasks) -> dict:
    project_path = Path(body.path)
    if not project_path.exists():
        raise HTTPException(status_code=400, detail="Path does not exist")
    if not project_path.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")

    session = registry.open(project_path)
    session.indexing = IndexingState()
    background_tasks.add_task(_run_indexing, session)

    return {
        "project_id": session.project_id,
        "codemap_dir": str(session.codemap_dir),
        "status": "indexing",
    }


@router.get("/project/{project_id}/stats")
def get_stats(project_id: str) -> dict:
    session = registry.get(project_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown project")
    stats = compute_stats(session)
    return asdict(stats)


@router.post("/project/{project_id}/reindex")
def reindex(
    project_id: str,
    background_tasks: BackgroundTasks,
    full: bool = True,
) -> dict:
    session = registry.get(project_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown project")
    session.indexing = IndexingState()
    background_tasks.add_task(_run_indexing, session)
    return {"status": "indexing"}


@router.get("/project/{project_id}/status")
def get_status(project_id: str) -> dict:
    session = registry.get(project_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown project")
    s = session.indexing
    return {
        "fraction": s.fraction,
        "current": s.current,
        "done": s.done,
        "error": s.error,
    }
