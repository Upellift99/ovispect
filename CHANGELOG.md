# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/<OWNER>/ovispect/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/<OWNER>/ovispect/releases/tag/v0.1.0
