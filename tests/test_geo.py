"""Tests for the IP-to-country lookup module."""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from ovispect import geo

FIXTURE = Path(__file__).parent / "fixtures" / "dbip-country-lite-sample.csv"


@pytest.fixture(autouse=True)
def _reset_geo_cache() -> None:
    geo.reset_cache()
    yield
    geo.reset_cache()


# --- country_flag --------------------------------------------------------


def test_country_flag_renders_uppercase_ascii_pair() -> None:
    assert geo.country_flag("FR") == "🇫🇷"


def test_country_flag_handles_lowercase() -> None:
    assert geo.country_flag("us") == "🇺🇸"


@pytest.mark.parametrize("value", [None, "", "X", "USA", "F1", "  "])
def test_country_flag_rejects_invalid(value: str | None) -> None:
    assert geo.country_flag(value) == ""


# --- extract_ip ----------------------------------------------------------


def test_extract_ip_strips_v4_port() -> None:
    assert geo.extract_ip("203.0.113.7:51820") == "203.0.113.7"


def test_extract_ip_strips_v6_brackets_and_port() -> None:
    assert geo.extract_ip("[2001:db8::1]:51820") == "2001:db8::1"


def test_extract_ip_passes_through_bare_address() -> None:
    assert geo.extract_ip("203.0.113.7") == "203.0.113.7"


@pytest.mark.parametrize("value", ["", None])
def test_extract_ip_returns_none_for_empty(value: str | None) -> None:
    assert geo.extract_ip(value or "") is None


# --- CountryDatabase -----------------------------------------------------


def test_database_loads_and_resolves_v4() -> None:
    db = geo.CountryDatabase(FIXTURE)
    assert db.lookup("8.8.8.8") == "US"
    assert db.lookup("203.0.113.42") == "FR"
    assert db.lookup("80.12.34.56") == "FR"


def test_database_resolves_v6() -> None:
    db = geo.CountryDatabase(FIXTURE)
    assert db.lookup("2001:db8::1") == "DE"


def test_database_returns_none_for_unknown_ip() -> None:
    db = geo.CountryDatabase(FIXTURE)
    # Outside any range in the fixture.
    assert db.lookup("9.9.9.9") is None
    # Below the smallest start IP.
    assert db.lookup("0.0.0.1") is None


def test_database_returns_none_for_invalid_input() -> None:
    db = geo.CountryDatabase(FIXTURE)
    assert db.lookup("not-an-ip") is None
    assert db.lookup("") is None


def test_database_loads_gzipped_csv(tmp_path: Path) -> None:
    gz_path = tmp_path / "dbip.csv.gz"
    with gzip.open(gz_path, "wb") as out:
        out.write(FIXTURE.read_bytes())
    db = geo.CountryDatabase(gz_path)
    assert db.lookup("8.8.8.8") == "US"


def test_database_skips_malformed_rows(tmp_path: Path) -> None:
    path = tmp_path / "broken.csv"
    path.write_text(
        "garbage row\n"
        "1.2.3.4\n"  # too few fields
        "1.2.3.4,not-an-ip,US\n"  # bad end
        "1.2.3.4,1.2.3.99,fr\n"  # valid
        "1.2.3.4,1.2.3.99,XYZ\n"  # bad code length
        "1.2.3.4,1.2.3.99,F1\n"  # non-alpha
    )
    db = geo.CountryDatabase(path)
    assert db.lookup("1.2.3.50") == "FR"


# --- get_database --------------------------------------------------------


def test_get_database_returns_none_when_file_missing(tmp_path: Path) -> None:
    assert geo.get_database(tmp_path / "nope.csv") is None


def test_get_database_returns_none_for_none_path() -> None:
    assert geo.get_database(None) is None


def test_get_database_caches_result() -> None:
    first = geo.get_database(FIXTURE)
    second = geo.get_database(FIXTURE)
    assert first is second


def test_get_database_returns_none_for_corrupt_gzip(tmp_path: Path) -> None:
    bad = tmp_path / "bad.csv.gz"
    bad.write_bytes(b"not a real gzip stream")
    assert geo.get_database(bad) is None


def test_get_database_handles_empty_valid_gzip(tmp_path: Path) -> None:
    """A valid but empty gzip file (used by the SKIP_GEOIP build path)."""
    empty = tmp_path / "empty.csv.gz"
    with gzip.open(empty, "wb") as f:
        f.write(b"")
    db = geo.get_database(empty)
    assert db is not None
    assert db.lookup("8.8.8.8") is None
