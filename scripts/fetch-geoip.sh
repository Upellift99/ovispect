#!/bin/sh
# Fetch the latest db-ip.com Lite Country database (CC-BY-4.0).
#
# db-ip.com publishes a fresh CSV on the 1st of every month at the URL
#   https://download.db-ip.com/free/dbip-country-lite-YYYY-MM.csv.gz
# We try the current month and fall back up to three months back, which
# covers any publication delay or build-time clock skew.
#
# Output: ./dbip-country-lite.csv.gz in the current working directory.

set -eu

OUT="dbip-country-lite.csv.gz"
YEAR=$(date -u +%Y)
MONTH_RAW=$(date -u +%m)
# Strip leading zero so arithmetic doesn't treat "08"/"09" as octal in dash/ash.
MONTH=$(printf '%d' "$MONTH_RAW")

for offset in 0 1 2 3; do
    new_month=$((MONTH - offset))
    new_year=$YEAR
    while [ "$new_month" -le 0 ]; do
        new_month=$((new_month + 12))
        new_year=$((new_year - 1))
    done
    ym=$(printf '%04d-%02d' "$new_year" "$new_month")
    url="https://download.db-ip.com/free/dbip-country-lite-${ym}.csv.gz"
    echo "Trying $url"
    if curl --fail --silent --show-error --location --max-time 60 -o "$OUT" "$url"; then
        # Sanity check: file must be at least 1 MB (real DB is ~3 MB compressed).
        size=$(wc -c < "$OUT")
        if [ "$size" -lt 1048576 ]; then
            echo "Downloaded file is too small ($size bytes), discarding"
            rm -f "$OUT"
            continue
        fi
        echo "Downloaded $ym ($(echo "$size" | awk '{printf "%.1f MB\n", $1 / 1048576}'))"
        exit 0
    fi
done

echo "ERROR: Could not fetch GeoIP DB after 4 attempts (network blocked or db-ip.com down)" >&2
echo "Hint: rebuild with --build-arg SKIP_GEOIP=1 to disable the country lookup." >&2
exit 1
