# P1 临时数据库与受控初始化

本目录仅提供 WSL `Ubuntu-24.04` 的开发验证夹具，不是 s2413 安装或生产部署配置。PostgreSQL 固定为 16.13 及 Compose 中的镜像摘要，数据和 PostgreSQL 临时目录位于 tmpfs。夹具显式连接本机 `/var/run/docker.sock`，默认占用 `127.0.0.1:55433`；端口冲突直接拒绝，不复用现有实例。

在仓库根目录用当前锁定环境运行数据库窄检查：

```bash
uv run --locked --offline --no-sync python -B -m scripts.p1.check_database
```

后续集成可以共用同一个真实实例：

```python
from scripts.p1.database_fixture import database_fixture

with database_fixture() as fixture:
    api_settings = fixture.settings("api")
    worker_settings = fixture.settings("worker")
    maintenance_settings = fixture.settings("migrator")
    # 子进程只传 fixture.environment_for(role) 返回的 _URL_FILE 引用。
    # 不打印 settings.url、不展开受保护文件，也不把连接串写入命令参数。
```

每个实例使用唯一 Compose 项目和独立 Linux 运行目录，随机凭据文件为 `0600`、目录为 `0700`，不进入仓库。上下文退出时仅清理该实例的容器、网络和运行目录；无法确认容器停止时保留私有恢复材料并报错，不执行全局 prune。

`database.settings.load_database_settings(role)` 支持 `api`、`worker`、`migrator`，分别读取 `CLOUDHELM_API_DATABASE_URL`、`CLOUDHELM_WORKER_DATABASE_URL`、`CLOUDHELM_MIGRATOR_DATABASE_URL` 或对应的 `_FILE` 变量；每个角色必须且只能配置一个来源。文件使用 UTF-8，配置只在显式调用时读取，异常不回显原值。

维护角色使用 `create_engine_from_settings(settings, purpose="maintenance")`。既有受控实例可通过以下入口初始化或查询：

```bash
python -B -m database.manage initialize --operation-id initialization-001
python -B -m database.manage status
```

入口要求独立的 `cloudhelm_migrator` 身份和已有角色配置。它在平台排他维护锁下执行固定业务 Alembic 首迁移与公开 `DBOS.migrate()`，不启动 worker。初始化中断后，`status` 返回原初始化身份，使用相同 `--operation-id` 续接；来源不明的既有 schema、不同基线及跨 SDK 升级保持拒绝。业务修订为 `0001_p1_1`，应用源码/工作流基线为 `0.1.0`，DBOS SDK 为 `3.2.0`；这不是发布或 tag。未通过公开接口取得的精确 DBOS 系统 schema 数字保持 `null`。

API 与 worker 启动前在短事务内调用 `database.readiness.assert_runtime_ready(connection, role=...)`。维护业务命令调用 `require_maintenance_role(connection)` 和 `assert_schema_ready(connection)`。普通 worker 还必须使用 `run_migrations=False`，由 SDK 校验系统迁移；本夹具不创建业务 worker 注册入口。

|数据库角色|连接上限|使用范围|
|---|---:|---|
|`cloudhelm_api`|6|最多两个 API 进程，各自普通池 2、控制池 1|
|`cloudhelm_worker`|8|单 worker 业务池 2+1、DBOS 池 4、池外监听 1|
|`cloudhelm_migrator`|4|维护池 2；独立 SDK 迁移临时连接计入同一上限|

PostgreSQL `max_connections=32` 为夹具配置，不是容量结论。运行角色无 DDL、创建角色或 schema 所有权。命令、事件、审计、完成报告和不可变事实仅允许读取/追加；必要的业务变化按表/列开放更新，维护基线仅由维护身份写入。SDK 默认系统表权限在初始化后收窄，禁止运行角色修改迁移记录或截断系统表。

业务迁移是静态快照，不导入可变化的领域元数据。后续结构变更使用新的线性 revision；首迁移不提供 downgrade，也不开放备份恢复、跨 SDK 系统升级或未知安装的自动修复。
