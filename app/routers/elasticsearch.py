# -*- coding: utf-8 -*-
"""
Elasticsearch 监控路由
- 集群健康、节点列表、索引列表
- 连接配置由 Elasticsearch 页面内管理
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.config import load_config, normalize_config, save_config
from app.models import ComponentStatus
from app.services.es_service import ESService
from app.timeouts import with_timeout

router = APIRouter(prefix="/elasticsearch", tags=["Elasticsearch"])


def _connection_payload(conn: dict, active: str) -> dict:
    return {
        "id": conn.get("id", ""),
        "name": conn.get("name", ""),
        "url": conn.get("url", ""),
        "timeout": conn.get("timeout", 10),
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
    return "".join(chars).strip("-") or "es"


@router.get("/", response_class=HTMLResponse)
async def es_page(request: Request):
    """ES 监控页面"""
    return request.app.state.templates.TemplateResponse(
        request,
        "elasticsearch.html",
        {},
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


@router.get("/api/connections")
async def es_connections():
    """API：获取 ES 连接配置列表"""
    service_state = ESService().list_connections()
    cfg = load_config()
    es_cfg = cfg.get("elasticsearch", {})
    active = es_cfg.get("active", "default")
    runtime = {
        item["id"]: item
        for item in service_state.get("connections", [])
    }
    connections = []
    for conn in es_cfg.get("connections", []):
        payload = _connection_payload(conn, active)
        payload["has_password"] = runtime.get(payload["id"], {}).get("has_password", payload["has_password"])
        connections.append(payload)
    return {"active": active, "connections": connections}


@router.post("/api/connections")
async def es_save_connection(request: Request):
    """API：新增或更新 ES 连接配置"""
    data = await request.json()
    name = str(data.get("name") or "").strip()
    url = str(data.get("url") or "").strip()
    if not url:
        return JSONResponse({"error": "连接地址不能为空"}, status_code=400)

    timeout = data.get("timeout", 10)
    try:
        timeout = int(timeout)
    except (TypeError, ValueError):
        timeout = 10
    timeout = max(1, min(timeout, 120))

    username = str(data.get("username") or "").strip()
    password = data.get("password")

    cfg = load_config()
    es_cfg = cfg.setdefault("elasticsearch", {})
    connections = list(es_cfg.get("connections", []))
    conn_id = str(data.get("id") or "").strip()
    if not conn_id:
        base_id = _slugify_connection_id(name or url.replace("://", "-").split("/", 1)[0])
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
        "url": url,
        "timeout": timeout,
        "username": username,
        "password": str(password) if password is not None else existing_password,
    }
    for index, item in enumerate(connections):
        if item.get("id") == conn_id:
            connections[index] = updated
            break
    else:
        connections.append(updated)

    es_cfg["connections"] = connections
    if not es_cfg.get("active"):
        es_cfg["active"] = conn_id
    save_config(normalize_config(cfg))
    response = dict(updated)
    response["has_password"] = bool(response.pop("password", ""))
    return response


@router.post("/api/connections/active")
async def es_set_active_connection(request: Request):
    """API：切换当前 ES 连接"""
    data = await request.json()
    conn_id = str(data.get("id") or "").strip()
    cfg = load_config()
    es_cfg = cfg.get("elasticsearch", {})
    connections = es_cfg.get("connections", [])
    if conn_id not in {item.get("id") for item in connections}:
        return JSONResponse({"error": "连接不存在"}, status_code=404)
    es_cfg["active"] = conn_id
    save_config(normalize_config(cfg))
    return {"active": conn_id}


@router.delete("/api/connections/{conn_id}")
async def es_delete_connection(conn_id: str):
    """API：删除 ES 连接配置"""
    cfg = load_config()
    es_cfg = cfg.get("elasticsearch", {})
    connections = es_cfg.get("connections", [])
    if len(connections) <= 1:
        return JSONResponse({"error": "至少保留一个连接"}, status_code=400)
    if conn_id not in {item.get("id") for item in connections}:
        return JSONResponse({"error": "连接不存在"}, status_code=404)

    es_cfg["connections"] = [item for item in connections if item.get("id") != conn_id]
    if es_cfg.get("active") == conn_id:
        es_cfg["active"] = es_cfg["connections"][0]["id"]
    save_config(normalize_config(cfg))
    return {"deleted": conn_id, "active": es_cfg.get("active")}


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


@router.get("/config", response_class=HTMLResponse)
async def legacy_config_page(request: Request):
    """旧配置路径兼容，连接管理已合并到 ES 页面。"""
    root_path = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{root_path}/elasticsearch/", status_code=307)


@router.post("/config")
async def legacy_config_save(request: Request):
    """旧配置保存路径兼容，连接管理已合并到 ES 页面。"""
    root_path = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{root_path}/elasticsearch/", status_code=307)
