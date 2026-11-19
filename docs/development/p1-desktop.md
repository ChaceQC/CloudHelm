# 基础 Desktop 与项目同步

正式工程位于 [apps/desktop](../../apps/desktop/README.md)，界面采用工程工作台。客户端须配对 `p1-hub-api-r2` 的 Hub，连接时核对准确修订；同步协议为 `p1-sync-r1`。单 worker 故障与控制延迟见 [P1.5-02 记录](../acceptance/p1/p1-5-02.md)，其证据仅适用于原输入。Agent 参数与权限见 [Runtime 说明](p2-runtime.md#task-页面与-http-入口)；固定恢复副本的收尾使用 [本机维护 CLI](p1-delivery.md#31-独立恢复副本的受限维护)，普通 ready 环境仍可使用交付 API。

## 启动与连接

Desktop 的 npm、Rust/Tauri 构建和调试直接在 Windows 执行，使用 Windows Rust 工具链及 WebView2。依赖由 `package-lock.json` 和 `src-tauri/Cargo.lock` 固定，实际工具版本见进度。

```powershell
cd E:\Project\CloudHelm\apps\desktop
npm.cmd ci --no-audit --no-fund
npm.cmd run desktop:dev
```

生成本机调试程序：`npm.cmd run desktop:build -- --debug`；输出为 `src-tauri/target/debug/cloudhelm-desktop.exe`，不生成安装器。图标的矢量源为 `src-tauri/icon.svg`，可用 `npx.cmd tauri icon src-tauri/icon.svg --output src-tauri/icons` 重建，只维护实际引用的 `icon.ico`、`icon.png`。

Hub、数据库和 worker 在 WSL Ubuntu-24.04 运行。按 [Hub 开发说明](p1-hub.md)核对新库迁移目标、创建用户和项目、签发会话并启动服务。A10 记录中的 `0017_p2_agent_entry` 是当时的验证基线。旧安装需要受控升级；处于 `recovery_required` 的维护副本不提供普通 Desktop 连接，保留原数据库等待恢复核对。

在“连接”页输入 HTTPS Hub 根地址，勾选导入后点击连接，使用系统文件选择器选择受控交付到当前 Windows 用户的会话凭据文件。文件内容不进入页面或剪贴板；原生层验证会话后保存到 Windows 凭据存储，服务名为 `com.cloudhelm.desktop`，按 Hub 地址区分条目。后续可取消勾选直接使用已保存凭据。断开不取消服务端任务；删除本机凭据不等于服务端撤销会话。

本机 WSL 联调可使用显式 `--dev-loopback-port 19080` 的 API 和 `http://127.0.0.1:19080`，并主动勾选允许本机 HTTP。普通地址强制 HTTPS、系统 TLS 校验且不跟随重定向；拒绝 URL 认证信息、路径前缀和查询参数。loopback 联调不构成正式 TLS 安装验收。

## 使用

- 连接后选择获授权项目；首批列表之外的项目可按 ID 打开。快照包含当前可用动作，按钮据此启用，每次命令仍由服务端重新授权和核对版本。
- “提交任务”使用已完成的参照源码导入 Operation，填写目标及预算；也支持包含已登记引用的完整 TaskDeclaration。不存在的来源/证据会被真实拒绝，不自动补造。创建与启动分开，启动仅适用于 draft。
- 任务详情展示工作项、输入/控制修订和具体阻塞对象。取消须填写原因；取消已请求、停止待确认和实际取消按业务事实显示，客户端不释放资源或填入执行器证明。
- “Agent 推进”先显示可见工作项与能力、近期 Run、尚未续接的等待，以及已列 Run 的已知费用和未知预留。展开某个 Run 才读取该轮工具时间线、请求和证据；切换 Task、连接或权限范围会关闭原详情。active/USD Task 可按权限选择工作项与预算预留后启动，或按原 Session 策略续接；工作区差异单独查询。控制事实核对和取消仍使用 Task 入口，Run 成功不代表 Task 已完成。
- “部署批准”从固定计划读取目标、起始状态、Release、配置修订、数据库影响、步骤和停止核对策略。核对完整摘要并设置不晚于计划截止的有效期后批准；没有批准权时禁用按钮。批准记录不表示已经执行。
- “交付对象”读取真实 Release、配置和环境。“原操作查询”按原 Task/Workspace/开发环境及 Operation，或按部署计划 ID 查询业务/物理状态；unknown 不转为失败或自动重放。
- 回执与当前状态分别显示。HTTP 202 只表示可靠接收，完成依据业务完成报告和 Delivery 投影，不使用 DBOS 状态代填结论。

管理请求由主窗口通过受限原生桥发出。隔离预览在独立 WebView2 中打开，不继承主窗口的管理 IPC。正式预览条件见[预览说明](p2-previews.md)。

## 快照、SSE 与断线

|接口|语义|
|---|---|
|`GET /api/projects/{project_id}/snapshot`|同一 PostgreSQL REPEATABLE READ 事务读取当前授权、业务投影、版本和已提交分发游标；每类最多 100 个对象，整个 JSON 最多 2 MiB，超限返回 `snapshot_scope_too_large`，不截断快照|
|`GET /api/projects/{project_id}/events?stream_id=...&after=...&permission_revision=...`|通过 bearer 头认证；SSE 约 25 秒后重订阅，每两秒在控制池的独立短事务中重新授权，并分发/读取最多 32 条已提交事实；等待不持有数据库连接或模型/执行槽|

同步模块锁定项目持久计数器，在同一短事务中写 DispatchEvent、递增游标和标记 Outbox，按分发提交顺序分配游标，不使用业务 ID 或创建时间代替提交游标。事件只携带允许的聚合标识、版本和 schema 元数据。Desktop 对已知 Task 变化重查对应 Task，按版本跳过已覆盖的事件；Run 排队可能不改变 Task 版本，仍需刷新该 Task。可定位到已打开 Run 的通知只重查该轮。影响范围不明、手动刷新和命令回执走项目快照，同一连接内每个项目最多一个在途请求，期间新触发合成一次尾随刷新。业务事实仍来自当前授权的查询。

公开流身份由持久项目流 ID 与 API 启动代次组成。API 重启或旧备份恢复后，旧订阅收到 `snapshot_required`；客户端重建不能解除数据库恢复门禁或恢复普通自动执行。本轮按 light 单 API 进程接入，没有多 API 实例共享启动代次的支持结论。

新同步范围从快照游标开始订阅；同范围重连从最后实际消费的事件游标续订，即使刷新得到的快照游标更靠前。更换账户、项目、流或权限修订后，旧回包不再更新界面。撤权或会话失效时立即清理旧范围并触发本机收窗，等待重新连接；预览撤销和停止通知同样在普通刷新前触发收窗并使旧预览查询失效。事件缺口、旧流、失效游标或协议不兼容不能继续套用旧投影。断线显示上次快照时间并暂停普通写入，取得当前权限和新快照后恢复。当前业务没有公共硬删除入口，tombstones 为空；增加删除或事件裁剪前须先实现墓碑及重放窗口维护。

查询和控制沿用 API 独立控制连接池。当前普通工作流槽及普通数据库池饱和时的定向方法和实际延迟见 [P1.5-02 记录](../acceptance/p1/p1-5-02.md)，不将其当作尚未接入的 P2 模型槽或整机容量结论。

## 未确认命令

发出写请求前，原生层将 Hub/当前用户、路由、原请求和幂等键同步提交到本机应用数据目录的 `commands.sqlite3`，最多保存 100 条未确认命令。此库不保存 bearer 或权威业务状态；当前业务详情/事件缓存仅驻内存。

原生层确认 Hub 的命令身份并提交本机回执后，才在 IPC 返回 `receipt`，包含 `command_id`、`idempotency_key`、HTTP `status` 和原业务 `result`。界面展示后用回执的键确认清理；已登记的业务拒绝显示具体原因。`202` 显示“已接收”，原 Run、Operation 或对象页面显示当前业务状态。

没有明确回执的 HTTP 响应返回 `receipt: null`；传输或本机日志失败可能使提交结果待核对。连接相同 Hub 和用户后，点击“使用原身份核对 / 重投”。原生层从该账户日志读取原路由、正文和幂等键，Hub 按当前授权查原结果。相同键对应不同的本机请求时明确报冲突，原记录保留。

每次连接/断开使用单调代次，凭据与已验证账户保存在同一个原生会话；旧请求、订阅和组件回调不能借用新会话或覆盖其结果。发送前失败后读取实际原生日志，日志读取失败则保守保留待确认项。同一操作入口存在未知命令时先核对，其他对象的查询/取消不被它封锁。无 command_id 的拒绝可能长期占用名额和同一路由，当前没有人工解除入口；不可直接删库当作原操作未执行。该机制不构成断电耐久、SQLite 损坏恢复或原生交互验收。

## 定向检查

Windows 使用 `npm.cmd run build`、Rust 编译和所需的本机 Tauri 构建。从仓库根目录可运行 `node apps/desktop/scripts/generate-agent-contract.mjs --check`，核对 Agent TypeScript 与固定 OpenAPI；省略 `--check` 输出生成结果。CI 只构建前端，Windows 原生验证另行记录。

WSL 的 `uv run --locked --offline --no-sync python -m scripts.p1.check_sync` 使用唯一临时 PostgreSQL 项目和 loopback `55436`，核对迁移、未分发状态快照、分发回滚/去重、流/权限重建和一条有限 HTTP SSE，只清理自己的临时资源，不启动业务 worker、模型或远端部署。HTTP 快照仍用 `scripts.p1.check_public_contracts` 核对。

实际结果与未执行范围见 [PROJECT_PROGRESS.md](../../PROJECT_PROGRESS.md)。编译、浏览器或启动结果不替代原生/人工产品验收。
