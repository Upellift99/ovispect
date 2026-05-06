"""Entry point for ``python -m ovispect``."""

from __future__ import annotations

import uvicorn

from ovispect.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "ovispect.app:create_app",
        host=settings.bind_host,
        port=settings.bind_port,
        log_level=settings.log_level.lower(),
        access_log=False,
        factory=True,
    )


if __name__ == "__main__":
    main()
