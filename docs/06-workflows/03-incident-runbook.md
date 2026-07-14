# 远端业务项目告警分析与 Runbook 建议流程

> 来源：[设计书 10 章](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：定义端到端业务流程、参与模块和关键产物。
## 实现检查点

- 入口 API 是否存在。
- Orchestrator 状态迁移是否完整。
- Agent 输出是否结构化保存。
- Tool Gateway 是否记录工具调用和审批。
- 控制台是否能展示实时状态、产物和错误。

## 设计书摘录

### 10.4 远端业务项目告警分析与 Runbook 建议流程

本流程属于 M8 远端监控、告警与 SRE 分析阶段，不属于 M7。M7 只提供服务
status、受限直读 logs 和固定只读 diagnostics，不接入 Prometheus、Loki、
Alertmanager，不提供 metrics 查询，也不执行服务重启。M8 默认先对远端业务
项目进行分析和生成 runbook proposal；任何产生远端副作用的动作仍须经过
Tool Gateway、风险策略和独立人工审批。

```text
1. Prometheus / Alertmanager / Loki / Sentry 告警进入系统。
2. 告警被绑定到 project_id + environment_id + service_id。
3. SRE Agent 查询该远端业务项目的指标、日志、最近部署记录和 release diff。
4. Agent 判断可能原因：
   - 代码 bug
   - 容量不足
   - 下游依赖异常
   - 数据库慢查询
   - 最近发布引入问题
   - 配置错误
   - 容器重启循环
5. 生成 incident analysis：
   - 影响服务
   - 影响环境
   - 首次发生时间
   - 当前错误率 / 延迟 / 可用性
   - 关联部署版本
   - 可疑 commit / PR
6. 若是代码问题，转为 issue_to_pr 流程。
7. 若是运维操作，生成 runbook proposal：
   - 重启远端业务服务
   - 回滚到上一版本
   - 临时关闭 feature flag
   - 扩容副本数
   - 清理业务缓存
8. Tool Gateway 根据风险等级创建人工审批；生成 proposal 不等于执行动作。
9. 审批通过并显式推进后执行允许的固定动作，再继续监控恢复情况。
```

交互式 remote session、WebSocket terminal 和任意 shell 不属于 M8 默认闭环，
仅作为后续增强版规划。
