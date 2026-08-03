# Contributing to ovispect

Thanks for considering a contribution! ovispect is a small project with a
deliberately narrow scope, which keeps it easy to maintain. Reading this
document before opening a PR will help you ship quickly.

## Scope

ovispect aims to be a fast, modern, single-purpose dashboard for OpenVPN's
management interface. The README's *Why ovispect?* section spells out what
the project intentionally does **not** do (GeoIP, persistence, alerting,
multi-server fleets, in-app authentication, …). PRs that expand the scope in
those directions will likely be declined — please open a
[Discussion](https://github.com/Upellift99/ovispect/discussions) first.

Good first issues:

- UI polish (typography, spacing, accessibility)
- Additional unit tests, especially edge cases for the parser
- Documentation improvements (clearer migration steps, more reverse-proxy
  examples)
- Container hardening (read-only FS, distroless, etc.)

## Development setup

You will need Python 3.12+ and Docker (for the container linter).

With [`uv`](https://docs.astral.sh/uv/) (recommended):

```bash
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
pre-commit install
```

With `venv` + `pip`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
```

## Running the project locally

```bash
export OPENVPN_HOST=10.0.0.5
export OPENVPN_PORT=5555
python -m ovispect
```

Open <http://localhost:8000> in your browser. The page auto-refreshes every
`REFRESH_SECONDS` seconds.

If you do not have an OpenVPN server at hand, you can use a tiny TCP echo
script that replays a known `status 3` payload — see
[tests/fixtures/status3_sample.txt](tests/fixtures/status3_sample.txt).

## Running checks

```bash
ruff check .
ruff format --check .
mypy --strict src/ovispect
pytest -v
```

A single command that runs everything pre-commit knows about:

```bash
pre-commit run --all-files
```

Container linter:

```bash
docker run --rm -i hadolint/hadolint < Dockerfile
```

## Commit style

We follow [Conventional Commits](https://www.conventionalcommits.org/).
Common prefixes:

- `feat:` — user-visible new behavior
- `fix:` — bug fix
- `chore:` — tooling, build, dependencies
- `docs:` — documentation only
- `test:` — adding or refactoring tests
- `ci:` — GitHub Actions changes
- `refactor:` — code change with no behavioral effect

Breaking changes are flagged with `!` (`feat!: …`) and a `BREAKING CHANGE:`
trailer in the body.

## Pull requests

- Keep PRs focused. One concern per PR makes review faster and revert safer.
- Update tests for any behavior change.
- Update the relevant section of the README when applicable. Do **not** edit
  `CHANGELOG.md` by hand: Release Please regenerates its top section from the
  commit history (see below). Put the effort into your commit message instead —
  it is what ends up in the changelog.
- All CI checks must be green before review.
- A maintainer will review every PR; we do not allow self-merges to `main`.

## Releasing

Maintainers only. The version is bumped by
[Release Please](https://github.com/googleapis/release-please), which watches
`main` and keeps a release pull request up to date.

1. Merge whatever you want to ship into `main`. Release Please opens (or
   updates) a `chore(release): X.Y.Z` PR, bumping `pyproject.toml` and drafting
   a `CHANGELOG.md` entry from the `feat:` and `fix:` commits. Every other
   commit type is deliberately hidden, so the draft stays short.
2. **Rewrite that draft before merging.** The generated bullets are commit
   subjects; the changelog this project keeps explains *why* a change matters
   and what it means for an operator. Move entries under the right Keep a
   Changelog heading (`Security` in particular is never inferred), and match
   the surrounding style.
3. Merge the release PR.
4. Push the tag — this is the step that publishes:

   ```bash
   git switch main && git pull
   git tag -a v0.9.0 -m "v0.9.0" && git push origin v0.9.0
   ```

   `release.yml` then builds the multi-arch image, pushes it to GHCR, and
   creates the GitHub Release with the notes taken from `CHANGELOG.md`.

Release Please intentionally does not tag (`skip-github-release: true`).
Tagging stays a deliberate act, and it keeps the tag push as the single
trigger of the publishing pipeline.

## Reporting issues

Please use the GitHub issue forms — they collect the information we need to
reproduce most problems quickly. **Never include OpenVPN management
passwords or client certificates in an issue.** Redact IP addresses if your
deployment is sensitive.

For security vulnerabilities, follow [SECURITY.md](SECURITY.md) instead of
opening a public issue.

## Code of Conduct

By contributing you agree to abide by the project's
[Code of Conduct](CODE_OF_CONDUCT.md).
