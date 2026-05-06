"""Tests for connect/disconnect event derivation."""

from __future__ import annotations

from datetime import UTC, datetime

from ovispect.events import client_key, diff_clients
from ovispect.ovpn import Client


def _make(common_name: str, real_address: str, client_id: str = "1") -> Client:
    return Client(
        common_name=common_name,
        real_address=real_address,
        virtual_address="10.8.0.1",
        virtual_ipv6_address="",
        bytes_received=0,
        bytes_sent=0,
        connected_since="Mon May  6 11:00:00 2026",
        connected_since_t=1714989600,
        username="UNDEF",
        client_id=client_id,
        peer_id="0",
        data_channel_cipher="AES-256-GCM",
    )


# --- client_key ----------------------------------------------------------


def test_client_key_uses_client_id_when_defined() -> None:
    c = _make("alice", "1.2.3.4:51820", client_id="42")
    assert client_key(c) == "id:42"


def test_client_key_falls_back_when_client_id_undef() -> None:
    c = _make("alice", "1.2.3.4:51820", client_id="UNDEF")
    assert client_key(c) == "cn:alice|1.2.3.4:51820"


def test_client_key_falls_back_when_client_id_zero() -> None:
    c = _make("alice", "1.2.3.4:51820", client_id="0")
    assert client_key(c) == "cn:alice|1.2.3.4:51820"


def test_client_key_distinguishes_parallel_sessions_same_cn() -> None:
    a = _make("alice", "1.2.3.4:51820", client_id="UNDEF")
    b = _make("alice", "5.6.7.8:51820", client_id="UNDEF")
    assert client_key(a) != client_key(b)


# --- diff_clients --------------------------------------------------------


def test_diff_detects_new_clients() -> None:
    old = [_make("alice", "1.2.3.4:51820", client_id="1")]
    new = [
        _make("alice", "1.2.3.4:51820", client_id="1"),
        _make("bob", "5.6.7.8:51820", client_id="2"),
    ]
    events = diff_clients(old, new)
    assert len(events) == 1
    assert events[0].kind == "connect"
    assert events[0].client.common_name == "bob"


def test_diff_detects_disconnects() -> None:
    old = [
        _make("alice", "1.2.3.4:51820", client_id="1"),
        _make("bob", "5.6.7.8:51820", client_id="2"),
    ]
    new = [_make("alice", "1.2.3.4:51820", client_id="1")]
    events = diff_clients(old, new)
    assert len(events) == 1
    assert events[0].kind == "disconnect"
    assert events[0].client.common_name == "bob"


def test_diff_no_events_when_unchanged() -> None:
    old = [_make("alice", "1.2.3.4:51820", client_id="1")]
    new = [_make("alice", "1.2.3.4:51820", client_id="1")]
    assert diff_clients(old, new) == []


def test_diff_emits_both_connect_and_disconnect() -> None:
    old = [_make("alice", "1.2.3.4:51820", client_id="1")]
    new = [_make("bob", "5.6.7.8:51820", client_id="2")]
    events = diff_clients(old, new)
    kinds = sorted(e.kind for e in events)
    assert kinds == ["connect", "disconnect"]


def test_diff_uses_provided_timestamp() -> None:
    moment = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    old: list[Client] = []
    new = [_make("alice", "1.2.3.4:51820")]
    events = diff_clients(old, new, now=moment)
    assert events[0].occurred_at == moment


def test_diff_handles_session_replacement_keeps_one_disconnect_one_connect() -> None:
    """Same CN reconnecting from a different IP — old session vanishes,
    new session appears."""
    old = [_make("alice", "1.2.3.4:51820", client_id="1")]
    new = [_make("alice", "5.6.7.8:51820", client_id="2")]
    events = diff_clients(old, new)
    assert {e.kind for e in events} == {"connect", "disconnect"}
    by_kind = {e.kind: e for e in events}
    assert by_kind["connect"].client.real_address == "5.6.7.8:51820"
    assert by_kind["disconnect"].client.real_address == "1.2.3.4:51820"
