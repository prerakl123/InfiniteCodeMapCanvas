from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .graph_builder import (
    record_import_reverse,
    resolve_pending_edges,
    write_parse_result,
    write_resolved_edges,
)
from .ids import make_node_id
from .parser_python import PythonParser
from ..event_bus import event_bus
from ..paths import canonical_path_str

if TYPE_CHECKING:
    from ..session import ProjectSession


def _existing_state_for_file(session: "ProjectSession", path: str) -> tuple[set[str], set[str]]:
    """Return (node_ids, edge_ids) currently in the store for this file."""
    nodes = session.store.get_nodes_by_path(path)
    node_ids = {n["id"] for n in nodes}
    rows = session.store.get_edges_by_path(path)
    edge_ids = {r["id"] for r in rows}
    return node_ids, edge_ids


def reindex_file(
    session: "ProjectSession",
    file_path: Path,
    *,
    publish_events: bool = True,
) -> None:
    """Re-parse a single file and apply diffs to the store + publish WS events."""
    path_str = canonical_path_str(file_path)
    if not file_path.is_file():
        # Treat as removal.
        nodes = session.store.get_nodes_by_path(path_str)
        for n in nodes:
            session.store.delete_node_cascade(n["id"])
            if publish_events:
                event_bus.publish(
                    session.project_id, {"type": "node.removed", "id": n["id"]}
                )
        with session.store._conn:
            session.store._conn.execute(
                "DELETE FROM files WHERE path = ?", (path_str,)
            )
        return

    # Snapshot existing state
    prior_nodes, prior_edges = _existing_state_for_file(session, path_str)

    # Need the file's parent directory node id
    parent_dir = canonical_path_str(file_path.parent)
    parent_row = session.store._conn.execute(
        "SELECT id FROM nodes WHERE path = ? AND kind = 'directory'", (parent_dir,)
    ).fetchone()
    parent_id = parent_row["id"] if parent_row else None

    raw = file_path.read_bytes()
    parser = PythonParser()
    pr = parser.parse(raw, file_path, session.project_root)

    write_parse_result(
        session.store,
        pr,
        file_parent_id=parent_id,
        file_mtime_ns=file_path.stat().st_mtime_ns,
        file_size=file_path.stat().st_size,
    )

    # Resolve pending edges for THIS file alone (cross-file ones may reference
    # other files; that's still OK because qmap is rebuilt from the whole DB).
    qmap: dict[str, str] = {}
    rows = session.store._conn.execute(
        "SELECT id, qualname FROM nodes WHERE qualname IS NOT NULL"
    ).fetchall()
    for r in rows:
        qmap.setdefault(r["qualname"], r["id"])

    file_aliases = {pr.path: pr.name_aliases}
    resolved, import_reverse = resolve_pending_edges(
        pr.pending_edges,
        qmap,
        session.store,
        session.project_id,
        ext_cache={},
        file_aliases=file_aliases,
    )
    write_resolved_edges(session.store, resolved)
    record_import_reverse(session.store, import_reverse)

    # Reverse-import invalidation: any file G that imports F may need its
    # edges to F re-resolved. We re-parse F-targeted edges originating in G,
    # without re-parsing G's full AST.
    importers = session.store.get_importers_of(path_str)
    for importer_path in importers:
        if importer_path == path_str:
            continue
        # Cheap: just delete old import edges from G -> nodes in F, then re-parse G's imports.
        # For simplicity we re-parse G's imports only.
        try:
            g_path = Path(importer_path)
            if not g_path.is_file():
                continue
            g_raw = g_path.read_bytes()
            g_pr = parser.parse(g_raw, g_path, session.project_root)
            # Only handle import edges from the importer
            import_pending = [p for p in g_pr.pending_edges if p.kind == "imports"]
            g_aliases = {g_pr.path: g_pr.name_aliases}
            g_resolved, g_rev = resolve_pending_edges(
                import_pending, qmap, session.store, session.project_id, {}, file_aliases=g_aliases
            )
            # Remove old imports edges sourced from G that target nodes in F
            f_nodes = session.store.get_nodes_by_path(path_str)
            f_node_ids = {n["id"] for n in f_nodes}
            with session.store._conn:
                if f_node_ids:
                    placeholders = ",".join("?" * len(f_node_ids))
                    g_file_id = make_node_id(canonical_path_str(importer_path), "")
                    session.store._conn.execute(
                        f"DELETE FROM edges WHERE source_id = ? AND target_id IN ({placeholders}) AND kind = 'imports'",
                        [g_file_id] + list(f_node_ids),
                    )
            write_resolved_edges(session.store, g_resolved)
            record_import_reverse(session.store, g_rev)
        except Exception:
            continue

    # Compute diff for events
    new_nodes_ids = {pr.file_node.id} | {n.id for n in pr.nodes}
    removed_nodes = prior_nodes - new_nodes_ids
    added_nodes = new_nodes_ids - prior_nodes
    changed_nodes = new_nodes_ids & prior_nodes  # may or may not have changed; emit as changed

    if publish_events:
        for nid in removed_nodes:
            event_bus.publish(session.project_id, {"type": "node.removed", "id": nid})
        for nid in added_nodes:
            row = session.store.get_node(nid)
            if row:
                event_bus.publish(
                    session.project_id, {"type": "node.added", "node": _node_payload(row)}
                )
        for nid in changed_nodes:
            row = session.store.get_node(nid)
            if row:
                event_bus.publish(
                    session.project_id, {"type": "node.changed", "id": nid, "node": _node_payload(row)}
                )

        # Edges: emit ADDED set; let client re-fetch on dropped edges via resync if needed.
        # For simplicity, send the file's current edge set.
        current_edges = session.store.get_edges_by_path(path_str)
        for e in current_edges:
            if e["id"] not in prior_edges:
                event_bus.publish(
                    session.project_id, {"type": "edge.added", "edge": _edge_payload(e)}
                )
        new_edge_ids = {e["id"] for e in current_edges}
        for removed_eid in prior_edges - new_edge_ids:
            event_bus.publish(
                session.project_id, {"type": "edge.removed", "id": removed_eid}
            )


def _node_payload(row: dict) -> dict:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "name": row["name"],
        "qualname": row.get("qualname"),
        "path": row["path"],
        "parentId": row.get("parent_id"),
        "lineStart": row.get("line_start"),
        "lineEnd": row.get("line_end"),
        "contentHash": row.get("content_hash"),
        "meta": row.get("meta") or {},
    }


def _edge_payload(row: dict) -> dict:
    return {
        "id": row["id"],
        "sourceId": row["source_id"],
        "targetId": row["target_id"],
        "kind": row["kind"],
        "confidence": row.get("confidence", 1.0),
        "meta": row.get("meta") or {},
    }
