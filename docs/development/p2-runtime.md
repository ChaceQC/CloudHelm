# 有界 Agent Runtime

实际 Python 包为 `modules/agent_runtime/` 和 `modules/tool_gateway/`。源码 `0.27.0` 覆盖内部 Runtime、工程工具、有界开发循环、既有 Task 页面入口、独立验证、只读审查及反馈返工交接。固定 notes 需求的真实模型工程闭环、候选/构建结果与支持限制见 [A11 记录](../acceptance/p2/p2-1-a11.md)；验证角色的内部启动与受控阶段见[正式验收说明](p2-verification.md)，固定差异、证据及结构化反馈见[审查说明](p2-review.md)，返工入口及关闭依据见[返工说明](p2-rework.md)。

已有单 Agent 尝试、逐请求费用和时间/人工采集缺口归档在 [P2.5-02 早期基线](../acceptance/p2/p2-5-02.md)，可从公开脱敏字段复算费用小计和覆盖率。该记录不是 P3.4 冻结后的正式单/多 Agent 对照。

源码 `0.15.0` 在新 Run、实际请求/工具及结果提交边界读取[工作区写入权](p2-handoffs.md)。接管期间本工作项停止新推进；交还后须先复核输入，后续 Run 收到固定人工修改及差异引用，旧 Run 不恢复普通写入资格。

## 启动与上下文

在 WSL 的现有 worker 环境配置 `CLOUDHELM_AGENT_MODEL_KEY_FILE`；文件为当前服务用户所有的普通 UTF-8 文件，权限只允许该用户读写，最多 4096 字节。只填写实际密钥，不能提交或打印文件内容。`CLOUDHELM_AGENT_MODEL_BASE_URL` 可指定受控 Responses 端点，默认官方 `/v1`；配置只由 worker 读取，模型输入和 DBOS 参数不携带凭据或宿主文件路径。

内部入口为 `AgentRuntimeApplication.start(source_command_id, RuntimeStartRequest)`。来源必须是已接受、可恢复真实调用者且当前仍具有该 Task 命令权限的持久命令；它不以匿名身份或调用方自报权限启动。模型配置固定为 `default-responses / 1 / gpt-6-luna`，可选 `secret_version_ref` 只能指向同一受控配置和修订。

`RuntimeStartRequest` 包含既有 `RuntimeInput`、受限 `ContextPackage` 与 `RunPolicy`。Context 只含当前 InputSet、工作项修订、需求/验收/源码等引用、选定文件摘要/行范围、工具和权限/预算快照；上下文引用的摘要必须与实际内容一致。初次历史引用以 Session ID 为 `object_id`，`revision` 为 `0`，内容摘要为 UTF-8 `[]` 的 SHA-256。后续使用返回的完整历史引用与新 Session 版本。

启动在一个短事务内写 Session、Run、WorkflowBinding 并使用公开 `enqueue_in_transaction` 入队；相同 Run/正文返回原身份，异正文拒绝。同一 Session 同时最多一个 queued/running Run。worker 的 `models` 队列并发为 1，仍保留原控制队列；这是当前软件限制，不是容量验收结论。

### Task 页面与 HTTP 入口

在既有 Task 页先启动 Task，再选择工作项、填写单次请求预留上限和有界请求/时间/输出限制，点击“启动 Agent Run”。当前模型固定 `default-responses / 1 / gpt-6-luna`，只支持 USD Task。开发推进需要当前 `task.command` 和工作区写入权限；项目 owner 默认不含 `workspace.write`，须由项目管理入口明确授予开发动作。工具仍分别执行 `workspace.write`、`candidate.submit`、`operation.query` 等当前授权，不因页面可启动而获得全部工具权限。

