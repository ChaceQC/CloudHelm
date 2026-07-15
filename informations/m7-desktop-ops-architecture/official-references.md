# 桌面发行、常驻运维控制面与本地数据边界参考

> 检索日期：2026-07-16
> 适用阶段：M7 架构修订、M9 桌面产品化、M10 安装与最终验收

## 1. Tauri 桌面发行

### Tauri Windows Installer

- 官方文档：
  - https://v2.tauri.app/distribute/windows-installer/
  - https://v2.tauri.app/reference/config/#windowsconfig
- 采用结论：
  - Windows x86_64 的必交付安装器使用 NSIS setup `.exe`。
  - 安装后提供 `CloudHelm.exe`、开始菜单入口和卸载程序。
  - MSI 作为企业分发的可选产物，不替代 setup `.exe`。
  - 答辩环境可能离线时，需要验证 WebView2 已存在或随安装器提供离线安装路径。

### Tauri Linux Bundle

- 官方文档：
  - https://v2.tauri.app/distribute/appimage/
  - https://v2.tauri.app/distribute/debian/
  - https://v2.tauri.app/distribute/rpm/
- 采用结论：
  - Linux x86_64 必须同时生成 AppImage 与 `.deb`。
  - AppImage 作为直接运行的桌面可执行文件，`.deb` 作为 Ubuntu/Debian 安装包。
  - `.rpm` 保留为可选发行产物。
  - Linux 构建使用明确的最老支持发行版基线，避免 glibc/WebKitGTK 兼容漂移。

### Tauri Sidecar

- 官方文档：
  - https://v2.tauri.app/develop/sidecar/
- 采用结论：
  - 后续 `modules/local-runtime` 以按目标平台构建的 sidecar 随桌面安装包分发。
  - sidecar 只访问本机 allowlist workspace，负责本地 Git、worktree、测试和受控
    工具执行；远端权威状态仍写入 Ops Hub。
  - sidecar 不携带远端 PostgreSQL/Redis，也不直接连接 Remote Agent。

### Tauri Updater

- 官方文档：
  - https://v2.tauri.app/plugin/updater/
- 采用结论：
  - 自动更新属于 M9/M10 发行加固项。
  - 更新产物必须签名并保存 checksum；签名私钥不进入仓库或构建日志。

## 2. 桌面本地存储

### Tauri SQL Plugin

- 官方文档：
  - https://v2.tauri.app/plugin/sql/
- 采用结论：
  - 桌面端使用独立 SQLite 保存服务器 profile、UI 设置、只读缓存、草稿和事件
    sequence/cursor。
  - SQLite migration 与服务端 Alembic migration 分开维护。
  - React 层不直接接受任意 SQL；通过 Rust command/repository 封装固定查询。

### Tauri Stronghold

- 官方文档：
  - https://v2.tauri.app/plugin/stronghold/
- 采用结论：
  - access/refresh token、Ed25519 device private key 等敏感值进入 OS credential store 或
    Stronghold，不写入 SQLite、前端日志或 crash report。

### SQLite 官方边界

- 官方文档：
  - https://sqlite.org/serverless.html
  - https://sqlite.org/whentouse.html
  - https://sqlite.org/onefile.html
- 采用结论：
  - SQLite 适合单机、嵌入式、零配置、本地文件型数据。
  - CloudHelm Desktop 的缓存与草稿符合该使用场景。
  - 多客户端、常在线、多 worker 并发写、审批和 durable WorkflowJob 不迁移到
    SQLite。

## 3. 远端权威数据库

### PostgreSQL Client/Server Architecture

- 官方文档：
  - https://www.postgresql.org/docs/current/tutorial-arch.html
- 采用结论：
  - PostgreSQL 保留为常在线 Ops Hub 的权威数据库。
  - Project、Task、AgentRun、Approval、EventLog、WorkflowJob、Deployment 和审计
    状态均由服务端 PostgreSQL 保存。
  - Docker Compose PostgreSQL 可继续用于本地开发和单机 demo；桌面最终用户安装
    不以 Docker Desktop、PostgreSQL 或 Redis 为前置条件。

## 4. 本阶段取舍

```text
CloudHelm Desktop
  -> Tauri + React
  -> SQLite 非权威本地数据
  -> OS credential store
  -> 可选 local-runtime sidecar

CloudHelm Ops Hub
  -> FastAPI / Orchestrator / Agents / Tool Gateway / Workflow Engine
  -> PostgreSQL 权威数据
  -> Redis/Celery 非权威投递

Managed Project
  -> 独立源码、依赖、数据、Dockerfile/Compose
  -> 可选 CloudHelm project contract
  -> 不依赖 CloudHelm SDK、数据库或控制台才能运行
```

本次只冻结文档和计划；Tauri、SQLite、认证、同步 API、Ops Hub 安装器和通用项目
manifest 尚未进入生产代码。
