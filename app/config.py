# -*- coding: utf-8 -*-
"""
配置存储模块
- 从 SQLite 读取连接和运行配置
- 支持各组件页面运行时修改并持久化
"""

from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from pathlib import Path
from typing import Any

# 配置数据库路径（项目根目录）
CONFIG_DB_PATH = Path(__file__).resolve().parent.parent / "config.sqlite3"
CONFIG_KEY = "default"
CONFIG_TABLE = "app_config"

# 默认配置
DEFAULT_CONFIG: dict[str, Any] = {
    "zookeeper": {
        "hosts": "127.0.0.1:2181",
        "timeout": 10,
        "active": "default",
        "connections": [
            {
                "id": "default",
                "name": "默认集群",
                "hosts": "127.0.0.1:2181",
                "timeout": 10,
            }
        ],
    },
    "kafka": {
        "bootstrap_servers": "127.0.0.1:9092",
        "timeout": 10,
        "security_protocol": "PLAINTEXT",
        "sasl_mechanism": "PLAIN",
        "username": "",
        "password": "",
        "active": "default",
        "connections": [
            {
                "id": "default",
                "name": "默认集群",
                "bootstrap_servers": "127.0.0.1:9092",
                "timeout": 10,
                "security_protocol": "PLAINTEXT",
                "sasl_mechanism": "PLAIN",
                "username": "",
                "password": "",
            }
        ],
    },
    "elasticsearch": {
        "url": "http://127.0.0.1:9200",
        "timeout": 10,
        "username": "",
        "password": "",
        "active": "default",
        "connections": [
            {
                "id": "default",
                "name": "默认集群",
                "url": "http://127.0.0.1:9200",
                "timeout": 10,
                "username": "",
                "password": "",
            }
        ],
    },
    "file_browser": {
        "root": ".",
        "max_preview_bytes": 262144,
        "enabled": True,
    },
    "refresh_interval": 30,
}


def load_config() -> dict[str, Any]:
    """加载配置；SQLite 不存在或内容不可用时写入并返回默认配置。"""
    cfg = _load_config_from_sqlite()
    if cfg is None:
        cfg = deepcopy(DEFAULT_CONFIG)
        cfg = normalize_config(_deep_merge(deepcopy(DEFAULT_CONFIG), cfg))
        save_config(cfg)
        return cfg

    return normalize_config(_deep_merge(deepcopy(DEFAULT_CONFIG), cfg))


def save_config(cfg: dict[str, Any]) -> None:
    """保存配置到 SQLite。"""
    cfg = normalize_config(cfg)
    _save_config_to_sqlite(cfg)


def get_config_db_path() -> Path:
    """返回 SQLite 配置库路径，便于测试隔离存储。"""
    return CONFIG_DB_PATH


