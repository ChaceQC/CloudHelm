# 测试与验收矩阵细化

> 来源：设计书 17、22 章  
> 目的：把 MVP 验收标准转成可执行测试项和答辩演示证据。

## 1. 单元测试矩阵

|模块|测试项|建议工具|
|---|---|---|
|platform-api|请求参数校验、统一 500、严格 cursor、最新优先分页、状态更新|pytest + TestClient|
|platform-api|Task pause/resume/cancel 及 AgentRun/ToolCall/Approval 级联关闭|pytest|
|orchestrator|状态机正常路径、失败路径、审批等待恢复|pytest|
|agent-runtime|Responses API max reasoning、瞬时 HTTP 重试、无效 JSON 重试、不可重试 4xx|pytest|
|tool-gateway|参数校验、工作区 allowlist、风险分级、权限拒绝、审批拦截、审计脱敏|pytest|
|toolservers|repo read/write、sandbox exec、git diff mock|pytest|
|sandbox-runner|命令超时、资源限制、artifact 收集|pytest + Docker|
|deployment-controller|release plan、compose 渲染、health check|pytest|
|remote-agent|heartbeat、service_status、stream_logs|pytest|
|monitoring-collector|Prometheus/Loki 查询结果转换事件|pytest|
|control-console|最新请求门禁、评审动作策略、SSE 重连/去重、生产构建|Node test + TypeScript|

## 2. 集成测试矩阵

|编号|场景|步骤|通过标准|
|---|---|---|---|
|IT-001|创建项目|POST /api/projects|projects 有记录，返回 200|
|IT-002|创建任务|POST /api/tasks|tasks 有记录，EventLog 有 TaskCreated|
|IT-003|需求规格化|触发 Requirement Agent|生成 RequirementSpec 和 AC|
|IT-004|技术设计|触发 Architect Agent|生成 TechnicalDesign、OpenAPI、DB schema|
|IT-005|设计审批|approve design|状态进入 Planning|
|IT-006|代码修改|Coder 调用 Repo Tool|sandbox worktree 有 diff|
|IT-007|测试运行|Tester 调用 Sandbox Tool|生成 TestReport|
|IT-008|代码审查|Reviewer 读取 diff 和 AC|生成 ReviewReport|
|IT-009|安全扫描|Security Agent 扫描|生成 SecurityReport|
|IT-010|创建 PR|Git Tool create_pr|Gitea PR 或等价 PR record|
|IT-011|部署审批|Release / Deploy Agent 通过 Deploy Tool 请求 staging|ApprovalRequest 风险 L3|
|IT-012|Agent 化远端部署|审批后 Release / Deploy Agent 调用 Deployment Controller 部署|DeploymentHealthy|
|IT-013|日志查询|控制台打开服务日志|返回远端业务日志|
|IT-014|指标查询|查询 service_up/error_rate|返回指标数据|
|IT-015|告警处理|触发服务不可用|ProjectAlertFired 和 Incident|
|IT-016|SRE 分析|触发 SRE Agent|生成 IncidentAnalysis 和 RunbookProposal|

## 3. E2E 演示脚本

### 前置条件

- 本地平台已启动。
- 示例仓库已导入 Gitea。
- 远端 demo 主机已安装 Docker Compose、Remote Agent、node_exporter、cAdvisor、日志采集器。
- 控制台能连接平台 API。

### 演示步骤

1. 在控制台选择 `sample-repo-python`。
2. 创建任务：增加用户注册、登录、个人资料功能。
3. 展示 Requirement Agent 生成的用户故事、约束、验收标准。
4. 展示 Architect Agent 生成的 API、DB schema、模块设计。
5. 点击批准设计。
6. 展示 Planner 任务拆分。
7. 展示 Coder 修改文件和 diff。
8. 展示 Tester 运行 pytest。
9. 展示 Reviewer 的需求符合度检查。
10. 展示 Security 扫描结果。
11. 创建 PR。
12. 审批合并和部署 staging。
13. 展示 Release / Deploy Agent 执行的远端部署版本、服务状态、日志、指标。
14. 人为触发故障，例如停止 api 容器。
15. 展示告警进入控制台。
16. 展示 SRE Agent 分析原因和 runbook 建议。
17. 审批 staging 重启或回滚。
18. 展示服务恢复。

## 4. MVP 验收标准映射

|设计书验收点|测试编号|演示证据|
|---|---|---|
|控制台创建功能开发任务|IT-002|任务创建页面、API 返回|
|任务状态实时变化|IT-002 至 IT-016|Task Timeline / SSE|
|Requirement Agent 生成规格|IT-003|RequirementSpec 页面|
|Architect Agent 生成技术设计|IT-004|Design Review 页面|
|开发者审批或修改方案|IT-005|Approval 记录|
|Agent 读取和修改示例仓库|IT-006|diff|
|Agent 在 sandbox 执行测试|IT-007|TestReport|
|系统生成 diff|IT-006|Diff Viewer|
|系统创建 branch 和 commit|IT-010|Git 记录|
|系统创建 PR 或等价记录|IT-010|PR 链接/PR record|
|Reviewer Agent 给出审查结论|IT-008|ReviewReport|
|工具调用记录可查看|全流程|Tool Calls 面板|
|L3 以上进入审批|IT-011|ApprovalRequest|
|Release / Deploy Agent 部署到远端 staging/demo|IT-012|DeploymentHealthy|
|Remote Agent 回传心跳和状态|IT-012|Remote status|
|控制台查看远端日志|IT-013|Logs panel|
|Prometheus 采集指标|IT-014|Metric panel|
|Loki 查询日志|IT-013|Log query|
|远端异常触发告警|IT-015|Alert / Incident|
|SRE Agent 给出分析|IT-016|IncidentAnalysis|
|全流程事件写入 event_logs|全流程|event_logs 查询|

## 5. 缺陷分级

|等级|说明|示例|
|---|---|---|
|P0|阻断主闭环|不能创建任务、状态机崩溃、部署完全不可用|
|P1|阻断关键演示步骤|无法生成 PR、审批无法恢复、远端日志不可见|
|P2|影响体验但可绕过|页面刷新不及时、某些字段显示不完整|
|P3|文案或低风险问题|错别字、非关键布局问题|

## 6. 答辩证据归档

每次完整 E2E 演示后保存：

```text
artifacts/demo-run-YYYYMMDD-HHMM/
├── requirement_spec.json
├── technical_design.md
├── openapi.yaml
├── db_schema.sql
├── diff.patch
├── test_report.json
├── security_report.json
├── review_report.md
├── deployment_result.json
├── incident_analysis.md
├── screenshots/
└── timeline.json
```
