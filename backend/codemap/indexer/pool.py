from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Iterable

from .parser_base import ParseResult
from .parser_python import PythonParser


def _parse_one(args: tuple[str, str]) -> ParseResult:
    """Worker entry point. Re-instantiates parser per process (no shared state)."""
    file_path_str, project_root_str = args
    parser = PythonParser()
    path = Path(file_path_str)
    try:
        raw = path.read_bytes()
    except OSError as e:
        from .ids import make_node_id
        from .parser_base import ParsedNode

        file_id = make_node_id(str(path), "")
        return ParseResult(
            path=str(path),
            file_node=ParsedNode(
                id=file_id,
                kind="file",
                name=path.name,
                qualname=None,
                path=str(path),
                parent_id=None,
                meta={"loc": 0, "parse_error": str(e)},
            ),
            parse_error=str(e),
        )
    return parser.parse(raw, path, Path(project_root_str))


def default_workers() -> int:
    return min((os.cpu_count() or 2) - 1 or 1, 8)


def parse_files_parallel(
    files: Iterable[Path],
    project_root: Path,
    max_workers: int | None = None,
) -> list[ParseResult]:
    """Parse a batch of files using a process pool.

    For small batches (< 16 files) falls back to single-threaded parsing to
    avoid pool startup cost.
    """
    files_list = list(files)
    if not files_list:
        return []

    if len(files_list) < 16:
        parser = PythonParser()
        results: list[ParseResult] = []
        for f in files_list:
            try:
                raw = f.read_bytes()
            except OSError as e:
                from .ids import make_node_id
                from .parser_base import ParsedNode

                fid = make_node_id(str(f), "")
                results.append(
                    ParseResult(
                        path=str(f),
                        file_node=ParsedNode(
                            id=fid,
                            kind="file",
                            name=f.name,
                            qualname=None,
                            path=str(f),
                            parent_id=None,
                            meta={"loc": 0, "parse_error": str(e)},
                        ),
                        parse_error=str(e),
                    )
                )
                continue
            results.append(parser.parse(raw, f, project_root))
        return results

    workers = max_workers or default_workers()
    args = [(str(f), str(project_root)) for f in files_list]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(_parse_one, args, chunksize=8))
