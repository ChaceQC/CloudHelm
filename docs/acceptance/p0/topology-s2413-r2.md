# P0-G01a：WSL 与 s2413 只读拓扑快照 r2

> 记录日期：2026-10-15（Asia/Shanghai）。
> 范围：计划修订 9 的 P0-G01a；承接用户“暂时都使用 s2413”的同机选择。
> 结论：取得两个真实环境的本轮只读事实。s2413 的候选项目目录、批准额度、项目占账与产品身份通道尚未就绪；诊断结论为相关新准入关闭。本记录不是已运行的 CloudHelm 准入服务、部署或容量验收结果。

## 1. 输入、方法与证据绑定

依据为 [PROJECT_PLAN.md 第 3 节](../../../PROJECT_PLAN.md)、[拓扑角色决定](../../decisions/p0/topology.md)、[支持矩阵](../support-matrix.md)、[D03 共享宿主计量](../../design/03-workspace-build-resources.md) 与 [D05 身份和秘密边界](../../design/05-security-sync-operations.md)。Hub、开发 Runner 与当前交付验证共用 s2413，一个物理宿主只计一份资源池；正式独立目标仍由 P1.4/P1 出口另行取证。

入口提交为 `dev / 6b2f308da162599729f16f7722e2862f630b24ec`。本轮采集器 [topology_snapshot.py](../../../scripts/p0/topology_snapshot.py) 是该入口之后的工作区新增源码，不能声称入口提交已经包含它。方法修订为 `p0-topology-r2`，最终源码 SHA-256：

```text
7ebab53228ac8e928bf467d855cda7bcaf99559aa708837b8ab5c94af4d58604
```

|实际执行|UTC 开始|UTC 结束|结果|
|---|---|---|---|
|s2413，Python 经 SSH stdin 运行|2026-10-14T17:18:20.824859+00:00|2026-10-14T17:18:21.166588+00:00|SSH 退出码 0；系统、存储、cgroup、网络、时钟及 Docker 取得观测，工具不可调用/子项未知值保留|
|WSL Ubuntu-24.04，本机 Python 运行|2026-10-14T17:18:24.664565+00:00|2026-10-14T17:18:26.374945+00:00|进程退出码 0；工具拒绝/不可调用和 cgroup 根节点未知值保留|

本轮原始白名单 JSON、定向核验片段及结果保存在受忽略的本机文件 `.thesis-work/runtime-data/p0-topology-20261015-r2.json`，未加入公开制品；SHA-256 为 `47bdb16002a5181f7270964a6d5ae58b7dc9d11b044a5c992288f1fc3e34b0c1`。公开表格保留用于判断的实际数值。先前 runtime journals、InputSet 和历史报告没有改写；主会话再按最终集成版本冻结新输入。

Windows `wsl.exe --list --verbose` 核实发行版为 `Ubuntu-24.04`、WSL version 2，首次列表状态为 Stopped；实际采集命令启动该发行版执行。确认仓库映射存在，最终命令为：

```powershell
wsl.exe -d Ubuntu-24.04 -- bash --noprofile --norc -c 'export PATH="$HOME/.local/bin:$PATH"; exec python3 /mnt/e/Project/CloudHelm/scripts/p0/topology_snapshot.py wsl'
```

这里仅将当前 Linux 用户的 `~/.local/bin` 加入 PATH，不读取登录配置。s2413 使用现有 Codex 受管连接；本机没有可直接复用的 `ssh s2413` 配置别名。连接条目中的目标、身份文件和端口仅在进程内部取用，公开记录只保留 s2413、TCP 22、publickey-only、StrictHostKeyChecking=yes 与远端有效身份 root。SSH 登录只证明本次获授权诊断身份；不产生产品机器注册、部署或应急授权。

