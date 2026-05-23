from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path


def _default_codemap_root() -> Path:
    override = os.environ.get("CODEMAP_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".codemap"


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8765
    dev_frontend_origin: str = "http://localhost:5173"
    codemap_root: Path = field(default_factory=_default_codemap_root)

    def project_codemap_dir(self, project_path: Path) -> Path:
        digest = hashlib.blake2b(str(project_path.resolve()).encode("utf-8"), digest_size=8).hexdigest()
        return self.codemap_root / digest


settings = Settings()
