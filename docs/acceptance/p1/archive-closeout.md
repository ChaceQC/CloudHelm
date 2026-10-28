# P1 原部署核对与有限收尾 r1

> 日期：2026-10-28（Asia/Shanghai）。实现候选为本轮 `0.9.0`，工作流应用独立保留 `cloudhelm-hub/0.7.0`，新隔离库 head 为 `0010_p1_archive_closeout`。
> 规则：[D02](../../design/02-execution-recovery.md) v4.7.2、[D04 §9.4](../../design/04-release-deployment.md#94-首次安装进入运行前的受控收尾) v4.7.2；实施输入与分工见[实施约定](../../implementation/p1-archive-closeout.md)。
> 本结论只适用于所列原资产、候选、输入、方法与环境；实际进度及验证结果统一记录在 [PROJECT_PROGRESS.md](../../../PROJECT_PROGRESS.md#2026-10-28原部署事实核对与受控收尾-c06c07)。不代表完整交付、任意恢复或人工产品验收。

## 原身份与只读方法

原 Operation 为 `deployment-e7cf429d83b9dd9f5cd8b1a7473bf02c94f5c257f5ff55eceab80cc2249c4d0b`，计划摘要为 `sha256:e7cf429d83b9dd9f5cd8b1a7473bf02c94f5c257f5ff55eceab80cc2249c4d0b`，安装身份为 `installation-3c8559b10db945dc8edb66507b0e1723`。没有创建替代 Operation。

远端取证窗口为 `2026-10-28T04:16:27.284583+00:00`～`04:17:06.078281+00:00`；目标内核 `6.12.107+deb13-amd64`、x86_64。通过只读 `debugfs` 与 `O_NOATIME` 方式提取原 ext4 内的 SQLite 主文件和 WAL，先固定不可变副本，再在第二份 scratch 中让 SQLite 读取 WAL。原镜像不挂载、原库不直接打开、原服务不启动；前后核对原镜像 SHA-256 及 atime/mtime/ctime 不变。

本机方法与完整脱敏结果保存在被忽略的 `.thesis-work/p1-closeout-audit/capture-20261028T041625Z/`。远端采集方法 SHA-256 为 `866c8d1cb13177cb47fa2c04bb51d69eddee5a0d27be117b9f64f9704ebe29fe`，隔离收集方法为 `45b80cb083cba9b4f0cabc4e52acaaf4aadbc21761b5741e194c19136089d112`。副本分析使用 WSL Ubuntu-24.04、Python `3.12.13`、SQLite `3.53.1`。

|原资产|字节|SHA-256|
|---|---|---|
|有界 ext4 镜像|8,589,934,592|`21e9ae56c0c819bcf927147f4ce61b57320deb4a2466fab631a985b4a0170232`|
|SQLite 主文件|4,096|`0ab48b25cba617ed3a4acca0161813b314c095ef63544bb4af60769eb1012977`|
|SQLite WAL|144,232|`e09a4fd1a5add418b2e17ab80a6a47329a356eb880b6b1a241efc9d75c489b65`|
|backend 部分归档|49,152,000|`78f2416ac477752b17dc291910881f326c83dc33b0815e55daba25ccc08bd52f`|

## 原账本与物理事实

|核对项|实际事实|收尾含义|
|---|---|---|
|完整主文件与 WAL|integrity_check 为 ok；lineage 唯一且匹配原安装；Operation payload、绑定及规范计划摘要一致|可沿原身份核对，不能只使用 4KiB 主文件|
|Operation/许可|原 Operation 为 active；1 个 `artifact_prepare` 已接受许可，`closed=0`，绑定已启动意图|许可已过期不等于持久封闭；尚不能释放冲突绑定|
|意图/结果|1 条 `artifact_prepare` unknown 意图，本地 result 为 0 条；后四步无意图和已接受许可|没有证据证明归档完成；原 unknown 保留|
|物理进程|前后两次核对均无原 Agent、专属 dockerd/containerd、其他安装引用或原镜像打开 fd；`/proc` 核对无读取缺项|原执行进程已停止；仍需持久封闭旧启动路径|
|systemd/cgroup|daemon inactive、disabled；原专属 cgroup 不存在、进程数 0|不把“发出停止请求”当作停止；不自动启动 daemon 获取新事实|
|存储/运行残留|镜像未挂载且无 loop 引用；容器目录、overlay2 image ID 目录为空，部分归档仍在且无完成凭据|8GiB 有界镜像和部分归档归属原安装/Operation；磁盘未回收|
|批准/期限|计划 `start_before=2026-10-25T09:08:19.705220Z`，批准 `expires_at=2026-10-25T08:40:05.145318Z`，均已过期|不继续原普通计划；新交付仍需准确新计划与新批准|

另在 `2026-10-28T04:21:24.059210+00:00`～`04:21:24.273546+00:00` 只读提取保留 Hub pg_dump 的已知表非敏感列，未恢复或连接数据库。快照保存于 `2026-10-25T07:31:30.136820+00:00`，443,582 bytes，SHA-256 为 `62218f8cba31cf914d83ab6977321c735425efc005d87e5a10b586cf72e30932`，与保留索引一致且前后未改变。

该**旧快照**中原 Operation 对应 1 条 grant、0 条 Hub result，绑定仍指向原 active Operation，environment/config revision 都为 1，实际业务 head 为 `0008_p1_4_remote`。这与远端原账本的已接受许可/未完成事实一致，但不作为当前在线 Hub 状态。提取方法 SHA-256 为 `78ddddb371bb49c14ac91f3bff0b8b856d09858d546f629505e84fbb02a1d04d`，使用系统 Python `3.12.3` 与 `pg_restore 16.15` 读取归档，不作为产品 Python/PostgreSQL 版本。

补充只读存储核对确认 Docker 仓库/标签、镜像 ID 和容器均为 0，overlay2 只有空 `l` 目录。原 backing 的宿主已分配字节为 `123,695,104`，ext4 已用块为 `291,631,104` bytes（含元数据），部分归档的逻辑及 inode 已分配字节为 `49,152,000`。这三种口径不能相加，也不等于可回收量；后续占账仍保留原有界文件系统的完整 `8,589,934,592` bytes。补充核对前后 backing 元数据与首轮一致。

## 新入口的验证与适用性

产品新增入口使用合成固定部署输入、真实临时 SQLite 和新隔离 PostgreSQL 的定向方法验证。最终 Hub 方法在 `2026-10-28T04:33:43.888506+00:00`～`04:33:57.171907+00:00` 通过 42 项断言，输入摘要为 `sha256:ae8dc571e3c30ed9e506b9049d0c5617e73ce1731bea884dbb137a61001961e6`，234 个源码/依赖/夹具文件集合摘要为 `c35eb27db2d390cfbc523a77d53be74dcf3444c1dcc66345c8d0def77f269a4a`。

方法使用真实当前认证、HTTP、PostgreSQL 迁移/角色/命令事务和 SQLite 历史输入，覆盖回执不释放绑定、当前人类幂等收尾、唯一事实/事件、原 unknown 保留、后续绑定重投隔离及残留容量。远端物理成功回执、原计划/许可和时钟为合成输入，不冒充真实目标收尾。

原目标的只读事实不被当作新收尾命令已执行；原 SQLite、WAL、Hub 快照、8GiB 镜像和部分归档保持封存。前期方法修正、未复现的身份查询拒绝、远端 SQLite 方法、UTC 结果及实际覆盖详见本轮进度；不扩展为稳定性或完整恢复支持。

新收尾只支持 `expected_state.environment_revision=0` 且为空的首次安装，以及尚未进入 `runtime_input_check` 的本地意图集合。进入数据库迁移或服务更新、非空原环境、损坏/缺失账本、不明物理写入及任意旧备份恢复均不在本轮支持范围。

本轮没有原地改写原 Hub/远端账本，也没有为原部署代填人类收尾确认。后续须先准备受支持的当前控制面与原安装维护输入，再沿原身份应用封闭/收尾；完成后才能依据新时钟、当前代次和准确新计划请求新交付批准。P1 整体与 P2 入口仍由[出口核对](exit-review.md)决定。
