# Hub 基础开发与维护

本文对应 [P1.1 实施说明](../implementation/p1-1-foundation.md) 与当前 [工程开发说明](p1-engineering.md)。Hub API 和单 worker 共用一个 PostgreSQL 数据库，业务表在 `cloudhelm` schema，DBOS 系统表在 `dbos` schema。当前入口用于受信任平台所有者管理的开发环境；构建与增量开发的支持范围见工程说明，基础 Windows Desktop 见[客户端说明](p1-desktop.md)，单 worker、未知资源收尾及恢复门禁的当前证据见 [P1.5-02 记录](../acceptance/p1/p1-5-02.md)，完整 Agent、跨端客户端、远程交付及恢复支持按各自工作包接入。

环境口径：s2413 是用户选定的临时同机组合，现有快照只证明采集时的系统事实；实际安装、配额生效和运行验证分别取证。WSL 结果不能替代这些证据，正式独立目标仍是 P1.4/P1 出口前置。具体方案见 [开发组合决定](../decisions/p0/s2413-development-envelope.md)，分类结果见 [支持矩阵](../acceptance/support-matrix.md)。

## 1. 环境与配置

本仓库的本机工程运行在 WSL `Ubuntu-24.04`，路径为 `/mnt/e/Project/CloudHelm`。解释器固定 Python `3.12.13`，依赖通过根目录 `uv.lock` 管理；PostgreSQL 固定 `16.13`，DBOS 固定 `3.2.0`。

先在当前 WSL shell 定义 uv 路径，本文后续命令统一使用 `$UV`。另开终端运行 API 或 worker 时也要执行该定义。

```bash
cd /mnt/e/Project/CloudHelm
export LANG=C.UTF-8 PYTHONUTF8=1
export UV=/home/cloudhelm/.local/bin/uv
$UV sync --locked
```

为各进程提供独立的 PostgreSQL 认证配置。推荐使用下列环境变量引用受保护的 UTF-8 文件，文件内容是该角色的连接 URL；同一角色只能选择 URL 或 URL_FILE 一个来源。

|用途|配置字段|数据库角色 / 连接上限|
|---|---|---|
|受控迁移、用户与项目引导|`CLOUDHELM_MIGRATOR_DATABASE_URL_FILE`|`cloudhelm_migrator` / 4|
|API|`CLOUDHELM_API_DATABASE_URL_FILE`|`cloudhelm_api` / 6，覆盖最多两个 API 的普通/控制池|
|单 worker|`CLOUDHELM_WORKER_DATABASE_URL_FILE`|`cloudhelm_worker` / 8，包含业务池、系统池和额外监听连接|

配置文件置于 Linux 受限目录，使用所有者专用权限，不放入仓库、工作区、日志或普通客户端缓存。文档命令只引用路径，不打印连接 URL、认证材料或摘要。Runner/Remote Agent 不取得这些 Hub 凭据。

非临时环境由安装维护方准备独立数据库、上述角色和认证文件；服务不自行创建数据库角色。`cloudhelm_migrator` 拥有初始化/维护所需权限，API/worker 没有建库、建角色或 DDL 权限。业务角色与公开 API 动作权限仍分别校验，持有项目角色不等于数据库维护权。

## 2. 受控数据库初始化

以下命令只对当前显式配置的开发数据库执行；首次初始化须是已准备的受控目标。普通 API 和 worker 不执行迁移。

```bash
$UV run --locked python -m database.manage status
$UV run --locked python -m database.manage initialize
```

