# -*- coding: utf-8 -*-
"""
Kafka 监控路由
- Broker 列表、Topic 列表、Consumer Group 列表
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.services.kafka_service import KafkaService

router = APIRouter(prefix="/kafka", tags=["Kafka"])


@router.get("/", response_class=HTMLResponse)
async def kafka_page(request: Request):
    """Kafka 监控页面"""
    kafka = KafkaService()
    status = kafka.get_status()
    brokers = await asyncio.to_thread(kafka.get_brokers)
    topics = await asyncio.to_thread(kafka.get_topics)
    consumer_groups = await asyncio.to_thread(kafka.get_consumer_groups)

    return request.app.state.templates.TemplateResponse("kafka.html", {
        "request": request,
        "status": status,
        "brokers": brokers,
        "topics": topics,
        "consumer_groups": consumer_groups,
    })


@router.get("/api/status")
async def kafka_status():
    """API：获取 Kafka 状态"""
    kafka = KafkaService()
    status = kafka.get_status()
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
    brokers = await asyncio.to_thread(kafka.get_brokers)
    return [{"broker_id": b.broker_id, "host": b.host, "port": b.port} for b in brokers]


@router.get("/api/topics")
async def kafka_topics():
    """API：获取 Topic 列表"""
    kafka = KafkaService()
    topics = await asyncio.to_thread(kafka.get_topics)
    return [{"name": t.name, "partitions": t.partitions, "replicas": t.replicas,
             "partition_details": t.partition_details} for t in topics]


@router.get("/api/consumer-groups")
async def kafka_consumer_groups():
    """API：获取 Consumer Group 列表"""
    kafka = KafkaService()
    groups = await asyncio.to_thread(kafka.get_consumer_groups)
    return [{"group_id": g.group_id, "state": g.state, "members": g.members,
             "topics": g.topics, "lag": g.lag} for g in groups]
