# Release / Deploy Agent

> 来源：[设计书 8.1](../../../云舵 CloudHelm 毕设设计书.md)

## 职责

生成远端业务项目 release plan，在审批通过后执行 staging / demo 远端部署，检查发布健康状态，并生成 canary / rollback 建议。

## 允许工具

`ci status、deploy plan、deploy staging、release status；实际部署需审批`

## 主要输出

release_plan、deployment_result、release_status、rollback_plan、deployment_risk。

## 风险边界

L3/L4 部署或回滚必须审批；审批通过后由本 Agent 经 Tool Gateway 调用 Deploy Tool / Deployment Controller / Remote Agent 执行，而不是由 CI 直接改远端环境。

## 与其他 Agent 的协作

- 输入来自上一阶段的结构化产物或平台事件。
- 输出必须被 Orchestrator 持久化，并可在控制台查看。
- 需要人工确认的结果必须生成 ApprovalRequest，而不是隐式继续执行。

## 验收点

1. 能生成结构化结果。
2. 能在失败时给出可恢复原因。
3. 工具调用符合角色权限。
4. 关键结果能进入 EventLog / Artifact / Spec Store。
