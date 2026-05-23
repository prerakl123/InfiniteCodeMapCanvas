from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .session import ProjectSession


@dataclass
class ProjectStats:
    python_version: str = "unknown"
    venv_path: str | None = None
    package_manager: str = "unknown"
    dependencies: list[str] = field(default_factory=list)
    file_counts: dict[str, int] = field(default_factory=dict)
    loc_total: int = 0
    test_framework: str = "unknown"
    entry_points: list[str] = field(default_factory=list)
    last_sync_at: str | None = None
    indexed_file_count: int = 0
    parse_error_count: int = 0
    node_counts: dict[str, int] = field(default_factory=dict)


def _sniff_python_version(root: Path) -> str:
    pv_file = root / ".python-version"
    if pv_file.is_file():
        try:
            return pv_file.read_text(encoding="utf-8").strip()
        except OSError:
            pass

    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            rp = data.get("project", {}).get("requires-python")
            if rp:
                return rp
        except (OSError, tomllib.TOMLDecodeError):
            pass

    for cfg in root.rglob("pyvenv.cfg"):
        try:
            for line in cfg.read_text(encoding="utf-8").splitlines():
                if line.startswith("version"):
                    _, _, v = line.partition("=")
                    return v.strip()
        except OSError:
            pass

    return "unknown"


def _sniff_venv(root: Path) -> str | None:
    for cfg in root.rglob("pyvenv.cfg"):
        return str(cfg.parent)
    return None


def _sniff_package_manager(root: Path) -> str:
    if (root / "uv.lock").is_file():
        return "uv"
    if (root / "poetry.lock").is_file():
        return "poetry"
    if (root / "Pipfile.lock").is_file():
        return "pipenv"
    if (root / "requirements.txt").is_file():
        return "pip-tools"
    return "unknown"


def _sniff_dependencies(root: Path) -> list[str]:
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            deps = data.get("project", {}).get("dependencies")
            if isinstance(deps, list):
                return deps
        except (OSError, tomllib.TOMLDecodeError):
            pass
    return []


def _sniff_test_framework(root: Path) -> str:
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            tool = data.get("tool", {})
            for key in tool:
                if key.startswith("pytest"):
                    return "pytest"
        except (OSError, tomllib.TOMLDecodeError):
            pass

    if (root / "tests").is_dir():
        return "pytest"

    return "unknown"


def _sniff_entry_points(root: Path) -> list[str]:
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            scripts = data.get("project", {}).get("scripts", {})
            if isinstance(scripts, dict):
                return list(scripts.keys())
        except (OSError, tomllib.TOMLDecodeError):
            pass
    return []


def compute_stats(session: ProjectSession) -> ProjectStats:
    root = session.project_root
    store = session.store

    python_version = _sniff_python_version(root)
    venv_path = _sniff_venv(root)
    package_manager = _sniff_package_manager(root)
    dependencies = _sniff_dependencies(root)
    test_framework = _sniff_test_framework(root)
    entry_points = _sniff_entry_points(root)

    node_counts = store.count_nodes_by_kind()
    last_sync_at = store.get_last_sync()
    parse_error_count = store.count_files_with_errors()

    file_nodes = store._conn.execute(
        "SELECT path, meta FROM nodes WHERE kind = 'file'"
    ).fetchall()

    file_counts: dict[str, int] = {}
    loc_total = 0
    for row in file_nodes:
        ext = Path(row["path"]).suffix or "(no ext)"
        file_counts[ext] = file_counts.get(ext, 0) + 1
        try:
            meta = json.loads(row["meta"]) if row["meta"] else {}
            loc_total += meta.get("loc", 0)
        except Exception:
            pass

    indexed_file_count = sum(
        1 for row in store._conn.execute("SELECT 1 FROM files").fetchall()
    )

    return ProjectStats(
        python_version=python_version,
        venv_path=venv_path,
        package_manager=package_manager,
        dependencies=dependencies,
        file_counts=file_counts,
        loc_total=loc_total,
        test_framework=test_framework,
        entry_points=entry_points,
        last_sync_at=last_sync_at,
        indexed_file_count=indexed_file_count,
        parse_error_count=parse_error_count,
        node_counts=node_counts,
    )
