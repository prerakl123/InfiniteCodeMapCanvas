from __future__ import annotations

import fnmatch
from pathlib import Path

import pathspec

_BASELINE: frozenset[str] = frozenset(
    [
        "__pycache__",
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "dist",
        "build",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        "htmlcov",
        ".idea",
        ".vscode",
    ]
)

_BASELINE_PATTERNS: tuple[str, ...] = ("*.egg-info", "*.pyc", "*.pyo")


class IgnoreMatcher:
    def __init__(
        self,
        root: Path,
        venv_dirs: frozenset[Path],
        gitignore_spec: pathspec.PathSpec | None,
        codemapignore_spec: pathspec.PathSpec | None,
    ) -> None:
        self._root = root
        self._venv_dirs = venv_dirs
        self._gitignore_spec = gitignore_spec
        self._codemapignore_spec = codemapignore_spec

    @classmethod
    def from_project(cls, root: Path) -> IgnoreMatcher:
        root = root.resolve()

        venv_dirs: set[Path] = set()
        for candidate in root.rglob("pyvenv.cfg"):
            venv_dirs.add(candidate.parent.resolve())

        gitignore_spec: pathspec.PathSpec | None = None
        gitignore_file = root / ".gitignore"
        if gitignore_file.is_file():
            try:
                lines = gitignore_file.read_text(encoding="utf-8", errors="replace").splitlines()
                gitignore_spec = pathspec.PathSpec.from_lines("gitwildmatch", lines)
            except OSError:
                pass

        codemapignore_spec: pathspec.PathSpec | None = None
        codemapignore_file = root / ".codemapignore"
        if codemapignore_file.is_file():
            try:
                lines = codemapignore_file.read_text(encoding="utf-8", errors="replace").splitlines()
                codemapignore_spec = pathspec.PathSpec.from_lines("gitwildmatch", lines)
            except OSError:
                pass

        return cls(root, frozenset(venv_dirs), gitignore_spec, codemapignore_spec)

    def matches(self, path: Path) -> bool:
        path = path.resolve()

        name = path.name
        if name in _BASELINE:
            return True
        for pat in _BASELINE_PATTERNS:
            if fnmatch.fnmatch(name, pat):
                return True

        for venv_dir in self._venv_dirs:
            try:
                path.relative_to(venv_dir)
                return True
            except ValueError:
                pass
            if path == venv_dir:
                return True

        try:
            rel = path.relative_to(self._root)
        except ValueError:
            return False

        rel_str = str(rel)

        if self._gitignore_spec and self._gitignore_spec.match_file(rel_str):
            return True

        if self._codemapignore_spec and self._codemapignore_spec.match_file(rel_str):
            return True

        return False
