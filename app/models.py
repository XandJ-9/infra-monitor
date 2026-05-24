# -*- coding: utf-8 -*-
"""
数据模型模块
- 定义各组件状态的数据结构
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ComponentStatus:
    """组件通用状态"""
    name: str                # 组件名称
    connected: bool = False  # 是否连接
    cluster: str = ""        # 集群名称
    version: str = ""        # 版本号
    error: str = ""          # 错误信息
    metrics: dict[str, Any] = field(default_factory=dict)  # 额外指标


@dataclass
class ZKNodeInfo:
    """ZK 节点信息"""
    path: str
    value: str = ""
    version: int = 0
    czxid: int = 0
    mzxid: int = 0
    ctime: int = 0
    mtime: int = 0
    num_children: int = 0
    children: list[str] = field(default_factory=list)


@dataclass
class ZKServerInfo:
    """ZK 服务器节点信息"""
    host: str
    port: int = 2888
    role: str = ""  # leader / follower / observer
    status: str = ""


@dataclass
class KafkaBrokerInfo:
    """Kafka Broker 信息"""
    broker_id: int
    host: str
    port: int
    rack: str = ""


@dataclass
class KafkaTopicInfo:
    """Kafka Topic 信息"""
    name: str
    partitions: int = 0
    replicas: int = 0
    partition_details: list[dict[str, Any]] = field(default_factory=list)
    under_replicated_partitions: int = 0
    offline_partitions: int = 0


@dataclass
class KafkaConsumerGroupInfo:
    """Kafka Consumer Group 信息"""
    group_id: str
    state: str = ""
    members: int = 0
    topics: list[str] = field(default_factory=list)
    lag: int = 0
    offsets: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ESIndexInfo:
    """ES 索引信息"""
    name: str
    health: str = ""
    status: str = ""
    docs_count: int = 0
    store_size: str = ""
    primaries: int = 0
    replicas: int = 0


@dataclass
class ESNodeInfo:
    """ES 节点信息"""
    name: str
    host: str = ""
    role: str = ""
    heap_percent: str = ""
    ram_percent: str = ""
    load: str = ""
