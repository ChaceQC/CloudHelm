# Agent 指导开发技术栈

> 来源：[设计书 5.1.1](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：说明从需求到 PR 的规格化、设计、脚手架、实现和验收工具链。
## 产物链

`requirement_spec -> technical_design -> development_plan -> patch/diff -> test_report -> PR`。

## 设计书摘录

### 5.1.1 Agent 指导开发技术选型

为了体现“开发者指导 Agents 进行软件开发”，本地开发链路需要额外引入规格化、设计、脚手架和验收能力。

|阶段|主要技术|产物|说明|
|---|---|---|---|
|需求输入|Markdown / Issue / 表单 / 附件解析|`requirement_spec`|开发者描述目标，Requirement Agent 提取用户故事、约束和验收标准|
|需求澄清|LLM structured output + Pydantic|`clarification_questions` / `acceptance_criteria`|当需求不完整时，Agent 生成澄清问题；需求明确后生成验收标准|
|方案设计|ADR + Mermaid + OpenAPI + DB schema|`technical_design`|Architect Agent 输出模块、接口、数据表、状态机和风险点|
|任务拆分|LangGraph state + JSON task graph|`development_plan`|Planner Agent 把功能拆成可执行 steps，并分配给 Coder / Tester / Reviewer|
|项目生成|Cookiecutter / Backstage Templates / Yeoman|项目骨架、目录、配置文件|支持从 0 创建服务、前端项目、全栈模板或 worker|
|代码实现|Repo Tool + Sandbox Tool + LLM code edit|patch / diff|Coder Agent 在本地 worktree 中完成实现，不直接改远端|
|接口与类型|OpenAPI Generator / TypeScript types|client SDK / server stub|保证前后端接口契约一致|
|数据库变更|Alembic / Prisma Migrate|migration file|数据库 schema 变更必须可审查，可回滚|
|测试验收|pytest / vitest / Playwright / Storybook|test report / screenshot|Tester Agent 自动生成和运行单元测试、集成测试、E2E 测试|
|远端发布|Release / Deploy Agent + Deploy Tool + Deployment Controller + Remote Agent|deployment / release status|CI 只提供构建产物，Release / Deploy Agent 在审批后执行部署、健康检查和状态回传|
|人工指导|Control Console approval / comment|approval record / redirect event|开发者可以审批方案、要求重做、补充约束、对 diff 提意见|
