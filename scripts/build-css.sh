#!/bin/sh
# Compile src/ovispect/static/app.src.css into src/ovispect/static/app.css.
#
# Uses the Tailwind CSS standalone CLI (a single Go binary, no Node
# required). The binary is cached under ./.cache/tailwindcss and pinned
# to a specific version for reproducibility.

set -eu

VERSION="v3.4.17"
CACHE_DIR=".cache"
BIN="${CACHE_DIR}/tailwindcss"

if [ ! -x "$BIN" ]; then
    mkdir -p "$CACHE_DIR"
    uname_s=$(uname -s | tr '[:upper:]' '[:lower:]')
    uname_m=$(uname -m)
    case "$uname_s-$uname_m" in
        linux-x86_64)  asset="tailwindcss-linux-x64" ;;
        linux-aarch64) asset="tailwindcss-linux-arm64" ;;
        darwin-x86_64) asset="tailwindcss-macos-x64" ;;
        darwin-arm64)  asset="tailwindcss-macos-arm64" ;;
        *)
            echo "ERROR: unsupported platform $uname_s-$uname_m" >&2
            exit 1
            ;;
    esac
    url="https://github.com/tailwindlabs/tailwindcss/releases/download/${VERSION}/${asset}"
    echo "Downloading Tailwind CLI ${VERSION} for ${uname_s}-${uname_m}"
    curl --fail --silent --show-error --location -o "$BIN" "$url"
    chmod +x "$BIN"
fi

"$BIN" \
    -c tailwind.config.js \
    -i src/ovispect/static/app.src.css \
    -o src/ovispect/static/app.css \
    --minify
