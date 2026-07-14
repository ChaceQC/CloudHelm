# infra

本目录保存 CloudHelm 本地开发、CI、远端演示部署和观测系统配置。

- `docker-compose.dev.yml`：当前本地开发 PostgreSQL，供 Platform API 迁移、测试和手工联调使用。
- M6 已完成 Sandbox 取舍：本地代码、pytest、Bandit、pip-audit 和 Git 使用
  allowlist 内受控目录与 `subprocess`，具备命令数组、超时、进程树清理、
  环境白名单和输出上限，但没有 Docker CPU、内存、PID、只读挂载和网络隔离。
- M7 在接入远端 staging/demo 前再次评估一次性 Docker sandbox，并新增真实
  CI、远端演示 Compose 与 Remote Agent 配置；M8 再接入 Prometheus、Loki、
  Alertmanager 或设计允许的等价观测链路。
