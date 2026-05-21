# -*- coding: utf-8 -*-
"""
首页仪表盘路由
- 汇总各组件状态
- SSE 实时推送
"""

from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from app.models import ComponentStatus
from app.services.es_service import ESService
from app.services.kafka_service import KafkaService
from app.services.zk_service import ZKService
from app.timeouts import sync_with_timeout, with_timeout

router = APIRouter()


def _status_payload(status: ComponentStatus) -> dict:
    return {
        "connected": status.connected,
        "cluster": status.cluster,
        "version": status.version,
        "error": status.error,
        "metrics": status.metrics,
    }


async def _component_statuses() -> tuple[ComponentStatus, ComponentStatus, ComponentStatus]:
    zk = ZKService()
    kafka = KafkaService()
    es = ESService()

    return await asyncio.gather(
        sync_with_timeout(
            zk.get_status,
            fallback=ComponentStatus(name="ZooKeeper", connected=False, error="连接超时"),
        ),
        sync_with_timeout(
            kafka.get_status,
            fallback=ComponentStatus(name="Kafka", connected=False, error="连接超时"),
        ),
        with_timeout(
            es.get_status(),
            fallback=ComponentStatus(name="Elasticsearch", connected=False, error="连接超时"),
        ),
    )


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """首页仪表盘"""
    zk_status, kafka_status, es_status = await _component_statuses()

    # 读取刷新间隔
    from app.config import load_config
    cfg = load_config()
    refresh_interval = cfg.get("refresh_interval", 30)

    return request.app.state.templates.TemplateResponse(
        request,
        "dashboard.html", {
            "zk_status": zk_status,
            "kafka_status": kafka_status,
            "es_status": es_status,
            "refresh_interval": refresh_interval,
        }
    )


@router.get("/api/dashboard/status")
async def dashboard_status():
    """API：获取各组件状态 JSON"""
    zk_status, kafka_status, es_status = await _component_statuses()

    return {
        "zookeeper": _status_payload(zk_status),
        "kafka": _status_payload(kafka_status),
        "elasticsearch": _status_payload(es_status),
    }


@router.get("/api/dashboard/sse")
async def dashboard_sse():
    """SSE 实时推送各组件状态"""
    async def event_stream() -> AsyncGenerator[str, None]:
        while True:
            zk_status, kafka_status, es_status = await _component_statuses()

            data = {
                "zookeeper": _status_payload(zk_status),
                "kafka": _status_payload(kafka_status),
                "elasticsearch": _status_payload(es_status),
            }
            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

            from app.config import load_config
            cfg = load_config()
            interval = cfg.get("refresh_interval", 30)
            await asyncio.sleep(interval)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
