# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.0] - 2026-05-06

### Added

- **IP-to-country lookup**: a regional-indicator flag and ISO 3166-1
  alpha-2 code are shown next to each client's real address (and in the
  drawer). Lookup is backed by [DB-IP.com Lite Country](https://db-ip.com/db/download/ip-to-country-lite)
  (CC-BY-4.0), bundled in the Docker image so there is no runtime network
  dependency. Private, loopback and unknown IPs simply render without a
  flag.
- New `ovispect.geo` module with `CountryDatabase`, `country_flag`,
  `extract_ip` helpers and a singleton cache; loads CSV or `.csv.gz`,
  serves O(log n) lookups via `bisect`.
- Dockerfile gains a `geoip` build stage that fetches the latest monthly
  DB from db-ip.com via `scripts/fetch-geoip.sh` (with up-to-three-month
  fallback for any publication delay). Pass
  `--build-arg SKIP_GEOIP=1` to disable the download for offline builds.
- `GEOIP_DATABASE_PATH` setting (default `/opt/geo/dbip-country-lite.csv.gz`)
  controls the runtime database location; missing/corrupt files
  gracefully disable the column.
- Footer displays the DB-IP.com attribution required by CC-BY-4.0
  whenever the database is loaded.

### Changed

- `/api/clients` payload now includes `country_code` (or `null`) and
  `country_flag` (or `""`) per client.
- README updated: feature list, comparison table (now lists GeoIP +
  Auth as supported) and a third-party-attribution section.

## [0.4.0] - 2026-05-06

### Added

- **Sort/filter persisted to `localStorage`** — your sort key, direction
  and search filter survive a full page reload (not just an auto-refresh
  tick). Stored under the `ovispect:ui` key, no PII.
- **Live diff between snapshots** — newly connected clients flash green
  for ~2.4s; departed clients linger one tick with a red strikethrough
  fade-out instead of vanishing silently. Skipped on the first snapshot
  so the dashboard doesn't flash every row on load.
- **Per-client drawer**: clicking a row opens a slide-in panel with the
  full session info (username, real address, both virtual IPs, RX/TX
  with raw byte counts, connected timestamp + duration, client/peer IDs,
  data-channel cipher). Closes on backdrop click, ✕, or `Esc`. Drawer
  keeps live-updating while open as long as the client is still
  connected; shows a "disconnected" banner otherwise.
- New deployment example: `compose.shared-network.example.yml` —
  documents the pattern of joining ovispect to a pre-existing Docker
  bridge network with a stable subnet (useful when OpenVPN's management
  port is reachable from the bridge gateway, or when other services on
  the host need to talk to ovispect without published ports).

### Changed

- `GET /api/clients` payload now includes `virtual_ipv6_address`,
  `client_id`, `peer_id`, and `data_channel_cipher` so the drawer can
  render them without a second round-trip.

## [0.3.1] - 2026-05-06

### Added

- Inline clear (`✕`) button on the search input, visible only while the
  field has content. Pressing `Esc` clears the field too. The native
  WebKit cancel cross is hidden to avoid duplication.
- Zebra striping on the dashboard table — even rows get a subtle
  background tint for easier scanning. Hover keeps a stronger highlight.

## [0.3.0] - 2026-05-06

### Added

- Sortable columns on the dashboard table — click any header to toggle
  ascending/descending. Sorts use raw values (bytes, seconds) so RX/TX/
  Connected sort numerically rather than lexicographically.
- Live search input above the table, matching `Common Name`,
  `Real Address`, and `Virtual` (case-insensitive substring). A
  `N / Total matches` counter appears next to the input when filtering.
- `<tfoot>` row with aggregate **Total RX**, **Total TX**, and the visible
  client count (recomputed against the active filter).
- New JSON endpoint `GET /api/clients` returning the full snapshot
  (`fetched_at`, `is_error`, `total_*`, `clients[]` with both raw and
  humanized values). Auth-protected when authentication is enabled.

### Changed

- The dashboard now refreshes via `fetch('/api/clients')` instead of a
  full-page `<meta http-equiv="refresh">`. Consequence: the user's sort
  order, search filter, and scroll position are preserved across ticks.
- The view-model builder is factored around `_build_snapshot_payload` so
  SSR (`/`) and JSON (`/api/clients`) emit identical data shapes.

## [0.2.2] - 2026-05-06

### Fixed

- Management client now recognizes both `LF` and `CRLF` line terminators
  when scanning for the `END` sentinel that closes a `status 3` response.
  OpenVPN's management interface ships CRLF on most builds, which made
  `_recv_until` block until timeout and surface as
  *"timed out waiting for management response"* even when the server was
  replying correctly. The trailing `END` line is now stripped whether the
  payload ends with `\nEND\n` or `\nEND\r\n`.

## [0.2.1] - 2026-05-06

### Fixed

- `__version__` now reads from the installed package metadata via
  `importlib.metadata`, so the footer on every page (and the
  `/openapi.json` version field) reflects the real release. Previously it
  was hardcoded in `__init__.py` and could fall out of sync with
  `pyproject.toml` (0.2.0 footers were still showing `v0.1.0`).
- `compose.example.yml` now resolves every value through `${VAR:-default}`
  or `${VAR:?}`, so settings put in `.env` (including `AUTH_USERNAME`)
  actually reach the container.
- All `ghcr.io/Upellift99/...` references switched to lowercase
  (`ghcr.io/upellift99/...`); the GitHub Container Registry rejects
  uppercase paths. The release workflow's `IMAGE_NAME` is pinned
  lowercased so `${{ github.repository }}` capitalization is no longer
  load-bearing.

### Added

- `.env.example` — canonical reference for all supported env vars.

## [0.2.0] - 2026-05-06

### Added

- Optional built-in form-based authentication with bcrypt password hashing.
  Disabled by default — set `AUTH_PASSWORD_HASH` to enable.
- Session cookies signed via Starlette's `SessionMiddleware` with
  `SameSite=Strict`, configurable lifetime, and `Secure` flag.
- In-memory rate limiting on the login endpoint (5 failed attempts per IP
  per 5-minute window, then a 5-minute lockout).
- `python -m ovispect.hash_password` (also installed as
  `ovispect-hash-password`) CLI helper to mint `AUTH_PASSWORD_HASH` values.
- Sign-out control in the dashboard header when authentication is enabled.
- New env vars: `AUTH_USERNAME`, `AUTH_PASSWORD_HASH`, `SESSION_SECRET`,
  `SESSION_LIFETIME_SECONDS`, `SESSION_COOKIE_NAME`, `SESSION_COOKIE_SECURE`.
- `compose.reverse-proxy.example.yml`: standalone v0.1-style deployment
  alongside the new built-in-auth example.

### Changed

- README's *Authentication* section rewritten to document the two
  deployment modes (standalone vs reverse-proxy).
- `compose.example.yml` now demonstrates the standalone-with-auth setup.
- Test suite grown from 41 to 82 tests; coverage stays at 95%+.

### Security

- Login uses POST-only flow with `SameSite=Strict` cookies, generic
  "Invalid credentials" error to prevent username enumeration, and an
  open-redirect-safe `next=` parameter.
- Strict startup validation: refuses to boot when `AUTH_PASSWORD_HASH` is
  set with a `SESSION_SECRET` shorter than 32 chars or with a value that
  is not a valid bcrypt hash.

## [0.1.0] - 2026-05-06

### Added

- Initial public release.
- FastAPI dashboard rendering OpenVPN's `status 3` output as a dark
  terminal-styled table (IBM Plex Mono).
- TCP client for the OpenVPN management interface with optional password
  auth, configurable timeout, and graceful error handling.
- TSV parser for `status 3` that tolerates malformed rows.
- Routes:
    - `GET /` — server-rendered dashboard with full-page auto-refresh.
    - `GET /healthz` — JSON liveness probe used by the container HEALTHCHECK.
    - `GET /metrics` — minimal Prometheus exposition (clients connected,
      RX/TX totals, up gauge).
- Multi-stage Alpine container (≤ 70 MB final image) running as a non-root
  user with a HEALTHCHECK and tini as PID 1.
- 12-factor configuration via environment variables, validated with
  pydantic-settings.
- Drop-in `compose.example.yml` (read-only filesystem, `cap_drop: ALL`,
  `no-new-privileges`).
- Public-project documentation: README with comparison table and migration
  guide from `openvpn-monitor`, CONTRIBUTING, SECURITY, CODE_OF_CONDUCT.
- Test suite (41 tests) covering parser, formatting helpers, and HTTP
  routes via FastAPI's `TestClient`.

[Unreleased]: https://github.com/Upellift99/ovispect/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/Upellift99/ovispect/releases/tag/v0.5.0
[0.4.0]: https://github.com/Upellift99/ovispect/releases/tag/v0.4.0
[0.3.1]: https://github.com/Upellift99/ovispect/releases/tag/v0.3.1
[0.3.0]: https://github.com/Upellift99/ovispect/releases/tag/v0.3.0
[0.2.2]: https://github.com/Upellift99/ovispect/releases/tag/v0.2.2
[0.2.1]: https://github.com/Upellift99/ovispect/releases/tag/v0.2.1
[0.2.0]: https://github.com/Upellift99/ovispect/releases/tag/v0.2.0
[0.1.0]: https://github.com/Upellift99/ovispect/releases/tag/v0.1.0
