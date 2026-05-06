"""Tests for the ``status 3`` TSV parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from ovispect.ovpn import Client, parse_status3

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_payload() -> str:
    return (FIXTURES / "status3_sample.txt").read_text(encoding="utf-8")


def test_parses_three_clients(sample_payload: str) -> None:
    clients = parse_status3(sample_payload)
    assert len(clients) == 3
    assert all(isinstance(c, Client) for c in clients)


def test_first_client_fields_match_fixture(sample_payload: str) -> None:
    clients = parse_status3(sample_payload)
    alice = clients[0]
    assert alice.common_name == "alice@example.com"
    assert alice.real_address == "203.0.113.10:51820"
    assert alice.virtual_address == "10.8.0.6"
    assert alice.bytes_received == 1234567
    assert alice.bytes_sent == 7654321
    assert alice.connected_since_t == 1714989600
    assert alice.username == "UNDEF"
    assert alice.data_channel_cipher == "AES-256-GCM"


def test_ignores_non_client_list_rows(sample_payload: str) -> None:
    clients = parse_status3(sample_payload)
    common_names = [c.common_name for c in clients]
    assert "ROUTING_TABLE" not in common_names
    assert "TITLE" not in common_names


def test_empty_payload_returns_empty_list() -> None:
    assert parse_status3("") == []


def test_skips_malformed_rows() -> None:
    payload = (
        "CLIENT_LIST\tonly\ttoo\tfew\tfields\n"
        "CLIENT_LIST\tgood\t1.2.3.4:1\t10.0.0.1\t\t10\t20\tMon\t1\tu\t1\t0\tAES-256-GCM\n"
    )
    clients = parse_status3(payload)
    assert len(clients) == 1
    assert clients[0].common_name == "good"


def test_skips_rows_with_non_integer_counters() -> None:
    payload = (
        "CLIENT_LIST\tcn\t1.2.3.4:1\t10.0.0.1\t\tNOT_AN_INT\t20\tMon\t1\tu\t1\t0\tAES-256-GCM\n"
    )
    assert parse_status3(payload) == []


def test_handles_crlf_line_endings(sample_payload: str) -> None:
    crlf = sample_payload.replace("\n", "\r\n")
    clients = parse_status3(crlf)
    assert len(clients) == 3
