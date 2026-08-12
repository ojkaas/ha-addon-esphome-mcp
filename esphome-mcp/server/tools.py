"""ESPHome MCP tool implementations.

Build/flash/validate/logs/list are routed through ``backend.py``, which picks
per call between delegating to the ESPHome Device Builder dashboard
(``dashboard.py``) and running the bundled ``esphome`` CLI (``local.py``),
according to the ``build_backend`` option. The default delegates so builds run
against the dashboard's current esphome; the bundled path is the fallback.

File and font tools bypass the backend entirely and operate directly on the
shared Home Assistant filesystem (``/config/esphome``).
"""

import asyncio
import base64
import collections
import concurrent.futures
import glob
import logging
import os
import threading
import time

from . import backend

log = logging.getLogger("esphome-mcp")

ESPHOME_DIR = os.environ.get("ESPHOME_DIR", "/config/esphome")

FORBIDDEN_FILES = {"secrets.yaml", ".secret.yaml"}

# How long compile/flash wait synchronously before returning a pollable
# handle. Must stay comfortably under the MCP client's request timeout so a
# long build returns a handle instead of erroring with a transport timeout.
SYNC_WAIT_WINDOW = 45
# Hard caps on background builds.
COMPILE_TIMEOUT = 600
FLASH_TIMEOUT = 900
# install = compile + flash, so it needs the compile budget plus the upload
# budget rather than either one alone.
INSTALL_TIMEOUT = COMPILE_TIMEOUT + FLASH_TIMEOUT

# Upper bound on retained output lines per build. A build that loops or spews
# progress would otherwise grow this list without limit for the lifetime of the
# process. The tail is what diagnoses a failure, so keep the most recent lines
# and report how many were dropped.
MAX_BUILD_LINES = 5000

# Background build registry, keyed by device YAML filename.
_BUILDS: dict[str, dict] = {}
_BUILDS_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _resolve_device(device: str) -> str:
    """Resolve a device name to its YAML filename (without path)."""
    if not device.endswith(".yaml"):
        device = f"{device}.yaml"
    return device


def _safe_join(base: str, relpath: str) -> str | None:
    """Join *relpath* onto *base*, returning None if it escapes *base*.

    Client-supplied filenames must never resolve outside the config
    directory. Reject absolute paths and any ``..`` traversal by comparing
    the normalised absolute target against ``base`` (which the config tools
    all live under).
    """
    base_abs = os.path.abspath(base)
    target = os.path.abspath(os.path.join(base_abs, relpath))
    if target != base_abs and not target.startswith(base_abs + os.sep):
        return None
    return target


def _is_forbidden(filename: str) -> bool:
    """Check if a filename is forbidden for transfer."""
    return os.path.basename(filename).lower() in FORBIDDEN_FILES


def _run_async(coro):
    """Run a coroutine to completion from a sync tool.

    FastMCP invokes these sync tools directly on its event-loop thread, so a
    bare ``asyncio.run()`` raises "cannot be called from a running event
    loop". Offload to a worker thread that owns its own fresh loop.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, coro).result()


# ---------------------------------------------------------------------------
# Background builds (compile/flash) — the dashboard WS stream is consumed in a
# worker thread so a slow build returns a pollable handle instead of hitting
# the MCP request timeout. The dashboard also queues the job server-side, so
# it survives even if we stop polling.
# ---------------------------------------------------------------------------
def _append_line(job: dict, line: str) -> None:
    """Record one output line. Caller must hold ``_BUILDS_LOCK``."""
    lines = job["lines"]
    if len(lines) == lines.maxlen:
        job["dropped"] += 1
    lines.append(line)


def _render_lines(job: dict) -> str:
    """Join a job's retained output. Caller must hold ``_BUILDS_LOCK``."""
    body = "\n".join(job["lines"])
    if not job["dropped"]:
        return body
    return (
        f"[... {job['dropped']} earlier line(s) dropped, "
        f"output capped at {MAX_BUILD_LINES} lines ...]\n{body}"
    )


