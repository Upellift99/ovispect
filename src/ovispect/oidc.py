"""Native OIDC authentication (Mode 1).

Implements OpenID Connect 1.0 Authorization Code Flow + PKCE (S256) against
a single configured provider. Discovery is performed at startup; failure is
fatal — ovispect refuses to boot rather than silently degrading.

Only the validated user-identity claims are persisted in the Starlette
session — never the raw ``id_token``, ``access_token`` or ``refresh_token``.
This keeps the cookie comfortably under the 4 KB browser limit.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, Request
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet

from ovispect.auth import build_login_redirect, is_safe_next
from ovispect.config import Settings

logger = logging.getLogger(__name__)

OIDC_SESSION_KEY = "oidc"
PENDING_KEY = "oidc_state"
DISCOVERY_PATH = "/.well-known/openid-configuration"

# Identity claims kept in the session cookie. Everything else (raw tokens,
# audience claims, signature metadata, …) is dropped on purpose.
_SAFE_SESSION_CLAIMS: frozenset[str] = frozenset(
    {
        "sub",
        "preferred_username",
        "email",
        "name",
        "given_name",
        "family_name",
        "groups",
        "exp",
        "iat",
    }
)

_JWKS_REFRESH_TTL_SECONDS = 3600
_HTTP_TIMEOUT_SECONDS = 10.0
_ALLOWED_ALGS = ["RS256", "RS384", "RS512", "ES256", "ES384", "PS256"]
_CALLBACK_PATH = "/oidc/callback"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _generate_pkce() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _generate_state() -> str:
    return _b64url(secrets.token_bytes(24))


def is_oidc_enabled(settings: Settings) -> bool:
    """Return True iff the OIDC mode is fully configured."""
    return settings.oidc_enabled


class OIDCError(Exception):
    """Raised on any callback / token-validation failure.

    The exception's ``code`` is a short machine-readable label; the public
    UI surfaces a generic message and only operators see the code in logs.
    """

    def __init__(self, code: str, *, status_code: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class DiscoveryDocument:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    userinfo_endpoint: str | None = None
    end_session_endpoint: str | None = None


def discover(
    issuer_url: str,
    *,
    verify_ssl: bool = True,
    timeout: float = _HTTP_TIMEOUT_SECONDS,
) -> DiscoveryDocument:
    """Fetch ``.well-known/openid-configuration`` and parse the required fields.

    Raises ``RuntimeError`` on any failure — discovery happens at startup and
    a misconfigured issuer should crash boot, not produce a half-initialised
    app.
    """
    base = issuer_url.rstrip("/")
    url = base + DISCOVERY_PATH
    try:
        with httpx.Client(verify=verify_ssl, timeout=timeout) as client:
            response = client.get(url)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"OIDC discovery request to {url} failed: {exc}") from exc
    except ValueError as exc:
        raise RuntimeError(f"OIDC discovery at {url} returned non-JSON body: {exc}") from exc

    for required in ("issuer", "authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not isinstance(data.get(required), str):
            raise RuntimeError(f"OIDC discovery at {url} is missing required field: {required!r}")
    return DiscoveryDocument(
        issuer=data["issuer"],
        authorization_endpoint=data["authorization_endpoint"],
        token_endpoint=data["token_endpoint"],
        jwks_uri=data["jwks_uri"],
        userinfo_endpoint=data.get("userinfo_endpoint"),
        end_session_endpoint=data.get("end_session_endpoint"),
    )


HttpClientFactory = Callable[[], httpx.AsyncClient]


class OIDCClient:
    """Per-app OIDC handler.

    Holds the discovery document and a lazily-fetched JWKS keyset. State for
    the in-flight authorize request is stored in the Starlette session.
    """

    def __init__(
        self,
        settings: Settings,
        discovery: DiscoveryDocument,
        *,
        http_client_factory: HttpClientFactory | None = None,
    ) -> None:
        self._settings = settings
        self._discovery = discovery
        self._jwks: KeySet | None = None
        self._jwks_fetched_at: float = 0.0
        self._http_client_factory: HttpClientFactory = (
            http_client_factory if http_client_factory is not None else self._default_client
        )

    def _default_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            verify=self._settings.oidc_verify_ssl,
            timeout=_HTTP_TIMEOUT_SECONDS,
        )

    @property
    def discovery(self) -> DiscoveryDocument:
        return self._discovery

    @property
    def settings(self) -> Settings:
        return self._settings

    # ---- Authorization request ------------------------------------------------

    def derive_redirect_uri(self, request: Request) -> str:
        """Return the absolute callback URL for this provider.

        If ``OIDC_REDIRECT_URI`` is configured, use it verbatim. Otherwise,
        rebuild it from the request's scheme + host (respecting common
        proxy headers) + the static callback path.
        """
        configured = self._settings.oidc_redirect_uri
        if configured is not None:
            return str(configured)
        scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
        host = request.headers.get("x-forwarded-host") or request.headers.get("host")
        if not host:
            host = request.url.netloc
        return f"{scheme}://{host}{_CALLBACK_PATH}"

    def authorize_redirect(
        self,
        request: Request,
        *,
        next_path: str | None = None,
    ) -> str:
        """Return the URL the user should be redirected to (303) to start sign-in.

        Generates fresh ``state`` and PKCE verifier and stores them in the
        session so the callback can validate them.
        """
        verifier, challenge = _generate_pkce()
        state = _generate_state()
        redirect_uri = self.derive_redirect_uri(request)
        safe_next = next_path if next_path and is_safe_next(next_path) else ""
        request.session[PENDING_KEY] = {
            "state": state,
            "verifier": verifier,
            "redirect_uri": redirect_uri,
            "next": safe_next,
        }
        params = {
            "client_id": self._settings.oidc_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": self._settings.oidc_scopes,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return f"{self._discovery.authorization_endpoint}?{urlencode(params)}"

    # ---- Callback -------------------------------------------------------------

    async def handle_callback(
        self,
        request: Request,
        *,
        code: str,
        state: str,
    ) -> dict[str, Any]:
        """Exchange ``code`` for tokens, validate the id_token, populate session.

        Only the safe identity claims are kept; the raw tokens are dropped
        as soon as validation succeeds (see module docstring for rationale).
        Returns a dict with ``user`` and ``next`` (the originally-requested
        path, or empty string if none/unsafe).
        """
        pending = request.session.get(PENDING_KEY)
        if not isinstance(pending, dict) or pending.get("state") != state:
            raise OIDCError("state_mismatch")
        request.session.pop(PENDING_KEY, None)

        verifier = pending.get("verifier")
        redirect_uri = pending.get("redirect_uri")
        if not isinstance(verifier, str) or not isinstance(redirect_uri, str):
            raise OIDCError("pending_state_corrupt")
        next_path = pending.get("next") or ""

        token = await self._exchange_code(code=code, verifier=verifier, redirect_uri=redirect_uri)
        id_token = token.get("id_token")
        if not isinstance(id_token, str):
            raise OIDCError("missing_id_token")
        claims = await self._validate_id_token(id_token)

        user = self._extract_user(claims)
        request.session[OIDC_SESSION_KEY] = {
            "user": user,
            "authenticated_at": int(time.time()),
        }
        return {"user": user, "next": next_path if is_safe_next(next_path) else ""}

    def _extract_user(self, claims: dict[str, Any]) -> dict[str, Any]:
        """Project the validated claims down to the identity fields we keep.

        Always includes the configured username and groups claims so that
        non-default ``OIDC_USERNAME_CLAIM`` / ``OIDC_GROUPS_CLAIM`` settings
        survive the projection.
        """
        keep = _SAFE_SESSION_CLAIMS | {
            self._settings.oidc_username_claim,
            self._settings.oidc_groups_claim,
        }
        return {k: claims[k] for k in keep if k in claims}

    async def _exchange_code(
        self,
        *,
        code: str,
        verifier: str,
        redirect_uri: str,
    ) -> dict[str, Any]:
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": self._settings.oidc_client_id,
            "client_secret": self._settings.oidc_client_secret.get_secret_value(),
            "code_verifier": verifier,
        }
        try:
            async with self._http_client_factory() as client:
                response = await client.post(self._discovery.token_endpoint, data=data)
        except httpx.HTTPError as exc:
            logger.warning("oidc token endpoint request failed: %s", exc)
            raise OIDCError("token_endpoint_unreachable") from exc
        if response.status_code != 200:
            logger.warning(
                "oidc token endpoint returned %s: %s",
                response.status_code,
                response.text[:256],
            )
            raise OIDCError(f"token_endpoint_status_{response.status_code}")
        try:
            return cast("dict[str, Any]", response.json())
        except ValueError as exc:
            raise OIDCError("token_endpoint_non_json") from exc

    async def _validate_id_token(self, id_token: str) -> dict[str, Any]:
        keyset = await self._get_jwks()
        try:
            decoded = jwt.decode(id_token, keyset, algorithms=_ALLOWED_ALGS)
        except JoseError as exc:
            logger.warning("id_token signature validation failed: %s", exc)
            raise OIDCError("id_token_invalid_signature") from exc
        claims = dict(decoded.claims)
        now = int(time.time())

        if claims.get("iss") != self._discovery.issuer:
            raise OIDCError("iss_mismatch")
        aud = claims.get("aud")
        if isinstance(aud, str):
            aud_ok = aud == self._settings.oidc_client_id
        elif isinstance(aud, list):
            aud_ok = self._settings.oidc_client_id in aud
        else:
            aud_ok = False
        if not aud_ok:
            raise OIDCError("aud_mismatch")
        exp = claims.get("exp")
        if not isinstance(exp, int) or exp < now - 60:
            raise OIDCError("id_token_expired")
        iat = claims.get("iat")
        if isinstance(iat, int) and iat > now + 300:
            raise OIDCError("id_token_iat_in_future")
        return claims

    async def _get_jwks(self) -> KeySet:
        now = time.time()
        if self._jwks is not None and (now - self._jwks_fetched_at) < _JWKS_REFRESH_TTL_SECONDS:
            return self._jwks
        try:
            async with self._http_client_factory() as client:
                response = await client.get(self._discovery.jwks_uri)
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise OIDCError("jwks_unreachable") from exc
        except ValueError as exc:
            raise OIDCError("jwks_non_json") from exc
        keyset = KeySet.import_key_set(payload)
        self._jwks = keyset
        self._jwks_fetched_at = now
        return keyset

    # ---- Logout ---------------------------------------------------------------

    def logout_url(
        self,
        request: Request,
        *,
        post_logout_redirect_uri: str | None = None,
    ) -> str | None:
        """Build the provider-side end_session URL, or None if unsupported.

        We no longer carry an ``id_token_hint`` because the raw id_token is
        not retained server-side. Modern providers (Keycloak ≥ 18, Authelia,
        Authentik, Zitadel) accept ``client_id`` + ``post_logout_redirect_uri``
        as a sufficient hint pair.
        """
        if self._discovery.end_session_endpoint is None:
            return None
        params: dict[str, str] = {"client_id": self._settings.oidc_client_id}
        if post_logout_redirect_uri:
            params["post_logout_redirect_uri"] = post_logout_redirect_uri
        return f"{self._discovery.end_session_endpoint}?{urlencode(params)}"


def init_oidc_client(settings: Settings) -> OIDCClient | None:
    """Initialise the OIDC client at startup, performing discovery.

    Returns ``None`` when OIDC mode is not configured. Raises ``RuntimeError``
    if discovery fails — that signals a misconfigured deployment and must
    abort boot rather than silently fall back to another mode.
    """
    if not settings.oidc_enabled or settings.oidc_issuer_url is None:
        return None
    issuer_url = str(settings.oidc_issuer_url)
    doc = discover(issuer_url, verify_ssl=settings.oidc_verify_ssl)
    return OIDCClient(settings, doc)


# ---------------------------------------------------------------------------
# Session helpers (read-side) and the FastAPI dependency
# ---------------------------------------------------------------------------


def get_session(request: Request) -> dict[str, Any] | None:
    """Return the active OIDC session payload, or None."""
    try:
        session = request.session.get(OIDC_SESSION_KEY)
    except (AssertionError, AttributeError):
        return None
    return session if isinstance(session, dict) else None


def session_username(settings: Settings, payload: dict[str, Any] | None) -> str | None:
    user = _user_from_payload(payload)
    if user is None:
        return None
    value = user.get(settings.oidc_username_claim)
    if isinstance(value, str) and value:
        return value
    # Fallback chain: email, sub.
    for fallback in ("email", "sub"):
        candidate = user.get(fallback)
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def session_groups(settings: Settings, payload: dict[str, Any] | None) -> list[str]:
    user = _user_from_payload(payload)
    if user is None:
        return []
    raw = user.get(settings.oidc_groups_claim)
    if isinstance(raw, list):
        return [str(g) for g in raw]
    if isinstance(raw, str):
        return [g.strip() for g in raw.split(",") if g.strip()]
    return []


def _user_from_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not payload:
        return None
    user = payload.get("user")
    return user if isinstance(user, dict) else None


def has_required_groups(settings: Settings, groups: list[str]) -> bool:
    required = settings.oidc_required_groups_set
    if not required:
        return True
    return any(g in required for g in groups)


def clear_session(request: Request) -> None:
    try:
        request.session.pop(OIDC_SESSION_KEY, None)
        request.session.pop(PENDING_KEY, None)
    except (AssertionError, AttributeError):
        return


def require_oidc_auth_factory(
    settings: Settings,
    client: OIDCClient,
) -> Callable[[Request], Awaitable[dict[str, Any]]]:
    """Build the FastAPI dependency that enforces OIDC authentication.

    Session expiration is handled by the Starlette signed cookie itself
    (see ``SESSION_LIFETIME_SECONDS``). When it lapses the user is bounced
    to ``/login`` and re-authenticated transparently as long as their SSO
    session at the provider is still active — so we don't need to track
    refresh tokens or run a silent renewal on every request.
    """

    async def _require(request: Request) -> dict[str, Any]:
        payload = get_session(request)
        if payload is None:
            path = request.url.path
            if request.url.query:
                path = f"{path}?{request.url.query}"
            raise HTTPException(
                status_code=303,
                headers={"Location": build_login_redirect(path)},
            )
        groups = session_groups(settings, payload)
        if not has_required_groups(settings, groups):
            raise HTTPException(status_code=403, detail="oidc_group_denied")
        return payload

    return _require
