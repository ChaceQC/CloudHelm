# Remote Ops API

> 来源：[设计书 12 章](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：给出该 API 分组的端点清单和实现注意点。
## 实现注意点

- 请求和响应模型应写入 OpenAPI，并同步生成前端类型。
- 涉及任务状态、工具调用、审批和远端操作的接口必须写事件日志。
- 列表接口需要分页、过滤和按 project/environment/task 过滤。

## 设计书摘录

### 12.7 Remote Ops API

这些接口的操作对象都是远端部署的业务项目。

```text
GET    /api/environments/{environment_id}/services
GET    /api/services/{service_id}/status
GET    /api/services/{service_id}/logs
GET    /api/services/{service_id}/metrics
POST   /api/services/{service_id}/restart-request
POST   /api/services/{service_id}/collect-diagnostics

POST   /api/remote-sessions
GET    /api/remote-sessions/{session_id}
GET    /api/remote-sessions/{session_id}/stream
POST   /api/remote-sessions/{session_id}/close
```
