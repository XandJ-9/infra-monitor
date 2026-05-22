# -*- coding: utf-8 -*-
"""
Kafka 监控路由
- Broker 列表、Topic 列表、Consumer Group 列表
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.models import ComponentStatus
from app.services.kafka_service import KafkaService
from app.timeouts import sync_with_timeout

router = APIRouter(prefix="/kafka", tags=["Kafka"])


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


@router.get("/api/brokers")
async def kafka_brokers():
    """API：获取 Broker 列表"""
    kafka = KafkaService()
    brokers = await sync_with_timeout(kafka.get_brokers, fallback=[])
    return [{"broker_id": b.broker_id, "host": b.host, "port": b.port} for b in brokers]


@router.get("/api/topics")
async def kafka_topics():
    """API：获取 Topic 列表"""
    kafka = KafkaService()
    topics = await sync_with_timeout(kafka.get_topics, fallback=[])
    return [{"name": t.name, "partitions": t.partitions, "replicas": t.replicas,
             "partition_details": t.partition_details} for t in topics]


@router.get("/api/consumer-groups")
async def kafka_consumer_groups():
    """API：获取 Consumer Group 列表"""
    kafka = KafkaService()
    groups = await sync_with_timeout(kafka.get_consumer_groups, fallback=[])
    return [{"group_id": g.group_id, "state": g.state, "members": g.members,
             "topics": g.topics, "lag": g.lag} for g in groups]
