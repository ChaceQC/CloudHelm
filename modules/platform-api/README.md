# modules/platform-api

CloudHelm 平台 API 服务。M2 使用 FastAPI + SQLAlchemy + Alembic + PostgreSQL 提供真实数据库驱动的 Project、Task、Requirement、Technical Design、AgentRun、ToolCall、Approval 和 Event Timeline API。

## 命令

```powershell
docker compose -f ../../infra/docker-compose.dev.yml up -d postgres
$env:CLOUDHELM_DATABASE_URL='postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm'
uv run alembic upgrade head
uv run pytest
uv run uvicorn cloudhelm_platform_api.main:app --host 127.0.0.1 --port 18080
```

启动后验证：

```powershell
Invoke-RestMethod http://127.0.0.1:18080/health
```

## 环境变量

- `CLOUDHELM_ENV`：运行环境，默认 `development`。
- `CLOUDHELM_VERSION`：服务版本，默认 `0.2.0`。
- `CLOUDHELM_DATABASE_URL`：SQLAlchemy 数据库连接串，本地默认指向 `infra/docker-compose.dev.yml` 的 PostgreSQL。
- `CLOUDHELM_REDIS_URL`：Redis 预留配置；M2 暂不接入生产路径。

## API 分层

```text
src/cloudhelm_platform_api/
  api/            # FastAPI 路由、依赖、错误处理
  schemas/        # Pydantic DTO、枚举、分页和错误响应
  services/       # 业务规则、状态流转、事件写入和事务提交
  repositories/   # SQLAlchemy 查询和持久化
  models/         # SQLAlchemy typed ORM 模型
  db/             # Engine、Session、Declarative Base
```

写操作必须由 service 在同一事务内同时写业务表和 `event_logs`。路由函数不得直接写 SQL。

## 当前边界

M2 提供 AgentRun、ToolCall 和 Approval 的真实记录接口，但不自动执行 Agent、不调用真实 Tool Gateway、不执行 Git/部署/监控操作。`/api/tasks/{task_id}/events/stream` 基于真实 `event_logs` 输出当前事件和 heartbeat，暂不实现长连接实时推送。
