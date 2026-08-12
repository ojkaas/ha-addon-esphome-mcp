"""Client for the ESPHome Device Builder dashboard HTTP/WS API.

The MCP no longer runs ``esphome`` in its own container. Every build,
flash, validate, logs and device-list operation is delegated to the
Device Builder dashboard running in the official ESPHome add-on — so
compilation always uses that add-on's (current) ESPHome, and this add-on
carries no ESP toolchain and no version pin.

Wire protocols (from esphome/device-builder):

* ``GET /devices`` — ``{"configured": [...], "importable": [...]}``.
* ``GET /json-config?configuration=<f>.yaml`` — 200 when the config is
  valid, 422 when it ran and failed, other codes for infra faults.
* ``GET /compile`` and ``GET /upload`` (WebSocket, "spawn" protocol):
  client sends ``{"type": "spawn", "configuration": "<f>.yaml",
  "port": "OTA"}`` (``port`` for /upload only); server streams
  ``{"event": "line", "data": "<chunk>"}`` and ends with
  ``{"event": "exit", "code": <int>}``.
* ``GET /ws`` (multiplexed): send ``{"command": "devices/logs",
  "message_id": "<id>", "args": {...}}``; server streams
  ``{"message_id", "event": "output", "data": "<line>"}`` and a final
  ``{"event": "result", "data": {...}}``. Cancel with
  ``devices/stop_stream``. Pre-authenticated when the dashboard has no
  password set.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
from collections.abc import Callable

import aiohttp

# ``esphome config`` colourises its output with ANSI SGR escapes (and wraps
# secret values in the conceal SGR). The dashboard delivers these as the
# literal text ``\033[..m`` / ``\x1b[..m`` (escaped, not the raw 0x1b byte),
# so match both the real control byte and its escaped textual forms. Strip
# every escape so the text that reaches the MCP client is clean and greppable.
_ANSI_RE = re.compile(r"(?:\x1b|\\x1b|\\033|\\e)\[[0-9;]*[A-Za-z]")


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences (real or literally-escaped) from *text*."""
    return _ANSI_RE.sub("", text)

# The HA ESPHome add-on serves the dashboard ingress-only on
# ``127.0.0.1:<ingress_port>``; this add-on runs host_network so loopback (a
# trusted peer) reaches it. Set the ``dashboard_url`` option to that port.
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://127.0.0.1:6052").rstrip("/")
# Only needed if the dashboard has a password configured; blank = open.
DASHBOARD_TOKEN = os.environ.get("DASHBOARD_TOKEN", "")

# Legacy spawn protocol uses "OTA" to make the CLI resolve the YAML's
# mDNS address and force an over-the-air upload (never serial).
OTA_PORT = "OTA"


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {DASHBOARD_TOKEN}"} if DASHBOARD_TOKEN else {}


def _ws_url(path: str) -> str:
    base = DASHBOARD_URL.replace("https://", "wss://").replace("http://", "ws://")
    return base + path


def _session() -> aiohttp.ClientSession:
    return aiohttp.ClientSession(headers=_headers())


# ---------------------------------------------------------------------------
# REST
# ---------------------------------------------------------------------------
async def list_devices() -> dict:
    """Return the dashboard's device inventory."""
    async with _session() as s:
        async with s.get(f"{DASHBOARD_URL}/devices") as r:
            r.raise_for_status()
            return await r.json()