Windows OpenSSH 以 `ProcessStartInfo.ArgumentList` 传参，UTF-8 stdin 的 SHA-256 与上述源码一致，远端固定命令为 `env PYTHONIOENCODING=utf-8 python3 - s2413`。没有远端脚本文件或配置写入。实际 SSH 选项包括 `-T`、BatchMode=yes、ConnectTimeout=10、StrictHostKeyChecking=yes、UpdateHostKeys=no、PreferredAuthentications=publickey、PasswordAuthentication=no、KbdInteractiveAuthentication=no、IdentitiesOnly=yes、ForwardAgent=no、ClearAllForwardings=yes、PermitLocalCommand=no、ControlMaster=no、ControlPath=none、SendEnv=-* 和 LogLevel=ERROR；完整地址、账号、身份文件路径及 stderr 均不输出。

采集器只读取固定路径、选定系统字段、工具版本与格式化 Docker 元数据。候选路径或祖先是符号链接时拒绝跟随；子命令不用 shell，仅继承 PATH/HOME 和固定 UTF-8 locale。Windows 挂载盘上的可执行文件不运行。Docker 先读取 endpoint scheme，再显式绑定已解析的本地 Unix socket；非本地 endpoint 不查询，Docker endpoint 环境覆盖不继承。失败返回状态、退出码或异常类型，不返回异常正文、配置全文、完整 env、容器配置、进程命令行或秘密。

## 2. 系统与当前聚合占用

|项目|WSL|s2413|
|---|---|---|
|操作系统|Ubuntu 24.04.4 LTS / noble|Debian GNU/Linux 13 (trixie)|
|内核 / 架构|6.18.33.2-microsoft-standard-WSL2 / x86_64|6.12.107+deb13-amd64 / x86_64|
|采集器 Python|3.12.3|3.13.5|
|逻辑 CPU / 当前亲和性 CPU|16 / 16|6 / 6|
|有效系统身份|非 root；无 SSH 会话标记|root；有 SSH 会话标记|
|MemTotal|7,897,505,792 bytes（约 7.36 GiB）|16,653,258,752 bytes（约 15.51 GiB）|
|MemAvailable|7,084,818,432 bytes|8,138,584,064 bytes（约 7.58 GiB）|
|MemFree|5,684,097,024 bytes|369,754,112 bytes|
|Buffers / Cached|63,037,440 bytes / 1,468,309,504 bytes|718,487,552 bytes / 5,534,797,824 bytes|
|Swap 总量 / 已用|2,147,483,648 bytes / 0 bytes|13,207,859,200 bytes / 1,854,980,096 bytes（已用约 1.73 GiB）|
|1 / 5 / 15 分钟 load average|0.34 / 0.2 / 0.08|0.36 / 0.39 / 0.45|
|可运行 task / 可见 task 计数|1 / 380|2 / 2120|
|NTP / NTPSynchronized / 时区|yes / yes / Asia/Shanghai|yes / yes / Asia/Shanghai|

这些是采样时的可见系统量：MemAvailable 是内核估计的可用量，MemFree、Buffers、Cached 不能相加后当作批准额度；load average 不是 CPU 硬限或利用率；task 计数包含线程语义，不能当作业务任务数。采样读取并非原子事务，也不是持续容量监测。

s2413 当前约 15.51 GiB 总内存、约 7.58 GiB MemAvailable 与已用 Swap 均不能证明可以再承诺同等项目额度。WSL 约 7.36 GiB 的可见总内存低于 8 GiB light 整机基线，不能代替该档容量验收。NTP 布尔值只绑定本次快照；两端的可信误差上界、暂停检测、许可时间域和恢复行为仍未观测。

## 3. 路径、文件系统和配额标志

