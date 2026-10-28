# 有界 Agent Runtime

实际 Python 包为 `modules/agent_runtime/` 和 `modules/tool_gateway/`。本入口交付 P2.1-01 的内部 Runtime；P2.1-02 的供应商 usage、费用结算与长工具可靠等待尚未接入，未提供 Desktop Agent 启动界面。

## 启动与上下文

在 WSL 的现有 worker 环境配置 `CLOUDHELM_AGENT_MODEL_KEY_FILE`；文件为当前服务用户所有的普通 UTF-8 文件，权限只允许该用户读写，最多 4096 字节。只填写实际密钥，不能提交或打印文件内容。`CLOUDHELM_AGENT_MODEL_BASE_URL` 可指定受控 Responses 端点，默认官方 `/v1`；配置只由 worker 读取，模型输入和 DBOS 参数不携带凭据或宿主文件路径。

内部入口为 `AgentRuntimeApplication.start(source_command_id, RuntimeStartRequest)`。来源必须是已接受、可恢复真实调用者且当前仍具有该 Task 命令权限的持久命令；它不以匿名身份或调用方自报权限启动。模型配置固定为 `default-responses / 1 / gpt-6-luna`，可选 `secret_version_ref` 只能指向同一受控配置和修订。

`RuntimeStartRequest` 包含既有 `RuntimeInput`、受限 `ContextPackage` 与 `RunPolicy`。Context 只含当前 InputSet、工作项修订、需求/验收/源码等引用、工具和权限/预算快照；上下文引用的摘要必须与实际内容一致。初次历史引用以 Session ID 为 `object_id`，`revision` 为 `0`，内容摘要为 UTF-8 `[]` 的 SHA-256。后续使用返回的完整历史引用与新 Session 版本。

启动在一个短事务内写 Session、Run、WorkflowBinding 并使用公开 `enqueue_in_transaction` 入队；相同 Run/正文返回原身份，异正文拒绝。同一 Session 同时最多一个 queued/running Run。worker 的 `models` 队列并发为 1，仍保留原控制队列；这是当前软件限制，不是容量验收结论。

## 能力与每次准入

|固定能力|当前支持|
|---|---|
|模型与协议|`gpt-6-luna`、PydanticAI 2.55.0、Responses 文本；本次方法按 2026-10-28 固定|
|工具|受控用户函数；首链仅 `task.read`，参数为 `{}`，逐次准入并顺序执行|
|请求限制|默认 3 次、整轮 60 秒；明确的输出 token 上限；真实 HTTP 请求体最多 1MiB|
|重试与修复|SDK 500/连接重试和工具参数修复均经同一个传输准入；上限包含真实 HTTP 尝试|
|流式/托管工具|关闭；不开放模型直连 shell、工作区或 MCP|
|缓存与计费|不预设缓存折扣；usage 和账单保持 unknown，等待 P2.1-02 核对|

每次实际 HTTP 出站前重新检查 worker 运行门禁、真实来源权限、Task 普通推进资格、控制/输入修订、Session/Run、绝对截止时间、请求次数和预算，并先持久登记唯一请求身份、正文摘要与保守费用占账。每次工具调用独立检查相同当前资格及工具白名单，历史成功和 Context 快照不授予下一次权限。

保守预留仅适用于 P0 `official-model-prices-r1` 的全球 Standard 文本/用户函数范围：使用较大的长上下文输入/缓存写入与输出费率、实际请求字节长度及固定输出上限计算最低预留，未知缓存收益不抵扣。Task 和本 Run 预算均须足够，首链只支持 USD；兼容端点的实际账单未据此认定。所有已准入请求继续占账，不补零，不把占账写成已知费用。

## 恢复与结果

DBOS workflow/step 只接收 `run_id`，只返回有界状态、历史引用和请求 ID。合法完整 SDK 历史保存在有界业务历史表，摘要使用固定排序的 UTF-8 JSON；模型凭据只存在当前请求的内存。失败不把原 provider 异常或部分消息交给 DBOS。

SDK 内部只返回新增历史消息，错误只传安全码；请求身份及费用占账由持久请求表读取，传输层按实际准入次数限制出站。能力范围以本页能力表和对应实际限制为准，不另维护无人消费的能力描述对象。

恢复沿原 Run/workflow。已存在实际请求记录而 step 检查点缺失时，保留原预留、返回待核对原因并停止自动重发；P2.1-02 承接 usage/结果核对。新 Run 和切换 epoch 的新请求仍使用同一传输门禁，本次不开放自动历史压缩调度或写工具重放。

Run 成功只表示本次有界推进保存，返回 `continue_required`，不完成 Task。执行期间 Task 取消、终态或输入失效关闭新请求/工具；晚到结果只保存需复核事实。Task 控制读取实际 Run 边界和未知费用，不把技术成功当业务完成。

新库 head 为 `0012_p2_agent_runtime`。旧安装仍不会由 initialize 自动升级；固定旧快照的受限维护入口继续固定在 `0011`，保持 recovery_required，不能直接运行新 Runtime。
