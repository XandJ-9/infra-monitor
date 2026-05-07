# -*- coding: utf-8 -*-
"""
Kafka 服务层
- 通过 ZK 获取 Kafka 集群元数据（不依赖 kafka-python）
- Broker 列表、Topic 列表、Consumer Group 信息
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.models import ComponentStatus, KafkaBrokerInfo, KafkaTopicInfo, KafkaConsumerGroupInfo
from app.services.zk_service import ZKService

logger = logging.getLogger(__name__)


class KafkaService:
    """Kafka 元数据服务，通过 ZK 获取"""

    _instance: KafkaService | None = None

    def __new__(cls) -> KafkaService:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def get_status(self) -> ComponentStatus:
        """获取 Kafka 集群状态（通过 ZK 上的 /brokers 路径判断）"""
        status = ComponentStatus(name="Kafka")
        zk = ZKService()
        zk.ensure_connection()

        if not zk.connected:
            status.connected = False
            status.error = "ZK 未连接，无法获取 Kafka 元数据"
            return status

        try:
            # 检查 /brokers/ids 是否存在
            if not zk.exists("/brokers/ids"):
                status.connected = False
                status.error = "/brokers/ids 不存在，可能未部署 Kafka 或未注册到 ZK"
                return status

            # 获取 broker 列表
            broker_ids = zk.get_children("/brokers/ids")
            status.connected = True
            status.metrics["broker_count"] = len(broker_ids)

            # 获取 controller 信息
            if zk.exists("/controller"):
                ctrl_node = zk.get_node("/controller")
                if ctrl_node and ctrl_node.value:
                    try:
                        ctrl_data = json.loads(ctrl_node.value)
                        status.metrics["controller"] = ctrl_data.get("brokerid", "unknown")
                    except json.JSONDecodeError:
                        status.metrics["controller"] = ctrl_node.value[:100]

            # 获取 topic 数量
            if zk.exists("/brokers/topics"):
                topics = zk.get_children("/brokers/topics")
                status.metrics["topic_count"] = len(topics)

            status.cluster = f"{len(broker_ids)} brokers"
            # 尝试获取版本信息
            if broker_ids:
                first_broker = zk.get_node(f"/brokers/ids/{broker_ids[0]}")
                if first_broker and first_broker.value:
                    try:
                        broker_data = json.loads(first_broker.value)
                        status.version = broker_data.get("version", "unknown")
                    except json.JSONDecodeError:
                        pass

        except Exception as e:
            status.error = str(e)

        return status

    def get_brokers(self) -> list[KafkaBrokerInfo]:
        """获取所有 Broker 信息"""
        zk = ZKService()
        if not zk.connected:
            return []

        brokers: list[KafkaBrokerInfo] = []
        try:
            broker_ids = zk.get_children("/brokers/ids")
            for bid in broker_ids:
                node = zk.get_node(f"/brokers/ids/{bid}")
                if node and node.value:
                    try:
                        data = json.loads(node.value)
                        host = data.get("host", "unknown")
                        port = data.get("port", 9092)
                        brokers.append(KafkaBrokerInfo(
                            broker_id=int(bid),
                            host=host,
                            port=port,
                        ))
                    except (json.JSONDecodeError, ValueError):
                        brokers.append(KafkaBrokerInfo(broker_id=int(bid), host="parse-error", port=0))
        except Exception as e:
            logger.warning("获取 Broker 列表失败: %s", e)

        return brokers

    def get_topics(self) -> list[KafkaTopicInfo]:
        """获取所有 Topic 信息"""
        zk = ZKService()
        if not zk.connected:
            return []

        topics: list[KafkaTopicInfo] = []
        try:
            topic_names = zk.get_children("/brokers/topics")
            for name in topic_names:
                topic_info = KafkaTopicInfo(name=name)
                # 获取 topic 元数据
                node = zk.get_node(f"/brokers/topics/{name}")
                if node and node.value:
                    try:
                        data = json.loads(node.value)
                        partitions = data.get("partitions", {})
                        topic_info.partitions = len(partitions)
                        # 计算最大副本数
                        max_replicas = 0
                        partition_details = []
                        for pid, replicas in partitions.items():
                            replica_list = replicas if isinstance(replicas, list) else []
                            max_replicas = max(max_replicas, len(replica_list))
                            partition_details.append({
                                "partition": int(pid),
                                "replicas": replica_list,
                            })
                        topic_info.replicas = max_replicas
                        topic_info.partition_details = partition_details
                    except (json.JSONDecodeError, ValueError):
                        pass
                topics.append(topic_info)
        except Exception as e:
            logger.warning("获取 Topic 列表失败: %s", e)

        return sorted(topics, key=lambda t: t.name)

    def get_consumer_groups(self) -> list[KafkaConsumerGroupInfo]:
        """获取 Consumer Group 列表及 Lag 信息"""
        zk = ZKService()
        if not zk.connected:
            return []

        groups: list[KafkaConsumerGroupInfo] = []
        try:
            # 旧版 consumer: /consumers
            # 新版 consumer: /brokers 下的 __consumer_offsets
            # 先尝试旧版路径
            if zk.exists("/consumers"):
                group_ids = zk.get_children("/consumers")
                for gid in group_ids:
                    group = KafkaConsumerGroupInfo(group_id=gid)
                    # 获取 group 的 owners（成员数）
                    owners_path = f"/consumers/{gid}/owners"
                    if zk.exists(owners_path):
                        topics = zk.get_children(owners_path)
                        group.topics = topics
                        group.members = sum(
                            len(zk.get_children(f"{owners_path}/{t}"))
                            for t in topics
                            if zk.exists(f"{owners_path}/{t}")
                        )
                    # 获取 offset 和 lag
                    offsets_path = f"/consumers/{gid}/offsets"
                    total_lag = 0
                    if zk.exists(offsets_path):
                        offset_topics = zk.get_children(offsets_path)
                        for t in offset_topics:
                            partitions = zk.get_children(f"{offsets_path}/{t}")
                            for p in partitions:
                                try:
                                    offset_node = zk.get_node(f"{offsets_path}/{t}/{p}")
                                    if offset_node:
                                        offset = int(offset_node.value)
                                        # 获取对应 topic partition 的大小
                                        # 这里简化处理，lag 计算需要对比
                                        total_lag += offset
                                except (ValueError, Exception):
                                    pass
                    group.lag = total_lag
                    groups.append(group)

            # 检查是否有 __consumer_offsets topic（新版 consumer）
            if zk.exists("/brokers/topics/__consumer_offsets"):
                # 新版 consumer 的 offset 存储在内部 topic 中
                # 通过 ZK 无法直接获取新版 consumer group 详情
                # 标记一下
                if not any(g.group_id == "__consumer_offsets" for g in groups):
                    groups.append(KafkaConsumerGroupInfo(
                        group_id="(新版本 Consumer Groups 需通过 Kafka API 获取)",
                        state="info",
                    ))

        except Exception as e:
            logger.warning("获取 Consumer Group 列表失败: %s", e)

        return sorted(groups, key=lambda g: g.group_id)
