# -*- coding: utf-8 -*-
"""
ZooKeeper 监控路由
- 集群状态、节点树浏览、节点详情
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.models import ComponentStatus
from app.services.zk_service import ZKService
from app.timeouts import sync_with_timeout

router = APIRouter(prefix="/zookeeper", tags=["ZooKeeper"])


@router.get("/", response_class=HTMLResponse)
async def zk_page(request: Request):
    """ZK 监控页面"""
    zk = ZKService()

    # 设置总超时 15 秒，避免 ZK 连接阻塞页面
    status, servers = await asyncio.gather(
        sync_with_timeout(
            zk.get_status,
            fallback=ComponentStatus(name="ZooKeeper", connected=False, error="连接超时"),
        ),
        sync_with_timeout(zk.get_server_info, fallback=[]),
    )

    # 获取关键 znode 监控
    key_paths = ["/controller", "/brokers", "/brokers/ids", "/brokers/topics",
                 "/cluster", "/admin", "/config"]
    key_nodes = []
    if zk.connected:
        for path in key_paths:
            exists = await sync_with_timeout(zk.exists, path, fallback=False)
            key_nodes.append({"path": path, "exists": exists})
    else:
        key_nodes = [{"path": p, "exists": False} for p in key_paths]

    return request.app.state.templates.TemplateResponse(
        request,
        "zookeeper.html", {
            "status": status,
            "servers": servers,
            "key_nodes": key_nodes,
        }
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
