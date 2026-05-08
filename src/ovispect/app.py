"""FastAPI application: routes, templating, authentication, and Prometheus."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from ovispect import __version__
from ovispect import oidc as oidc_module
from ovispect.auth import (
    LoginRateLimiter,
    build_login_redirect,
    clear_session,
    client_ip,
    is_auth_enabled,
    is_authenticated,
    is_safe_next,
    mark_authenticated,
    require_auth_factory,
    verify_password,
)
from ovispect.config import Settings, get_settings
from ovispect.events import diff_clients
from ovispect.formatting import (
    format_local_time,
    humanize_bytes,
    humanize_duration,
    seconds_since,
    strip_port,
)
from ovispect.geo import country_flag, extract_ip, get_database
from ovispect.oidc import (
    OIDCClient,
    OIDCError,
    init_oidc_client,
    require_oidc_auth_factory,
    session_groups,
    session_username,
)
from ovispect.ovpn import Client, StatusSnapshot, fetch_status
from ovispect.webhooks import WebhookNotifier

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _resolve_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        logger.warning("unknown timezone %r, falling back to UTC", name)
        return ZoneInfo("UTC")


CountryLookup = Callable[[str], str | None]


def _format_client_row(
    client: Client,
    *,
    now: datetime,
    country_lookup: CountryLookup | None = None,
) -> dict[str, Any]:
    """Serialize a :class:`Client` for the dashboard.

    Both raw integers (for client-side sorting) and pre-humanized strings
    (for direct display) are emitted, so the same payload can drive the
    SSR template *and* the JSON API.
    """
    connected_for = seconds_since(client.connected_since_t, now=now)
    country_code: str | None = None
    if country_lookup is not None:
        ip = extract_ip(client.real_address)
        if ip:
            country_code = country_lookup(ip)
    return {
        "common_name": client.common_name,
        "real_address_short": strip_port(client.real_address),
        "real_address_full": client.real_address,
        "virtual_address": client.virtual_address or "—",
        "virtual_ipv6_address": client.virtual_ipv6_address,
        "bytes_received": client.bytes_received,
        "bytes_received_human": humanize_bytes(client.bytes_received),
        "bytes_sent": client.bytes_sent,
        "bytes_sent_human": humanize_bytes(client.bytes_sent),
        "connected_for_seconds": connected_for,
        "connected_relative": humanize_duration(connected_for),
        "connected_absolute": client.connected_since,
        "username": client.username,
        "client_id": client.client_id,
        "peer_id": client.peer_id,
        "data_channel_cipher": client.data_channel_cipher,
        "country_code": country_code,
        "country_flag": country_flag(country_code),
    }


def _build_snapshot_payload(settings: Settings, snapshot: StatusSnapshot) -> dict[str, Any]:
    """JSON-serializable view of the snapshot, shared by SSR and the JSON API."""
    tz = _resolve_timezone(settings.timezone)
    now = datetime.now(tz=UTC)
    age_seconds = max(int((now - snapshot.fetched_at).total_seconds()), 0)
    db = get_database(settings.geoip_database_path)
    country_lookup: CountryLookup | None = db.lookup if db is not None else None
    return {
        "fetched_at_iso": snapshot.fetched_at.isoformat(),
        "fetched_at_local": format_local_time(snapshot.fetched_at, tz=tz),
        "is_stale": age_seconds > 30,
        "is_error": snapshot.error is not None,
        "error": snapshot.error,
        "clients_connected": len(snapshot.clients),
        "total_bytes_received": snapshot.total_bytes_received,
        "total_bytes_sent": snapshot.total_bytes_sent,
        "total_bytes_received_human": humanize_bytes(snapshot.total_bytes_received),
        "total_bytes_sent_human": humanize_bytes(snapshot.total_bytes_sent),
        "clients": [
            _format_client_row(c, now=now, country_lookup=country_lookup) for c in snapshot.clients
        ],
    }


def _build_view_model(
    settings: Settings,
    snapshot: StatusSnapshot,
    *,
    auth_enabled: bool,
    username: str | None = None,
) -> dict[str, Any]:
    payload = _build_snapshot_payload(settings, snapshot)
    return {
        "site_name": settings.site_name,
        "refresh_seconds": settings.refresh_seconds,
        "version": __version__,
        "fetched_at_local": payload["fetched_at_local"],
        "fetched_at_iso": payload["fetched_at_iso"],
        "is_stale": payload["is_stale"],
        "is_error": payload["is_error"],
        "error_message": payload["error"],
        "clients_connected": payload["clients_connected"],
        "rows": payload["clients"],
        "total_bytes_received_human": payload["total_bytes_received_human"],
        "total_bytes_sent_human": payload["total_bytes_sent_human"],
        "show_logout": auth_enabled,
        "username": username,
        "geoip_attribution": get_database(settings.geoip_database_path) is not None,
    }


def _upstream_username(request: Request) -> str | None:
    """Extract a user identifier from common reverse-proxy auth headers.

    Supports oauth2-proxy's ``X-Auth-Request-User`` /
    ``X-Auth-Request-Preferred-Username`` and a few neighbours. Best-effort
    only; ovispect does not enforce anything in upstream-trust mode.
    """
    for header in (
        "x-auth-request-preferred-username",
        "x-auth-request-user",
        "remote-user",
        "x-forwarded-user",
    ):
        value = request.headers.get(header)
        if value:
            return value.strip() or None
    return None


async def _webhook_poll_loop(cfg: Settings, notifier: WebhookNotifier) -> None:
    """Poll the management interface and forward connect/disconnect events.

    Runs forever (until cancelled by the lifespan teardown). Errors during
    a single iteration are logged and never bubble up — the loop sleeps
    and retries on the next tick.
    """
    last_clients: list[Client] | None = None
    enabled_kinds = cfg.webhook_event_kinds
    while True:
        try:
            snapshot = await asyncio.to_thread(
                fetch_status,
                cfg.openvpn_host,
                cfg.openvpn_port,
                password=cfg.openvpn_password.get_secret_value(),
                timeout=cfg.management_timeout_seconds,
            )
            if snapshot.error is None:
                if last_clients is not None:
                    for event in diff_clients(last_clients, snapshot.clients):
                        if event.kind in enabled_kinds:
                            await notifier.send(event)
                last_clients = list(snapshot.clients)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("webhook poll iteration failed")
        await asyncio.sleep(cfg.webhook_poll_seconds)


def _make_lifespan(cfg: Settings) -> Callable[[FastAPI], Any]:
    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if not cfg.webhook_enabled:
            yield
            return
        db = get_database(cfg.geoip_database_path)
        country_for_ip = db.lookup if db is not None else None
        notifier = WebhookNotifier(cfg, country_for_ip=country_for_ip)
        task = asyncio.create_task(_webhook_poll_loop(cfg, notifier))
        logger.info(
            "Webhook poll loop started (every %ds → %s, format=%s, events=%s)",
            cfg.webhook_poll_seconds,
            cfg.webhook_url,
            cfg.webhook_format,
            sorted(cfg.webhook_event_kinds),
        )
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            await notifier.close()

    return lifespan


def create_app(settings: Settings | None = None) -> FastAPI:  # noqa: PLR0915
    """Application factory.

    Tests can pass a custom :class:`Settings` instance to avoid touching
    environment variables. Production code calls :func:`get_settings`.
    """
    cfg = settings if settings is not None else get_settings()
    mode = cfg.auth_mode
    auth_enabled = mode != "upstream"

    if mode == "oidc" and is_auth_enabled(cfg):
        logger.warning(
            "Both OIDC_ISSUER_URL and AUTH_PASSWORD_HASH are configured —"
            " AUTH_PASSWORD_HASH is ignored in OIDC mode."
        )

    oidc_client: OIDCClient | None = None
    if mode == "oidc":
        oidc_client = init_oidc_client(cfg)
        if oidc_client is None:  # pragma: no cover - guarded by config validation
            raise RuntimeError("OIDC mode requested but client initialisation returned None")
        logger.info("Authentication mode: OIDC (issuer: %s)", oidc_client.discovery.issuer)
    elif mode == "builtin":
        logger.info("Authentication mode: built-in (single user: %s)", cfg.auth_username)
    else:
        logger.info("Authentication mode: trust upstream (no built-in authentication)")

    application = FastAPI(
        title="ovispect",
        description="A lightweight dashboard for OpenVPN's management interface.",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=_make_lifespan(cfg),
    )

    application.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    if auth_enabled:
        application.add_middleware(
            SessionMiddleware,
            secret_key=cfg.session_secret.get_secret_value(),
            session_cookie=cfg.session_cookie_name,
            max_age=cfg.session_lifetime_seconds,
            same_site="lax" if mode == "oidc" else "strict",
            https_only=cfg.session_cookie_secure,
        )

    require_auth: Any
    if mode == "oidc":
        assert oidc_client is not None
        require_auth = require_oidc_auth_factory(cfg, oidc_client)
    else:
        require_auth = require_auth_factory(cfg)
    rate_limiter = LoginRateLimiter()

    @application.get("/healthz", response_class=JSONResponse)
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    def _resolve_username(request: Request) -> str | None:
        if mode == "oidc":
            return session_username(cfg, oidc_module.get_session(request))
        if mode == "builtin":
            return cfg.auth_username
        return _upstream_username(request)

    @application.get("/", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
    async def index(request: Request) -> Response:
        snapshot = fetch_status(
            cfg.openvpn_host,
            cfg.openvpn_port,
            password=cfg.openvpn_password.get_secret_value(),
            timeout=cfg.management_timeout_seconds,
        )
        context = _build_view_model(
            cfg,
            snapshot,
            auth_enabled=auth_enabled,
            username=_resolve_username(request),
        )
        return templates.TemplateResponse(request, "index.html", context)

    @application.get(
        "/api/clients",
        response_class=JSONResponse,
        dependencies=[Depends(require_auth)],
    )
    async def api_clients() -> dict[str, Any]:
        snapshot = fetch_status(
            cfg.openvpn_host,
            cfg.openvpn_port,
            password=cfg.openvpn_password.get_secret_value(),
            timeout=cfg.management_timeout_seconds,
        )
        return _build_snapshot_payload(cfg, snapshot)

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

    if mode == "oidc":
        assert oidc_client is not None
        _wire_oidc_routes(application, cfg, oidc_client)
        return application

    if mode == "upstream":
        return application

    @application.get("/login", response_class=HTMLResponse)
    async def login_form(request: Request, next: str | None = None) -> Response:
        if is_authenticated(request):
            return RedirectResponse(url="/", status_code=303)
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "site_name": cfg.site_name,
                "version": __version__,
                "next": next if is_safe_next(next) else "",
                "error": None,
            },
        )

    @application.post("/login", response_class=HTMLResponse)
    async def login_submit(
        request: Request,
        username: Annotated[str, Form(...)],
        password: Annotated[str, Form(...)],
        next: Annotated[str, Form()] = "",
    ) -> Response:
        ip = client_ip(request)
        decision = rate_limiter.check(ip)
        if not decision.allowed:
            retry = decision.retry_after
            minutes = max(int(retry.total_seconds() // 60) + 1, 1) if retry else 5
            return templates.TemplateResponse(
                request,
                "login.html",
                {
                    "site_name": cfg.site_name,
                    "version": __version__,
                    "next": next if is_safe_next(next) else "",
                    "error": (
                        f"Too many failed attempts. Try again in {minutes} minute"
                        f"{'s' if minutes != 1 else ''}."
                    ),
                },
                status_code=429,
            )

        expected_user = cfg.auth_username
        expected_hash = cfg.auth_password_hash.get_secret_value()
        if username == expected_user and verify_password(password, expected_hash):
            rate_limiter.reset(ip)
            mark_authenticated(request)
            target = next if is_safe_next(next) else "/"
            return RedirectResponse(url=target, status_code=303)

        rate_limiter.register_failure(ip)
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "site_name": cfg.site_name,
                "version": __version__,
                "next": next if is_safe_next(next) else "",
                "error": "Invalid credentials.",
            },
            status_code=401,
        )

    @application.post("/logout")
    async def logout(request: Request) -> Response:
        clear_session(request)
        return RedirectResponse(url=build_login_redirect(None), status_code=303)

    return application


def _wire_oidc_routes(
    application: FastAPI,
    cfg: Settings,
    client: OIDCClient,
) -> None:
    """Attach /login, /oidc/callback and /logout for OIDC mode."""

    @application.get("/login")
    async def login(request: Request, next: str | None = None) -> Response:
        if oidc_module.get_session(request) is not None:
            return RedirectResponse(url="/", status_code=303)
        try:
            url = client.authorize_redirect(request, next_path=next)
        except (AssertionError, AttributeError):
            # Session middleware not installed — should never happen in OIDC mode.
            raise HTTPException(status_code=500, detail="session_unavailable")  # noqa: B904
        return RedirectResponse(url=url, status_code=303)

    @application.get("/oidc/callback")
    async def callback(
        request: Request,
        code: str | None = None,
        state: str | None = None,
        error: str | None = None,
        error_description: str | None = None,
    ) -> Response:
        if error or not code or not state:
            return _render_login_error(
                request, cfg, reason=error or "missing_parameters", description=error_description
            )
        try:
            result = await client.handle_callback(request, code=code, state=state)
        except OIDCError as exc:
            logger.warning("oidc callback failed: %s", exc.code)
            return _render_login_error(request, cfg, reason=exc.code)

        groups = session_groups(cfg, oidc_module.get_session(request))
        if cfg.oidc_required_groups_set and not any(
            g in cfg.oidc_required_groups_set for g in groups
        ):
            oidc_module.clear_session(request)
            return _render_forbidden(request, cfg, status_code=403)

        target = result["next"] or "/"
        return RedirectResponse(url=target, status_code=303)

    @application.post("/logout")
    async def logout(request: Request) -> Response:
        end_session = client.logout_url(
            request,
            post_logout_redirect_uri=(
                str(cfg.oidc_logout_redirect_uri) if cfg.oidc_logout_redirect_uri else None
            ),
        )
        oidc_module.clear_session(request)
        if end_session is not None:
            return RedirectResponse(url=end_session, status_code=303)
        target = (
            str(cfg.oidc_logout_redirect_uri) if cfg.oidc_logout_redirect_uri is not None else "/"
        )
        return RedirectResponse(url=target, status_code=303)


def _render_login_error(
    request: Request,
    cfg: Settings,
    *,
    reason: str,
    description: str | None = None,
) -> Response:
    request_id = secrets.token_hex(4)
    logger.info("oidc login error rendered (reason=%s, request_id=%s)", reason, request_id)
    return templates.TemplateResponse(
        request,
        "login_error.html",
        {
            "site_name": cfg.site_name,
            "version": __version__,
            "request_id": request_id,
        },
        status_code=400,
    )


def _render_forbidden(
    request: Request,
    cfg: Settings,
    *,
    status_code: int = 403,
) -> Response:
    return templates.TemplateResponse(
        request,
        "forbidden.html",
        {
            "site_name": cfg.site_name,
            "version": __version__,
            "required_groups": sorted(cfg.oidc_required_groups_set),
        },
        status_code=status_code,
    )


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
