# Kafka 监控能力设计

## 背景

当前 Kafka 模块主要通过 ZooKeeper 元数据读取 broker、topic 和旧版 consumer group 信息。这种方式适合早期 Kafka 集群的基础诊断，但对 Kafka 2.x/3.x、KRaft 模式、新版 consumer group、真实 lag、ISR 和 leader 等现代运维信息支持不足。

Kafka 在基础设施中通常承担消息队列、数据缓冲和实时流管道角色。监控目标不应只停留在进程存活或 topic 数量，而应帮助运维快速判断：

- 集群是否可用。
- 生产者是否还能正常写入。
- 消费者是否还能正常读取。
- 数据副本是否安全。
- 消费延迟是否失控。
- 容量和流量是否存在趋势性风险。

## 核心关注面

### 集群健康

集群健康用于回答“Kafka 本身是否正常工作”。

基础能力：

- Broker 存活数量和离线 broker。
- Controller 当前节点和 controller 切换情况。
- Kafka 版本、集群 ID、部署模式。
- Bootstrap servers 可达性。
- Metadata 获取状态。
- 认证失败、连接超时、部分 broker 不可达等错误分类。

页面展示应避免只给出 `connected=true`，需要区分不可达、认证失败、元数据异常、部分节点异常等状态。

### Topic 与分区健康

Topic 和 partition 是 Kafka 运维的核心对象。

基础能力：

- Topic 列表、搜索、排序和过滤。
- Partition 数量和副本数。
- 每个 partition 的 leader、replicas、ISR。
- Under-replicated partitions。
- Offline partitions。
- Leader 在 broker 上的分布。
- 副本在 broker 上的分布。
- Topic 配置摘要，例如 `retention.ms`、`cleanup.policy`、`min.insync.replicas`、`segment.bytes`。

重点风险：

- Offline partition 表示分区不可用，生产或消费可能失败。
- Under-replicated partition 表示副本未同步完成，数据可靠性下降。
- ISR 长期小于副本数，可能影响 `acks=all` 写入。
- Leader 分布不均会导致 broker 压力倾斜。
- 单副本 topic 在生产环境中应作为高风险提示。

### Consumer Group 与消费延迟

Consumer lag 是 Kafka 运维最常见的问题入口。

基础能力：

- Consumer group 列表。
- Group 状态，例如 Stable、Empty、Dead、PreparingRebalance、CompletingRebalance。
- Group 成员数。
- 订阅 topic。
- 每个 topic/partition 的 current offset、log end offset、lag。
- Total lag。
- 最近 offset commit 时间。
- Rebalance 状态和频率。

Lag 应支持按以下路径下钻：

```text
group -> topic -> partition -> current_offset / end_offset / lag
```

总 lag 只能说明存在积压，partition 级 lag 才能帮助判断是单分区卡住、消费能力不足，还是分区分配不均。

### 吞吐与延迟

Kafka 是数据管道，吞吐和请求延迟决定它是否还能承载当前业务流量。

建议指标：

- Messages in/sec。
- Bytes in/sec。
- Bytes out/sec。
- Produce request rate。
- Fetch request rate。
- Produce/fetch latency。
- Failed produce/fetch request。
- Network request queue。
- Request handler idle ratio。

AdminClient 更适合元数据和 group lag；吞吐、请求延迟和队列类指标通常需要接入 JMX Exporter、Prometheus 或已有监控系统。项目设计上应预留外部指标来源入口。

### 存储与容量

Kafka 的容量风险主要集中在 broker 磁盘和 topic 增长速度。

基础能力：

- Broker 磁盘使用率。
- Kafka log dir 使用情况。
- 每个 topic 的数据大小。
- Topic 增长速率。
- Retention 配置。
- Log segment 数量。
- Offline log dirs。
- 剩余可用空间预估。

风险提示：

