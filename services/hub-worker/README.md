# Hub 单 worker 入口

当前入口用于本机 WSL/Linux 受控运行账户的单进程开发验证。它只加载 `collaboration.task_initial.v1` 与 `collaboration.task_control.v1`，不运行生成代码、不提供原始 DBOS 管理 API，也不提供数据库升级或备份恢复入口。

在仓库根目录、已完成受控初始化的环境中运行：

```bash
uv run --locked --offline --no-sync python -B -m services.hub-worker
```

使用 `CLOUDHELM_WORKER_DATABASE_URL_FILE` 指向权限受限的 UTF-8 连接配置；也支持受保护的 `CLOUDHELM_WORKER_DATABASE_URL` 环境变量，两者只能配置一个。不要把凭据或连接串加入命令参数、日志和诊断附件。继承的 `DBOS_*` 配置不属于本地运行协议，会在读取其值前拒绝。

启动依次核对维护基线与 worker 角色、取得安装身份对应的进程锁、构造唯一 DBOS 应用、注册领域工作流、设置监听队列、`DBOS.launch()`，最后注册并发限制。`run_migrations=False`；序列化使用公开 `DBOSPortableJSONSerializer`，workflow 实参只有 `command_id`。领域注册接口为 `modules.collaboration.workflows.register_task_workflows(application)`，应用对象为 `TaskApplication(normal_engine, control_engine, dbos_client)`。

普通业务池为 2、控制池为 1、DBOS 池为 4、池外 LISTEN 连接为 1，均无 overflow。`orchestration` 与 `control` 各自 worker/global 并发为 1，SDK executor 线程上限为 4。API 使用自己的 DBOSClient，不导入此入口，不增加 worker。

进程锁位于 `/home/cloudhelm/.local/state/cloudhelm/worker-locks`，目录为 `0700`、锁文件为 `0600`，按安装身份的 SHA-256 命名。第二实例立即拒绝；不根据 PID 或超时抢占，不删除锁文件绕过锁。锁描述符保留到 OS 进程真正退出，SDK 停止返回后仍不会提前释放。这只约束同一受控本机账户/状态目录，不是多机调度租约或高可用方案。

stdout 仅输出带 UTC 时间的固定状态类别与必要身份。收到 `ready` 表示该进程已经完成启动及队列注册；发送 SIGTERM/SIGINT 请求停止。`--shutdown-grace-seconds` 控制 SDK 的工作流收束等待，范围为 0～30 秒，默认 10 秒。`shutdown_requested` 不是物理退出证明，集成脚本必须等待子进程退出，再启动下一实例；不得将停止请求当作 Task 完成或外部进程停止。

最小生命周期检查由统一数据库夹具组织：通过 `fixture.environment_for("worker")` 传递文件引用，启动本入口并读取一条 `ready`；同环境启动第二个进程应返回 `worker_already_running`；向首个进程发送 SIGTERM 并等待退出，然后才能验证新的实例能取得锁。业务工作流消费、当前权限、取消与任务结果由领域集成检查覆盖。
