# Changelog

All notable changes to this project will be documented in this file.

## [1.8.3] - 2026-08-12

### Fixed

- **`flash` / `install` could silently return a running `compile`'s job.** The
  build registry is keyed by configuration alone, so all three operations
  collide on one key, and `_start_build` reused any running job regardless of
  kind. Asking for a flash while a compile ran therefore reported the compile's
  progress labelled "Flash" — and no flash ever happened. A mismatched kind is
  now refused with a message pointing at `esphome_build_status`, and each job
  records its kind (also surfaced in `build_status` output).
- **Auth token compared in constant time.** `auth.py` used `!=`, whose early
  exit leaks the position of the first mismatching byte; it now uses
  `hmac.compare_digest`. Tokens are compared as bytes so a non-ASCII configured
  token yields a clean 403 instead of a `TypeError` (500).
- **Empty `ESPHOME_MCP_AUTH_TOKEN` now fails closed.** It previously served
  every request unauthenticated. `run.sh` always exports a token, so an empty
  value means the server was started outside that path — with `/config` mapped
  read-write, falling open exposed filesystem access to anyone who could reach
  the port. Requests now get 503 and an error is logged. `/health` is still
  served, so the container healthcheck keeps working.
- **Healthcheck access logs no longer flood the add-on log.** The probe hits
  `/health` every 10s, which uvicorn logged as ~8600 access lines a day,
  burying real activity. Those lines are filtered out; everything else is
  logged as before.
- **Build output no longer grows without bound.** `job["lines"]` was an
  unbounded list held for the process lifetime. It is now capped at
  `MAX_BUILD_LINES` (5000) most-recent lines, and the rendered output states
  how many earlier lines were dropped rather than silently truncating.
- **Fixed a data race on the build registry.** `_build_worker` read
  `_BUILDS[key]` outside `_BUILDS_LOCK`; it now receives the job object
  directly from `_start_build`.

### Added

- `tests/test_builds.py` and `tests/test_auth.py` covering the above.

## [1.8.2] - 2026-08-12

### Fixed

- **Dashboard auto-discovery now works.** It requires reading other add-ons'
  info via the Supervisor `/addons` API, which needs `hassio_role: manager`;
  the add-on only had the default role, so discovery silently fell back to
  `http://127.0.0.1:6052`. Added `hassio_role: manager`.

## [1.8.1] - 2026-08-12

### Fixed

- **Pin `mcp[cli]` below 2.0.** mcp 2.x removed `mcp.server.fastmcp`, which the
  server imports, so a fresh build crashed on startup with
  `ModuleNotFoundError: No module named 'mcp.server.fastmcp'`. The requirement
  was unbounded (`>=1.9.0`); it is now `>=1.9.0,<2`.

## [1.8.0] - 2026-08-12

### Added

- **Auto-discovery of the ESPHome dashboard URL.** Leave `dashboard_url` empty
  (now the default) and the add-on resolves the ESPHome Device Builder's current
  Supervisor ingress port via `hassio_api` (`server/discover.py`), so no manual
  port is needed and it survives a dashboard reinstall. Falls back to
  `http://127.0.0.1:6052` if discovery fails.
- **The active build backend is logged** (`Build backend -> dashboard|local`)
  on startup and whenever it changes, so the add-on log shows which path a
  build took.

### Changed

- `dashboard_url` now defaults to empty (auto-discover) instead of
  `http://127.0.0.1:6052`. Added `hassio_api: true` so the add-on can query the
  Supervisor for the dashboard's ingress port.

## [1.7.0] - 2026-08-12

### Added

- **Three build backends via the `build_backend` option** (`auto` | `dashboard`
  | `bundled`). `auto` (default) delegates builds to the ESPHome Device Builder
  dashboard when it is reachable and **falls back to a bundled esphome
  toolchain** otherwise; `dashboard` always delegates; `bundled` always uses the
  local toolchain. File/font push/pull remain direct-filesystem and
  backend-independent.
- **`esphome_version` option** to pin the esphome version used by the bundled
  fallback (reconciled at startup; no effect in `dashboard` mode).

### Changed

