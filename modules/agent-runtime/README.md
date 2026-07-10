# modules/agent-runtime

CloudHelm M4 Agent Runtime 提供 Requirement / Architect / Planner 三类 Agent 的结构化输入输出、Prompt 文件和 provider 适配层。

## M4 能力边界

- Agent 只生成需求规格、技术设计和开发计划类结构化对象。
- Agent Runtime 不直接写数据库，不调用 Repo、Docker、Git、SSH 或远端工具。
- 所有输出必须经过 Pydantic 校验后，才允许由 Platform API / Orchestrator 写入业务表。
- 默认 `local_structured` provider 是 M4 MVP 的规则化结构化生成器：它只根据真实 Task / Requirement / Design 输入拆分字段，不使用固定样例或测试假数据。
- `openai_compatible` provider 默认使用 Responses API + JSON Schema 输出，并支持 `reasoning.effort=max`；旧服务可切换到 Chat Completions。瞬时 HTTP/网络错误和无效结构化响应执行有界指数退避重试，认证等不可重试 4xx 立即失败。
- 重试耗尽后仍会写入失败 AgentRun；瞬时请求错误和结构化响应错误属于可恢复失败，Platform API 将 Task 暂停在原业务阶段，不伪装为完成。

## 命令

```powershell
uv run pytest
```

## Provider 配置

Platform API 通过以下环境变量选择 provider：

- `CLOUDHELM_AGENT_PROVIDER=local_structured`：本地规则化结构化生成器。
- `CLOUDHELM_AGENT_PROVIDER=openai_compatible`：OpenAI 兼容模型调用。
- `CLOUDHELM_LLM_PROVIDER`：外部模型供应商名称，用于审计。
- `CLOUDHELM_LLM_MODEL`：模型名称。
- `CLOUDHELM_LLM_API_BASE`：OpenAI 兼容 API 根地址。
- `CLOUDHELM_LLM_API_KEY`：模型 API Key，不得提交到 Git。
- `CLOUDHELM_LLM_API_MODE=responses`：默认调用 `/v1/responses`；可设为 `chat_completions`。
- `CLOUDHELM_LLM_REASONING_EFFORT=max`：发送最大推理强度；`gpt-5.6-sol` 模型字符串按用户配置原样透传。
- `CLOUDHELM_LLM_MAX_OUTPUT_TOKENS=32768`：为 reasoning token 和结构化 JSON 预留输出预算。
- `CLOUDHELM_LLM_TIMEOUT_SECONDS=120`：单次 HTTP 请求超时。
- `CLOUDHELM_LLM_MAX_ATTEMPTS=3`：请求或结构化输出失败时的总尝试次数。
- `CLOUDHELM_LLM_RETRY_BACKOFF_SECONDS=1`：指数退避初始秒数；测试可设为 0。
