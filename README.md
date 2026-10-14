# 云舵 CloudHelm

云舵 CloudHelm 是一款面向多 Agent 协作开发、远程交付与持续运维的平台。

## 当前基线

仓库目前提供 **v4.7 设计资料、执行计划、P0 隔离接缝工程和全栈参照项目**。CloudHelm 产品尚未实现，暂不提供产品安装包或业务启动命令。v4.7 是设计文档版本，不是软件版本。

隔离工程用于核验 SDK、数据库、工具协议和 Compose 边界，开发者可按 [P0 接缝使用说明](./docs/development/p0-seams.md) 安装锁定依赖、启动临时数据库并执行对应探测；实际兼容范围见 [组件基线](./docs/decisions/p0/component-baseline.md) 和 [接缝结论](./docs/acceptance/p0/seam-summary.md)。

[P0 决定契约](./packages/contracts/p0/README.md) 提供身份、迁移、资源、Task 控制、许可、预览及核心映射的可校验模型和 JSON Schema。开发者可按 [契约使用说明](./docs/development/p0-decisions.md) 在 WSL 执行不连接外部服务的窄检查；这些模型尚未接入产品运行入口。

[全栈便签参照](./examples/standalone-project/README.md) 包含 React、FastAPI、PostgreSQL 和线性 Alembic 迁移，可在 WSL 通过 Compose 运行。入口仅供本机合成数据使用，源码与独立 HTTP 验收资产分开提供；候选组合和使用边界见 [首条链路规格](./docs/implementation/reference-chain.md) 与 [支持矩阵](./docs/acceptance/support-matrix.md)。

## 技术方向

以下为总体设计中的技术选型，仍待分阶段实现和验证：

- 桌面端：Tauri、React、TypeScript。
- 服务端：FastAPI、Pydantic、SQLAlchemy、PostgreSQL、Alembic。
- Agent 与持久工作流：PydanticAI、DBOS Python。
- 开发、构建与交付环境：Docker Compose。

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
