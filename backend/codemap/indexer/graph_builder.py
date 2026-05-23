from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .ids import make_edge_id, make_node_id
from .parser_base import ParsedEdge, ParsedNode, ParseResult, PendingEdge
from ..storage.store import Store

EXTERNAL_ROOT_QUALNAME = "__codemap_external__"


@dataclass
class BuildContext:
    project_id: str
    project_root: Path


def _external_root_id() -> str:
    return make_node_id("__codemap_external__", EXTERNAL_ROOT_QUALNAME)


def _external_module_id(top_level: str) -> str:
    return make_node_id("__codemap_external__", f"{EXTERNAL_ROOT_QUALNAME}.{top_level}")


def ensure_external_root(store: Store, project_id: str) -> str:
    root_id = _external_root_id()
    if store.get_node(root_id) is None:
        store.upsert_node(
            {
                "id": root_id,
                "kind": "directory",
                "name": "external",
                "qualname": EXTERNAL_ROOT_QUALNAME,
                "path": "__codemap_external__",
                "parent_id": None,
                "meta": {
                    "project_id": project_id,
                    "synthetic": True,
                    "child_counts": {},
                },
            }
        )
    return root_id


def ensure_external_module(
    store: Store,
    top_level: str,
    project_id: str,
    cache: dict[str, str],
) -> str:
    if top_level in cache:
        return cache[top_level]
    root_id = ensure_external_root(store, project_id)
    mod_id = _external_module_id(top_level)
    if store.get_node(mod_id) is None:
        store.upsert_node(
            {
                "id": mod_id,
                "kind": "external_module",
                "name": top_level,
                "qualname": top_level,
                "path": f"__codemap_external__/{top_level}",
                "parent_id": root_id,
                "meta": {
                    "top_level": top_level,
                    "synthetic": True,
                    "imported_as": [],
                },
            }
        )
    cache[top_level] = mod_id
    return mod_id


def _resolve_via_aliases(
    p: PendingEdge,
    qmap: dict[str, str],
    file_aliases: dict[str, dict[str, str]],
    ext_top_level: str | None,
    meta: dict,
) -> tuple[str | None, str | None]:
    """Try to resolve a bare-name pending edge using the source file's import scope."""
    if not p.source_path:
        return None, ext_top_level
    aliases = file_aliases.get(p.source_path) or {}
    name = p.target_qualname
    head, _, tail = name.partition(".")
    qualified = aliases.get(head)
    if qualified is None:
        return None, ext_top_level
    full = f"{qualified}.{tail}" if tail else qualified
    target_id = qmap.get(full)
    if target_id is None:
        # Try the head module (e.g. `pydantic` for `pydantic.BaseModel`).
        target_id = qmap.get(qualified)
    if target_id is not None:
        meta["resolved_via"] = "alias"
        meta["alias_to"] = full
        return target_id, ext_top_level
    # No in-project match. Promote to external module if it looks external.
    top = qualified.split(".")[0]
    if top:
        meta["resolved_via"] = "external_alias"
        return None, top
    return None, ext_top_level


def build_qualname_map(
    parse_results: list[ParseResult],
) -> dict[str, str]:
    """Build qualname -> node_id map across all parsed files (in-project).

    For files, qualname is the module dotted path; this lets `imports` resolve to
    the file node. For classes/functions/methods, qualname is the symbol qualname.
    """
    qmap: dict[str, str] = {}
    for pr in parse_results:
        if pr.file_node.qualname:
            qmap[pr.file_node.qualname] = pr.file_node.id
        for node in pr.nodes:
            if node.qualname:
                # First wins to avoid silent overwrite from duplicate qualnames.
                qmap.setdefault(node.qualname, node.id)
    return qmap


