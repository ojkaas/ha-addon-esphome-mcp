"""ESPHome MCP Server — FastMCP application with streamable HTTP transport."""

import json
import logging
import os

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from . import tools
from .auth import BearerAuthMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("esphome-mcp")

mcp = FastMCP(
    name="esphome",
    host="0.0.0.0",
    stateless_http=True,
)


# ---------------------------------------------------------------------------
# Register tools
# ---------------------------------------------------------------------------
@mcp.tool()
def esphome_list_devices() -> str:
    """List all available ESPHome device configurations.

    Scans YAML files in the ESPHome config directory,
    returning device names and friendly names.
    """
    return tools.list_devices()


@mcp.tool()
def esphome_validate(device: str) -> str:
    """Validate an ESPHome device config.

    Args:
        device: Device name (e.g. 'statusdisplay') or YAML filename.
    """
    return tools.validate(device)


@mcp.tool()
def esphome_compile(device: str) -> str:
    """Compile firmware from the current YAML WITHOUT flashing it.

    Use this to check that a config builds. To actually deploy it to the
    device, use esphome_install (compile + flash) instead of compiling and
    then flashing separately.

    The build runs in the background. If it finishes quickly the full output
    is returned inline; if it takes longer than the sync window, a pollable
    handle is returned — check progress with esphome_build_status(device).

    Args:
        device: Device name (e.g. 'statusdisplay') or YAML filename.
    """
    return tools.compile_device(device)


@mcp.tool()
def esphome_install(device: str) -> str:
    """Deploy the current YAML: COMPILE from source, then OTA flash.

    THIS IS ALMOST ALWAYS THE TOOL YOU WANT after editing a config. It
    rebuilds the firmware from the current YAML and only flashes if that
    compile succeeds, so the device always runs the latest config.

    Prefer this over esphome_flash whenever the YAML may have changed. Use the
    bare esphome_flash ONLY to re-push an already-built binary without
    rebuilding (rare).

    Runs in the background and may return a pollable handle — check progress
    with esphome_build_status(device).

    Args:
        device: Device name (e.g. 'statusdisplay') or YAML filename.
    """
    return tools.install(device)


@mcp.tool()
def esphome_flash(device: str) -> str:
    """Flash the LAST-COMPILED firmware WITHOUT rebuilding it first.

    WARNING: this uploads the existing/old firmware.bin from the previous
    compile. It does NOT pick up any YAML changes. If you edited the config,
    this will flash a STALE binary. To deploy config changes, use
    esphome_install (compile + flash) instead.

    Only use this to re-push an already-built binary (e.g. a flash that failed
    mid-upload but the compile was fine).

    Runs in the background and may return a pollable handle — check progress
    with esphome_build_status(device).

    Args:
        device: Device name (e.g. 'statusdisplay') or YAML filename.
    """
    return tools.flash(device)


@mcp.tool()
def esphome_build_status(device: str) -> str:
    """Get the status/output of the latest background compile or flash.

    Use this to poll a build that esphome_compile / esphome_flash reported as
    still running. Returns running progress (tail) or the final result.

    Args:
        device: Device name (e.g. 'statusdisplay') or YAML filename.
    """
    return tools.build_status(device)


@mcp.tool()
def esphome_logs(device: str, num_lines: int = 50) -> str:
    """Get recent logs from an ESPHome device.

    Captures a snapshot of logs (streaming is not supported in MCP tools).

    Args:
        device: Device name (e.g. 'statusdisplay') or YAML filename.
        num_lines: Number of log lines to return (default 50).
    """
    return tools.logs(device, num_lines)


@mcp.tool()
def esphome_push_files(files: dict[str, str]) -> str:
    """Write YAML config files to /config/esphome/ (content passed inline).

    COST WARNING: this takes the full file CONTENT as an argument, which means
    reading the file into context and re-emitting it here — the bytes cross the
    model context twice. For anything but a tiny snippet, prefer the companion
    CLI, which reads the file from disk and uploads it without the content ever
    entering context:

        esphome-mcp push <file.yaml>

    Use this tool only when that CLI is unavailable, or for content you are
    generating inline anyway (not reading from a local file). Rejects
    secrets.yaml.

    Args:
        files: Dict mapping filename to YAML content.
               Use 'archive/name.yaml' for archived configs.
    """
    return tools.push_files(files)


@mcp.tool()
def esphome_pull_files(filenames: list[str] | None = None) -> str:
    """Read YAML config files from /config/esphome/ (content returned inline).

    COST WARNING: this returns the full file CONTENT into context. If the goal
    is to get files onto local disk, prefer the companion CLI, which writes them
    straight to disk without the content entering context:

        esphome-mcp pull [name...]

    Use this tool only when you actually need to inspect the content in the
    conversation, or when that CLI is unavailable. Excludes secrets.yaml.

    Args:
        filenames: Optional list of filenames to pull.
                   If omitted, returns all YAML files.
    """
    result = tools.pull_files(filenames)
    return json.dumps(result, indent=2)


@mcp.tool()
def esphome_push_fonts(files: dict[str, str]) -> str:
    """Push font files to the ESPHome fonts directory on Home Assistant.

    Args:
        files: Dict mapping filename to base64-encoded file content.
    """
    return tools.push_fonts(files)


@mcp.tool()
def esphome_pull_fonts(filenames: list[str] | None = None) -> str:
    """Pull font files from the ESPHome fonts directory on Home Assistant.

    Returns base64-encoded file contents.

    Args:
        filenames: Optional list of font filenames to pull.
                   If omitted, returns all fonts.
    """
    result = tools.pull_fonts(filenames)
    return json.dumps(result, indent=2)


# ---------------------------------------------------------------------------
# ASGI app with auth middleware
# ---------------------------------------------------------------------------
async def health(_request):
    """Liveness probe for the container HEALTHCHECK (exempt from auth).

    Home Assistant Supervisor holds an add-on in the ``startup`` state until
    Docker reports a health status for the container, so the image ships a
    healthcheck that actually runs and passes. ``BearerAuthMiddleware`` skips
    ``/health`` so the probe needs no token. See the Dockerfile for why
    ``HEALTHCHECK NONE`` is not a valid alternative here.
    """
    return PlainTextResponse("ok")


class _SuppressHealthAccessLog(logging.Filter):
    """Drop uvicorn access lines for the healthcheck probe.

    The container HEALTHCHECK polls /health every 10s, so leaving these in
    buries real activity under ~8600 access lines a day in the add-on log.
    Uvicorn passes the request as args (client, method, path, version, status);
    fall back to a substring test if that shape ever changes, so an unexpected
    record is kept rather than silently swallowed.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3:
            return args[2] != "/health"
        return "/health" not in record.getMessage()


logging.getLogger("uvicorn.access").addFilter(_SuppressHealthAccessLog())

app = mcp.streamable_http_app()
app.router.routes.append(Route("/health", health, methods=["GET"]))
app.add_middleware(BearerAuthMiddleware)


if __name__ == "__main__":
    port = int(os.environ.get("MCP_PORT", "8098"))
    log.info("ESPHome MCP Server starting on port %d", port)
    uvicorn.run(
        "server.main:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
