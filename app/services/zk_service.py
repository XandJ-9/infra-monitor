# -*- coding: utf-8 -*-
"""
ZooKeeper 服务层
- 管理与 ZK 集群的连接
- 提供节点查询、树浏览等操作
- 参考 zk_client.py 的连接和操作逻辑
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from kazoo.client import KazooClient
from kazoo.exceptions import NoNodeError

from app.config import load_config
from app.models import ComponentStatus, ZKNodeInfo, ZKServerInfo

logger = logging.getLogger(__name__)


class ZKService:
    """ZooKeeper 服务，单例管理"""

    _instance: ZKService | None = None
    _lock = threading.Lock()

    def __new__(cls) -> ZKService:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._clients = {}
                cls._instance._client_hosts = {}
                cls._instance._client_timeouts = {}
                cls._instance._last_fail_times = {}
            return cls._instance

    @property
    def zk(self) -> KazooClient | None:
        """获取当前 ZK 客户端"""
        return self._get_client()

    @property
    def connected(self) -> bool:
        """是否已连接"""
        client = self._get_client()
        return client is not None and client.connected

    def _active_connection(self) -> dict[str, Any]:
        cfg = load_config()
        zk_cfg = cfg.get("zookeeper", {})
        active = zk_cfg.get("active")
        connections = zk_cfg.get("connections", [])
        for conn in connections:
            if conn.get("id") == active:
                return conn
        return connections[0] if connections else {
            "id": "default",
            "name": "默认集群",
            "hosts": zk_cfg.get("hosts", "127.0.0.1:2181"),
            "timeout": zk_cfg.get("timeout", 5),
        }

    def _get_client(self, connection_id: str | None = None) -> KazooClient | None:
        """获取指定连接的客户端；未指定时使用当前 active 连接。"""
        if connection_id is None:
            connection_id = self._active_connection().get("id", "default")
        return self._clients.get(connection_id)

    def list_connections(self) -> dict[str, Any]:
        """列出配置中的 ZK 连接及当前运行态。"""
        cfg = load_config()
        zk_cfg = cfg.get("zookeeper", {})
        active = zk_cfg.get("active", "default")
        result = []
        for conn in zk_cfg.get("connections", []):
            conn_id = conn.get("id", "")
            client = self._clients.get(conn_id)
            result.append({
                "id": conn_id,
                "name": conn.get("name", conn_id),
                "hosts": conn.get("hosts", ""),
                "timeout": conn.get("timeout", 10),
                "active": conn_id == active,
                "connected": bool(client and client.connected),
                "last_fail_time": self._last_fail_times.get(conn_id),
            })
        return {"active": active, "connections": result}

    def _connect(self, connection_id: str, hosts: str, timeout: float = 10) -> None:
        """建立 ZK 连接（如果地址变了重新连）"""
        client = self._clients.get(connection_id)
        if client and client.connected and self._client_hosts.get(connection_id) == hosts:
            return
        # 先关旧连接
        self._disconnect(connection_id)
        self._client_hosts[connection_id] = hosts
        self._client_timeouts[connection_id] = timeout
        try:
            from kazoo.retry import KazooRetry
            retry_policy = KazooRetry(max_tries=1, max_delay=1, sleep_func=time.sleep)
            client = KazooClient(hosts=hosts, timeout=timeout,
                                 connection_retry=retry_policy)
            client.start(timeout=timeout)
            self._clients[connection_id] = client
            self._last_fail_times.pop(connection_id, None)
            logger.info("ZK 已连接: %s (%s)", hosts, connection_id)
        except Exception as e:
            logger.warning("ZK 连接失败: %s (%s) - %s", hosts, connection_id, e)
            self._clients.pop(connection_id, None)

    def _disconnect(self, connection_id: str | None = None) -> None:
        """断开 ZK 连接"""
        connection_ids = [connection_id] if connection_id else list(self._clients)
        for conn_id in connection_ids:
            client = self._clients.get(conn_id)
            if not client:
                continue
            try:
                client.stop()
                client.close()
            except Exception:
                pass
            self._clients.pop(conn_id, None)

    def ensure_connection(self) -> None:
        """确保连接，使用当前配置。连接失败后短时间内不重试（避免页面超时）"""
        # 如果已连接或正在冷却期内，直接返回
        conn = self._active_connection()
        connection_id = conn.get("id", "default")
        client = self._clients.get(connection_id)
        hosts = conn.get("hosts", "127.0.0.1:2181")
        timeout = conn.get("timeout", 5)
        if client and client.connected and self._client_hosts.get(connection_id) == hosts:
            return
        now = time.time()
        last_fail_time = self._last_fail_times.get(connection_id)
        if last_fail_time and (now - last_fail_time) < 10:
            return  # 10 秒冷却期，避免反复重试导致页面卡死
        try:
            self._connect(connection_id, hosts, timeout)
            client = self._clients.get(connection_id)
            if not (client and client.connected):
                self._last_fail_times[connection_id] = now
        except Exception:
            self._last_fail_times[connection_id] = now

    def get_status(self) -> ComponentStatus:
        """获取 ZK 整体状态"""
        self.ensure_connection()
        status = ComponentStatus(name="ZooKeeper")
        conn = self._active_connection()
        client = self._get_client(conn.get("id", "default"))
        if not self.connected:
            status.connected = False
            status.cluster = conn.get("name", "")
            status.error = f"无法连接到 {conn.get('hosts', '')}"
            return status

        status.connected = True
        status.cluster = conn.get("name", "connected")
        status.metrics["连接地址"] = conn.get("hosts", "")
        try:
            # 尝试获取集群信息
            # 从 /zookeeper/config 获取集群配置（ZK 3.5+）
            try:
                client.get("/zookeeper/config")
                # 解析版本信息从环境变量
                data_ver, _ = client.get("/zookeeper/version")
                if data_ver:
                    status.version = data_ver.decode("utf-8", errors="replace")
            except NoNodeError:
                status.version = "3.4.x"

            # 获取关键 znode 存在信息
            key_nodes = ["/controller", "/brokers", "/brokers/ids", "/brokers/topics"]
            for node in key_nodes:
                exists = client.exists(node) is not None
                status.metrics[node] = "存在" if exists else "不存在"

        except Exception as e:
            status.error = str(e)

        return status

    def get_children(self, path: str) -> list[str]:
        """获取子节点列表"""
        self.ensure_connection()
        client = self.zk
        if not client or not client.connected:
            return []
        try:
            return client.get_children(path)
        except NoNodeError:
            return []

    def get_node(self, path: str) -> ZKNodeInfo | None:
        """获取节点数据和元信息"""
        self.ensure_connection()
        client = self.zk
        if not client or not client.connected:
            return None
        try:
            data, stat = client.get(path)
            children = client.get_children(path)
            return ZKNodeInfo(
                path=path,
                value=data.decode("utf-8", errors="replace") if data else "",
                version=stat.version,
                czxid=stat.czxid,
                mzxid=stat.mzxid,
                ctime=stat.ctime,
                mtime=stat.mtime,
                num_children=stat.numChildren,
                children=sorted(children),
            )
        except NoNodeError:
            return None

    def exists(self, path: str) -> bool:
        """检查节点是否存在"""
        self.ensure_connection()
        client = self.zk
        if not client or not client.connected:
            return False
        return client.exists(path) is not None

    def get_server_info(self) -> list[ZKServerInfo]:
        """获取 ZK 集群各节点信息（通过 /zookeeper/config 解析）"""
        self.ensure_connection()
        servers: list[ZKServerInfo] = []
        client = self.zk
        if not client or not client.connected:
            return servers
        try:
            data, _ = client.get("/zookeeper/config")
            if data:
                config_text = data.decode("utf-8", errors="replace")
                for line in config_text.strip().split("\n"):
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    # 格式: server.1=host:port1:port2;clientPort
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        addr = parts[1]
                        host_port = addr.split(":")
                        host = host_port[0] if host_port else "unknown"
                        servers.append(ZKServerInfo(
                            host=host,
                            port=int(host_port[1]) if len(host_port) > 1 else 2888,
                            role="",  # 角色需要通过 stat 命令获取，这里先留空
                        ))
        except (NoNodeError, Exception) as e:
            logger.debug("获取 ZK server info 失败: %s", e)
        return servers

    def get_tree(self, path: str = "/", depth: int = 3) -> dict[str, Any]:
        """递归获取节点树（限制深度防止过深）"""
        self.ensure_connection()
        client = self.zk
        if not client or not client.connected:
            return {"name": path, "children": []}
        if depth <= 0:
            return {"name": path, "children": []}
        try:
            children = client.get_children(path)
            node_path = path if path.endswith("/") else path + "/"
            result = {"name": path, "children": []}
            for child in sorted(children):
                child_path = node_path + child if path == "/" else path + "/" + child
                result["children"].append(self.get_tree(child_path, depth - 1))
            return result
        except NoNodeError:
            return {"name": path, "children": []}

    def disconnect(self, connection_id: str | None = None) -> None:
        """主动断开连接"""
        self._disconnect(connection_id)
        if connection_id:
            self._last_fail_times.pop(connection_id, None)
        else:
            self._last_fail_times.clear()
