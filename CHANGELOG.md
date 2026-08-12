# Changelog

All notable changes to this project will be documented in this file.

## Attributors

- **Bert Berrevoets** — Project author
- **Claude Code** — AI-assisted development

## [1.2.5] - 2026-08-12

### Fixed

- The add-on stayed on **"Starting"** in the Home Assistant UI forever, even
  though the MCP server was up and answering requests. Supervisor derives the
  add-on state from `docker inspect .Config.Healthcheck`, and per the Docker
  image spec `HEALTHCHECK NONE` is encoded as a *populated* field
  (`{"Test": ["NONE"]}`) rather than an absent one. Supervisor therefore read
  "this container has a healthcheck" and held the add-on in `startup` waiting
  for a Docker health event that a disabled healthcheck never emits.
  `HEALTHCHECK NONE` is replaced by a real probe against the MCP server, so
  the add-on now reaches "Started" (and the watchdog toggle becomes
  meaningful).

### Added

- `GET /health` — unauthenticated liveness endpoint returning `ok`, used by
  the container healthcheck. The auth middleware already exempted this path;
  the route it pointed at simply did not exist until now.

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

Author: *Bert Berrevoets, Claude Code*

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
