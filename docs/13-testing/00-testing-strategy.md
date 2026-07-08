# 测试方案

> 来源：[设计书 17 章](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：定义单元测试、集成测试和 E2E 答辩演示测试。
## 测试分层

- 单元测试：验证单模块逻辑和权限边界。
- 集成测试：验证需求、设计、实现、测试、PR、部署、远端状态回传。
- E2E 演示测试：演示开发者指导 Agents 实现功能，再由 Release / Deploy Agent 部署到远端 staging，然后触发监控告警和 SRE 分析。

## 设计书摘录

## 17. 测试方案

### 17.1 单元测试

|模块|测试重点|
|---|---|
|platform-api|API 参数校验、状态转换、权限校验|
|orchestrator|状态机流转、失败重试、human-in-the-loop|
|agent-runtime|需求解析、技术设计生成、结构化输出解析、模型错误恢复|
|spec-store|需求版本、验收标准、ADR、OpenAPI、数据库 schema 的保存和读取|
|tool-gateway|权限判断、审批拦截、审计记录|
|toolservers|工具参数、路径安全、错误处理|
|sandbox-runner|容器创建、命令超时、资源限制|
|deployment-controller|部署计划生成、版本记录、健康检查、回滚计划|
|remote-agent|心跳、命令执行、日志流、服务状态采集|
|monitoring-collector|指标查询、日志查询、告警转换、incident 事件生成|

### 17.2 集成测试

1. 开发者输入功能需求后能启动 Agent workflow。
2. Requirement Agent 能生成 requirement_spec 和 acceptance_criteria。
3. Architect Agent 能生成技术方案、OpenAPI 草案和数据库 schema。
4. 开发者能在控制台审批或要求修改技术方案。
5. Agent 能读取演示仓库文件。
6. Agent 能写入 sandbox worktree。
7. Agent 能运行测试。
8. Agent 能根据验收标准生成验收报告。
9. Agent 能生成 diff。
10. Agent 能创建 branch 和 PR。
11. L3 工具调用会进入审批。
12. 审批通过后工具继续执行。
13. 任务事件能实时推送到桌面端。
14. PR 合并后能触发远端 staging 部署。
15. Remote Agent 能回传远端业务项目服务状态。
16. Prometheus / Loki 能查询到远端业务项目指标和日志。
17. 远端业务项目异常能生成 ProjectAlert / Incident。

### 17.3 E2E 演示测试

准备一个可扩展的示例仓库，不只演示 bug 修复，而是演示“开发者指导 Agents 实现新功能”：

```text
examples/sample-repo-python/
  - 一个 FastAPI demo
  - 一个 React 前端 demo，可选
  - 初始状态缺少用户注册 / 登录 / 个人资料功能
  - 一个 OpenAPI 验收目标
  - 一个基础健康检查接口
```

演示流程：

```text
1. 开发者在控制台输入目标：为示例项目增加用户注册、登录和个人资料功能。
2. Requirement Agent 生成需求规格和验收标准。
3. Architect Agent 生成 API 设计、数据库设计、模块划分和风险说明。
4. 开发者审批方案或提出修改意见。
5. Planner Agent 拆分后端、前端、测试、文档任务。
6. Coder Agent 在本地 sandbox 中实现功能。
7. Tester Agent 运行 pytest / vitest / Playwright。
8. Security Agent 运行 Semgrep / Trivy。
9. Reviewer Agent 检查 diff 是否满足验收标准。
10. 系统创建 PR。
11. 开发者在控制台查看 diff、测试报告和验收结果，并审批合并。
12. CI 构建镜像。
13. Release / Deploy Agent 经审批后调用 Deployment Controller 部署到远端 staging。
14. 控制台展示远端业务项目版本、健康状态、日志、指标。
15. 人为触发一个远端接口错误或停止服务。
16. Monitoring Collector 收到告警。
17. SRE Agent 分析远端业务项目日志和指标，提出 runbook 或修复 PR。
```

---
