#!/bin/bash
# -*- coding: utf-8 -*-
"""
开发环境启动脚本
启动 Docker Compose 测试环境 + FastAPI 应用（使用 uv）
"""

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================="
echo " Infra Monitor 开发环境启动脚本 (uv)"
echo "=========================================="
echo ""

# 检查 Docker 是否运行
if ! docker info > /dev/null 2>&1; then
    echo "错误: Docker 未运行，请先启动 Docker"
    exit 1
fi

# 启动 Docker Compose 服务
echo "📦 启动 Docker Compose 服务 (ZooKeeper, Kafka, Elasticsearch)..."
docker-compose up -d

echo "⏳ 等待服务启动..."
sleep 5

# 等待各服务健康检查通过
echo "🔍 等待 ZooKeeper 就绪..."
timeout 60 bash -c 'until docker-compose exec -T zookeeper nc -z localhost 2181; do sleep 2; done'

echo "🔍 等待 Kafka 就绪..."
timeout 60 bash -c 'until docker-compose exec -T kafka kafka-broker-api-versions --bootstrap-server localhost:9092 > /dev/null 2>&1; do sleep 2; done'

echo "🔍 等待 Elasticsearch 就绪..."
timeout 60 bash -c 'until curl -s http://localhost:9200/_cluster/health > /dev/null 2>&1; do sleep 2; done'

echo ""
echo "✅ 所有服务已就绪!"
echo ""
echo "服务访问地址:"
echo "  - ZooKeeper: localhost:2181"
echo "  - Kafka:     localhost:9092"
echo "  - Elasticsearch: http://localhost:9200"
echo ""

# 使用 uv 同步依赖
echo "🔧 使用 uv 同步依赖..."
uv sync

echo ""
echo "🚀 使用 uv 启动 FastAPI 应用..."
echo "   访问地址: http://localhost:8000"
echo ""
echo "按 Ctrl+C 停止所有服务"
echo ""

# 启动应用（用户按 Ctrl+C 时会触发 trap）
trap "echo ''; echo '🛑 停止 Docker Compose 服务...'; docker-compose down; exit" INT TERM

uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
