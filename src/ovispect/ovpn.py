"""Client for OpenVPN's text-based management interface.

The management interface speaks a telnet-style protocol over TCP. ovispect
only needs the ``status 3`` command (TSV-formatted client list), so the
client is intentionally minimal: connect, optional password, ``status 3``,
``quit``. Everything is parsed in-process; no shell-out, no deps.
"""

from __future__ import annotations

import logging
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_END_MARKER = b"\nEND\n"
_RECV_CHUNK = 4096


class ManagementError(Exception):
    """Raised when communication with the management interface fails."""


@dataclass(frozen=True, slots=True)
class Client:
    """A single connected OpenVPN client.

    Field order mirrors the columns of ``status 3`` so that constructing this
    from a parsed line is straightforward.
    """

    common_name: str
    real_address: str
    virtual_address: str
    virtual_ipv6_address: str
    bytes_received: int
    bytes_sent: int
    connected_since: str
    connected_since_t: int
    username: str
    client_id: str
    peer_id: str
    data_channel_cipher: str


@dataclass(frozen=True, slots=True)
class StatusSnapshot:
    """A point-in-time view of the OpenVPN server."""

    fetched_at: datetime
    clients: list[Client] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def total_bytes_received(self) -> int:
        return sum(c.bytes_received for c in self.clients)

    @property
    def total_bytes_sent(self) -> int:
        return sum(c.bytes_sent for c in self.clients)


def parse_status3(payload: str) -> list[Client]:
    """Parse a ``status 3`` response payload into a list of :class:`Client`.

    Only ``CLIENT_LIST`` rows are kept; ``HEADER``, ``ROUTING_TABLE``,
    ``GLOBAL_STATS``, ``TIME``, and ``END`` are ignored. Malformed rows
    (wrong column count, non-integer counters) are skipped with a warning
    rather than aborting the whole parse — a single corrupt row should not
    blank out the dashboard.
    """
    clients: list[Client] = []
    for raw in payload.splitlines():
        line = raw.rstrip("\r")
        if not line.startswith("CLIENT_LIST\t"):
            continue
        fields = line.split("\t")
        if len(fields) < 13:
            logger.warning("skipping malformed CLIENT_LIST row (got %d fields)", len(fields))
            continue
        try:
            client = Client(
                common_name=fields[1],
                real_address=fields[2],
                virtual_address=fields[3],
                virtual_ipv6_address=fields[4],
                bytes_received=int(fields[5]),
                bytes_sent=int(fields[6]),
                connected_since=fields[7],
                connected_since_t=int(fields[8]),
                username=fields[9],
                client_id=fields[10],
                peer_id=fields[11],
                data_channel_cipher=fields[12],
            )
        except ValueError:
            logger.warning("skipping CLIENT_LIST row with non-integer counters: %r", fields[:3])
            continue
        clients.append(client)
    return clients


def _recv_until(sock: socket.socket, marker: bytes, timeout: float) -> bytes:
    """Read from ``sock`` until ``marker`` is observed in the cumulative buffer.

    Raises :class:`ManagementError` on timeout or premature EOF.
    """
    sock.settimeout(timeout)
    buffer = bytearray()
    while marker not in buffer:
        try:
            chunk = sock.recv(_RECV_CHUNK)
        except TimeoutError as exc:
            raise ManagementError("timed out waiting for management response") from exc
        except OSError as exc:
            raise ManagementError(f"socket error: {exc}") from exc
        if not chunk:
            raise ManagementError("connection closed before end marker")
        buffer.extend(chunk)
    return bytes(buffer)


def query_management(
    host: str,
    port: int,
    *,
    password: str = "",
    timeout: float = 5.0,
) -> str:
    """Connect to the management interface and return the raw ``status 3`` payload.

    The returned string contains every line emitted between connection setup
    and ``END`` (exclusive), suitable for handing to :func:`parse_status3`.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            try:
                banner = sock.recv(_RECV_CHUNK)
            except TimeoutError as exc:
                raise ManagementError("timed out reading management banner") from exc

            if password:
                if b"PASSWORD" not in banner.upper():
                    logger.debug("password configured but no PASSWORD prompt seen; sending anyway")
                sock.sendall(password.encode("utf-8") + b"\n")
                auth_response = _recv_until(sock, b"\n", timeout)
                if b"FAILED" in auth_response.upper() or b"ERROR" in auth_response.upper():
                    raise ManagementError("management authentication failed")

            sock.sendall(b"status 3\n")
            raw = _recv_until(sock, _END_MARKER, timeout)

            try:
                sock.sendall(b"quit\n")
            except OSError:
                pass

            text = raw.decode("utf-8", errors="replace")
            end_idx = text.rfind("\nEND\n")
            return text[:end_idx] if end_idx != -1 else text
    except ManagementError:
        raise
    except (TimeoutError, ConnectionRefusedError, OSError) as exc:
        raise ManagementError(f"failed to query management interface: {exc}") from exc


def fetch_status(
    host: str,
    port: int,
    *,
    password: str = "",
    timeout: float = 5.0,
) -> StatusSnapshot:
    """High-level helper that returns a :class:`StatusSnapshot`, never raises.

    On any error this returns a snapshot with ``error`` set and an empty
    client list, so callers (i.e. the FastAPI route) can render gracefully.
    """
    fetched_at = datetime.now(tz=timezone.utc)
    try:
        payload = query_management(host, port, password=password, timeout=timeout)
    except ManagementError as exc:
        message = str(exc)
        logger.warning("management query failed: %s", message)
        return StatusSnapshot(fetched_at=fetched_at, clients=[], error=message[:200])

    clients = parse_status3(payload)
    return StatusSnapshot(fetched_at=fetched_at, clients=clients, error=None)
