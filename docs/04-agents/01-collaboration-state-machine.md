# Agent 协作状态机

> 来源：[设计书 8.2](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：定义任务从创建到完成的状态迁移。
## 状态机实现要求

- 每次状态迁移必须写入 `event_logs`。
- 等待审批、测试失败、安全失败、远端告警都必须有可恢复路径。
- `Done` 只表示当前任务健康完成，不表示项目生命周期结束。

## M4 落地状态

M4 已在 `modules/orchestrator` 中实现显式状态机，并由 Platform API service 在同一事务中写入 Task、AgentRun、业务产物和 EventLog。

M4 覆盖的状态：

```text
Created -> RequirementClarifying -> Designing -> WaitingDesignApproval -> Planning
Designing -> Planning
```

API 入口：

- `POST /api/tasks/{task_id}/start`：从 `Created` 进入 `RequirementClarifying`。
- `POST /api/tasks/{task_id}/run-next`：按当前阶段推进一个最小 Agent 步骤。
- `GET /api/tasks/{task_id}/orchestration`：返回下一步动作、设计审批状态和计划是否存在。

失败规则：缺少外部模型配置、结构化输出校验失败或非法状态迁移时，必须写入 `AgentRunFailed` 或稳定错误响应，任务不得伪装为完成。

## 设计书摘录

### 8.2 Agent 协作状态机

```mermaid
stateDiagram-v2
    [*] --> Created
    Created --> RequirementClarifying
    RequirementClarifying --> RequirementClarifying: developer adds constraints
    RequirementClarifying --> Designing: requirement accepted
    Designing --> WaitingDesignApproval: architecture / API / DB risk
    WaitingDesignApproval --> Designing: rejected / redirected
    WaitingDesignApproval --> Planning: approved
    Designing --> Planning: low risk
    Planning --> Scaffolding: new project / new module
    Planning --> Implementing: existing project
    Scaffolding --> Implementing
    Implementing --> Testing
    Testing --> Implementing: tests failed
    Testing --> Reviewing: tests passed
    Reviewing --> Implementing: review requested changes
    Reviewing --> SecurityScanning
    SecurityScanning --> Implementing: security failed
    SecurityScanning --> PullRequestCreated
    PullRequestCreated --> WaitingMergeApproval
    WaitingMergeApproval --> Deploying: approved
    WaitingMergeApproval --> Implementing: rejected
    Deploying --> Monitoring
    Monitoring --> Remediating: remote alert
    Remediating --> Implementing: code fix needed
    Remediating --> WaitingOpsApproval: runbook / rollback needed
    WaitingOpsApproval --> Monitoring: approved and executed
    Monitoring --> Done: healthy
    Done --> [*]
```
