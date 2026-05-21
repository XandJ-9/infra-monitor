# -*- coding: utf-8 -*-
"""
Elasticsearch 服务层
- 通过 HTTP API 获取 ES 集群状态
- 集群健康、节点列表、索引列表
- 使用 httpx 异步调用
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import load_config
from app.models import ComponentStatus, ESIndexInfo, ESNodeInfo

logger = logging.getLogger(__name__)


class ESService:
    """Elasticsearch 服务，通过 HTTP API 获取集群信息"""

    _instance: ESService | None = None

    def __new__(cls) -> ESService:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._base_url = ""
            cls._instance._timeout = 10
        return cls._instance

    def _get_config(self) -> tuple[str, float]:
        """获取 ES 配置"""
        cfg = load_config()
        es_cfg = cfg.get("elasticsearch", {})
        return es_cfg.get("url", "http://127.0.0.1:9200"), es_cfg.get("timeout", 10)

    async def _get(self, path: str) -> dict | None:
        """异步 GET 请求 ES API"""
        base_url, timeout = self._get_config()
        url = f"{base_url.rstrip('/')}{path}"
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return resp.json()
                else:
                    logger.warning("ES API 返回 %d: %s", resp.status_code, url)
                    return None
        except Exception as e:
            logger.warning("ES 请求失败: %s - %s", url, e)
            return None

    async def get_status(self) -> ComponentStatus:
        """获取 ES 集群状态"""
        status = ComponentStatus(name="Elasticsearch")
        data = await self._get("/")
        if data is None:
            status.connected = False
            base_url, _ = self._get_config()
            status.error = f"无法连接到 {base_url}"
            return status

        status.connected = True
        status.version = data.get("version", {}).get("number", "unknown")
        status.cluster = data.get("cluster_name", "unknown")

        # 获取集群健康
        health = await self._get("/_cluster/health")
        if health:
            status.metrics["status"] = health.get("status", "unknown")
            status.metrics["number_of_nodes"] = health.get("number_of_nodes", 0)
            status.metrics["active_shards"] = health.get("active_shards", 0)
            status.metrics["unassigned_shards"] = health.get("unassigned_shards", 0)

        return status

    async def get_cluster_health(self) -> dict[str, Any]:
        """获取集群健康详情"""
        return await self._get("/_cluster/health") or {}

    async def get_nodes(self) -> list[ESNodeInfo]:
        """获取节点列表"""
        data = await self._get("/_cat/nodes?format=json&h=name,host,role,heap.percent,ram.percent,load")
        if not data:
            return []

        nodes: list[ESNodeInfo] = []
        for item in data:
            nodes.append(ESNodeInfo(
                name=item.get("name", ""),
                host=item.get("host", ""),
                role=item.get("role", ""),
                heap_percent=str(item.get("heap.percent", "")),
                ram_percent=str(item.get("ram.percent", "")),
                load=str(item.get("load", "")),
            ))
        return nodes

    async def get_indices(self) -> list[ESIndexInfo]:
        """获取索引列表"""
        data = await self._get("/_cat/indices?format=json&h=index,health,status,docs.count,store.size,pri,rep")
        if not data:
            return []

        indices: list[ESIndexInfo] = []
        for item in data:
            indices.append(ESIndexInfo(
                name=item.get("index", ""),
                health=item.get("health", ""),
                status=item.get("status", ""),
                docs_count=item.get("docs.count", 0),
                store_size=str(item.get("store.size", "")),
                primaries=item.get("pri", 0),
                replicas=item.get("rep", 0),
            ))
        return sorted(indices, key=lambda i: i.name)

    async def get_cluster_stats(self) -> dict[str, Any]:
        """获取集群统计信息"""
        return await self._get("/_cluster/stats") or {}
