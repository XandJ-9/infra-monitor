# -*- coding: utf-8 -*-
"""
配置管理模块
- 从 config.json 读取配置
- 支持运行时修改并持久化
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# 配置文件路径（项目根目录）
CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config.json"

# 默认配置
DEFAULT_CONFIG: dict[str, Any] = {
    "zookeeper": {
        "hosts": "127.0.0.1:2181",
        "timeout": 10,
    },
    "elasticsearch": {
        "url": "http://127.0.0.1:9200",
        "timeout": 10,
    },
    "refresh_interval": 30,
}


def load_config() -> dict[str, Any]:
    """加载配置文件，如果不存在则使用默认配置"""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            # 合并默认值，防止缺少字段
            return _deep_merge(DEFAULT_CONFIG.copy(), cfg)
        except (json.JSONDecodeError, OSError):
            return DEFAULT_CONFIG.copy()
    return DEFAULT_CONFIG.copy()


def save_config(cfg: dict[str, Any]) -> None:
    """保存配置到文件"""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并字典，override 覆盖 base"""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            base[key] = _deep_merge(base[key], value)
        else:
            base[key] = value
    return base
