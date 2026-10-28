# Hub 单 worker 入口

当前入口用于本机 WSL/Linux 受控运行账户的单进程开发验证。它加载 Task 初始/控制流程、源码/工作区/构建/开发环境/部署领域流程及 `agent_runtime.advance.v1` 有界模型推进。Agent 的内部启动、模型配置和限制见[Runtime 说明](../../docs/development/p2-runtime.md)。物理执行由受控注册、当前业务门禁及真实存储准入约束；缺少注册时不开放相应执行。它不提供原始 DBOS 管理 API、数据库升级或备份恢复入口。

在仓库根目录、已完成受控初始化的环境中运行：

```bash
uv run --locked --offline --no-sync python -B -m services.hub-worker
```

使用 `CLOUDHELM_WORKER_DATABASE_URL_FILE` 指向权限受限的 UTF-8 连接配置；也支持受保护的 `CLOUDHELM_WORKER_DATABASE_URL` 环境变量，两者只能配置一个。不要把凭据或连接串加入命令参数、日志和诊断附件。继承的 `DBOS_*` 配置不属于本地运行协议，会在读取其值前拒绝。

启动依次核对维护基线与 worker 角色、取得安装身份对应的进程锁、构造唯一 DBOS 应用、注册领域工作流、设置监听队列、`DBOS.launch()`，最后注册并发限制。`run_migrations=False`；序列化使用公开 `DBOSPortableJSONSerializer`，Task workflow 实参只有 `command_id`，工程 workflow 只有 `operation_id`，Agent workflow 只有 `run_id`。领域工作流在所属模块注册，工作文件、源码 bytes、密钥与制品归档不进入 DBOS 参数。

普通业务池为 2、控制池为 1、DBOS 池为 4、池外 LISTEN 连接为 1，均无 overflow。`orchestration`、`control`、`engineering` 和 `models` 各自 worker/global 并发为 1，SDK executor 线程上限为 4。模型队列不新增第二个 worker，也不构成物理或容量准入证据。API 使用自己的 DBOSClient，不导入此入口，不增加 worker。

工程注册使用 `CLOUDHELM_ENGINEERING_REGISTRY_FILE`，配置格式、固定参照与种子前置、同一挂载命名空间和开发存储维护边界见[工程开发说明](../../docs/development/p1-engineering.md)。每次新副作用重新读取当前权限、Task 控制/输入及原操作身份；恢复先查询原物理结果，未知结果保留阻断。

进程锁位于 `/home/cloudhelm/.local/state/cloudhelm/worker-locks`，目录为 `0700`、锁文件为 `0600`，按安装身份的 SHA-256 命名。第二实例立即拒绝；不根据 PID 或超时抢占，不删除锁文件绕过锁。锁描述符保留到 OS 进程真正退出，SDK 停止返回后仍不会提前释放。这只约束同一受控本机账户/状态目录，不是多机调度租约或高可用方案。

stdout 仅输出带 UTC 时间的固定状态类别与必要身份。收到 `ready` 表示该进程已经完成启动及队列注册；发送 SIGTERM/SIGINT 请求停止。`--shutdown-grace-seconds` 控制 SDK 的工作流收束等待，范围为 0～30 秒，默认 10 秒。`shutdown_requested` 不是物理退出证明，集成脚本必须等待子进程退出，再启动下一实例；不得将停止请求当作 Task 完成或外部进程停止。

最小生命周期检查由统一数据库夹具组织：通过 `fixture.environment_for("worker")` 传递文件引用，启动本入口并读取一条 `ready`；同环境启动第二个进程应返回 `worker_already_running`；向首个进程发送 SIGTERM 并等待退出，然后才能验证新的实例能取得锁。业务工作流消费、当前权限、取消与任务结果由领域集成检查覆盖。
