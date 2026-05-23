from __future__ import annotations

import uvicorn

from codemap.config import settings


def main() -> None:
    uvicorn.run(
        "codemap.server:app",
        host=settings.host,
        port=settings.port,
        reload=True,
        reload_dirs=["codemap"],
    )


if __name__ == "__main__":
    main()
