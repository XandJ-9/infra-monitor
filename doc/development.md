# 开发流程

## 环境要求

- Python 3.10+
- uv
- Docker 与 Docker Compose

## Docker 测试环境

项目提供 `docker-compose.yml`，可一键启动 ZooKeeper、Kafka、Elasticsearch 测试环境：

```bash
docker compose up -d
docker compose ps
docker compose logs -f
docker compose down
```

推荐开发时直接使用启动脚本：

```bash
./start-dev.sh
```

脚本会自动启动 Docker Compose 服务、等待健康检查、同步依赖并启动 FastAPI 应用。

## 依赖安装

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync
```

## 依赖导出

项目依赖以 `pyproject.toml` 和 `uv.lock` 为准，`requirements.txt` 用于兼容传统生产部署环境。导出时优先使用 `uv export`，避免手工维护版本号。

曾执行过的三种导出方式如下：

1. 导出当前完整环境依赖，包含默认 dev 依赖和本地 editable 项：

```bash
uv export --format requirements.txt --no-hashes --no-header --output-file requirements.txt
```

该方式会包含 `pytest`、`ruff`、`playwright` 和 `-e .`，适合复现开发环境，不适合作为生产部署文件。

2. 导出生产运行时依赖，排除 dev 依赖和本地项目项，但保留 `# via ...` 来源注释：

```bash
uv export --format requirements.txt --no-dev --no-emit-project --no-hashes --no-header --output-file requirements.txt
```

3. 导出生产运行时依赖，排除 dev 依赖、本地项目项和注释：

```bash
uv export --format requirements.txt --no-dev --no-emit-project --no-hashes --no-header --no-annotate --output-file requirements.txt
```

当前根目录 `requirements.txt` 使用第 3 种方式生成，作为生产环境部署依赖文件。它不应包含 `pytest`、`ruff`、`playwright`、`-e .` 或注释。

## 本地启动

直接访问模式：

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Nginx 反向代理模式，路径前缀为 `/infra-monitor/`：

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --root-path /infra-monitor
```

`--root-path /infra-monitor` 会让 FastAPI 在生成模板链接和静态文件路径时自动带上代理前缀。

## 配置

运行时配置保存在根目录 `config.json`：

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

配置也可以在 Web 界面的“配置”页面修改。

## 测试与检查

测试用例统一放在 `tests/` 目录下，文件命名保持 `test_*.py`。`pyproject.toml` 已通过 `testpaths = ["tests"]` 固定 pytest 的发现目录。

提交前建议运行：

```bash
uv run ruff check .
uv run pytest -q
docker compose config --quiet
```

默认测试不连接外部组件。需要验证 ZooKeeper、Kafka、Elasticsearch 连通性时，先启动 Docker 测试环境，再显式运行 integration 测试：

```bash
docker compose up -d
RUN_CONNECTION_TESTS=1 uv run pytest -q -m integration
```

连接测试也可以作为脚本单独执行：

```bash
RUN_CONNECTION_TESTS=1 uv run python tests/test_connection.py
```

## 开发约定

- 路由层负责 HTTP 参数、模板渲染、JSON 响应和异常映射。
- 服务层负责组件连接、文件访问和外部 API 调用。
- 新增功能优先补充服务层测试，涉及路由时补充 FastAPI 路由测试。
- 外部组件访问必须设置超时，并在失败时返回可展示的错误信息。
- 新增设计文档放入 `doc/`，并在 `doc/README.md` 中登记。
