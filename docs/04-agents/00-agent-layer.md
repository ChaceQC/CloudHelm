# Agent 分层总览

> 来源：[设计书 8.1](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：汇总所有 Agent 角色、职责和工具边界。
## 分工原则

- Requirement / Planner / Architect 负责需求和设计质量。
- Scaffold / Coder / Tester / Reviewer 负责本地开发闭环。
- Security / Release / Deploy / SRE 负责安全、Agent 化发布部署和远端业务运维闭环。

## M4 落地状态

M4 已新增 `modules/agent-runtime`，实现 Requirement、Architect、Planner 三类 Agent 的结构化输入输出和 provider 边界：

- Requirement Agent 读取真实 Task，输出 `requirement_specs` 所需的 `user_story`、`constraints_json` 和 `acceptance_criteria_json`。
- Architect Agent 读取最新 RequirementSpec，输出 `technical_designs` 所需的 ADR 正文、OpenAPI 草案、DB schema 草案、Mermaid 和风险等级。
- Planner Agent 读取已通过 TechnicalDesign，输出 `development_plans` 的任务图和风险说明。

M4 默认 provider 为 `local_structured`，它基于真实输入生成结构化草案并通过 Pydantic 校验；`openai_compatible` 仅在提供外部模型配置后启用，使用 HTTP SSE Responses API。当前真实流程透传兼容端点提供的 `gpt-5.6-sol` 与 `reasoning.effort=xhigh`，并发送 Codex User-Agent、thread/session headers、稳定 `prompt_cache_key` 和完整 ResponseItem 历史。瞬时请求和无效结构化响应执行有界指数退避，耗尽后记录失败 AgentRun 并暂停可恢复 Task。M4 不允许上述 Agent 绕过 Tool Gateway 调用 Repo、Sandbox、Git、Docker、SSH、部署或监控工具。

Requirement、Architect、Planner 不是三个独立模型会话，而是同一 Task root
conversation 的连续 turn。只有显式 `spawn_subagent` 才创建 child，并保存
parent、role、depth、fork mode 与生命周期；child 完成时只回传结构化通知，
不把隐藏 reasoning 或工具执行历史整段合并回 root。

当前 child 能力只实现内部 conversation 持久化、配额/权限/生命周期与摘要门禁；
生产编排尚未调用真实 child AgentRun/provider，也没有公开 spawn API、wait-all、
steer/queue、独立 thread UI 或 workspace/worktree scheduler。

## M6 落地状态

M6 在相同 Agent Runtime 和 Task root conversation 上新增五个普通角色：

- Scaffold Agent：只提出受控 fixture/workspace 请求，由 Tool Gateway 创建
  Task 独立 Git workspace 和 baseline commit。
- Coder Agent：根据已审批计划、execution recipe、当前文件和验收标准提出
  `repo.*`、`git.*` 工具调用，真实写入 sample workspace 并生成 diff。
- Tester Agent：通过 `test.run_pytest` 执行真实 pytest/JUnit，退出码、报告
  统计和输出必须一致，不能由模型声明通过。
- Reviewer Agent：使用同一 evidence set 的 diff、测试报告和全部 AC 映射生成
  review；未覆盖或要求修改时回到 `Implementing`。
- Security Agent：消费真实 Bandit 与 pip-audit 结果，区分 finding、工具不可用、
  解析失败和阻断结论。

五个角色与 Requirement、Architect、Planner 共享稳定
`cloudhelm_agent_output_v1` 传输 schema 和完整、排序稳定的工具声明；当前角色
最终输出仍必须通过专属 Pydantic model。角色切换不会隐式创建 conversation，
也不会通过删减工具清单改变 Prompt Cache 前缀。

M6 工具循环由 Platform API 执行：Provider 的 function/custom call 经角色
allowlist、Tool Gateway 和 Policy 校验后产生真实 ToolCall；对应 output 使用
同一 `call_id` 回到 conversation。一轮可有多个 call/output，但最终只提交一个
逻辑 turn。Agent 不能接收或覆盖服务端绑定的 workspace、recipe、分支和 Artifact
根目录。

## Instructions v3

Agent Runtime 将 Instructions 分为可审计的稳定层和 turn 层：

- `prompts/base.md`：整个 conversation 固定，完整定义指令优先级、prompt
  injection 可信边界、ResponseItem/reasoning、输出真实性、Tool Gateway、
  审批、风险、subagent 和完成判定。
- `prompts/requirement.md`、`architect.md`、`planner.md`、`scaffold.md`、
  `coder.md`、`tester.md`、`reviewer.md`、`security.md`：精确说明当前角色的
  唯一目标、每个输入字段的权威含义、处理顺序、每个输出字段的精度、工具
  allowlist、禁止项和完成判定。
- `<role_contract>`：机器可核对的 agent type、输出 contract、稳定传输 schema、
  conversation rule、工具列表和副作用策略。
- `<validation_repair>`：只在当前结构化修复请求出现，包含 Pydantic 错误、允许
  修复范围和禁止动作；不会改写 Base Instructions 或污染已提交历史。
- `<approval_context>`：只表达 action/status/actor/resource/version 的持久化
  事实，审批 reason 属于不可信业务数据，不能覆盖 Role/Tool Policy。
- `prompts/subagent.md` 与 `<subagent_contract>`：定义 child 的单一目标、
  fresh/full-history、权限不继承、父子隔离、终态和最终通知。

Responses `text.format` 使用扁平稳定 `cloudhelm_agent_output_v1` 作为跨角色
传输字段集合；它不是宽松业务契约。当前 turn 最终必须通过角色专属 Pydantic
model，不能输出其他角色字段或额外 envelope。

## 设计书摘录

### 8.1 Agent 角色

|Agent|职责|允许工具|
|---|---|---|
|Requirement Agent|解析开发者输入的目标、需求文档、Issue、截图或接口说明，提取用户故事、约束和验收标准|requirement.parse、spec.update、repo read|
|Planner Agent|理解开发目标、拆解步骤、评估风险、生成迭代计划和任务图|只读 repo、issue、spec、日志、指标|
|Architect Agent|设计模块边界、API、数据库 schema、状态机、目录结构和技术方案|design.generate、spec.update、repo read|
|Scaffold Agent|根据模板创建项目骨架、模块目录、配置文件、CI 文件和基础测试|scaffold.generate、repo write、sandbox exec|
|Coder Agent|根据需求和技术方案实现功能、修改代码、补测试、生成 patch|repo write、sandbox exec、git diff|
|Tester Agent|安装依赖、运行测试、分析失败原因|sandbox exec、ci logs、test report|
|Reviewer Agent|审查 diff、指出风险、判断是否满足需求|repo read、git diff、安全扫描结果|
|Security Agent|运行 Semgrep / Trivy / dependency audit|security scan、repo read|
|Release / Deploy Agent|生成远端业务项目的 release plan，审批通过后执行 staging / demo 部署，检查发布健康状态，并生成 canary / rollback 建议|ci status、deploy plan、deploy staging、release status；实际部署需审批|
|SRE Agent|分析远端业务项目的告警、日志、指标，建议 runbook|monitor read、logs search、低风险 runbook|
