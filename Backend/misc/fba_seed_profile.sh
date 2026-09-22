#!/usr/bin/env bash
#
# Seed the FBA buyer-name scraper's Chromium profile volume (fba_profile ->
# /data/fba-profile) with just the Seller Central login state from a
# logged-in local Chrome / Playwright profile.
#
# WHY COOKIES-ONLY: copying a whole Chrome profile fails when the local Chrome
# is a newer major version than the container's bundled Chromium (playwright
# pins it) — Chromium SIGTRAPs on launch. The login cookies are basic-store
# ("v10") encrypted with a fixed key, so they port cleanly on their own.
#
# Usage:
#   Backend/misc/fba_seed_profile.sh <source-chrome-profile-dir> [dev|prod]
#
#   <source-chrome-profile-dir> is whatever FBA/config.json's
#   "chrome_profile_path" points to, AFTER logging in with:
#       python3 FBA/open_browser.py     # sign in, reach the dashboard, Ctrl+C
#
# Run from the repo root (where docker-compose.yml is).

set -euo pipefail

SRC="${1:?usage: fba_seed_profile.sh <source-chrome-profile-dir> [dev|prod]}"
ENVN="${2:-prod}"

case "$ENVN" in
  dev)  SVC=backend-dev; PROFILE=(--profile dev) ;;
  prod) SVC=backend;     PROFILE=(--profile prod) ;;
  *) echo "second arg must be 'dev' or 'prod'"; exit 1 ;;
esac

[ -f "$SRC/Default/Cookies" ] || { echo "error: no Default/Cookies under $SRC"; exit 1; }

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/Default"
cp "$SRC/Default/Cookies" "$STAGE/Default/Cookies"
if [ -f "$SRC/Default/Network/Cookies" ]; then
  mkdir -p "$STAGE/Default/Network"
  cp "$SRC/Default/Network/Cookies" "$STAGE/Default/Network/Cookies"
fi
[ -d "$SRC/Default/Local Storage" ] && cp -r "$SRC/Default/Local Storage" "$STAGE/Default/"

echo "Seeding $SVC:/data/fba-profile from $SRC (cookies only)…"
docker compose "${PROFILE[@]}" exec -u root -T "$SVC" \
  sh -c 'rm -rf /data/fba-profile/* /data/fba-profile/.??* 2>/dev/null || true'
docker compose "${PROFILE[@]}" cp "$STAGE/." "$SVC:/data/fba-profile/"
docker compose "${PROFILE[@]}" exec -u root -T "$SVC" \
  sh -c 'chown -R appuser:appgroup /data/fba-profile && rm -f /data/fba-profile/Singleton*'

echo "Done. Verify with:"
echo "  docker compose ${PROFILE[*]} exec -e PYTHONPATH=/app -w /app $SVC python -u misc/fba_scrape_smoke.py"
