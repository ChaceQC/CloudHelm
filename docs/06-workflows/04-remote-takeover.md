# 远程人工接管流程

> 来源：[设计书 10 章](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：定义端到端业务流程、参与模块和关键产物。
## 实现检查点

- 入口 API 是否存在。
- Orchestrator 状态迁移是否完整。
- Agent 输出是否结构化保存。
- Tool Gateway 是否记录工具调用和审批。
- 控制台是否能展示实时状态、产物和错误。

## 设计书摘录

### 10.5 远程人工接管流程

远程人工接管属于 M8 之后的增强能力，用于 Agent 无法确定原因、审批人希望手动
检查远端业务项目时。

## M7 边界

M7 不创建 `remote_session`，不建立 WebSocket terminal，也不接受任意 shell
命令。控制台只允许读取 Remote Agent 上报的服务 status、受限直读 logs，并
触发服务端预定义、只读、可审计的 diagnostics profile。

## 增强版参考流程

以下流程只用于后续增强版设计，不是 M7 API、控制台或验收范围：

```text
1. 用户在控制台点击 Takeover。
2. Control Plane 创建 remote_session。
3. Tool Gateway 校验用户权限、目标环境、操作等级。
4. Remote Control Plane 建立 WebSocket terminal。
5. 用户只能进入指定 project / environment 的受控工作目录。
6. 所有命令输入、输出、开始时间、结束时间写入 audit log。
7. 接管结束后生成 takeover summary。
8. 若用户手动修复，需要把操作转化为 runbook 或修复 PR，避免只停留在临时状态。
```

增强版仍须通过 Tool Gateway、Policy、Approval 与完整审计，不得复用 M7
diagnostics 接口承载交互式命令。

---