|接口|行为|
|---|---|
|`POST /api/tasks/{task_id}/agent-runs`|`Idempotency-Key`、Task 三版本、`work_item_id`；新 Session 明确提供 `per_request_cost_upper_bound`，请求/时间/输出默认 3/60 秒/4096。服务端装配真实当前 InputSet、需求/验收/源码、开发角色/工具和预算快照，不接受客户端自报权限、内部 Context 或成功事实|
|`GET /api/tasks/{task_id}/agent`|独立控制池按当前 `resource.read`、`operation.query` 返回 Session/Run、真实结果和交接、工具返回、模型请求金额及等待。未知金额为 null；不返回 prompt、模型请求体、工具调用参数或完整历史|
|`GET /api/tasks/{task_id}/agent-diff/{work_item_id}`|按明确 Task/工作项读取其工作区相对物化基线的当前差异；读取前后复核授权与 binding。不是固定候选或验收证据|

初次启动复用工作区创建服务，把缺失工作区绑定到所选现有工作项，不新增第二个工作项；`pending` 或仅因 `capability_not_enabled` 阻塞的初始项在当前命令中进入 running。来源仍须是受控真实工程输入；不把协议夹具升级成产品来源。命令回执、工作项/工作区、Session/Run、WorkflowBinding 与 DBOS 入队同事务提交，失败一起回滚。202 仅表示接受；API 不读取模型密钥或启动模型执行器，worker 配置缺失仍是实际失败。

“按原策略继续”提交原 `session_id` 和 `expected_session_version`，沿已提交历史创建新 Run，不接受同时改写原策略。已有活动 Run、原长工具等待、旧工作项归属、输入/控制版本冲突及 Task 关闭继续由服务端拒绝；长工具沿原等待自动续接，不以手动继续跳过。新 Session 也不能越过同工作项的在途 Run/等待。取消与核对复用原 Task 命令；界面不新增独立暂停或强行重放按钮。

验证/审查 Run 提交真实交接时，同事务保存问题及面向原开发会话的事件；阻塞问题使原工作项回到 ready 并推进修订。开发者按上述入口显式继续，Context 的 `rework` 带入未关闭或关闭依据失效的问题、原候选/证据、受影响检查和复发引用；沿原编辑、候选和构建工具推进，新检查交给独立验证/复查。没有新增自动调度或以开发自测关闭问题的权限。

状态按钮显式读取当前持久事实，现有项目快照变化也刷新 Agent 投影；没有独立轮询器。结果最多最新 8 Session、每 Session 8 Run、每 Run 16 条工具反馈，单字符串最多 4096 字符，Run 投影合计最多 512KiB；截断明确标记。差异最多 16 文件、单文件 8KiB、合计 32KiB，敏感路径不展示，识别到秘密的补丁整体显示 `[REDACTED]`。这些限制沿用规则式筛选，不扩大对未知秘密格式的支持结论。

API 进程读取当前差异时需与 worker 使用同一受保护的 `CLOUDHELM_ENGINEERING_REGISTRY_FILE` 和受管存储；只通过原 `EngineeringRegistry.admit(0)` 与文件服务读取，未配置/未物化/不可用时显示真实原因，不读取任意宿主路径或启动执行器。新隔离库 `0017_p2_agent_entry` 只增加 API 的 Session/Run INSERT 及 Session state UPDATE，模型请求、历史与结果仍由 worker 写入。旧安装不由 initialize 自动升级；维护副本仍固定 0011，不能为使用新入口绕过恢复门禁。

## 能力与每次准入

|固定能力|当前支持|
|---|---|
|模型与协议|`gpt-6-luna`、PydanticAI 2.55.0、Responses 文本；本次方法按 2026-10-28 固定|
|工具|`task.read`、`submit_operation`、`query_operation`、`await_operation`，以及开发角色的工作区读取/编辑/diff 和环境准备/控制/状态/实时日志工具；逐次准入并顺序执行|
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
|运行策略|RunPolicy 的 role 默认 developer，instruction_revision 新默认 agent-r2；共同协议及角色指令通过 SDK instructions 提交，r2 开发指令接通有界循环，显式 agent-r1 保留原文本协议；项目正文只作为数据|

例如源码片段为 `{"path":"src/main.py","digest":"sha256:<完整文件摘要>","purpose":"source","start_line":1,"max_lines":120}`。默认不装入整个仓库；每个 Context 最多 8 个显式片段、每片最多 160 行、单文件最多 64KiB、源码返回正文合计最多 32KiB，安全路径索引最多 64 条。返回真实摘要、总行数、截断与 next_start_line；续读时在下一份 Context 中指定同一来源及新起始行。规范未读完整时不得宣称已覆盖其全部约束。非空 source_prefix 尚不支持，因为当前 Git 子树视图无法保证读取前缀外的继承规范，明确拒绝。

