# Remote Agent 开发入口与启用门禁

当前源码 `0.7.1`，工作流应用单独保留 `cloudhelm-hub/0.7.0`，新隔离库业务 head 为
`0008_p1_4_remote`（前驱 `0007_p1_4_delivery`）。P1.4-02 开发切片已接入；完整退出条件及实际结果以
[进度](../../PROJECT_PROGRESS.md) 为准。尚无适用时钟证明，默认普通启动保持关闭。
本文不构成产品安装包、完整独立交付或整机重启验收。

## 1. 通道和状态所有权

`modules.delivery.remote_http:create_app` 是 Hub 的执行器通道，使用现有 worker 角色的有界 control 连接池，
不启动额外 DBOS worker。DBOS 仍可靠暂存批准计划；Remote Agent 主动报告观察、拉取完整计划和原 Operation，
在本地选择下一有限步骤。Hub 只授权、接收账本事实和计算业务结果，不逐步下发执行。

契约固定为 `remote/v1`，快照为 [remote-openapi.json](../../packages/contracts/p1/remote-openapi.json)：

|入口|用途|
|---|---|
|`POST /remote/v1/bindings`|仅返回凭据所属项目/目标/安装的绑定，用于计划生成前采集实际状态|
|`POST /remote/v1/observations`|受认证执行器报告有界事实；普通人类 Hub API 不提供此入口|
|`POST /remote/v1/poll`|完整不可变计划、Manifest、批准及原 Operation，或明确等待原因|
|`POST /remote/v1/sample`|绑定 nonce、两端身份、通道和纪元的原始样本；同 nonce 重投不生成新鲜样本|
|`POST /remote/v1/permits`|重查当前批准/权限/原设备凭据、时间、前序事实、实际状态和资源，签发具名许可|
|`POST /remote/v1/results`|追加步骤投影、业务事件和 Outbox；未知保留 active 绑定|
|`GET /remote/v1/artifacts/{operation}/{storage_id}`|仅流式传输原计划内的已验证归档，不接受宿主路径|

执行器使用独立 `chra1_` 不透明 token，不能混用人类 DeviceSession。维护角色通过 `enroll_remote` 登记
摘要、项目/目标/安装、期限与撤销状态；token 值只放目标私有文件。worker 只有凭据锁列的更新权，
不能改凭据/范围/期限/撤销。新表分别保存维护凭据和不可变样本/许可/结果，API 角色不能写执行事实。
HTTPS 和证书验证为必需，仅 loopback 允许 HTTP 调试。禁止重定向、URL 凭据和关闭证书验证；
正文/响应有界，拒绝时不回显输入、异常、数据库诊断或秘密。

## 2. 维护与启动

先按 [Hub 入口](p1-hub.md) 准备同版新隔离库；`initialize` 不升级旧安装。
维护配置 `CLOUDHELM_REMOTE_ARTIFACT_ROOT` 指向满足 ArtifactStore 所有权/私有权限的真实归档存储，
未配置时归档入口不可用。通过现有 TLS 入口接入以下 Hub facade，禁止直接暴露 loopback 调试方式：

```bash
uv run --locked --offline --no-sync uvicorn modules.delivery.remote_http:create_app \
  --factory --host 127.0.0.1 --port 58110 --no-access-log
```

目标需要锁定的 Python 3.12 工程环境、Docker Engine、systemd/cgroup v2、专属有界文件系统和私有凭据文件。
SSH 只承担获授权引导/诊断，不成为日常通道。目标配置为服务 UID 所有的 `0600` 普通文件，拒绝符号链接。
以下仅为结构示例，容量与路径不构成实际预留证明；真实秘密经独立受控通道提供：

