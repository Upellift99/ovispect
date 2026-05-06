# Security Policy

## Supported Versions

ovispect is in pre-1.0 development. Only the latest minor release receives
security fixes. When a 1.x line is published, this section will be updated
to reflect a multi-version support matrix.

| Version | Supported          |
|---------|--------------------|
| latest  | :white_check_mark: |
| older   | :x:                |

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Please open a private report via GitHub Security Advisories:
<https://github.com/Upellift99/ovispect/security/advisories/new>

Include in your report:

- A description of the issue and its impact
- Steps to reproduce (a minimal proof of concept is ideal)
- The version of ovispect (`ovispect:<tag>` or commit SHA)
- Your environment (Docker, native, reverse proxy in front, etc.)

GitHub Security Advisories give you a private, end-to-end audit trail with
the maintainers and let us coordinate the fix, the CVE, and the public
disclosure all in one place — there is no email channel by design.

### Response targets

- **Acknowledgement** of your report within 72 hours.
- **Initial triage and severity classification** within 7 days.
- **Fix and coordinated disclosure** within 30 days for confirmed issues.
  More complex issues may take longer; we will keep you informed.

Confirmed vulnerabilities are disclosed via
[GitHub Security Advisories](https://github.com/Upellift99/ovispect/security/advisories)
and assigned a CVE when applicable. Reporters are credited unless they ask
to remain anonymous.

## Scope

In scope:

- The ovispect application code (anything under `src/`)
- The published container image (`ghcr.io/Upellift99/ovispect`)
- The published documentation, where it could mislead operators into an
  insecure configuration

Out of scope:

- Vulnerabilities in third-party dependencies — please report those upstream
- The OpenVPN management protocol itself (report to the OpenVPN project)
- Self-XSS or social engineering against the maintainer

## Hardening recommendations

ovispect is a *read-only* dashboard. It still benefits from defense in
depth:

- Run it behind a reverse proxy that handles TLS and authentication
- Bind it to a private interface (`127.0.0.1` or a private VLAN)
- Run it as a non-root user (the published image already does)
- Keep the OpenVPN management interface itself bound to `127.0.0.1` or a
  private network — **never expose it to the public internet**
