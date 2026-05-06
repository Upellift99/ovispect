"""Pure functions to humanize bytes, durations, and addresses for the UI."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

_BYTE_UNITS: tuple[str, ...] = ("B", "KB", "MB", "GB", "TB", "PB", "EB")


def humanize_bytes(value: int) -> str:
    """Return a human-readable size string.

    Uses 1024-based units. ``< 1024`` is reported with the raw byte count and
    the ``B`` suffix; larger values are reported with one fractional digit.

    >>> humanize_bytes(0)
    '0 B'
    >>> humanize_bytes(1023)
    '1023 B'
    >>> humanize_bytes(1024)
    '1.0 KB'
    >>> humanize_bytes(1536)
    '1.5 KB'
    """
    if value < 0:
        raise ValueError("byte count cannot be negative")
    if value < 1024:
        return f"{value} B"

    size = float(value)
    for unit in _BYTE_UNITS[1:]:
        size /= 1024
        if size < 1024:
            return f"{size:.1f} {unit}"
    return f"{size:.1f} {_BYTE_UNITS[-1]}"


def humanize_duration(seconds: int) -> str:
    """Return a compact relative duration like ``45s``, ``12m``, ``2h 14m``, ``3d 4h``.

    >>> humanize_duration(0)
    '0s'
    >>> humanize_duration(45)
    '45s'
    >>> humanize_duration(60)
    '1m'
    >>> humanize_duration(8054)
    '2h 14m'
    >>> humanize_duration(90061)
    '1d 1h'
    """
    if seconds < 0:
        raise ValueError("duration cannot be negative")
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        hours, rem = divmod(seconds, 3600)
        minutes = rem // 60
        if minutes == 0:
            return f"{hours}h"
        return f"{hours}h {minutes}m"
    days, rem = divmod(seconds, 86400)
    hours = rem // 3600
    if hours == 0:
        return f"{days}d"
    return f"{days}d {hours}h"


def strip_port(real_address: str) -> str:
    """Remove the trailing ``:port`` from ``host:port`` while preserving IPv6 brackets.

    >>> strip_port('1.2.3.4:51820')
    '1.2.3.4'
    >>> strip_port('[2001:db8::1]:51820')
    '[2001:db8::1]'
    >>> strip_port('not-a-real-address')
    'not-a-real-address'
    """
    if real_address.startswith("[") and "]" in real_address:
        host, _, _ = real_address.partition("]")
        return host + "]"
    if real_address.count(":") == 1:
        host, _, _ = real_address.partition(":")
        return host
    return real_address


def format_local_time(dt: datetime, tz: timezone | None = None) -> str:
    """Format a datetime as ``HH:MM:SS`` in the supplied timezone (UTC by default)."""
    target = tz if tz is not None else timezone.utc
    return dt.astimezone(target).strftime("%H:%M:%S")


def seconds_since(epoch: int, *, now: datetime | None = None) -> int:
    """Return whole seconds elapsed between ``epoch`` (Unix time) and ``now``.

    Negative deltas (clock skew) are clamped to zero so that the UI never
    displays a negative connection duration.
    """
    reference = now if now is not None else datetime.now(tz=timezone.utc)
    delta = reference - datetime.fromtimestamp(epoch, tz=timezone.utc)
    return max(int(delta.total_seconds()), 0)


def staleness(last_fetch: datetime, *, now: datetime | None = None) -> timedelta:
    """Return how long ago the most recent successful fetch happened."""
    reference = now if now is not None else datetime.now(tz=timezone.utc)
    return reference - last_fetch
