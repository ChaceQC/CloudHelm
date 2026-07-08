# Agent 结构化输出契约

> 来源：[设计书 8.3](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：约束 Agent 关键步骤必须输出可校验对象。
## 实现要求

- 所有关键输出使用 Pydantic / JSON Schema 校验。
- 结构化对象必须保存到数据库或 spec-store，供后续 Agent 和控制台复用。
- 解析失败应进入重试或澄清状态，而不是继续执行危险操作。

## M4 落地状态

M4 已提供以下结构化输出契约：

- `packages/shared-contracts/schemas/agents/requirement-agent-output.schema.json`
- `packages/shared-contracts/schemas/agents/architect-agent-output.schema.json`
- `packages/shared-contracts/schemas/agents/planner-agent-output.schema.json`
- `packages/shared-contracts/schemas/agents/development-plan.schema.json`
- `packages/shared-contracts/schemas/agents/agent-run-output.schema.json`

后端对应 Pydantic model 位于 `modules/agent-runtime/src/cloudhelm_agent_runtime/schemas/`。Platform API 入库前会再次校验输出，并将通过校验的对象保存到 `agent_runs.structured_output_json` 与对应业务表。

## 设计书摘录

### 8.3 Agent 输出必须结构化

Agent 不允许只输出自然语言，关键步骤必须输出结构化对象。

示例：任务计划对象

```json
{
  "task_id": "task_001",
  "risk_level": "L1",
  "summary": "为示例项目实现用户注册、登录、个人资料页面和远端 staging 部署",
  "requirement_spec": {
    "user_story": "作为普通用户，我希望可以注册账号、登录系统并查看个人资料。",
    "acceptance_criteria": [
      "用户可以通过邮箱和密码注册",
      "注册后可以登录并获得访问令牌",
      "登录用户可以访问个人资料接口和页面",
      "单元测试、接口测试和基础 E2E 测试通过"
    ],
    "constraints": [
      "后端使用 FastAPI",
      "前端使用 React",
      "数据库迁移必须可回滚"
    ]
  },
  "steps": [
    {
      "name": "生成需求规格和验收标准",
      "agent": "requirement",
      "expected_artifact": "requirement_spec"
    },
    {
      "name": "设计 API、数据库表和模块结构",
      "agent": "architect",
      "expected_artifact": "technical_design"
    },
    {
      "name": "实现后端接口、前端页面和测试",
      "agent": "coder",
      "expected_artifact": "patch"
    },
    {
      "name": "运行单元测试、接口测试和 E2E 测试",
      "agent": "tester",
      "expected_artifact": "test_report"
    }
  ],
  "required_tools": [
    "requirement.parse",
    "design.generate_api_design",
    "design.generate_db_design",
    "repo.read_file",
    "repo.write_file",
    "sandbox.exec",
    "git.diff"
  ],
  "approval_required": false
}
```

---