初始化保存安装身份和原操作身份，执行业务线性迁移至 `0011_p1_archive_maintenance`（前驱 `0010_p1_archive_closeout`），再使用 DBOS 公开同版初始化接口。当前工作流应用为 `cloudhelm-hub/0.7.0`。重复调用已有 `ready` 的同版目标返回原基线；并发维护、未知来源、不同版本或恢复门禁关闭时明确拒绝。包括 `0010_p1_archive_closeout`、`0009_p1_5_sync`、`0008_p1_4_remote`、`0007_p1_4_delivery`/`0.6.0` 在内的旧安装不会由此命令自动升级。中断初始化需要沿原操作身份核对，`--operation-id` 用于已登记的原身份，不用新身份覆盖未知结果。固定 `0008` 快照仅在获授权的独立维护副本中按[受限维护入口](p1-delivery.md#31-独立恢复副本的受限维护)定向升级，升级后仍拒绝普通运行。资源入口和受控 Runner 命令见[共享资源说明](p1-resources.md)，Release/配置/计划与批准见[交付说明](p1-delivery.md)，Remote Agent 的默认门禁见[远端说明](p1-remote-agent.md)。

成功回执中的 `dbos_schema_version` 仍可为 `null`：公开接口没有提供本轮可单独核验的精确数字版本。实际支持依据是固定 SDK、受控初始化来源及公开启动核验，不支持借此进行跨 SDK 升级、回退或旧备份自动恢复。

## 3. 用户、项目与会话

维护 CLI 使用 migrator 身份，并记录实际本机 UID 和维护会话。没有默认用户或万能管理员；创建项目必须显式指定已存在的所有者。

```bash
$UV run --locked python -m modules.identity.cli create-user \
  --user-id owner --display-name '项目所有者'
$UV run --locked python -m modules.identity.cli create-project \
  --project-id example --owner-user-id owner --name '示例项目'
$UV run --locked python -m modules.identity.cli issue-session \
  --user-id owner \
  --credential-file /home/cloudhelm/.local/share/cloudhelm/credentials/owner-session \
  --lifetime-seconds 28800
```

会话期限为 60～86400 秒，默认 28800 秒。签发程序使用随机 opaque bearer，数据库只保存摘要。交付目录必须是当前用户拥有的 Linux 原生文件系统目录，权限为 `0700`；新文件为 `0600`，拒绝覆盖、符号链接及 Windows 映射文件系统。回执只含用户/会话标识、文件位置与到期时间。

数据库提交不确定时，程序保留已交付文件并返回 `session_issue_unconfirmed` 与核对标识；先沿该身份核对，不把错误当作签发成功。普通 HTTP 不提供凭据签发、用户注册或跨项目创建入口。

```bash
$UV run --locked python -m modules.identity.cli revoke-session \
  --session-id '<已有会话标识>'
$UV run --locked python -m modules.identity.cli disable-user \
  --user-id '<已有用户标识>'
```

撤销会话会阻止新的 HTTP 请求，已可靠接受的原任务不会因为客户端注销而自动取消。禁用用户、撤销项目角色或委托会在后续推进的当前授权检查中阻止新动作；取消 Task 使用其独立控制命令。

## 4. API 与单 worker

完成受控数据库和身份初始化后，在同一仓库的两个 WSL 终端分别启动服务；各进程只消费自己的角色配置，角色与连接预算见 §1。

```bash
$UV run --locked python -m services.hub-api \
  --uds /home/cloudhelm/.local/share/cloudhelm/api/api.sock
```

```bash
$UV run --locked python -m services.hub-worker
```

API socket 的父目录为 `0700`，socket 为 `0600`，程序检查 Linux 原生文件系统与符号链接。需要本机 TCP 联调时，显式选择 `--dev-loopback-port 19080`，只绑定 `127.0.0.1`；实际 TLS、s2413 网络入口及 Desktop 通道另有安装与验证门禁。

worker 成功启动后输出带 UTC 时间的 `ready`。同一安装身份在受控本机账户下只允许一个 worker；第二实例拒绝，不通过删除锁或等待超时抢占。SIGTERM/SIGINT 提交停止请求后须等待 OS 进程实际退出；`--shutdown-grace-seconds` 只限定 SDK 收束等待。详细边界见 [worker 说明](../../services/hub-worker/README.md)。

管理请求通过 `Authorization: Bearer` 头认证，客户端直接消费受保护凭据，不将它放入 URL、进程命令参数或日志。命令使用 `Idempotency-Key`；同键重投保留原请求体，改变输入须使用新键。JSON 请求需要 `Content-Type: application/json`，可带精确的 `X-CloudHelm-Api-Schema: p1-hub-api-r1`；未知修订、重复 JSON 键、未知字段和超限正文都会拒绝。

|用途|入口|
|---|---|
|当前会话、项目读取|`GET /api/auth/me`、`GET /api/projects`、`GET /api/projects/{project_id}`|
|项目名称、角色|`PATCH /api/projects/{project_id}`；`GET/POST /api/projects/{project_id}/role-bindings`；`POST /api/projects/{project_id}/role-bindings/revoke`|
|Task 创建、当前状态|`POST /api/projects/{project_id}/tasks`；`GET /api/tasks/{task_id}`|
|Task 控制|`POST /api/tasks/{task_id}/start`、`/complete`、`/cancel`、`/reconcile`|
|来源、工作区、候选与构建|工程申请、文件修改及原操作查询见[工程入口](p1-engineering.md#4-工程入口与本机注册)|
|唯一完成报告|`GET /api/tasks/{task_id}/completion-report`|
|进程存活|`GET /health/live`|

准确字段和响应见 [HTTP 快照](../../packages/contracts/p1/hub-openapi.json)及[契约说明](../../packages/contracts/p1/README.md)。项目管理和 Task 新转换检查预期版本；完成还检查控制/输入有效性修订。`202` 只表示可靠接收，查询接口给出当前业务状态，幂等回执仍保存原时点响应。

Task 声明引用必须已由受控内部来源登记。普通 HTTP 不接受完整完成事实、人测通过或执行器停止证明。初始工作流只执行当前门禁与有界推进，尚未提供的构建或 Agent 能力会记录具体阻断；缺最终候选/验收或存在未知写操作时，完成继续拒绝。

## 5. 开发验证

```bash
$UV run --locked python -m scripts.p1.check_database
```

该方法使用固定 PostgreSQL 镜像，在 WSL 启动独立、临时、有资源上限的 Compose 项目，loopback 端口为 `55433`，冲突时拒绝。凭据由程序随机生成并存放在本次 Linux 私有目录，数据库数据使用 tmpfs；方法结束后定向清理本次项目及目录。

它验证初始化/维护互斥、角色和 schema 权限、UoW 回滚及有限公开 DBOS 查询，不启动业务 worker、不重跑 P0 或收费模型。历史完整 P1.1 HTTP、Task 并发与单 worker 方法已从当前分支删除，需通过原固定候选独立检出复现；实际结果仍只在验收记录及 [PROJECT_PROGRESS.md](../../PROJECT_PROGRESS.md) 维护。

HTTP 快照核对不进入服务 lifespan，不读取凭据或连接数据库：

```bash
$UV run --locked python -m scripts.p1.check_public_contracts
```

原 `check_foundation` 四组全流程、Task 故障/竞争和相应夹具不再常驻当前分支。需要复核旧结果时，先从 Git 查询原 InputSet，再按候选绑定独立检出，见 [历史方法复现](p0-seams.md#取回历史方法)。保留检查及其实际范围见[精简验证入口](checks.md)；本次删减不构成当前业务流程重验。
