# P1 当前控制面与真实交付输入核对 r1

> 日期：2026-10-28（Asia/Shanghai）。核对候选为 `dev / 3f1a037`、源码 `0.9.0`；本轮只读输入核对不构成部署、恢复或人工验收。实施边界见[本轮约定](../../implementation/p1-current-delivery.md)，实际进度统一记录在 [PROJECT_PROGRESS.md](../../../PROJECT_PROGRESS.md)。

## 固定输入与实际核对

本轮沿用[原 Operation 与 C06/C07 身份](archive-closeout.md)，没有创建替代 Operation、binding 或安装。准备阶段只读取证；之后实际原身份封闭及确认输入见本页末节。

WSL Ubuntu-24.04 的实际内核为 `6.18.33.2-microsoft-standard-WSL2`。安全 SSH 探针返回退出码 0 和预期标记；它只打印状态、长度和分类，不打印连接配置或秘密。

本机保留输入的核对时间为 `2026-10-28T04:46:34.047613+00:00`，方法为已有 `.thesis-work/p1-4-02/c05_readonly_probe.py hub`，加载 C06 的 `noatime.so` 防止只读检查更新原 backing 的访问时间。未挂载原有界盘，使用 debugfs 读取原归档：

|归档角色|字节数|与原 Manifest 的长度/完整 SHA-256|
|---|---:|---|
|backend|65,600,512|均匹配|
|frontend|26,081,792|均匹配|
|postgres|160,163,840|均匹配|

原 16GiB backing 的已登记设备/inode/长度仍匹配，未挂载且无 loop 引用。保留 `cloudhelm.dump`、`roles.sql` 的长度和 SHA-256 均与索引匹配，7 份私有运行文件全部存在。私有配置和秘密未输出，未恢复数据库或执行角色快照。

这些结果只证明所列保留输入完整。尚未重新执行当前 ArtifactStore 的 OCI 内容检查、Release 适用性交接或真实部署；不能据此把目标部分归档的原 unknown 记成成功。

## 控制面衔接结论

当前 `initialize` 无旧库升级/事实导入能力；新空库缺少原计划、批准、binding、环境修订、许可及 BuildRun/Release 历史。原回执入口会返回 `deployment_operation_not_found`，新 binding 的容量查询也无法发现原 8GiB 保留盘。此为源码核对结论，未通过向原安装发送写请求来制造失败。

用户已选择固定快照的独立维护恢复/升级。本轮已实现受限来源门禁，实际副本线性到 `0011_p1_archive_maintenance` 且保持 recovery_required；未直接恢复普通运行，没有补造 BuildRun 或改绑旧成功证据。新控制面的正式受信交接不在本切片中扩展。

## 时钟与执行状态

旧 profile 自身摘要和 `clock_evidence.py` 摘要仍匹配，但当前 Hub boot 不匹配。当前 Windows 会话的管理员角色检查为 false，58113 未发现监听；尚未实际启动见证，故不将非管理员身份单独记为权限失败。

本轮时钟方法在新的忽略目录独立运行。管理员见证的 HCS/监听、RSA 签名、nonce 和 VM 绑定实际核对通过；`05:11:46.514566+00:00`～`05:23:47.221064+00:00` 得到 1,310 样本及 124 次验签，目标 RAW 719.506 秒。首末平均区间 `[-1.2732003866, 630.2783953008] ppm`、最大 RTT 2.370 秒，本轮未生成可启用 profile。观测不证明适用运行期间 100 ppm/10µs/1µs 上界，普通步骤门禁仍关闭；日志摘要及方法见本轮进度。

当前未创建准确新计划、未取得该摘要的人类批准、未执行五步交付或 Hub 离线业务核验；未执行整机重启。原 unknown、绑定、磁盘及旧快照保留。P1 整体和 P2 的门禁继续以[出口核对](exit-review.md)为准。

## 原身份维护收尾的确认输入

本轮已沿原 8GiB backing、原安装和原 Operation 实际取得不可变 C07 回执，并在 recovery_required 副本使用当前安装凭据接收。
`2026-10-28T05:41:31.289339+00:00` 核对回执与库内摘要一致、原绑定仍指向原 Operation；尚未执行人类收尾命令。

|确认项|准确输入|
|---|---|
|目标安装|`installation-3c8559b10db945dc8edb66507b0e1723`|
|原计划|`plan-bef88a2d7fa33f6694a4cd0a2128b64d9f37381fc85e14d961917efee0b9f1c5`|
|原计划摘要|`sha256:e7cf429d83b9dd9f5cd8b1a7473bf02c94f5c257f5ff55eceab80cc2249c4d0b`|
|收尾回执摘要|`sha256:4805187f1b729da7b74d5312c8f2103c6428ed9cf61e3d8a64fe54712ddd499f`|
|源代码包|223 个文件，`sha256:d712a2199b3bb116fea5374e65de45d4318e449e9c9b1b85d2fc0d34d678a2f6`|
|确认后的资源|memory/cpu/pids 为 0，磁盘保留 `8,589,934,592 bytes`；不删除 backing/部分归档|

确认只追加该原身份的收尾依据并解除冲突绑定，保留原 `unknown`，不把部署改成成功，不批准新计划。
确认要求来自 [D04 §9.4](../../design/04-release-deployment.md#94-首次安装进入运行前的受控收尾)：
“当前具有 `deployment.approve` 的已认证人类以准确计划和回执摘要提交幂等收尾命令”。
准备好的私有请求正文与以上两个摘要一致，未包含秘密值。
