from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

_SCHEMA_FILE = Path(__file__).parent / "schema.sql"


def apply_migrations(conn: sqlite3.Connection) -> None:
    schema_sql = _SCHEMA_FILE.read_text(encoding="utf-8")
    conn.executescript(schema_sql)

    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    if row is not None:
        raw = row[0]
        existing = raw if isinstance(raw, int) else json.loads(raw)
        if existing > SCHEMA_VERSION:
            raise RuntimeError("Database was created by a newer indexer version")

    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
        (json.dumps(SCHEMA_VERSION),),
    )
    conn.commit()
