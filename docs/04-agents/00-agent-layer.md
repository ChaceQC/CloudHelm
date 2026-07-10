# Agent 分层总览

> 来源：[设计书 8.1](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：汇总所有 Agent 角色、职责和工具边界。
## 分工原则

- Requirement / Planner / Architect 负责需求和设计质量。
- Scaffold / Coder / Tester / Reviewer 负责本地开发闭环。
- Security / Release / Deploy / SRE 负责安全、Agent 化发布部署和远端业务运维闭环。

## M4 落地状态

M4 已新增 `modules/agent-runtime`，实现 Requirement、Architect、Planner 三类 Agent 的结构化输入输出和 provider 边界：

- Requirement Agent 读取真实 Task，输出 `requirement_specs` 所需的 `user_story`、`constraints_json` 和 `acceptance_criteria_json`。
- Architect Agent 读取最新 RequirementSpec，输出 `technical_designs` 所需的 ADR 正文、OpenAPI 草案、DB schema 草案、Mermaid 和风险等级。
- Planner Agent 读取已通过 TechnicalDesign，输出 `development_plans` 的任务图和风险说明。

M4 默认 provider 为 `local_structured`，它基于真实输入生成结构化草案并通过 Pydantic 校验；`openai_compatible` provider 仅在提供外部模型配置后启用，默认使用 Responses API，可配置 `reasoning.effort=max` 并透传 `gpt-5.6-sol` 等显式模型字符串。瞬时请求和无效结构化响应执行有界指数退避，耗尽后记录失败 AgentRun 并暂停可恢复 Task。M4 不允许上述 Agent 调用 Repo、Sandbox、Git、Docker、SSH、部署或监控工具。

## 设计书摘录

### 8.1 Agent 角色

|Agent|职责|允许工具|
|---|---|---|
|Requirement Agent|解析开发者输入的目标、需求文档、Issue、截图或接口说明，提取用户故事、约束和验收标准|requirement.parse、spec.update、repo read|
|Planner Agent|理解开发目标、拆解步骤、评估风险、生成迭代计划和任务图|只读 repo、issue、spec、日志、指标|
|Architect Agent|设计模块边界、API、数据库 schema、状态机、目录结构和技术方案|design.generate、spec.update、repo read|
|Scaffold Agent|根据模板创建项目骨架、模块目录、配置文件、CI 文件和基础测试|scaffold.generate、repo write、sandbox exec|
|Coder Agent|根据需求和技术方案实现功能、修改代码、补测试、生成 patch|repo write、sandbox exec、git diff|
|Tester Agent|安装依赖、运行测试、分析失败原因|sandbox exec、ci logs、test report|
|Reviewer Agent|审查 diff、指出风险、判断是否满足需求|repo read、git diff、安全扫描结果|
|Security Agent|运行 Semgrep / Trivy / dependency audit|security scan、repo read|
|Release / Deploy Agent|生成远端业务项目的 release plan，审批通过后执行 staging / demo 部署，检查发布健康状态，并生成 canary / rollback 建议|ci status、deploy plan、deploy staging、release status；实际部署需审批|
|SRE Agent|分析远端业务项目的告警、日志、指标，建议 runbook|monitor read、logs search、低风险 runbook|
