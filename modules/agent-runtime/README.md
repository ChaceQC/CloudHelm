# modules/agent-runtime

CloudHelm M4 Agent Runtime 提供 Requirement / Architect / Planner 三类 Agent 的结构化输入输出、Prompt 文件和 provider 适配层。

## M4 能力边界

- Agent 只生成需求规格、技术设计和开发计划类结构化对象。
- Agent Runtime 不直接写数据库，不调用 Repo、Docker、Git、SSH 或远端工具。
- 所有输出必须经过 Pydantic 校验后，才允许由 Platform API / Orchestrator 写入业务表。
- 默认 `local_structured` provider 是 M4 MVP 的规则化结构化生成器：它只根据真实 Task / Requirement / Design 输入拆分字段，不使用固定样例或测试假数据。
- `openai_compatible` provider 预留 OpenAI 兼容 Chat Completions + JSON Schema 输出路径；缺少 URL、模型或 API Key 时返回明确配置错误。

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
