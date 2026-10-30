# P2.4-02 剩余隔离门禁收尾 r1

> 日期：2026-10-30（Asia/Shanghai）；入口 `dev / 96d267c`，源码 `0.29.0`。
> 端口 ACL、物理关流、逐代理回执和 Windows 独立容器已实现并取得下述定向证据。**P2.4-02 整体退出条件仍未满足，正式路线继续关闭。**

本记录承接[上轮记录](p2-4-02.md)，保留其失败和原始输入。脱敏字段、方法及源码摘要见 [本轮证据](p2-4-02-followup-evidence.json)。各组输入分别固定，不能将网络监听夹具、业务准入夹具、原生方法及 A11 制品物理运行拼成同一个正式候选的全链通过。规则仍为 [P0 预览决定 r2](../../decisions/p0/preview-access.md)和 D05/D06。

## 实现与直接结果

|范围|实际交付与结果|适用边界|
|---|---|---|
|E05a 原始入口|现有 root ResourceHost 按实例安装 OUTPUT/INPUT/FORWARD 小链；仅代理 cgroup→80/8000、同实例前端→后端、后端/受控迁移→数据库放行。真实内核/容器 84 项通过；同 UID 1000 普通宿主、跨实例、5173 等拒绝；8 个容器无 IPv6 地址；service 重启后旧网络拒绝新 cgroup|两个生产 Docker 配置接缝及明确 TCP 监听夹具，不等于真实产品预览注册通过|
|E06a 回压/失联|受控 Uvicorn h11 接缝以 TCP reset/abort 关闭下游，核对上游 socket 描述符释放、下游 connection_lost 后才移登记。525216 bytes 回压下，封入口至下游/上游观察为 0.960/1.634 ms，客户端 reset 5.977 ms；失联最后有效控制至封入口 2501.281 ms，之后两端 0.594/0.943 ms、客户端 6.366 ms|实际本机 TLS/socket、合成授权；单次观察不构成含误差/虚拟化暂停证明的 3s/2s/10s 承诺|
|E06b 回执/恢复|真实 PostgreSQL/TLS 15 项通过。两次撤销至客户端终止 718.399/473.102 ms，各收到 1 个实际 TLS listener 的传输回执；提交后丢响应注入重投 2 次，receipt 不变。真实子进程重启后旧 Cookie 403，原截止/代理集合不重置|候选/InputSet/正式报告/准入为夹具；无可信时基仍 revoking/pending_time_unknown，重新签发拒绝；非 TLS/UDS 本地事实不算外部确认|
|E07a Windows 原生|纯 Tauri Window 挂原始 Wry WebView，每实例新分区且无 Tauri 脚本/协议/IPC handler。合成原生 9 项、真实 TLS/实库原生 11 项通过；认证→POST兑换→Strict Cookie→项目 GET200/h1 成立，7 个 URL 无凭据/票据/Cookie 值；文件、导航、请求、弹窗与存储隔离核对完成，关闭后分区删除、WebView2 剩余进程0|Desktop 元数据驱动为夹具；管理文档、认证、票据、数据库、TLS及项目请求实际运行。Linux/安装升级/人工验收及服务端撤销主动收窗未放行|
|E07b1 真实制品|原 A11 候选32文件/139151 bytes及三个OCI重新核对；实际 CandidatePreviewDocker 两轮ready，前端 `/`、`/health`、`/ready` 与后端精确 `/devmarker` 均200。停止后旧容器/network查询404、旧socket失败；新轮物理身份不同，原资源回执 stopped/disk_reclaimed|原合法普通资源 preview_slots=0，方法显式安装物理ACL，不冒充产品预览准入。Docker复用IPv4，新实例可再提供同一raw地址；不能声称旧IP永久失效|

原生实读 Windows 11 25H2/`26200.9168`、rustc `1.97.1`、Tauri `2.12.5`、tauri-runtime-wry `2.12.3`、Wry `0.57.1`、WebView2 `154.0.4258.62`。最终调试程序 SHA-256 为 `45ec17cc9a4927d38180641f3f72854eec4687bb136e081393956e39b1d98367`。新增两个 Windows 直接引用均使用既有锁定包，未升级依赖；现有 Tauri `unstable` 用于纯 Window。WebView2 的 chrome.webview 对象存在不等于获得 IPC：载入前原生 getter 确认 WebMessage 关闭，没有消息接收器或 Host Objects。

