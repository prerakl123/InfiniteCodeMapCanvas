from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .migrations import apply_migrations


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    if "meta" in d and d["meta"] is not None:
        d["meta"] = json.loads(d["meta"])
    else:
        d["meta"] = {}
    return d


class Store:
    def __init__(self, db_path: Path) -> None:
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA foreign_keys = ON")
        apply_migrations(self._conn)

    def close(self) -> None:
        self._conn.close()

    def upsert_node(self, node: dict) -> None:
        """Insert or update a node WITHOUT cascading deletes to its edges.

        SQLite's INSERT OR REPLACE deletes the conflicting row before inserting,
        and ON DELETE CASCADE on the edges FK then wipes every edge touching
        the node. To keep edges intact, use ON CONFLICT DO UPDATE.
        """
        meta = node.get("meta")
        meta_json = json.dumps(meta) if meta is not None else None
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO nodes
                  (id, kind, name, qualname, path, parent_id, line_start, line_end, content_hash, meta)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  kind = excluded.kind,
                  name = excluded.name,
                  qualname = excluded.qualname,
                  path = excluded.path,
                  parent_id = excluded.parent_id,
                  line_start = excluded.line_start,
                  line_end = excluded.line_end,
                  content_hash = excluded.content_hash,
                  meta = excluded.meta
                """,
                (
                    node["id"],
                    node["kind"],
                    node["name"],
                    node.get("qualname"),
                    node["path"],
                    node.get("parent_id"),
                    node.get("line_start"),
                    node.get("line_end"),
                    node.get("content_hash"),
                    meta_json,
                ),
            )

    def update_node_meta(self, node_id: str, meta_patch: dict) -> None:
        """Merge `meta_patch` into the existing meta of a node. UPDATE only."""
        with self._conn:
            row = self._conn.execute(
                "SELECT meta FROM nodes WHERE id = ?", (node_id,)
            ).fetchone()
            if row is None:
                return
            existing = json.loads(row["meta"]) if row["meta"] else {}
            existing.update(meta_patch)
            self._conn.execute(
                "UPDATE nodes SET meta = ? WHERE id = ?",
                (json.dumps(existing), node_id),
            )

    def upsert_edge(self, edge: dict) -> None:
        meta = edge.get("meta")
        meta_json = json.dumps(meta) if meta is not None else None
        with self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO edges
                  (id, source_id, target_id, kind, confidence, meta)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    edge["id"],
                    edge["source_id"],
                    edge["target_id"],
                    edge["kind"],
                    edge.get("confidence", 1.0),
                    meta_json,
                ),
            )

    def delete_node_cascade(self, node_id: str) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))

    def bulk_replace_file(self, file_path: str, nodes: list[dict], edges: list[dict]) -> None:
        """Atomically replace all nodes/edges for a file path.

        Uses ON CONFLICT DO UPDATE for the per-node upserts so that we don't
        cascade-delete edges referring to nodes from OTHER files (e.g. a class
        in this file inheriting from an in-project base; we keep the inheriting
        edge).
        """
        with self._conn:
            # Delete only the rows that belong to this file. The CASCADE will
            # remove edges where source/target lived in this file — that is
            # intended; we'll rewrite them.
            self._conn.execute("DELETE FROM nodes WHERE path = ?", (file_path,))
            for node in nodes:
                meta = node.get("meta")
                meta_json = json.dumps(meta) if meta is not None else None
                self._conn.execute(
                    """
                    INSERT INTO nodes
                      (id, kind, name, qualname, path, parent_id, line_start, line_end, content_hash, meta)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                      kind = excluded.kind,
                      name = excluded.name,
                      qualname = excluded.qualname,
                      path = excluded.path,
                      parent_id = excluded.parent_id,
                      line_start = excluded.line_start,
                      line_end = excluded.line_end,
                      content_hash = excluded.content_hash,
                      meta = excluded.meta
                    """,
                    (
                        node["id"],
                        node["kind"],
                        node["name"],
                        node.get("qualname"),
                        node["path"],
                        node.get("parent_id"),
                        node.get("line_start"),
                        node.get("line_end"),
                        node.get("content_hash"),
                        meta_json,
                    ),
                )
            for edge in edges:
                meta = edge.get("meta")
                meta_json = json.dumps(meta) if meta is not None else None
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO edges
                      (id, source_id, target_id, kind, confidence, meta)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        edge["id"],
                        edge["source_id"],
                        edge["target_id"],
                        edge["kind"],
                        edge.get("confidence", 1.0),
                        meta_json,
                    ),
                )

    def get_node(self, node_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()
        return _row_to_dict(row) if row else None

    def get_children(self, parent_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM nodes WHERE parent_id = ?", (parent_id,)
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_root_nodes(self, project_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM nodes WHERE parent_id IS NULL AND json_extract(meta, '$.project_id') = ?",
            (project_id,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_edges_for_nodes(self, node_ids: list[str]) -> list[dict]:
        if not node_ids:
            return []
        placeholders = ",".join("?" * len(node_ids))
        rows = self._conn.execute(
            f"SELECT * FROM edges WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})",
            node_ids + node_ids,
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_edges_among(self, node_ids: list[str]) -> list[dict]:
        """Edges whose source AND target are both in node_ids."""
        if not node_ids:
            return []
        placeholders = ",".join("?" * len(node_ids))
        rows = self._conn.execute(
            f"SELECT * FROM edges WHERE source_id IN ({placeholders}) AND target_id IN ({placeholders})",
            node_ids + node_ids,
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_edges_by_path(self, path: str) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT e.* FROM edges e
            JOIN nodes n ON (n.id = e.source_id OR n.id = e.target_id)
            WHERE n.path = ?
            """,
            (path,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_importers_of(self, imported_path: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT importer_path FROM import_reverse WHERE imported_path = ?",
            (imported_path,),
        ).fetchall()
        return [r["importer_path"] for r in rows]

    def get_nodes_by_path(self, path: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM nodes WHERE path = ?", (path,)
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def upsert_file_record(
        self,
        path: str,
        content_hash: str,
        mtime_ns: int,
        size: int,
        parse_error: str | None = None,
    ) -> None:
        parsed_at = datetime.now(timezone.utc).isoformat()
        with self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO files (path, content_hash, mtime_ns, size, parsed_at, parse_error)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (path, content_hash, mtime_ns, size, parsed_at, parse_error),
            )

    def get_file_record(self, path: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM files WHERE path = ?", (path,)
        ).fetchone()
        return dict(row) if row else None

    def set_meta(self, key: str, value) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                (key, json.dumps(value)),
            )

    def get_meta(self, key: str):
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        if not row:
            return None
        raw = row[0]
        return raw if isinstance(raw, (int, float)) else json.loads(raw)

    def count_nodes_by_kind(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT kind, COUNT(*) as cnt FROM nodes GROUP BY kind"
        ).fetchall()
        return {r["kind"]: r["cnt"] for r in rows}

    def count_files_with_errors(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM files WHERE parse_error IS NOT NULL"
        ).fetchone()
        return row["cnt"] if row else 0

    def get_last_sync(self) -> str | None:
        return self.get_meta("last_full_sync_at")
