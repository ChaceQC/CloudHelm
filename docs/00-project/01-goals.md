# 设计目标

> 来源：[设计书 3 章](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：沉淀功能目标、非功能目标与 MVP 约束。
## 落地原则

- 功能目标用于拆分产品需求和验收用例。
- 非功能目标用于约束安全、可观测性、可恢复性、远程可控性和可演示性。
- 开发任务、测试任务、部署任务、运维任务都应能回溯到本页目标。

## 设计书摘录

## 3. 设计目标

### 3.1 功能目标

1. 支持开发者通过自然语言、需求文档、Issue、截图或接口说明指导 Agents 进行软件开发，而不是要求开发者直接编码。
2. 支持完整开发类任务，而不局限于修复类任务：
   - 从 0 创建项目骨架。
   - 实现新功能。
   - 修改已有功能。
   - 设计 API。
   - 设计数据库表和迁移脚本。
   - 开发前端页面。
   - 开发后端接口。
   - 集成第三方服务。
   - 重构模块。
   - 生成测试用例。
   - 生成技术文档。
   - 修复 bug。
   - 处理 CI 失败。
   - 分析远端业务项目告警。
3. 支持开发者对 Agent 开发过程进行持续指导：
   - 补充需求。
   - 修改验收标准。
   - 约束技术栈。
   - 指定代码风格。
   - 要求重做方案。
   - 审批或拒绝架构方案。
   - 对 diff 提出修改意见。
   - 在必要时人工接管。
4. 支持多 Agent 分工协作：
   - Requirement Agent：澄清需求、提取验收标准、生成任务说明。
   - Planner Agent：任务拆解、迭代计划和风险评估。
   - Architect Agent：模块划分、接口设计、数据模型设计和技术方案评审。
   - Coder Agent：根据需求和方案进行代码实现。
   - Tester Agent：生成测试、运行测试、分析失败原因。
   - Reviewer Agent：代码审查、需求符合度检查、可维护性检查。
   - Security Agent：安全扫描与风险提示。
   - Release / Deploy Agent：生成发布计划、执行经两道审批的远端部署、检查发布健康状态并生成回滚候选方案。
   - SRE Agent：分析远端已部署业务项目的运行问题。
5. 支持 Agent 调用工具，而不是只输出文本。
6. 所有工具调用必须经过统一 Tool Gateway。
7. 支持 Docker Sandbox 隔离执行命令和修改代码。
8. 支持 Git 分支、commit、diff、PR 工作流；M7 进一步把精确 commit 绑定到
   release candidate，并只通过固定 Gitea workflow 的 `workflow_dispatch`
   触发 CI。
9. 支持远程部署目标管理；M7 只管理 Linux staging / demo Environment 和
   RemoteTarget，production、Kubernetes 集群和 GitOps 目标属于后续扩展。
10. 支持远程服务状态、受限日志、部署状态和固定 diagnostics 查询；M7 默认通过
    Remote Agent，SSH 只执行单独审批的固定只读诊断，不提供任意远程命令或交互
    终端。
11. 支持实时监控运维，包括指标、日志、告警、发布状态、错误率、延迟和资源使用率。
12. 支持人类审批、暂停、接管、拒绝和回滚请求；M7 明确区分 release candidate
    approval 与 deployment approval，审批记录本身不直接执行副作用。
13. 支持事件日志、审计日志、Agent 运行轨迹和成本统计。
14. 支持桌面端控制台，体验参考 Codex App：
   - 项目 / 任务线程。
   - 本地开发内嵌终端；交互式远程终端属于增强版。
   - diff 查看。
   - 测试报告。
   - 远程环境状态。
   - 实时监控面板。
   - 工具调用记录。
   - 审批按钮。

### 3.2 非功能目标

1. **安全性**：Agent 默认无生产权限，高风险操作必须审批。
2. **可观测性**：记录每次 Agent 决策、工具调用、命令输出和测试结果。
3. **可恢复性**：任务状态可持久化，失败后可重试或人工接管。
4. **远程可控性**：远程部署和运维动作必须可追踪、可中断、可审批、可回放。
5. **云端适配性**：M7 先适配单台 Linux staging / demo 主机，后续再扩展到
   production、Kubernetes / GitOps。
6. **可扩展性**：工具通过 MCP / Tool Server 扩展。
7. **可替换性**：模型通过 LiteLLM 接入，支持 OpenAI、Claude、本地模型等。
8. **可演示性**：毕设答辩时可以完整演示“开发者指导 Agents 实现功能 -> 本地
   sandbox 验证 -> PR -> release candidate 审批 -> `workflow_dispatch` CI ->
   不可变 OCI 制品 -> deployment 审批 -> Remote Agent 执行 Linux staging /
   demo 部署 -> 实时监控 -> 运维反馈”的闭环。

---
