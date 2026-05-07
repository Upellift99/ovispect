# End-to-end tests (Playwright)

These tests boot a real uvicorn server and drive a headless Chromium via
[Playwright](https://playwright.dev/python/). They are excluded from the
default `pytest` run (see the `not e2e` filter in `pyproject.toml`) so
the unit suite stays fast and dependency-free.

## Setup

```sh
pip install -e .[dev,e2e]
playwright install chromium
```

`playwright install chromium` downloads ~150 MB to `~/.cache/ms-playwright`.

## Running

```sh
pytest -m e2e
```

The default `pytest` invocation excludes them via `-m 'not e2e'` in
`pyproject.toml`, so passing the path alone (`pytest tests/e2e`) won't
collect anything — use the marker.

## What is covered

- The dashboard never reaches out to `fonts.googleapis.com` or
  `cdn.tailwindcss.com` — every asset is served from `/static`.
- The S/M/L font-size selector flips `html[data-font-size]` on click,
  highlights the active button via `aria-pressed`, and persists the
  choice across a full reload (localStorage round-trip).
