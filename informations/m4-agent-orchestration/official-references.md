# M4 Agent 编排与结构化输出资料归档

检索日期：2026-07-08；补充检索：2026-07-10
适用阶段：M4 Agent 编排与规格化闭环

## 1. LangGraph / 状态机实践

- 官方资料：[LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)
- 采用结论：M4 暂不引入 LangGraph 运行时依赖，先用显式状态机覆盖 `Created -> RequirementClarifying -> Designing -> WaitingDesignApproval -> Planning`，降低毕业设计 MVP 的依赖和调试成本。
- 取舍：保留 StateGraph / checkpoint / human-in-the-loop 思路，用 `modules/orchestrator` 的纯状态机和 Platform API 事务事件实现最小闭环；M5 以后如引入真实异步图执行，再补充迁移计划。

## 2. Pydantic 2 JSON Schema 与 validation

- 官方资料：[Pydantic JSON Schema](https://docs.pydantic.dev/latest/concepts/json_schema/)、[Pydantic Models](https://docs.pydantic.dev/latest/concepts/models/)
- 采用结论：Requirement / Architect / Planner 输出先定义 Pydantic model，再导出 `packages/shared-contracts/schemas/agents/*.schema.json`。
- 取舍：Platform API 入库前再次 `model_validate`，禁止把未校验自然语言直接写入核心业务字段。

## 3. OpenAI / 兼容 LLM structured outputs

- 官方资料：[OpenAI Structured Outputs](https://platform.openai.com/docs/guides/structured-outputs)
- 补充官方资料：[Reasoning models](https://developers.openai.com/api/docs/guides/reasoning)、[Responses API migration](https://developers.openai.com/api/docs/guides/migrate-to-responses)、[OpenAI Models](https://developers.openai.com/api/docs/models)
- 采用结论：`modules/agent-runtime` 的 `openai_compatible` provider 默认调用 Responses API，在请求中发送可配置的 `reasoning.effort`，用户指定 `gpt-5.6-sol` 时按配置透传模型字符串并使用 `max`；旧兼容端点可切换回 Chat Completions。
- 取舍：OpenAI 公共模型目录截至 2026-07-10 已列出 `gpt-5.6-sol`，并声明支持 `none/low/medium/high/xhigh/max` reasoning effort、Responses API 和 Chat Completions。项目仍通过环境变量选择模型，避免把外部模型和凭据硬编码进业务代码。
- 结构化输出继续由 Pydantic 二次校验；因为现有 Architect 输出含开放式 OpenAPI/DB JSON 对象，请求使用 `strict=false`，避免把不符合 OpenAI strict schema 子集的动态对象伪装成严格保证。
- 当前 M4 默认仍使用 `local_structured` provider，避免在无外部模型凭据时写固定假数据。切换外部 LLM 时记录 provider、model、API mode、reasoning effort 和失败事件。

## 4. FastAPI 后台任务与 service 边界

- 官方资料：[FastAPI Background Tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/)、[FastAPI Dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/)
- 采用结论：M4 的 `start` / `run-next` 采用同步 service 调用，一次推进一个 Agent 步骤，便于答辩演示和事务验证。
- 取舍：暂不使用后台任务隐藏执行过程；后续如接入异步队列或长任务，需要把 AgentRun、EventLog 和错误恢复策略先补到设计文档。

## 5. pytest 状态机与 schema 测试

- 官方资料：[pytest Fixtures](https://docs.pytest.org/en/stable/how-to/fixtures.html)、[pytest Assertions](https://docs.pytest.org/en/stable/how-to/assert.html)
- 采用结论：M4 增加黑盒 API 测试和白盒 schema / 状态机测试，覆盖正常路径、审批分支、缺配置失败、非法状态和开发计划查询。
- 取舍：生产代码不引入测试 fake；测试只通过本地 PostgreSQL、Alembic 和真实 FastAPI TestClient 验证事务副作用。
