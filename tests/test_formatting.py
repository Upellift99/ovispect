"""Tests for byte/duration/address humanizers."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ovispect.formatting import (
    format_local_time,
    humanize_bytes,
    humanize_duration,
    seconds_since,
    strip_port,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, "0 B"),
        (1, "1 B"),
        (1023, "1023 B"),
        (1024, "1.0 KB"),
        (1536, "1.5 KB"),
        (1048576, "1.0 MB"),
        (1073741824, "1.0 GB"),
        (1099511627776, "1.0 TB"),
    ],
)
def test_humanize_bytes(value: int, expected: str) -> None:
    assert humanize_bytes(value) == expected


def test_humanize_bytes_rejects_negative() -> None:
    with pytest.raises(ValueError, match="negative"):
        humanize_bytes(-1)


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "0s"),
        (1, "1s"),
        (45, "45s"),
        (60, "1m"),
        (119, "1m"),
        (3599, "59m"),
        (3600, "1h"),
        (8054, "2h 14m"),
        (86399, "23h 59m"),
        (86400, "1d"),
        (90061, "1d 1h"),
    ],
)
def test_humanize_duration(seconds: int, expected: str) -> None:
    assert humanize_duration(seconds) == expected


def test_humanize_duration_rejects_negative() -> None:
    with pytest.raises(ValueError, match="negative"):
        humanize_duration(-1)


@pytest.mark.parametrize(
    ("addr", "expected"),
    [
        ("1.2.3.4:51820", "1.2.3.4"),
        ("[2001:db8::1]:51820", "[2001:db8::1]"),
        ("1.2.3.4", "1.2.3.4"),
        ("not-a-real-address", "not-a-real-address"),
    ],
)
def test_strip_port(addr: str, expected: str) -> None:
    assert strip_port(addr) == expected


def test_format_local_time_uses_utc_by_default() -> None:
    dt = datetime(2026, 5, 6, 12, 34, 56, tzinfo=UTC)
    assert format_local_time(dt) == "12:34:56"


def test_seconds_since_clamps_clock_skew() -> None:
    now = datetime(2026, 5, 6, 0, 0, 0, tzinfo=UTC)
    future_epoch = int(now.timestamp()) + 60
    assert seconds_since(future_epoch, now=now) == 0


def test_seconds_since_returns_elapsed() -> None:
    now = datetime(2026, 5, 6, 1, 0, 0, tzinfo=UTC)
    past_epoch = int(now.timestamp()) - 3661
    assert seconds_since(past_epoch, now=now) == 3661
