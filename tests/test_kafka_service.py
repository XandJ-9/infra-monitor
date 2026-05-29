# -*- coding: utf-8 -*-

from __future__ import annotations

from collections import namedtuple

import app.services.kafka_service as kafka_service
import app.config as config
from app.main import app
from app.services.kafka_service import KafkaService
from fastapi.testclient import TestClient


Broker = namedtuple("Broker", ["nodeId", "host", "port", "rack"])
TopicPartition = namedtuple("TopicPartition", ["topic", "partition"])
OffsetAndMetadata = namedtuple("OffsetAndMetadata", ["offset"])
GroupDescription = namedtuple("GroupDescription", ["state", "members"])


class FakeAdminClient:
    created_configs: list[dict] = []

    def __init__(self, **config):
        self.created_configs.append(config)
        self.closed = False

    def close(self):
        self.closed = True

    def describe_cluster(self):
        return {
            "cluster_id": "cluster-a",
            "controller": Broker(1, "broker-1", 9092, ""),
            "brokers": [
                Broker(1, "broker-1", 9092, ""),
                Broker(2, "broker-2", 9092, "rack-a"),
            ],
        }

    def describe_topics(self):
        return [{
            "topic": "orders",
            "partitions": [
                {"partition": 0, "leader": 1, "replicas": [1, 2], "isr": [1, 2]},
                {"partition": 1, "leader": 2, "replicas": [1, 2], "isr": [2]},
                {"partition": 2, "leader": -1, "replicas": [1, 2], "isr": []},
            ],
        }]

    def list_consumer_groups(self):
        return [("order-service", "consumer")]

    def describe_consumer_groups(self, group_ids):
        assert group_ids == ["order-service"]
        return [GroupDescription(state="Stable", members=["a", "b"])]

    def list_consumer_group_offsets(self, group_id):
        assert group_id == "order-service"
        return {
            TopicPartition("orders", 0): OffsetAndMetadata(7),
            TopicPartition("orders", 1): OffsetAndMetadata(10),
        }


class FakeConsumer:
    def __init__(self, **_config):
        self.closed = False

    def end_offsets(self, partitions):
        return {
            partitions[0]: 12,
            partitions[1]: 10,
        }

    def close(self):
        self.closed = True


def _service(monkeypatch) -> KafkaService:
    FakeAdminClient.created_configs = []
    monkeypatch.setattr(kafka_service, "load_config", lambda: {
        "kafka": {
            "bootstrap_servers": "broker-1:9092,broker-2:9092",
            "timeout": 3,
            "security_protocol": "SASL_PLAINTEXT",
            "sasl_mechanism": "PLAIN",
            "username": "monitor",
            "password": "secret",
        }
    })
    service = KafkaService()
    monkeypatch.setattr(service, "admin_client_cls", FakeAdminClient)
    monkeypatch.setattr(service, "consumer_cls", FakeConsumer)
    return service


def test_get_status_uses_admin_client_and_reports_partition_health(monkeypatch) -> None:
    service = _service(monkeypatch)

    status = service.get_status()

    assert status.connected is True
    assert status.cluster == "cluster-a"
    assert status.metrics["metadata_source"] == "Kafka AdminClient"
    assert status.metrics["broker_count"] == 2
    assert status.metrics["topic_count"] == 1
    assert status.metrics["under_replicated_partitions"] == 2
    assert status.metrics["offline_partitions"] == 1
    assert FakeAdminClient.created_configs[0]["request_timeout_ms"] == 3000
    assert FakeAdminClient.created_configs[0]["sasl_plain_username"] == "monitor"


def test_get_topics_includes_leader_replicas_isr_and_risk_flags(monkeypatch) -> None:
    service = _service(monkeypatch)

    topics = service.get_topics()

    assert len(topics) == 1
    topic = topics[0]
    assert topic.name == "orders"
    assert topic.partitions == 3
    assert topic.replicas == 2
    assert topic.under_replicated_partitions == 2
    assert topic.offline_partitions == 1
    assert topic.partition_details[1] == {
        "partition": 1,
        "leader": 2,
        "replicas": [1, 2],
        "isr": [2],
        "under_replicated": True,
        "offline": False,
    }