人工修改最多装入 32 项可见变更和前 8 项差异，差异正文合计 8KiB；超量、二进制和不可生成正文保留真实标记及原交还查询引用。最终 JSON prompt 上限 64KiB，超出时拒绝；不会静默丢弃需求、证据或未决项。DBOS 参数仍只有 run_id，结果仍是有界引用；经筛选正文仅进入内存请求及既有 256KiB 上限的业务 SDK 历史，不进入工作流参数/step 返回。

读取前检查当前 resource.read，实际模型/工具请求继续走原实时准入；权限修订改变时旧 Run 停止。非开发角色不能获得 submit_operation 或当前工作区工具；角色名称不额外授予工具或业务权限。当前不支持同一 Session 切换模型、角色/指令或工具包，需使用新 Session；自动 Epoch 切换和历史压缩留在后续接缝。

敏感路径（.env、凭据目录、私钥等）拒绝进入读取或目录投影；明确命名的敏感赋值、URL 凭据和 PEM 私钥块在请求/业务历史前过滤，原文件摘要及行号保留。规则式过滤不构成对任意未知秘密格式的识别保证，来源仍须是受控项目文本。密钥解析继续只在原 provider 出站边界按引用进行。

本次为未发布内部契约的增量字段；调用方按当前 ContextPackage 重新计算 context 摘要。旧模型/工具历史不因升级自动得到新角色能力；原 HTTP 契约、数据库迁移和 DBOS 应用版本不变。上下文开发核对与夹具限制见 [A03 记录](../acceptance/p2/p2-1-a03.md)。A04 的当前工作区读取及 A05 写入见下节；完整工程循环按后续工作包接通。

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

## 文件创建、精确补丁与差异

A05 在同一 Gateway 接通以下开发角色工具。创建和补丁必须携带 `workspace_id`、相对 `path`、准确的 `expected_workspace_revision`、`expected_write_generation` 及 `expected_manifest_digest`；来源是本轮读取结果的 binding/manifest，不接受宿主路径或任意命令。

|工具|输入与实际行为|
|---|---|
|`workspace.create_file`|`content_utf8` 为最多 64KiB 的 UTF-8 正文，允许空文件；`mode` 为 `100644`（默认）或 `100755`。目标须不存在，父目录须已存在；不隐式新增目录|
|`workspace.apply_patch`|`expected_file_digest`、非空 `old_text` 和 `new_text`；从实际旧文件匹配摘要，仅当旧文本恰好出现一次（含重叠匹配）才精确替换，保留原 mode。旧/新正文及替换结果均限 64KiB，零匹配、多匹配、不变或非 UTF-8 文本明确拒绝|
|`workspace.diff`|`workspace_id`、相对 `path` 和可选 `expected_manifest_digest`；相对物化时的固定基线显示真实 diff，返回 binding、前后文件元数据、binary/truncated/reason_code。沿原文件服务输入限额，筛选后的 patch 最多 8KiB；这是当前观察，不是固定候选证据|

Gateway 每次取得当前 Run、Task/工作项归属及 `workspace.write`/读取权限；编辑准备在原受管存储与根锁下读取并匹配版本、代次、manifest 和旧文件。内容在短命令事务外沿既有受控存储暂存；真正接受命令时再次检查当前 Run 与领域写入门禁，并在同一事务保存原变更意图和 DBOS 入队。实际执行继续使用原文件日志和发布路径，接管期间、旧 Run、旧版本或旧代次均无权覆盖当前文件。

写工具返回 accepted 的原 Operation 引用；需要结果时用现有 `query_operation`/`await_operation`，不以提交回执表示文件修改成功。变更回执登记同事务通知原等待，完成后取得新的 binding，再继续读取或修改。稳定 Run/tool-call 身份关联规范参数摘要：同次调用同参数返回原回执，异参数拒绝，不重新准备或暂存。修改后沿既有候选采集形成固定快照，不新增另一套 Git 或候选状态。