```json
{
  "hub_url": "https://hub.example.invalid",
  "token_file": "/etc/cloudhelm/remote-token",
  "ca_file": "/etc/cloudhelm/hub-ca.pem",
  "state_directory": "/var/lib/cloudhelm-target/bounded/state",
  "docker_socket": "/run/cloudhelm-target/docker.sock",
  "registration": {
    "target_id": "target-example", "installation_id": "installation-example",
    "executor_instance": "replaced-by-process-identity", "generation": 1,
    "docker_identity_kind": "oci_config",
    "supported_steps": ["artifact_prepare", "runtime_input_check", "database_migrate", "service_update", "health_verify"],
    "capacity": {"memory_mib": 1024, "cpu_millicores": 1500, "disk_bytes": 4294967296, "pids": 256}
  },
  "resources": {
    "mount_root": "/var/lib/cloudhelm-target/bounded",
    "cgroup_path": "/sys/fs/cgroup/cloudhelm-target.slice",
    "cgroup_parent": "cloudhelm-target.slice",
    "daemon_pid_file": "/run/cloudhelm-target/docker.pid"
  },
  "secret_files": {
    "secret://test/database-url@v1": "/etc/cloudhelm/secrets/database-url-v1",
    "secret://test/postgres-password@v1": "/etc/cloudhelm/secrets/postgres-password-v1"
  }
}
```

维护入口先准备真实执行组：Agent、命令、专用 Docker daemon、容器均处于同一有界 cgroup；账本、暂存、
Docker root、业务卷和日志均处于同一专属有界挂载。执行器实际核对内核硬限、daemon/自身归属、挂载容量和
Docker root；硬限超过占账即拒绝。Hub 按真实 installation 串行核算各项目绑定，未知替换保留新旧配置逐维较大值。
成功后的业务占用继续保留。本入口不自动迁移现有 Docker root、分区或修改其他项目的资源组。

初次安装显式建立账本，之后不再带初始化开关：

```bash
uv run --locked --offline --no-sync python -B -m services.remote-agent \
  --config /etc/cloudhelm/remote.json --initialize-ledger --once
uv run --locked --offline --no-sync python -B -m services.remote-agent \
  --config /etc/cloudhelm/remote.json
uv run --locked --offline --no-sync python -B -m services.remote-agent \
  --config /etc/cloudhelm/remote.json --reconcile-operation ORIGINAL_OPERATION_ID
```

进程启动生成新 executor_instance，需核对实际账本/进程后由维护入口登记，不复用旧进程的启动身份。
最后一条命令只查询/补报原步骤，不启动下一步。自动接管、重新登记和完整恢复仍受后续恢复工作包约束；
换身份或计划不释放旧冲突占用，账本缺失也不被解释成新空安装。

### 2.1 WSL 到独立目标的受控验证连接

WSL 的 `127.0.0.1` 属于 WSL 网络命名空间。Windows SSH 发起反向转发时，不能假定其
`127.0.0.1` 一定能抵达该监听器。先核对 WSL `eth0` 的实际地址，将 HTTPS facade 绑定该地址，
再由 Windows SSH 显式转发到它；目标只监听自己的 loopback，例如：

```powershell
ssh -N -o ExitOnForwardFailure=yes -R 127.0.0.1:58112:<WSL_ETH0_IP>:58111 <已授权目标>
```

目标仍使用 `https://127.0.0.1:58112`，核验匹配该名称的受控证书，并从私有文件提供执行器凭据。
这条 SSH 路由只用于已授权的隔离开发验证；HTTPS、执行器认证和步骤门禁仍由产品通道独立执行，
不构成正式网络安装方案。连接、身份认证、计划批准和物理完成分别核对。

固定组合的受控采集器另保存目标原始 UTC 时间和已认证 Hub 响应时间。响应先于实际状态采集，
其保守时刻用作本次观察的采集起点；只接受 RAW 计时下往返小于 2 秒、响应至采集小于 5 秒的输入，
保留逐条时间审计。Hub 的 60 秒新鲜度规则不变，不调整任何主机的系统时间。
该采集器属于本次固定输入，未接入通用 CLI；不据此宣称任意机器时差或网络条件都受支持。