def _build_worker(job: dict, kind: str, configuration: str, timeout: int) -> None:
    def on_line(line: str) -> None:
        with _BUILDS_LOCK:
            _append_line(job, backend.strip_ansi(line))

    async def _compile() -> int:
        return await backend.compile(configuration, on_line)

    async def _upload() -> int:
        return await backend.upload(configuration, on_line)

    async def run() -> int:
        if kind == "flash":
            return await _upload()
        if kind == "compile":
            return await _compile()
        # install: compile from source, then flash — but only if the compile
        # succeeded. Flashing after a failed compile would push a stale binary,
        # which is exactly the footgun this fused step exists to avoid.
        on_line("[install] Step 1/2: compiling from source...")
        rc = await _compile()
        if rc != 0:
            on_line(f"[install] Compile failed (exit {rc}); NOT flashing.")
            return rc
        on_line("[install] Step 2/2: compile OK, flashing (OTA)...")
        return await _upload()

    try:
        rc = asyncio.run(asyncio.wait_for(run(), timeout))
    except asyncio.TimeoutError:
        rc = -1
        on_line(f"[killed: exceeded {timeout}s timeout]")
    except Exception as e:  # noqa: BLE001 - surface any transport/dashboard fault
        rc = -1
        on_line(f"[error contacting build backend ({backend.describe()}): {e}]")

    with _BUILDS_LOCK:
        job["returncode"] = rc
        job["finished"] = time.time()
        job["status"] = "done" if rc == 0 else "failed"


def _start_build(
    key: str, kind: str, configuration: str, timeout: int
) -> tuple[dict, str | None]:
    """Start a background build for ``key``, or reuse the running one.

    Returns ``(job, conflict)``; ``conflict`` is a message to hand back to the
    caller instead of the job when the request cannot be served.

    Reuse is only correct when the running job is the SAME operation. The
    registry is keyed by configuration alone so ``build_status`` can find a
    device's build from its name, which means compile/flash/install all collide
    on one key. Handing back a different operation's job would report a running
    compile as though it were the flash that was asked for — and no flash would
    ever happen. Refuse that case explicitly.
    """
    with _BUILDS_LOCK:
        job = _BUILDS.get(key)
        if job and job["status"] == "running":
            if job["kind"] == kind:
                return job, None
            return job, (
                f"Cannot start {kind} for {key}: a {job['kind']} is already "
                f"running for this device. Poll it with "
                f"esphome_build_status(device='{key}'), then retry once it "
                f"finishes."
            )
        job = {
            "status": "running",
            "kind": kind,
            "lines": collections.deque(maxlen=MAX_BUILD_LINES),
            "dropped": 0,
            "returncode": None,
            "started": time.time(),
            "finished": None,
        }
        _BUILDS[key] = job
    threading.Thread(
        target=_build_worker, args=(job, kind, configuration, timeout), daemon=True
    ).start()
    return job, None


def _job_snapshot(job: dict) -> tuple[str, str, int | None]:
    with _BUILDS_LOCK:
        return job["status"], _render_lines(job), job["returncode"]


def _await_or_handle(key: str, job: dict, label: str) -> str:
    """Wait up to SYNC_WAIT_WINDOW for completion, else return a poll handle."""
    deadline = time.time() + SYNC_WAIT_WINDOW
    while time.time() < deadline:
        status, _, _ = _job_snapshot(job)
        if status != "running":
            break
        time.sleep(1)

    status, output, rc = _job_snapshot(job)
    if status == "running":
        elapsed = int(time.time() - job["started"])
        tail = "\n".join(output.splitlines()[-15:])
        return (
            f"{label} still running ({elapsed}s elapsed). The build continues "
            f"in the background — poll it with "
            f"esphome_build_status(device='{key}').\n\n"
            f"--- output so far (tail) ---\n{tail}"
        )
    if rc != 0:
        return f"Command failed (exit {rc}):\n{output}"
    return output


