"""Tests for the native OIDC auth module."""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import httpx2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from joserfc import jwt
from joserfc.jwk import KeySet, RSAKey

from ovispect import app as app_module
from ovispect import oidc as oidc_module
from ovispect.config import Settings
from ovispect.oidc import (
    DiscoveryDocument,
    OIDCClient,
    OIDCError,
    discover,
    init_oidc_client,
)
from ovispect.ovpn import StatusSnapshot

ISSUER = "https://sso.example.test/realms/ovispect"
CLIENT_ID = "ovispect"
CLIENT_SECRET = "topsecret"  # pragma: allowlist secret
SESSION_SECRET = "x" * 64  # pragma: allowlist secret


class FakeProvider:
    """A route table served through :class:`httpx2.MockTransport`.

    Replaces the global monkey-patching a mocking library would do: the
    module under test builds its clients on ``oidc._transport_override``,
    which the ``provider`` fixture points at this table. Every response is
    built fresh per request, so a route can be hit any number of times.
    """

    def __init__(self) -> None:
        self._routes: dict[tuple[str, str], tuple[int, Any, str | None]] = {}
        self._failures: dict[tuple[str, str], Exception] = {}

    def fail(self, method: str, url: str, exc: Exception) -> None:
        """Make a route raise (e.g. ``httpx2.ConnectError``) instead of answering."""
        self._failures[(method.upper(), url)] = exc

    def get(
        self, url: str, *, status: int = 200, json: Any = None, text: str | None = None
    ) -> None:
        self._routes[("GET", url)] = (status, json, text)

    def post(
        self, url: str, *, status: int = 200, json: Any = None, text: str | None = None
    ) -> None:
        self._routes[("POST", url)] = (status, json, text)

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        key = (request.method, str(request.url).split("?", 1)[0])
        if key in self._failures:
            raise self._failures[key]
        if key not in self._routes:
            return httpx2.Response(404, text=f"no fake route for {key[0]} {key[1]}")
        status, json, text = self._routes[key]
        kwargs: dict[str, Any] = {}
        if json is not None:
            kwargs["json"] = json
        if text is not None:
            kwargs["text"] = text
        return httpx2.Response(status, **kwargs)

    @property
    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self.handle)


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> FakeProvider:
    """Route every HTTP client built by ``ovispect.oidc`` to a fake IdP."""
    fake = FakeProvider()
    monkeypatch.setattr(oidc_module, "_transport_override", fake.transport)
    return fake