后端为 WSL Ubuntu-24.04/Linux `6.18.33.2-microsoft-standard-WSL2`、Python `3.12.13`、PostgreSQL `16.13`、Uvicorn `0.54.0`。TLS仅本机进程内域名映射、临时证书及单SPKI信任，未修改系统DNS/信任库或发布安装描述符。

## 必要修正与兼容

- 单独 transport.abort 仍使外部客户端恢复读取后超时，故按实证增加 SO_LINGER reset，首轮失败保留。有限响应进入物理收尾后不再取消收尾任务，避免撤销跳过连接表清理；另一次真实TLS有限响应及受控关闭延迟方法通过，登记归零。
- 原生 NavigationStarting 取消后仍有GET到禁止来源，已在载入前增加 WebResourceRequested 拦截，不读取请求body/凭据。正常销毁后以目录实际删除确认清理，失败向可信主窗口发 preview-cleanup removed=false；硬杀/崩溃不保证当场删除，旧目录不复用。
- 回执绑定原 authorization/revision、proxy_id/boot_id、TLS listener启动及原receipt摘要；重投不刷新事实，不能代报旧boot。默认无ClockSupport，复用既有受审接口而不生成虚假误差profile；提交前BOOTTIME锚点及证据摘要以可选JSON字段保存，重启不重置原截止。
- 环境公开查询增加可选 entry_origin/client_route，可信Desktop据此固定目标，不返回上游或秘密。票据只在独立容器管理文档内经原POST交付。旧记录缺字段继续解析；HTTP快照同步，数据库head `0020_p2_previews`、工作流 `cloudhelm-hub/0.7.0` 不变。

方法修正单独记录：实库方法最初只等待冷启动5秒且误用前一响应，已改为独立ready标志及有界等待；最终依据实际新进程监听和旧Cookie拒绝。原生首轮误按title判断仅有h1的上游，未重放票据，改用新实例 `p2402-local-7` 复核h1及GET200。两者不列作产品修复。

## 未满足的退出条件

|未决项|事实、责任与下一入口|
|---|---|
|真实预览注册/安装|现有宿主pool及development Runner预览槽均0，未安装受控代理service/cgroup。安装/资源负责人沿同一物理账本与正常维护入口登记实际能力，核对真实DNS/TLS/网络；不能另建账本绕开旧占用|
|同一正式候选全链|A11只有CandidateSnapshot/agent_candidate_ready，没有FixedCandidateRecord及真实正式验证、独立审查、最终集成依据。候选/集成负责人沿既有固定、验证审查和队列命令取得记录，再调用candidate-previews；不能将本次物理OCI方法补写为已合入|
|可信计时|没有绑定当前环境/启动的受审误差、速率和暂停连续性证据。时间/基础设施负责人须提供适用ClockSupport；当前unknown保持关闭，未证明10秒全局承诺及可信超时边界，不以观测值代替|
|撤销分区/完整旧版本组合|正常销毁已验证；服务端撤销主动收窗/分区清理没有取得证据。同一正式候选的旧人测轮次、重建/重连组合仍需取证，P2.4-01旧轮次事务证据不扩大范围|

本次不修改退出条件、不编造人测/审批、不开放描述符或P3。前置具备后继续本包，不重跑无关历史套件。

## 方法与清理

一次性方法位于忽略目录 `.thesis-work/p2-4-02-followup/`，公开JSON保存摘要和允许字段。WSL使用既有 `.venv`、`PYTHONPATH=.`、`PYTHONUTF8=1`：root运行 `network/check_network.py`；普通用户运行 `proxy/check_physical_close.py`、`proxy/check_finalizing.py`、`integration.py`。真实制品方法为 `candidate/physical.py`，按固定结果中的参数调用。Windows运行 `cargo build --locked --offline`、本目录native方法和 `npm.cmd run build`。这些方法各覆盖本次边界，没有重跑历史人测/返工套件。

临时数据库、TLS listener/私有证书、原生分区/进程、方法容器/网络/专属规则和探测service均按本轮身份收尾；原永久存储恢复未挂载。精确核对后删除0、保留3个原A11镜像身份：有既有构建引用，缺本轮加载前私有缓存清单，不能认定本轮新增；没有prune。未运行收费模型、正式部署、整机重启、容量或人工产品验收。
