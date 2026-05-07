# Infra Monitor

基础设施监控面板 —— ZooKeeper / Kafka / Elasticsearch 一站式监控。

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

## 功能特性

- **首页仪表盘**：一览三个组件的连接状态、版本、关键指标
- **ZooKeeper 监控**：集群状态、节点树浏览器、节点数据查看
- **Kafka 监控**：Broker 列表、Topic 列表、Consumer Group 及 Lag
- **Elasticsearch 监控**：集群健康、节点负载、索引列表
- **配置管理**：Web 界面修改连接地址，即时生效

## 技术栈

- Python 3.10+
- FastAPI + Uvicorn
- Jinja2 + Bootstrap 5
- kazoo（ZK 客户端）
- httpx（异步 HTTP 客户端，调用 ES API）

## 快速开始

### 0. Docker 测试环境（可选）

项目提供了 Docker Compose 配置，一键启动 ZooKeeper、Kafka、Elasticsearch 测试环境：

```bash
# 启动测试环境
docker-compose up -d

# 查看服务状态
docker-compose ps

# 查看日志
docker-compose logs -f

# 停止测试环境
docker-compose down
```

**使用启动脚本（推荐）**：
```bash
./start-dev.sh
```
此脚本会自动：
1. 启动 Docker Compose 服务
2. 等待所有服务健康检查通过
3. 使用 uv 同步依赖
4. 启动 FastAPI 应用

服务启动后访问：http://localhost:8000

### 1. 安装 uv 和依赖

```bash
# 安装 uv（如果尚未安装）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 同步依赖
uv sync
```

### 2. 修改配置（可选）

编辑 `config.json`，修改各组件连接地址：

```json
{
  "zookeeper": {
    "hosts": "127.0.0.1:2181",
    "timeout": 10
  },
  "elasticsearch": {
    "url": "http://127.0.0.1:9200",
    "timeout": 10
  },
  "refresh_interval": 30
}
```

也可以启动后在 Web 界面的「配置」页面修改。

### 3. 启动服务

**使用 uv（推荐）：**

直接访问模式：
```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Nginx 反向代理模式（路径前缀 `/infra-monitor/`）：
```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --root-path /infra-monitor
```

> `--root-path /infra-monitor` 让 FastAPI 知道自己部署在 `/infra-monitor/` 路径下，所有模板链接和静态文件路径会自动添加前缀。

### 4. 访问

- 直接访问：http://localhost:8000
- Nginx 代理：http://yourserver/infra-monitor/

## 项目结构

```
infra-monitor/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI 入口
│   ├── config.py            # 配置管理（读写 config.json）
│   ├── models.py            # 数据模型
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── dashboard.py     # 首页仪表盘 + SSE 推送
│   │   ├── zookeeper.py     # ZK 监控路由
│   │   ├── kafka.py         # Kafka 监控路由
│   │   └── elasticsearch.py # ES 监控路由 + 配置管理
│   ├── services/
│   │   ├── __init__.py
│   │   ├── zk_service.py    # ZK 连接与操作（基于 kazoo）
│   │   ├── kafka_service.py # Kafka 元数据（通过 ZK 获取）
│   │   └── es_service.py    # ES HTTP API 调用
│   └── templates/
│       ├── base.html        # 基础模板（导航栏、Bootstrap）
│       ├── dashboard.html   # 仪表盘
│       ├── zookeeper.html   # ZK 监控（含节点树浏览器）
│       ├── kafka.html       # Kafka 监控
│       ├── elasticsearch.html # ES 监控
│       └── config.html      # 配置管理
├── static/
│   ├── css/style.css        # 自定义样式
│   └── js/app.js            # 前端工具函数
├── docker-compose.yml       # Docker 测试环境配置
├── start-dev.sh             # 开发环境启动脚本
├── config.json              # 运行时配置
├── pyproject.toml           # Python 依赖配置（uv）
└── README.md
```

## API 接口

### 仪表盘

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/dashboard/status` | 获取各组件状态 JSON |
| GET | `/api/dashboard/sse` | SSE 实时推送状态 |

### ZooKeeper

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/zookeeper/api/status` | ZK 连接状态 |
| GET | `/zookeeper/api/tree?path=/&depth=3` | 节点树 |
| GET | `/zookeeper/api/node?path=/brokers` | 节点详情 |
| GET | `/zookeeper/api/children?path=/` | 子节点列表 |
| GET | `/zookeeper/api/exists?path=/controller` | 节点是否存在 |
| GET | `/zookeeper/api/servers` | 集群节点信息 |

### Kafka

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/kafka/api/status` | Kafka 状态 |
| GET | `/kafka/api/brokers` | Broker 列表 |
| GET | `/kafka/api/topics` | Topic 列表 |
| GET | `/kafka/api/consumer-groups` | Consumer Group 列表 |

### Elasticsearch

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/elasticsearch/api/status` | ES 状态 |
| GET | `/elasticsearch/api/health` | 集群健康 |
| GET | `/elasticsearch/api/nodes` | 节点列表 |
| GET | `/elasticsearch/api/indices` | 索引列表 |

## 注意事项

1. ZK 和 Kafka 元数据通过 kazoo 获取，不依赖 kafka-python
2. ES 通过 HTTP API 获取，使用 httpx 异步调用
3. 连接失败会优雅降级，不影响其他组件展示
4. Kafka 新版 Consumer Group 的 offset 存储在 `__consumer_offsets` 内部 topic，通过 ZK 无法直接获取完整信息，需使用 Kafka AdminClient API
5. Docker 测试环境版本：ZooKeeper 7.5.0、Kafka 7.5.0、Elasticsearch 8.11.0
