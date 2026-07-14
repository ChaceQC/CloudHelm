# Codex / Responses 多轮上下文与 Prompt Cache 资料归档

检索与验证日期：2026-07-11；Codex CLI 协作模型复核：2026-07-14
适用阶段：M4/M5 Agent conversation、reasoning、工具上下文与真实缓存纠偏

## 1. OpenAI 官方资料

- [Prompt caching](https://platform.openai.com/docs/guides/prompt-caching)
  - 采用结论：缓存要求请求开头具有完全一致的前缀；tools、images 和
    Structured Output schema 也参与前缀。usage 中
    `input_tokens_details.cached_tokens` 是命中证据。
  - 官方显式协议使用请求级
    `prompt_cache_options: {"mode": "explicit"}`，并在 content block 使用
    `prompt_cache_breakpoint: {"mode": "explicit"}`。
  - CloudHelm 默认继续使用自动缓存；显式协议只在端点能力明确时启用。
- [Reasoning models](https://developers.openai.com/api/docs/guides/reasoning)
  - 采用结论：多轮调用只保存和回放供应商返回的 reasoning item；
    `reasoning.encrypted_content` 不解密、不展示、不伪造。
  - 当前流程使用 `reasoning.effort=xhigh`、`summary=auto` 和
    `context=all_turns`。
- [Responses API migration](https://developers.openai.com/api/docs/guides/migrate-to-responses)
  - 采用结论：请求和后续历史使用有序 ResponseItem；CloudHelm 使用
    `store=false`，因此清除不可复用服务端 item ID，但保留 message phase、
    encrypted reasoning、call status 和 call ID。
- [Function calling](https://developers.openai.com/api/docs/guides/function-calling)
  - 采用结论：模型的 `function_call` 与脱敏 Tool Gateway 结果
    `function_call_output` 必须使用同一 `call_id` 成对进入历史。
- [Streaming API responses](https://developers.openai.com/api/docs/guides/streaming-responses)
  - 采用结论：外部模型调用使用 HTTP SSE `stream=true`，按 typed event
    累积文本和最终有序 output items；本轮不实现 WebSocket。

## 2. Codex 官方源码审计

- 仓库：[openai/codex](https://github.com/openai/codex)
- 审计 commit：`a328f30172c606cfdc150c009790a3f05bfb4d22`
- 审计时使用临时只读 clone；临时路径和副本不提交到仓库。

重点文件与采用结论：

- `codex-rs/core/src/client.rs`
  - 请求发送完整 `ResponseItem[]`、稳定 thread/session headers、
    `x-client-request-id` 和 originator。
  - `store=false` 时只清除不可复用 item id。
  - Responses 请求包含稳定 instructions、tools、reasoning、text format 和
    prompt cache key。
- `codex-rs/protocol/src/models.rs`
  - 采用 Message、Reasoning、FunctionCall、FunctionCallOutput、
    CustomToolCall 等 item 形态，不把历史压成自然语言摘要。
- `codex-rs/core/tests/suite/prompt_caching.rs`
  - 采用跨 turn 稳定 instructions/tool 定义与完整历史前缀白盒比较。
- `codex-rs/core/src/agent/control/spawn.rs`
  - fresh child 不复制父历史。
  - full-history fork 保留 system/developer/user message 与 assistant
    `final_answer`，过滤 reasoning、工具调用/结果和内部 inter-agent metadata。
- `codex-rs/core/src/agent/control_tests.rs`
  - 采用 parent/child、depth、role、fork mode、生命周期和最终通知测试。

## 3. 当前兼容端点能力探测

真实凭据仅临时注入测试进程；本文件不保存 Key、Cookie、账号或端点地址。

|能力|结果|CloudHelm 处理|
|---|---|---|
|HTTP SSE Responses|支持|作为默认外部模型传输。|
|`gpt-5.6-sol` + `xhigh`|支持|模型字符串和 effort 原样透传。|
|Codex User-Agent / originator / thread headers|支持|每个 root/child 使用稳定 conversation ID。|
|`reasoning.context=all_turns`|支持|完整回放已返回 reasoning item。|
|`reasoning.encrypted_content`|支持|保存到 conversation JSONB，不对外展示。|
|稳定扁平 `text.format`|支持|三个普通角色发送同一 `cloudhelm_agent_output_v1`。|
|自动 Prompt Cache|支持|真实五轮第 2-5 轮均返回递增 cached token。|
|官方 `prompt_cache_options` / `prompt_cache_breakpoint`|HTTP 502|默认关闭；显式启用后保留真实错误，不静默删字段。|
|根级 `anyOf/$ref` 联合输出 schema|HTTP 502|改用扁平稳定传输 schema，再由角色专属 Pydantic 严格校验。|

## 4. 已采用的 CloudHelm 设计

1. 每个 Task 只有一个 root `agent_conversations` 记录。
2. Requirement、Architect、Planner 以及后续普通角色只增加 root turn，不按
   `agent_type` 新建 conversation。
3. 每次请求使用稳定 Base Instructions、稳定扁平输出 schema、同一 model /
   reasoning 配置、同一 cache key 和完整已提交 ResponseItem 前缀。
4. 结构化格式修复请求只在当前尝试追加 `<validation_repair>`；失败输出不进入
   durable conversation。
5. AgentRun 同时保存总 usage 和 `provider_requests` 逐请求 usage；
   `cache_hit` 仅由真实 `cached_input_tokens > 0` 推导。
6. 每个模型步骤使用数据库 savepoint，晚期失败不能留下业务产物或错误递增 turn。
7. 只有显式 `spawn_subagent` 创建 child；child 使用独立 conversation/cache
   key，结束后只向父线程追加 `<subagent_notification>`。
8. 当前不实现 Responses WebSocket、服务端 conversation store 或自动 compaction；
   上下文达到模型阈值前需要另立 compaction/truncation 设计，不能静默丢历史。

## 5. 2026-07-14 Codex CLI Agent 协作复核

复核来源：

- [Codex manual](https://developers.openai.com/codex/codex-manual.md) 的
  Multi-agent operations、Best practices、AGENTS.md 和 App Server thread /
  turn / item 章节。
- [openai/codex](https://github.com/openai/codex) 的 app-server 与 subagent
  实现入口。

最新采用结论：

1. root conversation 作为主 agent thread，保存用户目标、约束、决策、审批和
   最终汇总；噪声较大的探索、测试和日志分析放入独立 child。
2. child 必须由显式 spawn 创建，并携带 role、objective、expected result、
   fork mode 和完成判定。默认 `max_depth=1`、`max_threads=6`。
3. read-heavy 工作可并行；写入同一 workspace、Git index 或共享状态的工作必须
   串行，或使用独立 worktree/workspace。
4. child 只向父线程回传简洁结构化摘要和证据引用，不复制 reasoning、完整工具
   历史、原始日志或堆栈；CloudHelm 将摘要限制为 4000 字符并执行脱敏。
5. child 权限不得高于父线程；CloudHelm 不直接复用父审批，而是让 Tool Gateway
   按 child role、资源版本和当前审批重新判定，这是比直接继承更严格的实现。
6. Codex CLI 将运行中 follow-up 区分为 steer 当前 turn 与 queue 下一 turn。
   M1-M6 当前只实现审批上下文、暂停/取消和 subagent notification；通用
   steer/queue API 作为后续交互契约，不写成已交付。

## 6. 首次真实五轮缓存证据

```text
turn1 input=6511  cached=0
turn2 input=11453 cached=5888
turn3 input=16422 cached=11008
turn4 input=21373 cached=16128
turn5 input=26324 cached=21248
```

- 五轮均为一个供应商请求、同一 conversation 和同一 cache key。
- input token 每轮严格递增。
- 第 2-5 轮真实 cached token 均大于 0 且严格递增。
- 以上数字来自供应商 usage，不由 CloudHelm 根据文本长度估算。

## 7. 最终三角色完整流程证据

```text
Requirement turn=1 requests=1 input=5363  cached=0     output=3254
Architect   turn=2 requests=2 input=24795 cached=15872 output=31818
  request1 input=12026 cached=4864  output=15156
  request2 input=12769 cached=11008 output=16662
Planner     turn=3 requests=1 input=30484 cached=12032 output=7084
```

- 三个 AgentRun 使用同一 conversation ID 和同一 cache key。
- Architect 首次结构化输出需要一次格式修复，因此真实记录两次供应商请求；
  CloudHelm 没有把它隐藏或误报成单次调用。
- 用最终成功请求比较，input 为 `5363 < 12769 < 30484`，cached 为
  `0 < 11008 < 12032`。
- 数据库只有一个 root conversation，`turn_count=3`，最后 response ID 与
  Planner AgentRun 一致。
- 设计审批与计划审批均为 approved；Timeline 包含 3 个
  `AgentRunCompleted` 和 1 个 `AgentConversationCreated`。