秘密路径、`.gitmodules`/`.lfsconfig` 和明显秘密正文拒绝编辑；含已被读取工具筛选的秘密正文不能用脱敏文本覆盖。该规则沿用 A03 的筛选范围，可能拒绝含敏感字段名的普通源码，且不保证识别所有未知格式。模型正文只在内存准备/受限 SDK 历史及原受控内容存储流转，命令、工作流参数和结果仍只保存元数据与引用；不写日志或错误正文。支持范围与必要定向结果见 [A05 记录](../acceptance/p2/p2-1-a05.md)。环境、构建和自测分别由 A06～A08 接通，完整真实开发循环由 A09～A11 承接。

## 依赖准备、开发环境与实时日志

A06 在新 ContextPackage 显式授予下列开发工具，限当前项目、Task 和 WorkItem。只支持已登记的 `notes-backend-dev-r1`、固定 Python/uv、离线 wheel 种子、原锁及合成 PostgreSQL 数据。prepare 包含依赖、迁移、启动和就绪探针；resume 复核当前源码/锁并复用或准备准确依赖，不接受命令、宿主路径、镜像或自定义安装源。

|工具|输入与实际行为|
|---|---|
|`workspace.prepare_environment`|`workspace_id`、`expected_workspace_revision`、`expected_write_generation`；提交原 prepare，返回 accepted 回执|
|`workspace.control_environment`|上述字段及 `environment_id`、`action=suspend/resume/dispose`、`expected_environment_revision`、`expected_data_revision`、`expected_data_generation`；按准确版本控制，Agent 不开放 reset_data|
|`workspace.environment_status`|`workspace_id`；返回最近环境或 null，含 binding、环境/数据修订及代次、pending 操作和最近带时间戳观测；历史 ready 不证明进程现在仍活着|
|`workspace.environment_logs`|`workspace_id`、`environment_id`、`service=backend/postgres`、`max_lines`（默认 80，最多 160）；返回准确运行中非 TTY 容器约一秒的实时窗口、容器身份、UTC 时间、最多 8192 UTF-8 字节及截断标记|

准备与控制使用规范参数摘要和稳定 Run/tool-call 身份，同调用同参返回原操作，异参及跨工具身份复用拒绝。可信规格在事务外读取，正式接受的短事务重新检查当前 Run，再经原 Task/写入权/资源门禁写入并同事务 DBOS 入队。长动作单条成批；accepted 仅表示收到，原 `query_operation`/`await_operation` 提供最终 observation，pending/unknown 保留等待，最终回执与原等待通知同事务交接。

日志返回 `source=live`、`history_available=false`，空窗口为真实空文本，不回读启动前输出。Docker 日志驱动仍为 none；原始捕获最多 64KiB/160 行，仅在有界内存中沿 A03 规则筛选，不保证识别任意未知秘密格式。关闭 socket 不写 stdin、不发信号、不停止容器。读取后重新检查当前 Run；原控制器仍要求原操作主体当前具备写入和操作查询权限，撤权时拒绝。状态、停止、分维释放和保留磁盘继续归原 Runner/账本负责。

旧 Context/Session 不自动获得新工具；同一 Session 仍不能换工具集合。本次不改 HTTP、数据库、DBOS 应用或工作流步骤。参数、证据及本机真实 notes 启动被旧执行核对门禁拒绝的范围见 [A06 记录](../acceptance/p2/p2-1-a06.md)。构建、自测接线见下文，完整真实循环由 A09～A11 承接。

## 固定候选构建与结果

A07 在新的开发角色 ContextPackage 中显式授予下列内部工具；参数 Schema 随上下文提供。

|工具|参数|作用|
|---|---|---|
|`workspace.submit_candidate`|`workspace_id`、`expected_workspace_revision`、`expected_write_generation`、`expected_manifest_digest`|沿原工作区冻结命令提交准确物理候选；返回原 Operation 的 accepted 回执|
|`build.request`|`workspace_id`、`candidate_id`|对当前工作项已登记的不可变物理候选申请真实 BuildRun；返回原构建 Operation 回执|
|`build.result`|`operation_id`；可选 `log_role=backend/frontend`、`log_offset=0`、`max_bytes=8192`（4～8192）|返回原 BuildView 与有界日志/失败诊断；状态、执行观察、固定输入和制品引用保持原事实|

