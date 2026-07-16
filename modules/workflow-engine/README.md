# CloudHelm Workflow Engine

`modules/workflow-engine` 是 M7 Ops Hub 的服务端 durable workflow 执行器。
PostgreSQL `workflow_jobs` 始终是业务权威，Redis/Celery 只负责投递
`workflow_job_id`。

当前 M7-2C 只注册无外部副作用的
`release_candidate_reconcile -> release_candidate -> none` handler；Git、
Gitea CI、registry、部署和 Remote Agent operation 尚未注册。

## 进程

```bash
uv sync --frozen

uv run cloudhelm-workflow-engine dispatcher

uv run celery \
  -A cloudhelm_workflow_engine.celery_app:celery_app \
  worker \
  --queues cloudhelm.workflow \
  --pool prefork \
  --concurrency 1 \
  --hostname 'cloudhelm-workflow@%h' \
  --loglevel INFO

uv run cloudhelm-workflow-engine reclaimer
```

Celery 在 WSL/Linux 中运行。Windows 只负责仓库编辑和调用 WSL 测试，不依赖
Docker Desktop。

## 开发连接

```text
CLOUDHELM_DATABASE_URL=postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm
CLOUDHELM_WORKFLOW_BROKER_URL=redis://127.0.0.1:16379/0
```

连接串只通过环境变量注入，不进入日志、EventLog 或 broker message。

## 验证

```powershell
wsl -d Ubuntu-24.04 -u cloudhelm `
  --cd "/mnt/d/graduation project/modules/workflow-engine" -- `
  env UV_PROJECT_ENVIRONMENT=/home/cloudhelm/.cache/cloudhelm/workflow-engine-venv `
  /home/cloudhelm/.local/bin/uv lock --check

wsl -d Ubuntu-24.04 -u cloudhelm `
  --cd "/mnt/d/graduation project/modules/workflow-engine" -- `
  env UV_PROJECT_ENVIRONMENT=/home/cloudhelm/.cache/cloudhelm/workflow-engine-venv `
  /home/cloudhelm/.local/bin/uv run pytest -q -m "not workflow_integration"
```

真实 Redis restart 与 prefork hard-crash 测试需要显式设置：

```powershell
wsl -d Ubuntu-24.04 -u cloudhelm `
  --cd "/mnt/d/graduation project/modules/workflow-engine" -- `
  env UV_PROJECT_ENVIRONMENT=/home/cloudhelm/.cache/cloudhelm/workflow-engine-venv `
  CLOUDHELM_RUN_WORKFLOW_INTEGRATION=1 `
  /home/cloudhelm/.local/bin/uv run pytest -q -m workflow_integration
```

fixture 只允许 `cloudhelm-redis-workflow-test` 与
`redis://127.0.0.1:16380/15`，自动创建并删除 container，不停止或 flush
`cloudhelm-redis-dev`。
