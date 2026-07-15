# 核心原则

> 来源：[设计书 6.4](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：定义所有模块都必须遵守的安全、审计和工作流原则。
## 实现约束

- Agent 不直接访问外部系统，必须经过 Tool Gateway。
- 高风险工具必须审批，所有远程控制必须审计。
- 本地开发与 Agent 远程部署分离，远端只接受 Git / CI 验证后的产物，并由 Release / Deploy Agent 通过 Tool Gateway 和受控部署工具执行上线。
- “Sandbox”是安全边界而不是已固定的框架名：M6 以 allowlist 本地目录、
  命令 profile、环境白名单、超时和进程树清理实现最小受控执行；Docker
  CPU/内存/PID/网络隔离属于后续增强。
- Desktop 是客户端，Ops Hub 是权威常在线控制面；客户端退出不得成为远端
  工作流停机条件。
- PostgreSQL 属于 Ops Hub，SQLite 属于 Desktop 非权威本地 store，业务项目数据
  由项目自身拥有，三者不得混用。
- CloudHelm 对业务项目的兼容要求通过版本化契约和标准协议实现，不允许形成
  CloudHelm SDK/数据库/控制台运行时锁定。

## 设计书摘录

### 6.4 核心原则

1. **Agent 不直接调用外部系统**：必须经过 Tool Gateway。
2. **实现者不能自己批准上线**：Coder Agent 与 Reviewer / Release / Human Approval 分离。
3. **所有修改走 Git 工作流**：branch、commit、PR、review、merge。
4. **命令执行在受控执行区完成**：M6 只能操作服务端绑定的 Task workspace，
   禁止访问任意宿主路径或生产环境；后续升级为 Docker sandbox。
5. **高风险工具必须审批**：数据库写操作、部署、回滚、删除、生产变更必须人工确认。
6. **事件溯源**：所有任务状态变化、工具调用、审批操作都写入事件表。
7. **开发者指导与 Agent 实现分离**：开发者主要负责目标、约束、验收和审批；Agents 负责在本地隔离工作区中生成方案、实现代码、运行测试和提交 PR。
8. **本地 Agent 开发与 Agent 远程部署分离**：代码生成、修改和测试优先在
   本地受控 workspace/sandbox 完成；远程环境只接受经过 Git / CI 验证的产物，
   并由 Release / Deploy Agent 通过 Tool Gateway 和受控部署工具执行上线。
9. **远程控制必须可审计**：针对远端业务项目的远程命令、日志拉取、重启、扩容、回滚都必须记录操作者、参数、输出和审批链。
10. **Desktop 与常驻控制面分离**：Windows/Linux App 只负责交互、缓存和本地
    sidecar；权威状态与远端 Agents 运维系统运行在 Linux Ops Hub。
11. **服务端持久化后独立推进**：用户命令或审批一旦在 Ops Hub 事务内落库，
    后续不需要新人工决策的步骤由 Workflow Engine 继续，不能依赖 App
    `run-next` 保持在线。
12. **项目必须可剥离交付**：Agent 生成项目必须具备独立源码、依赖、配置、
    migration、测试、Dockerfile/Compose 和 README；移除 CloudHelm adapter 后
    仍能运行。
13. **运维层与业务层生命周期分离**：Ops Hub、Remote Agent、观测组件和业务
    项目使用独立网络、数据卷、凭据、升级和卸载流程。

---
