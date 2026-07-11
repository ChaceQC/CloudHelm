# modules/platform-api

CloudHelm 平台 API 服务。M5 使用 FastAPI + SQLAlchemy + Alembic + PostgreSQL 提供真实数据库驱动的 Project、Task、Requirement、Technical Design、DevelopmentPlan、AgentRun、ToolCall、Approval、Event Timeline、Orchestration API 和 Tool Gateway 调用入口。

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
- `CLOUDHELM_VERSION`：服务版本，默认 `0.4.3`。
- `CLOUDHELM_AGENT_PROVIDER`：M4 Agent provider，默认 `local_structured`。
- `CLOUDHELM_TOOL_RATE_LIMIT_CALLS`：单实例窗口内每个任务或 AgentRun 的最大工具调用次数，默认 60。
- `CLOUDHELM_TOOL_RATE_LIMIT_WINDOW_SECONDS`：工具调用滑动窗口秒数，默认 60。
- `CLOUDHELM_TOOL_WORKSPACE_ROOTS`：允许 Repo、Sandbox、Git 工具访问的根目录 JSON 数组；默认 `[]`，即拒绝工作区工具。
- `CLOUDHELM_LLM_PROVIDER`、`CLOUDHELM_LLM_MODEL`、`CLOUDHELM_LLM_API_BASE`、`CLOUDHELM_LLM_API_KEY`：切换 `openai_compatible` provider 时使用；真实 Key 不得提交。
- `CLOUDHELM_LLM_API_MODE`：默认 `responses`；旧兼容服务可改为 `chat_completions`。
- `CLOUDHELM_LLM_REASONING_EFFORT`：默认 `xhigh`，用于当前 `gpt-5.6-sol` 真实流程。
- `CLOUDHELM_LLM_REASONING_SUMMARY`：默认 `auto`。
- `CLOUDHELM_LLM_REASONING_CONTEXT`：默认 `all_turns`。
- `CLOUDHELM_LLM_MAX_OUTPUT_TOKENS`：默认 `32768`，同时为 reasoning token 和最终结构化输出预留空间。
- `CLOUDHELM_LLM_TIMEOUT_SECONDS`：单次模型 HTTP 请求超时，默认 120 秒。
- `CLOUDHELM_LLM_MAX_ATTEMPTS`：模型请求或结构化响应失败时的总尝试次数，默认 3。
- `CLOUDHELM_LLM_RETRY_BACKOFF_SECONDS`：首次重试退避秒数，后续按 2 的幂增长，默认 1。
- `CLOUDHELM_LLM_EXPLICIT_CACHE_BREAKPOINT`：默认 `false`；仅兼容端点明确支持
  Responses `prompt_cache_options` / `prompt_cache_breakpoint` 时启用。
- `CLOUDHELM_LLM_USER_AGENT` / `CLOUDHELM_LLM_ORIGINATOR`：Codex 兼容请求头。
- `CLOUDHELM_AGENT_MAX_SUBAGENT_DEPTH` / `CLOUDHELM_AGENT_MAX_SUBAGENT_THREADS`：
  显式 child conversation 的深度和并发上限。
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

写操作必须由 service 同步写业务表和 `event_logs`。普通数据库写入使用同一事务；Tool Gateway 为避免数据库事务跨越文件/Git/进程副作用，先用短事务原子抢占幂等键，再在第二事务写终态和事件。路由函数不得直接写 SQL。

## Task Agent conversation

- 每个 Task 只有一个 root `agent_conversations` 记录；Requirement、Architect、
  Planner 和后续普通角色共享该 conversation。
- 每次成功 turn 在业务产物、AgentRun、conversation 和 EventLog 的同一事务中
  保存完整可重放 ResponseItem；每个 Agent 步骤使用 savepoint，晚期持久化失败
  会回滚业务产物和 conversation turn，再单独提交失败 AgentRun。
- `agent_runs` 同时记录总量和 `provider_requests` 逐请求 usage。`cache_hit`
  只能由供应商 `cached_input_tokens > 0` 推导，结构化修复重试不会被隐藏。
- 只有 `AgentConversationService.spawn_subagent` 能创建 child，要求 running
  父 AgentRun、明确 objective/expected result，并保存 parent、role、depth、
  fork mode 和生命周期。

## M5 Tool Gateway 接口

```text
GET  /api/tool-gateway/tools
POST /api/tasks/{task_id}/tool-gateway/call
```

低风险工具由 `modules/tool-gateway` 统一校验并执行，调用结果写入
`tool_calls` 和 `event_logs`。L3/L4 或工具声明要求审批时，只创建
`approval_requests`，ToolCall 状态为 `waiting_approval`，不执行 handler。
Agent 调用必须绑定属于当前任务且状态为 `running` 的 AgentRun，Task 也必须为
`running`。工具参数落库前会递归脱敏，文件正文仅保存长度和 SHA-256；
Tool Gateway 返回的主体、风险、幂等键、参数 hash 和终态保存在
`tool_calls.audit_json`。

## 当前边界

M5 提供本地 Tool Gateway、Repo Tool、Sandbox Tool 和 Git Tool，并以应用级共享 Gateway 执行单实例调用限流。Sandbox Tool 暂用平台 allowlist 内的本地目录 + `subprocess` 超时，不接 Docker；Repo/Git 仅执行已注册的本地低风险动作，不执行 push、远端 SSH、部署或监控操作。`/api/tasks/{task_id}/events/stream` 基于真实 `event_logs` 回放当前事件，暂不实现生产级事件总线推送。
