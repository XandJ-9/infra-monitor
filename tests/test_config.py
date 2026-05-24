# -*- coding: utf-8 -*-

import json
from pathlib import Path

import app.config as config
from app.config import CONFIG_PATH


def test_config_path_points_to_project_root() -> None:
    assert CONFIG_PATH == Path(__file__).resolve().parent.parent / "config.json"


def test_load_config_merges_missing_nested_keys(tmp_path, monkeypatch) -> None:
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        json.dumps({"zookeeper": {"hosts": "zk.example:2181"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CONFIG_PATH", cfg_path)

    loaded = config.load_config()

    assert loaded["zookeeper"]["hosts"] == "zk.example:2181"
    assert loaded["zookeeper"]["timeout"] == config.DEFAULT_CONFIG["zookeeper"]["timeout"]
    assert loaded["zookeeper"]["active"] == "default"
    assert loaded["zookeeper"]["connections"][0]["hosts"] == "zk.example:2181"
    assert loaded["elasticsearch"] == config.DEFAULT_CONFIG["elasticsearch"]
    assert loaded["file_browser"] == config.DEFAULT_CONFIG["file_browser"]
    assert loaded["refresh_interval"] == config.DEFAULT_CONFIG["refresh_interval"]


def test_load_config_merges_file_browser_nested_defaults(tmp_path, monkeypatch) -> None:
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        json.dumps({"file_browser": {"root": "logs"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CONFIG_PATH", cfg_path)

    loaded = config.load_config()

    assert loaded["file_browser"]["root"] == "logs"
    assert loaded["file_browser"]["enabled"] is True
    assert loaded["file_browser"]["max_preview_bytes"] == 262144


def test_load_config_invalid_json_falls_back_to_defaults(tmp_path, monkeypatch) -> None:
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text("{invalid json", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", cfg_path)

    loaded = config.load_config()

    assert loaded == config.DEFAULT_CONFIG
    assert loaded is not config.DEFAULT_CONFIG
    assert loaded["zookeeper"] is not config.DEFAULT_CONFIG["zookeeper"]


def test_save_config_writes_pretty_utf8_json(tmp_path, monkeypatch) -> None:
    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", cfg_path)
    payload = {
        "zookeeper": {"hosts": "本机:2181", "timeout": 7},
        "elasticsearch": {"url": "http://127.0.0.1:9200", "timeout": 8},
        "file_browser": {"root": ".", "max_preview_bytes": 262144, "enabled": True},
        "refresh_interval": 12,
    }

    config.save_config(payload)

    raw = cfg_path.read_bytes()
    assert "本机".encode("utf-8") in raw
    assert raw.decode("utf-8") == json.dumps(payload, indent=2, ensure_ascii=False)
    assert json.loads(raw.decode("utf-8")) == payload
