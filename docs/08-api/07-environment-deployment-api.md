# Environment / Deployment API

> 来源：[设计书 12 章](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：给出该 API 分组的端点清单和实现注意点。
## 实现注意点

- 请求和响应模型应写入 OpenAPI，并同步生成前端类型。
- 涉及任务状态、工具调用、审批和远端操作的接口必须写事件日志。
- 列表接口需要分页、过滤和按 project/environment/task 过滤。

## 设计书摘录

### 12.6 Environment / Deployment API

```text
POST   /api/projects/{project_id}/environments
GET    /api/projects/{project_id}/environments
GET    /api/environments/{environment_id}

POST   /api/environments/{environment_id}/remote-targets
GET    /api/environments/{environment_id}/remote-targets
POST   /api/remote-targets/{target_id}/test-connection

POST   /api/remote-agents/heartbeat
GET    /api/tasks/{task_id}/release-candidate
GET    /api/tasks/{task_id}/ci-runs
POST   /api/webhooks/ci/gitea
GET    /api/tasks/{task_id}/remote-deployment
POST   /api/tasks/{task_id}/remote-deployment/start
POST   /api/tasks/{task_id}/remote-deployment/run-next
GET    /api/projects/{project_id}/deployments
GET    /api/deployments/{deployment_id}
POST   /api/deployments/{deployment_id}/health-check
POST   /api/deployments/{deployment_id}/rollback-request
```

`remote-deployment/start` 只接受 `environment_id`；PullRequestRecord、完整 commit、
repository binding、RemoteTarget、CI manifest 和 OCI digest 均由服务端派生。
调用方不得提交任意 host、URL、workflow path、credential、image 或 Compose。
