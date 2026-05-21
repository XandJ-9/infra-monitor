#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

cleanup() {
    echo ""
    echo "Stopping Docker Compose services..."
    docker compose down
}

trap cleanup INT TERM

echo "=========================================="
echo " Infra Monitor dev environment (uv)"
echo "=========================================="
echo ""

if ! docker info > /dev/null 2>&1; then
    echo "Error: Docker is not running. Start Docker and try again."
    exit 1
fi

echo "Starting Docker Compose services (ZooKeeper, Kafka, Elasticsearch)..."
docker compose up -d

echo "Waiting for services to start..."
sleep 5

echo "Waiting for ZooKeeper..."
timeout 60 bash -c 'until docker compose exec -T zookeeper nc -z localhost 2181; do sleep 2; done'

echo "Waiting for Kafka..."
timeout 60 bash -c 'until docker compose exec -T kafka kafka-broker-api-versions --bootstrap-server localhost:9092 > /dev/null 2>&1; do sleep 2; done'

echo "Waiting for Elasticsearch..."
timeout 60 bash -c 'until curl -fsS http://localhost:9200/_cluster/health > /dev/null 2>&1; do sleep 2; done'

echo ""
echo "All services are ready."
echo ""
echo "Service endpoints:"
echo "  - ZooKeeper: localhost:2181"
echo "  - Kafka:     localhost:9092"
echo "  - Elasticsearch: http://localhost:9200"
echo ""

echo "Syncing dependencies with uv..."
uv sync

echo ""
echo "Starting FastAPI app with uv..."
echo "Visit: http://localhost:8000"
echo "Press Ctrl+C to stop the app and Docker Compose services."
echo ""

uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
