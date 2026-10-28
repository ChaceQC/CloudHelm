# 有界 Agent Runtime

实际 Python 包为 `modules/agent_runtime/` 和 `modules/tool_gateway/`。本入口覆盖 P2.1-01/02 的内部 Runtime、逐请求费用和 Workspace 物化的长工具等待，未提供 Desktop Agent 启动界面。

## 启动与上下文

在 WSL 的现有 worker 环境配置 `CLOUDHELM_AGENT_MODEL_KEY_FILE`；文件为当前服务用户所有的普通 UTF-8 文件，权限只允许该用户读写，最多 4096 字节。只填写实际密钥，不能提交或打印文件内容。`CLOUDHELM_AGENT_MODEL_BASE_URL` 可指定受控 Responses 端点，默认官方 `/v1`；配置只由 worker 读取，模型输入和 DBOS 参数不携带凭据或宿主文件路径。

内部入口为 `AgentRuntimeApplication.start(source_command_id, RuntimeStartRequest)`。来源必须是已接受、可恢复真实调用者且当前仍具有该 Task 命令权限的持久命令；它不以匿名身份或调用方自报权限启动。模型配置固定为 `default-responses / 1 / gpt-6-luna`，可选 `secret_version_ref` 只能指向同一受控配置和修订。

`RuntimeStartRequest` 包含既有 `RuntimeInput`、受限 `ContextPackage` 与 `RunPolicy`。Context 只含当前 InputSet、工作项修订、需求/验收/源码等引用、工具和权限/预算快照；上下文引用的摘要必须与实际内容一致。初次历史引用以 Session ID 为 `object_id`，`revision` 为 `0`，内容摘要为 UTF-8 `[]` 的 SHA-256。后续使用返回的完整历史引用与新 Session 版本。

启动在一个短事务内写 Session、Run、WorkflowBinding 并使用公开 `enqueue_in_transaction` 入队；相同 Run/正文返回原身份，异正文拒绝。同一 Session 同时最多一个 queued/running Run。worker 的 `models` 队列并发为 1，仍保留原控制队列；这是当前软件限制，不是容量验收结论。

## 能力与每次准入

|固定能力|当前支持|
|---|---|
|模型与协议|`gpt-6-luna`、PydanticAI 2.55.0、Responses 文本；本次方法按 2026-10-28 固定|
|工具|`task.read`、`submit_operation`、`query_operation`、`await_operation`；逐次准入并顺序执行|
|请求限制|默认 3 次、整轮 60 秒；明确的输出 token 上限；真实 HTTP 请求体最多 1MiB|
|重试与修复|SDK 500/连接重试和工具参数修复均经同一个传输准入；上限包含真实 HTTP 尝试|
|流式/托管工具|关闭；不开放模型直连 shell、工作区或 MCP|
|缓存与计费|仅按实际供应商 usage 计算；缺项保持 unknown；计算金额与有证据的账单金额分别保存|

每次实际 HTTP 出站前重新检查 worker 运行门禁、真实来源权限、Task 普通推进资格、控制/输入修订、Session/Run、绝对截止时间、请求次数和预算，并先持久登记唯一请求身份、正文摘要与保守费用占账。每次工具调用独立检查相同当前资格及工具白名单，历史成功和 Context 快照不授予下一次权限。

保守预留仅适用于 P0 `official-model-prices-r1` 的全球 Standard 文本/用户函数范围：使用较大的长上下文输入/缓存写入与输出费率、实际请求字节长度及固定输出上限计算最低预留，未知缓存收益不抵扣。Task 和本 Run 预算均须足够，首链只支持 USD；兼容端点的实际账单未据此认定。

## 请求结果与费用核对

传输层在每次实际 HTTP 尝试前取得 `request_record_id`，完整读取响应后立即交 `RuntimeBilling.record` 记录安全的供应商响应/请求身份、实际模型、服务档位及 usage；模型修复或重试的每个 HTTP 请求分别记录。失败/取消响应也保留其中实际提供的 usage，连接中断或没有字段时仍未知。落账失败阻断当前调用，不把该失败作为网络错误自动重发。

原请求的正文摘要、顺序和预留不可变，关联结果按修订追加，同请求相同结果幂等。固定计价依据沿用 [P0 决定](../decisions/p0/admitted-runtime.md)：`default` 映射 Standard，全球文本与自定义函数没有供应商托管工具收费；金额使用 `Decimal`，绑定官方价格修订。输入总量、缓存读取、缓存写入、输出及适用模型/档位缺少必要字段时，总计算金额保持 null；不从缺失的缓存字段推定 0。兼容提供方的独立账单只有同时提供金额、币种和账单证据才保存。

