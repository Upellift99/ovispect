"""Webhook delivery for connect/disconnect events.

A :class:`WebhookNotifier` wraps an :mod:`httpx` async client, formats a
:class:`~ovispect.events.ClientEvent` for the configured target
(generic JSON, Slack, Discord, or Gotify), optionally signs the body
with HMAC-SHA256, and POSTs it with bounded retries.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from collections.abc import Callable
from typing import Any

import httpx

from ovispect.config import Settings
from ovispect.events import ClientEvent
from ovispect.formatting import strip_port
from ovispect.geo import country_flag, extract_ip

logger = logging.getLogger(__name__)

CountryLookup = Callable[[str], str | None]


def _action_text(event: ClientEvent, country_for_ip: CountryLookup | None) -> str:
    """Render a one-line action sentence shared by Slack/Discord/Gotify."""
    c = event.client
    icon = "🟢" if event.kind == "connect" else "🔴"
    verb = "connected" if event.kind == "connect" else "disconnected"
    cc: str | None = None
    if country_for_ip is not None:
        ip = extract_ip(c.real_address)
        if ip:
            cc = country_for_ip(ip)
    flag = country_flag(cc)
    flag_part = f"{flag} " if flag else ""
    real = strip_port(c.real_address)
    virt = c.virtual_address or "—"
    return f"{icon} {c.common_name} {verb} ({flag_part}{real} → {virt})"


def _generic_payload(
    event: ClientEvent,
    site_name: str,
    country_for_ip: CountryLookup | None,
) -> dict[str, Any]:
    c = event.client
    cc: str | None = None
    if country_for_ip is not None:
        ip = extract_ip(c.real_address)
        if ip:
            cc = country_for_ip(ip)
    return {
        "event": event.kind,
        "site_name": site_name,
        "timestamp": event.occurred_at.isoformat(),
        "client": {
            "common_name": c.common_name,
            "real_address": c.real_address,
            "virtual_address": c.virtual_address,
            "virtual_ipv6_address": c.virtual_ipv6_address,
            "country_code": cc,
            "username": c.username,
            "client_id": c.client_id,
            "peer_id": c.peer_id,
            "data_channel_cipher": c.data_channel_cipher,
            "bytes_received": c.bytes_received,
            "bytes_sent": c.bytes_sent,
            "connected_since": c.connected_since,
            "connected_since_t": c.connected_since_t,
        },
    }


def format_payload(
    fmt: str,
    event: ClientEvent,
    *,
    site_name: str,
    country_for_ip: CountryLookup | None = None,
) -> dict[str, Any]:
    """Build the JSON body for a webhook in the requested ``fmt``.

    Supported formats: ``generic``, ``slack``, ``discord``, ``gotify``.
    Unknown formats raise :class:`ValueError`.
    """
    if fmt == "generic":
        return _generic_payload(event, site_name, country_for_ip)
    text = _action_text(event, country_for_ip)
    if fmt == "slack":
        return {"text": text}
    if fmt == "discord":
        return {"content": text}
    if fmt == "gotify":
        return {"title": site_name, "message": text, "priority": 5}
    raise ValueError(f"unknown webhook format: {fmt}")


def sign_body(body: bytes, secret: str) -> str:
    """Return the ``sha256=<hex>`` HMAC of *body* with *secret*."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


class WebhookNotifier:
    """Async webhook sender. Owns its :class:`httpx.AsyncClient`."""

    def __init__(
        self,
        settings: Settings,
        *,
        country_for_ip: CountryLookup | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._country_for_ip = country_for_ip
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(
            timeout=settings.webhook_timeout_seconds,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def send(self, event: ClientEvent) -> bool:
        """POST *event* to the configured webhook. Returns True on success.

        Retries on connection errors and 5xx responses with exponential
        backoff (capped at ~10s). 4xx responses are not retried (the
        receiver explicitly refused).
        """
        cfg = self._settings
        url = cfg.webhook_url.strip()
        if not url:
            return False
        payload = format_payload(
            cfg.webhook_format,
            event,
            site_name=cfg.site_name,
            country_for_ip=self._country_for_ip,
        )
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers: dict[str, str] = {"Content-Type": "application/json; charset=utf-8"}
        secret = cfg.webhook_secret.get_secret_value()
        if secret:
            headers["X-Ovispect-Signature"] = sign_body(body, secret)

        last_error: str | None = None
        for attempt in range(cfg.webhook_max_retries):
            try:
                response = await self._client.post(url, content=body, headers=headers)
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "webhook attempt %d/%d failed: %s",
                    attempt + 1,
                    cfg.webhook_max_retries,
                    last_error,
                )
            else:
                if response.status_code < 400:
                    return True
                if response.status_code < 500:
                    logger.warning(
                        "webhook rejected with HTTP %d (not retrying): %s",
                        response.status_code,
                        response.text[:200],
                    )
                    return False
                last_error = f"HTTP {response.status_code}"
                logger.warning(
                    "webhook attempt %d/%d server error: %s",
                    attempt + 1,
                    cfg.webhook_max_retries,
                    last_error,
                )
            await asyncio.sleep(min(2**attempt, 10))

        logger.warning(
            "webhook delivery giving up after %d attempts: %s", cfg.webhook_max_retries, last_error
        )
        return False