- Base image is once again the official ESPHome image (Debian/glibc) so the
  bundled fallback has a working ESP toolchain. The bundled path reuses the
  dashboard add-on's PlatformIO cache via `PLATFORMIO_CORE_DIR`.
- Restored the `/health` liveness probe + real container `HEALTHCHECK` (fix for
  the add-on hanging in "Starting"; originally by scadinot), needed again with
  the ESPHome base image.

### Attribution

- This fork is maintained by **ojkaas**, building on the original by
  **bberrevoets**, the dashboard-delegation architecture by
  **dmitrii-galantsev**, and the healthcheck fix by **scadinot**.

## [1.6.1] - 2026-07-25

### Changed

- `esphome_push_files` / `esphome_pull_files` tool descriptions now lead with a
  cost warning and point at the `esphome-mcp` CLI. The old descriptions
  described a `files: {name: content}` argument with no caveat, so a model
  handling a natural-language "push X" request would pick the tool and read the
  file into context to fill the argument — the exact double-pass the CLI exists
  to avoid. (The `/push` slash command already used the CLI, but only fired on
  explicit `/push`; plain requests bypassed it.)

### Note

- Making the assistant *default* to the CLI for a given project is best done
  with a project `CLAUDE.md` instructing it to use `esphome-mcp` and not read
  files first; the tool-description change is the server-side backstop.

## [1.6.0] - 2026-07-25

### Added

- **`esphome_install` tool — compile from source, then OTA flash.** This is
  the correct way to deploy a YAML edit: it rebuilds the firmware and only
  flashes if the compile succeeds (a failed compile aborts before upload, so a
  stale binary can never ship). Tool descriptions now steer the model here as
  the default deploy action. Also available as `esphome-mcp install <device>`.

### Changed

- Clarified `esphome_flash` / `esphome_compile` descriptions to prevent the
  common mistake of "just flashing" after editing a config. The dashboard's
  `/upload` only flashes the *last-compiled* binary — it never rebuilds (per
  the device-builder `JobType` docs: "UPLOAD only flashes an existing binary")
  — so a bare flash after a YAML change pushes stale firmware. `esphome_flash`
  is now explicitly documented as "flash the last-compiled binary without
  rebuilding," for re-pushing an already-built artifact only.

### Added (earlier, previously unreleased)

- `scripts/esphome-mcp` — a stdlib-only CLI client for the add-on's MCP HTTP
  endpoint. It moves config/font bytes disk↔server directly, so pushing or
  pulling a file through an AI assistant no longer forces the content through
  the model context twice (read + re-emit as a tool argument). The assistant
  emits only a short command; the CLI reads the file from disk and POSTs it.
  Auto-discovers url+token from a `.mcp.json`, `$ESPHOME_MCP_URL/_TOKEN`, or
  flags. Also usable from a plain shell. Documented in DOCS.md. No add-on/
  server changes — works against the currently deployed server.

## [1.5.0] - 2026-07-25

### Fixed

- **`esphome_validate` now returns the real error on failure.** It called the
  dashboard's `GET /json-config`, which deliberately collapses *any* config
  failure to a bare `{"error":"Configuration is invalid"}` (it suppresses the
  detail because `esphome config --show-secrets` output can leak resolved
  secrets) — so the tool could never say *why* a config was invalid. Validate
  now streams the `/ws` `devices/validate` command, which runs `esphome config`
  and returns its full output: component errors, source file, line numbers.
  Verified end-to-end against a live dashboard (2026.7.2) with both a broken
  and a valid config.
- Strip ANSI escape sequences from all streamed dashboard output (validate,
  logs, compile/flash). The dashboard emits colour codes as the literal text
  `\033[..m` (not raw control bytes), so they were leaking into tool output;
  `dashboard.strip_ansi` now removes both the escaped and raw forms.

### Changed

- On success `esphome_validate` reports a one-line "Configuration is valid"
  instead of echoing the entire resolved YAML (hundreds of lines).

### Security

- File tools (`push_files` / `pull_files`) route client-supplied filenames
  through a new `_safe_join` guard, rejecting absolute paths and `..`
  traversal so a filename can't read or write outside `/config/esphome`.

### Removed

- Dead `_device_yaml_path` helper (unused since builds moved to the dashboard).

## [1.4.0] - 2026-07-12

