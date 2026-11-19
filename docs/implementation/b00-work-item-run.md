# B00 工作项与 Run 交接

B00 在既有启动命令和已确认 Operation 的等待续接处固定工作项。权威入口为 [D01 §3–4](../design/01-domain-collaboration.md#3-工作项与分类依赖)。[定向验证记录](../acceptance/b00.md)说明实际覆盖范围。

| 读取目标 | 权威来源和绑定 |
|---|---|
| 当前工作项 | `work_items` 的 Task、工作项 ID、修订、分配与目标；`run_requirements_json` 声明前置引用和是否必须具备正式预览支持。未声明时无此类启动门槛。 |
| 本轮输入 | [ContextPackage](../../packages/contracts/p2/runtime.py) 保存需求、验收修订和当前 Task InputSet；[WorkItemRunSpec](../../packages/contracts/p2/work_item_run.py) 补充目标、验收方法与检查、精确依赖，以及工作区、基线、写入代次和最近已确认交还。开发范围为该工作区根目录，执行器仍管路径与实际写入权限。 |
| 依赖的满足证据 | 契约、候选或制品、集成输入、环境分别固定准确主体和证据。协作域要求同项目、同 Task InputSet、主体相符且已通过的 `work_item_dependency` 证明，来源必须是已启用的集成产品来源。环境还须对应本 Task 当前就绪的受控预览及未过期的活跃资源租约。 |
| 有界推进与等待 | `RuntimeInput` 保存控制、输入有效性和 Session 版本；`RunPolicy` 保存单轮额度。Run 及 WorkflowBinding 和工作流入队共同提交。等待续接通过 `agent_operation_waits` 保存原 Run、工具调用、Operation 与新 Run 的关联。 |
| 启动前的能力 | `TaskAgentApplication.capabilities` 提供内部 [WorkItemCapabilities](../../packages/contracts/p2/work_item_capabilities.py)，含工作项/授权修订、依赖声明及受管源码、参照构建、正式预览、人测的可用性、原因、证据或策略引用和门槛阶段。登记支持不能证明某次实际环境就绪，也不授予权限。 |

工作项依赖与 Task 初始工程 InputSet 分别维护。Context 的内容摘要同时绑定原 InputSet 和前置引用；候选、构建、验证报告仍各自按原输入记录核对，保持 [A02 的固定候选读链](../acceptance/a02e.md)。B00 接受已固定的上游证明；创建依赖图、按契约变化传播失效及跨开发会话解锁由 E01 承接。

C01 从新开发 Run 的 `work_item_spec` 和已有绑定取读依据，再处理 Git 和上下文正文。C02 可从领域记录直接读取上述规格、现有 `policy.instruction_revision`、`context.tool_names`、等待引用和可用能力，无需展开 SDK 历史。B00 保持原 Hub HTTP 和 DBOS 调用参数；记名工具、写入代次在新工具上的执行门禁、公开摘要与 Desktop 接线按后续工作包开放。
