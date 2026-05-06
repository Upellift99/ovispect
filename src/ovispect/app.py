"""FastAPI application: routes, templating, and Prometheus exposition."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.templating import Jinja2Templates

from ovispect import __version__
from ovispect.config import Settings, get_settings
from ovispect.formatting import (
    format_local_time,
    humanize_bytes,
    humanize_duration,
    seconds_since,
    strip_port,
)
from ovispect.ovpn import StatusSnapshot, fetch_status

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _resolve_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        logger.warning("unknown timezone %r, falling back to UTC", name)
        return ZoneInfo("UTC")


def _build_view_model(settings: Settings, snapshot: StatusSnapshot) -> dict[str, Any]:
    tz = _resolve_timezone(settings.timezone)
    now = datetime.now(tz=timezone.utc)
    age_seconds = max(int((now - snapshot.fetched_at).total_seconds()), 0)
    is_stale = age_seconds > 30

    rows: list[dict[str, Any]] = []
    for client in snapshot.clients:
        connected_for = seconds_since(client.connected_since_t, now=now)
        rows.append(
            {
                "common_name": client.common_name,
                "real_address_short": strip_port(client.real_address),
                "real_address_full": client.real_address,
                "virtual_address": client.virtual_address or "—",
                "bytes_received": humanize_bytes(client.bytes_received),
                "bytes_sent": humanize_bytes(client.bytes_sent),
                "connected_relative": humanize_duration(connected_for),
                "connected_absolute": client.connected_since,
                "username": client.username,
            }
        )

    return {
        "site_name": settings.site_name,
        "refresh_seconds": settings.refresh_seconds,
        "version": __version__,
        "fetched_at_local": format_local_time(snapshot.fetched_at, tz=tz),
        "fetched_at_iso": snapshot.fetched_at.isoformat(),
        "is_stale": is_stale,
        "is_error": snapshot.error is not None,
        "error_message": snapshot.error,
        "clients_connected": len(snapshot.clients),
        "rows": rows,
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    """Application factory.

    Tests can pass a custom :class:`Settings` instance to avoid touching
    environment variables. Production code calls :func:`get_settings`.
    """
    cfg = settings if settings is not None else get_settings()
    application = FastAPI(
        title="ovispect",
        description="A lightweight dashboard for OpenVPN's management interface.",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @application.get("/healthz", response_class=JSONResponse)
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    @application.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> Response:
        snapshot = fetch_status(
            cfg.openvpn_host,
            cfg.openvpn_port,
            password=cfg.openvpn_password.get_secret_value(),
            timeout=cfg.management_timeout_seconds,
        )
        context = _build_view_model(cfg, snapshot)
        return templates.TemplateResponse(request, "index.html", context)

    @application.get("/metrics", response_class=PlainTextResponse)
    async def metrics() -> Response:
        snapshot = fetch_status(
            cfg.openvpn_host,
            cfg.openvpn_port,
            password=cfg.openvpn_password.get_secret_value(),
            timeout=cfg.management_timeout_seconds,
        )
        body = _render_prometheus(snapshot)
        return PlainTextResponse(body, media_type="text/plain; version=0.0.4")

    return application


def _render_prometheus(snapshot: StatusSnapshot) -> str:
    """Render a minimal Prometheus exposition for the current snapshot."""
    up_value = 0 if snapshot.error else 1
    lines = [
        "# HELP ovispect_up 1 if the last management query succeeded, 0 otherwise.",
        "# TYPE ovispect_up gauge",
        f"ovispect_up {up_value}",
        "# HELP ovispect_clients_connected Number of currently connected clients.",
        "# TYPE ovispect_clients_connected gauge",
        f"ovispect_clients_connected {len(snapshot.clients)}",
        "# HELP ovispect_bytes_received_total Bytes received across all active clients.",
        "# TYPE ovispect_bytes_received_total counter",
        f"ovispect_bytes_received_total {snapshot.total_bytes_received}",
        "# HELP ovispect_bytes_sent_total Bytes sent across all active clients.",
        "# TYPE ovispect_bytes_sent_total counter",
        f"ovispect_bytes_sent_total {snapshot.total_bytes_sent}",
    ]
    return "\n".join(lines) + "\n"
