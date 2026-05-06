"""Optional built-in authentication: bcrypt password check + session helpers.

Authentication is opt-in. When ``AUTH_PASSWORD_HASH`` is empty, every
helper here either short-circuits (``is_auth_enabled`` returns False) or is
simply not wired into the FastAPI app — ovispect then runs in
"reverse-proxy mode" with no in-app enforcement.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import bcrypt
from fastapi import HTTPException, Request

from ovispect.config import Settings

logger = logging.getLogger(__name__)

SESSION_FLAG = "authenticated"

_DEFAULT_MAX_ATTEMPTS = 5
_DEFAULT_WINDOW = timedelta(minutes=5)
_DEFAULT_LOCKOUT = timedelta(minutes=5)


def is_auth_enabled(settings: Settings) -> bool:
    """Return True iff a non-empty bcrypt hash has been configured."""
    return bool(settings.auth_password_hash.get_secret_value())


def verify_password(plain: str, hashed: str) -> bool:
    """Compare a plaintext password against a bcrypt hash.

    Always swallows ``bcrypt`` errors (malformed hash, decoding issues, …)
    and returns ``False`` so a corrupted env var can never blow up the
    request handler.
    """
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        logger.warning("password verification failed: %s", exc)
        return False


def is_authenticated(request: Request) -> bool:
    """Return True if the current session carries the auth flag.

    Safe to call when the SessionMiddleware is not installed: returns False
    instead of raising.
    """
    try:
        session = request.session
    except (AssertionError, AttributeError):
        return False
    return bool(session.get(SESSION_FLAG))


def mark_authenticated(request: Request) -> None:
    request.session[SESSION_FLAG] = True


def clear_session(request: Request) -> None:
    try:
        request.session.clear()
    except (AssertionError, AttributeError):
        return


def is_safe_next(value: str | None) -> bool:
    """Validate the ``next`` query/form parameter to prevent open redirects.

    Only accept paths that start with a single ``/`` — no scheme, no host,
    no protocol-relative ``//evil.com``.
    """
    if not value:
        return False
    if not value.startswith("/"):
        return False
    return not value.startswith("//")


def build_login_redirect(path: str | None) -> str:
    if path and is_safe_next(path):
        return f"/login?next={quote(path, safe='/')}"
    return "/login"


def client_ip(request: Request, *, trusted_forwarded: bool = True) -> str:
    """Best-effort client IP extraction.

    When ``trusted_forwarded`` is True (the default) and an
    ``X-Forwarded-For`` header is present, use its leftmost value. ovispect
    is intended to be deployed behind a single trusted reverse proxy in
    standalone mode, so this is reasonable; operators in more complex
    setups should configure their proxy to overwrite the header.
    """
    if trusted_forwarded:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            first = forwarded.split(",", 1)[0].strip()
            if first:
                return first
    if request.client is not None:
        return request.client.host
    return "unknown"


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after: timedelta | None = None


class LoginRateLimiter:
    """In-memory per-IP rate limiter for the login endpoint.

    The default policy: at most 5 failed attempts per IP within a 5-minute
    rolling window; once exceeded, further attempts are rejected for an
    additional 5 minutes after the latest failure.

    Process-local on purpose: ovispect is a single-instance dashboard. Use
    a dedicated WAF (BunkerWeb, fail2ban) for fleet-wide protection.
    """

    def __init__(
        self,
        *,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
        window: timedelta = _DEFAULT_WINDOW,
        lockout: timedelta = _DEFAULT_LOCKOUT,
    ) -> None:
        self._max_attempts = max_attempts
        self._window = window
        self._lockout = lockout
        self._failures: dict[str, list[datetime]] = defaultdict(list)
        self._lock = threading.Lock()

    def _purge(self, attempts: list[datetime], cutoff: datetime) -> Iterable[datetime]:
        return [t for t in attempts if t >= cutoff]

    def check(self, key: str, *, now: datetime | None = None) -> RateLimitDecision:
        """Return whether the next attempt for ``key`` should be allowed."""
        ts = now if now is not None else datetime.now(tz=UTC)
        with self._lock:
            attempts = list(self._failures.get(key, ()))
            if not attempts:
                return RateLimitDecision(allowed=True)
            attempts = list(self._purge(attempts, ts - self._window))
            self._failures[key] = attempts
            if len(attempts) < self._max_attempts:
                return RateLimitDecision(allowed=True)
            unlock_at = attempts[-1] + self._lockout
            if ts >= unlock_at:
                self._failures[key] = []
                return RateLimitDecision(allowed=True)
            return RateLimitDecision(allowed=False, retry_after=unlock_at - ts)

    def register_failure(self, key: str, *, now: datetime | None = None) -> None:
        ts = now if now is not None else datetime.now(tz=UTC)
        with self._lock:
            self._failures[key].append(ts)

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


def require_auth_factory(settings: Settings) -> Callable[[Request], None]:
    """Build a FastAPI dependency that enforces authentication.

    Returning a closure (rather than a top-level function) lets us bind the
    enabled/disabled decision once at app construction, avoiding a per-request
    settings lookup.
    """
    enabled = is_auth_enabled(settings)

    def _require_auth(request: Request) -> None:
        if not enabled:
            return
        if is_authenticated(request):
            return
        path = request.url.path
        if request.url.query:
            path = f"{path}?{request.url.query}"
        raise HTTPException(
            status_code=303,
            headers={"Location": build_login_redirect(path)},
        )

    return _require_auth
