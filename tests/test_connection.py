# -*- coding: utf-8 -*-
"""
连接测试脚本
测试 ZooKeeper、Kafka、Elasticsearch 连接状态
"""

import asyncio
import os
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.zk_service import ZKService
from app.services.kafka_service import KafkaService
from app.services.es_service import ESService

if "pytest" in sys.modules:
    import pytest

    async_test = pytest.mark.asyncio

    def connection_test(func):
        skip_unless_enabled = pytest.mark.skipif(
            os.environ.get("RUN_CONNECTION_TESTS") != "1",
            reason=(
                "Connection checks require local ZooKeeper/Kafka/Elasticsearch; "
                "set RUN_CONNECTION_TESTS=1 to run them."
            ),
        )
        return pytest.mark.integration(skip_unless_enabled(func))
else:
    def async_test(func):
        return func

    def connection_test(func):
        return func


def test_connection_script_imports() -> None:
    """Keep pytest green while integration checks remain opt-in."""
    assert callable(main)


@connection_test
@async_test
async def test_zookeeper() -> None:
    """测试 ZooKeeper 连接"""
    assert await check_zookeeper()


async def check_zookeeper() -> bool:
    print("🦓 测试 ZooKeeper 连接...", end=" ")
    zk = ZKService()
    zk.ensure_connection()

    if not zk.connected:
        print("❌ 失败")
        return False

    status = zk.get_status()
    print(f"✅ 成功 - {status.cluster}")
    return True


@connection_test
@async_test
async def test_kafka() -> None:
    """测试 Kafka 连接"""
    assert await check_kafka()


async def check_kafka() -> bool:
    print("📦 测试 Kafka 连接...", end=" ")
    kafka = KafkaService()
    status = kafka.get_status()

    if not status.connected:
        print(f"❌ 失败 - {status.error}")
        return False

    print(f"✅ 成功 - {status.cluster}")
    return True


@connection_test
@async_test
async def test_elasticsearch() -> None:
    """测试 Elasticsearch 连接"""
    assert await check_elasticsearch()


async def check_elasticsearch() -> bool:
    print("🔍 测试 Elasticsearch 连接...", end=" ")
    es = ESService()
    status = await es.get_status()

    if not status.connected:
        print(f"❌ 失败 - {status.error}")
        return False

    print(f"✅ 成功 - {status.cluster}")
    return True


async def main():
    """主测试函数"""
    print("=" * 50)
    print(" Infra Monitor 连接测试")
    print("=" * 50)
    print()

    results = await asyncio.gather(
        check_zookeeper(),
        check_kafka(),
        check_elasticsearch(),
    )

    print()
    success_count = sum(results)
    print(f"测试完成: {success_count}/3 通过")

    if success_count == 3:
        print("✅ 所有服务连接正常！")
        return 0
    else:
        print("❌ 部分服务连接失败，请检查 Docker 服务状态")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
