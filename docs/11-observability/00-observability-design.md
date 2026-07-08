# 可观测性设计

> 来源：[设计书 15 章](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：定义系统指标、日志和 trace 的采集范围。
## 观测目标

- 平台自身：任务成功率、Agent 耗时、工具失败率、审批等待、token 成本。
- 远端业务项目：部署成功率、服务可用性、错误率、延迟、容器重启、告警数量。
- Trace：从 task_id 串起 workflow、Agent、tool_call、deploy、remote health check 和 monitoring event。

## 设计书摘录

## 15. 可观测性设计

### 15.1 系统指标

|指标|说明|
|---|---|
|task_total|任务总数|
|task_success_rate|任务成功率|
|agent_run_duration_seconds|Agent 运行耗时|
|tool_call_total|工具调用次数|
|tool_call_failure_total|工具调用失败次数|
|approval_wait_seconds|审批等待时间|
|requirement_clarification_total|需求澄清次数|
|design_revision_total|技术方案修改次数|
|acceptance_criteria_pass_rate|验收标准通过率|
|sandbox_exec_duration_seconds|沙箱命令执行时间|
|llm_token_total|token 消耗|
|llm_cost_usd_total|模型成本|
|project_deployment_total|远端业务项目部署次数|
|project_deployment_success_rate|远端业务项目部署成功率|
|project_service_up|远端业务服务是否可用|
|project_http_error_rate|远端业务项目 HTTP 错误率|
|project_http_latency_p95|远端业务项目 P95 延迟|
|project_container_restart_total|远端业务容器重启次数|
|project_alert_total|远端业务项目告警数量|
|remote_agent_heartbeat_age_seconds|远端 Agent 最近心跳时间|

### 15.2 日志

1. API 请求日志。
2. Agent 决策摘要。
3. 工具调用日志。
4. 沙箱命令输出。
5. CI 日志摘要。
6. 安全扫描报告。
7. 远端业务项目部署日志。
8. 远端业务项目应用日志。
9. 远端业务项目 runbook 执行日志。

### 15.3 Trace

一次任务应该能串起完整 trace：

```text
task_id
  -> workflow_run
      -> planner_agent_run
      -> tool_call repo.search_code
      -> coder_agent_run
      -> tool_call repo.write_file
      -> tool_call sandbox.run_tests
      -> reviewer_agent_run
      -> tool_call git.create_pr
      -> deploy_workflow
      -> remote_agent_deploy
      -> project_health_check
      -> monitoring_event
```

---
