# 基础 Desktop 与项目同步

正式工程位于 [apps/desktop](../../apps/desktop/README.md)，界面采用工程工作台。源码版本为 `0.24.0`，同步协议为 `p1-sync-r1`；DBOS 工作流应用独立保留 `cloudhelm-hub/0.7.0`。本入口覆盖 P1.5-01/02 及 A10 Task Agent 接线；单 worker 故障与控制延迟见 [P1.5-02 记录](../acceptance/p1/p1-5-02.md)，完整 P1 出口分别取证。Agent 启动参数与权限见 [Runtime 说明](p2-runtime.md#task-页面与-http-入口)；固定恢复副本的收尾使用 [本机维护 CLI](p1-delivery.md#31-独立恢复副本的受限维护)，普通 ready 环境仍可使用交付 API；既有原生调试程序和原生验收证据仍绑定 `0.8.1`，不追认为新版本验收。

## 启动与连接

Desktop 的 npm、Rust/Tauri 构建和调试直接在 Windows 执行，使用 Windows Rust 工具链及 WebView2。依赖由 `package-lock.json` 和 `src-tauri/Cargo.lock` 固定，实际工具版本见进度。

```powershell
cd E:\Project\CloudHelm\apps\desktop
npm.cmd ci --no-audit --no-fund
npm.cmd run desktop:dev
```

生成本机调试程序：`npm.cmd run desktop:build -- --debug`；输出为 `src-tauri/target/debug/cloudhelm-desktop.exe`，不生成安装器。图标的矢量源为 `src-tauri/icon.svg`，可用 `npx.cmd tauri icon src-tauri/icon.svg --output src-tauri/icons` 重建，只维护实际引用的 `icon.ico`、`icon.png`。

Hub、数据库和 worker 仍在 WSL Ubuntu-24.04 运行，初始化、用户、项目、签发会话和服务启动见 [Hub 开发说明](p1-hub.md)。新隔离库迁移 head 为 `0017_p2_agent_entry`，线性承接 `0016_p2_merge_queue`；旧安装不由 initialize 自动升级。不得为打开 Desktop 清空旧库或绕过恢复门禁；recovery_required 的独立维护副本不提供普通 Desktop 连接。

在“连接”页输入 HTTPS Hub 根地址，勾选导入后点击连接，使用系统文件选择器选择受控交付到当前 Windows 用户的会话凭据文件。文件内容不进入页面或剪贴板；原生层验证会话后保存到 Windows 凭据存储，服务名为 `com.cloudhelm.desktop`，按 Hub 地址区分条目。后续可取消勾选直接使用已保存凭据。断开不取消服务端任务；删除本机凭据不等于服务端撤销会话。

本机 WSL 联调可使用显式 `--dev-loopback-port 19080` 的 API 和 `http://127.0.0.1:19080`，并主动勾选允许本机 HTTP。普通地址强制 HTTPS、系统 TLS 校验且不跟随重定向；拒绝 URL 认证信息、路径前缀和查询参数。loopback 联调不构成正式 TLS 安装验收。

## 使用

- 连接后选择获授权项目；首批列表之外的项目可按 ID 打开。快照包含当前可用动作，按钮据此启用，每次命令仍由服务端重新授权和核对版本。
- “提交任务”使用已完成的参照源码导入 Operation，填写目标及预算；也支持包含已登记引用的完整 TaskDeclaration。不存在的来源/证据会被真实拒绝，不自动补造。创建与启动分开，启动仅适用于 draft。
- 任务详情展示工作项、输入/控制修订和具体阻塞对象。取消须填写原因；取消已请求、停止待确认和实际取消按业务事实显示，客户端不释放资源或填入执行器证明。
- “Agent 推进”在 active/USD Task 上按当前权限选择工作项、填写预算预留及有界限制后启动；继续沿原 Session 版本/历史和策略。查询真实 Run/工具/费用/等待，按该 Session 的工作项读取 diff；长工具沿原等待续接。控制事实核对和取消仍使用 Task 入口，不把 Run 成功写成 Task 完成。A10 编译/定向证据与原生未验收边界见 [A10 记录](../acceptance/p2/p2-1-a10.md)。
- “部署批准”从固定计划读取目标、起始状态、Release、配置修订、数据库影响、步骤和停止核对策略。核对完整摘要并设置不晚于计划截止的有效期后批准；没有批准权时禁用按钮。批准记录不表示已经执行。
- “交付对象”读取真实 Release、配置和环境。“原操作查询”按原 Task/Workspace/开发环境及 Operation，或按部署计划 ID 查询业务/物理状态；unknown 不转为失败或自动重放。
- 回执与当前状态分别显示。HTTP 202 只表示可靠接收，完成依据业务完成报告和 Delivery 投影，不使用 DBOS 状态代填结论。

管理网络从受限原生桥发出，页面没有通用 HTTP、文件、Shell 或预览 IPC 权限；CSP 禁止 iframe，P2 预览尚未接入。

## 快照、SSE 与断线

|接口|语义|
|---|---|
|`GET /api/projects/{project_id}/snapshot`|同一 PostgreSQL REPEATABLE READ 事务读取当前授权、业务投影、版本和已提交分发游标；每类最多 100 个对象，整个 JSON 最多 2 MiB，超限返回 `snapshot_scope_too_large`，不截断快照|
|`GET /api/projects/{project_id}/events?stream_id=...&after=...&permission_revision=...`|通过 bearer 头认证；SSE 约 25 秒后重订阅，每两秒在控制池的独立短事务中重新授权，并分发/读取最多 32 条已提交事实；等待不持有数据库连接或模型/执行槽|

同步模块锁定项目持久计数器，在同一短事务中写 DispatchEvent、递增游标和标记 Outbox，按分发提交顺序分配游标，不使用业务 ID 或创建时间代替提交游标。事件只携带允许的聚合标识/版本和 schema 元数据，作为刷新提示；客户端重新取得一致性业务快照，不将事件 payload 变成另一套权威状态。

公开流身份由持久项目流 ID 与 API 启动代次组成。API 重启或旧备份恢复后，旧订阅收到 `snapshot_required`；客户端重建不能解除数据库恢复门禁或恢复普通自动执行。本轮按 light 单 API 进程接入，没有多 API 实例共享启动代次的支持结论。

权限修订变化时关闭旧范围并重建；撤权/会话过期时清理当前范围，等待重新连接。事件缺口、旧流、失效游标或协议不兼容不能继续套用旧投影。断线显示上次快照时间并暂停普通写入，取得当前权限和新快照后恢复。当前业务没有公共硬删除入口，tombstones 为空；增加删除或事件裁剪前须先实现墓碑及重放窗口维护。

查询和控制沿用 API 独立控制连接池。当前普通工作流槽及普通数据库池饱和时的定向方法和实际延迟见 [P1.5-02 记录](../acceptance/p1/p1-5-02.md)，不将其当作尚未接入的 P2 模型槽或整机容量结论。

## 未确认命令

发出写请求前，原生层将 Hub/当前用户、路由、原请求和幂等键同步提交到本机应用数据目录的 `commands.sqlite3`，最多保存 100 条未确认命令。此库不保存 bearer 或权威业务状态；当前业务详情/事件缓存仅驻内存。

收到带原 command_id 的确定回执后，原生层先持久化回执，当前连接的界面展示后再确认清理。网络/提交未知、撤权或不带 command_id 的 schema 拒绝不能证明原操作未执行，继续保留原请求。连接相同 Hub/用户后显示待确认项；重投由原生层从该账户日志读取原正文和幂等键，并经 Hub 重新授权，界面不能更换正文或账户重投。

新请求和从日志恢复的请求分别在原生入口完成一次路由、幂等键和正文边界校验，私有发送函数消费已校验的请求。重投只读取原请求；持久回执仍在收到确定响应时核对 command_id，并在界面确认后清理。

每次连接/断开使用单调代次，凭据与已验证账户保存在同一个原生会话；旧请求、订阅和组件回调不能借用新会话或覆盖其结果。发送前失败后读取实际原生日志，日志读取失败则保守保留待确认项。同一操作入口存在未知命令时先核对，其他对象的查询/取消不被它封锁。无 command_id 的拒绝可能长期占用名额和同一路由，当前没有人工解除入口；不可直接删库当作原操作未执行。该机制不构成断电耐久、SQLite 损坏恢复或原生交互验收。

## 定向检查

Windows 使用 `npm.cmd run build`、Rust 编译和所需的本机 Tauri 构建；CI 只构建前端，不把 Linux CI 编译当作 Windows 原生证据。

WSL 的 `uv run --locked --offline --no-sync python -m scripts.p1.check_sync` 使用唯一临时 PostgreSQL 项目和 loopback `55436`，核对迁移、未分发状态快照、分发回滚/去重、流/权限重建和一条有限 HTTP SSE，只清理自己的临时资源，不启动业务 worker、模型或远端部署。HTTP 快照仍用 `scripts.p1.check_public_contracts` 核对。

实际结果与未执行范围见 [PROJECT_PROGRESS.md](../../PROJECT_PROGRESS.md)。编译、浏览器或启动结果不替代原生/人工产品验收。
