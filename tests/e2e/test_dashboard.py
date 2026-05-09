"""End-to-end Playwright checks: self-hosted assets and S/M/L font selector."""

from __future__ import annotations

from urllib.parse import urlparse

import pytest

# Skip the whole module when playwright is not installed so the default
# `pytest` run (which excludes the e2e marker) does not error out at
# collection time.
pytest.importorskip("playwright.sync_api")

from playwright.sync_api import Page, expect


def test_dashboard_serves_local_assets_only(live_server: str, page: Page) -> None:
    """The dashboard must not pull anything from third-party origins."""
    server_host = urlparse(live_server).netloc
    external_requests: list[str] = []
    page.on(
        "request",
        lambda req: (
            external_requests.append(req.url)
            if urlparse(req.url).netloc not in {"", server_host}
            else None
        ),
    )

    response = page.goto(live_server)
    assert response is not None
    assert response.status == 200

    # The compiled stylesheet is reachable and served as CSS.
    css = page.request.get(f"{live_server}/static/app.css")
    assert css.status == 200
    assert css.headers["content-type"].startswith("text/css")

    # At least one bundled font also reachable.
    font = page.request.get(f"{live_server}/static/fonts/ibm-plex-mono-400.woff2")
    assert font.status == 200
    assert int(font.headers["content-length"]) > 1000

    page.wait_for_load_state("networkidle")
    assert external_requests == [], f"unexpected external requests: {external_requests}"


def test_font_size_selector_persists_across_reload(live_server: str, page: Page) -> None:
    """Clicking S/M/L updates `html[data-font-size]` and survives a reload."""
    page.goto(live_server)

    html = page.locator("html")
    medium_btn = page.locator('.fs-btn[data-fontsize="m"]')
    large_btn = page.locator('.fs-btn[data-fontsize="l"]')

    expect(html).to_have_attribute("data-font-size", "m")
    expect(medium_btn).to_have_attribute("aria-pressed", "true")

    large_btn.click()
    expect(html).to_have_attribute("data-font-size", "l")
    expect(large_btn).to_have_attribute("aria-pressed", "true")
    expect(medium_btn).to_have_attribute("aria-pressed", "false")

    page.reload()
    expect(html).to_have_attribute("data-font-size", "l")
    expect(page.locator('.fs-btn[data-fontsize="l"]')).to_have_attribute("aria-pressed", "true")


def test_dashboard_collapses_secondary_columns_on_mobile(live_server: str, page: Page) -> None:
    """Below Tailwind's `sm` breakpoint (640 px) the table collapses into
    a card-style grid: the column headers go away entirely (each row is
    self-describing with inline RX/TX labels), and the noisier header
    bits collapse so the dashboard fits a phone."""
    cn = page.locator('th[data-sort-key="common_name"]')
    virtual = page.locator('th[data-sort-key="virtual_address"]')
    connected = page.locator('th[data-sort-key="connected_for_seconds"]')
    fs_group = page.locator(".fs-group")
    sub_label = page.locator("header span", has_text="/ ovispect")

    # iPhone-SE-ish viewport — well under the 640 px sm breakpoint.
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(live_server)

    # Card layout hides the entire <thead>; rows render as two-row cards.
    expect(cn).to_be_hidden()
    expect(virtual).to_be_hidden()
    expect(connected).to_be_hidden()
    # Header crowding fix: pinch-zoom replaces the S/M/L selector here.
    expect(fs_group).to_be_hidden()
    expect(sub_label).to_be_hidden()

    # Above the breakpoint the regular table layout is back.
    page.set_viewport_size({"width": 1280, "height": 800})
    expect(cn).to_be_visible()
    expect(virtual).to_be_visible()
    expect(connected).to_be_visible()
    expect(fs_group).to_be_visible()
    expect(sub_label).to_be_visible()
