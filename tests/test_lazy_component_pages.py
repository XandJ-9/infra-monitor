# -*- coding: utf-8 -*-

from fastapi.testclient import TestClient

from app.main import app
from app.services.es_service import ESService
from app.services.kafka_service import KafkaService
from app.services.zk_service import ZKService


def test_component_pages_render_before_status_queries(monkeypatch) -> None:
    def fail_sync(*_args, **_kwargs):
        raise AssertionError("status query should be lazy-loaded")

    async def fail_async(*_args, **_kwargs):
        raise AssertionError("status query should be lazy-loaded")

    monkeypatch.setattr(ZKService, "get_status", fail_sync)
    monkeypatch.setattr(KafkaService, "get_status", fail_sync)
    monkeypatch.setattr(ESService, "get_status", fail_async)

    client = TestClient(app)

    for path, title in [
        ("/", "基础设施监控仪表盘"),
        ("/zookeeper/", "ZooKeeper 监控"),
        ("/kafka/", "Kafka 监控"),
        ("/elasticsearch/", "Elasticsearch 监控"),
    ]:
        response = client.get(path)

        assert response.status_code == 200
        assert title in response.text
        assert "正在加载连接状态" in response.text
