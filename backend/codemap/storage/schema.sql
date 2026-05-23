PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS nodes (
  id           TEXT PRIMARY KEY,
  kind         TEXT NOT NULL,
  name         TEXT NOT NULL,
  qualname     TEXT,
  path         TEXT NOT NULL,
  parent_id    TEXT REFERENCES nodes(id) ON DELETE CASCADE,
  line_start   INTEGER,
  line_end     INTEGER,
  content_hash TEXT,
  meta         TEXT
);
CREATE INDEX IF NOT EXISTS idx_nodes_parent   ON nodes(parent_id);
CREATE INDEX IF NOT EXISTS idx_nodes_path     ON nodes(path);
CREATE INDEX IF NOT EXISTS idx_nodes_qualname ON nodes(qualname);
CREATE INDEX IF NOT EXISTS idx_nodes_kind     ON nodes(kind);

CREATE TABLE IF NOT EXISTS edges (
  id         TEXT PRIMARY KEY,
  source_id  TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
  target_id  TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
  kind       TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 1.0,
  meta       TEXT
);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id, kind);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id, kind);
CREATE INDEX IF NOT EXISTS idx_edges_kind   ON edges(kind);

CREATE TABLE IF NOT EXISTS files (
  path         TEXT PRIMARY KEY,
  content_hash TEXT NOT NULL,
  mtime_ns     INTEGER NOT NULL,
  size         INTEGER NOT NULL,
  parsed_at    TEXT NOT NULL,
  parse_error  TEXT
);

CREATE TABLE IF NOT EXISTS import_reverse (
  imported_path TEXT NOT NULL,
  importer_path TEXT NOT NULL,
  PRIMARY KEY (imported_path, importer_path)
);
