"""Bearer token authentication middleware for the MCP server."""

import hmac
import logging
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

log = logging.getLogger("esphome-mcp")


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Validates Bearer token on all requests."""

    async def dispatch(self, request: Request, call_next):
        # Allow health check without auth
        if request.url.path == "/health":
            return await call_next(request)

        expected_token = os.environ.get("ESPHOME_MCP_AUTH_TOKEN", "")
        if not expected_token:
            # Fail closed. run.sh always exports a token — generating and
            # persisting one to /data/auth_token when the option is blank — so
            # an empty value here means the server was started outside that
            # path. Serving the tools anyway would expose read/write access to
            # /config to anyone who can reach the port.
            log.error(
                "ESPHOME_MCP_AUTH_TOKEN is empty; refusing all requests. "
                "Start the server via run.sh, or set the variable explicitly."
            )
            return JSONResponse(
                {"error": "Server misconfigured: no auth token set"},
                status_code=503,
            )

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                {"error": "Missing or invalid Authorization header"},
                status_code=401,
            )

        token = auth_header[len("Bearer "):]
        # compare_digest runs in time independent of where the first mismatch
        # falls, so a caller cannot recover the token byte by byte from
        # response timing. Compare as bytes: the str form rejects non-ASCII,
        # and the token is user-configurable.
        if not hmac.compare_digest(token.encode("utf-8"), expected_token.encode("utf-8")):
            return JSONResponse(
                {"error": "Invalid token"},
                status_code=403,
            )

        return await call_next(request)
