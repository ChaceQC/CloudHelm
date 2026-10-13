# 云舵 CloudHelm

云舵 CloudHelm 是一款面向多 Agent 协作开发、远程交付与持续运维的平台。

## 当前基线

仓库目前提供 **v4.7 设计资料与执行计划**，业务软件尚未实现，暂不提供安装包或可运行的启动、构建命令。v4.7 是设计文档版本，不是软件版本。

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
