# Infra Monitor 开发计划方案

## 背景与目标

Infra Monitor 当前是一个轻量级 FastAPI 运维面板，已覆盖 ZooKeeper、Kafka、Elasticsearch 的基础状态展示、元数据查看和运行时配置管理。后续扩展目标是把它从“本地/内网诊断工具”逐步升级为“可部署、可观测、可告警、可扩展”的基础设施监控平台。

## 当前基线

- 后端：FastAPI + Jinja2，按 `routers` 和 `services` 分层。
- ZooKeeper：通过 `kazoo` 维护单例连接，支持状态、节点、树浏览。
- Kafka：通过 ZooKeeper 元数据读取 broker、topic、旧版 consumer group 信息。
- Elasticsearch：通过 HTTP API 获取集群健康、节点、索引信息。
- 前端：Bootstrap + Jinja2 模板，局部使用 fetch 查询 API。
- 配置：`config.json` 持久化，Web 配置页可修改 ZK/ES 地址和刷新间隔。
- 测试：已有 lint、普通 pytest 基线；外部组件连通性测试默认跳过。

## 优先级路线

### P0：稳定性与基础质量

目标：修正现有功能的可靠性问题，让项目可以稳定开发、测试、部署。

- 修正配置文件路径，确保读取和保存仓库根目录下的 `config.json`。
- 增加配置模块测试：路径、默认值合并、非法 JSON fallback、保存格式。
- 完成首页刷新逻辑：让 `refreshDashboard()` 真实更新三张状态卡，或改用 SSE。
- 给关键 API 增加超时保护，避免外部组件异常拖垮请求。
- 修复 `start-dev.sh` 的 Bash 兼容问题，并统一使用 `docker compose`。
- 将外部组件连通性测试明确标记为 integration，并在文档中说明运行方式。
- 补充 CI 建议命令：`uv run ruff check .`、`uv run pytest -q`。

验收标准：

- 普通测试不依赖 Docker 或外部组件。
- 配置页保存后，服务读取的是项目内 `config.json`。
- 首页点击刷新后页面数据可见更新。

### P1：Kafka 监控增强

目标：从“通过 ZK 看 Kafka 元数据”升级到“直接理解现代 Kafka 集群”。

- 引入 Kafka AdminClient，支持非 ZooKeeper/KRaft 模式。
- 获取 broker、topic、partition、replica、ISR、leader 信息。
- 支持 consumer group 列表、成员、状态、订阅 topic、真实 lag。
- 增加 topic 详情页：分区分布、副本健康、消息量指标入口。
- 配置页增加 Kafka bootstrap servers、认证方式、超时参数。

验收标准：

- Kafka 2.x/3.x 常见部署方式均可读取基础信息。
- Consumer lag 不再使用旧版 ZK offset 近似值。

### P2：Elasticsearch 监控增强

目标：提升 ES 运维诊断能力。

- 支持 basic auth、API key、TLS 证书配置。
- 增加索引搜索、排序、过滤、分页。
- 增加 shard 分布视图：未分配分片、主副本分布、节点承载。
- 增加节点资源视图：heap、RAM、CPU、disk、load。
- 增加常见风险提示：red/yellow、unassigned shards、磁盘水位、heap 过高。

验收标准：

- 可以在生产 ES 的安全配置下连接。
- 能快速定位索引和 shard 层面的健康问题。

### P3：告警与历史趋势

目标：从实时面板扩展到持续观测。

- 增加后台采集任务，按配置周期采集组件状态。
- 使用 SQLite 作为本地默认存储，预留 Postgres/MySQL 扩展。
- 增加趋势图：组件可用性、ES shard、Kafka lag、broker 数、topic 数。
- 增加告警规则配置：阈值、持续时间、静默窗口、恢复通知。
- 支持 Webhook、邮件、企业 IM 通知。

验收标准：

- 面板能展示最近 24 小时/7 天趋势。
- 告警有触发、恢复、静默和历史记录。

### P4：多环境与权限

目标：让工具适合团队共享使用。

- 支持多环境配置：dev、test、prod 或自定义环境。
- 配置页支持环境切换、复制、导入导出。
- 增加登录认证和只读/管理员权限。
- 对配置保存、敏感字段、操作日志做审计。
- 支持以环境变量覆盖配置，方便容器化部署。

验收标准：

- 同一实例可管理多套基础设施。
- 非管理员不能修改连接配置或告警规则。

### P5：部署与工程化

目标：降低部署和维护成本。

- 增加 Dockerfile 和生产 compose 示例。
- 静态资源本地化，避免内网环境依赖 CDN。
- 增加 `/healthz`、`/readyz`、版本信息接口。
- 引入结构化日志和请求 ID。
- 增加基础 CI 工作流和发布说明模板。

验收标准：

- 新环境可以通过 Docker 一键启动。
- 部署后能被平台健康检查和日志系统接入。

## 建议迭代顺序

1. 先完成 P0，稳定现有功能和测试基线。
2. 再做 P1 Kafka，因为当前 Kafka 能力边界最大，且对现代 Kafka 支持不足。
3. 接着做 P2 ES，提升实际排障价值。
4. P3 告警和趋势作为第二阶段主线，开始引入持久化。
5. P4/P5 面向团队化和生产化部署，可按实际使用场景拆分推进。

## 近期任务清单

- [ ] 为配置模块补充完整单元测试。
- [ ] 修复首页 `refreshDashboard()` DOM 更新。
- [ ] 抽象组件状态采集接口，为 ZK/Kafka/ES 统一返回结构。
- [ ] 为服务层增加 mock 测试，覆盖连接失败、超时、异常返回。
- [ ] 增加 Kafka AdminClient 技术选型验证。
- [ ] 增加 ES 认证配置字段和连接验证按钮。
- [ ] 准备 Dockerfile 和生产部署说明。

## 风险与注意事项

- Kafka 新版 consumer group 信息不能可靠地从 ZooKeeper 获取，需要 AdminClient。
- 配置页涉及连接地址和未来凭据，生产使用前必须加认证和权限。
- 采集历史趋势后会引入存储、迁移、保留策略，需要提前控制复杂度。
- 面板需要避免一个组件连接失败拖慢所有页面，超时和并发隔离要持续加强。
