"""Fixtures for the Playwright end-to-end suite.

The :func:`live_server` fixture boots a real uvicorn server on a free
port in a background thread, with :func:`ovispect.app.fetch_status`
stubbed so the dashboard renders without a real OpenVPN backend. Every
test in this directory is auto-marked ``e2e`` and skipped by default —
see ``pyproject.toml``.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
import uvicorn

from ovispect import app as app_module
from ovispect.config import Settings
from ovispect.ovpn import StatusSnapshot


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Auto-mark every test under ``tests/e2e`` with ``@pytest.mark.e2e``."""
    for item in items:
        if "tests/e2e/" in item.nodeid.replace("\\", "/"):
            item.add_marker(pytest.mark.e2e)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _empty_snapshot(*_args: object, **_kwargs: object) -> StatusSnapshot:
    return StatusSnapshot(fetched_at=datetime.now(tz=UTC), clients=[])


class _ThreadedServer(uvicorn.Server):
    """uvicorn.Server variant that skips signal handlers (non-main thread)."""

    def install_signal_handlers(self) -> None:  # pragma: no cover - trivial override
        return None


@pytest.fixture(scope="session")
def live_server() -> Iterator[str]:
    """Boot uvicorn in a daemon thread and yield its base URL."""
    settings = Settings(
        openvpn_host="127.0.0.1",
        openvpn_port=1,  # nothing listens here; fetch_status is stubbed anyway
        site_name="E2E",
        timezone="UTC",
        management_timeout_seconds=1,
    )
    application = app_module.create_app(settings)

    original_fetch = app_module.fetch_status
    app_module.fetch_status = _empty_snapshot  # type: ignore[assignment]

    port = _free_port()
    config = uvicorn.Config(
        application,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        loop="asyncio",
        # ovispect doesn't use websockets, and importing the default ws backend
        # raises a DeprecationWarning that pyproject.toml's filterwarnings=error
        # promotes to a hard failure inside the server thread.
        ws="none",
    )
    server = _ThreadedServer(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 5.0
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    if not server.started:
        server.should_exit = True
        thread.join(timeout=2)
        app_module.fetch_status = original_fetch  # type: ignore[assignment]
        pytest.fail("uvicorn did not start within 5s")

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        app_module.fetch_status = original_fetch  # type: ignore[assignment]
