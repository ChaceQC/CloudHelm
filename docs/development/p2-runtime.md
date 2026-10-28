# 有界 Agent Runtime

实际 Python 包为 `modules/agent_runtime/` 和 `modules/tool_gateway/`。本入口覆盖 P2.1-01/02 的内部 Runtime、逐请求费用和 Workspace 物化的长工具等待，未提供 Desktop Agent 启动界面。

源码 `0.15.0` 在新 Run、实际请求/工具及结果提交边界读取[工作区写入权](p2-handoffs.md)。接管期间本工作项停止新推进；交还后须先复核输入，后续 Run 收到固定人工修改及差异引用，旧 Run 不恢复普通写入资格。

## 启动与上下文

在 WSL 的现有 worker 环境配置 `CLOUDHELM_AGENT_MODEL_KEY_FILE`；文件为当前服务用户所有的普通 UTF-8 文件，权限只允许该用户读写，最多 4096 字节。只填写实际密钥，不能提交或打印文件内容。`CLOUDHELM_AGENT_MODEL_BASE_URL` 可指定受控 Responses 端点，默认官方 `/v1`；配置只由 worker 读取，模型输入和 DBOS 参数不携带凭据或宿主文件路径。

内部入口为 `AgentRuntimeApplication.start(source_command_id, RuntimeStartRequest)`。来源必须是已接受、可恢复真实调用者且当前仍具有该 Task 命令权限的持久命令；它不以匿名身份或调用方自报权限启动。模型配置固定为 `default-responses / 1 / gpt-6-luna`，可选 `secret_version_ref` 只能指向同一受控配置和修订。

`RuntimeStartRequest` 包含既有 `RuntimeInput`、受限 `ContextPackage` 与 `RunPolicy`。Context 只含当前 InputSet、工作项修订、需求/验收/源码等引用、选定文件摘要/行范围、工具和权限/预算快照；上下文引用的摘要必须与实际内容一致。初次历史引用以 Session ID 为 `object_id`，`revision` 为 `0`，内容摘要为 UTF-8 `[]` 的 SHA-256。后续使用返回的完整历史引用与新 Session 版本。

启动在一个短事务内写 Session、Run、WorkflowBinding 并使用公开 `enqueue_in_transaction` 入队；相同 Run/正文返回原身份，异正文拒绝。同一 Session 同时最多一个 queued/running Run。worker 的 `models` 队列并发为 1，仍保留原控制队列；这是当前软件限制，不是容量验收结论。

## 能力与每次准入

|固定能力|当前支持|
|---|---|
|模型与协议|`gpt-6-luna`、PydanticAI 2.55.0、Responses 文本；本次方法按 2026-10-28 固定|
|工具|`task.read`、`submit_operation`、`query_operation`、`await_operation`，以及开发角色的 `workspace.list_directory`、`workspace.read_file`、`workspace.search`；逐次准入并顺序执行|
|请求限制|默认 3 次、整轮 60 秒；明确的输出 token 上限；真实 HTTP 请求体最多 1MiB|
|重试与修复|SDK 500/连接重试和工具参数修复均经同一个传输准入；上限包含真实 HTTP 尝试|
|流式/托管工具|关闭；不开放模型直连 shell、工作区或 MCP|
|缓存与计费|仅按实际供应商 usage 计算；缺项保持 unknown；计算金额与有证据的账单金额分别保存|

每次实际 HTTP 出站前重新检查 worker 运行门禁、真实来源权限、Task 普通推进资格、控制/输入修订、Session/Run、绝对截止时间、请求次数和预算，并先持久登记唯一请求身份、正文摘要与保守费用占账。每次工具调用独立检查相同当前资格及工具白名单，历史成功和 Context 快照不授予下一次权限。

保守预留仅适用于 P0 `official-model-prices-r1` 的全球 Standard 文本/用户函数范围：使用较大的长上下文输入/缓存写入与输出费率、实际请求字节长度及固定输出上限计算最低预留，未知缓存收益不抵扣。Task 和本 Run 预算均须足够，首链只支持 USD；兼容端点的实际账单未据此认定。

## 工程上下文加载

A03 在现有内部启动入口装配可读内容，不新增 HTTP 路由或 Agent 工具。worker 使用受管存储与 GitObjectStore 加载实际固定 commit；未配置加载器、来源不可读或当前授权失败时，在模型请求前停止。

|内容|实际来源与绑定|
|---|---|
|需求与验收|读取当前项目已登记的需求 statement、必需 check IDs 和 method 正文；需求、验收、源码必须属于该 Context 的 InputSet，不把摘要充当正文或验收通过事实|
|规范、源码与契约|`ContextPackage.source_reads` 明确 path、完整文件 SHA-256、purpose、start_line 与 max_lines；源码限当前 source_ref 的精确 commit，自动加载根及所选路径祖先 AGENTS.md|
|决定、未决项与证据|已登记引用解析其受控 metadata；源码文件型引用使用 `authority=source-files`、object_id=相对路径、revision=baseline_commit 及文件摘要，并须有匹配 purpose 的 source_reads；保留完整引用，不调用模型生成摘要|
|人工交还|读取原交还记录的变更清单，并从原 baseline/returned 固定快照生成真实文本差异；不重新采集可变工作区|
|运行策略|RunPolicy 增加 role（默认 developer）及固定 instruction_revision=agent-r1；共同协议和五角色 r1 指令通过 SDK instructions 提交，项目正文只作为数据|

