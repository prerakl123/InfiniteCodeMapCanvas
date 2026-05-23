from __future__ import annotations

import ast
import hashlib
import tokenize
from io import BytesIO
from pathlib import Path

from .ids import make_node_id
from .parser_base import (
    CallSite,
    LanguageParser,
    ParsedEdge,
    ParsedNode,
    ParseResult,
    PendingEdge,
)


def _call_callee_repr(call: ast.Call) -> str:
    try:
        return ast.unparse(call.func)
    except Exception:
        return "?"


def _docstring_excerpt(node: ast.AST, limit: int = 120) -> str | None:
    try:
        doc = ast.get_docstring(node)  # type: ignore[arg-type]
    except TypeError:
        return None
    if not doc:
        return None
    doc = doc.strip().replace("\n", " ")
    return doc[: limit - 1] + "…" if len(doc) > limit else doc


def _decorator_name(dec: ast.expr) -> str:
    if isinstance(dec, ast.Name):
        return dec.id
    if isinstance(dec, ast.Attribute):
        parts: list[str] = []
        cur: ast.AST = dec
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        return ".".join(reversed(parts))
    if isinstance(dec, ast.Call):
        return _decorator_name(dec.func)
    return ast.unparse(dec) if hasattr(ast, "unparse") else "?"


def _base_name(base: ast.expr) -> str:
    if isinstance(base, ast.Name):
        return base.id
    if isinstance(base, ast.Attribute):
        parts: list[str] = []
        cur: ast.AST = base
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        return ".".join(reversed(parts))
    try:
        return ast.unparse(base)
    except Exception:
        return "?"


def _compute_loc(source: bytes) -> tuple[int, int, int, int]:
    """Return (loc_total, loc_code, loc_blank, loc_comment)."""
    try:
        text = source.decode("utf-8", errors="replace")
    except Exception:
        return (0, 0, 0, 0)

    total = text.count("\n") + (0 if text.endswith("\n") or not text else 1)
    blank = sum(1 for line in text.splitlines() if not line.strip())

    comment = 0
    try:
        for tok in tokenize.tokenize(BytesIO(source).readline):
            if tok.type == tokenize.COMMENT:
                comment += 1
    except (tokenize.TokenizeError, SyntaxError, IndentationError):
        pass

    code = total - blank - comment
    if code < 0:
        code = 0
    return (total, code, blank, comment)


def _module_qualname(file_path: Path, project_root: Path) -> str:
    """Compute a Python-style dotted module name from a file path.

    Drops .py extension; uses '__init__' segments are stripped (package name).
    Files outside project root return empty string.
    """
    try:
        rel = file_path.resolve().relative_to(project_root.resolve())
    except ValueError:
        return ""
    parts = list(rel.parts)
    if not parts:
        return ""
    last = parts[-1]
    if last.endswith(".py"):
        last = last[:-3]
    parts[-1] = last
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _resolve_relative_import(
    module: str | None, level: int, file_module: str
) -> str:
    """Resolve `from .x.y import z` (level=N, module=str|None) against the file's module path."""
    if level == 0:
        return module or ""
    parts = file_module.split(".") if file_module else []
    # `level` dots go up `level - 1` packages from the file's package
    if parts:
        # drop the file's own name to get its package
        base = parts[:-1]
    else:
        base = []
    if level - 1 > 0:
        base = base[: max(0, len(base) - (level - 1))]
    if module:
        return ".".join(base + module.split("."))
    return ".".join(base)