|环境与路径|存在性 / 观测模式|文件系统归属|总量 / 已用 / 可用|
|---|---|---|---|
|WSL `/`、`/var/lib/docker`|均存在；0755 / 0710|filesystem-1 / ext4|1,081,101,176,832 bytes / 17,582,931,968 bytes / 1,008,525,889,536 bytes|
|WSL `/mnt/e/Project/CloudHelm`|存在；0777|filesystem-2 / 9p|1,000,200,990,720 bytes / 824,328,843,264 bytes / 175,872,147,456 bytes|
|s2413 `/`、`/var/lib/docker`|均存在；0755 / 0710|filesystem-1 / ext4|236,895,510,528 bytes / 154,809,913,344 bytes / 69,977,427,968 bytes|
|s2413 `/srv/cloudhelm`|不存在；观测祖先 `/srv`|filesystem-1 / ext4|使用上行同一文件系统的计量|
|s2413 `/var/lib/cloudhelm`|不存在；观测祖先 `/var/lib`|filesystem-1 / ext4|使用上行同一文件系统的计量|
|s2413 `/var/log/cloudhelm`|不存在；观测祖先 `/var/log`|filesystem-1 / ext4|使用上行同一文件系统的计量|
|s2413 `/run/cloudhelm`|不存在；观测祖先 `/run`|filesystem-2 / tmpfs|1,665,327,104 bytes / 4,022,272 bytes / 1,661,304,832 bytes|

`filesystem-N` 编号只在各自 profile 内有效。同一文件系统的多个路径只计一次容量，不能把根分区、Docker 和不存在的候选目录余量相加；不存在路径显示的是最近已存在祖先所在文件系统。`/run` 为 tmpfs，其字节会涉及内存/Swap，不构成额外物理磁盘预算。WSL ext4 的虚拟文件系统容量不等同 Windows 宿主已分配或可扩展空间。

全部所查挂载的只读标志为 false；白名单 quota mount flags 均为空。两端本次 PATH 均未发现 `quota`、`xfs_quota`。这只说明没有在所读 mountinfo 标志中观测到 quota 标记，没有查询项目 quota 数据库，也没有验证内核/存储后端实际施加的硬限；因此 `project_quota=unknown`，不能写成“配额已关闭”或“额度无限”。

WSL ext4 的 inode 总量 / 可用为 67,108,864 / 66,780,317；9p 返回 999 / 1,000,000，采集器标为 `inode_capacity_consistent=false`，不可用于 inode 容量承诺。s2413 ext4 为 14,761,984 / 13,026,657，tmpfs 为 2,032,868 / 2,031,193。目录 mode 是 Linux 观测值，不等于已核验 ACL、用户归属或 Windows 权限。

本轮四个 s2413 CloudHelm 候选目录均不存在；没有创建、改权、挂载、分配 quota 或清理旧镜像。共享 Docker 数据根不能因存在就被视为本项目受控写入区。

## 4. cgroup 可见范围与限制

两端均观测到 cgroup v2。WSL 根控制器为 `cpu cpuset hugetlb io memory pids rdma`；s2413 另外有 `misc`。两端固定检查的 `/sys/fs/cgroup/cloudhelm.slice` 均不存在；本轮没有遍历其他组名或确认等价的项目资源组。

下表按采集进程到可见根的祖先层级排列，不公开会话路径、用户名或具体会话标识。内存和 Swap 为 bytes，PID/task 为整数，CPU 为 quota/period 微秒。

|环境 / level_from_probe|cpu.max（quota / period）|memory.current / max|memory.swap.current / max|pids.current / max|
|---|---|---|---|---|
|WSL / 0|max / 100000|26,169,344 / max|0 / max|9 / 9025|
|WSL / 1（可见根）|未观测：FileNotFoundError|未观测：FileNotFoundError|未观测：FileNotFoundError|未观测：FileNotFoundError|
|s2413 / 0|max / 100000|8,810,496 / max|0 / max|3 / max|
|s2413 / 1|max / 100000|2,299,445,248 / max|31,875,072 / max|91 / 41436|
|s2413 / 2|max / 100000|7,133,458,432 / max|1,801,142,272 / max|1042 / max|
|s2413 / 3（可见根）|未观测：FileNotFoundError|未观测：FileNotFoundError|未观测：FileNotFoundError|未观测：FileNotFoundError|