async def validate(
    configuration: str, *, timeout: float = 120.0
) -> tuple[bool, str]:
    """Validate a config by streaming ``devices/validate`` over ``/ws``.

    Returns (ok, output). The dashboard runs ``esphome config`` and streams
    its full stdout/stderr — component errors, line numbers, the works — then
    a final ``result`` frame with the exit code. We deliberately do **not**
    use ``GET /json-config``: that endpoint collapses any failure to a bare
    ``{"error": "Configuration is invalid"}`` (it suppresses the real message
    because ``--show-secrets`` output can leak resolved secrets), so it can
    never tell the caller *why* a config is invalid.

    ``show_secrets`` is left False so the dashboard scrubs resolved
    ``!secret`` values before they cross the wire.
    """
    mid = "mcp-validate"
    lines: list[str] = []
    success: bool | None = None
    async with _session() as s:
        async with s.ws_connect(_ws_url("/ws"), heartbeat=30) as ws:
            await ws.send_json(
                {
                    "command": "devices/validate",
                    "message_id": mid,
                    "args": {
                        "configuration": configuration,
                        "show_secrets": False,
                    },
                }
            )
            while True:
                try:
                    msg = await ws.receive(timeout=timeout)
                except asyncio.TimeoutError:
                    lines.append(f"[validate timed out after {timeout:.0f}s]")
                    break
                if msg.type is not aiohttp.WSMsgType.TEXT:
                    break
                frame = json.loads(msg.data)
                # The dashboard pushes an unsolicited server-info "hello"
                # frame on connect; it carries no ``message_id``/``event``,
                # so the event checks below skip it.
                event = frame.get("event")
                if event == "output":
                    lines.append(strip_ansi(str(frame.get("data", ""))))
                elif event == "result":
                    success = bool((frame.get("data") or {}).get("success"))
                    break
                elif frame.get("error_code"):
                    lines.append(
                        f"[dashboard error {frame.get('error_code')}] "
                        f"{frame.get('details', '')}"
                    )
                    success = False
                    break

    output = "\n".join(lines).strip()
    if success:
        return True, output or "Configuration is valid!"
    if success is None:
        # Stream ended without a result frame — treat as failure but return
        # whatever we captured so the caller isn't left blind.
        return False, output or "Validation ended without a result from the dashboard."
    return False, output or "Configuration is invalid (no detail returned)."


# ---------------------------------------------------------------------------
# WebSocket streams
# ---------------------------------------------------------------------------
async def stream_spawn(
    path: str,
    configuration: str,
    on_line: Callable[[str], None],
    *,
    port: str | None = None,
) -> int:
    """Drive the legacy ``/compile`` or ``/upload`` spawn protocol.

    Streams each output line to ``on_line`` and returns the build's exit
    code (1 if the socket closes without an explicit exit frame).
    """
    spawn: dict[str, str] = {"type": "spawn", "configuration": configuration}
    if port is not None:
        spawn["port"] = port
    async with _session() as s:
        async with s.ws_connect(_ws_url(path), heartbeat=30) as ws:
            await ws.send_json(spawn)
            async for msg in ws:
                if msg.type is not aiohttp.WSMsgType.TEXT:
                    continue
                frame = json.loads(msg.data)
                event = frame.get("event")
                if event == "line":
                    on_line(str(frame.get("data", "")).rstrip("\n"))
                elif event == "exit":
                    code = frame.get("code")
                    return int(code) if code is not None else 1
    return 1


async def stream_logs(
    configuration: str,
    on_line: Callable[[str], None],
    *,
    max_lines: int = 50,
    timeout: float = 15.0,
    port: str = OTA_PORT,
) -> int:
    """Snapshot up to ``max_lines`` of live device logs, then stop.

    ``esphome logs`` streams indefinitely, so we cap by line count and an
    idle ``timeout`` and then cancel the stream server-side.
    """
    mid = "mcp-logs"
    count = 0
    async with _session() as s:
        async with s.ws_connect(_ws_url("/ws"), heartbeat=30) as ws:
            await ws.send_json(
                {
                    "command": "devices/logs",
                    "message_id": mid,
                    "args": {
                        "configuration": configuration,
                        "port": port,
                        "no_states": True,
                    },
                }
            )
            try:
                while count < max_lines:
                    msg = await ws.receive(timeout=timeout)
                    if msg.type is not aiohttp.WSMsgType.TEXT:
                        break
                    frame = json.loads(msg.data)
                    event = frame.get("event")
                    if event == "output":
                        on_line(str(frame.get("data", "")))
                        count += 1
                    elif event == "result":
                        break
                    elif frame.get("error_code"):
                        on_line(f"[dashboard error] {frame.get('details', '')}")
                        break
            except asyncio.TimeoutError:
                pass
            finally:
                with contextlib.suppress(Exception):
                    await ws.send_json(
                        {
                            "command": "devices/stop_stream",
                            "message_id": "mcp-logs-stop",
                            "args": {"stream_id": mid},
                        }
                    )
    return 0
