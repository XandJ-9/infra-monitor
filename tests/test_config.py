# -*- coding: utf-8 -*-

import json
import sqlite3
from pathlib import Path

import app.config as config
from app.config import CONFIG_DB_PATH


def _write_raw_config(db_path: Path, value: str) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            INSERT INTO app_config (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP
            """,
            (config.CONFIG_KEY, value),
        )


def test_config_db_path_points_to_project_root() -> None:
    assert CONFIG_DB_PATH == Path(__file__).resolve().parent.parent / "config.sqlite3"
    assert config.get_config_db_path() == CONFIG_DB_PATH


def test_load_config_creates_default_sqlite_when_missing(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "config.sqlite3"
    monkeypatch.setattr(config, "CONFIG_DB_PATH", db_path)

    loaded = config.load_config()

    assert loaded == config.DEFAULT_CONFIG
    assert loaded is not config.DEFAULT_CONFIG
    assert loaded["zookeeper"] is not config.DEFAULT_CONFIG["zookeeper"]
    assert db_path.exists()


def test_load_config_merges_missing_nested_keys_from_sqlite(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "config.sqlite3"
    _write_raw_config(
        db_path,
        json.dumps({"zookeeper": {"connections": [{"id": "custom", "name": "自定义", "hosts": "zk.example:2181"}]}}),
    )
    monkeypatch.setattr(config, "CONFIG_DB_PATH", db_path)

    loaded = config.load_config()

    assert loaded["zookeeper"]["hosts"] == "zk.example:2181"
    assert loaded["zookeeper"]["timeout"] == config.DEFAULT_CONFIG["zookeeper"]["timeout"]
    assert loaded["zookeeper"]["active"] == "custom"
    assert loaded["zookeeper"]["connections"][0]["hosts"] == "zk.example:2181"
    assert loaded["kafka"] == config.DEFAULT_CONFIG["kafka"]
    assert loaded["elasticsearch"] == config.DEFAULT_CONFIG["elasticsearch"]
    assert loaded["file_browser"] == config.DEFAULT_CONFIG["file_browser"]
    assert loaded["refresh_interval"] == config.DEFAULT_CONFIG["refresh_interval"]


def test_load_config_merges_file_browser_nested_defaults(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "config.sqlite3"
    _write_raw_config(db_path, json.dumps({"file_browser": {"root": "logs"}}))
    monkeypatch.setattr(config, "CONFIG_DB_PATH", db_path)

    loaded = config.load_config()

    assert loaded["file_browser"]["root"] == "logs"
    assert loaded["file_browser"]["enabled"] is True
    assert loaded["file_browser"]["max_preview_bytes"] == 262144


def test_load_config_invalid_sqlite_payload_falls_back_to_defaults(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "config.sqlite3"
    _write_raw_config(db_path, "{invalid json")
    monkeypatch.setattr(config, "CONFIG_DB_PATH", db_path)

    loaded = config.load_config()

    assert loaded == config.DEFAULT_CONFIG
    assert loaded is not config.DEFAULT_CONFIG
    assert loaded["zookeeper"] is not config.DEFAULT_CONFIG["zookeeper"]


def test_load_config_normalizes_kafka_config(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "config.sqlite3"
    _write_raw_config(
        db_path,
        json.dumps({
            "kafka": {
                "active": "prod",
                "connections": [{
                    "id": "prod",
                    "name": "生产",
                    "bootstrap_servers": "broker.example:9092",
                    "timeout": "6",
                    "security_protocol": "sasl_ssl",
                    "sasl_mechanism": "scram-sha-512",
                    "username": " monitor ",
                    "password": "secret",
                }],
            }
        }),
    )
    monkeypatch.setattr(config, "CONFIG_DB_PATH", db_path)

    loaded = config.load_config()

    expected_connection = {
        "id": "prod",
        "name": "生产",
        "bootstrap_servers": "broker.example:9092",
        "timeout": 6,
        "security_protocol": "SASL_SSL",
        "sasl_mechanism": "SCRAM-SHA-512",
        "username": "monitor",
        "password": "secret",
    }
    assert loaded["kafka"]["active"] == "prod"
    assert loaded["kafka"]["connections"] == [expected_connection]
    for key, value in expected_connection.items():
        if key not in {"id", "name"}:
            assert loaded["kafka"][key] == value


def test_save_config_writes_utf8_json_payload_to_sqlite(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "config.sqlite3"
    monkeypatch.setattr(config, "CONFIG_DB_PATH", db_path)
    payload = {
        "zookeeper": {"hosts": "本机:2181", "timeout": 7},
        "elasticsearch": {"url": "http://127.0.0.1:9200", "timeout": 8, "username": "elastic", "password": "secret"},
        "file_browser": {"root": ".", "max_preview_bytes": 262144, "enabled": True},
        "refresh_interval": 12,
    }

    config.save_config(payload)

    expected = config.normalize_config(payload)
    assert db_path.exists()
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT value FROM app_config WHERE key = ?",
            (config.CONFIG_KEY,),
        ).fetchone()
    assert row is not None
    assert "本机" in row[0]
    assert json.loads(row[0]) == expected


def test_load_config_normalizes_elasticsearch_config(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "config.sqlite3"
    _write_raw_config(
        db_path,
        json.dumps({
            "elasticsearch": {
                "active": "prod",
                "connections": [{
                    "id": "prod",
                    "name": "生产",
                    "url": "https://es.example.com:9200",
                    "timeout": 8,
                    "username": "elastic",
                    "password": "secret",
                }],
            }
        }),
    )
    monkeypatch.setattr(config, "CONFIG_DB_PATH", db_path)

    loaded = config.load_config()

    assert loaded["elasticsearch"]["active"] == "prod"
    assert loaded["elasticsearch"]["connections"] == [{
        "id": "prod",
        "name": "生产",
        "url": "https://es.example.com:9200",
        "timeout": 8,
        "username": "elastic",
        "password": "secret",
    }]
