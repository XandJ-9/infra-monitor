# Infra Monitor

Infra Monitor 是一个轻量级基础设施监控面板，用于在内网或本地环境中快速查看 ZooKeeper、Kafka、Elasticsearch 以及服务器文件的运行状态与基础信息。

## 功能概览

- 首页仪表盘：汇总各组件连接状态、版本和关键指标
- ZooKeeper 监控：集群状态、节点树浏览、节点数据查看
- Kafka 监控：Broker、Topic、Consumer Group 基础信息
- Elasticsearch 监控：集群健康、节点负载、索引列表
- 在线文件浏览器：只读浏览服务器文件目录，预览文本、代码和图片文件
- 配置管理：通过 Web 页面调整连接地址和刷新间隔

## 技术栈

- Python 3.10+
- FastAPI + Uvicorn
- Jinja2 + Bootstrap 5
- kazoo
- httpx

## 快速开始

推荐使用开发启动脚本，它会启动 Docker 测试环境、同步依赖并运行 FastAPI 应用：

```bash
./start-dev.sh
```

服务启动后访问：

- 直接访问：http://localhost:8000
- Nginx 代理模式：http://yourserver/infra-monitor/

也可以手动启动：

```bash
uv sync
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## 文档

项目设计、开发流程和后续规划已整理到 [doc](doc/) 目录：

- [文档索引](doc/README.md)
- [架构设计](doc/architecture.md)
- [开发流程](doc/development.md)
- [开发计划](doc/development-plan.md)
- [在线文件浏览器设计方案](doc/file-browser-design.md)

## 截图预览

### 仪表盘

![Dashboard](screenshots/dashboard.png)

### ZooKeeper 监控

![ZooKeeper](screenshots/zookeeper.png)

### Kafka 监控

![Kafka](screenshots/kafka.png)

### Elasticsearch 监控

![Elasticsearch](screenshots/elasticsearch.png)

### 配置管理

![Config](screenshots/config.png)