### Changed

- Run on `host_network` and default `dashboard_url` to `http://127.0.0.1:<port>`.
  The HA ESPHome add-on serves its dashboard ingress-only on
  `127.0.0.1:<ingress_port>` (no fixed 6052), and its peer guard trusts only
  loopback/Supervisor — so a bridge-network add-on gets 403. host_network lets
  us reach it over loopback as a trusted peer, mirroring HA core's ESPHome
  integration. Set `dashboard_url` to `http://127.0.0.1:<ingress_port>` (find
  it via `ha addons info <esphome-slug> | grep ingress_port`).

## [1.3.2] - 2026-07-12

### Fixed

- Run delegated dashboard calls on a worker thread. FastMCP invokes the sync
  tools on its own event-loop thread, so the direct `asyncio.run()` in
  `list_devices`/`validate`/`logs` raised "cannot be called from a running
  event loop". Offload via a one-shot thread pool. Verified end-to-end
  against a live dashboard (list, validate, and WS compile streaming).

## [1.3.1] - 2026-07-12

### Fixed

- Build on the trusted HA Alpine base (`ghcr.io/home-assistant/{arch}-base`)
  and install `python3`/`py3-pip`/`bash` via apk. Supervisor rejects
  untrusted base images like `python:3.12-slim` (Docker Hub library) and
  silently falls back to the HA base, which lacks pip — so 1.3.0 failed to
  build with `pip3: not found`.

## [1.3.0] - 2026-07-12

### Changed

- **Builds are now delegated to the ESPHome Device Builder dashboard** (the
  official ESPHome add-on) over its HTTP/WS API instead of running a bundled
  `esphome` binary. This removes the pinned esphome version that lived in the
  Docker base image — configs needing newer ESPHome features (e.g. the
  `WAVESHARE-ESP32-C6-LCD-1.47` display model) no longer fail with an
  "Unknown value" error because the add-on always builds with current ESPHome.
- `compile`/`flash` drive the dashboard's `/compile` and `/upload` WebSocket
  spawn protocol; `validate` uses `GET /json-config`; `list_devices` uses
  `GET /devices`; `logs` streams the `/ws` `devices/logs` command. File and
  font tools still read/write the shared `/config/esphome` mount directly.
- Dropped the heavy `ghcr.io/esphome/esphome` base image for a slim
  `python:3.12-slim` — no ESP toolchain or PlatformIO is shipped anymore.

### Added

- Options `dashboard_url` (default `http://core-esphome:6052`) and
  `dashboard_token` (only needed if the dashboard has a password set).

## [1.2.0] - 2026-05-20 (glibc fork)

### Changed

- Rebased the image on the official `ghcr.io/esphome/esphome` (Debian/glibc)
  image. The previous Alpine/musl base could not run ESPHome's glibc ESP
  cross-toolchains (`xtensa-lx106-elf-g++`), so every compile failed with
  `not found` (exit 127). Compiles/flashes now work.
- Replaced bashio/`with-contenv` startup with a plain `/data/options.json`
  read; cleared the base image's inherited `ENTRYPOINT` and `HEALTHCHECK`
  (the dashboard healthcheck caused a ~60s restart loop).
- Default port moved to **8098** so the fork can run beside the original.

### Added

- Background builds: `esphome_compile` / `esphome_flash` run in a thread and
  return a pollable handle for long builds, with new `esphome_build_status`
  to check progress — avoids MCP request timeouts on multi-minute compiles.
- `esphome_flash` forces OTA (`--device <name>.local`) so it no longer hangs
  on the interactive serial/OTA chooser when USB adapters are present.

## [1.0.0] - 2026-03-17

### Added

- Initial release as Home Assistant add-on
- FastMCP server with streamable HTTP transport on port 8099
- Bearer token authentication (auto-generated or user-configured)
- Nine MCP tools: list_devices, validate, compile, flash, logs,
  push_files, pull_files, push_fonts, pull_fonts
- Direct filesystem access to `/config/esphome/` — no SSH required
- Alpine-based Docker image with ESPHome and PlatformIO pre-installed
- Multi-architecture support (aarch64, amd64)
- Add-on documentation (DOCS.md)
- secrets.yaml protection in push/pull operations