例如源码片段为 `{"path":"src/main.py","digest":"sha256:<完整文件摘要>","purpose":"source","start_line":1,"max_lines":120}`。默认不装入整个仓库；每个 Context 最多 8 个显式片段、每片最多 160 行、单文件最多 64KiB、源码返回正文合计最多 32KiB，安全路径索引最多 64 条。返回真实摘要、总行数、截断与 next_start_line；续读时在下一份 Context 中指定同一来源及新起始行。规范未读完整时不得宣称已覆盖其全部约束。非空 source_prefix 尚不支持，因为当前 Git 子树视图无法保证读取前缀外的继承规范，明确拒绝。

人工修改最多装入 32 项可见变更和前 8 项差异，差异正文合计 8KiB；超量、二进制和不可生成正文保留真实标记及原交还查询引用。最终 JSON prompt 上限 64KiB，超出时拒绝；不会静默丢弃需求、证据或未决项。DBOS 参数仍只有 run_id，结果仍是有界引用；经筛选正文仅进入内存请求及既有 128KiB 上限的业务 SDK 历史，不进入工作流参数/step 返回。

读取前检查当前 resource.read，实际模型/工具请求继续走原实时准入；权限修订改变时旧 Run 停止。非开发角色不能获得当前唯一写工具 submit_operation；角色名称不额外授予工具或业务权限。当前不支持同一 Session 切换模型、角色/指令或工具包，需使用新 Session；自动 Epoch 切换和历史压缩留在后续接缝。

敏感路径（.env、凭据目录、私钥等）拒绝进入读取或目录投影；明确命名的敏感赋值、URL 凭据和 PEM 私钥块在请求/业务历史前过滤，原文件摘要及行号保留。规则式过滤不构成对任意未知秘密格式的识别保证，来源仍须是受控项目文本。密钥解析继续只在原 provider 出站边界按引用进行。

本次为未发布内部契约的增量字段；调用方按当前 ContextPackage 重新计算 context 摘要。旧模型/工具历史不因升级自动得到新角色能力；原 HTTP 契约、数据库迁移和 DBOS 应用版本不变。上下文开发核对与夹具限制见 [A03 记录](../acceptance/p2/p2-1-a03.md)。A04 的当前工作区读取见下节；A05 写入及完整工程循环尚未接通。

## 工作区目录、读取与搜索

A04 在原 `dispatch_tool(name, arguments)` 接入三条开发角色路由。调用方在新的 ContextPackage.tool_names 中显式授予工具，并绑定新的 Context 摘要；同一 Session 仍不能更换工具集合，旧 Session 不自动升级。工具参数 JSON Schema 随上下文送达模型。

每条路由均需 `workspace_id`，只允许读取当前 Run 的项目、Task 和 WorkItem 所属且已物化的工作区。Gateway 先按当前 Run 和 `resource.read` 取得既有 WorkspaceReadSpec，再由 worker 在受管存储与原读锁下读取；参数不接受宿主路径、外部仓库、任意 commit 或执行命令。验证/审查角色的固定候选工具由 P2.5 接入，本包不授予它们可变工作区读取。

|工具|参数与返回|
|---|---|
|`workspace.list_directory`|`path` 默认空根、`offset` 默认 0、`max_entries` 默认/最多 64；列出直接子目录和文件，返回总数、路径、文件摘要/大小、`truncated/next_offset`|
|`workspace.read_file`|必填相对 `path`；`start_line/start_column` 默认 1、`max_lines` 默认 120/最多 160；单文件最多 64KiB，返回最多 8192 字符的安全 UTF-8 文本、文件摘要、总行数、截断及 `next_start_line/next_start_column`，长行可继续读取|
|`workspace.search`|`query` 为 1～256 字符、区分大小写的单行字面文本；`path` 默认空根，可限制到目录或文件；`offset` 默认 0、`max_results` 默认/最多 32；每个命中行返回首个位置、文件摘要和最多 240 字符片段，按 UTF-8 路径及行号续读|

结果共同返回工作区 `binding`（含版本、写入代次与基线）和当前文件 `manifest_digest`。续读传入前页摘要作为 `expected_manifest_digest`；文件视图改变即返回 `workspace_manifest_mismatch`，应重新定位，不能拼接成同一版本。目录/搜索 JSON 页面限约 32KiB，超量明确标记截断并提供下页 offset。读取/搜索的行列针对过滤后的安全文本；原文件摘要保留。

敏感路径不会进入目录/搜索结果，也不能直接读取；文本先复用 A03 秘密筛选再返回或搜索。搜索跳过超过 64KiB 或非文本文件并分别计数；分页中计数只覆盖已扫描前缀，`skipped_counts_complete=true` 才表示整个所选范围已扫描。参数、范围及可预期读取拒绝返回固定 code，不回传原始输入或存储异常。

本工具提供当前文件观察，不形成固定候选或验收证据。原 manifest 只涵盖文件，空目录增删不会改变其摘要；规则式秘密筛选不保证识别所有未知格式，来源仍须受控。实际开发核对及夹具范围见 [A04 记录](../acceptance/p2/p2-1-a04.md)。

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

当前源码版本为 `0.18.0`，新库 head 为 `0016_p2_merge_queue`；本包未新增迁移。DBOS 应用继续为 `cloudhelm-hub/0.7.0`，workflow/step 顺序不变，等待续接由结果事务入队。旧安装仍不会由 initialize 自动升级；固定旧快照的受限维护入口继续固定在 `0011`，保持 recovery_required，不能直接运行新 Runtime。
