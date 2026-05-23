from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ParsedNode:
    id: str
    kind: str
    name: str
    qualname: str | None
    path: str
    parent_id: str | None
    line_start: int | None = None
    line_end: int | None = None
    content_hash: str | None = None
    meta: dict = field(default_factory=dict)


@dataclass
class ParsedEdge:
    id: str
    source_id: str
    target_id: str
    kind: str
    confidence: float = 1.0
    meta: dict = field(default_factory=dict)


@dataclass
class PendingEdge:
    """An edge whose target cannot be resolved during single-file parse.

    Resolved by the graph_builder once a full qualname -> node_id map exists.
    For imports of external modules, target_qualname is the dotted module name.
    """

    source_id: str
    kind: str
    target_qualname: str
    confidence: float = 1.0
    meta: dict = field(default_factory=dict)
    # When non-None, treat unresolved target as external module with this top-level name.
    external_top_level: str | None = None
    # File path of the source — used by resolver to look up per-file name aliases.
    source_path: str | None = None
    # Module qualname of the source file — used for same-file lookups.
    source_module: str | None = None


@dataclass
class CallSite:
    """A `Call` AST occurrence inside a function/method body.

    Recorded during AST parse, resolved later by jedi. `line` and `col` are
    1-based and 0-based respectively, matching jedi's API.
    """

    source_id: str  # node_id of the containing function/method
    line: int
    col: int
    callee_repr: str


@dataclass
class ParseResult:
    path: str
    file_node: ParsedNode
    nodes: list[ParsedNode] = field(default_factory=list)
    edges: list[ParsedEdge] = field(default_factory=list)
    pending_edges: list[PendingEdge] = field(default_factory=list)
    imported_modules: list[str] = field(default_factory=list)
    call_sites: list[CallSite] = field(default_factory=list)
    # name-in-scope -> fully qualified dotted name (e.g. {"BaseModel": "pydantic.BaseModel"})
    name_aliases: dict[str, str] = field(default_factory=dict)
    parse_error: str | None = None


class LanguageParser(ABC):
    @abstractmethod
    def parse(self, file_bytes: bytes, file_path: Path, project_root: Path) -> ParseResult:
        """Parse a single file. Must not raise on syntax errors — instead set parse_error."""
        ...
