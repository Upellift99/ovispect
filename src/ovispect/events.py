"""Connect/disconnect events derived from snapshot diffs.

The webhook background task polls the OpenVPN management interface on
its own cadence and asks :func:`diff_clients` to compute the events to
ship. The function is pure: it operates on two ordered lists of
:class:`~ovispect.ovpn.Client` and emits a stable list of
:class:`ClientEvent`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from ovispect.ovpn import Client

EventKind = Literal["connect", "disconnect"]


@dataclass(frozen=True, slots=True)
class ClientEvent:
    """A connection-lifecycle event captured by diffing two snapshots."""

    kind: EventKind
    occurred_at: datetime
    client: Client


def client_key(client: Client) -> str:
    """Return a stable identity for a client across snapshots.

    OpenVPN's ``client_id`` is unique per session when defined and not
    placeholder (``UNDEF``/``0``). Otherwise we fall back to the
    ``(common_name, real_address)`` tuple, which still distinguishes two
    parallel sessions of the same user.
    """
    cid = (client.client_id or "").strip()
    if cid and cid not in ("UNDEF", "0"):
        return f"id:{cid}"
    return f"cn:{client.common_name}|{client.real_address}"


def diff_clients(
    old: list[Client],
    new: list[Client],
    *,
    now: datetime | None = None,
) -> list[ClientEvent]:
    """Return the connect/disconnect events between two snapshots.

    The return order is deterministic: connects first (in the order they
    appear in ``new``), then disconnects (in the order they appeared in
    ``old``).
    """
    timestamp = now if now is not None else datetime.now(tz=UTC)
    old_by_key = {client_key(c): c for c in old}
    new_by_key = {client_key(c): c for c in new}

    events: list[ClientEvent] = []
    for c in new:
        key = client_key(c)
        if key not in old_by_key:
            events.append(ClientEvent(kind="connect", occurred_at=timestamp, client=c))
    for c in old:
        key = client_key(c)
        if key not in new_by_key:
            events.append(ClientEvent(kind="disconnect", occurred_at=timestamp, client=c))
    return events
