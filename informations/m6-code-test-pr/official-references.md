# M6 本地代码、测试与等价 PR 闭环官方资料

检索日期：2026-07-14
适用阶段：M6 本地 sample repo、Agent 工具循环、Artifact、测试、安全扫描与
本地等价 PR record

## 1. FastAPI 与 HTTP 测试

- [Bigger Applications](https://fastapi.tiangolo.com/tutorial/bigger-applications/)
  - 采用结论：Platform API 继续按 `api`、`schemas`、`services`、
    `repositories` 和 `models` 分层；路由只处理 HTTP DTO、依赖注入和错误映射。
- [Testing](https://fastapi.tiangolo.com/tutorial/testing/)
  - 采用结论：同步 API 黑盒测试继续通过应用测试客户端执行，不绕过真实路由、
    Pydantic 校验和异常处理。
- [Async Tests](https://fastapi.tiangolo.com/advanced/async-tests/)
  - 采用结论：后续需要直接等待异步函数时使用 `httpx` ASGI transport；M6
    当前同步 service 与 PostgreSQL session 不额外引入异步 ORM。
- [Background Tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/)
  - 采用结论：M6 的模型、测试、安全和 Git 步骤仍由一次一个 `run-next`
    同步推进并显式持久化状态，不把重型工作隐藏在请求结束后的
    `BackgroundTasks` 中。
- [Starlette Test Client](https://www.starlette.io/testclient/)
  - 采用结论：测试依赖随 FastAPI/Starlette 兼容范围升级，消除旧
    `TestClient` 对弃用 `httpx` 参数的调用；不在生产代码中增加兼容补丁。

## 2. SQLAlchemy 2.x 与 PostgreSQL

- [Transactions and Connection Management](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html)
  - 采用结论：Agent 最终产物、AgentRun、conversation turn、Task phase 和
    EventLog 使用 `Session.begin_nested()` savepoint 保持原子；外部工具调用
    使用短事务和独立幂等记录，避免长事务包住文件系统或 Git 副作用。
- [PostgreSQL JSON / JSONB](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#sqlalchemy.dialects.postgresql.JSONB)
  - 采用结论：Artifact metadata、changed files、diff stat 和报告结构使用
    JSONB；模型层同时限制 JSON 顶层类型，避免任意标量破坏契约。
- [Defining Constraints and Indexes](https://docs.sqlalchemy.org/en/20/core/constraints.html)
  - 采用结论：数据库使用命名外键、唯一约束、检查约束和按 Task/状态/时间的
    组合索引；服务层仍执行跨表 Task 归属和 artifact 类型校验。

## 3. Alembic

- [Commands: `check`](https://alembic.sqlalchemy.org/en/latest/api/commands.html#alembic.command.check)
  - 采用结论：新增 M6 migration 后执行 downgrade、upgrade 和
    `alembic check`，确认 ORM metadata 没有未生成差异。
- [Autogeneration](https://alembic.sqlalchemy.org/en/latest/autogenerate.html)
  - 采用结论：autogenerate 只用于发现候选差异；最终 migration 人工复核
    表顺序、约束名、索引、注释和 downgrade。

## 4. pytest 与报告

- [`tmp_path`](https://docs.pytest.org/en/stable/how-to/tmp_path.html)
  - 采用结论：Tool Gateway、Platform API 和 sample repo 测试使用独立临时
    workspace/artifact root，不污染真实 sample repo、主仓库或用户目录。
- [JUnit XML](https://docs.pytest.org/en/stable/how-to/output.html#creating-junitxml-format-files)
  - 采用结论：Tester 运行真实 `pytest --junitxml=...`；结构化报告必须同时
    保存命令退出码、JUnit 统计和 stdout/stderr 摘要，解析失败不能伪造成通过。
- [Exit codes](https://docs.pytest.org/en/stable/reference/exit-codes.html)
  - 采用结论：区分测试失败、收集失败、无测试和基础设施错误；只有退出码为
    0 且报告统计一致时才能进入 Reviewer。

## 5. Git

- [`git switch`](https://git-scm.com/docs/git-switch)
  - 采用结论：从受控 base 创建 `codex/` 前缀任务分支；已位于同名分支时按
    幂等成功处理，拒绝静默切换到无关分支。
- [`git diff`](https://git-scm.com/docs/git-diff)
  - 采用结论：收集 `--name-only`、`--stat` 和完整 patch；新文件必须通过
    显式路径纳入 diff/commit 证据。
- [`git commit`](https://git-scm.com/docs/git-commit)
  - 采用结论：只提交服务层计算出的显式文件列表，拒绝 `.`、目录 pathspec
    和未审查文件；提交信息使用中文类型前缀。
- [`git format-patch`](https://git-scm.com/docs/git-format-patch)
  - 采用结论：本地 PR record 保存 base 到 head 的 patch artifact；没有真实
    Git 服务时不构造远端 URL。

## 6. 安全扫描

- [Bandit CLI](https://bandit.readthedocs.io/en/latest/man/bandit.html)
  - 采用结论：Python sample repo 使用递归扫描和 JSON 输出；发现项按严重级别
    进入 SecurityReport，CLI 缺失或 JSON 损坏返回 partial/blocked。
- [pip-audit](https://github.com/pypa/pip-audit)
  - 采用结论：锁定依赖后执行真实依赖审计并保存 JSON；网络或漏洞源不可用时
    记录基础设施阻塞，不写入“零漏洞”。
- [Semgrep CLI reference](https://semgrep.dev/docs/cli-reference/)
  - 采用结论：保留为后续可配置扫描器；M6 默认 Python fixture 使用 Bandit +
    pip-audit，避免为单一示例强制全局安装大型扫描器。
- [Trivy filesystem target](https://trivy.dev/latest/docs/target/filesystem/)
  - 采用结论：保留文件系统/容器扫描接口，M7 镜像产生后再加入默认门禁。

## 7. Docker sandbox

- [Resource constraints](https://docs.docker.com/engine/containers/resource_constraints/)
- [Bind mounts](https://docs.docker.com/engine/storage/bind-mounts/)
- [None network driver](https://docs.docker.com/engine/network/drivers/none/)
- [`docker container run`](https://docs.docker.com/reference/cli/docker/container/run/)

采用结论：

1. M6 延续受控本地 `subprocess`，只允许由服务端绑定的 sample workspace、
   命令数组、正向命令 profile、环境变量白名单、超时、输出上限和进程树清理。
2. 原因是当前 Windows 开发环境的 Docker daemon 不是稳定前置条件，而 M6
   必须允许模块测试和答辩环境复现。
3. 该方案不具备 Docker 的内存、CPU、PID、只读挂载和 `--network none`
   隔离；限制与风险必须显示在 SecurityReport 和文档中。
4. `Dockerfile` / Compose 仍作为 sample repo 可复现运行入口；M7 前再把
   Docker 一次性 sandbox 设为可选/默认执行器。

## 8. OpenAI Responses API

- [Function calling](https://developers.openai.com/api/docs/guides/function-calling)
  - 采用结论：模型 `function_call` 与 Tool Gateway 结果
    `function_call_output` 使用同一 `call_id`；Platform API 执行工具并把
    脱敏结果按顺序回放。
- [Streaming responses](https://developers.openai.com/api/docs/guides/streaming-responses)
  - 采用结论：继续使用 HTTP SSE；允许一次响应只包含 tool call，不强制每次
    都有最终 `output_text`。
- [Prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)
  - 采用结论：Base Instructions、稳定扁平 `text.format`、稳定完整 tools
    清单和 root history 保持一致；缓存命中只读取 usage 中的真实 cached token。
- [Reasoning models](https://developers.openai.com/api/docs/guides/reasoning)
  - 采用结论：保存并回放供应商返回的 reasoning item 和
    `encrypted_content`，不解密、不展示、不伪造。

## 9. Codex 显式多 Agent

- [Codex manual](https://developers.openai.com/codex/codex-manual.md)
- [Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents.md)
- [openai/codex](https://github.com/openai/codex)

采用结论：

1. 普通 Requirement、Architect、Planner、Scaffold、Coder、Tester、
   Reviewer、Security 角色共享一个 Task root conversation。
2. 只在明确的 spawn 请求、深度和并发限制允许时创建 child conversation。
3. read-heavy 探索适合并行子 Agent；写入同一 workspace 的工作保持串行，避免
   diff、测试和 Git 状态互相覆盖。
4. CloudHelm 自身使用 `max_depth=1`、`max_active_children=6`；Codex CLI 的
   thread/subagent 模型只作为协作参考，不把 active-child 计数描述为官方并发
   thread 配置的精确等价。递归委派需显式调整并记录风险。
5. child 只把不超过 4000 字符的脱敏最终通知回传父会话，不复制 child
   reasoning、工具调用、工具结果或原始日志。
6. child 权限不得高于父线程；每次工具调用继续由 Tool Gateway 按 role、资源
   版本和审批状态重新判定。
