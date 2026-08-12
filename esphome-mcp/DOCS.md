# ESPHome MCP Server

This add-on runs an MCP (Model Context Protocol) server that exposes
ESPHome operations as tools for Claude Code. By default it delegates builds,
flashes, validation and logs to the ESPHome Device Builder dashboard (the
official ESPHome add-on) so they run against **current** ESPHome, and falls
back to a **bundled** esphome toolchain when the dashboard is unavailable (see
[Build backends](#build-backends)). It keeps native filesystem access to
`/config/esphome/` for config/font transfer — no SSH tunneling required.

## Architecture

```text
Claude Code (desktop)
     |  HTTP (MCP, port 8098, Bearer token)
     v
HA Add-on (MCP Server, host_network)
     |  HTTP/WS  -->  ESPHome Device Builder dashboard (127.0.0.1:<ingress_port>)
     |                    - GET /devices
     |                    - WS /compile, WS /upload
     |                    - WS /ws (devices/validate, devices/logs)
     |  local file I/O
     v
/config/esphome/  (shared mount: push/pull YAML + fonts)
```

In the default (`auto`) and `dashboard` modes, compilation happens in the
ESPHome add-on's container using its current esphome. The add-on also bundles
its own esphome toolchain (from the Debian/glibc base image) as a fallback for
when the dashboard is unreachable — see [Build backends](#build-backends).

## Configuration

### auth_token

An authentication token to secure the MCP endpoint. If left empty, a
token is auto-generated on first start and printed in the add-on logs.

```yaml
auth_token: "my-secret-token"
```

### dashboard_url

URL of the ESPHome Device Builder dashboard the add-on delegates builds to.

The HA ESPHome add-on serves its dashboard **ingress-only**, bound to
`127.0.0.1:<ingress_port>` (there is no fixed `6052` listener), and its peer
guard trusts only loopback and the Supervisor. This add-on therefore runs on
`host_network` so `127.0.0.1` reaches the dashboard as a trusted peer — the
same path HA core's ESPHome integration uses.

Set this to `http://127.0.0.1:<ingress_port>`. Find the ingress port on the
ESPHome add-on's page, or from the CLI:

```bash
ha addons info <esphome-slug> | grep ingress_port
```

The ingress port is stable for an install (it only changes if you reinstall
the ESPHome add-on).

### dashboard_token

Only needed if the dashboard is protected with a password. Leave empty for
the default (open) HA add-on behind Ingress.

### build_backend

Which backend runs `validate` / `compile` / `flash` / `logs` / `list`:

- **`auto`** (default) — probe the dashboard; delegate when reachable, else use
  the bundled esphome toolchain.
- **`dashboard`** — always delegate; returns a clear error if the dashboard is
  down. No local toolchain is used.
- **`bundled`** — always use the add-on's own esphome toolchain.

File/font push/pull are unaffected — they always use direct filesystem access.
See [Build backends](#build-backends).

```yaml
build_backend: "auto"
```

### esphome_version

Pins the esphome version used by the **bundled** fallback (e.g. `2026.7.4`).
Leave empty to use the version baked into the image. This has no effect in
`dashboard` mode, where the version is whatever the dashboard runs. When set,
the add-on installs that version at startup.

```yaml
esphome_version: ""
```

## Build backends

Build/flash/validate/logs/list can run two ways:

1. **Dashboard delegation** (default) — proxied to the official ESPHome Device
   Builder add-on over its HTTP/WS API, so builds use that add-on's current
   esphome and share its build cache. This requires the ESPHome **Device
   Builder** add-on to be installed and running, with `dashboard_url` set to its
   ingress port.
2. **Bundled toolchain** (fallback) — the add-on's own esphome (from the
   Debian/glibc base image) compiles locally. Used automatically in `auto` mode
   when the dashboard is unreachable, or always in `bundled` mode. It reuses the
   dashboard add-on's PlatformIO cache (`/config/esphome/.esphome/.platformio`)
   so it does not re-download toolchains.

Carrying the bundled toolchain makes the image large; that is the cost of
offline-capable builds. Set `build_backend: dashboard` if you never want the
fallback.

## Setup

1. Add this repository as a custom add-on repository in Home Assistant:
   **Settings > Add-ons > Add-on Store > ... > Repositories**
   Enter: `https://github.com/ojkaas/ha-addon-esphome-mcp`

2. Install the **ESPHome MCP Server** add-on and start it.

3. Check the add-on logs for the auth token (if you didn't set one).

4. Set the `ESPHOME_MCP_TOKEN` environment variable on your development
   machine to the auth token value.

5. Configure `.mcp.json` in your ESPHome project:

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

6. Restart Claude Code and verify the connection with `/mcp`.

## Available Tools

| Tool | Description |
| ---- | ----------- |
| `esphome_list_devices` | List device configs with names |
| `esphome_validate` | Validate a device YAML config |
| `esphome_compile` | Compile firmware from source, no flash (background) |
| `esphome_install` | **Compile + OTA flash** — deploy the current YAML (background) |
| `esphome_flash` | OTA flash the **last-compiled** binary without rebuilding (background) |
| `esphome_build_status` | Poll the latest background build for a device |
| `esphome_logs` | Get recent device logs (snapshot) |
| `esphome_push_files` | Write YAML files to the config directory |
| `esphome_pull_files` | Read YAML files from the config directory |
| `esphome_push_fonts` | Write font files (base64-encoded) |
| `esphome_pull_fonts` | Read font files (base64-encoded) |

## CLI: cheap push/pull (`scripts/esphome-mcp`)

Pushing or pulling a config *through* an AI assistant is expensive: the file's
bytes pass through the model's context twice — once when it reads the file and
again when it re-emits the content as the `esphome_push_files` argument. For a
large YAML that is a lot of wasted tokens.

`scripts/esphome-mcp` is a stdlib-only client that moves the bytes
disk↔server directly over the MCP HTTP endpoint, so the file content never
enters the assistant's context — the assistant only emits a short command.
It also works from a plain shell with no assistant at all.

```bash
# Put it on PATH (once):
ln -sf "$PWD/scripts/esphome-mcp" ~/.local/bin/esphome-mcp

# It auto-reads url+token from a .mcp.json in the current dir tree,
# or use $ESPHOME_MCP_URL / $ESPHOME_MCP_TOKEN, or --url/--token.
esphome-mcp push esp-lcd.yaml          # upload (content read from disk)
esphome-mcp pull esp-lcd.yaml          # download to disk
esphome-mcp pull                       # download all configs
esphome-mcp ls                         # list devices
esphome-mcp validate esp-lcd           # full validation output
esphome-mcp install esp-lcd            # compile + OTA flash (deploy changes)
esphome-mcp push-font myfont.ttf       # fonts (base64 handled locally)
esphome-mcp call <tool> k=v ...        # call any MCP tool directly
```

In an assistant session, prefer this CLI (via a `/push` slash command or a
`Bash(esphome-mcp:*)` call) over the `esphome_push_files` MCP tool whenever the
file is large.

## Security

- All requests require a valid Bearer token in the Authorization header. The
  one exception is `GET /health`, an unauthenticated liveness probe that returns
  `ok` and exposes no data — it backs the container healthcheck (and therefore
  Home Assistant's add-on status).
- `secrets.yaml` is explicitly rejected in push/pull operations.
- The add-on exposes port 8098 — ensure your network is trusted or use
  a reverse proxy with TLS.

## Network

The add-on listens on port **8098** (TCP). Make sure this port is
accessible from your development machine.

## Deploying config changes: install vs flash

These three tools are easy to confuse:

- **`esphome_compile`** builds firmware from the current YAML but does *not*
  flash it.
- **`esphome_flash`** OTA-uploads the *last-compiled* `firmware.bin` — it does
  *not* rebuild. If you edited the YAML and call this, you flash a **stale**
  binary that lacks your changes.
- **`esphome_install`** does both: compile from source, then flash — and only
  flashes if the compile succeeds. This is what you want after editing a
  config.

Rule of thumb: **to deploy YAML changes, use `esphome_install`.** Reach for the
bare `esphome_flash` only to re-push an already-built binary (e.g. an upload
that failed after a good compile).

## Long-running builds

Compiles (and the compile step of an install) can take several minutes,
especially the first build of a device. These run in the background: if a
build finishes within ~45s the full output is returned immediately;
otherwise the tool returns a handle and you poll `esphome_build_status`
with the device name until it reports `done` or `failed`.
