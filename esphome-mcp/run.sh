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

# Delegate all builds to the ESPHome Device Builder dashboard. Under the HA
# ESPHome add-on the dashboard is ingress-only on 127.0.0.1:<ingress_port>
# (reachable because this add-on is host_network, and loopback is a trusted
# peer). Set dashboard_url to http://127.0.0.1:<ingress_port> — find the port
# on the ESPHome add-on page or via: ha addons info <esphome-slug> | grep ingress
# Token only needed if the dashboard has a password.
DASHBOARD_URL="$(opt dashboard_url)"
export DASHBOARD_URL="${DASHBOARD_URL:-http://127.0.0.1:6052}"
export DASHBOARD_TOKEN="$(opt dashboard_token)"

echo "[INFO] Delegating builds to dashboard: ${DASHBOARD_URL}"
case "$DASHBOARD_URL" in
    *:6052) echo "[WARN] dashboard_url uses :6052 — the HA ESPHome add-on serves"
            echo "[WARN] on its ingress port, not 6052. If builds fail to connect,"
            echo "[WARN] set dashboard_url to http://127.0.0.1:<ingress_port>." ;;
esac
echo "[INFO] Starting ESPHome MCP Server on port ${MCP_PORT}..."
exec python3 -m server.main
