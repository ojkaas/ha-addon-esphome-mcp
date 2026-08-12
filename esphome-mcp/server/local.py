"""Local ``esphome`` CLI backend — the bundled fallback.

Used when ``build_backend=bundled``, or in ``auto`` mode when the ESPHome
Device Builder dashboard is unreachable. Runs the ``esphome`` binary that the
Debian/glibc base image ships (see the Dockerfile) as a subprocess and streams
its stdout line-by-line, mirroring ``dashboard.py``'s streaming contract so
``backend.py`` can dispatch to either interchangeably.

Compilation reuses the dashboard add-on's PlatformIO toolchains via
``PLATFORMIO_CORE_DIR`` (set in ``run.sh``), so the fallback does not
re-download a toolchain.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable

ESPHOME_DIR = os.environ.get("ESPHOME_DIR", "/config/esphome")
# Overridable mainly so tests can point at a stub instead of a real esphome.
ESPHOME_BIN = os.environ.get("ESPHOME_BIN", "esphome")

# esphome resolves the YAML's mDNS address and forces an OTA (never serial)
# upload when the device is given as "OTA".
OTA_PORT = "OTA"

FORBIDDEN_LIST = {"secrets.yaml", ".secret.yaml"}


def _config_path(configuration: str) -> str:
    """Absolute path to a device YAML inside ESPHOME_DIR."""
    return os.path.join(ESPHOME_DIR, os.path.basename(configuration))


async def _stream(
    args: list[str],
    on_line: Callable[[str], None],
    *,
    idle_timeout: float | None = None,
    max_lines: int | None = None,
) -> int:
    """Run ``esphome <args>`` in ESPHOME_DIR, streaming stdout to *on_line*.

    Returns the process exit code. ``idle_timeout`` caps the wait for each new
    line (used by ``logs``, which otherwise streams forever); ``max_lines``
    stops after that many lines. When either cap fires the process is
    terminated.
    """
    proc = await asyncio.create_subprocess_exec(
        ESPHOME_BIN,
        *args,
        cwd=ESPHOME_DIR,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    assert proc.stdout is not None

    capped = False
    count = 0
    try:
        while True:
            if idle_timeout is not None:
                try:
                    line = await asyncio.wait_for(
                        proc.stdout.readline(), timeout=idle_timeout
                    )
                except asyncio.TimeoutError:
                    capped = True
                    break
            else:
                line = await proc.stdout.readline()
            if not line:
                break
            on_line(line.decode("utf-8", "replace").rstrip("\n"))
            count += 1
            if max_lines is not None and count >= max_lines:
                capped = True
                break
    finally:
        if capped and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()

    if proc.returncode is None:
        await proc.wait()
    # A capped stream (logs) has no meaningful exit code; report success.
    return 0 if capped else (proc.returncode or 0)


# ---------------------------------------------------------------------------
# Uniform backend interface (see backend.py)
# ---------------------------------------------------------------------------
async def list_devices() -> dict:
    """List device configs by scanning ESPHOME_DIR (no dashboard inventory).

    Returns the same shape as ``dashboard.list_devices`` so callers don't care
    which backend produced it. Friendly names aren't parsed here to avoid a
    YAML dependency; the filename stem is used as the device name.
    """
    configured = []
    try:
        entries = sorted(os.listdir(ESPHOME_DIR))
    except OSError:
        entries = []
    for fn in entries:
        if not fn.endswith(".yaml") or fn in FORBIDDEN_LIST:
            continue
        if not os.path.isfile(os.path.join(ESPHOME_DIR, fn)):
            continue
        configured.append({"name": fn[:-5], "configuration": fn})
    return {"configured": configured, "importable": []}


async def validate(configuration: str) -> tuple[bool, str]:
    """Validate a config with ``esphome config``; (ok, output)."""
    lines: list[str] = []
    rc = await _stream(["config", _config_path(configuration)], lines.append)
    return rc == 0, "\n".join(lines)


async def compile(configuration: str, on_line: Callable[[str], None]) -> int:
    """Compile firmware with ``esphome compile``."""
    return await _stream(["compile", _config_path(configuration)], on_line)


async def upload(configuration: str, on_line: Callable[[str], None]) -> int:
    """OTA-flash the last build with ``esphome upload --device OTA``."""
    return await _stream(
        ["upload", _config_path(configuration), "--device", OTA_PORT], on_line
    )


async def logs(
    configuration: str, on_line: Callable[[str], None], *, max_lines: int = 50
) -> int:
    """Snapshot up to *max_lines* of ``esphome logs`` output, then stop."""
    await _stream(
        ["logs", _config_path(configuration), "--device", OTA_PORT],
        on_line,
        idle_timeout=15.0,
        max_lines=max_lines,
    )
    return 0
