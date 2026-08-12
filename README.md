# ESPHome MCP Server — Home Assistant Add-on

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

MCP (Model Context Protocol) server that exposes ESPHome operations as tools
for [Claude Code](https://claude.ai/code). It runs as a Home Assistant add-on
that, **by default, delegates** builds/flashes/validation/logs to the ESPHome
Device Builder dashboard (so they use current ESPHome) and **falls back to a
bundled esphome toolchain** when the dashboard is unavailable. Config and font
files are transferred over the shared `/config/esphome/` filesystem — no SSH
required.

## Requirements

- The default and `dashboard` backends delegate to the official ESPHome
  **Device Builder** add-on — install and run it, and point `dashboard_url` at
  its ingress port. In `auto` mode, if it is not reachable the add-on falls back
  to its bundled toolchain; in `bundled` mode it is not needed at all.

## Quick Start

1. Add this repository as a custom add-on repository in Home Assistant:

   **Settings > Add-ons > Add-on Store > ... (menu) > Repositories**

   ```text
   https://github.com/ojkaas/ha-addon-esphome-mcp
   ```

2. Install and start the **ESPHome MCP Server** add-on.

3. Check the add-on logs for the auto-generated auth token.

4. Set `ESPHOME_MCP_TOKEN` in your shell environment.

5. Add to `.mcp.json` in your ESPHome project:

   ```json
   {
     "mcpServers": {
       "esphome": {
         "type": "http",
         "url": "http://<your-ha-host>:8098/mcp",
         "headers": {
           "Authorization": "Bearer ${ESPHOME_MCP_TOKEN}"
         }
       }
     }
   }
   ```

6. Restart Claude Code and verify with `/mcp`.

## Tools

| Tool | Description |
| ---- | ----------- |
| `esphome_list_devices` | List device configs with names |
| `esphome_validate` | Validate a device YAML config |
| `esphome_compile` | Compile firmware from source, no flash (background) |
| `esphome_install` | **Compile + OTA flash** — deploy the current YAML (background) |
| `esphome_flash` | OTA flash the last-compiled binary without rebuilding (background) |
| `esphome_build_status` | Poll a background compile/flash |
| `esphome_logs` | Get recent device logs |
| `esphome_push_files` | Write YAML configs to HA |
| `esphome_pull_files` | Read YAML configs from HA |
| `esphome_push_fonts` | Write font files (base64) to HA |
| `esphome_pull_fonts` | Read font files (base64) from HA |

## Build backends

Build/flash/validate/logs/list are routed by the `build_backend` option:

- **`auto`** (default) — delegate to the dashboard when reachable, else use the
  bundled esphome toolchain.
- **`dashboard`** — always delegate; clear error if the dashboard is down.
- **`bundled`** — always use the add-on's own esphome toolchain.

`esphome_version` pins the version used by the bundled fallback (empty = image
default; no effect in `dashboard` mode). File/font tools always use direct
filesystem access and are backend-independent. See
[esphome-mcp/DOCS.md](esphome-mcp/DOCS.md#build-backends) for details.

## Architecture

```text
Claude Code (desktop)
     |  HTTP (MCP, Bearer token, port 8098)
     v
HA Add-on (MCP Server, host_network)
     |  build_backend router:
     |    - HTTP/WS  -->  ESPHome Device Builder dashboard   (delegate, default)
     |    - local    -->  bundled esphome toolchain          (fallback)
     |  local file I/O  -->  /config/esphome/  (push/pull YAML + fonts)
```

See [esphome-mcp/DOCS.md](esphome-mcp/DOCS.md) for full documentation.

## Credits

- Original add-on: [bberrevoets](https://github.com/bberrevoets/ha-addon-esphome-mcp).
- Dashboard-delegation architecture:
  [dmitrii-galantsev](https://github.com/dmitrii-galantsev/ha-addon-esphome-mcp).
- Healthcheck fix (add-on stuck on "Starting"):
  [scadinot](https://github.com/scadinot/ha-addon-esphome-mcp).
- This fork (three-mode backend + bundled fallback), maintained by **ojkaas**.

## License

[MIT](LICENSE)
