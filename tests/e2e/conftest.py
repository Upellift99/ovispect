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
from collections.abc import Callable, Iterator
from datetime import UTC, datetime

import pytest
import uvicorn

from ovispect import app as app_module
from ovispect.config import Settings
from ovispect.ovpn import Client, StatusSnapshot


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


DRAWER_CLIENT_CN = "alice"


def _one_client_snapshot(*_args: object, **_kwargs: object) -> StatusSnapshot:
    """A snapshot with a single client, so the table has a row to click."""
    return StatusSnapshot(
        fetched_at=datetime.now(tz=UTC),
        clients=[
            Client(
                common_name=DRAWER_CLIENT_CN,
                real_address="203.0.113.7:1194",
                virtual_address="10.8.0.2",
                virtual_ipv6_address="",
                bytes_received=1024,
                bytes_sent=2048,
                connected_since="2026-01-01 00:00:00",
                connected_since_t=int(datetime.now(tz=UTC).timestamp()) - 60,
                username="alice",
                client_id="1",
                peer_id="0",
                data_channel_cipher="AES-256-GCM",
            )
        ],
    )


class _ThreadedServer(uvicorn.Server):
    """uvicorn.Server variant that skips signal handlers (non-main thread)."""

    def install_signal_handlers(self) -> None:  # pragma: no cover - trivial override
        return None


def _serve(stub: Callable[..., StatusSnapshot]) -> Iterator[str]:
    """Boot uvicorn in a daemon thread with ``fetch_status`` stubbed."""
    settings = Settings(
        openvpn_host="127.0.0.1",
        openvpn_port=1,  # nothing listens here; fetch_status is stubbed anyway
        site_name="E2E",
        timezone="UTC",
        management_timeout_seconds=1,
    )
    application = app_module.create_app(settings)

    original_fetch = app_module.fetch_status
    app_module.fetch_status = stub  # type: ignore[assignment]

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


@pytest.fixture(scope="session")
def live_server() -> Iterator[str]:
    """Dashboard with no connected client."""
    yield from _serve(_empty_snapshot)


@pytest.fixture(scope="session")
def live_server_with_clients() -> Iterator[str]:
    """Dashboard with one connected client, so a row can be clicked open."""
    yield from _serve(_one_client_snapshot)
