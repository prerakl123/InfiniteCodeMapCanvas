from __future__ import annotations

import hashlib
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from ..event_bus import event_bus
from ..indexer import graph_builder
from ..indexer.ids import make_node_id
from ..indexer.ignore import IgnoreMatcher
from ..indexer.parser_python import PythonParser
from ..indexer.pool import parse_files_parallel
from ..indexer.walker import walk
from ..paths import canonical_path_str
from ..session import IndexingState, ProjectSession, registry
from ..stats import compute_stats
from ..watcher import ProjectWatcher

router = APIRouter(prefix="/api")


class OpenProjectRequest(BaseModel):
    path: str
    force: bool = False


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

        total = len(entries) + 2
        processed = 0

        # 1. Create the project root directory node.
        root_path_str = canonical_path_str(root)
        root_id = make_node_id(root_path_str, "")
        root_node = {
            "id": root_id,
            "kind": "directory",
            "name": root.name,
            "path": root_path_str,
            "parent_id": None,
            "meta": {"project_id": project_id, "child_counts": {}, "loc_total": 0},
        }
        session.store.upsert_node(root_node)
        processed += 1
        state.fraction = processed / total
        state.current = root_path_str

        dir_ids: dict[str, str] = {root_path_str: root_id}
        py_files: list[tuple[Path, str, int, int]] = []  # (path, parent_dir_id, mtime, size)

        # 2. Walk and write directory + file nodes (without symbol info yet).
        parser = PythonParser()
        try_jedi_enabled = False
        try:
            from ..indexer.parser_python_jedi import enrich_with_jedi  # type: ignore
            try_jedi_enabled = True
        except Exception:
            enrich_with_jedi = None  # type: ignore

        for entry in entries:
            path_str = canonical_path_str(entry.path)
            state.current = path_str

            parent_str = canonical_path_str(entry.path.parent)
            parent_id = dir_ids.get(parent_str)

            if entry.is_dir:
                node_id = make_node_id(path_str, "")
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
                processed += 1
                state.fraction = processed / total
                continue

            # Files: only Python files get full parse; others get a stub file node.
            if entry.path.suffix == ".py":
                py_files.append((entry.path, parent_id or root_id, entry.mtime_ns, entry.size))
                processed += 1
                state.fraction = processed / total
                continue

            content_hash: str | None = None
            try:
                raw = entry.path.read_bytes()
                content_hash = hashlib.blake2b(raw, digest_size=8).hexdigest()
            except OSError:
                pass

            node_id = make_node_id(path_str, "")
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
            if processed % 50 == 0:
                event_bus.publish(
                    project_id,
                    {
                        "type": "indexing.progress",
                        "fraction": state.fraction,
                        "current": state.current,
                    },
                )

        # 3. Parse Python files in pass 1 (AST symbols + pending edges).
        #    Uses the process pool for batches >= 16 files.
        state.current = f"Parsing {len(py_files)} Python files…"
        py_paths = [t[0] for t in py_files]
        parse_results_raw = parse_files_parallel(py_paths, root)
        meta_by_path = {canonical_path_str(t[0]): (t[1], t[2], t[3]) for t in py_files}

        parse_results: list[tuple] = []  # (pr, fpath, mtime, size)
        for pr in parse_results_raw:
            parent_id, mtime_ns, size = meta_by_path.get(canonical_path_str(pr.path), (None, 0, 0))
            graph_builder.write_parse_result(
                session.store,
                pr,
                file_parent_id=parent_id,
                file_mtime_ns=mtime_ns,
                file_size=size,
            )
            parse_results.append((pr, Path(pr.path), mtime_ns, size))

        processed += 1
        state.fraction = processed / total

        # 4. Resolve pending edges (imports, inherits, decorates) cross-file.
        ext_cache: dict[str, str] = {}
        qmap = graph_builder.build_qualname_map([pr for pr, *_ in parse_results])
        file_aliases = {pr.path: pr.name_aliases for pr, *_ in parse_results}

        all_pending = []
        for pr, *_ in parse_results:
            all_pending.extend(pr.pending_edges)

        resolved, import_reverse = graph_builder.resolve_pending_edges(
            all_pending,
            qmap,
            session.store,
            project_id,
            ext_cache,
            file_aliases=file_aliases,
        )
        graph_builder.write_resolved_edges(session.store, resolved)
        graph_builder.record_import_reverse(session.store, import_reverse)

        # 5. Optional Phase-3 enrichment with jedi (calls + instantiates).
        if try_jedi_enabled and enrich_with_jedi is not None:
            try:
                state.current = "Resolving calls (jedi)…"
                enrich_with_jedi(
                    session=session,
                    parse_results=[pr for pr, *_ in parse_results],
                    qmap=qmap,
                    project_root=root,
                )
            except Exception as exc:  # noqa: BLE001
                # Non-fatal: jedi enrichment may fail on broken envs.
                state.current = f"jedi enrichment skipped: {exc}"

        session.store.set_meta(
            "last_full_sync_at", datetime.now(timezone.utc).isoformat()
        )
        state.fraction = 1.0
        state.done = True

        # Phase 4: kick off the filesystem watcher once indexing completes.
        if session.watcher is None:
            try:
                w = ProjectWatcher(session)
                w.start()
                session.watcher = w
            except Exception as exc:  # noqa: BLE001
                # Watcher startup failure is non-fatal; index is usable read-only.
                state.current = f"watcher unavailable: {exc}"

        # Publish indexing.complete on WS for any connected clients.
        event_bus.publish(
            session.project_id,
            {
                "type": "indexing.complete",
                "node_counts": session.store.count_nodes_by_kind(),
            },
        )

    except Exception as exc:
        state.error = str(exc)
        state.done = True
        event_bus.publish(
            session.project_id, {"type": "indexing.error", "error": str(exc)}
        )


@router.post("/project")
def open_project(body: OpenProjectRequest, background_tasks: BackgroundTasks) -> dict:
    project_path = Path(body.path)
    if not project_path.exists():
        raise HTTPException(status_code=400, detail="Path does not exist")
    if not project_path.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")

    if body.force:
        try:
            registry.force_reset(project_path)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=500, detail=f"Force reset failed: {exc}"
            )

    try:
        session = registry.open(project_path)
    except RuntimeError as exc:
        # Schema mismatch or other recoverable open-time failure: tell the
        # client they can retry with `force=true` to wipe the stale index.
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(exc),
                "recoverable": True,
                "action": "force_reset",
            },
        )

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
    force: bool = False,
) -> dict:
    session = registry.get(project_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown project")

    if force:
        project_path = session.project_root
        try:
            registry.force_reset(project_path)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=500, detail=f"Force reset failed: {exc}"
            )
        try:
            session = registry.open(project_path)
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    session.indexing = IndexingState()
    background_tasks.add_task(_run_indexing, session)
    return {
        "project_id": session.project_id,
        "status": "indexing",
    }


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
