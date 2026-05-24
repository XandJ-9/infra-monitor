# -*- coding: utf-8 -*-
"""
ZooKeeper 监控路由
- 集群状态、节点树浏览、节点详情
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.config import load_config, normalize_config, save_config
from app.models import ComponentStatus
from app.services.zk_service import ZKService
from app.timeouts import sync_with_timeout

router = APIRouter(prefix="/zookeeper", tags=["ZooKeeper"])


def _connection_payload(conn: dict, active: str) -> dict:
    return {
        "id": conn.get("id", ""),
        "name": conn.get("name", ""),
        "hosts": conn.get("hosts", ""),
        "timeout": conn.get("timeout", 10),
        "active": conn.get("id") == active,
    }


def _slugify_connection_id(value: str) -> str:
    chars = []
    for char in value.lower().strip():
        if char.isalnum():
            chars.append(char)
        elif char in {"-", "_", ".", ":"}:
            chars.append("-")
    return "".join(chars).strip("-") or "zk"


@router.get("/", response_class=HTMLResponse)
async def zk_page(request: Request):
    """ZK 监控页面"""
    return request.app.state.templates.TemplateResponse(
        request,
        "zookeeper.html",
        {},
    )


@router.get("/api/status")
async def zk_status():
    """API：获取 ZK 状态"""
    zk = ZKService()
    status = await sync_with_timeout(
        zk.get_status,
        fallback=ComponentStatus(name="ZooKeeper", connected=False, error="连接超时"),
    )
    return {
        "connected": status.connected,
        "cluster": status.cluster,
        "version": status.version,
        "error": status.error,
        "metrics": status.metrics,
    }


@router.get("/api/connections")
async def zk_connections():
    """API：获取 ZK 连接配置列表"""
    service_state = ZKService().list_connections()
    cfg = load_config()
    zk_cfg = cfg.get("zookeeper", {})
    active = zk_cfg.get("active", "default")
    runtime = {
        item["id"]: item
        for item in service_state.get("connections", [])
    }
    connections = []
    for conn in zk_cfg.get("connections", []):
        payload = _connection_payload(conn, active)
        payload["connected"] = runtime.get(payload["id"], {}).get("connected", False)
        payload["last_fail_time"] = runtime.get(payload["id"], {}).get("last_fail_time")
        connections.append(payload)
    return {"active": active, "connections": connections}


@router.post("/api/connections")
async def zk_save_connection(request: Request):
    """API：新增或更新 ZK 连接配置"""
    data = await request.json()
    name = str(data.get("name") or "").strip()
    hosts = str(data.get("hosts") or "").strip()
    if not hosts:
        return JSONResponse({"error": "连接地址不能为空"}, status_code=400)

    timeout = data.get("timeout", 10)
    try:
        timeout = int(timeout)
    except (TypeError, ValueError):
        timeout = 10
    timeout = max(1, min(timeout, 120))

    cfg = load_config()
    zk_cfg = cfg.setdefault("zookeeper", {})
    connections = list(zk_cfg.get("connections", []))
    conn_id = str(data.get("id") or "").strip()
    if not conn_id:
        base_id = _slugify_connection_id(name or hosts.split(",", 1)[0])
        existing_ids = {item.get("id") for item in connections}
        conn_id = base_id
        suffix = 2
        while conn_id in existing_ids:
            conn_id = f"{base_id}-{suffix}"
            suffix += 1

    updated = {
        "id": conn_id,
        "name": name or conn_id,
        "hosts": hosts,
        "timeout": timeout,
    }
    for index, item in enumerate(connections):
        if item.get("id") == conn_id:
            connections[index] = updated
            ZKService().disconnect(conn_id)
            break
    else:
        connections.append(updated)

    zk_cfg["connections"] = connections
    if not zk_cfg.get("active"):
        zk_cfg["active"] = conn_id
    save_config(normalize_config(cfg))
    return updated


@router.post("/api/connections/active")
async def zk_set_active_connection(request: Request):
    """API：切换当前 ZK 连接"""
    data = await request.json()
    conn_id = str(data.get("id") or "").strip()
    cfg = load_config()
    zk_cfg = cfg.get("zookeeper", {})
    connections = zk_cfg.get("connections", [])
    if conn_id not in {item.get("id") for item in connections}:
        return JSONResponse({"error": "连接不存在"}, status_code=404)
    zk_cfg["active"] = conn_id
    save_config(normalize_config(cfg))
    return {"active": conn_id}


@router.delete("/api/connections/{conn_id}")
async def zk_delete_connection(conn_id: str):
    """API：删除 ZK 连接配置"""
    cfg = load_config()
    zk_cfg = cfg.get("zookeeper", {})
    connections = zk_cfg.get("connections", [])
    if len(connections) <= 1:
        return JSONResponse({"error": "至少保留一个连接"}, status_code=400)
    if conn_id not in {item.get("id") for item in connections}:
        return JSONResponse({"error": "连接不存在"}, status_code=404)

    zk_cfg["connections"] = [item for item in connections if item.get("id") != conn_id]
    if zk_cfg.get("active") == conn_id:
        zk_cfg["active"] = zk_cfg["connections"][0]["id"]
    ZKService().disconnect(conn_id)
    save_config(normalize_config(cfg))
    return {"deleted": conn_id, "active": zk_cfg.get("active")}


@router.get("/api/tree")
async def zk_tree(path: str = "/", depth: int = 3):
    """API：获取节点树"""
    zk = ZKService()
    tree = await sync_with_timeout(zk.get_tree, path, depth, fallback={"name": path, "children": []})
    return tree


@router.get("/api/node")
async def zk_node(path: str = "/"):
    """API：获取节点详情"""
    zk = ZKService()
    node = await sync_with_timeout(zk.get_node, path, fallback=None)
    if node is None:
        return JSONResponse({"error": "节点不存在", "path": path}, status_code=404)
    return {
        "path": node.path,
        "value": node.value,
        "version": node.version,
        "czxid": node.czxid,
        "mzxid": node.mzxid,
        "ctime": node.ctime,
        "mtime": node.mtime,
        "num_children": node.num_children,
        "children": node.children,
    }


@router.get("/api/children")
async def zk_children(path: str = "/"):
    """API：获取子节点列表"""
    zk = ZKService()
    children = await sync_with_timeout(zk.get_children, path, fallback=[])
    return {"path": path, "children": children}


@router.get("/api/exists")
async def zk_exists(path: str = "/"):
    """API：检查节点是否存在"""
    zk = ZKService()
    exists = await sync_with_timeout(zk.exists, path, fallback=False)
    return {"path": path, "exists": exists}


@router.get("/api/servers")
async def zk_servers():
    """API：获取集群节点信息"""
    zk = ZKService()
    servers = await sync_with_timeout(zk.get_server_info, fallback=[])
    return [{"host": s.host, "port": s.port, "role": s.role} for s in servers]