def resolve_pending_edges(
    pending: list[PendingEdge],
    qmap: dict[str, str],
    store: Store,
    project_id: str,
    ext_cache: dict[str, str],
    file_aliases: dict[str, dict[str, str]] | None = None,
) -> tuple[list[ParsedEdge], list[tuple[str, str]]]:
    """Returns (resolved_edges, import_reverse_pairs).

    `file_aliases` is `{source_file_path: {local_name: fully_qualified_name}}` —
    used to resolve bare names like `BaseModel` to `pydantic.BaseModel` via the
    importing file's scope.
    """
    resolved: list[ParsedEdge] = []
    import_reverse: list[tuple[str, str]] = []

    for p in pending:
        target_id: str | None = qmap.get(p.target_qualname)
        confidence = p.confidence
        meta = dict(p.meta)
        ext_top_level = p.external_top_level

        if target_id is None and p.kind == "imports":
            fallback = meta.get("fallback_qualname")
            if isinstance(fallback, str):
                target_id = qmap.get(fallback)

        # For inherits/decorates: try resolving bare names via per-file alias map.
        if target_id is None and p.kind in ("inherits", "decorates"):
            target_id, ext_top_level = _resolve_via_aliases(
                p, qmap, file_aliases or {}, ext_top_level, meta
            )

        # Same-file lookup: e.g. `class B(A)` where A is defined in the same module.
        if target_id is None and p.source_module:
            same_file_qn = f"{p.source_module}.{p.target_qualname}"
            target_id = qmap.get(same_file_qn)
            if target_id:
                meta["resolved_via"] = "same_module"

        if target_id is None and ext_top_level:
            target_id = ensure_external_module(
                store, ext_top_level, project_id, ext_cache
            )
            confidence = min(confidence, 0.9)
            meta["external"] = True
        if target_id is None:
            # cannot resolve; skip the edge
            continue

        edge = ParsedEdge(
            id=make_edge_id(p.source_id, target_id, p.kind),
            source_id=p.source_id,
            target_id=target_id,
            kind=p.kind,
            confidence=confidence,
            meta=meta,
        )
        resolved.append(edge)

        if p.kind == "imports":
            # source is a file; target may be a file or symbol within a file.
            target_node = store.get_node(target_id)
            if target_node and target_node.get("kind") in ("file", "class", "function", "method"):
                target_path = target_node["path"]
                # importer path = source_id's file path. We need to look that up.
                source_node = store.get_node(p.source_id)
                if source_node:
                    import_reverse.append((target_path, source_node["path"]))

    return resolved, import_reverse


def write_parse_result(
    store: Store,
    pr: ParseResult,
    file_parent_id: str | None,
    file_mtime_ns: int,
    file_size: int,
) -> None:
    """Persist a single file's parse result.

    Removes any prior nodes for this path then writes file_node + child nodes.
    """
    # Patch file parent_id
    pr.file_node.parent_id = file_parent_id

    nodes_payload: list[dict] = []
    nodes_payload.append(_to_node_dict(pr.file_node))
    for node in pr.nodes:
        nodes_payload.append(_to_node_dict(node))

    edges_payload: list[dict] = [
        {
            "id": e.id,
            "source_id": e.source_id,
            "target_id": e.target_id,
            "kind": e.kind,
            "confidence": e.confidence,
            "meta": e.meta,
        }
        for e in pr.edges
    ]

    store.bulk_replace_file(pr.path, nodes_payload, edges_payload)
    store.upsert_file_record(
        path=pr.path,
        content_hash=pr.file_node.content_hash or "",
        mtime_ns=file_mtime_ns,
        size=file_size,
        parse_error=pr.parse_error,
    )


def _to_node_dict(n: ParsedNode) -> dict:
    return {
        "id": n.id,
        "kind": n.kind,
        "name": n.name,
        "qualname": n.qualname,
        "path": n.path,
        "parent_id": n.parent_id,
        "line_start": n.line_start,
        "line_end": n.line_end,
        "content_hash": n.content_hash,
        "meta": n.meta,
    }


def write_resolved_edges(store: Store, edges: list[ParsedEdge]) -> None:
    for e in edges:
        store.upsert_edge(
            {
                "id": e.id,
                "source_id": e.source_id,
                "target_id": e.target_id,
                "kind": e.kind,
                "confidence": e.confidence,
                "meta": e.meta,
            }
        )


def record_import_reverse(store: Store, pairs: list[tuple[str, str]]) -> None:
    if not pairs:
        return
    with store._conn:
        for imported_path, importer_path in pairs:
            store._conn.execute(
                "INSERT OR REPLACE INTO import_reverse (imported_path, importer_path) VALUES (?, ?)",
                (imported_path, importer_path),
            )