async def test_client_builders_hit_the_network_when_no_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without the test seam, real clients are built with the verify flag."""
    monkeypatch.setattr(oidc_module, "_transport_override", None)
    with oidc_module._sync_client(verify_ssl=False, timeout=1.0) as sync_client:
        assert isinstance(sync_client, httpx2.Client)
    async with oidc_module._async_client(verify_ssl=True, timeout=1.0) as async_client:
        assert isinstance(async_client, httpx2.AsyncClient)


def test_oidc_callback_token_endpoint_unreachable_renders_error(  # type: ignore[no-untyped-def]
    oidc_app,
) -> None:
    """A transport error on the token endpoint is a clean 400, not a crash."""
    application, _, provider = oidc_app
    with TestClient(application, follow_redirects=False) as tc:
        login = tc.get("/login")
        state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
        provider.fail(
            "POST",
            f"{ISSUER}/protocol/openid-connect/token",
            httpx2.ConnectError("connection refused"),
        )
        response = tc.get("/oidc/callback", params={"code": "x", "state": state})
    assert response.status_code == 400
    assert "Authentication failed" in response.text


async def test_jwks_unreachable_raises_oidc_error(  # type: ignore[no-untyped-def]
    oidc_app,
) -> None:
    _, client, provider = oidc_app
    provider.fail(
        "GET",
        f"{ISSUER}/protocol/openid-connect/certs",
        httpx2.ConnectError("connection refused"),
    )
    with pytest.raises(OIDCError, match="jwks_unreachable"):
        await client._get_jwks()


def test_client_builders_use_the_override_when_set(provider: FakeProvider) -> None:
    """With the seam set, both clients are served by the fake provider."""
    provider.get("https://idp.example/ping", status=204)
    with oidc_module._sync_client(verify_ssl=True, timeout=1.0) as sync_client:
        assert sync_client.get("https://idp.example/ping").status_code == 204
        assert sync_client.get("https://idp.example/missing").status_code == 404


def _discovery_payload() -> dict[str, Any]:
    return {
        "issuer": ISSUER,
        "authorization_endpoint": f"{ISSUER}/protocol/openid-connect/auth",
        "token_endpoint": f"{ISSUER}/protocol/openid-connect/token",
        "jwks_uri": f"{ISSUER}/protocol/openid-connect/certs",
        "userinfo_endpoint": f"{ISSUER}/protocol/openid-connect/userinfo",
        "end_session_endpoint": f"{ISSUER}/protocol/openid-connect/logout",
    }


@pytest.fixture
def signing_key() -> RSAKey:
    return RSAKey.generate_key(2048, parameters={"kid": "test-key"})


@pytest.fixture
def jwks(signing_key: RSAKey) -> dict[str, Any]:
    keyset = KeySet([signing_key])
    return keyset.as_dict(private=False)


def _make_id_token(
    signing_key: RSAKey,
    *,
    iss: str = ISSUER,
    aud: str | list[str] = CLIENT_ID,
    sub: str = "user-1",
    extra: dict[str, Any] | None = None,
    expires_in: int = 3600,
    iat_offset: int = 0,
) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "iss": iss,
        "aud": aud,
        "sub": sub,
        "exp": now + expires_in,
        "iat": now + iat_offset,
        "preferred_username": "alice",
        "email": "alice@example.test",
    }
    if extra:
        payload.update(extra)
    return jwt.encode({"alg": "RS256", "kid": "test-key"}, payload, signing_key)


def _settings_oidc(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "openvpn_host": "127.0.0.1",
        "openvpn_port": 5555,
        "site_name": "Test VPN",
        "timezone": "UTC",
        "oidc_issuer_url": ISSUER,
        "oidc_client_id": CLIENT_ID,
        "oidc_client_secret": CLIENT_SECRET,
        "session_secret": SESSION_SECRET,
        "session_cookie_secure": False,  # TestClient is plaintext
    }
    base.update(overrides)
    return Settings(**base)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def test_discover_parses_required_fields(provider: FakeProvider) -> None:
    provider.get(
        f"{ISSUER}/.well-known/openid-configuration", status=200, json=_discovery_payload()
    )
    doc = discover(ISSUER)
    assert doc.issuer == ISSUER
    assert doc.authorization_endpoint.endswith("/auth")
    assert doc.token_endpoint.endswith("/token")
    assert doc.jwks_uri.endswith("/certs")
    assert doc.end_session_endpoint is not None


def test_discover_raises_on_404(provider: FakeProvider) -> None:
    provider.get(f"{ISSUER}/.well-known/openid-configuration", status=404)
    with pytest.raises(RuntimeError, match="discovery"):
        discover(ISSUER)


def test_discover_raises_on_missing_field(provider: FakeProvider) -> None:
    payload = _discovery_payload()
    del payload["jwks_uri"]
    provider.get(f"{ISSUER}/.well-known/openid-configuration", status=200, json=payload)
    with pytest.raises(RuntimeError, match="jwks_uri"):
        discover(ISSUER)


def test_init_oidc_client_returns_none_when_disabled(provider: FakeProvider) -> None:
    settings = Settings(openvpn_host="127.0.0.1", openvpn_port=5555)
    assert init_oidc_client(settings) is None


def test_init_oidc_client_raises_when_discovery_fails(provider: FakeProvider) -> None:
    provider.get(f"{ISSUER}/.well-known/openid-configuration", status=500)
    with pytest.raises(RuntimeError, match="discovery"):
        init_oidc_client(_settings_oidc())


# ---------------------------------------------------------------------------
# Callback flow
# ---------------------------------------------------------------------------


@pytest.fixture
def oidc_app(  # type: ignore[no-untyped-def]
    provider: FakeProvider,
    monkeypatch: pytest.MonkeyPatch,
    signing_key: RSAKey,
    jwks: dict[str, Any],
) -> Iterator[tuple[FastAPI, OIDCClient, FakeProvider]]:
    """Build a fully-wired FastAPI app in OIDC mode with mocked discovery."""

    def _fake_status(*_args: Any, **_kwargs: Any) -> StatusSnapshot:
        return StatusSnapshot(fetched_at=datetime.now(tz=UTC), clients=[])

    monkeypatch.setattr(app_module, "fetch_status", _fake_status)

    settings = _settings_oidc()

    provider.get(
        f"{ISSUER}/.well-known/openid-configuration", status=200, json=_discovery_payload()
    )
    provider.get(f"{ISSUER}/protocol/openid-connect/certs", status=200, json=jwks)
    application = app_module.create_app(settings)
    # Find the OIDC client we just initialised.
    client = _find_oidc_client(application)
    return application, client, provider


def _find_oidc_client(application: FastAPI) -> OIDCClient:
    for route in application.routes:
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None:
            continue
        cell = getattr(endpoint, "__closure__", None)
        if not cell:
            continue
        for c in cell:
            try:
                value = c.cell_contents
            except ValueError:
                continue
            if isinstance(value, OIDCClient):
                return value
    raise AssertionError("OIDC client not bound to any route")


def test_login_redirects_to_authorize_endpoint(  # type: ignore[no-untyped-def]
    oidc_app,
) -> None:
    application, _, _ = oidc_app
    with TestClient(application, follow_redirects=False) as tc:
        response = tc.get("/login")
    assert response.status_code == 303
    location = response.headers["location"]
    parsed = urlparse(location)
    assert parsed.path.endswith("/auth")
    qs = parse_qs(parsed.query)
    assert qs["client_id"] == [CLIENT_ID]
    assert qs["response_type"] == ["code"]
    assert qs["code_challenge_method"] == ["S256"]
    assert "state" in qs
    assert "code_challenge" in qs


def test_index_redirects_to_login_when_unauthenticated_in_oidc(  # type: ignore[no-untyped-def]
    oidc_app,
) -> None:
    application, _, _ = oidc_app
    with TestClient(application, follow_redirects=False) as tc:
        response = tc.get("/")
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


def test_oidc_callback_state_mismatch_renders_error(  # type: ignore[no-untyped-def]
    oidc_app,
) -> None:
    application, _, _ = oidc_app
    with TestClient(application, follow_redirects=False) as tc:
        # Hit /login first to populate session state, then craft a bad callback.
        tc.get("/login")
        response = tc.get("/oidc/callback", params={"code": "x", "state": "wrong"})
    assert response.status_code == 400
    assert "Authentication failed" in response.text


def test_oidc_callback_provider_error_renders_error(  # type: ignore[no-untyped-def]
    oidc_app,
) -> None:
    application, _, _ = oidc_app
    with TestClient(application, follow_redirects=False) as tc:
        response = tc.get("/oidc/callback", params={"error": "access_denied"})
    assert response.status_code == 400


def test_oidc_callback_success_sets_session(  # type: ignore[no-untyped-def]
    oidc_app,
    signing_key: RSAKey,
    jwks: dict[str, Any],
) -> None:
    application, _, provider = oidc_app
    with TestClient(application, follow_redirects=False) as tc:
        login = tc.get("/login")
        location = login.headers["location"]
        state = parse_qs(urlparse(location).query)["state"][0]

        id_token = _make_id_token(signing_key)
        provider.post(
            f"{ISSUER}/protocol/openid-connect/token",
            status=200,
            json={
                "access_token": "at",
                "refresh_token": "rt",
                "id_token": id_token,
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )
        provider.get(f"{ISSUER}/protocol/openid-connect/certs", status=200, json=jwks)
        response = tc.get(
            "/oidc/callback",
            params={"code": "abc", "state": state},
        )
        assert response.status_code == 303, response.text
        assert response.headers["location"] == "/"

        index = tc.get("/")
        assert index.status_code == 200
        assert "alice" in index.text


def test_oidc_callback_rejects_expired_id_token(  # type: ignore[no-untyped-def]
    oidc_app,
    signing_key: RSAKey,
    jwks: dict[str, Any],
) -> None:
    application, _, provider = oidc_app
    with TestClient(application, follow_redirects=False) as tc:
        login = tc.get("/login")
        state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
        expired = _make_id_token(signing_key, expires_in=-3600)
        provider.post(
            f"{ISSUER}/protocol/openid-connect/token",
            status=200,
            json={
                "access_token": "at",
                "id_token": expired,
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )
        provider.get(f"{ISSUER}/protocol/openid-connect/certs", status=200, json=jwks)
        response = tc.get("/oidc/callback", params={"code": "x", "state": state})
        assert response.status_code == 400


def test_oidc_callback_rejects_aud_mismatch(  # type: ignore[no-untyped-def]
    oidc_app,
    signing_key: RSAKey,
    jwks: dict[str, Any],
) -> None:
    application, _, provider = oidc_app
    with TestClient(application, follow_redirects=False) as tc:
        login = tc.get("/login")
        state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
        token = _make_id_token(signing_key, aud="someone-else")
        provider.post(
            f"{ISSUER}/protocol/openid-connect/token",
            status=200,
            json={
                "access_token": "at",
                "id_token": token,
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )
        provider.get(f"{ISSUER}/protocol/openid-connect/certs", status=200, json=jwks)
        response = tc.get("/oidc/callback", params={"code": "x", "state": state})
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# Group enforcement
# ---------------------------------------------------------------------------


def test_required_groups_grant_access(
    provider: FakeProvider,
    monkeypatch: pytest.MonkeyPatch,
    signing_key: RSAKey,
    jwks: dict[str, Any],
) -> None:

    monkeypatch.setattr(
        app_module,
        "fetch_status",
        lambda *_a, **_k: StatusSnapshot(fetched_at=datetime.now(tz=UTC), clients=[]),
    )

    settings = _settings_oidc(oidc_required_groups="admins,vpn-monitors")

    provider.get(
        f"{ISSUER}/.well-known/openid-configuration", status=200, json=_discovery_payload()
    )
    provider.get(f"{ISSUER}/protocol/openid-connect/certs", status=200, json=jwks)
    application = app_module.create_app(settings)

    with TestClient(application, follow_redirects=False) as tc:
        login = tc.get("/login")
        state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
        token = _make_id_token(signing_key, extra={"groups": ["vpn-monitors"]})
        provider.post(
            f"{ISSUER}/protocol/openid-connect/token",
            status=200,
            json={
                "access_token": "at",
                "id_token": token,
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )
        response = tc.get("/oidc/callback", params={"code": "x", "state": state})
        assert response.status_code == 303
        assert response.headers["location"] == "/"


def test_required_groups_deny_renders_403(
    provider: FakeProvider,
    monkeypatch: pytest.MonkeyPatch,
    signing_key: RSAKey,
    jwks: dict[str, Any],
) -> None:

    monkeypatch.setattr(
        app_module,
        "fetch_status",
        lambda *_a, **_k: StatusSnapshot(fetched_at=datetime.now(tz=UTC), clients=[]),
    )

    settings = _settings_oidc(oidc_required_groups="admins")

    provider.get(
        f"{ISSUER}/.well-known/openid-configuration", status=200, json=_discovery_payload()
    )
    provider.get(f"{ISSUER}/protocol/openid-connect/certs", status=200, json=jwks)
    application = app_module.create_app(settings)

    with TestClient(application, follow_redirects=False) as tc:
        login = tc.get("/login")
        state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
        token = _make_id_token(signing_key, extra={"groups": ["users"]})
        provider.post(
            f"{ISSUER}/protocol/openid-connect/token",
            status=200,
            json={
                "access_token": "at",
                "id_token": token,
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )
        response = tc.get("/oidc/callback", params={"code": "x", "state": state})
        assert response.status_code == 403
        assert "Access denied" in response.text
        assert "admins" in response.text


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


def test_oidc_logout_redirects_to_end_session(  # type: ignore[no-untyped-def]
    oidc_app,
    signing_key: RSAKey,
    jwks: dict[str, Any],
) -> None:
    application, _, provider = oidc_app
    with TestClient(application, follow_redirects=False) as tc:
        login = tc.get("/login")
        state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
        provider.post(
            f"{ISSUER}/protocol/openid-connect/token",
            status=200,
            json={
                "id_token": _make_id_token(signing_key),
                "access_token": "at",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )
        provider.get(f"{ISSUER}/protocol/openid-connect/certs", status=200, json=jwks)
        tc.get("/oidc/callback", params={"code": "x", "state": state})

        logout = tc.post("/logout")
    assert logout.status_code == 303
    assert "openid-connect/logout" in logout.headers["location"]
    assert f"client_id={CLIENT_ID}" in logout.headers["location"]
    # id_token is no longer stored server-side, so we never carry an id_token_hint.
    assert "id_token_hint=" not in logout.headers["location"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_session_username_falls_back_to_email_when_claim_missing() -> None:
    settings = _settings_oidc()
    payload = {"user": {"email": "alice@example.test"}}
    assert oidc_module.session_username(settings, payload) == "alice@example.test"


def test_session_groups_handles_string_claim() -> None:
    settings = _settings_oidc()
    payload = {"user": {"groups": "a, b , c"}}
    assert oidc_module.session_groups(settings, payload) == ["a", "b", "c"]


def test_has_required_groups_passes_when_unset() -> None:
    settings = _settings_oidc()
    assert oidc_module.has_required_groups(settings, []) is True


def test_oidc_client_logout_url_returns_none_without_endpoint() -> None:
    settings = _settings_oidc()
    doc = DiscoveryDocument(
        issuer=ISSUER,
        authorization_endpoint=f"{ISSUER}/auth",
        token_endpoint=f"{ISSUER}/token",
        jwks_uri=f"{ISSUER}/jwks",
        end_session_endpoint=None,
    )
    client = OIDCClient(settings, doc)

    assert client.logout_url(post_logout_redirect_uri=None) is None


def test_oidc_error_carries_code() -> None:
    err = OIDCError("state_mismatch")
    assert err.code == "state_mismatch"
    assert err.status_code == 400


def test_is_oidc_enabled_helper() -> None:
    assert oidc_module.is_oidc_enabled(_settings_oidc()) is True
    assert (
        oidc_module.is_oidc_enabled(Settings(openvpn_host="127.0.0.1", openvpn_port=5555)) is False
    )


# ---------------------------------------------------------------------------
# Session shape — the v0.8.2 fix: keep the cookie small and free of raw tokens
# ---------------------------------------------------------------------------


def _capture_session(  # type: ignore[no-untyped-def]
    oidc_app,
    signing_key: RSAKey,
    jwks: dict[str, Any],
    *,
    extra_claims: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run a successful callback and return the resulting OIDC session dict."""
    application, _, provider = oidc_app
    with TestClient(application, follow_redirects=False) as tc:
        login = tc.get("/login")
        state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
        token = _make_id_token(signing_key, extra=extra_claims)
        provider.post(
            f"{ISSUER}/protocol/openid-connect/token",
            status=200,
            json={
                # The provider returns realistic, multi-KB tokens. The
                # whole point of the fix is that none of these end up
                # in the cookie.
                "access_token": "A" * 1500,
                "refresh_token": "R" * 600,
                "id_token": token,
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )
        provider.get(f"{ISSUER}/protocol/openid-connect/certs", status=200, json=jwks)
        cb = tc.get("/oidc/callback", params={"code": "x", "state": state})
        assert cb.status_code == 303
        # Pull the session straight out of TestClient's cookie jar via a
        # second authenticated GET — easier than reaching into Starlette's
        # signing internals.
        cookie = tc.cookies.get("ovispect_session")
        assert cookie is not None
    return _decode_session_cookie(cookie)


def _decode_session_cookie(cookie: str) -> dict[str, Any]:
    """Decode a Starlette signed-session cookie payload (no signature check)."""
    payload = cookie.split(".", 1)[0]
    pad = "=" * (-len(payload) % 4)
    raw = base64.urlsafe_b64decode(payload + pad)
    decoded = cast("dict[str, Any]", json.loads(raw))
    return decoded


def test_session_size_under_limit(  # type: ignore[no-untyped-def]
    oidc_app,
    signing_key: RSAKey,
    jwks: dict[str, Any],
) -> None:
    """The serialised session must stay well under the 4 KB browser limit."""
    application, _, provider = oidc_app
    with TestClient(application, follow_redirects=False) as tc:
        login = tc.get("/login")
        state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
        provider.post(
            f"{ISSUER}/protocol/openid-connect/token",
            status=200,
            json={
                "access_token": "A" * 1800,
                "refresh_token": "R" * 800,
                "id_token": _make_id_token(
                    signing_key,
                    extra={"groups": ["admins", "vpn-monitors"]},
                ),
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )
        provider.get(f"{ISSUER}/protocol/openid-connect/certs", status=200, json=jwks)
        tc.get("/oidc/callback", params={"code": "x", "state": state})
        cookie = tc.cookies.get("ovispect_session")
        assert cookie is not None
    # The cookie value, post-signing, must comfortably fit in the recommended
    # 4096-byte ceiling. We pick 1 KB as the assertion to leave headroom.
    assert len(cookie) < 1024, f"session cookie is {len(cookie)} bytes, expected < 1024"


def test_session_contains_only_safe_claims(  # type: ignore[no-untyped-def]
    oidc_app,
    signing_key: RSAKey,
    jwks: dict[str, Any],
) -> None:
    """No raw tokens may leak into the session — that's the bug we fixed."""
    decoded = _capture_session(oidc_app, signing_key, jwks)
    oidc_state = decoded.get("oidc")
    assert isinstance(oidc_state, dict)
    forbidden = {"id_token", "access_token", "refresh_token", "expires_at", "claims"}
    leaked = forbidden & oidc_state.keys()
    assert not leaked, f"session unexpectedly contains: {leaked}"
    user = oidc_state.get("user")
    assert isinstance(user, dict)
    assert forbidden.isdisjoint(user.keys())


def test_session_contains_user_identity(  # type: ignore[no-untyped-def]
    oidc_app,
    signing_key: RSAKey,
    jwks: dict[str, Any],
) -> None:
    """The session must still carry enough to identify and authorise the user."""
    decoded = _capture_session(
        oidc_app, signing_key, jwks, extra_claims={"groups": ["vpn-monitors"]}
    )
    user = decoded["oidc"]["user"]
    assert user["sub"] == "user-1"
    assert user["email"] == "alice@example.test"
    assert user["preferred_username"] == "alice"
    assert user["groups"] == ["vpn-monitors"]


def test_oidc_callback_rejects_iss_mismatch(  # type: ignore[no-untyped-def]
    provider: FakeProvider,
    monkeypatch: pytest.MonkeyPatch,
    signing_key: RSAKey,
    jwks: dict[str, Any],
) -> None:

    monkeypatch.setattr(
        app_module,
        "fetch_status",
        lambda *_a, **_k: StatusSnapshot(fetched_at=datetime.now(tz=UTC), clients=[]),
    )

    settings = _settings_oidc()
    provider.get(
        f"{ISSUER}/.well-known/openid-configuration", status=200, json=_discovery_payload()
    )
    provider.get(f"{ISSUER}/protocol/openid-connect/certs", status=200, json=jwks)
    application = app_module.create_app(settings)

    with TestClient(application, follow_redirects=False) as tc:
        login = tc.get("/login")
        state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
        bad_token = _make_id_token(signing_key, iss="https://attacker.example/realm")
        provider.post(
            f"{ISSUER}/protocol/openid-connect/token",
            status=200,
            json={
                "access_token": "at",
                "id_token": bad_token,
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )
        response = tc.get("/oidc/callback", params={"code": "x", "state": state})
        assert response.status_code == 400


def test_oidc_token_endpoint_failure_renders_error(  # type: ignore[no-untyped-def]
    provider: FakeProvider,
    monkeypatch: pytest.MonkeyPatch,
    jwks: dict[str, Any],
) -> None:

    monkeypatch.setattr(
        app_module,
        "fetch_status",
        lambda *_a, **_k: StatusSnapshot(fetched_at=datetime.now(tz=UTC), clients=[]),
    )

    settings = _settings_oidc()
    provider.get(
        f"{ISSUER}/.well-known/openid-configuration", status=200, json=_discovery_payload()
    )
    provider.get(f"{ISSUER}/protocol/openid-connect/certs", status=200, json=jwks)
    application = app_module.create_app(settings)

    with TestClient(application, follow_redirects=False) as tc:
        login = tc.get("/login")
        state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
        provider.post(f"{ISSUER}/protocol/openid-connect/token", status=500, text="boom")
        response = tc.get("/oidc/callback", params={"code": "x", "state": state})
        assert response.status_code == 400
        assert "Authentication failed" in response.text
