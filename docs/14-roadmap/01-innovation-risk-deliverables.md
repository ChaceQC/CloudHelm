# 创新点、风险与预期成果

> 来源：[设计书 19-21 章](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：汇总论文和答辩材料需要强调的创新、风险控制和成果列表。
## 用途

- 写论文绪论、系统特色、风险分析和成果展示时优先引用本页。
- 写答辩 PPT 时可按“创新点 -> 风险控制 -> 软件/文档/演示成果”组织。

## 设计书摘录

## 19. 创新点

1. **不是单 Agent 聊天，而是事件驱动的软件工程操作系统。**
2. **Agent 与工具解耦**：通过 MCP 和 Tool Gateway 管理工具调用。
3. **人机协同闭环**：M7 以 release candidate approval 和 deployment approval
   两道门禁控制发布，保留 Pause、Reject 和 rollback request；远程 Takeover
   与自动回滚属于后续增强。
4. **安全可控**：工具风险分级、审批流、审计日志、sandbox 隔离。
5. **工程闭环完整**：从开发者需求、Agent 规格化、技术设计、代码实现、测试、扫描到 PR。
6. **本地到云端闭环**：从精确 PullRequestRecord / commit 开始，经 candidate
   approval、受控 ref、唯一 `workflow_dispatch`、CI 不可变 digest、ReleasePlan
   和 deployment approval，再由 Controller / Remote Agent 执行远端部署。
7. **远端业务项目运维闭环（M8）**：把集中日志、指标、告警、部署版本和
   runbook 关联到同一个 project / environment / service。
8. **桌面控制台体验**：参考 Codex，将复杂 Agent 执行过程和远端业务运行状态可视化。
9. **可观测 Agent 系统**：记录 token、成本、trace、工具调用和任务状态。

---

## 20. 风险与应对

|风险|说明|应对|
|---|---|---|
|范围过大|完整 DevOps 平台工作量大|M7 只做 staging 部署、status、受限 logs 和固定 diagnostics；集中监控进入 M8，remote session 属于后续增强|
|LLM 输出不稳定|Agent 可能生成错误计划|强制结构化输出、状态机校验、Reviewer Agent|
|需求不清晰|开发者目标可能过于抽象，导致 Agent 实现偏离预期|Requirement Agent 先生成验收标准，关键设计必须人工审批|
|架构设计错误|Agent 可能生成不合理 API、数据库或模块结构|Architect Agent 输出 ADR / OpenAPI / DB schema，并由 Reviewer 和开发者共同审查|
|工具调用危险|Agent 可能执行破坏性命令|Docker sandbox、Tool Gateway、风险分级、审批|
|远端操作危险|错误重启、回滚或任意 shell 可能影响远端业务项目|M7 不提供重启、自动回滚或 remote session；部署经两道审批，Remote Agent 只执行固定请求并完整审计|
|监控链路复杂|Prometheus、Loki、exporter、Remote Agent 都要部署|M7 先完成 Remote Agent 直读状态/日志/diagnostics；M8 再接集中采集链路|
|集成过多|Gitea、CI、Prometheus、Loki、Langfuse 都要部署|按 M7 部署、M8 监控、M9 平台观测分阶段接入，优先 Docker Compose|
|演示失败|现场模型或网络不稳定|准备固定示例仓库、可缓存模型输出，并保留 Remote Agent 固定 diagnostics 与可追溯部署证据|
|安全扫描误报|Semgrep / Trivy 可能有噪声|将扫描作为 Reviewer 输入，不直接阻断所有流程|

---

## 21. 预期成果

### 21.1 软件成果

1. 一个可运行的桌面控制台。
2. 一个 FastAPI 平台服务。
3. 一个 LangGraph Agent 编排器。
4. 一套 MCP Tool Server。
5. 一个 Docker Sandbox Runner。
6. 一个 Gitea 集成闭环。
7. 一套需求规格化与技术设计模块。
8. 一个项目脚手架 / 模块生成能力。
9. 一个 M7 Remote Agent。
10. 一个 M7 Deployment Controller。
11. 一个 M7 远端业务项目部署演示环境。
12. 一个 M8 远端业务项目监控与告警演示。
13. 一个“开发者指导 Agents 实现功能、Agent 执行远端部署、监控运维”闭环演示。

### 21.2 文档成果

1. 系统需求分析。
2. 总体架构设计。
3. Agent 设计文档。
4. Tool Gateway 设计文档。
5. 需求规格与技术设计文档。
6. 数据库设计文档。
7. API 文档。
8. 测试报告。
9. 部署说明。
10. 远端运维设计文档。
11. 毕设论文。

### 21.3 演示成果

最终演示应能完成：

```text
开发者创建功能开发目标
  -> Requirement Agent 生成需求规格和验收标准
  -> Architect Agent 生成 API、数据库和模块设计
  -> 开发者审批或修改方案
  -> Coder Agent 实现功能
  -> Sandbox 运行测试
  -> Security Agent 扫描
  -> Reviewer Agent 审查需求符合度和代码质量
  -> 创建 PullRequestRecord 并固化精确 commit
  -> 用户批准 release candidate
  -> 发布受控 ref 并唯一 workflow_dispatch
  -> CI 生成 manifest 与不可变 OCI digest
  -> Release / Deploy Agent 生成 ReleasePlan
  -> 用户批准 deployment approval
  -> Deployment Controller 调用 Remote Agent 部署 staging
  -> M7 控制台展示服务 status、受限 logs 和固定 diagnostics
  -> M8 采集集中日志、指标并触发告警
  -> M8 SRE Agent 分析并提出 runbook / 修复 PR
```

---