## 3. 时间与本地启动门禁

复用 P0 的 `CLOCK_MONOTONIC_RAW`、30 秒许可、2 秒不确定度、60 秒样本龄、完整 RTT 保守区间和
最多 5 秒首次接受窗口。过期等号拒绝；原 grant/首次接受持久保存，重投和续样不重开窗口。
失信后当前时钟对象永久关闭，通过新的连续性身份/纪元恢复，旧 grant 不复活。

`0.7.1` 修复看门狗初始化边界：完成原生签名见证验证后、线程启动前才建立运行间隙锚点。
初始化期间尚未暴露支持对象，见证的网络等待不计作运行间隙；运行后的 200 ms 检查、平台连续性
检查及失信实例永久关闭均保留。本修复不改变执行协议、数据库迁移或 DBOS 工作流应用版本。

`ClockSupport` 仅由受控 composition root 注入，包含经审查的实际硬件/虚拟化速率与读取误差证据，以及
每次启动前的连续性验证器。摘要、短时 RTT、NTP 状态或两种本机时钟的差值均不足以替代证明。
通用 CLI 和默认 Hub root 当前不注入该证明，故拒绝普通新步骤；方法中的合成时钟输入不能安装为生产证明。
本地绑定锁内完成当前许可、不可变接受、实际状态/维护/资源核对、intent 持久化及实际调用前窗口复核。
已有 intent 只查原结果；失联、未知前序、未封闭旧许可或维护门禁均不启动新步骤。
已运行的有限步骤按安全边界收束，不因许可过期杀迁移，不自动回滚或启用本机应急。

## 4. 固定物理适配与证据边界

执行器从 Manifest/配置重新构造配方和全部步骤输入，任何偏离或未知类型/版本都拒绝。
受限 Compose 规格映射为固定 Docker Engine 请求，不接受任意宿主 shell，也不扩大字段支持。

- 归档实际校验 archive/manifest/config/platform、解压层字节与并存空间；classic 模式受控转换，containerd
  模式保留 manifest 身份；加载后核对 loaded image ID 和 RootFS diff_ids，禁止 pull/build。
- 只解析声明参数与 secret 版本引用；便签库为 `reference_notes`，应用角色 `reference_app` 与迁移 owner 分离。
  秘密仅执行层私下注入，不进计划、SQLite、事件、日志或回报。
- 固定 PostgreSQL 16.13、Alembic 1.20.0 和已审查脚本，按实例取得原身份 session advisory lock；
  DDL、版本和成功账本单事务提交。锁等待 5 秒、语句 300 秒、步骤 600 秒，固定 schema/data/application 三组后置。
- 服务更新只操作 namespace 内的具名服务/网络/卷，保留明确硬限、日志限额和 `unless-stopped`；
  启动就绪后核验至少 30 秒连续健康窗口。未知立即停止后续步骤并保留占用。
- Hub 仅投影受认证账本事实；全部步骤和最后健康窗口齐全才显示 `succeeded`。accepted、DBOS 返回、退出码或
  单个容器 running 都不单独证明部署成功。

迁移丢回执先按原 operation/input digest 查数据库成功账本、实际 Alembic head、schema 和应用只读查询。
单事务已经证明的数据保持事实不因后续合法业务写入而失效。查无完整记录、异摘要、失联、原进程/锁未核清或
后置不满足均保留 unknown，不重放、不 downgrade。当前支持固定新安装和同版 schema 核对；已有数据的
`0001 → 0002` 独立升级仍待备份恢复/兼容证据，不因脚本存在而开放。

业务依赖目标 Docker 和容器 restart policy，不调用 Hub/DBOS，也不在每次应用重启重复迁移。
完整业务离线、整机/Remote Agent 重启、独立重装、保留卷卸载及真实 4 核 8GB 容量须分别实测。
本轮独立目标方法仅验证数据库迁移适配和专属数据库容器重启，不证明这些完整出口。
