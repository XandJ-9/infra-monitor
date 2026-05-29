# 架构设计

## 设计目标

Infra Monitor 采用轻量级 Web 应用结构，目标是在可信内网环境中提供基础设施状态查看、元数据浏览、组件连接管理和只读文件诊断能力。系统优先保证单组件异常时的优雅降级，避免一个外部服务连接失败影响整体页面访问。

## 技术架构

- 后端：FastAPI + Jinja2，按 `routers` 和 `services` 分层。
- 前端：Bootstrap 5 + Jinja2 模板，局部使用 fetch 调用 JSON API。
- ZooKeeper：通过 `kazoo` 维护连接并读取节点、状态和树结构。
- Kafka：优先通过 Kafka AdminClient 读取 broker、topic、partition、consumer group 和 lag 信息，ZooKeeper 仅作为旧集群元数据兼容路径。
- Elasticsearch：通过 `httpx` 调用 HTTP API 获取健康、节点、索引信息。
- 文件浏览器：通过本地文件服务层实现只读目录列表、文本预览和图片预览。
- 代码预览：文件浏览器对 Python、SQL、Bash 和 JSON 文本文件提供基础语法高亮。
- 连接管理：ZooKeeper、Kafka、Elasticsearch 在各自页面内维护连接列表、当前连接和认证信息，并通过本地 SQLite 持久化。

## 分层职责

- `app/main.py`：FastAPI 应用入口，注册静态资源、模板和路由。
- `app/routers/`：页面路由与 API 路由，负责参数接收、响应渲染和异常映射。
- `app/services/`：组件连接、外部 API 调用、文件系统访问等业务逻辑。
- `app/templates/`：Jinja2 页面模板。
- `static/`：全局 CSS 与 JavaScript。
- `app/config.py`：默认配置、SQLite 配置加载、合并、归一化和保存，作为各模块连接管理的持久化工具。
- `app/timeouts.py`：统一超时相关工具。
- `tests/test_*.py`：pytest 测试用例统一存放目录。

## 项目结构

```text
infra-monitor/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── models.py
│   ├── timeouts.py
│   ├── routers/
│   │   ├── dashboard.py
│   │   ├── zookeeper.py
│   │   ├── kafka.py
│   │   ├── elasticsearch.py
│   │   └── files.py
│   ├── services/
│   │   ├── zk_service.py
│   │   ├── kafka_service.py
│   │   ├── es_service.py
│   │   └── file_service.py
│   └── templates/
│       ├── base.html
│       ├── dashboard.html
│       ├── zookeeper.html
│       ├── kafka.html
│       ├── elasticsearch.html
│       └── files.html
├── doc/
├── screenshots/
├── static/
│   ├── css/style.css
│   └── js/app.js
├── tests/
│   ├── test_config.py
│   ├── test_connection.py
│   ├── test_es_service.py
│   ├── test_file_service.py
│   └── test_files_router.py
├── docker-compose.yml
├── start-dev.sh
├── pyproject.toml
└── README.md
```

## 页面与 API

### 仪表盘

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 仪表盘页面 |
| GET | `/api/dashboard/status` | 获取各组件状态 JSON |
| GET | `/api/dashboard/sse` | SSE 实时推送状态 |

### ZooKeeper

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/zookeeper/` | ZooKeeper 页面 |
| GET | `/zookeeper/api/status` | ZK 连接状态 |
| GET | `/zookeeper/api/connections` | ZK 连接列表 |
| POST | `/zookeeper/api/connections` | 新增或更新 ZK 连接 |
| POST | `/zookeeper/api/connections/active` | 切换当前 ZK 连接 |
| DELETE | `/zookeeper/api/connections/{conn_id}` | 删除 ZK 连接 |
| GET | `/zookeeper/api/tree?path=/&depth=3` | 节点树 |
| GET | `/zookeeper/api/node?path=/brokers` | 节点详情 |
| GET | `/zookeeper/api/children?path=/` | 子节点列表 |
| GET | `/zookeeper/api/exists?path=/controller` | 节点是否存在 |
| GET | `/zookeeper/api/servers` | 集群节点信息 |

### Kafka

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/kafka/` | Kafka 页面 |
| GET | `/kafka/api/status` | Kafka 状态 |
| GET | `/kafka/api/connections` | Kafka 连接列表 |
| POST | `/kafka/api/connections` | 新增或更新 Kafka 连接 |
| POST | `/kafka/api/connections/active` | 切换当前 Kafka 连接 |
| DELETE | `/kafka/api/connections/{conn_id}` | 删除 Kafka 连接 |
| GET | `/kafka/api/brokers` | Broker 列表 |
| GET | `/kafka/api/topics` | Topic 列表 |
| GET | `/kafka/api/consumer-groups` | Consumer Group 列表 |
| GET | `/kafka/api/diagnostics` | Kafka 风险诊断摘要 |

### Elasticsearch

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/elasticsearch/` | Elasticsearch 页面 |
| GET | `/elasticsearch/api/status` | ES 状态 |
| GET | `/elasticsearch/api/connections` | ES 连接列表 |
| POST | `/elasticsearch/api/connections` | 新增或更新 ES 连接 |
| POST | `/elasticsearch/api/connections/active` | 切换当前 ES 连接 |
| DELETE | `/elasticsearch/api/connections/{conn_id}` | 删除 ES 连接 |
| GET | `/elasticsearch/api/health` | 集群健康 |
| GET | `/elasticsearch/api/nodes` | 节点列表 |
| GET | `/elasticsearch/api/indices` | 索引列表 |

### 文件浏览器

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/files/` | 文件浏览器页面 |
| GET | `/files/api/list?path=...` | 目录列表 |
| GET | `/files/api/preview?path=...` | 文件预览元信息 |
| GET | `/files/api/image?path=...` | 图片文件预览 |

文件浏览器页面提供目录进入、返回上级、刷新、根目录输入、文件预览和左右分栏拖拽。文件列表展示名称、类型、大小、修改时间；预览区支持文本内容、Python/SQL/Bash/JSON 基础语法高亮，以及 PNG、JPEG、GIF、WebP、AVIF、APNG、SVG 图片内联预览。文本预览受 `file_browser.max_preview_bytes` 限制，超过上限时只返回截断内容并提示。

文件浏览器默认使用 SQLite 配置中的 `file_browser.root` 作为访问根目录，也支持在页面和 API 中通过 `root` query 参数临时切换根目录。后端统一通过 `FileBrowserService` 做真实路径解析和边界校验。

## 关键约束

1. Kafka 监控以 AdminClient 只读诊断为主，ZooKeeper 路径仅用于旧集群兼容和 AdminClient 失败时降级。
2. Elasticsearch 通过 HTTP API 获取数据，连接失败应返回可展示的错误状态。
3. 文件浏览器必须保持只读，不提供编辑、上传、删除、重命名、移动或下载能力。
4. 文件浏览器必须通过真实路径校验限制在选定根目录内，并拒绝绝对路径、`../` 路径穿越和指向根目录外的符号链接。
5. 外部组件异常、超时或未启动时，页面应优雅降级。
