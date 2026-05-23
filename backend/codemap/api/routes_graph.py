from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from ..session import registry

router = APIRouter(prefix="/api")


class NodeResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str
    kind: str
    name: str
    qualname: str | None = None
    path: str
    parent_id: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    content_hash: str | None = None
    meta: dict = {}


class EdgeResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str
    source_id: str
    target_id: str
    kind: str
    confidence: float = 1.0
    meta: dict = {}


def _node_from_dict(d: dict) -> NodeResponse:
    meta = d.get("meta")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    return NodeResponse(
        id=d["id"],
        kind=d["kind"],
        name=d["name"],
        qualname=d.get("qualname"),
        path=d["path"],
        parent_id=d.get("parent_id"),
        line_start=d.get("line_start"),
        line_end=d.get("line_end"),
        content_hash=d.get("content_hash"),
        meta=meta or {},
    )


def _edge_from_dict(d: dict) -> EdgeResponse:
    meta = d.get("meta")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    return EdgeResponse(
        id=d["id"],
        source_id=d["source_id"],
        target_id=d["target_id"],
        kind=d["kind"],
        confidence=d.get("confidence", 1.0),
        meta=meta or {},
    )


@router.get("/project/{project_id}/tree")
def get_tree(project_id: str) -> dict:
    session = registry.get(project_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown project")

    roots = session.store.get_root_nodes(project_id)
    if not roots:
        raise HTTPException(status_code=404, detail="Project not yet indexed")

    node = _node_from_dict(roots[0])
    return node.model_dump(by_alias=True)


@router.get("/graph/children/{node_id}")
def get_children(node_id: str) -> dict:
    for session in registry._sessions.values():
        node = session.store.get_node(node_id)
        if node is not None:
            children = session.store.get_children(node_id)
            child_ids = [c["id"] for c in children]
            edges = session.store.get_edges_among(child_ids + [node_id])
            return {
                "nodes": [_node_from_dict(c).model_dump(by_alias=True) for c in children],
                "edges": [_edge_from_dict(e).model_dump(by_alias=True) for e in edges],
            }

    raise HTTPException(status_code=404, detail="Node not found")


@router.get("/graph/neighbors/{node_id}")
def get_neighbors(node_id: str) -> dict:
    for session in registry._sessions.values():
        node = session.store.get_node(node_id)
        if node is not None:
            edges = session.store.get_edges_for_nodes([node_id])
            neighbor_ids: set[str] = set()
            for e in edges:
                neighbor_ids.add(e["source_id"])
                neighbor_ids.add(e["target_id"])
            neighbor_ids.discard(node_id)
            neighbors = [
                n
                for n in (session.store.get_node(nid) for nid in neighbor_ids)
                if n is not None
            ]
            return {
                "nodes": [_node_from_dict(n).model_dump(by_alias=True) for n in neighbors],
                "edges": [_edge_from_dict(e).model_dump(by_alias=True) for e in edges],
            }
    raise HTTPException(status_code=404, detail="Node not found")
