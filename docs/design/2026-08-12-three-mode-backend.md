# Three-mode build backend — design

Date: 2026-08-12
Status: approved, in implementation

## Background

This add-on exposes ESPHome operations to MCP clients (Claude Code). Its
history runs `bberrevoets` → `ojkaas` (this repo) → community forks:

- **scadinot** — kept the original *bundled ESPHome* design and bumped the
  pinned ESPHome image + fixed the "add-on stuck on Starting" healthcheck bug.
- **dmitrii-galantsev** — re-architected to *delegate* every build/flash/
  validate/logs call to the official ESPHome **Device Builder** dashboard over
  its HTTP/WS API, dropping the bundled toolchain and the light Alpine base.

Delegation is the better default (always-current ESPHome, no version
maintenance), but it hard-depends on the dashboard add-on running. This design
keeps delegation as the default **and** adds a bundled fallback so builds still
work when the dashboard is unavailable — the versatile combination.

## Decisions

- **Base image:** the official ESPHome image (`ghcr.io/esphome/esphome`,
  Debian/glibc) so the bundled fallback has a working ESP toolchain. Cost: the
  image is large again in all modes (unavoidable for offline builds). Because
  that base ships a dashboard `HEALTHCHECK`, scadinot's fix is folded back in
  (`ENTRYPOINT []` + a real `HEALTHCHECK` hitting an unauthenticated `/health`).
- **Toolchain reuse:** `PLATFORMIO_CORE_DIR=/config/esphome/.esphome/.platformio`
  so the bundled fallback reuses the toolchains the dashboard already downloaded.
- **Maintainer/attribution:** current maintainer `ojkaas`; README + config
  credit `bberrevoets` (original), `dmitrii-galantsev` (delegation), and
  `scadinot` (healthcheck fix).

## Config options (new)

| Option | Values | Default | Meaning |
|---|---|---|---|
| `build_backend` | `auto` \| `dashboard` \| `bundled` | `auto` | How build/flash/validate/logs run |
| `esphome_version` | version string or `""` | `""` | Pins the **bundled fallback** ESPHome version; `""` = image default |

- **auto** — probe the dashboard; reachable → delegate; unreachable → local
  bundled `esphome`.
- **dashboard** — delegate only; clear error if the dashboard is down.
- **bundled** — always use the local toolchain.

`esphome_version` only affects the bundled path. In dashboard mode the version
is whatever the dashboard runs. When set, `run.sh` reconciles it with
`pip install esphome==<version>` at start.

## Architecture

```
tools.py            MCP tool implementations (unchanged behaviour)
  └─ backend.py     router: resolve mode (env + dashboard probe), dispatch
       ├─ dashboard.py   delegation client (HTTP/WS)   [existing]
       └─ local.py       local `esphome` CLI client (subprocess)   [new]
```

`backend.py` presents one interface — `list_devices`, `validate`, `compile`,
`upload`, `logs`, `strip_ansi`, `target()` — and picks dashboard vs local per
call. `tools.py` calls `backend.*` instead of `dashboard.*` directly. File and
font tools are untouched: they always use direct `/config/esphome` filesystem
access and never depend on either backend.

### Mode resolution

- `BUILD_BACKEND=dashboard` → always dashboard.
- `BUILD_BACKEND=bundled` → always local.
- `BUILD_BACKEND=auto` (default) → probe `GET {DASHBOARD_URL}/devices` with a
  short timeout; success → dashboard, failure → local. Result cached briefly so
  a compile-then-flash sequence doesn't re-probe between steps.

### Local CLI client (`local.py`)

Runs `esphome` as a subprocess, streaming stdout line-by-line to mirror the
dashboard client's streaming contract:

- `validate` → `esphome config <file>` (ok = exit 0)
- `compile` → `esphome compile <file>`
- `upload`  → `esphome upload <file> --device OTA`
- `logs`    → `esphome logs <file> --device OTA` (capped by line count + idle)
- `list_devices` → scan `/config/esphome/*.yaml`

## Health endpoint

`GET /health` returns `ok`, exempt from bearer auth (the exemption already
exists in `auth.py`). It backs the container `HEALTHCHECK`.

## Testing

Unit-testable without HA or esphome: mode resolution, local `list_devices`
directory scan, ANSI stripping, path-safety. Full build/flash paths are
verified on-device (no HA/esphome in the dev environment).

## Out of scope

- Debian-slim + `pip install esphome` base (lighter image, but downloads the
  toolchain at first fallback compile — rejected for fallback reliability).
- Reintroducing per-release ESPHome image bumps as a maintenance task; the
  dashboard delegation default makes that unnecessary for most users.
