# modules/agent-runtime

CloudHelm Agent Runtime `0.4.0` 提供 Requirement / Architect / Planner /
Scaffold / Coder / Tester / Reviewer / Security 八类 Agent 的结构化输入输出、
版本化 Instructions、Codex 风格 ResponseItem 会话和 provider 适配层。

M6 新增 Responses 工具交换循环、稳定工具 manifest、逐 AC Tester 结果、
真实 diff/JUnit/安全扫描证据消费；Agent 仍不直接执行副作用，全部工具请求
交给 Platform API 与 Tool Gateway。

## M4-M6 能力边界

- Requirement、Architect、Planner 生成需求规格、技术设计和开发计划。
- Scaffold、Coder、Tester、Reviewer、Security 生成受严格 Pydantic 校验的
  workspace、实现、测试、审查和安全结构化结果，并消费真实 ToolCall/Artifact
  证据。
- Agent Runtime 不直接写数据库或执行副作用；Repo、Scaffold、Sandbox、
  Test、Security、Git 请求都由 Platform API 绑定服务端参数后交给 Tool Gateway。
- 所有输出必须经过 Pydantic 校验后，才允许由 Platform API / Orchestrator 写入业务表。
- 默认 `local_structured` provider 根据真实 Task、Requirement、Design、
  DevelopmentPlan、execution recipe 和工具结果生成结构化输出，不使用静态
  演示结果冒充执行证据。
- `openai_compatible` 默认使用 HTTP SSE Responses API，发送稳定 Base Instructions、完整历史、`reasoning.encrypted_content`、Codex User-Agent、thread/session headers 和稳定 `prompt_cache_key`；本轮明确不实现 WebSocket。
- Requirement、Architect、Planner 是同一 Task root conversation 的连续 turn。只有显式 `spawn_subagent` 才创建 child conversation。
- Responses `text.format` 使用跨角色一致的扁平 `cloudhelm_agent_output_v1` 传输 schema，当前角色输出再由对应 Pydantic model 严格校验。这样避免角色专属 schema 从请求开头破坏 Prompt Cache。
- 官方显式断点协议由 `CLOUDHELM_LLM_EXPLICIT_CACHE_BREAKPOINT` 控制，启用时同时发送 `prompt_cache_options.mode=explicit` 与 content `prompt_cache_breakpoint`，并随历史回放断点。2026-07-11 对当前真实兼容端点的单请求探测返回 HTTP 502，因此默认关闭，依靠稳定前缀自动缓存，不做静默字段降级。
- 默认模型流程使用 `gpt-5.6-sol`、`reasoning.effort=xhigh`、`reasoning.summary=auto`、`reasoning.context=all_turns`。Provider 类型仍保留 `max` 枚举兼容值。
- 瞬时 HTTP/网络错误和无效结构化响应执行有界指数退避重试，认证等不可重试 4xx 立即失败。
- 重试耗尽后仍会写入失败 AgentRun；瞬时请求错误和结构化响应错误属于可恢复失败，Platform API 将 Task 暂停在原业务阶段，不伪装为完成。

## Instructions 与会话

- `prompts/base.md`：跨角色稳定的 Base Instructions，定义会话、可信边界、
  ResponseItem、工具、审批、风险、subagent 和完成判定。
- `prompts/requirement.md`、`architect.md`、`planner.md`、`scaffold.md`、
  `coder.md`、`tester.md`、`reviewer.md`、`security.md`：当前 turn 的详细角色
  Instructions，包含输入解释、处理顺序、字段精度、allowlist、禁止项和完成判定。
- `prompts/subagent.md`：child conversation 的 fresh/full-history、权限、生命周期
  和最终通知边界。
- 格式修复只在当前请求追加 `<validation_repair>`，不会改写 Base Instructions；
  成功业务 turn 只有通过 Pydantic 的最终尝试才会原子追加到 conversation。
- M6 工具步骤在基础设施失败时保留已经真实发生的 function/custom call 与匹配
  output，并追加 `<failed_step_context>`；该失败上下文只用于可审计重试，不会
  伪装成成功结构化输出。
- 完整历史保存 developer/user/message、assistant final answer、encrypted reasoning、
  function/custom tool call 和匹配的 tool output；`store=false` 只移除不可复用 item id。

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
- `CLOUDHELM_LLM_REASONING_EFFORT=xhigh`：当前真实流程使用的推理强度。
- `CLOUDHELM_LLM_REASONING_SUMMARY=auto`：reasoning summary 模式。
- `CLOUDHELM_LLM_REASONING_CONTEXT=all_turns`：回放全部可用 reasoning context。
- `CLOUDHELM_LLM_MAX_OUTPUT_TOKENS=32768`：为 reasoning token 和结构化 JSON 预留输出预算。
- `CLOUDHELM_LLM_TIMEOUT_SECONDS=120`：单次 HTTP 请求超时。
- `CLOUDHELM_LLM_MAX_ATTEMPTS=3`：请求或结构化输出失败时的总尝试次数。
- `CLOUDHELM_LLM_RETRY_BACKOFF_SECONDS=1`：指数退避初始秒数；测试可设为 0。
- `CLOUDHELM_LLM_EXPLICIT_CACHE_BREAKPOINT=false`：仅端点明确支持
  Responses `prompt_cache_options` / `prompt_cache_breakpoint` 时启用。
- `CLOUDHELM_LLM_USER_AGENT=codex_cli_rs/0.0.0 (CloudHelm)`：Codex 路由兼容 User-Agent。
- `CLOUDHELM_LLM_ORIGINATOR=codex_cli_rs`：请求来源审计头。
