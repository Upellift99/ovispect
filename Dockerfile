# syntax=docker/dockerfile:1.7
# Multi-stage build that produces a small, non-root, healthchecked image.

ARG PYTHON_VERSION=3.12-alpine
# Set to a non-empty value to skip the GeoIP DB download (e.g. for offline
# builds or air-gapped environments). The country lookup will then be
# silently disabled at runtime.
ARG SKIP_GEOIP=

# --- GeoIP country DB (db-ip.com Lite, CC-BY-4.0) -----------------------
FROM alpine:3.19 AS geoip
ARG SKIP_GEOIP
WORKDIR /geoip
# hadolint ignore=DL3018
RUN apk add --no-cache curl ca-certificates gzip
COPY scripts/fetch-geoip.sh ./fetch-geoip.sh
RUN set -e; \
    if [ -z "$SKIP_GEOIP" ]; then \
        sh ./fetch-geoip.sh; \
    else \
        echo "SKIP_GEOIP set — emitting empty (valid) gzip marker"; \
        gzip -c < /dev/null > dbip-country-lite.csv.gz; \
    fi


FROM python:${PYTHON_VERSION} AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

# hadolint ignore=DL3018
RUN apk add --no-cache build-base \
 && python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml README.md ./
COPY src ./src

# hadolint ignore=DL3013
RUN pip install --upgrade pip wheel \
 && pip install . \
 && pip uninstall -y pip wheel setuptools \
 && find /opt/venv -type d -name __pycache__ -exec rm -rf {} + \
 && find /opt/venv -type d -name tests -exec rm -rf {} + \
 && find /opt/venv -name "*.pyc" -delete \
 && find /opt/venv -type d -name "*.dist-info" -exec rm -f {}/RECORD {}/WHEEL {}/INSTALLER \;


FROM python:${PYTHON_VERSION} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    BIND_HOST=0.0.0.0 \
    BIND_PORT=8000

# hadolint ignore=DL3018
RUN apk add --no-cache wget tini \
 && addgroup -S ovispect \
 && adduser -S -G ovispect -u 10001 -H -h /app ovispect

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --from=geoip /geoip/dbip-country-lite.csv.gz /opt/geo/dbip-country-lite.csv.gz

USER ovispect:ovispect

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q -O - "http://127.0.0.1:${BIND_PORT}/healthz" || exit 1

ENTRYPOINT ["/sbin/tini", "--"]
CMD ["python", "-m", "ovispect"]
