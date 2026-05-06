"""Shared pytest fixtures for ovispect's HTTP tests."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import bcrypt
import pytest
from fastapi.testclient import TestClient

from ovispect import app as app_module
from ovispect.config import Settings
from ovispect.ovpn import StatusSnapshot

PLAIN_PASSWORD = "correct horse battery staple"


def make_bcrypt_hash(plain: str = PLAIN_PASSWORD) -> str:
    """Generate a bcrypt hash with low rounds (fast for tests)."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=4)).decode("ascii")


def _ok_snapshot() -> StatusSnapshot:
    return StatusSnapshot(fetched_at=datetime.now(tz=UTC), clients=[])


@pytest.fixture
def fake_fetch(monkeypatch: pytest.MonkeyPatch) -> Callable[[StatusSnapshot], None]:
    """Stub :func:`ovispect.ovpn.fetch_status` everywhere it is referenced."""

    def _install(snapshot: StatusSnapshot) -> None:
        def _fake(*_args: Any, **_kwargs: Any) -> StatusSnapshot:
            return snapshot

        monkeypatch.setattr(app_module, "fetch_status", _fake)

    _install(_ok_snapshot())
    return _install


@pytest.fixture
def settings_no_auth() -> Settings:
    return Settings(
        openvpn_host="127.0.0.1",
        openvpn_port=5555,
        site_name="Test VPN",
        timezone="UTC",
    )


@pytest.fixture
def auth_hash() -> str:
    return make_bcrypt_hash()


@pytest.fixture
def settings_with_auth(auth_hash: str) -> Settings:
    return Settings(
        openvpn_host="127.0.0.1",
        openvpn_port=5555,
        site_name="Test VPN",
        timezone="UTC",
        auth_username="admin",
        auth_password_hash=auth_hash,
        session_secret="x" * 64,
        session_cookie_secure=False,  # TestClient does not negotiate TLS.
    )


@pytest.fixture
def client_no_auth(
    fake_fetch: Callable[[StatusSnapshot], None],
    settings_no_auth: Settings,
) -> Iterator[TestClient]:
    application = app_module.create_app(settings_no_auth)
    with TestClient(application) as client:
        yield client


@pytest.fixture
def client_with_auth(
    fake_fetch: Callable[[StatusSnapshot], None],
    settings_with_auth: Settings,
) -> Iterator[TestClient]:
    application = app_module.create_app(settings_with_auth)
    with TestClient(application, follow_redirects=False) as client:
        yield client
