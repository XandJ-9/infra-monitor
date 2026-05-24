# -*- coding: utf-8 -*-
"""
Kafka 监控路由
- Broker 列表、Topic 列表、Consumer Group 列表
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.config import load_config, normalize_config, save_config
from app.models import ComponentStatus
from app.services.kafka_service import KafkaService
from app.timeouts import sync_with_timeout

router = APIRouter(prefix="/kafka", tags=["Kafka"])


def _connection_payload(conn: dict, active: str) -> dict:
    return {
        "id": conn.get("id", ""),
        "name": conn.get("name", ""),
        "bootstrap_servers": conn.get("bootstrap_servers", ""),
        "timeout": conn.get("timeout", 10),
        "security_protocol": conn.get("security_protocol", "PLAINTEXT"),
        "sasl_mechanism": conn.get("sasl_mechanism", "PLAIN"),
        "username": conn.get("username", ""),
        "has_password": bool(conn.get("password")),
        "active": conn.get("id") == active,
    }


def _slugify_connection_id(value: str) -> str:
    chars = []
    for char in value.lower().strip():
        if char.isalnum():
            chars.append(char)
        elif char in {"-", "_", ".", ":"}:
            chars.append("-")
    return "".join(chars).strip("-") or "kafka"


@router.get("/", response_class=HTMLResponse)
async def kafka_page(request: Request):
    """Kafka 监控页面"""
    return request.app.state.templates.TemplateResponse(
        request,
        "kafka.html",
        {},
    )


@router.get("/api/status")
async def kafka_status():
    """API：获取 Kafka 状态"""
    kafka = KafkaService()
    status = await sync_with_timeout(
        kafka.get_status,
        fallback=ComponentStatus(name="Kafka", connected=False, error="连接超时"),
    )
    return {
        "connected": status.connected,
        "cluster": status.cluster,
        "version": status.version,
        "error": status.error,
        "metrics": status.metrics,
    }


@router.get("/api/connections")
async def kafka_connections():
    """API：获取 Kafka 连接配置列表"""
    service_state = KafkaService().list_connections()
    cfg = load_config()
    kafka_cfg = cfg.get("kafka", {})
    active = kafka_cfg.get("active", "default")
    runtime = {
        item["id"]: item
        for item in service_state.get("connections", [])
    }
    connections = []
    for conn in kafka_cfg.get("connections", []):
        payload = _connection_payload(conn, active)
        payload["has_password"] = runtime.get(payload["id"], {}).get("has_password", payload["has_password"])
        connections.append(payload)
    return {"active": active, "connections": connections}


@router.post("/api/connections")
async def kafka_save_connection(request: Request):
    """API：新增或更新 Kafka 连接配置"""
    data = await request.json()
    name = str(data.get("name") or "").strip()
    bootstrap_servers = str(data.get("bootstrap_servers") or "").strip()
    if not bootstrap_servers:
        return JSONResponse({"error": "Bootstrap Servers 不能为空"}, status_code=400)

    timeout = data.get("timeout", 10)
    try:
        timeout = int(timeout)
    except (TypeError, ValueError):
        timeout = 10
    timeout = max(1, min(timeout, 120))

    security_protocol = str(data.get("security_protocol") or "PLAINTEXT").strip().upper()
    sasl_mechanism = str(data.get("sasl_mechanism") or "PLAIN").strip().upper()
    username = str(data.get("username") or "").strip()
    password = data.get("password")

    cfg = load_config()
    kafka_cfg = cfg.setdefault("kafka", {})
    connections = list(kafka_cfg.get("connections", []))
    conn_id = str(data.get("id") or "").strip()
    if not conn_id:
        base_id = _slugify_connection_id(name or bootstrap_servers.split(",", 1)[0])
        existing_ids = {item.get("id") for item in connections}
        conn_id = base_id
        suffix = 2
        while conn_id in existing_ids:
            conn_id = f"{base_id}-{suffix}"
            suffix += 1

    existing_password = ""
    for item in connections:
        if item.get("id") == conn_id:
            existing_password = str(item.get("password") or "")
            break

    updated = {
        "id": conn_id,
        "name": name or conn_id,
        "bootstrap_servers": bootstrap_servers,
        "timeout": timeout,
        "security_protocol": security_protocol,
        "sasl_mechanism": sasl_mechanism,
        "username": username,
        "password": str(password) if password is not None else existing_password,
    }
    for index, item in enumerate(connections):
        if item.get("id") == conn_id:
            connections[index] = updated
            break
    else:
        connections.append(updated)

    kafka_cfg["connections"] = connections
    if not kafka_cfg.get("active"):
        kafka_cfg["active"] = conn_id
    save_config(normalize_config(cfg))
    response = dict(updated)
    response["has_password"] = bool(response.pop("password", ""))
    return response


@router.post("/api/connections/active")
async def kafka_set_active_connection(request: Request):
    """API：切换当前 Kafka 连接"""
    data = await request.json()
    conn_id = str(data.get("id") or "").strip()
    cfg = load_config()
    kafka_cfg = cfg.get("kafka", {})
    connections = kafka_cfg.get("connections", [])
    if conn_id not in {item.get("id") for item in connections}:
        return JSONResponse({"error": "连接不存在"}, status_code=404)
    kafka_cfg["active"] = conn_id
    save_config(normalize_config(cfg))
    return {"active": conn_id}


@router.delete("/api/connections/{conn_id}")
async def kafka_delete_connection(conn_id: str):
    """API：删除 Kafka 连接配置"""
    cfg = load_config()
    kafka_cfg = cfg.get("kafka", {})
    connections = kafka_cfg.get("connections", [])
    if len(connections) <= 1:
        return JSONResponse({"error": "至少保留一个连接"}, status_code=400)
    if conn_id not in {item.get("id") for item in connections}:
        return JSONResponse({"error": "连接不存在"}, status_code=404)

    kafka_cfg["connections"] = [item for item in connections if item.get("id") != conn_id]
    if kafka_cfg.get("active") == conn_id:
        kafka_cfg["active"] = kafka_cfg["connections"][0]["id"]
    save_config(normalize_config(cfg))
    return {"deleted": conn_id, "active": kafka_cfg.get("active")}


@router.get("/api/brokers")
async def kafka_brokers():
    """API：获取 Broker 列表"""
    kafka = KafkaService()
    brokers = await sync_with_timeout(kafka.get_brokers, fallback=[])
    return [{"broker_id": b.broker_id, "host": b.host, "port": b.port, "rack": b.rack} for b in brokers]


@router.get("/api/topics")
async def kafka_topics():
    """API：获取 Topic 列表"""
    kafka = KafkaService()
    topics = await sync_with_timeout(kafka.get_topics, fallback=[])
    return [{"name": t.name, "partitions": t.partitions, "replicas": t.replicas,
             "under_replicated_partitions": t.under_replicated_partitions,
             "offline_partitions": t.offline_partitions,
             "partition_details": t.partition_details} for t in topics]


@router.get("/api/consumer-groups")
async def kafka_consumer_groups():
    """API：获取 Consumer Group 列表"""
    kafka = KafkaService()
    groups = await sync_with_timeout(kafka.get_consumer_groups, fallback=[])
    return [{"group_id": g.group_id, "state": g.state, "members": g.members,
             "topics": g.topics, "lag": g.lag, "offsets": g.offsets} for g in groups]
