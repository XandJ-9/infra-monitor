# -*- coding: utf-8 -*-

import json

import app.config as config
from app.main import app
from app.services.zk_service import ZKService
from fastapi.testclient import TestClient


def test_zookeeper_connection_crud(tmp_path, monkeypatch) -> None:
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        json.dumps({
            "zookeeper": {"hosts": "zk-default:2181", "timeout": 5},
            "elasticsearch": {"url": "http://127.0.0.1:9200", "timeout": 5},
            "refresh_interval": 30,
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CONFIG_PATH", cfg_path)
    ZKService().disconnect()
    client = TestClient(app)

    initial = client.get("/zookeeper/api/connections")
    assert initial.status_code == 200
    assert initial.json()["connections"][0]["hosts"] == "zk-default:2181"

    created = client.post(
        "/zookeeper/api/connections",
        json={"name": "prod", "hosts": "zk-prod-1:2181,zk-prod-2:2181", "timeout": 7},
    )
    assert created.status_code == 200
    conn_id = created.json()["id"]

    switched = client.post("/zookeeper/api/connections/active", json={"id": conn_id})
    assert switched.status_code == 200
    assert switched.json()["active"] == conn_id

    listed = client.get("/zookeeper/api/connections").json()
    assert listed["active"] == conn_id
    assert len(listed["connections"]) == 2

    deleted = client.delete(f"/zookeeper/api/connections/{conn_id}")
    assert deleted.status_code == 200
    assert deleted.json()["active"] == "default"

    final = client.get("/zookeeper/api/connections").json()
    assert final["connections"] == [{
        "id": "default",
        "name": "默认集群",
        "hosts": "zk-default:2181",
        "timeout": 5,
        "active": True,
        "connected": False,
        "last_fail_time": None,
    }]
