"""Tests for the management interface client (socket layer mocked)."""

from __future__ import annotations

import socket
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ovispect.ovpn import ManagementError, fetch_status, query_management


class FakeSocket:
    """Minimal in-memory stand-in for a TCP socket.

    ``responses`` is a list of byte payloads that successive ``recv`` calls
    will drain. Anything sent via ``sendall`` is appended to ``sent``.
    """

    def __init__(self, responses: list[bytes]) -> None:
        self._responses = list(responses)
        self.sent: list[bytes] = []
        self.timeouts: list[float] = []
        self.closed = False

    def settimeout(self, value: float) -> None:
        self.timeouts.append(value)

    def recv(self, _bufsize: int) -> bytes:
        if not self._responses:
            return b""
        return self._responses.pop(0)

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def __enter__(self) -> FakeSocket:
        return self

    def __exit__(self, *_args: Any) -> None:
        self.closed = True


@pytest.fixture
def patch_socket(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Patch ``socket.create_connection`` to return a configurable FakeSocket."""

    def _install(fake: FakeSocket) -> MagicMock:
        mock = MagicMock(return_value=fake)
        monkeypatch.setattr(socket, "create_connection", mock)
        return mock

    return _install


def _status_payload() -> bytes:
    return (
        b"OpenVPN Version: 2.6.x\n"
        b"HEADER\tCLIENT_LIST\tCommon Name\tReal Address\tVirtual Address\t"
        b"Virtual IPv6 Address\tBytes Received\tBytes Sent\tConnected Since\t"
        b"Connected Since (time_t)\tUsername\tClient ID\tPeer ID\tData Channel Cipher\n"
        b"CLIENT_LIST\tdave\t192.0.2.7:60123\t10.8.0.20\t\t100\t200\t"
        b"Mon May  6 12:00:00 2026\t1714993200\tUNDEF\t1\t0\tAES-256-GCM\n"
        b"END\n"
    )


def test_query_management_returns_payload_without_password(patch_socket) -> None:  # type: ignore[no-untyped-def]
    fake = FakeSocket(responses=[b"INFO: hi\n", _status_payload()])
    patch_socket(fake)

    result = query_management("127.0.0.1", 5555)

    assert "CLIENT_LIST\tdave" in result
    assert "END" not in result.splitlines()[-1]
    assert b"status 3\n" in fake.sent
    assert b"quit\n" in fake.sent


def test_query_management_sends_password_when_configured(patch_socket) -> None:  # type: ignore[no-untyped-def]
    fake = FakeSocket(
        responses=[
            b"ENTER PASSWORD:\n",
            b"SUCCESS: password is correct\n",
            _status_payload(),
        ]
    )
    patch_socket(fake)

    query_management("127.0.0.1", 5555, password="hunter2")  # pragma: allowlist secret

    assert b"hunter2\n" in fake.sent  # pragma: allowlist secret


def test_query_management_raises_on_auth_failure(patch_socket) -> None:  # type: ignore[no-untyped-def]
    fake = FakeSocket(
        responses=[
            b"ENTER PASSWORD:\n",
            b"ERROR: bad password\n",
        ]
    )
    patch_socket(fake)

    with pytest.raises(ManagementError, match="authentication failed"):
        query_management("127.0.0.1", 5555, password="wrong")  # pragma: allowlist secret


def test_query_management_raises_when_connection_refused() -> None:
    with (
        patch.object(
            socket,
            "create_connection",
            side_effect=ConnectionRefusedError("refused"),
        ),
        pytest.raises(ManagementError, match="failed to query"),
    ):
        query_management("127.0.0.1", 1)


def test_query_management_raises_on_premature_eof(patch_socket) -> None:  # type: ignore[no-untyped-def]
    fake = FakeSocket(responses=[b"INFO: hi\n", b"partial chunk without end marker"])
    patch_socket(fake)

    with pytest.raises(ManagementError, match="closed before end marker"):
        query_management("127.0.0.1", 5555)


def test_query_management_raises_on_recv_timeout(patch_socket) -> None:  # type: ignore[no-untyped-def]
    class TimingOutSocket(FakeSocket):
        def recv(self, _bufsize: int) -> bytes:
            raise TimeoutError("simulated timeout")

    patch_socket(TimingOutSocket(responses=[]))

    with pytest.raises(ManagementError, match="timed out"):
        query_management("127.0.0.1", 5555)


def test_fetch_status_returns_error_snapshot_on_failure() -> None:
    with patch.object(
        socket,
        "create_connection",
        side_effect=ConnectionRefusedError("refused"),
    ):
        snapshot = fetch_status("127.0.0.1", 1)

    assert not snapshot.ok
    assert snapshot.error is not None
    assert snapshot.clients == []


def test_fetch_status_parses_clients_on_success(patch_socket) -> None:  # type: ignore[no-untyped-def]
    fake = FakeSocket(responses=[b"INFO: hi\n", _status_payload()])
    patch_socket(fake)

    snapshot = fetch_status("127.0.0.1", 5555)

    assert snapshot.ok
    assert len(snapshot.clients) == 1
    assert snapshot.clients[0].common_name == "dave"
    assert snapshot.total_bytes_received == 100
    assert snapshot.total_bytes_sent == 200
