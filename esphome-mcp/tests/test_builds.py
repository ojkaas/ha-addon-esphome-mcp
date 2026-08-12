"""Unit tests for the background build registry in tools.py."""

import time

import pytest

from server import tools


@pytest.fixture(autouse=True)
def clean_registry():
    """Each test starts from an empty build registry."""
    tools._BUILDS.clear()
    yield
    tools._BUILDS.clear()


def _running_job(kind: str) -> dict:
    """Register a job that looks like it is still running, without a thread."""
    job = {
        "status": "running",
        "kind": kind,
        "lines": tools.collections.deque(maxlen=tools.MAX_BUILD_LINES),
        "dropped": 0,
        "returncode": None,
        "started": time.time(),
        "finished": None,
    }
    tools._BUILDS["dev.yaml"] = job
    return job


def test_same_kind_joins_the_running_job():
    running = _running_job("compile")
    job, conflict = tools._start_build("dev.yaml", "compile", "dev.yaml", 10)
    assert conflict is None
    assert job is running


@pytest.mark.parametrize(
    ("running_kind", "requested"),
    [
        ("compile", "flash"),
        ("compile", "install"),
        ("flash", "compile"),
        ("install", "flash"),
    ],
)
def test_different_kind_is_refused_not_silently_reused(running_kind, requested):
    """A flash must never be answered with a running compile's job.

    The registry is keyed by configuration, so all three operations collide on
    one key; returning the other job would report progress for work the caller
    never asked for, and the requested operation would never run.
    """
    _running_job(running_kind)
    job, conflict = tools._start_build("dev.yaml", requested, "dev.yaml", 10)
    assert conflict is not None
    assert running_kind in conflict
    assert requested in conflict
    assert job["kind"] == running_kind


def test_finished_job_is_replaced_by_a_new_kind():
    job = _running_job("compile")
    job["status"] = "done"
    job["returncode"] = 0
    new_job, conflict = tools._start_build("dev.yaml", "flash", "dev.yaml", 0)
    assert conflict is None
    assert new_job["kind"] == "flash"


def test_line_buffer_is_capped_and_reports_drops(monkeypatch):
    monkeypatch.setattr(tools, "MAX_BUILD_LINES", 3)
    job = {
        "lines": tools.collections.deque(maxlen=3),
        "dropped": 0,
    }
    for i in range(5):
        tools._append_line(job, f"line{i}")

    assert list(job["lines"]) == ["line2", "line3", "line4"]
    assert job["dropped"] == 2

    rendered = tools._render_lines(job)
    assert "2 earlier line(s) dropped" in rendered
    assert rendered.endswith("line2\nline3\nline4")


def test_render_is_verbatim_when_nothing_dropped():
    job = {"lines": tools.collections.deque(["a", "b"], maxlen=10), "dropped": 0}
    assert tools._render_lines(job) == "a\nb"