祖先计数包含子组，不能求和；会话组的现有占用也不是全部宿主占用。可见根缺少这些文件会明确返回 FileNotFoundError，不因此推断控制器未支持、额度为零或没有其他限制。`max` 表示该层未设置对应有限硬上限，不代表 CloudHelm 获得宿主额度。cpuset 的细分有效集合、所有其他 cgroup、组级写入/磁盘硬限及容器资源组归属没有核验。

## 5. Docker 连接、聚合对象数与工具

|项目|WSL|s2413|
|---|---|---|
|客户端 / 服务端|29.1.3 / 29.1.3|26.1.5+dfsg1 / 26.1.5+dfsg1|
|Compose|2.40.3+ds1-0ubuntu1~24.04.1|2.39.4|
|daemon CPU / 内存|16 / 7,897,505,792 bytes|6 / 16,653,258,752 bytes|
|cgroup 版本 / 驱动|2 / systemd|2 / systemd|
|存储驱动|overlayfs|overlay2|
|容器：总计 / running / paused / stopped|0 / 0 / 0 / 0|179 / 17 / 0 / 162|
|镜像计数|14|259|
|Git / uv|2.43.0 / 0.11.29|2.47.3 / 0.8.22|
|Node / npm|Node 在本次 PATH 不可调用；npm 为 `windows_mounted_executable_not_run`|v22.23.2 / 10.9.8|
|Rust / Cargo|本次 PATH 均不可调用|本次 PATH 均不可调用|

两端实际读取的 context endpoint 均为 Unix socket；Docker endpoint 环境覆盖的存在标志均为 false，查询由显式 host 固定。daemon 返回的数据根均与白名单路径 `/var/lib/docker` 相等。此处只返回等值布尔结论，不输出未批准的根路径。

s2413 的 179 个容器和 259 个镜像是整台 daemon 的聚合计数，未读取名称、配置、业务归属、逐容器配额/使用量、镜像层字节或卷数据。17 个运行容器与其余停止容器不能视为可回收额度；停止容器、镜像和其他保留字节仍占磁盘。整机已用空间、容器数、可见内存和 cgroup 会话样本都不能替代项目账本、唯一归属或未知占用上界。

在 2026-10-14T17:15:40.389481+00:00 做过仅返回路径类别的补充核对：WSL uv 来自当前 Linux 用户的 `~/.local/bin`，npm 来自 Windows 驱动器挂载路径。最终采集器因此拒绝执行该 npm，不将开发期读到的宿主版本当作 Linux npm 能力。所有不可调用状态仅限定本轮 PATH；采集器 Python 版本也不替代各 P0/参照工程的锁定解释器或 SDK。没有安装/升级依赖或启动构建。

## 6. 网络聚合与身份连接事实

|监听或路由摘要|WSL|s2413|
|---|---|---|
|tcp_wildcard|0|2|
|tcp_loopback|3|21|
|tcp_nonloopback|1|3|
|udp_wildcard|0|6|
|udp_loopback|4|1|
|udp_nonloopback|1|12|
|不同的 (协议, 端口) 数|4|31|
|默认路由记录数（IPv4 / IPv6）|1 / 0|2 / 0|
|22 端口监听记录|0|2 条 tcp_wildcard|
|80 / 443 端口监听记录|0 / 0|0 / 0|

监听数据来自 `ss -H -lntu` 的可见网络命名空间，只返回协议/绑定类别和白名单端口计数；不返回地址、接口名、进程名或其他端口列表。默认路由只返回 `ip -j -4/-6 route show default` 的记录数，不返回路由内容。s2413 的两条 IPv4 默认路由不证明两个有效出站通道。

本次仅证明 Windows 诊断端通过严格 host key 校验、publickey-only 认证到 s2413 的 SSH/TCP 22 并执行只读 Python 成功。未证明 WSL 到 s2413、Hub 到 Runner/Remote Agent、反向通道、产品 TLS、DNS、证书续期、网关转发、外部防火墙或公网可达。80/443 没有监听记录也不能作为端口保留、无转发规则或预览隔离已通过的证据。

