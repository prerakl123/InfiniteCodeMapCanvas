from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .ids import make_edge_id
from .parser_base import ParsedEdge, ParseResult

if TYPE_CHECKING:
    from ..session import ProjectSession


def _get_jedi_project(session: "ProjectSession"):
    """Lazily attach a jedi.Project to the session and reuse it."""
    cache = getattr(session, "_jedi_project", None)
    if cache is not None:
        return cache

    import jedi  # imported lazily — heavy dep

    venv_path = None
    # Try to find a venv inside the project. Prefer common names.
    for candidate in ("venv", ".venv", "env"):
        c = session.project_root / candidate
        if (c / "pyvenv.cfg").is_file():
            venv_path = str(c)
            break
    if venv_path is None:
        # Fall back to any pyvenv.cfg under the root.
        for cfg in session.project_root.rglob("pyvenv.cfg"):
            venv_path = str(cfg.parent)
            break

    kwargs = {"path": str(session.project_root)}
    if venv_path:
        kwargs["environment_path"] = venv_path

    project = jedi.Project(**kwargs)
    session._jedi_project = project  # type: ignore[attr-defined]
    return project


def _bucket_call_sites_by_path(
    parse_results: list[ParseResult],
) -> dict[str, list]:
    result: dict[str, list] = {}
    for pr in parse_results:
        if not pr.call_sites:
            continue
        result.setdefault(pr.path, []).extend(pr.call_sites)
    return result


def _resolve_definition_to_qualname(definition, project_root: Path) -> str | None:
    """Map a jedi Definition to an in-project qualname (matches our qmap keys).

    Returns None if the definition does not live inside the project.
    """
    try:
        module_path = definition.module_path
    except Exception:
        return None
    if module_path is None:
        return None
    try:
        rel = Path(module_path).resolve().relative_to(project_root.resolve())
    except (ValueError, OSError):
        return None

    parts = list(rel.parts)
    if not parts:
        return None
    last = parts[-1]
    if last.endswith(".py"):
        last = last[:-3]
    parts[-1] = last
    if parts[-1] == "__init__":
        parts = parts[:-1]
    module_qn = ".".join(parts)

    try:
        full_name = definition.full_name
    except Exception:
        full_name = None

    if full_name:
        # jedi gives us `<package>.<module>.<...symbol>`. We want our qmap form,
        # which is `<module_qn>.<symbol_tail>`. Find the longest module prefix.
        fn_parts = full_name.split(".")
        # Strip leading "package" segments that match the module path. Compare
        # the module's qualname tail.
        # Heuristic: keep the last len(parts) + tail to map onto qmap.
        # qmap stores `<module_qn>` for the file itself and `<module_qn>.symbol`
        # for symbols within. So we want `<module_qn>` joined with `<symbol_tail>`.
        # We extract symbol_tail by stripping the module prefix from full_name.
        # Note: jedi's full_name uses dotted module path that may not match
        # our project module exactly (e.g. when project root != package root).
        # Fallback: try the name + line.
        # Try: take the last K parts where K = len(definition.full_name.split('.')) - depth_of(module_path_in_project)
        # Simpler: take whatever follows `parts[-1]` if present.
        if parts and parts[-1] in fn_parts:
            idx = len(fn_parts) - 1 - list(reversed(fn_parts)).index(parts[-1])
            tail = fn_parts[idx + 1 :]
            if tail:
                return f"{module_qn}.{'.'.join(tail)}"
            return module_qn
        # Fall back to a name-based guess.
        try:
            name = definition.name
            if name:
                return f"{module_qn}.{name}"
        except Exception:
            return module_qn
        return module_qn

    try:
        name = definition.name
        if name:
            return f"{module_qn}.{name}"
    except Exception:
        return None
    return None


def enrich_with_jedi(
    *,
    session: "ProjectSession",
    parse_results: list[ParseResult],
    qmap: dict[str, str],
    project_root: Path,
    timeout_per_call: float = 0.5,
) -> None:
    """Resolve call sites with jedi and write `calls` / `instantiates` edges.

    On any per-file error, skip that file and continue. Per-call errors are
    swallowed; the source function's `meta.unresolved_calls` counter is bumped.
    """
    try:
        import jedi
    except Exception:
        return

    project = _get_jedi_project(session)

    # Counter per source node for unresolved calls
    unresolved_counter: dict[str, int] = {}
    edges_to_write: list[ParsedEdge] = []

    by_path = _bucket_call_sites_by_path(parse_results)

    for path, call_sites in by_path.items():
        try:
            source = Path(path).read_bytes()
        except OSError:
            continue
        try:
            script = jedi.Script(code=source, path=path, project=project)
        except Exception:
            continue

        for cs in call_sites:
            try:
                defs = script.goto(line=cs.line, column=cs.col, follow_imports=True)
            except Exception:
                unresolved_counter[cs.source_id] = unresolved_counter.get(cs.source_id, 0) + 1
                continue

            if not defs:
                unresolved_counter[cs.source_id] = unresolved_counter.get(cs.source_id, 0) + 1
                continue

            resolved_targets: list[tuple[str, str]] = []  # (target_id, kind)
            for d in defs:
                qn = _resolve_definition_to_qualname(d, project_root)
                if qn is None:
                    continue
                target_id = qmap.get(qn)
                if target_id is None:
                    # Try one shorter form, e.g. drop trailing .__init__
                    if qn.endswith(".__init__"):
                        target_id = qmap.get(qn[: -len(".__init__")])
                if target_id is None:
                    continue
                try:
                    d_type = getattr(d, "type", None)
                except Exception:
                    d_type = None
                kind = "instantiates" if d_type == "class" else "calls"
                resolved_targets.append((target_id, kind))

            if not resolved_targets:
                unresolved_counter[cs.source_id] = unresolved_counter.get(cs.source_id, 0) + 1
                continue

            confidence = 1.0 if len(resolved_targets) == 1 else (1.0 / len(resolved_targets))
            for target_id, kind in resolved_targets:
                edges_to_write.append(
                    ParsedEdge(
                        id=make_edge_id(cs.source_id, target_id, kind),
                        source_id=cs.source_id,
                        target_id=target_id,
                        kind=kind,
                        confidence=confidence,
                        meta={
                            "call_site_line": cs.line,
                            "callee": cs.callee_repr,
                        },
                    )
                )

    # Write edges
    for edge in edges_to_write:
        session.store.upsert_edge(
            {
                "id": edge.id,
                "source_id": edge.source_id,
                "target_id": edge.target_id,
                "kind": edge.kind,
                "confidence": edge.confidence,
                "meta": edge.meta,
            }
        )

    # Update unresolved counters on source nodes — uses UPDATE so it does
    # NOT cascade-delete the edges we just inserted.
    if unresolved_counter:
        for source_id, count in unresolved_counter.items():
            session.store.update_node_meta(source_id, {"unresolved_calls": count})
