# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.8.0] - 2026-05-08

### Added

- **Native OIDC authentication (Mode 1)** — ovispect can now authenticate
  users directly against an OpenID Connect provider (Keycloak, Authelia,
  Authentik, Zitadel, …) without an oauth2-proxy / ForwardAuth layer in
  front. Implementation uses Authorization Code Flow with PKCE (S256) and
  validates `iss`, `aud`, `exp` and `iat` on every id_token.
- Auto-discovery of provider configuration via
  `.well-known/openid-configuration`; ovispect refuses to start when
  discovery fails rather than silently falling back.
- Group-based access control via `OIDC_REQUIRED_GROUPS`. A user lacking
  the required group lands on a polite 403 page that lists what's
  expected (handy for admins debugging access).
- SSO logout — the *Sign out* button hits the provider's
  `end_session_endpoint` with `id_token_hint`, then clears the local
  session.
- Username display in the dashboard header. The claim is configurable via
  `OIDC_USERNAME_CLAIM` (defaults to `preferred_username`, with `email`
  and `sub` as fallbacks).
- Display of the upstream user when running behind oauth2-proxy or a
  similar header-injecting proxy (`X-Auth-Request-User` /
  `X-Auth-Request-Preferred-Username`).
- New env vars: `OIDC_ISSUER_URL`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`,
  `OIDC_REDIRECT_URI`, `OIDC_SCOPES`, `OIDC_USERNAME_CLAIM`,
  `OIDC_REQUIRED_GROUPS`, `OIDC_GROUPS_CLAIM`, `OIDC_VERIFY_SSL`,
  `OIDC_LOGOUT_REDIRECT_URI`.
- New deployment example: `compose.oidc.example.yml`.

### Changed

- The README's *Authentication* section is rewritten around the three
  modes and includes provider-specific setup snippets for Keycloak,
  Authelia, and Authentik.
- The `require_auth` FastAPI dependency now routes to either the OIDC or
  built-in implementation based on the resolved mode (OIDC > built-in >
  upstream). When both `OIDC_ISSUER_URL` and `AUTH_PASSWORD_HASH` are
  set, OIDC wins and the latter is ignored with a warning at boot.

### Security

- Native OIDC implementation enforces PKCE (S256) for the authorize
  request and validates `state`, `iss`, `aud`, `exp`, `iat` on every
  id_token (signature via JWKS, RS256/RS384/RS512/ES256/ES384/PS256).
- Refresh tokens are stored exclusively server-side (signed Starlette
  session cookie); the browser never sees them. Expired access is
  silently refreshed once on demand and the session is cleared if the
  provider rejects the refresh.

### Documentation

- Added provider-specific setup examples for Keycloak, Authelia, and
  Authentik in the README.
- `.env.example` reorganised around the three authentication modes.

## [0.7.0] - 2026-05-07

### Added

- **Self-hosted assets** — IBM Plex Mono/Sans `.woff2` files and a
  precompiled Tailwind stylesheet now ship under
  `src/ovispect/static/`. The dashboard no longer reaches out to
  `fonts.googleapis.com` or `cdn.tailwindcss.com`; everything is served
  from the FastAPI app itself.
- `scripts/build-css.sh` — recompiles `app.css` via the Tailwind
  standalone CLI (Go binary, no Node required). Downloads the pinned
  v3.4.17 release on first run into `.cache/` (gitignored).
- **S/M/L font-size selector** in the header. The choice is persisted
  alongside the existing UI preferences in `localStorage` and scales
  every rem-based size via a CSS variable on `<html>`.
- **End-to-end Playwright suite** under `tests/e2e/`, opt-in via
  `pytest -m e2e`. Boots a real uvicorn instance in a background
  thread and asserts (a) no third-party origins are hit and (b) the
  S/M/L selector flips `html[data-font-size]` and survives a reload.
  New optional extra: `pip install -e .[e2e]`.
- Pre-commit hook that re-runs `scripts/build-css.sh` whenever a
  template, the Tailwind config, or `app.src.css` changes — keeps the
  committed `app.css` in lock-step with its sources.

### Changed

- Dashboard contrast is bumped for dark-mode legibility: zebra rows
  go from ~12 % to ~22 % opacity, uppercase labels lift from
  `neutral-500/600` to `neutral-300/400`, and the totals row now has a
  visible background plus white-on-grey values.

## [0.6.0] - 2026-05-06

### Added

- **Webhooks for connect/disconnect events** — set `WEBHOOK_URL` and a
  background task polls the management interface every
  `WEBHOOK_POLL_SECONDS` (default 10s), diffs each snapshot against the
  previous one, and POSTs an event for every client that joins or
  leaves. Independent of the dashboard refresh: events ship even if
  nobody has the page open.
- Four output formats selectable via `WEBHOOK_FORMAT`:
  - `generic` (default) — full JSON `{event, site_name, timestamp,
    client: {…}}` with all session metadata + `country_code`
  - `slack` — `{"text": "🟢 alice connected (🇫🇷 1.2.3.4 → 10.8.0.6)"}`
  - `discord` — `{"content": "…"}` one-liner
  - `gotify` — `{"title", "message", "priority": 5}`
- Optional HMAC-SHA256 body signing via `WEBHOOK_SECRET`; digest ships
  in the `X-Ovispect-Signature: sha256=<hex>` header.
- Bounded retry on transient failures: 4xx responses are not retried,
  5xx and connection errors retry up to `WEBHOOK_MAX_RETRIES` with
  exponential backoff capped at 10 s.
- Event filter via `WEBHOOK_EVENTS=connect,disconnect` (either, both,
  or neither — neither disables the loop entirely).
- Client identity uses OpenVPN's `client_id` when defined, else falls
  back to `(common_name, real_address)` so two parallel sessions of the
  same user don't trigger spurious duplicate events.

### Changed

- New runtime dependency: `httpx>=0.27` (already a transitive dev dep
  via FastAPI's `TestClient`; promoted to a first-class prod dep for
  the webhook sender).
- Test suite grows from 112 to 134 tests; `pytest-asyncio` added in dev
  deps with `asyncio_mode = "auto"`.

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

[Unreleased]: https://github.com/Upellift99/ovispect/compare/v0.8.0...HEAD
[0.8.0]: https://github.com/Upellift99/ovispect/releases/tag/v0.8.0
[0.7.0]: https://github.com/Upellift99/ovispect/releases/tag/v0.7.0
[0.6.0]: https://github.com/Upellift99/ovispect/releases/tag/v0.6.0
[0.5.0]: https://github.com/Upellift99/ovispect/releases/tag/v0.5.0
[0.4.0]: https://github.com/Upellift99/ovispect/releases/tag/v0.4.0
[0.3.1]: https://github.com/Upellift99/ovispect/releases/tag/v0.3.1
[0.3.0]: https://github.com/Upellift99/ovispect/releases/tag/v0.3.0
[0.2.2]: https://github.com/Upellift99/ovispect/releases/tag/v0.2.2
[0.2.1]: https://github.com/Upellift99/ovispect/releases/tag/v0.2.1
[0.2.0]: https://github.com/Upellift99/ovispect/releases/tag/v0.2.0
[0.1.0]: https://github.com/Upellift99/ovispect/releases/tag/v0.1.0
