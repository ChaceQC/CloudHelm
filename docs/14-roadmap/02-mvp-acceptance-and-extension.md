# MVP 验收标准与后续扩展

> 来源：[设计书 22-23 章](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：定义 MVP 完成标准和可扩展方向。
## 验收方式

MVP 验收应逐条对应演示脚本和测试用例，避免只展示静态页面而没有真实闭环。

## 设计书摘录

## 22. 最小可行版本验收标准

MVP 完成标准：

1. 能在控制台创建功能开发任务。
2. 能看到任务状态实时变化。
3. Requirement Agent 能生成需求规格和验收标准。
4. Architect Agent 能生成技术设计、OpenAPI 草案和数据库 schema。
5. 开发者能审批或要求修改需求 / 技术方案。
6. Agent 能读取和修改示例仓库。
7. Agent 能在 sandbox 中执行测试命令。
8. 系统能生成 diff。
9. 系统能创建 branch 和 commit。
10. 系统能创建 PR 或生成等价 PR 记录。
11. Reviewer Agent 能给出需求符合度和代码审查结论。
12. 工具调用记录可在控制台查看。
13. L3 以上操作会进入审批流程。
14. Release / Deploy Agent 能把示例业务项目部署到远端 staging / demo 环境。
15. Remote Agent 能回传远端业务项目心跳和服务状态。
16. 控制台能查看远端业务项目日志。
17. Prometheus 能采集远端业务项目或其主机 / 容器指标。
18. Loki 能查询远端业务项目日志。
19. 远端业务项目异常能触发告警或 incident。
20. SRE Agent 能基于远端日志、指标和部署记录给出分析结论。
21. 全流程事件写入 event_logs。

---

## 23. 后续扩展方向

1. 接入 Kubernetes 和 Argo CD，实现远端业务项目 GitOps 部署。
2. 接入 Sentry / OpenTelemetry Trace，实现告警驱动修复和 release 关联分析。
3. 接入 OpenBao，实现动态密钥与临时 token。
4. 接入 OPA，实现更严格的策略控制。
5. 支持多项目、多仓库、多 Agent 并行。
6. 支持自动生成 incident report 和 postmortem。
7. 支持根据历史任务进行 Agent 学习和 prompt 优化。
8. 支持浏览器 Agent 进行 UI 自动化测试。
9. 支持成本预算和资源配额控制。
10. 支持插件化工具市场。
11. 支持 preview environment，为每个 PR 自动部署独立预览环境。
12. 支持多云部署目标，例如阿里云、腾讯云、AWS、Azure。

---
