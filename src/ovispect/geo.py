"""IP-to-country lookup backed by the db-ip.com Lite Country database.

The database is a sorted CSV (optionally gzipped) of
``start_ip,end_ip,country_code`` rows. We load it once into two parallel
arrays (one per IP version) and serve queries via :mod:`bisect` in
O(log n).

Attribution: This product includes IP-to-Country data created by
DB-IP.com, distributed under CC-BY-4.0
(<https://creativecommons.org/licenses/by/4.0/>).
"""

from __future__ import annotations

import bisect
import csv
import gzip
import ipaddress
import logging
from pathlib import Path
from typing import IO

logger = logging.getLogger(__name__)


class CountryDatabase:
    """An in-memory IP→country lookup table loaded from a CSV file."""

    def __init__(self, source_path: Path) -> None:
        self.source_path = source_path
        self._v4_starts: list[int] = []
        self._v4_ends: list[int] = []
        self._v4_codes: list[str] = []
        self._v6_starts: list[int] = []
        self._v6_ends: list[int] = []
        self._v6_codes: list[str] = []
        self._load()

    def _open(self) -> IO[str]:
        if self.source_path.suffix == ".gz":
            return gzip.open(self.source_path, "rt", encoding="utf-8", newline="")
        return self.source_path.open("rt", encoding="utf-8", newline="")

    def _load(self) -> None:
        with self._open() as handle:
            reader = csv.reader(handle)
            for row in reader:
                if len(row) < 3:
                    continue
                try:
                    start = ipaddress.ip_address(row[0].strip())
                    end = ipaddress.ip_address(row[1].strip())
                except ValueError:
                    continue
                code = row[2].strip().upper()
                if len(code) != 2 or not code.isalpha():
                    continue
                if start.version == 4:
                    self._v4_starts.append(int(start))
                    self._v4_ends.append(int(end))
                    self._v4_codes.append(code)
                else:
                    self._v6_starts.append(int(start))
                    self._v6_ends.append(int(end))
                    self._v6_codes.append(code)
        logger.info(
            "GeoIP DB loaded: %d IPv4 ranges, %d IPv6 ranges (from %s)",
            len(self._v4_starts),
            len(self._v6_starts),
            self.source_path.name,
        )

    def lookup(self, ip: str) -> str | None:
        """Return the ISO 3166-1 alpha-2 country code for ``ip``, or ``None``.

        Reserved/private/loopback addresses fall through to ``None`` because
        no public database covers them.
        """
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return None
        if addr.version == 4:
            starts, ends, codes = self._v4_starts, self._v4_ends, self._v4_codes
        else:
            starts, ends, codes = self._v6_starts, self._v6_ends, self._v6_codes
        if not starts:
            return None
        addr_int = int(addr)
        idx = bisect.bisect_right(starts, addr_int) - 1
        if idx < 0:
            return None
        if ends[idx] >= addr_int:
            return codes[idx]
        return None


def country_flag(code: str | None) -> str:
    """Convert an ISO 3166-1 alpha-2 country code to a regional-indicator emoji.

    >>> country_flag("FR")
    '🇫🇷'
    >>> country_flag("us")
    '🇺🇸'
    >>> country_flag(None)
    ''
    >>> country_flag("XYZ")
    ''
    """
    if not code or len(code) != 2 or not code.isalpha():
        return ""
    base = 0x1F1E6  # REGIONAL INDICATOR SYMBOL LETTER A
    upper = code.upper()
    return chr(base + ord(upper[0]) - ord("A")) + chr(base + ord(upper[1]) - ord("A"))


def extract_ip(address: str) -> str | None:
    """Strip port and brackets from a ``host:port`` / ``[host]:port`` string.

    >>> extract_ip("203.0.113.7:51820")
    '203.0.113.7'
    >>> extract_ip("[2001:db8::1]:51820")
    '2001:db8::1'
    >>> extract_ip("203.0.113.7")
    '203.0.113.7'
    >>> extract_ip("")  # returns None
    """
    if not address:
        return None
    s = address.strip()
    if s.startswith("[") and "]" in s:
        return s[1 : s.index("]")] or None
    if s.count(":") == 1:
        head = s.split(":", 1)[0]
        return head or None
    return s


class _Cache:
    """Single-slot cache for the loaded :class:`CountryDatabase`."""

    database: CountryDatabase | None = None
    attempted: bool = False


def get_database(path: Path | None) -> CountryDatabase | None:
    """Return the cached :class:`CountryDatabase`, loading it on first call.

    Returns ``None`` when the file does not exist or fails to parse — the
    caller is expected to gracefully degrade (no country column).
    """
    if _Cache.attempted:
        return _Cache.database
    _Cache.attempted = True
    if path is None or not path.exists():
        logger.info("GeoIP database not found at %s — country lookup disabled", path)
        return None
    try:
        _Cache.database = CountryDatabase(path)
    except (OSError, csv.Error) as exc:
        logger.warning("Failed to read GeoIP database %s: %s", path, exc)
    return _Cache.database


def reset_cache() -> None:
    """Reset the singleton (test helper)."""
    _Cache.database = None
    _Cache.attempted = False
