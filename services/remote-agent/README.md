# CloudHelm Remote Agent

目标 Linux 上的有限计划执行器，主动连接 Hub；不运行 DBOS、不接受任意 shell。
凭据、资源/时间门禁、初始化和原身份查询命令统一见
[Remote Agent 开发说明](../../docs/development/p1-remote-agent.md)。

默认普通执行入口因尚无适用时钟证明保持关闭。SQLite 保存安装 lineage、绑定占用、原 grant/首次接受、
步骤 intent 与事实；缺账本、失信或未知结果不自动重试/回滚。维护文件和运行目录不得入库。

首次安装尚未进入运行步骤时，可由运维人员主动调用原身份收尾维护入口；永久封闭、停止事实、
Hub 接收与当前人类确认分别持久化，磁盘保留占账，见[收尾约定](../../docs/implementation/p1-archive-closeout.md)。
该入口不提供自动停机、原备份恢复、迁移或后续部署授权。
