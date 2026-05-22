# -*- coding: utf-8 -*-
"""
Elasticsearch 监控路由
- 集群健康、节点列表、索引列表
- 配置管理
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from app.config import load_config, save_config
from app.models import ComponentStatus
from app.services.es_service import ESService
from app.timeouts import with_timeout

router = APIRouter(prefix="/elasticsearch", tags=["Elasticsearch"])


@router.get("/", response_class=HTMLResponse)
async def es_page(request: Request):
    """ES 监控页面"""
    es = ESService()
    status, health, nodes, indices = await asyncio.gather(
        with_timeout(
            es.get_status(),
            fallback=ComponentStatus(name="Elasticsearch", connected=False, error="连接超时"),
        ),
        with_timeout(es.get_cluster_health(), fallback={}),
        with_timeout(es.get_nodes(), fallback=[]),
        with_timeout(es.get_indices(), fallback=[]),
    )

    return request.app.state.templates.TemplateResponse(
        request,
        "elasticsearch.html", {
            "status": status,
            "health": health,
            "nodes": nodes,
            "indices": indices,
        }
    )


@router.get("/api/status")
async def es_status():
    """API：获取 ES 状态"""
    es = ESService()
    status = await with_timeout(
        es.get_status(),
        fallback=ComponentStatus(name="Elasticsearch", connected=False, error="连接超时"),
    )
    return {
        "connected": status.connected,
        "cluster": status.cluster,
        "version": status.version,
        "error": status.error,
        "metrics": status.metrics,
    }


@router.get("/api/health")
async def es_health():
    """API：获取集群健康"""
    es = ESService()
    return await with_timeout(es.get_cluster_health(), fallback={})


@router.get("/api/nodes")
async def es_nodes():
    """API：获取节点列表"""
    es = ESService()
    nodes = await with_timeout(es.get_nodes(), fallback=[])
    return [{"name": n.name, "host": n.host, "role": n.role,
             "heap_percent": n.heap_percent, "ram_percent": n.ram_percent,
             "load": n.load} for n in nodes]


@router.get("/api/indices")
async def es_indices():
    """API：获取索引列表"""
    es = ESService()
    indices = await with_timeout(es.get_indices(), fallback=[])
    return [{"name": i.name, "health": i.health, "status": i.status,
             "docs_count": i.docs_count, "store_size": i.store_size,
             "primaries": i.primaries, "replicas": i.replicas} for i in indices]


@router.get("/api/search")
async def es_search(
    index: str = Query(..., min_length=1),
    q: str = "",
    size: int = Query(10, ge=1, le=100),
):
    """API：查询索引文档"""
    es = ESService()
    return await with_timeout(
        es.search_documents(index=index, query=q, size=size),
        fallback={"error": "查询超时", "hits": [], "total": 0},
    )


# ========== 配置管理路由 ==========

@router.get("/config", response_class=HTMLResponse)
async def config_page(request: Request):
    """配置管理页面"""
    cfg = load_config()
    return request.app.state.templates.TemplateResponse(
        request,
        "config.html", {
            "config": cfg,
        }
    )


@router.post("/config")
async def config_save(request: Request):
    """保存配置"""
    form = await request.form()
    cfg = load_config()

    # 更新 ZK 配置
    zk_hosts = form.get("zk_hosts", "").strip()
    if zk_hosts:
        cfg["zookeeper"]["hosts"] = zk_hosts
    zk_timeout = form.get("zk_timeout", "").strip()
    if zk_timeout:
        try:
            cfg["zookeeper"]["timeout"] = int(zk_timeout)
        except ValueError:
            pass

    # 更新 ES 配置
    es_url = form.get("es_url", "").strip()
    if es_url:
        cfg["elasticsearch"]["url"] = es_url
    es_timeout = form.get("es_timeout", "").strip()
    if es_timeout:
        try:
            cfg["elasticsearch"]["timeout"] = int(es_timeout)
        except ValueError:
            pass

    # 更新刷新间隔
    refresh = form.get("refresh_interval", "").strip()
    if refresh:
        try:
            cfg["refresh_interval"] = int(refresh)
        except ValueError:
            pass

    save_config(cfg)

    # 断开旧的 ZK 连接，让下次请求时用新配置重连
    from app.services.zk_service import ZKService
    ZKService().disconnect()

    return request.app.state.templates.TemplateResponse(
        request,
        "config.html", {
            "config": cfg,
            "saved": True,
        }
    )
