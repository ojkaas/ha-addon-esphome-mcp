"""Unit tests for the Bearer token middleware."""

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from server.auth import BearerAuthMiddleware


@pytest.fixture
def client():
    app = Starlette(
        routes=[
            Route("/mcp", lambda r: PlainTextResponse("tool")),
            Route("/health", lambda r: PlainTextResponse("ok")),
        ]
    )
    app.add_middleware(BearerAuthMiddleware)
    return TestClient(app)


def test_health_needs_no_token(client, monkeypatch):
    monkeypatch.setenv("ESPHOME_MCP_AUTH_TOKEN", "sekret")
    assert client.get("/health").status_code == 200


def test_health_served_even_when_unconfigured(client, monkeypatch):
    """The probe must keep working, or the add-on hangs in 'Starting'."""
    monkeypatch.delenv("ESPHOME_MCP_AUTH_TOKEN", raising=False)
    assert client.get("/health").status_code == 200


def test_valid_token_passes(client, monkeypatch):
    monkeypatch.setenv("ESPHOME_MCP_AUTH_TOKEN", "sekret")
    r = client.get("/mcp", headers={"Authorization": "Bearer sekret"})
    assert r.status_code == 200


def test_missing_header_is_401(client, monkeypatch):
    monkeypatch.setenv("ESPHOME_MCP_AUTH_TOKEN", "sekret")
    assert client.get("/mcp").status_code == 401


def test_wrong_token_is_403(client, monkeypatch):
    monkeypatch.setenv("ESPHOME_MCP_AUTH_TOKEN", "sekret")
    r = client.get("/mcp", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 403


def test_unconfigured_token_fails_closed(client, monkeypatch):
    """An empty token must not serve the tools unauthenticated.

    The add-on maps /config read-write, so falling open would hand filesystem
    access to anyone who can reach the port.
    """
    monkeypatch.delenv("ESPHOME_MCP_AUTH_TOKEN", raising=False)
    assert client.get("/mcp").status_code == 503
    r = client.get("/mcp", headers={"Authorization": "Bearer anything"})
    assert r.status_code == 503


def test_non_ascii_configured_token_rejects_cleanly(client, monkeypatch):
    """A non-ASCII auth_token must yield 403, not a 500.

    Header values are ASCII-only, so such a token can never match — but
    hmac.compare_digest raises TypeError on non-ASCII *str* input, which would
    surface as an unhandled 500. Comparing as bytes makes it a plain mismatch.
    """
    monkeypatch.setenv("ESPHOME_MCP_AUTH_TOKEN", "clé-secrète")
    r = client.get("/mcp", headers={"Authorization": "Bearer whatever"})
    assert r.status_code == 403
