# CLAUDE.md

This file provides guidance to Claude Code when working with code in
this repository.

## Project Overview

Home Assistant custom add-on that runs an MCP (Model Context Protocol)
server for ESPHome operations. Claude Code connects to it over HTTP
instead of SSH. Builds/flashes/validation/logs are routed by `backend.py`: by
default **delegated to the ESPHome Device Builder dashboard** (the official
ESPHome add-on) over its HTTP/WS API so they use current ESPHome, with a
**bundled esphome toolchain** as fallback (`local.py`). Config/font transfer
uses direct access to the shared `/config/esphome/` filesystem on the HA host.

## Repository Structure

- `repository.yaml` — HA add-on repository metadata
- `esphome-mcp/` — The add-on
  - `config.yaml` — HA add-on manifest (name, version, ports, options)
  - `build.yaml` — Multi-arch Docker build config
  - `Dockerfile` — official ESPHome image base (Debian/glibc) for the bundled
    toolchain; clears the dashboard entrypoint and adds a real `/health` probe
  - `run.sh` — Add-on entry point (reads config, starts server)
  - `requirements.txt` — Python dependencies (mcp, uvicorn, aiohttp)
  - `server/` — Python package
    - `main.py` — FastMCP app, tool registration, uvicorn entry point
    - `tools.py` — Tool implementations (build ops routed via `backend.py`;
      file/font tools use the local `/config` mount)
    - `backend.py` — routes each build op to the dashboard or the local CLI
      per the `build_backend` option (auto/dashboard/bundled)
    - `dashboard.py` — HTTP/WS client for the Device Builder dashboard
    - `local.py` — bundled `esphome` CLI client (fallback backend)
    - `discover.py` — resolves the dashboard's ingress port via the Supervisor
      API when `dashboard_url` is blank (run at startup by `run.sh`)
    - `auth.py` — Bearer token middleware
  - `DOCS.md` — Add-on documentation page shown in HA UI

## Key Conventions

- **Auth**: Bearer token in `Authorization` header; auto-generated if not
  configured, persisted to `/data/auth_token`
- **Transport**: Streamable HTTP on port 8098 at `/mcp`
- **Secrets**: `secrets.yaml` is explicitly rejected in push/pull tools
- **ESPHome**: `build_backend` (auto/dashboard/bundled) selects delegation vs
  the bundled toolchain per op; `auto` falls back to bundled when the dashboard
  is unreachable. `esphome_version` pins the bundled fallback's version
- **Networking**: `host_network: true`. The HA ESPHome add-on serves the
  dashboard ingress-only on `127.0.0.1:<ingress_port>` and its peer guard
  trusts only loopback/Supervisor, so we reach it over loopback (`dashboard_url`
  = `http://127.0.0.1:<ingress_port>`). Bridge networking gets 403; the
  official `core-esphome` hostname only exists for official add-ons.
  `dashboard_url` defaults to blank → `discover.py` resolves the ingress port
  from the Supervisor API (`hassio_api: true`), falling back to `:6052`
- **Builds**: compile/flash consume the dashboard's WS spawn stream in a
  background thread; poll with `esphome_build_status` when a build outlives
  the sync window
- **install vs flash**: the dashboard's `/upload` (legacy `esphome_flash`)
  ONLY flashes the last-compiled `firmware.bin` — it never rebuilds (see the
  device-builder `JobType` docstring: "UPLOAD only flashes an existing
  binary"). Deploying a YAML edit therefore needs compile-then-flash.
  `esphome_install` (`kind="install"` in `_build_worker`) runs `/compile` then
  `/upload`, aborting the flash if the compile fails so a stale binary can't
  ship. Tool descriptions steer the model to `install` as the default deploy;
  bare `flash` is only for re-pushing an already-built binary
- **Validate**: use the `/ws` `devices/validate` command, NOT `GET /json-config`.
  json-config collapses any failure to a bare `{"error":"Configuration is
  invalid"}` (it suppresses the real message because `--show-secrets` can leak
  secrets), so it can't say *why* a config failed. The WS command streams the
  full `esphome config` output. All streamed output is ANSI-stripped via
  `dashboard.strip_ansi` — the dashboard emits escapes as literal `\033[..m`
  text, not raw 0x1b bytes
- **Path safety**: file tools route client filenames through `_safe_join` so
  `..`/absolute paths can't escape `/config/esphome`
- **Config mapping**: HA Supervisor maps `/config/` into the container
  (shared with the ESPHome add-on) for the file/font tools

## Building / Testing

The add-on is built by HA Supervisor when installed. For local testing:

```bash
cd esphome-mcp
docker build --build-arg BUILD_FROM=ghcr.io/esphome/esphome:2026.7.4 -t esphome-mcp .
docker run -p 8098:8098 -v /path/to/config:/config \
    -e ESPHOME_MCP_AUTH_TOKEN=test \
    -e DASHBOARD_URL=http://host.docker.internal:6052 esphome-mcp
```

## Deployment

Add `https://github.com/ojkaas/ha-addon-esphome-mcp` as a custom
add-on repository in Home Assistant, then install and start the add-on.