先提交物理候选，按需 `await_operation` 取得含 snapshot/candidate_id 的最终采集回执，再提交构建；需要构建结果时等待同一 Operation。候选及构建回执在原登记事务中通知可靠等待，新 Run 按原协议续接。pending/running/unknown 不解除等待，accepted 不表示成功；构建成功、失败及退出码以原 BuildView/观察为准，日志的逐命令退出码不替代整次构建结论。

构建请求只接受当前项目、Task 和 WorkItem 的物理候选。服务端从该候选的实际字节计算已支持的 notes 离线构建声明，固定 recipe、锁、工具链、基础镜像、运行契约及验收引用；模型不传命令、宿主路径或构建定义。声明读取在事务外，接受事务重新检查当前 Run，沿原 `accept_build` 同事务入队。构建继续读独立快照，后续工作区编辑不改变该轮输入。同 Run/tool-call/规范参数重投返回原命令，异参或跨工具复用身份拒绝。

当前后端配方允许既有 `app/*.py` 文件的候选修改，实际字节摘要纳入 source manifest 与构建 input_key；其余参照文件、依赖/锁、迁移及受控配方继续固定，新增文件成员仍不在此配方支持范围。参照读取入口保持原全量摘要校验，不能用候选模式替换正式来源或验收资产。

后端 OCI 内容逐文件对照同一已固定候选的实际源码摘要；运行配置、证据文件、层成员及制品摘要仍沿原规则核验。

后端配方变体 `fixed-notes-python-offline-r3` 在独立 `runtime-check` 阶段导入候选应用，最终镜像从未执行候选代码的 `candidate-runtime` 层继承，只复制该检查的 JSON 结果，避免导入副作用写入最终依赖或增加运行文件。该构建检查继续属于开发证据，独立验证/安全审查由后续受控资产完成。

`build.result` 限当前工作项和原命令主体，并检查当前 `resource.read`、`operation.query`；私有 journal 的 intent 必须等于原 BuildRun，读取后复核当前 Run。查询不创建 Runner、启动命令或重放未知构建。`build` 是业务记录，`diagnostics` 是读取时的原物理 journal，二者可能在构建收尾期间处于不同观察时点；不能据诊断文字提升业务状态。


新构建在实际命令返回后保存筛选过的 stdout、stderr（按该顺序拼接），每条命令最多保留末尾 64KiB；后端运行镜像及依赖检查、前端构建分别记录真实退出码、UTC 捕获时间和截断标记。日志先按 A03 规则筛选再限长入私有文件，不保存新增原始日志；未知秘密格式仍受原筛选限制。返回页按保留文本的 UTF-8 字节偏移续读，使用 `next_offset`；可分别查询 backend/frontend。命令尚未返回、早期失败或旧构建没有日志时如实返回 unavailable，不能补造历史日志。

该工具固定的是构建源码快照及 BuildFixedInputs；后续正式验证环境与三类事实仍由既有 `FixedCandidateApplication.fix` 登记，不因构建工具接通自动形成正式验收或完成报告。现有受限 notes 配方、受管资源/停止核对、内容及输入适用性边界保持原范围。软件 `0.21.0`；无 HTTP、数据库、依赖或 DBOS 应用版本变化。方法与未验证范围见 [A07 记录](../acceptance/p2/p2-1-a07.md)。

## 项目自测与静态检查

A08 在新的开发角色 ContextPackage 中显式授予 `workspace.check`。参数为 `workspace_id`、`environment_id`、准确的 `expected_workspace_revision`、`expected_write_generation`、`expected_manifest_digest` 和单个 `check`；不接受命令、脚本、路径、安装源或自定义断言。

