"""Tests for the QUICK_FILTERS setting and its rendering."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ovispect import app as app_module
from ovispect.config import QuickFilter, Settings
from ovispect.ovpn import StatusSnapshot


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {"openvpn_host": "127.0.0.1", "openvpn_port": 5555}
    base.update(overrides)
    return Settings(**base)


def test_quick_filters_default_is_empty() -> None:
    assert _settings().quick_filter_list == []


def test_quick_filters_parses_labels_and_bare_needles() -> None:
    settings = _settings(quick_filters="Desktops=desktop; Laptops = laptop ;web|vps;")
    assert settings.quick_filter_list == [
        QuickFilter(label="Desktops", needle="desktop"),
        QuickFilter(label="Laptops", needle="laptop"),
        QuickFilter(label="web|vps", needle="web|vps"),
    ]


def test_quick_filters_drops_empty_and_duplicate_entries() -> None:
    settings = _settings(quick_filters="A=x;;A=y;=z;B=")
    assert settings.quick_filter_list == [QuickFilter(label="A", needle="x")]


def test_quick_filters_rejects_too_many_entries() -> None:
    too_many = ";".join(f"f{i}=x{i}" for i in range(21))
    with pytest.raises(ValidationError, match="at most 20"):
        _settings(quick_filters=too_many)


def test_quick_filters_rejects_long_label() -> None:
    with pytest.raises(ValidationError, match="exceeds 40"):
        _settings(quick_filters=f"{'L' * 41}=x")


def test_index_renders_quick_filter_buttons(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_fetch(*_args: Any, **_kwargs: Any) -> StatusSnapshot:
        return StatusSnapshot(fetched_at=datetime.now(tz=UTC), clients=[])

    monkeypatch.setattr(app_module, "fetch_status", _fake_fetch)
    application = app_module.create_app(
        _settings(quick_filters='Desktops=desktop;Both=desktop|laptop;Evil="<b>')
    )
    with TestClient(application) as client:
        body = client.get("/").text
    assert 'id="quick-filters"' in body
    assert 'data-needle="desktop"' in body
    assert ">Desktops</button>" in body
    assert 'data-needle="desktop|laptop"' in body
    assert ">Both</button>" in body
    # Needles and labels are HTML-escaped by the template engine.
    assert 'data-needle="&#34;&lt;b&gt;"' in body
    assert "<b>" not in body.split('id="quick-filters"')[1].split("</fieldset>")[0]


def test_index_omits_quick_filters_block_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_fetch(*_args: Any, **_kwargs: Any) -> StatusSnapshot:
        return StatusSnapshot(fetched_at=datetime.now(tz=UTC), clients=[])

    monkeypatch.setattr(app_module, "fetch_status", _fake_fetch)
    with TestClient(app_module.create_app(_settings())) as client:
        body = client.get("/").text
    assert 'id="quick-filters"' not in body
