"""Integration tests for the FastAPI application."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ovispect import app as app_module
from ovispect.config import Settings
from ovispect.ovpn import Client, StatusSnapshot
from tests.conftest import PLAIN_PASSWORD


def _make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "openvpn_host": "127.0.0.1",
        "openvpn_port": 5555,
        "site_name": "Test VPN",
        "refresh_seconds": 10,
        "timezone": "UTC",
        "log_level": "INFO",
    }
    base.update(overrides)
    return Settings(**base)


def _sample_clients() -> list[Client]:
    return [
        Client(
            common_name="alice@example.com",
            real_address="203.0.113.10:51820",
            virtual_address="10.8.0.6",
            virtual_ipv6_address="",
            bytes_received=1234567,
            bytes_sent=7654321,
            connected_since="Mon May  6 11:00:00 2026",
            connected_since_t=1714989600,
            username="UNDEF",
            client_id="1",
            peer_id="0",
            data_channel_cipher="AES-256-GCM",
        ),
    ]


@pytest.fixture
def client_factory(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Build a TestClient with a stubbed ``fetch_status``."""

    def _build(snapshot: StatusSnapshot) -> TestClient:
        def _fake_fetch(*_args: Any, **_kwargs: Any) -> StatusSnapshot:
            return snapshot

        monkeypatch.setattr(app_module, "fetch_status", _fake_fetch)
        application = app_module.create_app(_make_settings())
        return TestClient(application)

    return _build


def test_healthz_returns_ok(client_factory) -> None:  # type: ignore[no-untyped-def]
    snapshot = StatusSnapshot(fetched_at=datetime.now(tz=UTC), clients=[])
    with client_factory(snapshot) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_index_renders_clients(client_factory) -> None:  # type: ignore[no-untyped-def]
    snapshot = StatusSnapshot(fetched_at=datetime.now(tz=UTC), clients=_sample_clients())
    with client_factory(snapshot) as client:
        response = client.get("/")
    assert response.status_code == 200
    body = response.text
    assert "Test VPN" in body
    assert "alice@example.com" in body
    assert "203.0.113.10" in body
    assert "10.8.0.6" in body
    assert "1.2 MB" in body
    assert "7.3 MB" in body


def test_index_shows_empty_state(client_factory) -> None:  # type: ignore[no-untyped-def]
    snapshot = StatusSnapshot(fetched_at=datetime.now(tz=UTC), clients=[])
    with client_factory(snapshot) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "No active sessions" in response.text


def test_index_shows_error_banner(client_factory) -> None:  # type: ignore[no-untyped-def]
    snapshot = StatusSnapshot(
        fetched_at=datetime.now(tz=UTC),
        clients=[],
        error="connection refused",
    )
    with client_factory(snapshot) as client:
        response = client.get("/")
    assert response.status_code == 200
    body = response.text
    assert "Cannot reach the OpenVPN management interface" in body
    assert "connection refused" in body


def test_metrics_exposes_prometheus(client_factory) -> None:  # type: ignore[no-untyped-def]
    snapshot = StatusSnapshot(fetched_at=datetime.now(tz=UTC), clients=_sample_clients())
    with client_factory(snapshot) as client:
        response = client.get("/metrics")
    assert response.status_code == 200
    body = response.text
    assert "ovispect_up 1" in body
    assert "ovispect_clients_connected 1" in body
    assert "ovispect_bytes_received_total 1234567" in body
    assert "ovispect_bytes_sent_total 7654321" in body


def test_metrics_reports_down_on_error(client_factory) -> None:  # type: ignore[no-untyped-def]
    snapshot = StatusSnapshot(
        fetched_at=datetime.now(tz=UTC),
        clients=[],
        error="connection refused",
    )
    with client_factory(snapshot) as client:
        response = client.get("/metrics")
    assert response.status_code == 200
    assert "ovispect_up 0" in response.text


# --- Authentication-mode integration tests ---------------------------------


def test_index_unauthenticated_serves_dashboard_in_no_auth_mode(client_no_auth) -> None:  # type: ignore[no-untyped-def]
    response = client_no_auth.get("/")
    assert response.status_code == 200
    assert "Test VPN" in response.text
    assert "Sign out" not in response.text


def test_healthz_is_public_in_no_auth_mode(client_no_auth) -> None:  # type: ignore[no-untyped-def]
    assert client_no_auth.get("/healthz").json() == {"ok": True}


def test_index_redirects_to_login_when_unauthenticated(client_with_auth) -> None:  # type: ignore[no-untyped-def]
    response = client_with_auth.get("/")
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


def test_healthz_remains_public_in_auth_mode(client_with_auth) -> None:  # type: ignore[no-untyped-def]
    assert client_with_auth.get("/healthz").status_code == 200


def test_login_form_renders(client_with_auth) -> None:  # type: ignore[no-untyped-def]
    response = client_with_auth.get("/login")
    assert response.status_code == 200
    assert "Sign in" in response.text
    assert 'name="password"' in response.text


def test_login_submit_with_correct_credentials_sets_session(client_with_auth) -> None:  # type: ignore[no-untyped-def]

    response = client_with_auth.post(
        "/login",
        data={"username": "admin", "password": PLAIN_PASSWORD},
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert any(c.startswith("ovispect_session") for c in response.headers.get_list("set-cookie"))

    # Cookie persisted in the client; the dashboard is now reachable.
    follow = client_with_auth.get("/")
    assert follow.status_code == 200
    assert "Sign out" in follow.text


def test_login_submit_with_wrong_password_returns_401(client_with_auth) -> None:  # type: ignore[no-untyped-def]
    response = client_with_auth.post(
        "/login",
        data={"username": "admin", "password": "wrong"},  # pragma: allowlist secret
    )
    assert response.status_code == 401
    assert "Invalid credentials" in response.text


def test_login_submit_open_redirect_protection(client_with_auth) -> None:  # type: ignore[no-untyped-def]

    response = client_with_auth.post(
        "/login",
        data={
            "username": "admin",
            "password": PLAIN_PASSWORD,
            "next": "https://evil.com/steal",
        },
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_login_submit_preserves_safe_next(client_with_auth) -> None:  # type: ignore[no-untyped-def]

    response = client_with_auth.post(
        "/login",
        data={
            "username": "admin",
            "password": PLAIN_PASSWORD,
            "next": "/metrics",
        },
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/metrics"


def test_logout_clears_session(client_with_auth) -> None:  # type: ignore[no-untyped-def]

    client_with_auth.post(
        "/login",
        data={"username": "admin", "password": PLAIN_PASSWORD},
    )
    logout = client_with_auth.post("/logout")
    assert logout.status_code == 303
    assert logout.headers["location"].startswith("/login")

    after = client_with_auth.get("/")
    assert after.status_code == 303
    assert after.headers["location"].startswith("/login")


def test_login_rate_limit_blocks_after_repeated_failures(client_with_auth) -> None:  # type: ignore[no-untyped-def]
    bad_creds = {"username": "admin", "password": "wrong"}  # pragma: allowlist secret
    for _ in range(5):
        response = client_with_auth.post("/login", data=bad_creds)
        assert response.status_code == 401

    response = client_with_auth.post("/login", data=bad_creds)
    assert response.status_code == 429
    assert "Too many failed attempts" in response.text
