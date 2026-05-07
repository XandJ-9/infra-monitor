#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
使用 Playwright 截取应用页面截图
"""

import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

BASE_URL = "http://localhost:8000"
SCREENSHOTS_DIR = Path(__file__).parent / "screenshots"

# 确保截图目录存在
SCREENSHOTS_DIR.mkdir(exist_ok=True)

PAGES = [
    ("dashboard.png", "/", "仪表盘"),
    ("zookeeper.png", "/zookeeper/", "ZooKeeper 监控"),
    ("kafka.png", "/kafka/", "Kafka 监控"),
    ("elasticsearch.png", "/elasticsearch/", "Elasticsearch 监控"),
    ("config.png", "/elasticsearch/config", "配置管理"),
]


async def take_screenshot(filename: str, path: str, title: str):
    """截取指定页面"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # 设置视口大小
        await page.set_viewport_size({"width": 1400, "height": 900})

        print(f"截取 {title} ...")
        await page.goto(f"{BASE_URL}{path}")

        # 等待页面加载完成
        await page.wait_for_load_state("networkidle")

        # 等待一会儿让动态内容加载
        await asyncio.sleep(2)

        # 截图
        await page.screenshot(path=str(SCREENSHOTS_DIR / filename), full_page=True)

        print(f"✓ {filename}")

        await browser.close()


async def main():
    """主函数"""
    print(f"开始截图，目标地址: {BASE_URL}")
    print("-" * 40)

    for filename, path, title in PAGES:
        try:
            await take_screenshot(filename, path, title)
        except Exception as e:
            print(f"✗ {title} 截图失败: {e}")

    print("-" * 40)
    print("截图完成！")


if __name__ == "__main__":
    asyncio.run(main())