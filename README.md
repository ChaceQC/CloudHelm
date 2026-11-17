# 云舵 CloudHelm

云舵 CloudHelm 是一款面向多 Agent 协作开发、远程交付与持续运维的平台。

## 当前基线

目前可从源码运行 Hub 和 Windows 开发版 Desktop，还没有正式发布或产品安装包。当前检出版本见 [软件版本清单](pyproject.toml)，新库迁移目标见 [Hub 初始化](docs/development/p1-hub.md#2-受控数据库初始化)。`v4.7` 是设计文档版本。

开发环境目前可以：

- 在 WSL 启动 Hub API 和一个 worker，创建用户和项目、分配角色，并通过 [Windows Desktop](docs/development/p1-desktop.md) 提交、跟踪和取消任务。
- 在任务页启动或继续一个 Agent，查看文件改动、工具结果和等待状态。每轮运行有时间、模型请求次数和费用限制，模型请求和工具调用分别检查权限，见 [Agent 运行说明](docs/development/p2-runtime.md)。
- 在受限环境中编辑和构建固定参照项目，保存可复现的[候选版本](docs/development/p2-candidates.md)。可以对固定版本[执行验收](docs/development/p2-verification.md)、[审查改动](docs/development/p2-review.md)并[退回返工](docs/development/p2-rework.md)；也可[人工接管编辑并交还](docs/development/p2-handoffs.md)。[合并队列](docs/development/p2-merge-queue.md)对最终提交重新构建、验证和审查。
- 为固定参照项目编制归档和部署计划，在 Desktop 上按计划摘要批准。远端实际启动还需要适用的[时间和资源证明](docs/development/p1-remote-agent.md)。

开发端提供[预览与可选人工测试](docs/development/p2-previews.md)流程。正式客户端预览入口默认关闭，支持范围以[验收矩阵](docs/acceptance/support-matrix.md)为准。

## 开发与验证入口

|用途|说明|
|---|---|
|[Hub 开发与维护](./docs/development/p1-hub.md)|在 WSL 安装锁定依赖、配置独立数据库角色、初始化用户/项目并启动 API 与单 worker|
|[Agent 运行说明](./docs/development/p2-runtime.md)|配置模型与凭据，了解每轮运行的权限和预算限制|
|[Windows 工程工作台](./apps/desktop/README.md)|构建/启动真实基础 Desktop，连接 Hub，提交任务、批准计划、查询及取消|
|[Git、工作区与受限构建](./docs/development/p1-engineering.md)|工程入口、已实现能力和限制|
|[共享宿主资源与 Runner](./docs/development/p1-resources.md)|池注册、资源申请、受控执行和未知结果核对|
|[归档交付与计划批准](./docs/development/p1-delivery.md)|Release/配置/计划、可信目标事实和当前远端接入边界|
|[日常定向检查](./docs/development/checks.md)|契约、Git/OCI 边界及按需数据库、存储和参照 HTTP 检查|
|[P0 历史接缝复现](./docs/development/p0-seams.md)|按原提交取回历史实验；兼容范围见[组件基线](./docs/decisions/p0/component-baseline.md)和[接缝结论](./docs/acceptance/p0/seam-summary.md)|
|[契约查看与窄检查](./docs/development/p0-decisions.md)|查看 [P0 决定模型与 JSON Schema](./packages/contracts/p0/README.md)及 [Hub HTTP/内部交接类型](./packages/contracts/p1/README.md)，按各自范围校验|
|[全栈便签参照](./examples/standalone-project/README.md)|在 WSL 用 Compose 运行 React/FastAPI/PostgreSQL 与线性 Alembic 示例，仅供本机合成数据使用；源码与独立 HTTP 验收资产分开提供，边界见[首链规格](./docs/implementation/reference-chain.md)和[支持矩阵](./docs/acceptance/support-matrix.md)|
|[五套 HTML 界面方案](./examples/desktop-examples.md)|任务看板、部署航线、对象工作台、事件卷宗和命令中心；直接打开 HTML，以本地数据演示 P1.5 操作|

## 技术方向

技术选型及接入范围以设计和当前工程为准：

- Hub：FastAPI、Pydantic、SQLAlchemy、PostgreSQL、Alembic。
- 持久工作流：DBOS Python；Agent 协议运行时选用 PydanticAI，完整 Agent 链路尚未接入。
- 桌面端：Tauri、React、TypeScript，当前提供 Windows 基础工程。
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
