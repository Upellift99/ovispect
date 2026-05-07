"""End-to-end Playwright checks: self-hosted assets and S/M/L font selector."""

from __future__ import annotations

from urllib.parse import urlparse

import pytest

# Skip the whole module when playwright is not installed so the default
# `pytest` run (which excludes the e2e marker) does not error out at
# collection time.
pytest.importorskip("playwright.sync_api")

from playwright.sync_api import Page, expect  # noqa: E402


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
