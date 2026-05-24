# -*- coding: utf-8 -*-
"""
配置管理模块
- 从 config.json 读取配置
- 支持运行时修改并持久化
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

# 配置文件路径（项目根目录）
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"

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
    "elasticsearch": {
        "url": "http://127.0.0.1:9200",
        "timeout": 10,
    },
    "file_browser": {
        "root": ".",
        "max_preview_bytes": 262144,
        "enabled": True,
    },
    "refresh_interval": 30,
}


def load_config() -> dict[str, Any]:
    """加载配置文件，如果不存在则使用默认配置"""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            _migrate_legacy_zookeeper_config(cfg)
            # 合并默认值，防止缺少字段
            return normalize_config(_deep_merge(deepcopy(DEFAULT_CONFIG), cfg))
        except (json.JSONDecodeError, OSError):
            return deepcopy(DEFAULT_CONFIG)
    return normalize_config(deepcopy(DEFAULT_CONFIG))


def save_config(cfg: dict[str, Any]) -> None:
    """保存配置到文件"""
    cfg = normalize_config(cfg)
    with open(CONFIG_PATH, "w", encoding="utf-8", newline="\n") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并字典，override 覆盖 base"""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            base[key] = _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def normalize_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """规范化配置，兼容旧版单 ZooKeeper 连接格式。"""
    zk_cfg = cfg.setdefault("zookeeper", {})
    legacy_hosts = str(zk_cfg.get("hosts") or "127.0.0.1:2181").strip()
    legacy_timeout = _safe_int(zk_cfg.get("timeout"), 10)

    connections = zk_cfg.get("connections")
    if not isinstance(connections, list) or not connections:
        connections = [{
            "id": "default",
            "name": "默认集群",
            "hosts": legacy_hosts,
            "timeout": legacy_timeout,
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
            "timeout": _safe_int(item.get("timeout"), legacy_timeout),
        })

    if not normalized_connections:
        normalized_connections.append({
            "id": "default",
            "name": "默认集群",
            "hosts": legacy_hosts,
            "timeout": legacy_timeout,
        })

    active = str(zk_cfg.get("active") or normalized_connections[0]["id"]).strip()
    if active not in {item["id"] for item in normalized_connections}:
        active = normalized_connections[0]["id"]

    active_conn = next(item for item in normalized_connections if item["id"] == active)
    zk_cfg["active"] = active
    zk_cfg["connections"] = normalized_connections
    # 保留旧字段，兼容其他模块或手工配置。
    zk_cfg["hosts"] = active_conn["hosts"]
    zk_cfg["timeout"] = active_conn["timeout"]
    return cfg


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


def _migrate_legacy_zookeeper_config(cfg: dict[str, Any]) -> None:
    """把旧版 hosts/timeout 配置迁移成连接列表，再进入默认值合并。"""
    zk_cfg = cfg.get("zookeeper")
    if not isinstance(zk_cfg, dict) or zk_cfg.get("connections"):
        return
    hosts = str(zk_cfg.get("hosts") or "").strip()
    if not hosts:
        return
    timeout = _safe_int(zk_cfg.get("timeout"), 10)
    zk_cfg["active"] = "default"
    zk_cfg["connections"] = [{
        "id": "default",
        "name": "默认集群",
        "hosts": hosts,
        "timeout": timeout,
    }]
