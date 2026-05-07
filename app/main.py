# -*- coding: utf-8 -*-
"""
FastAPI 应用入口
- 初始化 app、挂载路由、模板和静态文件
- 支持 root_path 部署（Nginx 路径前缀反向代理）
"""

from __future__ import annotations

import logging
from pathlib import Path
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.routers import dashboard, zookeeper, kafka, elasticsearch

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# 项目路径
BASE_DIR = Path(__file__).resolve().parent.parent

app = FastAPI(
    title="Infra Monitor",
    description="基础设施监控面板 - ZooKeeper / Kafka / Elasticsearch",
    version="0.1.0",
)


class RootPathMiddleware(BaseHTTPMiddleware):
    """将 root_path 注入到请求状态中，供模板和 JS 使用"""

    async def dispatch(self, request: Request, call_next):
        root_path = request.scope.get("root_path", "")
        request.state.root_path = root_path
        response = await call_next(request)
        return response


app.add_middleware(RootPathMiddleware)

# 静态文件和模板
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


class ContextTemplates(Jinja2Templates):
    """自动注入 root_path 到模板上下文的模板类"""

    def TemplateResponse(self, name: str, context: dict, **kwargs):
        # 自动注入 root_path
        request = context.get("request")
        if request and "root_path" not in context:
            context["root_path"] = request.scope.get("root_path", "")
        return super().TemplateResponse(name, context, **kwargs)


templates = ContextTemplates(directory=str(BASE_DIR / "app" / "templates"))

# 将 templates 对象挂到 app.state，路由中通过 request.app.state.templates 访问
app.state.templates = templates

# 挂载路由
app.include_router(dashboard.router)
app.include_router(kafka.router)
app.include_router(zookeeper.router)
app.include_router(elasticsearch.router)


@app.on_event("shutdown")
def shutdown_event():
    """应用关闭时断开 ZK 连接"""
    from app.services.zk_service import ZKService
    zk = ZKService()
    zk.disconnect()
    logger.info("应用关闭，ZK 连接已断开")
