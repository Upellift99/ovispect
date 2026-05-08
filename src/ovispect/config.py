"""Runtime configuration loaded from environment variables (12-factor)."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
AuthMode = Literal["oidc", "builtin", "upstream"]

_BCRYPT_HASH_RE = re.compile(r"^\$2[aby]\$\d{2}\$.{53}$")
_MIN_SESSION_SECRET_LENGTH = 32


class Settings(BaseSettings):
    """Application settings.

    All values are sourced from process environment variables. Validation
    failures raise ``pydantic.ValidationError`` at startup, which is the
    intended behavior — fail fast on misconfiguration.
    """

    model_config = SettingsConfigDict(
        env_file=None,
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )

    openvpn_host: str = Field(
        ..., description="Hostname or IP of the OpenVPN management interface."
    )
    openvpn_port: int = Field(
        ..., ge=1, le=65535, description="TCP port of the management interface."
    )
    openvpn_password: SecretStr = Field(
        default=SecretStr(""),
        description="Optional management interface password.",
    )

    site_name: str = Field(
        default="OpenVPN", description="Display name shown in the dashboard header."
    )
    refresh_seconds: int = Field(
        default=10, ge=1, le=3600, description="Auto-refresh interval in seconds."
    )
    timezone: str = Field(default="UTC", description="IANA timezone for displayed timestamps.")
    log_level: LogLevel = Field(default="INFO", description="Application log level.")

    bind_host: str = Field(default="0.0.0.0", description="Address the HTTP server binds to.")
    bind_port: int = Field(
        default=8000, ge=1, le=65535, description="Port the HTTP server binds to."
    )

    management_timeout_seconds: float = Field(
        default=5.0,
        ge=0.5,
        le=60.0,
        description="Socket timeout when talking to the management interface.",
    )

    geoip_database_path: Path | None = Field(
        default=Path("/opt/geo/dbip-country-lite.csv.gz"),
        description=(
            "Path to a db-ip.com Lite Country CSV (optionally .gz). When the"
            " file is absent the country lookup is silently disabled."
        ),
    )

    webhook_url: str = Field(
        default="",
        description=(
            "URL to POST connect/disconnect events to. Empty disables the"
            " webhook background task entirely."
        ),
    )
    webhook_format: Literal["generic", "slack", "discord", "gotify"] = Field(
        default="generic",
        description="Payload shape: generic (full JSON), slack, discord, or gotify.",
    )
    webhook_secret: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "If set, body is signed with HMAC-SHA256 and the digest is sent"
            " as the X-Ovispect-Signature header (sha256=<hex>)."
        ),
    )
    webhook_timeout_seconds: float = Field(
        default=5.0,
        ge=0.5,
        le=60.0,
        description="Per-attempt HTTP timeout for webhook deliveries.",
    )
    webhook_poll_seconds: int = Field(
        default=10,
        ge=1,
        le=3600,
        description=(
            "Backend polling interval for the webhook event loop. May differ"
            " from REFRESH_SECONDS (the UI auto-refresh)."
        ),
    )
    webhook_max_retries: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Number of retry attempts on webhook delivery failure.",
    )
    webhook_events: str = Field(
        default="connect,disconnect",
        description=(
            "Comma-separated list of event kinds to forward. Valid values: connect, disconnect."
        ),
    )

    @property
    def webhook_event_kinds(self) -> frozenset[str]:
        """Parse :attr:`webhook_events` into a validated set of event kinds."""
        items = {x.strip().lower() for x in self.webhook_events.split(",") if x.strip()}
        return frozenset(items & {"connect", "disconnect"})

    @property
    def webhook_enabled(self) -> bool:
        return bool(self.webhook_url.strip()) and bool(self.webhook_event_kinds)

    auth_username: str = Field(
        default="admin",
        min_length=1,
        max_length=100,
        description="Expected username when built-in authentication is enabled.",
    )
    auth_password_hash: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "Bcrypt hash of the operator password. Leave empty to disable built-in"
            " authentication and rely on an upstream reverse proxy instead."
        ),
    )
    session_secret: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "Secret used to sign session cookies. Required (>= 32 chars) when"
            " AUTH_PASSWORD_HASH is set."
        ),
    )
    session_lifetime_seconds: int = Field(
        default=86400,
        ge=60,
        le=30 * 86400,
        description="Session cookie lifetime in seconds.",
    )
    session_cookie_name: str = Field(
        default="ovispect_session",
        min_length=1,
        max_length=64,
        description="Name of the session cookie.",
    )
    session_cookie_secure: bool = Field(
        default=True,
        description=(
            "Set the Secure flag on the session cookie. Disable only for local"
            " plaintext testing without TLS."
        ),
    )

    oidc_issuer_url: AnyHttpUrl | None = Field(
        default=None,
        description=(
            "Base issuer URL of the OIDC provider. Setting this enables Mode 1"
            " (native OIDC) and disables built-in/upstream auth."
        ),
    )
    oidc_client_id: str = Field(
        default="",
        description="OIDC client_id registered with the provider.",
    )
    oidc_client_secret: SecretStr = Field(
        default=SecretStr(""),
        description="OIDC client_secret registered with the provider.",
    )
    oidc_redirect_uri: AnyHttpUrl | None = Field(
        default=None,
        description=(
            "Absolute callback URL the provider redirects to. When unset,"
            " ovispect derives it from the request's Host header + /oidc/callback."
        ),
    )
    oidc_scopes: str = Field(
        default="openid profile email",
        description="Space-separated scopes requested at the authorize endpoint.",
    )
    oidc_username_claim: str = Field(
        default="preferred_username",
        min_length=1,
        max_length=64,
        description="ID-token claim used as the displayed username in the UI.",
    )
    oidc_required_groups: str = Field(
        default="",
        description=(
            "Comma-separated list of groups; when non-empty the user must"
            " be a member of at least one to gain access."
        ),
    )
    oidc_groups_claim: str = Field(
        default="groups",
        min_length=1,
        max_length=64,
        description="Name of the ID-token claim carrying the user's groups.",
    )
    oidc_verify_ssl: bool = Field(
        default=True,
        description="Verify the provider's TLS certificate (keep true in production).",
    )
    oidc_logout_redirect_uri: AnyHttpUrl | None = Field(
        default=None,
        description=(
            "Where to send the user after a provider-side logout. Defaults to"
            " the application root if unset."
        ),
    )

    @field_validator("oidc_required_groups", mode="before")
    @classmethod
    def _coerce_groups(cls, value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, list | tuple | set | frozenset):
            return ",".join(str(v) for v in value)
        return str(value)

    @property
    def oidc_required_groups_set(self) -> frozenset[str]:
        items = {g.strip() for g in self.oidc_required_groups.split(",") if g.strip()}
        return frozenset(items)

    @property
    def oidc_scope_list(self) -> list[str]:
        return [s for s in self.oidc_scopes.split() if s]

    @property
    def oidc_enabled(self) -> bool:
        return (
            self.oidc_issuer_url is not None
            and bool(self.oidc_client_id)
            and bool(self.oidc_client_secret.get_secret_value())
        )

    @property
    def auth_mode(self) -> AuthMode:
        """Active authentication mode.

        Resolution order: OIDC > built-in > upstream. Validated at startup.
        """
        if self.oidc_enabled:
            return "oidc"
        if self.auth_password_hash.get_secret_value():
            return "builtin"
        return "upstream"

    @model_validator(mode="after")
    def _validate_webhook_url(self) -> Self:
        url = self.webhook_url.strip()
        if url and not (url.startswith("http://") or url.startswith("https://")):
            raise ValueError("WEBHOOK_URL must start with http:// or https://")
        return self

    @model_validator(mode="after")
    def _validate_auth_pair(self) -> Self:
        password_hash = self.auth_password_hash.get_secret_value()
        if not password_hash:
            return self
        if not _BCRYPT_HASH_RE.match(password_hash):
            raise ValueError(
                "AUTH_PASSWORD_HASH must be a bcrypt hash (starts with $2a$, $2b$"
                " or $2y$). Use `python -m ovispect.hash_password` to generate one."
            )
        secret = self.session_secret.get_secret_value()
        if len(secret) < _MIN_SESSION_SECRET_LENGTH:
            raise ValueError(
                "SESSION_SECRET must be at least 32 characters when AUTH_PASSWORD_HASH"
                " is set. Generate one with `openssl rand -hex 32`."
            )
        return self

    @model_validator(mode="after")
    def _validate_oidc_pair(self) -> Self:
        if self.oidc_issuer_url is None:
            # If client id / secret are set without an issuer, that's
            # incoherent — surface it early instead of silently ignoring.
            if self.oidc_client_id or self.oidc_client_secret.get_secret_value():
                raise ValueError("OIDC_CLIENT_ID / OIDC_CLIENT_SECRET set without OIDC_ISSUER_URL.")
            return self
        if not self.oidc_client_id:
            raise ValueError("OIDC_CLIENT_ID is required when OIDC_ISSUER_URL is set.")
        if not self.oidc_client_secret.get_secret_value():
            raise ValueError("OIDC_CLIENT_SECRET is required when OIDC_ISSUER_URL is set.")
        secret = self.session_secret.get_secret_value()
        if len(secret) < _MIN_SESSION_SECRET_LENGTH:
            raise ValueError(
                "SESSION_SECRET must be at least 32 characters when OIDC_ISSUER_URL"
                " is set. Generate one with `openssl rand -hex 32`."
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance.

    Cached so that ``Settings()`` is constructed once per process; tests can
    clear the cache via ``get_settings.cache_clear()`` when needed.
    """
    return Settings()  # type: ignore[call-arg]
