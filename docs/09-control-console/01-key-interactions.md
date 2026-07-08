# 桌面端关键交互

> 来源：[设计书 13.2](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：定义需求输入、方案审批、实时跟踪、工具记录、接管和完成展示。
## 交互验收

- 能输入自然语言需求、Issue、截图、接口草稿、约束和验收标准。
- 能审查 Requirement Spec、ADR、OpenAPI、DB schema 和风险点。
- 能实时查看 Agent Timeline、Tool Calls、测试报告、扫描报告和 PR 链接。
- L3/L4 操作必须弹出审批卡片。

## M3 落地状态

- 需求输入表单当前调用真实 `POST /api/tasks` 创建 Task，暂不自动生成 Requirement Spec 或 Technical Design。
- Requirement / Design 面板读取真实后端记录；没有记录时展示真实空状态，不展示示例假数据。
- Timeline 面板读取 `GET /api/tasks/{task_id}/timeline`，并优先连接 M2 SSE 端点；因 M2 SSE 只回放已有事件和 heartbeat，界面在事件或操作后重新读取 Timeline。
- Tool Calls 与 Approval Panel 读取真实记录；审批按钮调用真实 approve / reject API，但 L3/L4 操作恢复执行仍留到 Tool Gateway 阶段。

## 设计书摘录

### 13.2 关键交互

1. 开发者创建任务时，可以输入自然语言需求、Issue 链接、截图、接口草稿、技术约束和验收标准。
2. Requirement Agent 生成需求规格后，控制台允许开发者确认、补充、修改或要求重新澄清。
3. Architect Agent 生成技术方案后，控制台展示 ADR、OpenAPI、数据库 schema、模块划分和风险点。
4. 开发者可以在 Design Review Panel 中审批方案、提出修改意见或锁定某些文件 / 技术栈。
5. Coder / Tester / Reviewer Agents 执行过程中，桌面端展示实时 Agent Timeline。
6. Agent 每次调用工具，控制台显示：
   - 工具名称。
   - 参数摘要。
   - 风险等级。
   - 执行状态。
   - 输出摘要。
7. 如果遇到 L3 / L4 操作，控制台弹出审批卡片。
8. 用户可以随时 Pause。
9. 用户可以 Takeover，打开 sandbox shell 或远程受控 shell 接管操作。
10. 完成后展示：
   - 需求符合度。
   - PR 链接。
   - diff。
   - 测试结果。
   - 安全扫描结果。
   - Agent 总结。

---
