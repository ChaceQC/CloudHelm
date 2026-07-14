# 毕设阶段计划

> 来源：[设计书 18 章](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：按八个阶段拆分实现路线。
## 执行顺序

基础平台 -> Agent 编排 -> 工具系统 -> Git/PR 闭环 -> 远端部署闭环 -> 监控运维 -> 审批安全观测 -> 答辩演示材料。

## 设计书摘录

## 18. 毕设阶段计划

### 第一阶段：基础平台

目标：跑通项目、任务、事件、控制台。

任务：

1. 搭建 Monorepo。
2. 搭建 FastAPI + PostgreSQL + Redis。
3. 实现 Project / Task / Requirement / Design / Event API。
4. 搭建 Tauri + React 控制台。
5. 实现需求输入、任务列表、任务详情、事件流。

### 第二阶段：Agent 编排

目标：让 Agent 能从开发者需求开始，按“需求澄清 -> 技术设计 -> 任务拆分 -> 实现 -> 测试 -> 审查”状态机执行。

任务：

1. 集成 LiteLLM。
2. 集成 LangGraph。
3. 实现 Requirement / Planner / Architect / Coder / Tester 五个 Agent。
4. 定义结构化输出 schema。
5. 实现需求规格、技术方案、验收标准和任务状态机。

### 第三阶段：工具系统

目标：让 Agent 可以真实调用工具。

任务：

1. 实现 Tool Gateway。
2. 实现 Requirement Tool 和 Design Tool。
3. 实现 Scaffold Tool。
4. 实现 Repo Tool。
5. 实现 Git Tool。
6. 实现 Sandbox Tool。
7. 记录 tool_calls。
8. 实现工具风险等级。

### 第四阶段：Agent 开发与 Git / PR 闭环

目标：完成从“开发者功能需求”到 PR。

任务：

1. 部署 Gitea。
2. 实现仓库 clone / worktree。
3. 实现基于模板的新项目 / 新模块生成。
4. 实现 branch / commit。
5. 实现 create PR。
6. 控制台展示需求规格、技术方案、diff、测试报告、验收结果和 PR 链接。

### 第五阶段（M7）：CI/CD 与远端部署闭环

目标：把 M6 的精确 PullRequestRecord / commit 经 release candidate approval、
受控 ref、唯一 `workflow_dispatch`、CI 不可变 OCI digest、ReleasePlan 和
deployment approval 后，由 Deployment Controller 与 Remote Agent 部署到远端
staging/demo。

任务：

1. 实现 RepositoryBinding、Environment、RemoteTarget、Remote Agent machine
   authentication、心跳和状态上报。
2. 创建绑定最新版 PullRequestRecord、完整 commit、candidate ref 和 request
   hash 的 release candidate approval。
3. 审批通过后发布受控 ref，并对不监听 push 的固定 workflow 执行唯一一次
   `workflow_dispatch`。
4. CI 只执行 test/security/build/artifact，输出 manifest、报告和不可变 OCI
   digest，不在 workflow 内执行部署。
5. Release / Deploy Agent 校验 PR/commit/manifest/digest 全链并生成 ReleasePlan。
6. 为精确 ReleasePlan、digest、Environment 和 RemoteTarget 创建第二道
   deployment approval。
7. 审批通过并显式推进后，由 Deploy Tool 调用 Deployment Controller，再由
   Remote Agent 执行受控 Docker Compose、digest 复核和健康检查。
8. 实现远端部署、服务 status、受限直读 logs 和固定 diagnostics API。
9. 控制台展示两道审批、CIRun、ReleasePlan、不可变 digest、部署 operation、
   服务健康、受限 logs 和 diagnostics。

M7 不提供 remote session、服务重启、metrics、集中日志、告警或自动回滚。

### 第六阶段（M8）：远端业务项目监控运维

目标：对远端已部署业务项目进行实时监控和运维分析。

任务：

1. 在远端部署 node_exporter、cAdvisor、Grafana Alloy / Fluent Bit。
2. 接入 Prometheus、Loki、Alertmanager。
3. 实现 Monitoring Tool：
   - query_metrics
   - search_logs
   - list_alerts
   - get_recent_deployments
4. 实现 ProjectAlert / Incident 数据流。
5. 实现 SRE Agent 告警分析。
6. 实现 runbook proposal。
7. 对重启服务、回滚版本等动作接入审批。

### 第七阶段：审批、安全与观测

目标：体现平台安全边界和工程价值。

任务：

1. 实现 Approval API。
2. 实现审批面板。
3. 实现 Semgrep / Trivy 工具。
4. 接入 Langfuse。
5. 接入 Prometheus / Grafana。
6. 实现成本和工具调用统计。

### 第八阶段：答辩演示与论文材料

目标：准备可演示闭环和实验数据。

任务：

1. 准备示例需求、示例仓库和待实现功能。
2. 准备远端 staging / demo 部署环境。
3. 录制或现场演示“开发者指导 Agents 实现功能 -> PR record / 精确 commit ->
   candidate approval -> 受控 ref / 唯一 CI -> 不可变 digest -> ReleasePlan /
   deployment approval -> Controller / Remote Agent 部署”。
4. 在 M8 验证后演示远端业务项目监控、告警、集中日志分析和 runbook 建议。
5. 统计任务耗时、工具调用次数、测试通过率、部署耗时、告警响应时间。
6. 编写系统设计、实现细节、测试报告。
7. 准备风险分析和后续展望。

---
