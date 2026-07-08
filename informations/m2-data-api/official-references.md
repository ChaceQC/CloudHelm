# M2 数据模型、API 与事件底座官方资料归档

检索日期：2026-07-08

本文件只保存官方链接、采用结论和少量必要说明，不保存第三方文档全文、
真实密钥、Cookie、账号、服务器地址或许可证不明代码。

## FastAPI

- 官方链接：
  - <https://fastapi.tiangolo.com/tutorial/dependencies/>
  - <https://fastapi.tiangolo.com/tutorial/bigger-applications/>
  - <https://fastapi.tiangolo.com/tutorial/handling-errors/>
  - <https://fastapi.tiangolo.com/how-to/extending-openapi/>
- 适用子任务：API 路由拆分、依赖注入、统一错误响应、OpenAPI 生成。
- 采用结论：
  - 使用 `APIRouter` 按 Project、Task、Requirement、Design、AgentRun、ToolCall、Approval、Event 分组。
  - 使用 `Depends` 注入 SQLAlchemy `Session`，路由不直接写数据库访问逻辑。
  - 使用异常处理器把业务错误、HTTP 错误和请求校验错误统一为 `code/message/detail/trace_id`。

## SQLAlchemy 2.x

- 官方链接：
  - <https://docs.sqlalchemy.org/en/20/orm/quickstart.html>
  - <https://docs.sqlalchemy.org/en/20/orm/session_basics.html>
  - <https://docs.sqlalchemy.org/en/20/orm/declarative_tables.html>
- 适用子任务：typed ORM、Session 生命周期、Repository 模式、事务提交。
- 采用结论：
  - 使用 SQLAlchemy 2.x `Mapped` / `mapped_column` typed ORM。
  - 每个请求使用短生命周期 `Session`，写操作由 service 在同一事务内提交业务记录和 `event_logs`。
  - Repository 只处理数据库访问，状态流转和事件写入放在 service 层。

## Alembic

- 官方链接：
  - <https://alembic.sqlalchemy.org/en/latest/tutorial.html>
  - <https://alembic.sqlalchemy.org/en/latest/autogenerate.html>
- 适用子任务：迁移目录、迁移脚本、`upgrade head`。
- 采用结论：
  - 在 `modules/platform-api/migrations/` 保存迁移环境和版本文件。
  - 迁移连接串来自 `CLOUDHELM_DATABASE_URL`，不硬编码真实数据库地址。
  - 当前首个迁移为手写迁移，避免 autogenerate 在新项目中漏掉注释、索引和 JSONB 细节。

## PostgreSQL

- 官方链接：
  - <https://www.postgresql.org/docs/current/datatype-uuid.html>
  - <https://www.postgresql.org/docs/current/datatype-json.html>
  - <https://www.postgresql.org/docs/current/datatype-datetime.html>
  - <https://www.postgresql.org/docs/current/indexes.html>
- 适用子任务：UUID、JSONB、TIMESTAMPTZ、索引设计。
- 采用结论：
  - 主键使用 PostgreSQL UUID 类型，由应用层生成 UUID，避免依赖额外扩展。
  - 结构化内容使用 JSONB，例如 `acceptance_criteria_json`、`constraints_json`、`arguments_json`。
  - 时间字段使用 `TIMESTAMPTZ`，应用层统一使用 timezone-aware UTC 时间。
  - 为 `tasks(project_id,status)`、`event_logs(task_id,created_at)` 等控制台常用查询建立索引。

## Pydantic v2

- 官方链接：
  - <https://docs.pydantic.dev/latest/concepts/fields/>
  - <https://docs.pydantic.dev/latest/concepts/models/>
  - <https://docs.pydantic.dev/latest/concepts/json_schema/>
- 适用子任务：请求/响应 DTO、枚举、字段说明、OpenAPI schema。
- 采用结论：
  - DTO 使用 Pydantic v2 `BaseModel` 和 `Field` 描述字段、约束和说明。
  - 读模型启用 `from_attributes=True`，从 SQLAlchemy ORM 对象安全转换。
  - 枚举集中放在 `schemas/common.py`，保证 API 响应与设计文档状态值一致。

## pytest 与数据库测试

- 官方链接：
  - <https://docs.pytest.org/en/stable/how-to/fixtures.html>
  - <https://fastapi.tiangolo.com/tutorial/testing/>
- 适用子任务：测试夹具、FastAPI TestClient、数据库重置。
- 采用结论：
  - 使用 pytest fixture 配置测试数据库、执行 Alembic 迁移并在每个测试前清空业务表。
  - 测试通过真实 API 和 PostgreSQL 数据库验证写入、状态变更和事件副作用。

## SSE / StreamingResponse

- 官方链接：
  - <https://www.starlette.io/responses/#streamingresponse>
- 适用子任务：`/api/tasks/{task_id}/events/stream`。
- 采用结论：
  - M2 采用 `StreamingResponse` 返回真实 `event_logs` 编码后的 SSE 数据。
  - M2 不实现长连接实时推送；控制台可在 M3 通过重连或轮询刷新，真实推送留到后续编排/事件总线阶段。
