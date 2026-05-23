from __future__ import annotations

import hashlib


def make_node_id(path: str, qualname: str) -> str:
    return hashlib.blake2b((path + "\0" + qualname).encode(), digest_size=8).hexdigest()


def make_edge_id(source_id: str, target_id: str, kind: str) -> str:
    return hashlib.blake2b(
        (source_id + "\0" + target_id + "\0" + kind).encode(), digest_size=8
    ).hexdigest()