同机角色不合并身份边界；root 诊断身份不等于 Hub、Runner、Remote Agent 的独立 machine identity，也不替代短期配对、当前授权、轮换/吊销或普通步骤许可。没有安装、注册或查询产品身份存储。

## 7. 未就绪入口与占账条件

|对象|本轮已证实的范围|未完成 / 入口处理|责任与下一复核点|
|---|---|---|---|
|受控存储|候选目录不存在；共享 ext4 / tmpfs 和 Docker 根的聚合容量可见|路径、所有权、隔离后端、全部写入者及硬配额未生效；相关写入入口不开放|G01b 固定实施决定；基础设施/执行器在 P1 实际运行前取证|
|资源预算与已有占用|系统内存/Swap/load、磁盘、cgroup 会话和 daemon 聚合计数|项目批准预算与 U 的可靠上界均未知；当前无可证明的新项目分配额度。按零可准入处理，不能把 unknown 填零后准入|资源负责人核对现有服务/保留/未知占用唯一归属、必要保留和逐维硬限；P1 前形成账本/执行器证据|
|产品身份与控制通道|本轮既有 SSH 诊断连接可用|Hub/Runner/Remote Agent 独立身份、注册、认证通道与权限尚未取证；SSH 不作自动部署通道|G01b 固定通道方案；P1 安装/配对前核验|
|端口、DNS/TLS、预览|仅本机监听分类及一次 SSH 方向可达|没有域名/证书/入口保留和代理隔离证据；产品网络及预览入口保持未就绪|基础设施/安全负责人按 P1 控制通道、P2 六组预览证据分别落实|
|许可时间|本次 NTP=yes、NTPSynchronized=yes|误差上界/可信样本/失信恢复未知，不能据布尔值允许新步骤|许可/执行器负责人按已定时间契约在 P1/P4 取证|
|正式独立交付与原生支持|WSL 开发与 s2413 同机角色明确|没有另一台目标、Desktop 原生隔离或容量验收；同机事实不替代这些证据|独立目标留在 P1.4/P1 出口；客户端/容量负责人按所属阶段执行|

准入口径仍由 D03 负责：同宿主所有未释放预留、保留字节、池外必要保留和未计入的未知占用都须核对，避免漏计或双计；每维执行硬上限不大于占账，未知上界不可证明时关闭该维的新准入。采集器的 `project_admission.new_admission=closed` 是本报告的诊断建议，不声称产品门禁已实现或现有服务被停止。

## 8. 必要核验与剩余工作

最终源码于 2026-10-14T17:17:26.944387+00:00 在 WSL 以 `python3 -B -c` 完成 UTF-8/AST 和 8 项定向安全核验：异常正文不回传、失败命令 stdout/stderr 不回传、Windows 挂载可执行文件拒绝、非本地 Docker endpoint 不查询、Docker 根路径隐藏、异常数值字段拒绝、两种 scoped IPv6 格式/监听聚合、候选符号链接拒绝。结果为 8/8，通过只适用于上述源码与这些固定合成输入；片段及完整结果保存在本轮私有 JSON。

2026-10-14T17:26:15.307718+00:00 在 WSL 核对源码/传输/核验输入哈希一致、私有 JSON 哈希、报告时间与主要内存数值、6 个本地链接及 UTF-8/AST/行尾空白，均通过。源码为 306 行，最长函数 32 行；按观测职责拆函数，保留单文件以便 SSH stdin 运行，无须远端安装模块。

开发期真实 s2413 的网络采集曾返回 ValueError，保留为方法缺口记录；已改为先去掉 IPv6 接口作用域再剥离括号，并在修正后重新取得第 1 节的最终快照。开发期两次不同 PATH 的工具可见性和较早源码的快照不追认为最终方法通过。

本轮没有运行全量测试、收费模型、数据库/容器业务接缝、产品安装、配额变更、部署、防火墙修改或旧镜像清理；没有覆盖人工验收。G01a 的采集器与真实事实可供下一项 G01b 消费，G01b 的受控环境决定、P0 整体出口裁决与最终 Git 交付由各自负责者继续。
