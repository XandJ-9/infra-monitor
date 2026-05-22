# -*- coding: utf-8 -*-

import pytest

from app.services.es_service import ESService


@pytest.mark.asyncio
async def test_search_documents_builds_query_and_parses_hits(monkeypatch) -> None:
    captured = {}

    async def fake_post(path, payload):
        captured["path"] = path
        captured["payload"] = payload
        return {
            "hits": {
                "total": {"value": 1, "relation": "eq"},
                "hits": [
                    {
                        "_index": "infra-monitor-demo",
                        "_id": "demo-001",
                        "_score": 1.25,
                        "_source": {"message": "infra-monitor 可查询测试数据"},
                    }
                ],
            }
        }

    es = ESService()
    monkeypatch.setattr(es, "_post", fake_post)

    result = await es.search_documents(
        index="infra-monitor-demo",
        query='message:"infra-monitor 可查询测试数据"',
        size=5,
    )

    assert captured["path"] == "/infra-monitor-demo/_search"
    assert captured["payload"]["query"]["query_string"]["default_operator"] == "AND"
    assert captured["payload"]["size"] == 5
    assert result == {
        "hits": [
            {
                "index": "infra-monitor-demo",
                "id": "demo-001",
                "score": 1.25,
                "source": {"message": "infra-monitor 可查询测试数据"},
            }
        ],
        "total": 1,
        "error": "",
    }


@pytest.mark.asyncio
async def test_search_documents_rejects_blank_index() -> None:
    result = await ESService().search_documents(index=" ")

    assert result == {"error": "索引名称不能为空", "hits": [], "total": 0}
