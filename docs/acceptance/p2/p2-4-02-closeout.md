# P2.4-02 本机登记与集成准备

> 验证日期：2026-11-01（Asia/Shanghai）；本机 WSL 与 Windows，基于 `dev / 90b2ed1` 的 `0.30.0` 开发工作树。

[前轮](p2-4-02-followup.md)验证了端口隔离、连接关闭和原生边界。原 A11 临时业务库已清理，本轮通过正常入口重新导入来源、创建 Task、物化工作区并冻结候选。本机已登记预览槽、启动代理并生成集成提交；完整的票据访问、正式客户端支持及人工验收仍待取证。

## 原账本与受控代理

实际共享宿主池仍为 `p14-d86ce88d099c-pool`。新增 root 单用途 `resource_host enable-preview-slot`，使用两份受保护配置，在原宿主启动锁、本地账本锁及 Hub 池锁内核对配置和全部未释放占账，只允许池预算、实测容量及唯一 development Runner 的预览槽由0变1，容量修订递增并更换本轮证据；其他资源、身份、未知上界和存储不变。

UTC `2026-11-01T05:25:03.135499+00:00` 核对两端均登记 1 个预览槽、容量修订为 2；按相同输入重投返回 `already_registered`。原 16 GiB 持久存储保持 `active`，未知磁盘上界保留为 24 GiB，两端未释放的占账一致。SQLite 先提交，Hub 随后提交。本轮未验证两次提交之间崩溃后的恢复。登记完成后，另行核对实际配方、CPU period 和 Runner 上限，均覆盖固定预览所需的资源。

实际 `cloudhelm-p2-preview.service` 在 root 控制的 `system.slice` cgroup 内以非 root 服务账户运行，源码、Python和依赖固定于 root 所有且无 group/other 写权限的快照。普通同 UID 实际打开 `cgroup.procs` 写入口返回 `PermissionError`。TLS58443和HTTP58444共用同一个实际 Hub app/runtime，健康查询200；只有TLS listener属于相应外部传输所有者。证书仅为本机临时材料，使用进程内域名映射及单SPKI信任，不修改系统 hosts 或信任库，也没有发布通过式安装描述符。

恢复的 `cloudhelm-p2-resource-host.service` 使用目标登记，实际 Unix 通道为 root 所有、0660。UTC `2026-11-01T05:27:30Z` 经该通道查到原构建资源的 seq4/stopped 回执。使用方法见[资源说明](../../development/p1-resources.md)。

## 真实候选与最终集成准备

新隔离 PostgreSQL 真实初始化到 `0020_p2_previews`。干净进程曾因0020缺少直接外键目标元数据而失败；仅补 `commands/tasks` 导入后重新初始化成功，不改schema或迁移head。DBOS应用继续为 `cloudhelm-hub/0.7.0`，依赖不变。

新 Task `e3449b9137f644779da62a1130f547a7` 沿正常来源导入、物化、精确修改及冻结得到 `candidate-48b74387f39c4a57a24445b163135fd9`：32文件、139151字节，manifest为 `sha256:a48e2bb7ee4ee3b5d4be5e83d65c25db2351b3c3081769686e054eb2d314cf42`，与原A11内容一致。物理源码提交为 `09854672990d8068a1ea20cf47c7c08b758a69ba`。

项目队列生成 `merge-entry-e85855e9e5774e46b1ac2f9ddd6be2c4` / `merge-attempt-e85855e9e5774e46b1ac2f9ddd6be2c4`。目标分支原 SHA 为 `7ec1ab83bdc963b4d6521d832f7f53f7a874dc11`，最终集成 SHA 为 `5cbf446b7ca15c4a21a76b349c0d3200f9696517`，无冲突，内容清单与冻结候选相同。该提交仍待构建、正式验证、审查和合入。

独立外部静态审查从受管bare Git重算上述最终提交、双亲、32个文件及manifest，未发现阻碍本轮精确复现/预览取证的源码问题。原50项参照资产不覆盖新增 `/devmarker`，前端也不代理此路径，后续须对准确最终制品的后端入口另取精确响应证据。静态OpenAPI快照仍为原参照，未把本次复现改写成完整公开契约更新。此静态审查未提交产品内审查或人工批准。

## 构建超时与停止核对

原构建 `build-operation-87850afe2e83473da74524b5f6b8562f` 的后端核对通过。前端在启动 BuildKit 前读取固定 Nginx 基础镜像清单时超时（`docker manifest inspect`，上限 90 秒），报 `probe_docker_command_timeout`。现有日志无法定位超时原因。

后续只读诊断中，Docker CLI 在 18.034 秒内未返回；直接读取固定 Registry 根索引在 3.988 秒完成。根索引摘要与冻结值匹配，唯一的 amd64 清单与本地已核对的 8 层 OCI 一致。最终提交的完整构建仍待执行。

原资源预留 `engineering-resource-1825085e63a92593bb171dfd786efbbd3746d79e` 经原 Dispatcher/通道明确停止，seq4回执确认组删除、tmpfs回收、瞬态磁盘归零及持久owner保留；Hub allocation released，各维占账为0。

Runner 增加了核对原停止回执后追加观察的路径。UTC `2026-11-01T05:29:57.663375+00:00` 产生 `engineering-build-stopped-87850afe2e83473da74524b5f6b8562f`，前驱为原 `unknown` 观察。原资源身份、请求摘要、进程绑定和清理事实匹配，构建结果更新为 `failed`，`content_verified=false`。

原intent/result/observation三文件摘要前后不变；重复核对返回同一闭合观察，实库共保留两条观察。缺回执、未停止或异摘要均不闭合。另用原journal临时副本与实际worker预检入口核对，旧unknown被拒绝时资源组入口调用为0；闭合文件还须匹配数据库同一原操作的观察链，不能仅靠文件存在放行新构建。

## 计时及客户端边界

本轮 WSL 启动标识为 `86402274-bf9e-4e8b-99d4-925c7ccbe9e0`，环境为 Ubuntu-24.04、Linux `6.18.33.2-microsoft-standard-WSL2`。13 组只读采样未能建立误差、速率上界或暂停连续性证据；历史 P1 记录绑定另一启动代次和 `CLOCK_MONOTONIC_RAW`，本轮使用 `CLOCK_BOOTTIME`。撤销仍为 `pending_time_unknown`，3 秒、2 秒和 10 秒时限均待适用的 `ClockSupport` 验证。

Windows `0.30.0` 离线调试构建通过。原生验证在 Esc 后中断，尚无本轮收窗结果。单独驱动原生窗口只验证窗口行为；同一候选实例的票据兑换、Strict Cookie 和项目访问仍要通过产品入口验证。正式入口需要六组适用的隔离证据才能签发票据。

## 方法与交付状态

一次性方法及脱敏结果位于本机 `.thesis-work/p2-4-02-closeout/`。本轮未执行模型调用、人测、远端部署或整机重启。下一步是构建并固定集成提交，再做正式验证、实际预览与停止、Windows 收窗及最终资源清理。当前 P2.4-02 仍未达到退出条件。
