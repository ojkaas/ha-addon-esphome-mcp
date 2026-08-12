"""Build-backend router.

Selects, per operation, whether ESPHome build/flash/validate/logs/list run via
the ESPHome Device Builder **dashboard** (``dashboard.py``) or the **local**
bundled ``esphome`` CLI (``local.py``). Both modules expose the same async
interface — ``list_devices``, ``validate``, ``compile``, ``upload``, ``logs`` —
so dispatch is a simple module choice.

Mode is set by the ``BUILD_BACKEND`` env var (from the ``build_backend`` add-on
option):

* ``dashboard`` — always delegate; surfaces an error if the dashboard is down.
* ``bundled``   — always use the local toolchain.
* ``auto`` (default) — probe the dashboard; reachable → dashboard, else local.

File/font tools do not go through here; they always use direct filesystem
access and depend on neither backend.
"""

from __future__ import annotations

import logging
import os
import time

from . import dashboard, local
from .dashboard import strip_ansi  # re-exported for callers  # noqa: F401

log = logging.getLogger("esphome-mcp")

DASHBOARD = "dashboard"
LOCAL = "local"
_VALID_MODES = ("auto", DASHBOARD, "bundled")

# Remember the last backend we logged so we announce it on startup and on every
# change, without logging the same choice on every single call.
_last_logged: dict[str, str | None] = {"which": None}

# Cache the dashboard probe briefly so a compile-then-flash sequence doesn't
# re-probe between steps (and flap backends mid-deploy).
_PROBE_TTL = 10.0
_PROBE_TIMEOUT = 3.0
_probe: dict[str, float | bool | None] = {"ok": None, "ts": 0.0}


def _mode() -> str:
    """Configured backend mode, defaulting to ``auto`` for unknown values."""
    mode = os.environ.get("BUILD_BACKEND", "auto").strip().lower()
    return mode if mode in _VALID_MODES else "auto"


def choose(mode: str, dashboard_up: bool) -> str:
    """Pure backend decision. Kept separate so it is unit-testable.

    ``dashboard_up`` is only consulted in ``auto`` mode.
    """
    if mode == DASHBOARD:
        return DASHBOARD
    if mode == "bundled":
        return LOCAL
    return DASHBOARD if dashboard_up else LOCAL


async def _dashboard_up() -> bool:
    """Probe the dashboard, cached for ``_PROBE_TTL`` seconds."""
    now = time.monotonic()
    ok = _probe["ok"]
    if ok is not None and (now - float(_probe["ts"])) < _PROBE_TTL:
        return bool(ok)
    ok = await dashboard.ping(timeout=_PROBE_TIMEOUT)
    _probe["ok"] = ok
    _probe["ts"] = now
    return ok


async def _impl():
    """Resolve the backend module to use for this call, logging any change."""
    mode = _mode()
    up = await _dashboard_up() if mode == "auto" else None
    which = choose(mode, bool(up))
    if _last_logged["which"] != which:
        if mode == "auto":
            log.info(
                "Build backend -> %s (mode=auto, dashboard %s)",
                which,
                "reachable" if up else "unreachable",
            )
        else:
            log.info("Build backend -> %s (mode=%s)", which, mode)
        _last_logged["which"] = which
    return dashboard if which == DASHBOARD else local


def describe() -> str:
    """Human description of the active backend, for error messages."""
    mode = _mode()
    if mode == DASHBOARD:
        return f"dashboard at {dashboard.DASHBOARD_URL}"
    if mode == "bundled":
        return "bundled esphome"
    return f"auto: dashboard at {dashboard.DASHBOARD_URL}, else bundled esphome"


# ---------------------------------------------------------------------------
# Dispatch — identical signatures on dashboard.py and local.py
# ---------------------------------------------------------------------------
async def list_devices() -> dict:
    return await (await _impl()).list_devices()


async def validate(configuration: str) -> tuple[bool, str]:
    return await (await _impl()).validate(configuration)


async def compile(configuration, on_line) -> int:
    return await (await _impl()).compile(configuration, on_line)


async def upload(configuration, on_line) -> int:
    return await (await _impl()).upload(configuration, on_line)


async def logs(configuration, on_line, *, max_lines: int = 50) -> int:
    return await (await _impl()).logs(configuration, on_line, max_lines=max_lines)