|检查|实际执行与覆盖范围|
|---|---|
|`backend.syntax`|在已登记 notes 后端容器用固定 Python 编译检查 `backend/app`、`backend/migrations` 下的 Python 源码；不导入或执行项目代码，不写 pyc。最多 256 文件、单文件 256KiB、合计 2MiB，进程内限时 5 秒；语法失败返回相对文件、行列与筛选后的错误信息，最多展示 8 项并保留失败总数|
|`backend.http`|复用固定 notes 只读 GET 探针，核对 `/health`、`/ready`、`/api/notes` 的状态、数据结构和已登记合成种子；返回响应摘要，失败返回固定原因及已观察到的 HTTP 状态。`/devmarker` 沿原探针读取，不作为通过门槛；不包含 CRUD、前端、任意项目测试框架或正式验收|

先准备环境；工作区编辑后用现有 `workspace.control_environment(action=resume)` 刷新到当前源码/绑定，再读取新 binding 与 manifest 发起检查。Gateway 在执行前后检查当前 Run、`workspace.write`/读取权限、当前 Task/WorkItem、工作区版本/代次、环境绑定/修订及未收尾写入/环境操作。检查在事务外执行，沿原受管存储与登记容器身份，前后观察实际源码摘要；陈旧输入、接管、撤权或环境变化不能返回通过。

每次仅执行一项固定短时只读检查，Docker 请求限时 8 秒，直接返回结果，不创建 Operation 或新的可靠等待链。`status=passed/failed/unknown`、`exit_code`、UTC 起止时间、binding、源码摘要、检查方法修订/摘要、容器身份及 `evidence_digest` 一并返回；传输超时退出码为 null，源文件缺失/限额或执行器异常不冒充测试失败或成功。没有新的原始日志持久化，API 正文不返回模型；语法诊断沿 A03 规则筛选，仍保留其未知秘密格式限制。

这是开发反馈，不登记 VerificationRun、正式验收报告或 Task 完成事实。正式验收继续读取独立受控资产；工具不能修改入口、关键断言或跳过规则。当前仅支持 `notes-backend-dev-r1`；真实受管容器及完整 Agent 循环另取证，方法和限制见 [A08 记录](../acceptance/p2/p2-1-a08.md)。

`notes-developer-check-r2` 将固定探针已读取的 `devmarker_status`、`devmarker_digest` 一并返回；它们不改变 health/ready/notes 的通过门槛。针对该接口的需求须另核对实际状态和期望正文摘要，不能仅据 `backend.http.status=passed` 宣称该需求通过。

## 有界开发循环

A09 复用同一个 PydanticAI `Agent.run` 和现有 Gateway 路由推进开发，不建立额外调度器或循环状态机。新建开发 Session 使用 `instruction_revision=agent-r2`；明确读取需求与调用关系、最小修改和 diff、刷新环境绑定、必要检查、按实际失败修复，以及固定候选后构建/读结果的顺序。工具未获授予时不能因指令获得权限。模型文字不代替执行结果，开发检查不产生正式验收结论。

`RunPolicy.max_no_progress_calls` 默认 2，范围 2～16，随 Run 固定。相同工具、参数和已见反馈连续重复两次（包括首次共三次）时停止；`workspace.check` 的判定排除本次起止时间及其派生 evidence_digest，保留源码、方法、退出码和具体失败等变化。原结果完整摘要仍保留。该阈值按单 Run 计算，与请求、时间和费用上限以先触发者为准；阈值大于本轮可用请求次数时可能先按请求上限交接，不跨 Run 增加另一套状态。

开发输出 `DevelopmentHandoff` 包含 `reason`、`summary`、`next_action`，以及仅 `candidate_ready` 必填的 `candidate_operation_id`：