# ---------------------------------------------------------------------------
# Tool functions — delegated to the dashboard
# ---------------------------------------------------------------------------
def list_devices() -> str:
    """List all ESPHome device configurations known to the dashboard."""
    try:
        data = _run_async(backend.list_devices())
    except Exception as e:  # noqa: BLE001
        return f"Failed to reach build backend ({backend.describe()}): {e}"

    configured = data.get("configured", [])
    if not configured:
        return "No device configurations found."

    lines = ["ESPHome Devices:", ""]
    for d in configured:
        name = d.get("name", "unknown")
        friendly = f' ("{d["friendly_name"]}")' if d.get("friendly_name") else ""
        conf = d.get("configuration", "")
        lines.append(f"  - {name}{friendly} ({conf})")
    return "\n".join(lines)


def validate(device: str) -> str:
    """Validate an ESPHome device config via the dashboard."""
    configuration = _resolve_device(device)
    try:
        ok, message = _run_async(backend.validate(configuration))
    except Exception as e:  # noqa: BLE001
        return f"Failed to reach build backend ({backend.describe()}): {e}"
    if ok:
        # A valid config streams its entire resolved YAML (hundreds of lines);
        # the caller only needs the verdict, so report success concisely.
        return f"Configuration is valid: {configuration}"
    return f"Validation FAILED for {configuration}:\n\n{message}"


def _run_build(device: str, kind: str, timeout: int, label: str) -> str:
    """Start (or join) a background build and return output or a poll handle."""
    configuration = _resolve_device(device)
    key = configuration
    job, conflict = _start_build(key, kind, configuration, timeout)
    if conflict:
        return conflict
    return _await_or_handle(key, job, label)


def compile_device(device: str) -> str:
    """Compile ESPHome firmware for a device (dashboard build, backgrounded)."""
    return _run_build(device, "compile", COMPILE_TIMEOUT, "Compile")


def flash(device: str) -> str:
    """OTA flash the LAST-COMPILED firmware (does NOT rebuild first)."""
    return _run_build(device, "flash", FLASH_TIMEOUT, "Flash")


def install(device: str) -> str:
    """Compile from source then OTA flash — the full deploy of current YAML."""
    return _run_build(device, "install", INSTALL_TIMEOUT, "Install")


def build_status(device: str) -> str:
    """Return the status and output of the latest compile/flash for a device."""
    key = _resolve_device(device)
    with _BUILDS_LOCK:
        job = _BUILDS.get(key)
        if job is None:
            return f"No build found for '{key}'. Start one with esphome_install."
        status = job["status"]
        kind = job["kind"]
        output = _render_lines(job)
        rc = job["returncode"]
        started = job["started"]
        finished = job["finished"]

    if status == "running":
        elapsed = int(time.time() - started)
        tail = "\n".join(output.splitlines()[-30:])
        return (
            f"{kind.capitalize()} running ({elapsed}s elapsed).\n\n"
            f"--- output (tail) ---\n{tail}"
        )

    duration = int((finished or time.time()) - started)
    return f"{kind.capitalize()} {status} (exit {rc}, took {duration}s):\n{output}"


def logs(device: str, num_lines: int = 50) -> str:
    """Snapshot recent device logs via the dashboard's /ws log stream."""
    configuration = _resolve_device(device)
    collected: list[str] = []

    try:
        _run_async(
            backend.logs(
                configuration,
                lambda line: collected.append(backend.strip_ansi(line)),
                max_lines=num_lines,
            )
        )
    except Exception as e:  # noqa: BLE001
        return f"Failed to stream logs from build backend ({backend.describe()}): {e}"

    if not collected:
        return f"No log output captured for {configuration} (device offline?)."
    return "\n".join(collected[-num_lines:])


