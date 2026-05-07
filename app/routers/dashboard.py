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

from app.services.zk_service import ZKService
from app.services.kafka_service import KafkaService
from app.services.es_service import ESService

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """首页仪表盘"""
    zk = ZKService()
    kafka = KafkaService()
    es = ESService()

    # 并发获取各组件状态（设置总超时 15 秒）
    try:
        zk_status, es_status = await asyncio.wait_for(
            asyncio.gather(
                asyncio.to_thread(zk.get_status),
                es.get_status(),
            ),
            timeout=15,
        )
    except asyncio.TimeoutError:
        from app.models import ComponentStatus
        zk_status = ComponentStatus(name="ZooKeeper", connected=False, error="连接超时")
        es_status = await es.get_status()
    kafka_status = kafka.get_status()

    # 读取刷新间隔
    from app.config import load_config
    cfg = load_config()
    refresh_interval = cfg.get("refresh_interval", 30)

    return request.app.state.templates.TemplateResponse("dashboard.html", {
        "request": request,
        "zk_status": zk_status,
        "kafka_status": kafka_status,
        "es_status": es_status,
        "refresh_interval": refresh_interval,
    })


@router.get("/api/dashboard/status")
async def dashboard_status():
    """API：获取各组件状态 JSON"""
    zk = ZKService()
    kafka = KafkaService()
    es = ESService()

    zk_status, es_status = await asyncio.gather(
        asyncio.to_thread(zk.get_status),
        es.get_status(),
    )
    kafka_status = kafka.get_status()

    return {
        "zookeeper": {
            "connected": zk_status.connected,
            "cluster": zk_status.cluster,
            "version": zk_status.version,
            "error": zk_status.error,
            "metrics": zk_status.metrics,
        },
        "kafka": {
            "connected": kafka_status.connected,
            "cluster": kafka_status.cluster,
            "version": kafka_status.version,
            "error": kafka_status.error,
            "metrics": kafka_status.metrics,
        },
        "elasticsearch": {
            "connected": es_status.connected,
            "cluster": es_status.cluster,
            "version": es_status.version,
            "error": es_status.error,
            "metrics": es_status.metrics,
        },
    }


@router.get("/api/dashboard/sse")
async def dashboard_sse():
    """SSE 实时推送各组件状态"""
    async def event_stream() -> AsyncGenerator[str, None]:
        while True:
            zk = ZKService()
            kafka = KafkaService()
            es = ESService()

            zk_status, es_status = await asyncio.gather(
                asyncio.to_thread(zk.get_status),
                es.get_status(),
            )
            kafka_status = kafka.get_status()

            data = {
                "zookeeper": {"connected": zk_status.connected, "cluster": zk_status.cluster,
                               "version": zk_status.version, "error": zk_status.error},
                "kafka": {"connected": kafka_status.connected, "cluster": kafka_status.cluster,
                          "version": kafka_status.version, "error": kafka_status.error},
                "elasticsearch": {"connected": es_status.connected, "cluster": es_status.cluster,
                                  "version": es_status.version, "error": es_status.error},
            }
            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

            from app.config import load_config
            cfg = load_config()
            interval = cfg.get("refresh_interval", 30)
            await asyncio.sleep(interval)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
