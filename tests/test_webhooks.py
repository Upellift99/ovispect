"""Tests for the webhook formatter and async sender."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from ovispect.config import Settings
from ovispect.events import ClientEvent
from ovispect.ovpn import Client
from ovispect.webhooks import WebhookNotifier, format_payload, sign_body


def _client(common_name: str = "alice") -> Client:
    return Client(
        common_name=common_name,
        real_address="203.0.113.10:51820",
        virtual_address="10.8.0.6",
        virtual_ipv6_address="fd00::1",
        bytes_received=1234567,
        bytes_sent=7654321,
        connected_since="Mon May  6 11:00:00 2026",
        connected_since_t=1714989600,
        username="alice@vpn",
        client_id="42",
        peer_id="0",
        data_channel_cipher="AES-256-GCM",
    )


def _event(kind: str = "connect") -> ClientEvent:
    return ClientEvent(
        kind=kind,  # type: ignore[arg-type]
        occurred_at=datetime(2026, 5, 6, 21, 0, 0, tzinfo=UTC),
        client=_client(),
    )


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "openvpn_host": "127.0.0.1",
        "openvpn_port": 5555,
        "site_name": "Test VPN",
        "webhook_url": "https://example.com/hook",
    }
    base.update(overrides)
    return Settings(**base)


# --- format_payload ------------------------------------------------------


def test_format_generic_includes_full_client_data() -> None:
    payload = format_payload("generic", _event(), site_name="Test VPN")
    assert payload["event"] == "connect"
    assert payload["site_name"] == "Test VPN"
    assert payload["timestamp"] == "2026-05-06T21:00:00+00:00"
    c = payload["client"]
    assert c["common_name"] == "alice"
    assert c["real_address"] == "203.0.113.10:51820"
    assert c["virtual_address"] == "10.8.0.6"
    assert c["bytes_received"] == 1234567
    assert c["client_id"] == "42"
    assert c["country_code"] is None  # no country_for_ip provided


def test_format_generic_includes_country_when_lookup_provided() -> None:
    payload = format_payload(
        "generic", _event(), site_name="Test VPN", country_for_ip=lambda _: "FR"
    )
    assert payload["client"]["country_code"] == "FR"


def test_format_slack_emits_text_field() -> None:
    payload = format_payload("slack", _event(), site_name="Test VPN", country_for_ip=lambda _: "FR")
    assert "text" in payload
    assert "🟢" in payload["text"]
    assert "alice" in payload["text"]
    assert "🇫🇷" in payload["text"]


def test_format_discord_emits_content_field() -> None:
    payload = format_payload("discord", _event("disconnect"), site_name="Test VPN")
    assert "content" in payload
    assert "🔴" in payload["content"]
    assert "disconnected" in payload["content"]


def test_format_gotify_emits_title_message_priority() -> None:
    payload = format_payload("gotify", _event(), site_name="Test VPN")
    assert payload["title"] == "Test VPN"
    assert "alice" in payload["message"]
    assert payload["priority"] == 5


def test_format_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unknown webhook format"):
        format_payload("matrix", _event(), site_name="Test VPN")


# --- HMAC signing --------------------------------------------------------


def test_sign_body_returns_sha256_hmac() -> None:
    body = b'{"event":"connect"}'
    secret = "swordfish"  # pragma: allowlist secret
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    assert sign_body(body, secret) == f"sha256={expected}"


# --- WebhookNotifier -----------------------------------------------------


async def test_notifier_posts_to_url() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(204)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        notifier = WebhookNotifier(_settings(), http_client=client)
        ok = await notifier.send(_event())
        assert ok is True
    assert len(captured) == 1
    assert str(captured[0].url) == "https://example.com/hook"
    body = json.loads(captured[0].content)
    assert body["event"] == "connect"


async def test_notifier_signs_when_secret_set() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    secret = "topsecret"  # pragma: allowlist secret
    settings = _settings(webhook_secret=secret)
    async with httpx.AsyncClient(transport=transport) as client:
        notifier = WebhookNotifier(settings, http_client=client)
        await notifier.send(_event())

    sig_header = captured[0].headers.get("x-ovispect-signature")
    expected = (
        "sha256=" + hmac.new(secret.encode(), captured[0].content, hashlib.sha256).hexdigest()
    )
    assert sig_header == expected


async def test_notifier_retries_on_5xx_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 2:
            return httpx.Response(503)
        return httpx.Response(200)

    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        notifier = WebhookNotifier(_settings(), http_client=client)
        ok = await notifier.send(_event())
        assert ok is True
    assert attempts["n"] == 2


async def test_notifier_does_not_retry_on_4xx() -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        notifier = WebhookNotifier(_settings(webhook_max_retries=5), http_client=client)
        ok = await notifier.send(_event())
        assert ok is False
    assert attempts["n"] == 1


async def test_notifier_includes_country_in_slack_text() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    settings = _settings(webhook_format="slack")
    async with httpx.AsyncClient(transport=transport) as client:
        notifier = WebhookNotifier(settings, country_for_ip=lambda _: "FR", http_client=client)
        await notifier.send(_event())
    body = json.loads(captured[0].content)
    assert "🇫🇷" in body["text"]
