# -*- coding: utf-8 -*-
"""
Kafka 服务层
- 优先通过 Kafka AdminClient 获取现代 Kafka 元数据
- ZooKeeper 仅作为旧集群或 AdminClient 失败时的兼容路径
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from typing import Any

from app.config import load_config
from app.models import ComponentStatus, KafkaBrokerInfo, KafkaConsumerGroupInfo, KafkaTopicInfo
from app.services.zk_service import ZKService

logger = logging.getLogger(__name__)


class KafkaService:
    """Kafka 元数据服务。"""

    _instance: KafkaService | None = None
    admin_client_cls: Any = None
    consumer_cls: Any = None
    HEALTHY_GROUP_STATES = {"", "Stable", "Empty"}

    def __new__(cls) -> KafkaService:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def get_status(self) -> ComponentStatus:
        """获取 Kafka 集群状态。"""
        try:
            with self._open_admin_client() as admin:
                cluster = admin.describe_cluster()
                topics = admin.describe_topics()
                brokers = cluster.get("brokers", [])
                controller = cluster.get("controller", cluster.get("controller_id"))
                status = ComponentStatus(name="Kafka", connected=True)
                status.cluster = str(cluster.get("cluster_id") or f"{len(brokers)} brokers")
                status.metrics["metadata_source"] = "Kafka AdminClient"
                status.metrics["bootstrap_servers"] = self._active_config().get("bootstrap_servers", "")
                status.metrics["broker_count"] = len(brokers)
                status.metrics["topic_count"] = len(topics)
                if controller is not None:
                    status.metrics["controller"] = self._broker_id(controller)
                status.metrics["under_replicated_partitions"] = sum(
                    1 for topic in topics for partition in topic.get("partitions", [])
                    if self._is_under_replicated(partition)
                )
                status.metrics["offline_partitions"] = sum(
                    1 for topic in topics for partition in topic.get("partitions", [])
                    if self._is_offline(partition)
                )
                return status
        except Exception as exc:
            logger.warning("Kafka AdminClient 状态获取失败，尝试 ZK fallback: %s", exc)
            fallback = self._get_status_from_zk()
            if fallback.connected:
                fallback.metrics["metadata_source"] = "ZooKeeper fallback"
                fallback.metrics["admin_error"] = self._safe_error(exc)
                return fallback
            fallback.error = self._classify_error(exc)
            return fallback

    def get_brokers(self) -> list[KafkaBrokerInfo]:
        """获取所有 Broker 信息。"""
        try:
            with self._open_admin_client() as admin:
                cluster = admin.describe_cluster()
                return sorted(
                    [
                        KafkaBrokerInfo(
                            broker_id=self._broker_id(broker),
                            host=str(self._value(broker, "host", "")),
                            port=int(self._value(broker, "port", 0) or 0),
                            rack=str(self._value(broker, "rack", "") or ""),
                        )
                        for broker in cluster.get("brokers", [])
                    ],
                    key=lambda item: item.broker_id,
                )
        except Exception as exc:
            logger.warning("Kafka AdminClient 获取 Broker 列表失败，尝试 ZK fallback: %s", exc)
            return self._get_brokers_from_zk()

    def get_topics(self) -> list[KafkaTopicInfo]:
        """获取所有 Topic 信息，包含 partition leader、replicas、ISR。"""
        try:
            with self._open_admin_client() as admin:
                topics = []
                for data in admin.describe_topics():
                    topic = self._topic_from_admin_data(data)
                    topics.append(topic)
                return sorted(topics, key=lambda item: item.name)
        except Exception as exc:
            logger.warning("Kafka AdminClient 获取 Topic 列表失败，尝试 ZK fallback: %s", exc)
            return self._get_topics_from_zk()

    def get_consumer_groups(self) -> list[KafkaConsumerGroupInfo]:
        """获取 Consumer Group 列表及 partition 级 offset/lag。"""
        try:
            with self._open_admin_client() as admin:
                groups = []
                for group_id, _protocol_type in admin.list_consumer_groups():
                    groups.append(self._consumer_group_from_admin(admin, group_id))
                return sorted(groups, key=lambda item: item.group_id)
        except Exception as exc:
            logger.warning("Kafka AdminClient 获取 Consumer Group 列表失败，尝试 ZK fallback: %s", exc)
            return self._get_consumer_groups_from_zk()

    def get_diagnostics(self, lag_threshold: int = 1000) -> dict[str, Any]:
        """生成 Kafka 只读风险诊断摘要。"""
        topics = self.get_topics()
        groups = self.get_consumer_groups()
        lag_threshold = max(0, int(lag_threshold or 0))

        risks: list[dict[str, Any]] = []
        partition_count = sum(topic.partitions for topic in topics)
        under_replicated_count = sum(topic.under_replicated_partitions for topic in topics)
        offline_count = sum(topic.offline_partitions for topic in topics)
        single_replica_topics = [topic for topic in topics if topic.replicas == 1]

        for topic in topics:
            if topic.offline_partitions > 0:
                risks.append({
                    "severity": "critical",
                    "category": "partition",
                    "resource": topic.name,
                    "title": "存在 Offline Partition",
                    "description": (
                        f"{topic.name} 有 {topic.offline_partitions} 个分区无可用 leader，"
                        "生产或消费可能失败。"
                    ),
                    "details": {
                        "offline_partitions": topic.offline_partitions,
                        "partitions": [
                            item["partition"]
                            for item in topic.partition_details
                            if item.get("offline")
                        ],
                    },
                })
            if topic.under_replicated_partitions > 0:
                risks.append({
                    "severity": "warning",
                    "category": "replica",
                    "resource": topic.name,
                    "title": "ISR 不足",
                    "description": (
                        f"{topic.name} 有 {topic.under_replicated_partitions} 个分区副本未完全同步，"
                        "数据可靠性下降。"
                    ),
                    "details": {
                        "under_replicated_partitions": topic.under_replicated_partitions,
                        "partitions": [
                            item["partition"]
                            for item in topic.partition_details
                            if item.get("under_replicated")
                        ],
                    },
                })
            if topic.replicas == 1:
                risks.append({
                    "severity": "warning",
                    "category": "replica",
                    "resource": topic.name,
                    "title": "单副本 Topic",
                    "description": f"{topic.name} 只有 1 个副本，broker 故障时存在数据不可用风险。",
                    "details": {"replicas": topic.replicas, "partitions": topic.partitions},
                })

        lagging_groups = []
        total_lag = 0
        max_group_lag = 0
        for group in groups:
            total_lag += group.lag
            max_group_lag = max(max_group_lag, group.lag)
            if group.lag > lag_threshold:
                lagging_groups.append(group)
                risks.append({
                    "severity": "warning",
                    "category": "lag",
                    "resource": group.group_id,
                    "title": "Consumer Group Lag 过高",
                    "description": (
                        f"{group.group_id} 当前总 lag 为 {group.lag}，超过阈值 {lag_threshold}。"
                    ),
                    "details": {
                        "lag": group.lag,
                        "threshold": lag_threshold,
                        "partitions": [
                            item for item in group.offsets
                            if int(item.get("lag", 0) or 0) > 0
                        ][:20],
                    },
                })
            if group.state not in self.HEALTHY_GROUP_STATES:
                risks.append({
                    "severity": "warning",
                    "category": "consumer_group",
                    "resource": group.group_id,
                    "title": "Consumer Group 状态异常",
                    "description": f"{group.group_id} 当前状态为 {group.state}，可能正在 rebalance 或不可用。",
                    "details": {"state": group.state, "members": group.members},
                })

        leader_skew = self._leader_skew(topics)
        if leader_skew["skewed"]:
            risks.append({
                "severity": "info",
                "category": "broker",
                "resource": "leader-distribution",
                "title": "Leader 分布不均",
                "description": (
                    f"Broker {leader_skew['max_broker']} 承载 {leader_skew['max_count']} 个 leader，"
                    f"平均值约 {leader_skew['average']:.1f}。"
                ),
                "details": leader_skew,
            })

        risks.sort(key=lambda item: self._risk_sort_key(item["severity"]))
        return {
            "summary": {
                "topic_count": len(topics),
                "partition_count": partition_count,
                "consumer_group_count": len(groups),
                "offline_partitions": offline_count,
                "under_replicated_partitions": under_replicated_count,
                "single_replica_topics": len(single_replica_topics),
                "lagging_groups": len(lagging_groups),
                "total_lag": total_lag,
                "max_group_lag": max_group_lag,
                "risk_count": len(risks),
                "lag_threshold": lag_threshold,
            },
            "risks": risks,
        }

    def _active_config(self) -> dict[str, Any]:
        cfg = load_config()
        kafka_cfg = cfg.get("kafka", {})
        active = kafka_cfg.get("active")
        connections = kafka_cfg.get("connections", [])
        for conn in connections:
            if conn.get("id") == active:
                return conn
        return connections[0] if connections else kafka_cfg

    def list_connections(self) -> dict[str, Any]:
        """列出配置中的 Kafka 连接。"""
        cfg = load_config()
        kafka_cfg = cfg.get("kafka", {})
        active = kafka_cfg.get("active", "default")
        connections = []
        for conn in kafka_cfg.get("connections", []):
            connections.append({
                "id": conn.get("id", ""),
                "name": conn.get("name", ""),
                "bootstrap_servers": conn.get("bootstrap_servers", ""),
                "timeout": conn.get("timeout", 10),
                "security_protocol": conn.get("security_protocol", "PLAINTEXT"),
                "sasl_mechanism": conn.get("sasl_mechanism", "PLAIN"),
                "username": conn.get("username", ""),
                "has_password": bool(conn.get("password")),
                "active": conn.get("id") == active,
            })
        return {"active": active, "connections": connections}

    def _client_config(self) -> dict[str, Any]:
        cfg = self._active_config()
        timeout = max(1, int(cfg.get("timeout", 10)))
        client_config: dict[str, Any] = {
            "bootstrap_servers": cfg.get("bootstrap_servers", "127.0.0.1:9092"),
            "request_timeout_ms": timeout * 1000,
            "api_version_auto_timeout_ms": timeout * 1000,
            "connections_max_idle_ms": timeout * 1000,
            "client_id": "infra-monitor",
        }
        security_protocol = str(cfg.get("security_protocol") or "PLAINTEXT").upper()
        client_config["security_protocol"] = security_protocol
        if security_protocol.startswith("SASL"):
            client_config["sasl_mechanism"] = cfg.get("sasl_mechanism", "PLAIN")
            client_config["sasl_plain_username"] = cfg.get("username", "")
            client_config["sasl_plain_password"] = cfg.get("password", "")
        return client_config

    def _admin_client(self):
        if self.admin_client_cls is None:
            from kafka import KafkaAdminClient

            self.admin_client_cls = KafkaAdminClient
        return self.admin_client_cls(**self._client_config())

    @contextmanager
    def _open_admin_client(self):
        client = self._admin_client()
        try:
            yield client
        finally:
            self._close_client(client)

    def _consumer(self):
        if self.consumer_cls is None:
            from kafka import KafkaConsumer

            self.consumer_cls = KafkaConsumer
        cfg = self._client_config()
        cfg["enable_auto_commit"] = False
        cfg["group_id"] = None
        return self.consumer_cls(**cfg)

    def _consumer_group_from_admin(self, admin: Any, group_id: str) -> KafkaConsumerGroupInfo:
        group = KafkaConsumerGroupInfo(group_id=group_id)
        descriptions = admin.describe_consumer_groups([group_id])
        if descriptions:
            description = descriptions[0]
            group.state = str(getattr(description, "state", "") or "")
            members = getattr(description, "members", []) or []
            group.members = len(members)

        offsets = admin.list_consumer_group_offsets(group_id)
        if not offsets:
            return group

        end_offsets = self._end_offsets(list(offsets))
        topics = set()
        rows = []
        total_lag = 0
        for topic_partition, offset_meta in offsets.items():
            topic = getattr(topic_partition, "topic", "")
            partition = int(getattr(topic_partition, "partition", 0))
            current_offset = int(getattr(offset_meta, "offset", -1) or -1)
            end_offset = int(end_offsets.get(topic_partition, 0) or 0)
            lag = max(0, end_offset - current_offset) if current_offset >= 0 else 0
            topics.add(topic)
            total_lag += lag
            rows.append({
                "topic": topic,
                "partition": partition,
                "current_offset": current_offset,
                "end_offset": end_offset,
                "lag": lag,
            })

        group.topics = sorted(topics)
        group.lag = total_lag
        group.offsets = sorted(rows, key=lambda item: (item["topic"], item["partition"]))
        return group

    def _end_offsets(self, partitions: list[Any]) -> dict[Any, int]:
        consumer = self._consumer()
        try:
            return consumer.end_offsets(partitions)
        finally:
            self._close_client(consumer)

    def _topic_from_admin_data(self, data: dict[str, Any]) -> KafkaTopicInfo:
        details = []
        max_replicas = 0
        under_replicated = 0
        offline = 0
        for partition in data.get("partitions", []):
            replicas = [self._broker_id(item) for item in partition.get("replicas", [])]
            isr = [self._broker_id(item) for item in partition.get("isr", [])]
            leader = self._broker_id(partition.get("leader"))
            is_under_replicated = len(isr) < len(replicas)
            is_offline = leader < 0
            max_replicas = max(max_replicas, len(replicas))
            under_replicated += 1 if is_under_replicated else 0
            offline += 1 if is_offline else 0
            details.append({
                "partition": int(partition.get("partition", 0)),
                "leader": leader,
                "replicas": replicas,
                "isr": isr,
                "under_replicated": is_under_replicated,
                "offline": is_offline,
            })

        return KafkaTopicInfo(
            name=str(data.get("topic", "")),
            partitions=len(details),
            replicas=max_replicas,
            partition_details=sorted(details, key=lambda item: item["partition"]),
            under_replicated_partitions=under_replicated,
            offline_partitions=offline,
        )

    def _broker_id(self, broker: Any) -> int:
        if broker is None:
            return -1
        if isinstance(broker, dict):
            value = broker.get("nodeId", broker.get("node_id", broker.get("id")))
            if value is not None:
                return int(value)
            return -1
        for attr in ("nodeId", "node_id", "id"):
            value = getattr(broker, attr, None)
            if value is not None:
                return int(value)
        try:
            return int(broker)
        except (TypeError, ValueError):
            return -1

    def _value(self, item: Any, key: str, default: Any = None) -> Any:
        if isinstance(item, dict):
            return item.get(key, default)
        return getattr(item, key, default)

    def _is_under_replicated(self, partition: dict[str, Any]) -> bool:
        replicas = partition.get("replicas", []) or []
        isr = partition.get("isr", []) or []
        return len(isr) < len(replicas)

    def _is_offline(self, partition: dict[str, Any]) -> bool:
        return self._broker_id(partition.get("leader")) < 0

    def _leader_skew(self, topics: list[KafkaTopicInfo]) -> dict[str, Any]:
        counts: dict[int, int] = {}
        for topic in topics:
            for partition in topic.partition_details:
                leader = int(partition.get("leader", -1))
                if leader >= 0:
                    counts[leader] = counts.get(leader, 0) + 1
        if len(counts) < 2:
            return {"skewed": False, "leaders": counts}

        total = sum(counts.values())
        average = total / len(counts)
        max_broker, max_count = max(counts.items(), key=lambda item: item[1])
        min_broker, min_count = min(counts.items(), key=lambda item: item[1])
        skewed = total >= len(counts) * 4 and average > 0 and max_count / average >= 2
        return {
            "skewed": skewed,
            "leaders": counts,
            "average": average,
            "max_broker": max_broker,
            "max_count": max_count,
            "min_broker": min_broker,
            "min_count": min_count,
        }

    def _risk_sort_key(self, severity: str) -> int:
        return {"critical": 0, "warning": 1, "info": 2}.get(severity, 3)

    def _classify_error(self, exc: Exception) -> str:
        name = exc.__class__.__name__
        raw = self._safe_error(exc)
        lowered = raw.lower()
        if "auth" in lowered or "sasl" in lowered:
            return f"Kafka 认证失败: {raw}"
        if "timeout" in lowered or "timed out" in lowered:
            return f"Kafka 连接超时: {raw}"
        if "no brokers" in lowered or "broker" in lowered:
            return f"Kafka bootstrap servers 不可达: {raw}"
        return f"{name}: {raw}"

    def _safe_error(self, exc: Exception) -> str:
        return str(exc)[:300] or exc.__class__.__name__

    def _close_client(self, client: Any) -> None:
        close = getattr(client, "close", None)
        if close:
            try:
                close()
            except Exception:
                pass

    def _get_status_from_zk(self) -> ComponentStatus:
        """旧集群兼容：通过 ZK 上的 /brokers 路径判断 Kafka 状态。"""
        status = ComponentStatus(name="Kafka")
        zk = ZKService()
        zk.ensure_connection()

        if not zk.connected:
            status.connected = False
            status.error = "ZK 未连接，无法获取 Kafka 元数据"
            return status

        try:
            if not zk.exists("/brokers/ids"):
                status.connected = False
                status.error = "/brokers/ids 不存在，可能未部署 Kafka 或未注册到 ZK"
                return status

            broker_ids = zk.get_children("/brokers/ids")
            status.connected = True
            status.metrics["broker_count"] = len(broker_ids)
            if zk.exists("/controller"):
                ctrl_node = zk.get_node("/controller")
                if ctrl_node and ctrl_node.value:
                    try:
                        ctrl_data = json.loads(ctrl_node.value)
                        status.metrics["controller"] = ctrl_data.get("brokerid", "unknown")
                    except json.JSONDecodeError:
                        status.metrics["controller"] = ctrl_node.value[:100]
            if zk.exists("/brokers/topics"):
                topics = zk.get_children("/brokers/topics")
                status.metrics["topic_count"] = len(topics)
            status.cluster = f"{len(broker_ids)} brokers"
            if broker_ids:
                first_broker = zk.get_node(f"/brokers/ids/{broker_ids[0]}")
                if first_broker and first_broker.value:
                    try:
                        broker_data = json.loads(first_broker.value)
                        status.version = broker_data.get("version", "unknown")
                    except json.JSONDecodeError:
                        pass
        except Exception as exc:
            status.error = self._safe_error(exc)

        return status

    def _get_brokers_from_zk(self) -> list[KafkaBrokerInfo]:
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
                        brokers.append(KafkaBrokerInfo(
                            broker_id=int(bid),
                            host=data.get("host", "unknown"),
                            port=int(data.get("port", 9092)),
                        ))
                    except (json.JSONDecodeError, ValueError):
                        brokers.append(KafkaBrokerInfo(broker_id=int(bid), host="parse-error", port=0))
        except Exception as exc:
            logger.warning("获取 ZK Broker 列表失败: %s", exc)

        return brokers

    def _get_topics_from_zk(self) -> list[KafkaTopicInfo]:
        zk = ZKService()
        if not zk.connected:
            return []

        topics: list[KafkaTopicInfo] = []
        try:
            topic_names = zk.get_children("/brokers/topics")
            for name in topic_names:
                topic_info = KafkaTopicInfo(name=name)
                node = zk.get_node(f"/brokers/topics/{name}")
                if node and node.value:
                    try:
                        data = json.loads(node.value)
                        partitions = data.get("partitions", {})
                        topic_info.partitions = len(partitions)
                        max_replicas = 0
                        partition_details = []
                        for pid, replicas in partitions.items():
                            replica_list = replicas if isinstance(replicas, list) else []
                            max_replicas = max(max_replicas, len(replica_list))
                            partition_details.append({
                                "partition": int(pid),
                                "leader": -1,
                                "replicas": replica_list,
                                "isr": [],
                                "under_replicated": False,
                                "offline": False,
                            })
                        topic_info.replicas = max_replicas
                        topic_info.partition_details = sorted(
                            partition_details,
                            key=lambda item: item["partition"],
                        )
                    except (json.JSONDecodeError, ValueError):
                        pass
                topics.append(topic_info)
        except Exception as exc:
            logger.warning("获取 ZK Topic 列表失败: %s", exc)

        return sorted(topics, key=lambda item: item.name)

    def _get_consumer_groups_from_zk(self) -> list[KafkaConsumerGroupInfo]:
        zk = ZKService()
        if not zk.connected:
            return []

        groups: list[KafkaConsumerGroupInfo] = []
        try:
            if zk.exists("/consumers"):
                group_ids = zk.get_children("/consumers")
                for gid in group_ids:
                    group = KafkaConsumerGroupInfo(group_id=gid)
                    owners_path = f"/consumers/{gid}/owners"
                    if zk.exists(owners_path):
                        topics = zk.get_children(owners_path)
                        group.topics = topics
                        group.members = sum(
                            len(zk.get_children(f"{owners_path}/{topic}"))
                            for topic in topics
                            if zk.exists(f"{owners_path}/{topic}")
                        )
                    groups.append(group)
            if zk.exists("/brokers/topics/__consumer_offsets"):
                groups.append(KafkaConsumerGroupInfo(
                    group_id="(新版 Consumer Groups 需 Kafka AdminClient 获取)",
                    state="info",
                ))
        except Exception as exc:
            logger.warning("获取 ZK Consumer Group 列表失败: %s", exc)

        return sorted(groups, key=lambda item: item.group_id)
