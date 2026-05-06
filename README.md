# ovispect

[![CI](https://github.com/Upellift99/ovispect/actions/workflows/ci.yml/badge.svg)](https://github.com/Upellift99/ovispect/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![Image size](https://ghcr-badge.egpl.dev/Upellift99/ovispect/size?color=blue)](https://github.com/Upellift99/ovispect/pkgs/container/ovispect)

A lightweight, modern dashboard for OpenVPN's management interface. ovispect
gives you an at-a-glance view of who is connected to your OpenVPN server, with
a refined dark UI that fits well into a bookmark bar — not a long-term
monitoring suite.

![Screenshot of the ovispect dashboard](docs/screenshot.png)

## Features

- Single binary container, ≤ 70 MB, runs as non-root
- Reads OpenVPN's `status 3` (TSV) over the management interface — no log scraping
- Server-rendered HTML, full-page auto-refresh, no JS framework
- Optional Prometheus exposition (`/metrics`) for ad-hoc scraping
- 12-factor configuration via environment variables only
- Strict types (`mypy --strict`), linted with `ruff`, container linted with `hadolint`
- Built for Linux `amd64` and `arm64`

## Why ovispect?

| Project                          | Image  | Maintained | UI            | GeoIP | Auth |
|----------------------------------|--------|------------|---------------|-------|------|
| `ruimarinho/openvpn-monitor`     | 927 MB | no         | dated         | yes   | no   |
| `samuelkadolph/openvpn-monitor`  | 58 MB  | yes        | same as above | yes   | no   |
| `kumina/openvpn_exporter` (Prom) | ~15 MB | yes        | none          | no    | no   |
| **ovispect** (this project)      | ≤70 MB | yes        | modern        | no    | no   |

ovispect targets the *"I bookmarked this, I want a quick clean look"* use
case. For long-term monitoring, alerting, and historical graphs, pair it with
Prometheus + Grafana or Zabbix — those tools do that job better and ovispect
will not try to compete with them.

## Quick start

```bash
docker run -d \
    --name ovispect \
    -e OPENVPN_HOST=10.0.0.5 \
    -e OPENVPN_PORT=5555 \
    -p 8000:8000 \
    ghcr.io/Upellift99/ovispect:latest
```

Then open <http://localhost:8000>.

A drop-in `compose.example.yml` is provided in this repo.

## Configuration

| Variable                      | Default     | Description                                                                 |
|-------------------------------|-------------|-----------------------------------------------------------------------------|
| `OPENVPN_HOST`                | (required)  | Hostname or IP of the OpenVPN management interface                          |
| `OPENVPN_PORT`                | (required)  | TCP port of the management interface                                        |
| `OPENVPN_PASSWORD`            | (empty)     | Management password if `management-client-auth` is configured server-side   |
| `SITE_NAME`                   | `OpenVPN`   | Name shown in the dashboard header                                          |
| `REFRESH_SECONDS`             | `10`        | Auto-refresh interval (1–3600)                                              |
| `TIMEZONE`                    | `UTC`       | IANA timezone for displayed timestamps (e.g. `Europe/Paris`)                |
| `LOG_LEVEL`                   | `INFO`      | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`                          |
| `BIND_HOST`                   | `0.0.0.0`   | Address the HTTP server listens on inside the container                     |
| `BIND_PORT`                   | `8000`      | Port the HTTP server listens on inside the container                        |
| `MANAGEMENT_TIMEOUT_SECONDS`  | `5.0`       | Socket timeout when talking to the management interface                     |

## OpenVPN management interface setup

ovispect reads from OpenVPN's text-based management interface. Add the
following to your `server.conf` (or equivalent), then reload OpenVPN:

```conf
# Listen on a private interface only — never expose this to the public internet.
management 10.0.0.5 5555
```

If you want to require a password, point the directive at a file containing
the secret on its first line:

```conf
management 10.0.0.5 5555 /etc/openvpn/management.pass
```

```bash
# Generate a random password file readable only by openvpn:
openssl rand -base64 32 > /etc/openvpn/management.pass
chmod 600 /etc/openvpn/management.pass
```

Then set `OPENVPN_PASSWORD` in ovispect to the same value.

## Authentication

**ovispect does not provide authentication.** This is intentional: the
dashboard is a thin read-only view, and authentication is solved better at
the reverse proxy layer. Three patterns most users adopt:

1. **HTTP basic auth via nginx / Caddy** — the simplest option for personal
   instances.
2. **`oauth2-proxy` in front of ovispect** — wires up Google, GitHub, Keycloak,
   or any OIDC provider.
3. **BunkerWeb / Authelia / Authentik** — for users who already run a unified
   identity layer for their internal tools.

Whichever you pick, never expose ovispect (or the OpenVPN management
interface) directly to the public internet.

## Migration from `openvpn-monitor`

If you currently run `ruimarinho/openvpn-monitor`, the swap is almost a
one-liner. Before:

```yaml
services:
  monitor:
    image: ruimarinho/openvpn-monitor
    environment:
      OPENVPNMONITOR_DEFAULT_HOST: 10.0.0.5
      OPENVPNMONITOR_DEFAULT_PORT: 5555
    ports: ["80:80"]
```

After:

```yaml
services:
  ovispect:
    image: ghcr.io/Upellift99/ovispect:latest
    environment:
      OPENVPN_HOST: 10.0.0.5
      OPENVPN_PORT: 5555
      SITE_NAME: My VPN
    ports: ["8000:8000"]
```

GeoIP data is not provided by ovispect on purpose. If you need it, run
[`maxmind/geoipupdate`](https://github.com/maxmind/geoipupdate) alongside the
relevant downstream tooling.

## Building from source

With `uv` (recommended):

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
pytest
```

With `venv` + `pip`:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Build the container locally:

```bash
docker build -t ovispect:dev .
docker run --rm -e OPENVPN_HOST=10.0.0.5 -e OPENVPN_PORT=5555 -p 8000:8000 ovispect:dev
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Bug reports and feature requests are
welcome via [GitHub Issues](https://github.com/Upellift99/ovispect/issues).

## Security

To report a vulnerability, please follow the procedure in
[SECURITY.md](SECURITY.md). Do not open a public issue for security reports.

## License

MIT — see [LICENSE](LICENSE).

ovispect is independent from, and not affiliated with, OpenVPN Inc.
The terminal-style design and feature scope took moral inspiration from
[`furlongm/openvpn-monitor`](https://github.com/furlongm/openvpn-monitor); no
code was copied.