- Broker 磁盘使用率过高。
- Topic 增长速度异常。
- 单 topic 占用空间过大。
- Broker 间磁盘使用不均。
- Retention 配置与数据增长速度不匹配。

### 数据可靠性

Kafka 的风险经常不是“服务不可用”，而是“服务仍可用但副本安全性下降”。

基础能力：

- Topic replication factor。
- `min.insync.replicas`。
- ISR 是否长期不足。
- `unclean.leader.election.enable` 是否开启。
- Internal topic 健康状态，尤其是 `__consumer_offsets`。
- Topic 是否单副本。

生产环境中应优先提示：

- 单副本 topic。
- ISR 不足。
- Under-replicated partition。
- Offline partition。
- 允许 unclean leader election 的 topic 或 broker 配置。

### Rebalance 与消费稳定性

频繁 rebalance 会造成消费暂停、延迟升高和实时任务抖动。

建议能力：

- Group 状态变化。
- Group member 数变化。
- Rebalance 频率。
- 长期处于 PreparingRebalance 或 CompletingRebalance 的 group。
- Partition assignment 分布。
- 消费成员是否异常频繁上下线。

### 连接管理与只读诊断

Kafka 管理操作风险较高，初期应以只读诊断为主。

基础管理能力：

- 查看 topic 配置。
- 查看 broker 配置摘要。
- 查看 consumer group 明细。
- 导出 topic、partition、consumer group 诊断信息。
- 标记重点 topic 或 group。
- 搜索、排序和过滤。

谨慎开放的操作：

- 创建 topic。
- 修改 topic retention。
- 扩容 partition。
- 修改 topic 配置。
- 删除 topic。

这些写操作需要权限控制、审计日志和二次确认，不建议在早期版本直接开放。

## 告警建议

Kafka 告警应支持阈值和持续时间，避免瞬时波动造成噪声。

基础告警：

- Broker 存活数量低于期望值。
- Offline partition 数量大于 0。
- Under-replicated partition 数量大于 0 且持续超过阈值。
- Consumer group total lag 超过阈值。
- Consumer group lag 持续增长。
- Group 长期处于异常状态。
- Broker 磁盘使用率超过阈值。
- Controller 频繁切换。
- Produce/fetch 请求失败率升高。
- Topic 单副本。
- ISR 长期不足。

## 项目落地路径

### 第一阶段：现代 Kafka 基础信息

目标是从 ZooKeeper 元数据读取升级到 Kafka AdminClient 为主。

- 增加 Kafka bootstrap servers 配置。
- 支持 Kafka 认证和超时配置。
- 获取 broker 列表。
- 获取 topic 列表。
- 获取 partition leader、replicas、ISR。
- 识别 under-replicated 和 offline partitions。
- 获取 consumer group 列表。
- 获取 group offset、log end offset 和 lag。

### 第二阶段：运维诊断视图

目标是让用户快速定位风险点。

- Topic 详情页。
- Consumer group 详情页。
- Broker 详情页。
- 风险提示：单副本、ISR 不足、lag 高、leader 倾斜。
- 搜索、排序、过滤。
- 诊断信息导出。

### 第三阶段：指标、趋势与告警

目标是从实时查看扩展到持续观测。

- 接入 JMX Exporter、Prometheus 或兼容指标源。
- 展示 lag 趋势。
- 展示 broker/topic 吞吐趋势。
- 展示磁盘容量趋势。
- 增加 Kafka 告警规则。
- 支持告警触发、恢复、静默和历史记录。

## 设计原则

- AdminClient 优先，ZooKeeper 仅作为旧集群兼容路径。
- 只读诊断优先，写操作后置并增加权限与审计。
- 页面围绕“能不能写、能不能读、数据安不安全、延迟有没有失控”组织。
- 元数据、运行指标和历史趋势分层建设，避免一次性引入过多复杂度。
- 错误状态要可解释，便于区分连接、认证、元数据和集群健康问题。