def test_get_consumer_groups_calculates_partition_lag(monkeypatch) -> None:
    service = _service(monkeypatch)

    groups = service.get_consumer_groups()

    assert len(groups) == 1
    group = groups[0]
    assert group.group_id == "order-service"
    assert group.state == "Stable"
    assert group.members == 2
    assert group.topics == ["orders"]
    assert group.lag == 5
    assert group.offsets == [
        {"topic": "orders", "partition": 0, "current_offset": 7, "end_offset": 12, "lag": 5},
        {"topic": "orders", "partition": 1, "current_offset": 10, "end_offset": 10, "lag": 0},
    ]


def test_get_diagnostics_summarizes_kafka_risks(monkeypatch) -> None:
    service = _service(monkeypatch)

    diagnostics = service.get_diagnostics(lag_threshold=3)

    summary = diagnostics["summary"]
    assert summary["topic_count"] == 1
    assert summary["partition_count"] == 3
    assert summary["offline_partitions"] == 1
    assert summary["under_replicated_partitions"] == 2
    assert summary["lagging_groups"] == 1
    assert summary["total_lag"] == 5
    assert summary["risk_count"] == 3
    assert [risk["title"] for risk in diagnostics["risks"]] == [
        "存在 Offline Partition",
        "ISR 不足",
        "Consumer Group Lag 过高",
    ]


def test_kafka_diagnostics_api_uses_lag_threshold(monkeypatch) -> None:
    calls = []

    def fake_diagnostics(self, lag_threshold=1000):
        calls.append(lag_threshold)
        return {
            "summary": {
                "topic_count": 0,
                "partition_count": 0,
                "consumer_group_count": 0,
                "offline_partitions": 0,
                "under_replicated_partitions": 0,
                "single_replica_topics": 0,
                "lagging_groups": 0,
                "total_lag": 0,
                "max_group_lag": 0,
                "risk_count": 0,
                "lag_threshold": lag_threshold,
            },
            "risks": [],
        }

    monkeypatch.setattr(KafkaService, "get_diagnostics", fake_diagnostics)
    client = TestClient(app)

    response = client.get("/kafka/api/diagnostics?lag_threshold=12")

    assert response.status_code == 200
    assert calls == [12]
    assert response.json()["summary"]["lag_threshold"] == 12


def test_kafka_connection_crud(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "CONFIG_DB_PATH", tmp_path / "config.sqlite3")
    config.save_config({
        "zookeeper": {"hosts": "zk-default:2181", "timeout": 5},
        "kafka": {"bootstrap_servers": "kafka-default:9092", "timeout": 5},
        "elasticsearch": {"url": "http://127.0.0.1:9200", "timeout": 5},
        "refresh_interval": 30,
    })
    client = TestClient(app)

    initial = client.get("/kafka/api/connections")
    assert initial.status_code == 200
    assert initial.json()["connections"][0]["bootstrap_servers"] == "kafka-default:9092"

    created = client.post(
        "/kafka/api/connections",
        json={
            "name": "prod",
            "bootstrap_servers": "kafka-prod-1:9092,kafka-prod-2:9092",
            "timeout": 7,
            "security_protocol": "SASL_SSL",
            "sasl_mechanism": "SCRAM-SHA-512",
            "username": "monitor",
            "password": "secret",
        },
    )
    assert created.status_code == 200
    conn_id = created.json()["id"]
    assert created.json()["has_password"] is True
    assert "password" not in created.json()

    switched = client.post("/kafka/api/connections/active", json={"id": conn_id})
    assert switched.status_code == 200
    assert switched.json()["active"] == conn_id

    listed = client.get("/kafka/api/connections").json()
    assert listed["active"] == conn_id
    assert len(listed["connections"]) == 2
    assert listed["connections"][1]["username"] == "monitor"
    assert listed["connections"][1]["has_password"] is True

    deleted = client.delete(f"/kafka/api/connections/{conn_id}")
    assert deleted.status_code == 200
    assert deleted.json()["active"] == "default"
