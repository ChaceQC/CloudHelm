# A00 隔离开发安装

Agent 重构的 [A00](../../PROJECT_PLAN.md#agent-与跨端架构重构a00-冻结首轮输入) 使用单独的 WSL 检出、数据库和进程。当前安装标识为 `69e168a64fe64110a66c4c0d78e7a143`。源码为 `dev / b226022483fcc3c4c98f22c3a8faba1fb0b4c696` 加本轮已记录的 `0020` 冷启动导入。初次初始化及验证结果见 [A00a 进度](../../PROJECT_PROGRESS.md#2026-11-19a00a-记录基线建立隔离安装)。

| 用途 | 本机开发位置 |
|---|---|
| 后端源码、Git、Python 环境 | WSL `/home/cloudhelm/.local/state/cloudhelm/a00a/source` |
| PostgreSQL | Compose 项目 `cloudhelm-a00a`，`127.0.0.1:55821`，卷 `cloudhelm-a00a_postgres-data` |
| API / worker | API 绑定 WSL `127.0.0.1:19180`；同安装一个 worker，各自引用 `database/` 下的连接文件 |
| Runner 与受管 Git | [A00b](../acceptance/a00b/README.md) 已为候选读取配置单独的受管 Git 存储。实际构建和运行仍需按[开发存储和工程登记](p1-engineering.md#4-工程入口与本机注册)准备 Runner |
| Desktop | Windows，按[原生启动说明](p1-desktop.md#启动与连接)从配对版本构建；本机联调使用该安装的端口与该库签发的新会话 |

在 WSL `Ubuntu-24.04` 打开终端，启动专属数据库并查询原安装身份。WSL 闲置退出后重新执行这一段；命名卷保留原安装数据。

```bash
a00a_root=/home/cloudhelm/.local/state/cloudhelm/a00a
cd "$a00a_root/source"
a00a_compose() {
  docker --host unix:///var/run/docker.sock compose --project-name cloudhelm-a00a \
    --env-file "$a00a_root/database/compose.env" \
    --file infra/p1/compose.yaml \
    --file /mnt/e/Project/CloudHelm/infra/p1/compose.isolated.yaml "$@"
}
a00a_compose up --detach --wait --wait-timeout 45 postgres
env -i HOME="$HOME" PATH=/usr/bin:/bin LC_ALL=C.UTF-8 PYTHONUTF8=1 \
  CLOUDHELM_MIGRATOR_DATABASE_URL_FILE="$a00a_root/database/migrator_database_url" \
  .venv/bin/python -B -m database.manage status
```

状态与安装身份吻合后，在两个 WSL 终端从同一 `source` 目录按需启动 API 与 worker。用独立角色引用，以免继承旧安装的数据库、模型或 Runner 配置。

```bash
env -i HOME="$HOME" PATH=/usr/bin:/bin LC_ALL=C.UTF-8 PYTHONUTF8=1 \
  CLOUDHELM_API_DATABASE_URL_FILE=/home/cloudhelm/.local/state/cloudhelm/a00a/database/api_database_url \
  .venv/bin/python -B -m services.hub-api --dev-loopback-port 19180
```

```bash
env -i HOME="$HOME" PATH=/usr/bin:/bin LC_ALL=C.UTF-8 PYTHONUTF8=1 \
  CLOUDHELM_WORKER_DATABASE_URL_FILE=/home/cloudhelm/.local/state/cloudhelm/a00a/database/worker_database_url \
  .venv/bin/python -B -m services.hub-worker
```

结束联调时先停止 API 与 worker 并等待退出，再用 `a00a_compose stop postgres` 保留数据。另建隔离安装时，分配自己的 Compose 项目和 loopback 端口，并按 [Hub 初始设置](p1-hub.md#2-受控数据库初始化)准备新库、角色和凭据；[持久卷覆盖](../../infra/p1/compose.isolated.yaml)只随新安装使用，现有 P1 临时数据库检查仍用原 tmpfs 配置。

需要访问 A00b 的固定源码时，先核对 WSL 存储 `dev-storage-b07c29f62efe41baa76ec305b21f988b`（实例修订 `f6f3cdd6e2b445b5a4e5747a2f39a9a8`）的原 backing 和挂载。WSL 退出后，如原挂载已解除，使用受控 `development_storage_maintenance remount` 原实例。API 和 worker 加载同一份 `CLOUDHELM_ENGINEERING_REGISTRY_FILE=/home/cloudhelm/.local/state/cloudhelm/a00a/a00b/engineering-registration.json`。该登记只用于本地 Git/工作区读取样例，没有物理构建和 Runner 的组占账登记。

[A00c](../acceptance/a00c/README.md) 的项目使用另一存储 `dev-storage-b8b9a26fd4464f6fa27ad361be3cb911`（实例修订 `c6b92771b61247c0a7d938340174d7e0`）。核对原挂载后使用 WSL `$a00a_root/a00c/engineering-registration.json` 的对应登记；不要交叉加载 A00b 和 A00c 的存储。该登记供核对草稿及固定 Git 来源；G01 的实际预算、构建资源和目标准入按集成版本重新登记。
