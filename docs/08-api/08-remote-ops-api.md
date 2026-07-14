# Remote Ops API

> 来源：[设计书 12 章](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：锁定 M7 远端只读运维 API，并区分 M8 与后续增强能力。
## 实现注意点

- 请求和响应模型应写入 OpenAPI，并同步生成前端类型。
- 涉及任务状态、工具调用、审批和远端操作的接口必须写事件日志。
- 列表接口需要分页、过滤和按 project/environment/task 过滤。
- 服务和 RemoteTarget 必须由已批准 Deployment 派生；调用方不得传入任意
  endpoint、host、path 或 command。

## M7 Remote Ops API

这些接口只操作由 Deployment Controller 与 Remote Agent 注册的远端业务服务：

```text
GET    /api/environments/{environment_id}/services
GET    /api/services/{service_id}/status
GET    /api/services/{service_id}/logs
GET    /api/services/{service_id}/logs/stream
POST   /api/services/{service_id}/collect-diagnostics
```

约束：

- `status` 只返回服务版本、部署、健康与 Remote Agent 采样时间，不执行远端动作。
- `logs` 与 `logs/stream` 由 Remote Agent 直读 allowlist 服务，必须限制查询时间、
  行数、总字节、连接时长和并发，并在 Platform API 返回前执行脱敏；它们不是
  Loki 或其他集中日志查询接口。
- `collect-diagnostics` 只接受服务端预定义的只读 profile，不接受 shell、命令、
  脚本、任意路径或任意环境变量。
- 每次 logs/diagnostics 调用都记录 ToolCall、目标服务、边界参数、结果摘要、
  `trace_id` 和审计事件，不保存未脱敏的完整输出。

## M8 监控与运维扩展

以下能力属于 M8，不属于 M7：

```text
GET    /api/services/{service_id}/metrics
POST   /api/services/{service_id}/restart-request
```

M8 通过 Prometheus/Loki/Alertmanager 或等价真实链路提供 metrics、集中日志、
告警、incident 与 runbook proposal；重启请求必须形成独立高风险审批，不得复用
M7 diagnostics。

## M8 之后的增强版

交互式远程接管不属于 M7 或 M8 默认闭环。若后续实现，独立规划
`remote-sessions`、WebSocket terminal、命令 allowlist、会话审计和接管摘要，
不得把 diagnostics 扩展为隐式 shell。