class _SymbolVisitor(ast.NodeVisitor):
    def __init__(
        self,
        file_path: str,
        file_id: str,
        file_module: str,
        project_root: Path,
        file_source_bytes: bytes,
    ) -> None:
        self.file_path = file_path
        self.file_id = file_id
        self.file_module = file_module
        self.project_root = project_root
        self.file_source_bytes = file_source_bytes
        self.nodes: list[ParsedNode] = []
        self.edges: list[ParsedEdge] = []
        self.pending: list[PendingEdge] = []
        self.imported_modules: list[str] = []
        self.call_sites: list[CallSite] = []
        self.name_aliases: dict[str, str] = {}
        # Stack of (qualname, node_id, kind)
        self._stack: list[tuple[str, str, str]] = []

    def _current_parent(self) -> tuple[str | None, str]:
        """Return (parent_id, parent_qualname_prefix)."""
        if self._stack:
            qn, nid, _ = self._stack[-1]
            return nid, qn
        return self.file_id, self.file_module

    def _make_signature_hash(self, node: ast.AST) -> str:
        try:
            sig = ast.dump(node, annotate_fields=False)
        except Exception:
            sig = repr(node)
        return hashlib.blake2b(sig.encode("utf-8"), digest_size=8).hexdigest()

    # ----- classes -----

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        parent_id, parent_qn = self._current_parent()
        qualname = f"{parent_qn}.{node.name}" if parent_qn else node.name
        node_id = make_node_id(self.file_path, qualname)

        bases = [_base_name(b) for b in node.bases]
        decorators = [_decorator_name(d) for d in node.decorator_list]
        method_count = sum(
            1 for c in node.body if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef))
        )

        parsed = ParsedNode(
            id=node_id,
            kind="class",
            name=node.name,
            qualname=qualname,
            path=self.file_path,
            parent_id=parent_id,
            line_start=node.lineno,
            line_end=getattr(node, "end_lineno", node.lineno),
            content_hash=self._make_signature_hash(node),
            meta={
                "bases": bases,
                "decorators": decorators,
                "method_count": method_count,
                "docstring_excerpt": _docstring_excerpt(node),
            },
        )
        self.nodes.append(parsed)

        # inherits edges - resolved later via qualname
        for base_name in bases:
            self.pending.append(
                PendingEdge(
                    source_id=node_id,
                    kind="inherits",
                    target_qualname=base_name,
                    confidence=1.0,
                    meta={"base_name": base_name},
                    source_path=self.file_path,
                    source_module=self.file_module,
                )
            )

        # decorates edges
        for dec_name in decorators:
            self.pending.append(
                PendingEdge(
                    source_id=node_id,
                    kind="decorates",
                    target_qualname=dec_name,
                    confidence=0.7,
                    meta={"decorator_name": dec_name, "target": "class"},
                    source_path=self.file_path,
                    source_module=self.file_module,
                )
            )

        self._stack.append((qualname, node_id, "class"))
        for child in node.body:
            self.visit(child)
        self._stack.pop()

    # ----- functions / methods -----

    def _visit_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        is_async: bool,
    ) -> None:
        parent_id, parent_qn = self._current_parent()
        in_class = bool(self._stack) and self._stack[-1][2] == "class"
        kind = "method" if in_class else "function"
        qualname = f"{parent_qn}.{node.name}" if parent_qn else node.name
        node_id = make_node_id(self.file_path, qualname)

        is_generator = any(
            isinstance(n, (ast.Yield, ast.YieldFrom)) for n in ast.walk(node)
        )
        param_count = (
            len(node.args.args)
            + len(node.args.kwonlyargs)
            + (1 if node.args.vararg else 0)
            + (1 if node.args.kwarg else 0)
            + len(node.args.posonlyargs)
        )
        decorators = [_decorator_name(d) for d in node.decorator_list]
        calls_out_count = sum(1 for n in ast.walk(node) if isinstance(n, ast.Call))

        parsed = ParsedNode(
            id=node_id,
            kind=kind,
            name=node.name,
            qualname=qualname,
            path=self.file_path,
            parent_id=parent_id,
            line_start=node.lineno,
            line_end=getattr(node, "end_lineno", node.lineno),
            content_hash=self._make_signature_hash(node),
            meta={
                "is_async": is_async,
                "is_generator": is_generator,
                "param_count": param_count,
                "decorators": decorators,
                "docstring_excerpt": _docstring_excerpt(node),
                "calls_out_count": calls_out_count,
            },
        )
        self.nodes.append(parsed)

        for dec_name in decorators:
            self.pending.append(
                PendingEdge(
                    source_id=node_id,
                    kind="decorates",
                    target_qualname=dec_name,
                    confidence=0.7,
                    meta={"decorator_name": dec_name, "target": kind},
                    source_path=self.file_path,
                    source_module=self.file_module,
                )
            )

        # Record call sites located inside this function body for jedi resolution.
        for call in self._collect_calls(node):
            self.call_sites.append(
                CallSite(
                    source_id=node_id,
                    line=call.lineno,
                    col=call.col_offset,
                    callee_repr=_call_callee_repr(call),
                )
            )

        self._stack.append((qualname, node_id, kind))
        for child in node.body:
            self.visit(child)
        self._stack.pop()

    def _collect_calls(
        self, fn: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> list[ast.Call]:
        """Collect ast.Call nodes inside fn.body but NOT inside nested defs.

        Calls inside nested functions belong to those nested function nodes
        (handled when they are visited).
        """
        results: list[ast.Call] = []
        for statement in fn.body:
            for descendant in ast.walk(statement):
                if isinstance(descendant, ast.Call):
                    results.append(descendant)
                elif isinstance(
                    descendant, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ):
                    # Skip walking into nested defs.
                    pass
        # The simple ast.walk above does descend into nested defs because
        # ast.walk doesn't know about scoping. Filter calls that live inside
        # nested defs by walking explicitly.
        filtered: list[ast.Call] = []
        nested_def_ranges: list[tuple[int, int]] = []
        for n in ast.walk(fn):
            if n is fn:
                continue
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                end = getattr(n, "end_lineno", n.lineno)
                nested_def_ranges.append((n.lineno, end))

        for c in results:
            in_nested = any(start <= c.lineno <= end for start, end in nested_def_ranges)
            if not in_nested:
                filtered.append(c)
        return filtered

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node, is_async=True)

    # ----- imports -----

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            module = alias.name
            self.imported_modules.append(module)
            local_name = alias.asname or module.split(".")[0]
            self.name_aliases[local_name] = module
            self.pending.append(
                PendingEdge(
                    source_id=self.file_id,
                    kind="imports",
                    target_qualname=module,
                    confidence=1.0,
                    meta={"import_alias": alias.asname} if alias.asname else {},
                    external_top_level=module.split(".")[0],
                    source_path=self.file_path,
                    source_module=self.file_module,
                )
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module_name = _resolve_relative_import(
            node.module, node.level, self.file_module
        )
        if not module_name:
            return
        self.imported_modules.append(module_name)
        # For each imported name, register two-stage lookup:
        # 1. Try to resolve module_name.name (a symbol)
        # 2. Fall back to module_name itself (the module).
        # Edge target is the module by default; symbol-level link is best-effort.
        for alias in node.names:
            sub = alias.name
            if sub == "*":
                self.pending.append(
                    PendingEdge(
                        source_id=self.file_id,
                        kind="imports",
                        target_qualname=module_name,
                        confidence=1.0,
                        meta={"import_from": True, "wildcard": True},
                        external_top_level=module_name.split(".")[0],
                        source_path=self.file_path,
                        source_module=self.file_module,
                    )
                )
                continue
            full = f"{module_name}.{sub}"
            local_name = alias.asname or sub
            self.name_aliases[local_name] = full
            self.pending.append(
                PendingEdge(
                    source_id=self.file_id,
                    kind="imports",
                    target_qualname=full,
                    confidence=1.0,
                    meta={
                        "import_from": True,
                        "module": module_name,
                        "name": sub,
                        "import_alias": alias.asname,
                        "fallback_qualname": module_name,
                    },
                    external_top_level=module_name.split(".")[0],
                    source_path=self.file_path,
                    source_module=self.file_module,
                )
            )


class PythonParser(LanguageParser):
    def parse(
        self, file_bytes: bytes, file_path: Path, project_root: Path
    ) -> ParseResult:
        path_str = str(file_path)
        content_hash = hashlib.blake2b(file_bytes, digest_size=8).hexdigest()

        loc_total, loc_code, loc_blank, loc_comment = _compute_loc(file_bytes)
        file_module = _module_qualname(file_path, project_root)
        file_id = make_node_id(path_str, "")

        # Parent of the file is the directory it lives in. We don't know the
        # directory's node_id from here; the caller in graph_builder will fix
        # parent_id by overwriting with the dir id stored at index time. For
        # incremental use we leave parent_id alone; storage already has the
        # file row with proper parent_id, and bulk_replace_file is called
        # by the indexer which sets parent_id explicitly elsewhere.
        file_node = ParsedNode(
            id=file_id,
            kind="file",
            name=file_path.name,
            qualname=file_module or None,
            path=path_str,
            parent_id=None,  # filled in by caller
            content_hash=content_hash,
            meta={
                "loc": loc_total,
                "loc_code": loc_code,
                "loc_blank": loc_blank,
                "loc_comment": loc_comment,
                "class_count": 0,
                "function_count": 0,
                "encoding": "utf-8",
            },
        )

        try:
            tree = ast.parse(file_bytes, filename=path_str)
        except SyntaxError as e:
            file_node.meta["parse_error"] = f"{e.msg} (line {e.lineno})"
            return ParseResult(
                path=path_str,
                file_node=file_node,
                parse_error=f"{e.msg} (line {e.lineno})",
            )
        except Exception as e:  # noqa: BLE001
            file_node.meta["parse_error"] = str(e)
            return ParseResult(
                path=path_str,
                file_node=file_node,
                parse_error=str(e),
            )

        visitor = _SymbolVisitor(
            file_path=path_str,
            file_id=file_id,
            file_module=file_module,
            project_root=project_root,
            file_source_bytes=file_bytes,
        )
        visitor.visit(tree)

        class_count = sum(1 for n in visitor.nodes if n.kind == "class")
        function_count = sum(
            1 for n in visitor.nodes if n.kind in ("function", "method")
        )
        file_node.meta["class_count"] = class_count
        file_node.meta["function_count"] = function_count

        return ParseResult(
            path=path_str,
            file_node=file_node,
            nodes=visitor.nodes,
            edges=visitor.edges,
            pending_edges=visitor.pending,
            imported_modules=list(set(visitor.imported_modules)),
            call_sites=visitor.call_sites,
            name_aliases=dict(visitor.name_aliases),
        )