# ---------------------------------------------------------------------------
# File / font tools — local filesystem on the shared /config mount
# ---------------------------------------------------------------------------
def push_files(files: dict[str, str]) -> str:
    """Write YAML files to the ESPHome config directory.

    Args:
        files: Dict mapping filename to YAML content.
    """
    results = []
    for filename, content in files.items():
        if _is_forbidden(filename):
            results.append(f"{filename}: REJECTED (secrets files cannot be pushed)")
            continue
        if not filename.endswith(".yaml"):
            results.append(f"{filename}: REJECTED (only .yaml files allowed)")
            continue

        # Support the archive/ subdirectory but never let a filename escape
        # the config directory via absolute paths or ``..`` traversal.
        target = _safe_join(ESPHOME_DIR, filename)
        if target is None:
            results.append(f"{filename}: REJECTED (path escapes config directory)")
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)

        try:
            with open(target, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
            results.append(f"{filename}: OK")
        except OSError as e:
            results.append(f"{filename}: ERROR ({e})")

    return "Push results:\n" + "\n".join(results)


def pull_files(filenames: list[str] | None = None) -> dict[str, str]:
    """Read YAML files from the ESPHome config directory.

    Args:
        filenames: Optional list of filenames to pull. If None, pulls all.

    Returns:
        Dict mapping filename to YAML content.
    """
    result = {}

    if filenames is None:
        # Pull all YAML files
        paths = sorted(glob.glob(os.path.join(ESPHOME_DIR, "*.yaml")))
        archive_dir = os.path.join(ESPHOME_DIR, "archive")
        if os.path.isdir(archive_dir):
            paths += sorted(glob.glob(os.path.join(archive_dir, "*.yaml")))
    else:
        paths = []
        for fn in filenames:
            if not fn.endswith(".yaml"):
                fn = f"{fn}.yaml"
            path = _safe_join(ESPHOME_DIR, fn)
            if path is None:
                continue
            if os.path.isfile(path):
                paths.append(path)
            else:
                archive_path = _safe_join(ESPHOME_DIR, os.path.join("archive", fn))
                if archive_path is not None and os.path.isfile(archive_path):
                    paths.append(archive_path)

    for path in paths:
        if _is_forbidden(path):
            continue
        rel = os.path.relpath(path, ESPHOME_DIR)
        try:
            with open(path, encoding="utf-8") as f:
                result[rel] = f.read()
        except OSError as e:
            result[rel] = f"ERROR: {e}"

    return result


def push_fonts(files: dict[str, str]) -> str:
    """Write font files to the ESPHome fonts directory.

    Args:
        files: Dict mapping filename to base64-encoded content.
    """
    fonts_dir = os.path.join(ESPHOME_DIR, "fonts")
    os.makedirs(fonts_dir, exist_ok=True)

    results = []
    for filename, b64_content in files.items():
        target = os.path.join(fonts_dir, os.path.basename(filename))
        try:
            data = base64.b64decode(b64_content)
            with open(target, "wb") as f:
                f.write(data)
            results.append(f"{filename}: OK ({len(data)} bytes)")
        except Exception as e:
            results.append(f"{filename}: ERROR ({e})")

    return "Font push results:\n" + "\n".join(results)


def pull_fonts(filenames: list[str] | None = None) -> dict[str, str]:
    """Read font files from the ESPHome fonts directory.

    Args:
        filenames: Optional list of font filenames. If None, pulls all.

    Returns:
        Dict mapping filename to base64-encoded content.
    """
    fonts_dir = os.path.join(ESPHOME_DIR, "fonts")
    result = {}

    if not os.path.isdir(fonts_dir):
        return result

    if filenames is None:
        paths = sorted(glob.glob(os.path.join(fonts_dir, "*")))
    else:
        paths = [
            os.path.join(fonts_dir, os.path.basename(fn))
            for fn in filenames
            if os.path.isfile(os.path.join(fonts_dir, os.path.basename(fn)))
        ]

    for path in paths:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "rb") as f:
                data = f.read()
            result[os.path.basename(path)] = base64.b64encode(data).decode("ascii")
        except OSError as e:
            result[os.path.basename(path)] = f"ERROR: {e}"

    return result