def _load_config_from_sqlite() -> dict[str, Any] | None:
    db_path = get_config_db_path()
    if not db_path.exists():
        return None
    try:
        with sqlite3.connect(db_path) as conn:
            _ensure_config_table(conn)
            row = conn.execute(
                f"SELECT value FROM {CONFIG_TABLE} WHERE key = ?",
                (CONFIG_KEY,),
            ).fetchone()
    except (OSError, sqlite3.DatabaseError):
        return None

    if row is None:
        return None
    try:
        loaded = json.loads(row[0])
    except (TypeError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _save_config_to_sqlite(cfg: dict[str, Any]) -> None:
    db_path = get_config_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(cfg, ensure_ascii=False)
    with sqlite3.connect(db_path) as conn:
        _ensure_config_table(conn)
        conn.execute(
            f"""
            INSERT INTO {CONFIG_TABLE} (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP
            """,
            (CONFIG_KEY, payload),
        )


def _ensure_config_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {CONFIG_TABLE} (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并字典，override 覆盖 base"""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            base[key] = _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def normalize_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """规范化配置，并同步当前连接到组件服务使用的便捷字段。"""
    _normalize_zookeeper_config(cfg)
    _normalize_kafka_config(cfg)
    _normalize_elasticsearch_config(cfg)
    return cfg


def _normalize_zookeeper_config(cfg: dict[str, Any]) -> None:
    zk_cfg = cfg.setdefault("zookeeper", {})
    default_hosts = str(zk_cfg.get("hosts") or "127.0.0.1:2181").strip()
    default_timeout = _safe_int(zk_cfg.get("timeout"), 10)

    connections = zk_cfg.get("connections")
    if not isinstance(connections, list) or not connections:
        connections = [{
            "id": "default",
            "name": "默认集群",
            "hosts": default_hosts,
            "timeout": default_timeout,
        }]

    normalized_connections: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(connections):
        if not isinstance(item, dict):
            continue
        hosts = str(item.get("hosts") or "").strip()
        if not hosts:
            continue
        conn_id = _slugify_connection_id(str(item.get("id") or item.get("name") or f"zk-{index + 1}"))
        if conn_id in seen_ids:
            conn_id = f"{conn_id}-{index + 1}"
        seen_ids.add(conn_id)
        normalized_connections.append({
            "id": conn_id,
            "name": str(item.get("name") or conn_id).strip() or conn_id,
            "hosts": hosts,
            "timeout": _safe_int(item.get("timeout"), default_timeout),
        })

    if not normalized_connections:
        normalized_connections.append({
            "id": "default",
            "name": "默认集群",
            "hosts": default_hosts,
            "timeout": default_timeout,
        })

    active = str(zk_cfg.get("active") or normalized_connections[0]["id"]).strip()
    if active not in {item["id"] for item in normalized_connections}:
        active = normalized_connections[0]["id"]

    active_conn = next(item for item in normalized_connections if item["id"] == active)
    zk_cfg["active"] = active
    zk_cfg["connections"] = normalized_connections
    # 同步当前连接，供服务层直接读取。
    zk_cfg["hosts"] = active_conn["hosts"]
    zk_cfg["timeout"] = active_conn["timeout"]


def _normalize_elasticsearch_config(cfg: dict[str, Any]) -> None:
    es_cfg = cfg.setdefault("elasticsearch", {})
    default_url = str(es_cfg.get("url") or "http://127.0.0.1:9200").strip()
    default_timeout = _safe_int(es_cfg.get("timeout"), 10)
    default_username = str(es_cfg.get("username") or "").strip()
    default_password = str(es_cfg.get("password") or "")

    connections = es_cfg.get("connections")
    if not isinstance(connections, list) or not connections:
        connections = [{
            "id": "default",
            "name": "默认集群",
            "url": default_url,
            "timeout": default_timeout,
            "username": default_username,
            "password": default_password,
        }]

    normalized_connections: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(connections):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        conn_id = _slugify_connection_id(str(item.get("id") or item.get("name") or f"es-{index + 1}"))
        if conn_id in seen_ids:
            conn_id = f"{conn_id}-{index + 1}"
        seen_ids.add(conn_id)
        normalized_connections.append({
            "id": conn_id,
            "name": str(item.get("name") or conn_id).strip() or conn_id,
            "url": url,
            "timeout": _safe_int(item.get("timeout"), default_timeout),
            "username": str(item.get("username") or "").strip(),
            "password": str(item.get("password") or ""),
        })

    if not normalized_connections:
        normalized_connections.append({
            "id": "default",
            "name": "默认集群",
            "url": default_url,
            "timeout": default_timeout,
            "username": default_username,
            "password": default_password,
        })

    active = str(es_cfg.get("active") or normalized_connections[0]["id"]).strip()
    if active not in {item["id"] for item in normalized_connections}:
        active = normalized_connections[0]["id"]

    active_conn = next(item for item in normalized_connections if item["id"] == active)
    es_cfg["active"] = active
    es_cfg["connections"] = normalized_connections
    # 同步当前连接，供服务层直接读取。
    es_cfg["url"] = active_conn["url"]
    es_cfg["timeout"] = active_conn["timeout"]
    es_cfg["username"] = active_conn.get("username", "")
    es_cfg["password"] = active_conn.get("password", "")


def _normalize_kafka_config(cfg: dict[str, Any]) -> None:
    kafka_cfg = cfg.setdefault("kafka", {})
    default_bootstrap_servers = str(
        kafka_cfg.get("bootstrap_servers") or DEFAULT_CONFIG["kafka"]["bootstrap_servers"]
    ).strip()
    default_timeout = _safe_int(kafka_cfg.get("timeout"), DEFAULT_CONFIG["kafka"]["timeout"])
    default_security_protocol = _normalize_kafka_security_protocol(kafka_cfg.get("security_protocol"))
    default_sasl_mechanism = _normalize_kafka_sasl_mechanism(kafka_cfg.get("sasl_mechanism"))
    default_username = str(kafka_cfg.get("username") or "").strip()
    default_password = str(kafka_cfg.get("password") or "")

    connections = kafka_cfg.get("connections")
    if not isinstance(connections, list) or not connections:
        connections = [{
            "id": "default",
            "name": "默认集群",
            "bootstrap_servers": default_bootstrap_servers,
            "timeout": default_timeout,
            "security_protocol": default_security_protocol,
            "sasl_mechanism": default_sasl_mechanism,
            "username": default_username,
            "password": default_password,
        }]

    normalized_connections: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(connections):
        if not isinstance(item, dict):
            continue
        bootstrap_servers = str(item.get("bootstrap_servers") or "").strip()
        if not bootstrap_servers:
            continue
        conn_id = _slugify_connection_id(str(
            item.get("id") or item.get("name") or f"kafka-{index + 1}"
        ))
        if conn_id in seen_ids:
            conn_id = f"{conn_id}-{index + 1}"
        seen_ids.add(conn_id)
        normalized_connections.append({
            "id": conn_id,
            "name": str(item.get("name") or conn_id).strip() or conn_id,
            "bootstrap_servers": bootstrap_servers,
            "timeout": _safe_int(item.get("timeout"), default_timeout),
            "security_protocol": _normalize_kafka_security_protocol(item.get("security_protocol")),
            "sasl_mechanism": _normalize_kafka_sasl_mechanism(item.get("sasl_mechanism")),
            "username": str(item.get("username") or "").strip(),
            "password": str(item.get("password") or ""),
        })

    if not normalized_connections:
        normalized_connections.append({
            "id": "default",
            "name": "默认集群",
            "bootstrap_servers": default_bootstrap_servers,
            "timeout": default_timeout,
            "security_protocol": default_security_protocol,
            "sasl_mechanism": default_sasl_mechanism,
            "username": default_username,
            "password": default_password,
        })

    active = str(kafka_cfg.get("active") or normalized_connections[0]["id"]).strip()
    if active not in {item["id"] for item in normalized_connections}:
        active = normalized_connections[0]["id"]

    active_conn = next(item for item in normalized_connections if item["id"] == active)
    kafka_cfg["active"] = active
    kafka_cfg["connections"] = normalized_connections
    # 同步当前连接，供服务层直接读取。
    kafka_cfg["bootstrap_servers"] = active_conn["bootstrap_servers"]
    kafka_cfg["timeout"] = active_conn["timeout"]
    kafka_cfg["security_protocol"] = active_conn["security_protocol"]
    kafka_cfg["sasl_mechanism"] = active_conn["sasl_mechanism"]
    kafka_cfg["username"] = active_conn.get("username", "")
    kafka_cfg["password"] = active_conn.get("password", "")


def _normalize_kafka_security_protocol(value: Any) -> str:
    security_protocol = str(value or "PLAINTEXT").strip().upper()
    allowed_protocols = {"PLAINTEXT", "SSL", "SASL_PLAINTEXT", "SASL_SSL"}
    return security_protocol if security_protocol in allowed_protocols else "PLAINTEXT"


def _normalize_kafka_sasl_mechanism(value: Any) -> str:
    sasl_mechanism = str(value or "PLAIN").strip().upper()
    allowed_mechanisms = {"PLAIN", "SCRAM-SHA-256", "SCRAM-SHA-512"}
    return sasl_mechanism if sasl_mechanism in allowed_mechanisms else "PLAIN"


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _slugify_connection_id(value: str) -> str:
    chars = []
    for char in value.lower().strip():
        if char.isalnum():
            chars.append(char)
        elif char in {"-", "_", ".", ":"}:
            chars.append("-")
    result = "".join(chars).strip("-")
    return result or "default"
