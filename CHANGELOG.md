# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/Upellift99/ovispect/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/Upellift99/ovispect/releases/tag/v0.2.0
[0.1.0]: https://github.com/Upellift99/ovispect/releases/tag/v0.1.0
