# 开发者指导 Agents 完成功能开发到 PR 流程

> 来源：[设计书 10 章](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：定义端到端业务流程、参与模块和关键产物。
## 实现检查点

- 入口 API 是否存在。
- Orchestrator 状态迁移是否完整。
- Agent 输出是否结构化保存。
- Tool Gateway 是否记录工具调用和审批。
- 控制台是否能展示实时状态、产物和错误。

## M6 本地等价 PR 实现

当前 `0.5.0` 的可执行范围是受控 sample repo：

```text
已审批 DevelopmentPlan
  -> start: Planning -> Scaffolding
  -> Scaffold 建立 Task 独立 workspace 与 baseline commit
  -> Coder 经 Tool Gateway 写文件并生成真实 diff
  -> Tester 运行真实 pytest/JUnit
  -> Reviewer 映射全部 Acceptance Criteria
  -> Security 运行 Bandit/pip-audit
  -> Git Tool 创建 branch、显式文件 commit 和 format patch
  -> 保存 Artifact 与 provider=local、url=null 的 PR record
  -> PullRequestCreated
```

控制台调用：

```text
GET  /api/tasks/{task_id}/local-development
POST /api/tasks/{task_id}/local-development/start
POST /api/tasks/{task_id}/local-development/run-next
```

每次 `run-next` 只推进一个阶段。所有步骤保存 AgentRun、ToolCall、Artifact、
Task phase 和 EventLog；diff、测试、review、安全和 PR record 必须引用同一个
`evidence_set_id`、已审批 DevelopmentPlan 与 execution recipe hash。

当前 `PullRequestCreated` 是本地 branch、commit、format patch 与等价 PR
record 已形成，不表示远端 push、真实 GitHub/Gitea PR、合并或部署完成。M7
从这个可审计边界继续执行 CI/CD 与远端 staging/demo 闭环。

失败恢复：

- Provider、CLI、文件系统或报告解析等基础设施错误记录失败 AgentRun 并暂停
  Task，phase 保持可重试。
- pytest 失败、Review 要求修改或 Security 阻断保存真实报告并回到
  `Implementing`。
- 相同 step/attempt/call/参数、Artifact 和 commit 使用幂等记录；数据库晚期
  失败后的重试不重复写文件、commit 或 PR record。

## 设计书摘录

### 10.1 开发者指导 Agents 完成功能开发到 PR 流程

```mermaid
sequenceDiagram
    participant U as Developer
    participant C as Control Console
    participant API as Platform API
    participant O as Orchestrator
    participant A as Agent Runtime
    participant T as Tool Gateway
    participant Spec as Spec Store
    participant S as Docker Sandbox
    participant G as Gitea/GitHub

    U->>C: 输入功能目标 / 需求文档 / 约束 / 验收标准
    C->>API: POST /tasks
    API->>O: start workflow
    O->>A: Requirement Agent 解析需求
    A->>T: requirement.parse / update_spec
    T->>Spec: 保存 requirement_spec / acceptance_criteria
    O->>A: Architect Agent 生成技术方案
    A->>T: design.generate_api_design / generate_db_design
    T->>Spec: 保存 ADR / OpenAPI / DB schema
    API->>C: 推送方案审查事件
    U->>C: 审批方案 / 补充约束 / 要求修改
    O->>A: Planner Agent 拆分开发任务
    A->>T: repo.search_code / scaffold.generate_module
    T->>S: 准备 worktree / 项目骨架
    O->>A: Coder Agent 实现功能
    A->>T: repo.write_file / sandbox.exec / openapi.generate
    T->>S: 生成代码、迁移、测试并运行
    A->>T: git.diff
    T->>S: 生成 diff
    O->>A: Tester Agent 验证验收标准
    A->>T: sandbox.run_tests / browser.run_e2e_test
    T->>S: 生成测试报告 / 截图
    O->>A: Reviewer Agent 审查需求符合度和代码质量
    A->>T: security.semgrep_scan
    T->>S: 安全扫描
    O->>T: git.commit / create_pr
    T->>G: 创建 branch / commit / PR
    API->>C: 推送任务完成事件
    C->>U: 展示 PR、diff、测试报告、验收结果
```

此流程覆盖的任务不只包括修复 bug，还包括：

```text
1. 从 0 创建一个新项目。
2. 为已有项目实现新功能。
3. 设计并实现 REST API。
4. 设计数据库 schema 和迁移脚本。
5. 开发前端页面和组件。
6. 集成第三方服务。
7. 重构已有模块。
8. 补充测试、文档和示例。
9. 修复 bug 或处理 CI 失败。
```
