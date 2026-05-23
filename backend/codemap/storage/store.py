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
        meta = node.get("meta")
        meta_json = json.dumps(meta) if meta is not None else None
        with self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO nodes
                  (id, kind, name, qualname, path, parent_id, line_start, line_end, content_hash, meta)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        with self._conn:
            self._conn.execute("DELETE FROM nodes WHERE path = ?", (file_path,))
            for node in nodes:
                meta = node.get("meta")
                meta_json = json.dumps(meta) if meta is not None else None
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO nodes
                      (id, kind, name, qualname, path, parent_id, line_start, line_end, content_hash, meta)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