|原因|保存及后续行为|
|---|---|
|`candidate_ready`|回查原候选操作的当前主体/工作项、实际注册回执、当前 workspace binding 及同一 InputSet/控制/输入修订；准确 snapshot 和输入引用写入交接。返回 `submitted` 及指向本 Run 持久交接正文的 delivery 引用；不表示独立验证、审查或 Task 完成|
|`human_decision_required`|保存具体问题、对象/版本、影响和下一步，Session paused；真实决定后才可按当前授权新建 Run，未实现人类决策自动唤醒|
|`no_progress` 或运行时 `agent_no_progress`|保存重复次数、阈值及最近反馈摘要，Session paused；先定位实际阻塞再由有权者安排下一 Run|
|`continue_required` 或请求/输出上限|保存当前进展和实际原因，以既有 continue_required 交接，不自动入队普通继续 Run或自行扩额|
|预算、权限、超时或未知失败|保留准确固定原因、请求身份、费用占账及实际 SDK 历史，Session paused；超时不证明 HTTP 或物理操作已停止，先按原身份核对。不可恢复错误仍保留 failed，不改成候选成功|

每次真实 HTTP 尝试前仍经过请求记录/当前门禁，普通工具也保留原准入；无进展在下一次请求前停止，同轮请求上限同时触发时优先记录已命中的无进展原因。延迟工具仍提交 `waiting_condition`，由原 Operation 结果事务触发新 Run，并校验原 tool-call ID；不使用模型轮询推进。交接只额外保存最近 4 条工具名、调用 ID 和结果摘要，实际正文沿原 SDK 历史保存。

请求/时间/用量到限时保存已实际捕获的 SDK 新消息；未知错误同样携带已有消息归档，不伪造完整模型响应或 tool return。A11 实测完整工程历史会超过原 128KiB，当前软件将 SDK 历史及数据库约束固定为 256KiB，Run 结果仍为 16KiB；超限仍明确失败，不提供无界归档或自动压缩。请求数、输出、时间和费用门禁不变，不在运行时自行扩额。旧 `agent-r1` 保持原文本输出，停止时同样记录原因；原 Run 缺新增字段且原请求也未显式传入时按原字段形状核对摘要，同参返回原身份，异正文拒绝。既有 Session 不能切换 r1/r2，须新建 Session。



内部方法保留 `AgentRuntimeApplication.start`，A10 从既有 Task 页面经同事务注册接入 A09；定向方法与边界分别见 [A09 记录](../acceptance/p2/p2-1-a09.md)及 [A10 记录](../acceptance/p2/p2-1-a10.md)。真实模型工程循环由 A11 取证。

## 请求结果与费用核对

传输层在每次实际 HTTP 尝试前取得 `request_record_id`，完整读取响应后立即交 `RuntimeBilling.record` 记录安全的供应商响应/请求身份、实际模型、服务档位及 usage；模型修复或重试的每个 HTTP 请求分别记录。失败/取消响应也保留其中实际提供的 usage，连接中断或没有字段时仍未知。落账失败阻断当前调用，不把该失败作为网络错误自动重发。

原请求的正文摘要、顺序和预留不可变，关联结果按修订追加，同请求相同结果幂等。固定计价依据沿用 [P0 决定](../decisions/p0/admitted-runtime.md)：`default` 映射 Standard，全球文本与自定义函数没有供应商托管工具收费；金额使用 `Decimal`，绑定官方价格修订。输入总量、缓存读取、缓存写入、输出及适用模型/档位缺少必要字段时，总计算金额保持 null；不从缺失的缓存字段推定 0。兼容提供方的独立账单只有同时提供金额、币种和账单证据才保存。

供应商重复发送 `x-request-id` 时，HTTP 边界按响应顺序取第一个逗号分隔的标识，避免 HTTP 客户端合并多个头后污染单标识字段；内部允许字符及长度校验继续执行，`provider_response_id` 和实际 usage 独立保留。

准入实时汇总已知费用及未知预留；未知时较小账单不释放预留，较大 USD 账单继续占账。真实 usage/金额超过预登记上限仍保存事实并阻断 Task 后续模型和工具准入。

迟到核对使用 `await RuntimeBilling(engine).reconcile(request_record_id, result, actor=..., scope=ModelUsageScope(...), evidence_ref=...)`。scope 绑定原 Task/Session/Run 和当前控制、输入有效性及权限修订；核对重新授权，相同事实/证据幂等，异身份、陈旧 scope、冲突 usage 或证据拒绝。Task 取消后仍可在当前授权下归档费用，不能借此恢复普通推进。

## 长工具提交和等待

