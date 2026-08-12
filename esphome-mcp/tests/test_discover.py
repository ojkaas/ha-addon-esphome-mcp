"""Unit tests for dashboard auto-discovery slug selection."""

from server import discover


def test_pick_selects_esphome_dashboard():
    addons = [
        {"slug": "508867bf_esphome-mcp", "state": "startup"},  # this add-on
        {"slug": "core_mosquitto", "state": "started"},
        {"slug": "15ef4d2f_esphome", "state": "started"},  # the dashboard
    ]
    assert discover._pick_dashboard_slug(addons) == "15ef4d2f_esphome"


def test_pick_never_matches_self_mcp():
    # Our own slug ends in _esphome-mcp, which must not be picked.
    addons = [{"slug": "508867bf_esphome-mcp", "state": "startup"}]
    assert discover._pick_dashboard_slug(addons) is None


def test_pick_none_when_no_dashboard():
    addons = [{"slug": "core_mariadb"}, {"slug": "a0d7b954_nodered"}]
    assert discover._pick_dashboard_slug(addons) is None


def test_pick_handles_missing_slug_key():
    assert discover._pick_dashboard_slug([{}, {"name": "x"}]) is None
