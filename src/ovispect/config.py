"""Runtime configuration loaded from environment variables (12-factor)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


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

    openvpn_host: str = Field(..., description="Hostname or IP of the OpenVPN management interface.")
    openvpn_port: int = Field(..., ge=1, le=65535, description="TCP port of the management interface.")
    openvpn_password: SecretStr = Field(
        default=SecretStr(""),
        description="Optional management interface password.",
    )

    site_name: str = Field(default="OpenVPN", description="Display name shown in the dashboard header.")
    refresh_seconds: int = Field(default=10, ge=1, le=3600, description="Auto-refresh interval in seconds.")
    timezone: str = Field(default="UTC", description="IANA timezone for displayed timestamps.")
    log_level: LogLevel = Field(default="INFO", description="Application log level.")

    bind_host: str = Field(default="0.0.0.0", description="Address the HTTP server binds to.")  # noqa: S104
    bind_port: int = Field(default=8000, ge=1, le=65535, description="Port the HTTP server binds to.")

    management_timeout_seconds: float = Field(
        default=5.0,
        ge=0.5,
        le=60.0,
        description="Socket timeout when talking to the management interface.",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance.

    Cached so that ``Settings()`` is constructed once per process; tests can
    clear the cache via ``get_settings.cache_clear()`` when needed.
    """
    return Settings()  # type: ignore[call-arg]
