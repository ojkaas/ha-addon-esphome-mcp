"""Unit tests for the local (bundled) esphome backend's pure parts."""

import asyncio
import os

from server import local


def test_list_devices_scans_yaml_only(tmp_path, monkeypatch):
    (tmp_path / "living.yaml").write_text("esphome:\n")
    (tmp_path / "kitchen.yaml").write_text("esphome:\n")
    (tmp_path / "secrets.yaml").write_text("wifi_password: x\n")  # forbidden
    (tmp_path / "notes.txt").write_text("nope\n")  # not yaml
    (tmp_path / "sub").mkdir()  # directory, not a file
    monkeypatch.setattr(local, "ESPHOME_DIR", str(tmp_path))

    result = asyncio.run(local.list_devices())

    names = sorted(d["name"] for d in result["configured"])
    assert names == ["kitchen", "living"]
    confs = {d["configuration"] for d in result["configured"]}
    assert confs == {"kitchen.yaml", "living.yaml"}
    assert result["importable"] == []


def test_list_devices_missing_dir_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(local, "ESPHOME_DIR", str(tmp_path / "does-not-exist"))
    result = asyncio.run(local.list_devices())
    assert result == {"configured": [], "importable": []}


def test_config_path_strips_directory(monkeypatch):
    monkeypatch.setattr(local, "ESPHOME_DIR", "/config/esphome")
    # A traversal attempt collapses to the basename inside ESPHOME_DIR.
    assert os.path.basename(local._config_path("../../etc/passwd")) == "passwd"
    assert os.path.basename(local._config_path("living.yaml")) == "living.yaml"
