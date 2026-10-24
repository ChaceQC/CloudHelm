# 云舵 CloudHelm

云舵 CloudHelm 是一款面向多 Agent 协作开发、远程交付与持续运维的平台。

## 当前基线

**Hub 开发源码 `0.4.0` · 数据库迁移 `0005` · 尚无正式发布、tag 或 Release**

仓库当前提供 **Hub 开发源码、v4.7 设计资料、执行计划、隔离接缝工程和全栈参照项目**，已具备的能力为：

- 受控数据库初始化、用户/项目与角色管理、Task 命令和唯一完成报告；
- 独立运行的 API 与单 worker 进程；
- 固定参照的 Git 工作区、候选、离线构建和制品记录；
- 共享宿主资源预留、Runner 注册、本地持久确认与受限 scratch 执行。

当前增量开发环境的实现与适用证据见[工程说明](docs/development/p1-engineering.md)。v4.7 是设计文档版本，与软件版本分开管理。

Task 推进受当前授权和证据门禁约束，具体阻断见 [Hub 开发说明](./docs/development/p1-hub.md)。完整 Agent 开发、Desktop 和远程交付继续按设计分阶段接入，**当前不提供产品安装包**。

## 开发与验证入口

|用途|说明|
|---|---|
|[Hub 开发与维护](./docs/development/p1-hub.md)|在 WSL 安装锁定依赖、配置独立数据库角色、初始化用户/项目并启动 API 与单 worker|
|[Git、工作区与受限构建](./docs/development/p1-engineering.md)|工程入口、已实现能力和限制|
|[共享宿主资源与 Runner](./docs/development/p1-resources.md)|池注册、资源申请、受控执行和未知结果核对|
|[P0 接缝使用说明](./docs/development/p0-seams.md)|按需复现 SDK、数据库、工具协议与 Compose 接缝；兼容范围见[组件基线](./docs/decisions/p0/component-baseline.md)和[接缝结论](./docs/acceptance/p0/seam-summary.md)|
|[契约查看与窄检查](./docs/development/p0-decisions.md)|查看 [P0 决定模型与 JSON Schema](./packages/contracts/p0/README.md)及 [Hub HTTP/内部交接类型](./packages/contracts/p1/README.md)，按各自范围校验|
|[全栈便签参照](./examples/standalone-project/README.md)|在 WSL 用 Compose 运行 React/FastAPI/PostgreSQL 与线性 Alembic 示例，仅供本机合成数据使用；源码与独立 HTTP 验收资产分开提供，边界见[首链规格](./docs/implementation/reference-chain.md)和[支持矩阵](./docs/acceptance/support-matrix.md)|

## 技术方向

技术选型及接入范围以设计和当前工程为准：

- Hub：FastAPI、Pydantic、SQLAlchemy、PostgreSQL、Alembic。
- 持久工作流：DBOS Python；Agent 协议运行时选用 PydanticAI，完整 Agent 链路尚未接入。
- 桌面端：计划使用 Tauri、React、TypeScript。
- 开发、构建与交付环境：Docker Compose，按受支持范围逐步接入。

工程动作需要显式授予；已有 owner、角色和委托不会自动获得新增权限，授权规则见[工程开发说明](./docs/development/p1-engineering.md)。

## 阅读入口

- [总体设计书：云舵 CloudHelm 毕设设计书 v4.7](./云舵%20CloudHelm%20毕设设计书%20v4.7.md)
- [详细设计索引](./docs/design/README.md)
- [D06：实施计划与验收](./docs/design/06-implementation-validation.md)
- [项目执行计划](./PROJECT_PLAN.md)
- [架构图与可编辑源文件](./docs/architecture/)
- [历史设计归档](./docs/archive/)
- [仓库开发规范](./AGENTS.md)
- [项目进度](./PROJECT_PROGRESS.md)
- [GitHub 协作与合并流程](./docs/GitHub协作与合并流程.md)

## 仓库协作

公开仓库：[ChaceQC/CloudHelm](https://github.com/ChaceQC/CloudHelm)。分支约定为 `main` 作为默认分支、`dev` 作为开发分支。具体协作和合并规则见 [GitHub 协作与合并流程](./docs/GitHub协作与合并流程.md)。
