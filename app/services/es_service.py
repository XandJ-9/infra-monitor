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
        return cls._instance

    def _active_connection(self) -> dict[str, Any]:
        """获取当前 ES 连接配置"""
        cfg = load_config()
        es_cfg = cfg.get("elasticsearch", {})
        active = es_cfg.get("active")
        connections = es_cfg.get("connections", [])
        for conn in connections:
            if conn.get("id") == active:
                return conn
        return connections[0] if connections else {
            "id": "default",
            "name": "默认集群",
            "url": es_cfg.get("url", "http://127.0.0.1:9200"),
            "timeout": es_cfg.get("timeout", 10),
            "username": es_cfg.get("username", ""),
            "password": es_cfg.get("password", ""),
        }

    def _connection(self, connection_id: str | None = None) -> dict[str, Any]:
        """获取指定连接配置；未指定时使用当前 active 连接。"""
        if connection_id is None:
            return self._active_connection()
        cfg = load_config()
        for conn in cfg.get("elasticsearch", {}).get("connections", []):
            if conn.get("id") == connection_id:
                return conn
        return self._active_connection()

    def list_connections(self) -> dict[str, Any]:
        """列出配置中的 ES 连接。"""
        cfg = load_config()
        es_cfg = cfg.get("elasticsearch", {})
        active = es_cfg.get("active", "default")
        connections = []
        for conn in es_cfg.get("connections", []):
            connections.append({
                "id": conn.get("id", ""),
                "name": conn.get("name", ""),
                "url": conn.get("url", ""),
                "timeout": conn.get("timeout", 10),
                "username": conn.get("username", ""),
                "has_password": bool(conn.get("password")),
                "active": conn.get("id") == active,
            })
        return {"active": active, "connections": connections}

    def _client_options(self, conn: dict[str, Any]) -> dict[str, Any]:
        options: dict[str, Any] = {"timeout": conn.get("timeout", 10)}
        username = str(conn.get("username") or "").strip()
        password = str(conn.get("password") or "")
        if username:
            options["auth"] = (username, password)
        return options

    async def _get(self, path: str, connection_id: str | None = None) -> Any | None:
        """异步 GET 请求 ES API"""
        conn = self._connection(connection_id)
        url = f"{conn.get('url', '').rstrip('/')}{path}"
        try:
            async with httpx.AsyncClient(**self._client_options(conn)) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return resp.json()
                else:
                    logger.warning("ES API 返回 %d: %s", resp.status_code, url)
                    return None
        except Exception as e:
            logger.warning("ES 请求失败: %s - %s", url, e)
            return None

    async def _post(
        self,
        path: str,
        payload: dict[str, Any],
        connection_id: str | None = None,
    ) -> Any | None:
        """异步 POST 请求 ES API"""
        conn = self._connection(connection_id)
        url = f"{conn.get('url', '').rstrip('/')}{path}"
        try:
            async with httpx.AsyncClient(**self._client_options(conn)) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    return resp.json()
                logger.warning("ES API 返回 %d: %s", resp.status_code, url)
                return None
        except Exception as e:
            logger.warning("ES 请求失败: %s - %s", url, e)
            return None

    async def get_status(self, connection_id: str | None = None) -> ComponentStatus:
        """获取 ES 集群状态"""
        status = ComponentStatus(name="Elasticsearch")
        conn = self._connection(connection_id)
        data = await self._get("/", connection_id=connection_id)
        if data is None:
            status.connected = False
            status.cluster = conn.get("name", "")
            status.error = f"无法连接到 {conn.get('url', '')}"
            return status

        status.connected = True
        status.version = data.get("version", {}).get("number", "unknown")
        status.cluster = data.get("cluster_name", "unknown")
        status.metrics["连接名称"] = conn.get("name", "")
        status.metrics["连接地址"] = conn.get("url", "")

        # 获取集群健康
        health = await self._get("/_cluster/health", connection_id=connection_id)
        if health:
            status.metrics["status"] = health.get("status", "unknown")
            status.metrics["number_of_nodes"] = health.get("number_of_nodes", 0)
            status.metrics["active_shards"] = health.get("active_shards", 0)
            status.metrics["unassigned_shards"] = health.get("unassigned_shards", 0)

        return status

    async def get_cluster_health(self, connection_id: str | None = None) -> dict[str, Any]:
        """获取集群健康详情"""
        return await self._get("/_cluster/health", connection_id=connection_id) or {}

    async def get_nodes(self, connection_id: str | None = None) -> list[ESNodeInfo]:
        """获取节点列表"""
        data = await self._get(
            "/_cat/nodes?format=json&h=name,host,role,heap.percent,ram.percent,load",
            connection_id=connection_id,
        )
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

    async def get_indices(self, connection_id: str | None = None) -> list[ESIndexInfo]:
        """获取索引列表"""
        data = await self._get(
            "/_cat/indices?format=json&h=index,health,status,docs.count,store.size,pri,rep",
            connection_id=connection_id,
        )
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

    async def get_cluster_stats(self, connection_id: str | None = None) -> dict[str, Any]:
        """获取集群统计信息"""
        return await self._get("/_cluster/stats", connection_id=connection_id) or {}

    async def search_documents(
        self,
        index: str,
        query: str = "",
        size: int = 10,
        connection_id: str | None = None,
    ) -> dict[str, Any]:
        """查询索引文档"""
        index = index.strip()
        if not index:
            return {"error": "索引名称不能为空", "hits": [], "total": 0}

        size = max(1, min(size, 100))
        query = query.strip()
        search_query: dict[str, Any]
        if query:
            search_query = {
                "query_string": {
                    "query": query,
                    "default_operator": "AND",
                }
            }
        else:
            search_query = {"match_all": {}}

        payload = {
            "query": search_query,
            "size": size,
            "sort": [{"@timestamp": {"order": "desc", "unmapped_type": "date"}}],
        }
        if connection_id is None:
            data = await self._post(f"/{index}/_search", payload)
        else:
            data = await self._post(f"/{index}/_search", payload, connection_id=connection_id)
        if data is None:
            return {"error": f"无法查询索引 {index}", "hits": [], "total": 0}

        total_data = data.get("hits", {}).get("total", 0)
        total = total_data.get("value", total_data) if isinstance(total_data, dict) else total_data
        hits = []
        for item in data.get("hits", {}).get("hits", []):
            hits.append({
                "index": item.get("_index", ""),
                "id": item.get("_id", ""),
                "score": item.get("_score"),
                "source": item.get("_source", {}),
            })
        return {"hits": hits, "total": total, "error": ""}