当前长操作支持当前 Task/工作项、同一授权主体的 Workspace 物化、文件变更及开发环境准备/控制；需要已登记的产品输入、工作区与当前 `workspace.write` 权限。`task.read({})` 返回当前工作项的 `workspace_id`，没有工作区时为 null。通过现有 `dispatch_tool(name, arguments)` 使用：

|动作|参数|结果|
|---|---|---|
|`submit_operation`|`{"workspace_id":"..."}`|复用 P1 应用事务及执行入队，返回原 `operation_id`、摘要、accepted、查询/等待引用；按原 Run + tool-call ID 去重|
|`query_operation`|`{"operation_id":"..."}`|有界状态及 UTC 观察时间；未登记最终回执时为 unknown|
|`await_operation`|`{"operation_id":"..."}`|已有回执直接返回原结果；否则结束当前 Run，原子保存历史与关联原 tool-call ID 的 WaitCondition|

提交与等待各自独立调用，长动作每批仅允许一条；混入其它调用时，在任何工具副作用之前要求模型拆批。短查询批次最多 8 条，模型真实请求总数仍受 Run 政策限制。accepted 工具返回保留提交语义，不在物理完成后覆写为产物。

物化、文件变更及环境最终回执落库与等待唤醒共用事务；结果早于等待登记时，登记事务重新检查原操作。等待结果已到、当前权限和 Task/输入修订允许、Session 无活动 Run 时，以等待身份唯一派生新 Run/workflow 并事务入队。重复通知不新增 Run；Session 已有活动 Run 时保留等待，在其结束后再检查。unknown 保留等待，暂停、取消、完成或失效输入不自动续接。续接载入完整的已确认工具结果，匹配原调用 ID，使用已保存的 SDK 历史；不额外拼接新 prompt，不发送模型轮询请求。

提交后可以继续不依赖当前操作结果的工作；真正调用 await 后，该 Session 的未配对调用须由对应结果续接，普通新 Run 在模型出站前拒绝。当前未开放跨历史分叉合并、其它领域长工具或长期自动超时维护。P1 原物化回执登记仍要求原主体现有 `workspace.write`，撤权后需按原 P1 受控结果核对入口处理；本包不绕过该权限边界。

## 恢复与结果

DBOS workflow/step 只接收 `run_id`，只返回有界状态、历史引用和请求 ID。合法完整 SDK 历史保存在有界业务历史表，摘要使用固定排序的 UTF-8 JSON；模型凭据只存在当前请求的内存。失败不把原 provider 异常或部分消息交给 DBOS。

SDK 内部只返回新增历史消息，错误只传安全码；请求身份及费用占账由持久请求表读取，传输层按实际准入次数限制出站。能力范围以本页能力表和对应实际限制为准，不另维护无人消费的能力描述对象。

恢复沿原 Run/workflow。已提交 Run 结果时返回原结果，不重新请求或再次创建续接；已有实际请求记录而 step 检查点和完整协议历史缺失时，先沿原请求核对费用并停止自动重发。费用已知不证明丢失的模型输出已经恢复。新 Run 和切换 epoch 的新请求仍使用同一传输门禁，本次不开放自动历史压缩调度或写工具重放。

Run 成功只表示本次有界推进保存，返回 `continue_required`，不完成 Task。执行期间 Task 取消、终态或输入失效关闭新请求/工具；晚到结果只保存需复核事实。Task 控制读取实际 Run 边界和未知费用，不把技术成功当业务完成。

当前源码版本为 `0.24.1`，新库 head 为 `0019_p2_history_limit`，线性承接 `0018_p2_agent_environment` 和 `0017_p2_agent_entry`。0019 将完整 SDK 历史的固定数据库边界调整为 256KiB；0018 使 worker 可沿现有 Gateway 登记开发环境/操作及推进 environment_revision，业务授权仍由原命令处理器检查。DBOS 应用继续为 `cloudhelm-hub/0.7.0`，workflow/step 顺序不变，等待续接由结果事务入队。旧安装仍不会由 initialize 自动升级；固定旧快照的受限维护入口继续固定在 `0011`，保持 recovery_required，不能直接运行新 Runtime。
