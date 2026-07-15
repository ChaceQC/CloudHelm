# Desktop、Ops Hub 与业务项目存储边界

> 目的：回答桌面安装是否应依赖 Docker PostgreSQL，并冻结三类数据所有权。
> 结论：PostgreSQL 保留给常在线 Ops Hub；Desktop 使用独立 SQLite；业务项目
> 自行拥有业务数据库。

## 1. 为什么不把整个平台迁移到 SQLite

现有 Platform API 已依赖：

- PostgreSQL JSONB。
- 部分唯一索引。
- UUID 与复杂 CHECK。
- `SELECT ... FOR UPDATE`、`SKIP LOCKED`。
- 多 worker WorkflowJob claim、lease、heartbeat 和并发幂等。

这些是常在线、多客户端、多 worker 控制平面的数据库语义。整体改为 SQLite 会
改变审批、任务、事件和异步工作流的一致性边界，因此不作为桌面产品化方案。

## 2. 为什么 Desktop 不应依赖 Docker PostgreSQL

Windows setup `.exe` 和 Linux AppImage/`.deb` 的最终用户安装目标是：

- 安装后直接启动 CloudHelm Desktop。
- 不要求安装 Docker Desktop、Docker Engine、PostgreSQL、Redis 或 Python。
- App 可以退出、断网和升级，不影响远端 Agents 运维系统持续运行。

因此 Docker Compose PostgreSQL 只属于：

1. 仓库贡献者的本地开发/集成测试 profile。
2. Linux Ops Hub 的 demo/self-hosted deployment profile。
3. 后续生产扩展中的独立或托管 PostgreSQL。

它不属于桌面安装器。

## 3. Desktop SQLite

Desktop SQLite 是非权威、可重建的本机 store，建议包含：

```text
server_profiles
ui_preferences
recent_projects
offline_drafts
event_cursors
cached_read_models
local_runtime_registry
```

约束：

- 每个 `ops_hub_id + user_id + stream_kind + scope_id` 保存独立
  `last_event_sequence`，避免不同用户或权限范围共用游标。
- cached read model 必须保存 `fetched_at`、`server_version` 和
  `aggregate_version`。
- 缓存过期或 schema 不兼容时清空并重新拉取，不尝试直接修改服务端数据库。
- 仅草稿和可重新获取的数据进入 SQLite。
- 审批、部署、取消、回滚和远端命令不在重连时自动重放。
- access token、refresh token、device private key 和真实业务 secret 不写入
  SQLite，使用 OS credential store/Stronghold。

Desktop SQLite 使用独立的 `desktop_store_schema_version` 和 migration 链，不与
Alembic revision 共用。

## 4. Ops Hub PostgreSQL

以下数据只以服务端 PostgreSQL 为权威：

- Project、Task、Requirement、Design、Plan。
- AgentConversation、AgentRun、ToolCall、ApprovalRequest。
- Artifact metadata、PullRequestRecord。
- EventLog、WorkflowJob、幂等键、lease、heartbeat。
- User、Device、UserSession、refresh token rotation history、Invitation、Role、
  Permission、RoleBinding 和 permission version。
- RepositoryBinding、ReleaseCandidate、CIRun。
- Environment、RemoteTarget、Deployment、ServiceInstance。
- 监控/告警/Incident 与完整审计。

Desktop、Local Runtime 和 Remote Agent 均通过版本化 API 读写，不直连数据库。

## 5. 业务项目数据库

Agent 生成的项目可以选择 SQLite、PostgreSQL、MySQL、文件存储或其他符合需求的
方案，但必须：

- 在项目自己的 README、配置、migration 和备份说明中自包含。
- 使用独立 database/volume/credential。
- 不连接或复用 CloudHelm Ops Hub PostgreSQL schema。
- 独立部署时无需 CloudHelm 提供数据库连接。
- 受管部署时只通过项目声明的逻辑环境变量接收配置。

CloudHelm 负责部署和运维证据，不拥有业务项目领域数据。

## 6. 数据同步不是数据库复制

Desktop 与 Ops Hub 的同步固定为 API + EventLog：

```text
REST snapshot
  + sequence-based incremental events
  + SSE live tail
```

禁止：

- 复制 PostgreSQL 数据文件到 Desktop。
- 让 SQLite 和 PostgreSQL 做双主同步。
- Desktop 直接执行远端 SQL。
- 业务项目读取 CloudHelm 内部表。

## 7. 备份和恢复

|数据域|备份策略|
|---|---|
|Desktop SQLite|可选用户配置导出；缓存可清空重建；凭据单独管理|
|Ops Hub PostgreSQL|定时逻辑/物理备份、恢复演练、RPO/RTO 记录|
|Redis|非权威队列；重启后由 PostgreSQL WorkflowJob 补投|
|Artifact store|按 digest 校验并纳入备份/保留策略|
|业务项目数据|由项目自己的运行与部署文档负责|

## 8. 当前迁移影响

- 现有 Alembic migration 继续属于 Ops Hub PostgreSQL。
- 暂停中的 `20260716_0008` migration/ORM 草稿不改写为 SQLite。
- 后续 Desktop SQLite schema 单独规划，不能把现有 ORM 直接复制到桌面。
- 当前本地 PostgreSQL 开发库未来迁移到远端 Ops Hub 时，应使用一次性导出/
  导入或重新初始化流程，不通过 Desktop 数据文件搬运。
