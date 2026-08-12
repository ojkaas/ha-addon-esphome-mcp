"""Unit tests for the build-backend router's pure decision logic."""

from server import backend


def test_choose_dashboard_mode_ignores_probe():
    assert backend.choose("dashboard", True) == backend.DASHBOARD
    assert backend.choose("dashboard", False) == backend.DASHBOARD


def test_choose_bundled_mode_ignores_probe():
    assert backend.choose("bundled", True) == backend.LOCAL
    assert backend.choose("bundled", False) == backend.LOCAL


def test_choose_auto_follows_probe():
    assert backend.choose("auto", True) == backend.DASHBOARD
    assert backend.choose("auto", False) == backend.LOCAL


def test_mode_defaults_to_auto(monkeypatch):
    monkeypatch.delenv("BUILD_BACKEND", raising=False)
    assert backend._mode() == "auto"


def test_mode_normalises_case_and_unknown(monkeypatch):
    monkeypatch.setenv("BUILD_BACKEND", "BUNDLED")
    assert backend._mode() == "bundled"
    monkeypatch.setenv("BUILD_BACKEND", "  dashboard ")
    assert backend._mode() == "dashboard"
    monkeypatch.setenv("BUILD_BACKEND", "nonsense")
    assert backend._mode() == "auto"


def test_describe_reflects_mode(monkeypatch):
    monkeypatch.setenv("BUILD_BACKEND", "bundled")
    assert "bundled" in backend.describe()
    monkeypatch.setenv("BUILD_BACKEND", "dashboard")
    assert "dashboard" in backend.describe()
    monkeypatch.setenv("BUILD_BACKEND", "auto")
    desc = backend.describe()
    assert "dashboard" in desc and "bundled" in desc
