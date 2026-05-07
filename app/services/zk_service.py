# -*- coding: utf-8 -*-
"""
ZooKeeper 服务层
- 管理与 ZK 集群的连接
- 提供节点查询、树浏览等操作
- 参考 zk_client.py 的连接和操作逻辑
"""

from __future__ import annotations

import json
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
                cls._instance._zk = None
                cls._instance._hosts = ""
                cls._instance._timeout = 10
                cls._instance._last_fail_time = None
            return cls._instance

    @property
    def zk(self) -> KazooClient | None:
        """获取当前 ZK 客户端"""
        return self._zk

    @property
    def connected(self) -> bool:
        """是否已连接"""
        return self._zk is not None and self._zk.connected

    def _connect(self, hosts: str, timeout: float = 10) -> None:
        """建立 ZK 连接（如果地址变了重新连）"""
        if self._zk and self._zk.connected and self._hosts == hosts:
            return
        # 先关旧连接
        self._disconnect()
        self._hosts = hosts
        self._timeout = timeout
        try:
            from kazoo.retry import KazooRetry
            retry_policy = KazooRetry(max_tries=1, max_delay=1, sleep_func=time.sleep)
            self._zk = KazooClient(hosts=hosts, timeout=timeout,
                                    connection_retry=retry_policy)
            self._zk.start(timeout=timeout)
            logger.info("ZK 已连接: %s", hosts)
        except Exception as e:
            logger.warning("ZK 连接失败: %s - %s", hosts, e)
            self._zk = None

    def _disconnect(self) -> None:
        """断开 ZK 连接"""
        if self._zk:
            try:
                self._zk.stop()
                self._zk.close()
            except Exception:
                pass
            self._zk = None

    def ensure_connection(self) -> None:
        """确保连接，使用当前配置。连接失败后短时间内不重试（避免页面超时）"""
        # 如果已连接或正在冷却期内，直接返回
        if self.connected:
            return
        now = time.time()
        if self._last_fail_time and (now - self._last_fail_time) < 10:
            return  # 10 秒冷却期，避免反复重试导致页面卡死
        cfg = load_config()
        zk_cfg = cfg.get("zookeeper", {})
        hosts = zk_cfg.get("hosts", "127.0.0.1:2181")
        timeout = zk_cfg.get("timeout", 5)  # 默认 5 秒超时
        try:
            self._connect(hosts, timeout)
            if not self.connected:
                self._last_fail_time = now
        except Exception:
            self._last_fail_time = now

    def get_status(self) -> ComponentStatus:
        """获取 ZK 整体状态"""
        self.ensure_connection()
        status = ComponentStatus(name="ZooKeeper")
        if not self.connected:
            status.connected = False
            status.error = f"无法连接到 {self._hosts}"
            return status

        status.connected = True
        try:
            # 尝试获取集群信息
            # 从 /zookeeper/config 获取集群配置（ZK 3.5+）
            try:
                data, _ = self._zk.get("/zookeeper/config")
                config_text = data.decode("utf-8", errors="replace") if data else ""
                status.cluster = "connected"
                # 解析版本信息从环境变量
                data_ver, _ = self._zk.get("/zookeeper/version")
                if data_ver:
                    status.version = data_ver.decode("utf-8", errors="replace")
            except NoNodeError:
                status.cluster = "connected"
                status.version = "3.4.x"

            # 获取关键 znode 存在信息
            key_nodes = ["/controller", "/brokers", "/brokers/ids", "/brokers/topics"]
            for node in key_nodes:
                exists = self._zk.exists(node) is not None
                status.metrics[node] = "存在" if exists else "不存在"

        except Exception as e:
            status.error = str(e)

        return status

    def get_children(self, path: str) -> list[str]:
        """获取子节点列表"""
        self.ensure_connection()
        if not self.connected:
            return []
        try:
            return self._zk.get_children(path)
        except NoNodeError:
            return []

    def get_node(self, path: str) -> ZKNodeInfo | None:
        """获取节点数据和元信息"""
        self.ensure_connection()
        if not self.connected:
            return None
        try:
            data, stat = self._zk.get(path)
            children = self._zk.get_children(path)
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
        if not self.connected:
            return False
        return self._zk.exists(path) is not None

    def get_server_info(self) -> list[ZKServerInfo]:
        """获取 ZK 集群各节点信息（通过 /zookeeper/config 解析）"""
        self.ensure_connection()
        servers: list[ZKServerInfo] = []
        if not self.connected:
            return servers
        try:
            data, _ = self._zk.get("/zookeeper/config")
            if data:
                config_text = data.decode("utf-8", errors="replace")
                for line in config_text.strip().split("\n"):
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    # 格式: server.1=host:port1:port2;clientPort
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        server_id = parts[0].replace("server.", "")
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
        if not self.connected:
            return {"name": path, "children": []}
        if depth <= 0:
            return {"name": path, "children": []}
        try:
            children = self._zk.get_children(path)
            node_path = path if path.endswith("/") else path + "/"
            result = {"name": path, "children": []}
            for child in sorted(children):
                child_path = node_path + child if path == "/" else path + "/" + child
                result["children"].append(self.get_tree(child_path, depth - 1))
            return result
        except NoNodeError:
            return {"name": path, "children": []}

    def disconnect(self) -> None:
        """主动断开连接"""
        self._disconnect()
        self._hosts = ""
