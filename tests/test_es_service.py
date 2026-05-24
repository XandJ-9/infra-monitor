# -*- coding: utf-8 -*-

import json

import pytest
from fastapi.testclient import TestClient

import app.config as config
from app.main import app
from app.services.es_service import ESService


@pytest.mark.asyncio
async def test_search_documents_builds_query_and_parses_hits(monkeypatch) -> None:
    captured = {}

    async def fake_post(path, payload):
        captured["path"] = path
        captured["payload"] = payload
        return {
            "hits": {
                "total": {"value": 1, "relation": "eq"},
                "hits": [
                    {
                        "_index": "infra-monitor-demo",
                        "_id": "demo-001",
                        "_score": 1.25,
                        "_source": {"message": "infra-monitor 可查询测试数据"},
                    }
                ],
            }
        }

    es = ESService()
    monkeypatch.setattr(es, "_post", fake_post)

    result = await es.search_documents(
        index="infra-monitor-demo",
        query='message:"infra-monitor 可查询测试数据"',
        size=5,
    )

    assert captured["path"] == "/infra-monitor-demo/_search"
    assert captured["payload"]["query"]["query_string"]["default_operator"] == "AND"
    assert captured["payload"]["size"] == 5
    assert result == {
        "hits": [
            {
                "index": "infra-monitor-demo",
                "id": "demo-001",
                "score": 1.25,
                "source": {"message": "infra-monitor 可查询测试数据"},
            }
        ],
        "total": 1,
        "error": "",
    }


@pytest.mark.asyncio
async def test_search_documents_rejects_blank_index() -> None:
    result = await ESService().search_documents(index=" ")

    assert result == {"error": "索引名称不能为空", "hits": [], "total": 0}


@pytest.mark.asyncio
async def test_get_status_includes_connection_name(monkeypatch) -> None:
    es = ESService()
    monkeypatch.setattr(es, "_connection", lambda connection_id=None: {
        "id": "prod",
        "name": "生产集群",
        "url": "http://es-prod:9200",
        "timeout": 5,
    })

    async def fake_get(path, connection_id=None):
        if path == "/":
            return {"cluster_name": "docker-cluster", "version": {"number": "8.11.0"}}
        return {"status": "green", "number_of_nodes": 3, "active_shards": 9, "unassigned_shards": 0}

    monkeypatch.setattr(es, "_get", fake_get)

    status = await es.get_status()

    assert status.cluster == "docker-cluster"
    assert status.metrics["连接名称"] == "生产集群"
    assert status.metrics["连接地址"] == "http://es-prod:9200"


def test_es_client_options_include_basic_auth() -> None:
    options = ESService()._client_options({
        "timeout": 7,
        "username": "elastic",
        "password": "secret",
    })

    assert options == {"timeout": 7, "auth": ("elastic", "secret")}


def test_elasticsearch_connection_crud(tmp_path, monkeypatch) -> None:
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        json.dumps({
            "zookeeper": {"hosts": "zk-default:2181", "timeout": 5},
            "elasticsearch": {"url": "http://es-default:9200", "timeout": 5},
            "refresh_interval": 30,
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CONFIG_PATH", cfg_path)
    client = TestClient(app)

    initial = client.get("/elasticsearch/api/connections")
    assert initial.status_code == 200
    assert initial.json()["connections"][0]["url"] == "http://es-default:9200"

    created = client.post(
        "/elasticsearch/api/connections",
        json={
            "name": "prod",
            "url": "https://es-prod.example.com:9200",
            "timeout": 7,
            "username": "elastic",
            "password": "secret",
        },
    )
    assert created.status_code == 200
    conn_id = created.json()["id"]
    assert created.json()["has_password"] is True
    assert "password" not in created.json()

    switched = client.post("/elasticsearch/api/connections/active", json={"id": conn_id})
    assert switched.status_code == 200
    assert switched.json()["active"] == conn_id

    listed = client.get("/elasticsearch/api/connections").json()
    assert listed["active"] == conn_id
    assert len(listed["connections"]) == 2
    assert listed["connections"][1]["username"] == "elastic"
    assert listed["connections"][1]["has_password"] is True

    deleted = client.delete(f"/elasticsearch/api/connections/{conn_id}")
    assert deleted.status_code == 200
    assert deleted.json()["active"] == "default"
