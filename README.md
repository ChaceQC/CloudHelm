# 云舵 CloudHelm

云舵 CloudHelm 是一款面向多 Agent 协作开发、远程交付与持续运维的平台。

## 当前基线

**Hub 开发源码 `0.29.0` · 数据库迁移 `0020` · 尚无正式发布、tag 或 GitHub Release**

仓库当前提供 **Hub 开发源码、v4.7 设计资料、执行计划、历史接缝记录和全栈参照项目**，已具备的能力为：

- 受控数据库初始化、用户/项目与角色管理、Task 命令和唯一完成报告；
- 独立运行的 API 与单 worker 进程；
- 真实 PydanticAI 的有界内部 Run、工程上下文与工作区读取/搜索、文件编辑/差异、固定开发环境、候选构建/结果及后端语法/API 自测工具、有界开发循环与交接、逐次模型/工具准入、供应商 usage/精确费用及原操作等待，见[Runtime 说明](docs/development/p2-runtime.md)；
- 固定参照的 Git 工作区、候选、离线构建和制品记录；
- 绑定精确构建、制品和受控验证环境的不可变候选/InputSet，见[固定候选说明](docs/development/p2-candidates.md)；
- 受控正式 HTTP 验收、独立验证角色的固定候选读取/阶段执行/报告交接、不可变完整性报告、精确证据选择与输入变化后的消费者门禁，见[正式验收说明](docs/development/p2-verification.md)；
- 只读审查角色的固定差异、代码与构建/验证证据读取，以及带位置、理由和证据的结构化反馈，见[审查说明](docs/development/p2-review.md)；
- 增量/固定候选预览、一次性票据及可选人测，见[预览与人测说明](docs/development/p2-previews.md)；客户端路线按独立隔离证据开放，默认关闭；
- 验证/审查问题到原开发工作项的持久返工交接、开发会话反馈、新候选重验及问题关闭依据，见[返工说明](docs/development/p2-rework.md)；
- 服务端受控人工接管、按版本编辑及显式交还，固定前后快照和文件差异，见[写入权交接说明](docs/development/p2-handoffs.md)；
- 项目合并队列、最终提交的独立验证与审查，以及权威分支条件更新，见[集成说明](docs/development/p2-merge-queue.md)；
- 共享宿主资源预留、Runner 注册、本地持久确认、受限 scratch 及固定工程资源组；
- 受管构建/开发环境、进程与磁盘分维释放，以及 backing 持续占账；
- 固定参照的归档 Release、独立环境配置、部署计划、人类摘要批准和启动前复核；
- Windows 基础 Desktop 的真实任务提交/控制、Agent 启动与显式继续、工作项差异/工具结果/等待查询、计划摘要批准、项目快照和 SSE 状态展示；
- Remote Agent 的认证通道、持久账本和固定执行适配，普通启动仍受[适用时间与资源证明门禁](docs/development/p1-remote-agent.md)约束。

当前增量开发环境的实现与适用证据见[工程说明](docs/development/p1-engineering.md)。v4.7 是设计文档版本，与软件版本分开管理。

Task 推进受当前授权和证据门禁约束，具体阻断见 [Hub 开发说明](./docs/development/p1-hub.md)。基础 Desktop 的运行和边界见[客户端说明](./docs/development/p1-desktop.md)；完整 Agent、跨端客户端和远程交付继续按设计分阶段接入，**当前不提供产品安装包**。

## 开发与验证入口

|用途|说明|
|---|---|
|[Hub 开发与维护](./docs/development/p1-hub.md)|在 WSL 安装锁定依赖、配置独立数据库角色、初始化用户/项目并启动 API 与单 worker|
|[有界 Agent Runtime](./docs/development/p2-runtime.md)|内部启动、模型能力和凭据配置、逐次准入与支持边界|
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
