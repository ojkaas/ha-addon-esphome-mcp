#!/usr/bin/env bash
# ==============================================================================
# ESPHome MCP Server — Add-on entry point (glibc base, no bashio)
# ==============================================================================
set -e

OPTIONS_FILE="/data/options.json"

# Small helper to read a key from the add-on options JSON.
opt() {
    python3 -c "import json;
try:
    print(json.load(open('${OPTIONS_FILE}')).get('$1') or '')
except Exception:
    print('')" 2>/dev/null || true
}

# Read auth token from add-on config (replaces bashio::config)
AUTH_TOKEN="$(opt auth_token)"

# Auto-generate token if not configured
if [ -z "$AUTH_TOKEN" ] || [ "$AUTH_TOKEN" = "null" ]; then
    TOKEN_FILE="/data/auth_token"
    if [ ! -f "$TOKEN_FILE" ]; then
        AUTH_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
        echo "$AUTH_TOKEN" > "$TOKEN_FILE"
    else
        AUTH_TOKEN="$(cat "$TOKEN_FILE")"
    fi
    echo "[WARN] ==================================================="
    echo "[WARN]   MCP Auth Token: ${AUTH_TOKEN}"
    echo "[WARN] ==================================================="
    echo "[WARN] Set this token in your MCP client's Authorization header."
fi

export ESPHOME_MCP_AUTH_TOKEN="$AUTH_TOKEN"
export ESPHOME_DIR="/config/esphome"

# Run on a non-default port so this fork can coexist with the original add-on.
export MCP_PORT="${MCP_PORT:-8098}"

# Dashboard delegation (default backend). Under the HA ESPHome add-on the
# dashboard is ingress-only on 127.0.0.1:<ingress_port> (reachable because this
# add-on is host_network, and loopback is a trusted peer). Set dashboard_url to
# http://127.0.0.1:<ingress_port> — find the port on the ESPHome add-on page or
# via: ha addons info <esphome-slug> | grep ingress. Token only needed if the
# dashboard has a password.
DASHBOARD_URL="$(opt dashboard_url)"
export DASHBOARD_URL="${DASHBOARD_URL:-http://127.0.0.1:6052}"
export DASHBOARD_TOKEN="$(opt dashboard_token)"

case "$DASHBOARD_URL" in
    *:6052) echo "[WARN] dashboard_url uses :6052 — the HA ESPHome add-on serves"
            echo "[WARN] on its ingress port, not 6052. If builds fail to connect,"
            echo "[WARN] set dashboard_url to http://127.0.0.1:<ingress_port>." ;;
esac

# Build backend: auto (default) | dashboard | bundled. `auto` delegates to the
# dashboard when reachable and falls back to the bundled esphome CLI otherwise.
BUILD_BACKEND="$(opt build_backend)"
export BUILD_BACKEND="${BUILD_BACKEND:-auto}"

# Reuse the PlatformIO toolchains/cache the ESPHome Device Builder add-on
# already downloaded under /config, so the bundled fallback needn't re-download.
export PLATFORMIO_CORE_DIR="/config/esphome/.esphome/.platformio"

# Optional: pin the esphome version used by the *bundled* fallback. In
# dashboard mode the version is whatever the dashboard runs, so skip the
# reconcile there. Installing at startup lets the option override the image's
# baked esphome without rebuilding.
ESPHOME_VERSION="$(opt esphome_version)"
if [ -n "$ESPHOME_VERSION" ] && [ "$BUILD_BACKEND" != "dashboard" ]; then
    CURRENT="$(esphome version 2>/dev/null | head -n1 || true)"
    case "$CURRENT" in
        *"$ESPHOME_VERSION"*) echo "[INFO] Bundled esphome already at ${ESPHOME_VERSION}." ;;
        *)  echo "[INFO] Pinning bundled esphome to ${ESPHOME_VERSION} (pip install)..."
            pip3 install --no-cache-dir --break-system-packages -q \
                "esphome==${ESPHOME_VERSION}" \
                || echo "[WARN] Could not install esphome==${ESPHOME_VERSION}; keeping existing." ;;
    esac
fi

echo "[INFO] Build backend: ${BUILD_BACKEND} (dashboard: ${DASHBOARD_URL})"
echo "[INFO] Starting ESPHome MCP Server on port ${MCP_PORT}..."
exec python3 -m server.main