准入实时汇总已知费用及未知预留；未知时较小账单不释放预留，较大 USD 账单继续占账。真实 usage/金额超过预登记上限仍保存事实并阻断 Task 后续模型和工具准入。

迟到核对使用 `await RuntimeBilling(engine).reconcile(request_record_id, result, actor=..., scope=ModelUsageScope(...), evidence_ref=...)`。scope 绑定原 Task/Session/Run 和当前控制、输入有效性及权限修订；核对重新授权，相同事实/证据幂等，异身份、陈旧 scope、冲突 usage 或证据拒绝。Task 取消后仍可在当前授权下归档费用，不能借此恢复普通推进。

## 长工具提交和等待

当前长操作仅支持当前 Task/工作项、同一授权主体的 Workspace 物化；需要已登记的产品输入、工作区与当前 `workspace.write` 权限。`task.read({})` 返回当前工作项的 `workspace_id`，没有工作区时为 null。通过现有 `dispatch_tool(name, arguments)` 使用：

|动作|参数|结果|
|---|---|---|
|`submit_operation`|`{"workspace_id":"..."}`|复用 P1 应用事务及执行入队，返回原 `operation_id`、摘要、accepted、查询/等待引用；按原 Run + tool-call ID 去重|
|`query_operation`|`{"operation_id":"..."}`|有界状态及 UTC 观察时间；未登记最终回执时为 unknown|
|`await_operation`|`{"operation_id":"..."}`|已有回执直接返回原结果；否则结束当前 Run，原子保存历史与关联原 tool-call ID 的 WaitCondition|

提交与等待各自独立调用，长动作每批仅允许一条；混入其它调用时，在任何工具副作用之前要求模型拆批。短查询批次最多 8 条，模型真实请求总数仍受 Run 政策限制。accepted 工具返回保留提交语义，不在物理完成后覆写为产物。

物化回执落库与等待唤醒共用事务；结果早于等待登记时，登记事务重新检查原操作。等待结果已到、当前权限和 Task/输入修订允许、Session 无活动 Run 时，以等待身份唯一派生新 Run/workflow 并事务入队。重复通知不新增 Run；Session 已有活动 Run 时保留等待，在其结束后再检查。unknown 保留等待，暂停、取消、完成或失效输入不自动续接。续接载入完整的已确认工具结果，匹配原调用 ID，使用已保存的 SDK 历史；不额外拼接新 prompt，不发送模型轮询请求。

提交后可以继续不依赖物化结果的工作；真正调用 await 后，该 Session 的未配对调用须由对应结果续接，普通新 Run 在模型出站前拒绝。当前未开放跨历史分叉合并、其它领域长工具或长期自动超时维护。P1 原物化回执登记仍要求原主体现有 `workspace.write`，撤权后需按原 P1 受控结果核对入口处理；本包不绕过该权限边界。

## 恢复与结果

DBOS workflow/step 只接收 `run_id`，只返回有界状态、历史引用和请求 ID。合法完整 SDK 历史保存在有界业务历史表，摘要使用固定排序的 UTF-8 JSON；模型凭据只存在当前请求的内存。失败不把原 provider 异常或部分消息交给 DBOS。

SDK 内部只返回新增历史消息，错误只传安全码；请求身份及费用占账由持久请求表读取，传输层按实际准入次数限制出站。能力范围以本页能力表和对应实际限制为准，不另维护无人消费的能力描述对象。

恢复沿原 Run/workflow。已提交 Run 结果时返回原结果，不重新请求或再次创建续接；已有实际请求记录而 step 检查点和完整协议历史缺失时，先沿原请求核对费用并停止自动重发。费用已知不证明丢失的模型输出已经恢复。新 Run 和切换 epoch 的新请求仍使用同一传输门禁，本次不开放自动历史压缩调度或写工具重放。

Run 成功只表示本次有界推进保存，返回 `continue_required`，不完成 Task。执行期间 Task 取消、终态或输入失效关闭新请求/工具；晚到结果只保存需复核事实。Task 控制读取实际 Run 边界和未知费用，不把技术成功当业务完成。

源码版本为 `0.13.0`，新库 head 为 `0013_p2_usage_waits`，线性承接 `0012_p2_agent_runtime`；DBOS 应用继续为 `cloudhelm-hub/0.7.0`，workflow/step 顺序不变，等待续接由结果事务入队。旧安装仍不会由 initialize 自动升级；固定旧快照的受限维护入口继续固定在 `0011`，保持 recovery_required，不能直接运行新 Runtime。
