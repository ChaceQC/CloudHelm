# 桌面端关键交互

> 来源：[设计书 13.2](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：定义需求输入、方案审批、实时跟踪、工具记录、本地接管与远端运维边界。
## 交互验收

- 能输入自然语言需求、Issue、截图、接口草稿、约束和验收标准。
- 能审查 Requirement Spec、ADR、OpenAPI、DB schema 和风险点。
- 能实时查看 Agent Timeline、Tool Calls、测试报告、扫描报告和 PR 链接。
- L3/L4 操作必须弹出审批卡片。

## M3 落地状态

- 需求输入表单当前调用真实 `POST /api/tasks` 创建 Task，暂不自动生成 Requirement Spec 或 Technical Design。
- Requirement / Design 面板读取真实后端记录；没有记录时展示真实空状态，不展示示例假数据。
- Timeline 面板读取 `GET /api/tasks/{task_id}/timeline`，并连接 M2 SSE 端点；因 SSE 每次只回放已有事件和 heartbeat，控制台固定退避重连、按 event id 去重，并在新事件或操作后同步读取详情和 Task Board。
- Tool Calls 与 Approval Panel 读取真实记录；审批按钮调用真实 approve / reject API，但 L3/L4 操作恢复执行仍留到 Tool Gateway 阶段。

## M4 落地状态

- 启动编排：在 Task Detail 点击“启动编排”，任务从 `Created` 进入 `RequirementClarifying`。
- 推进 Requirement：点击“推进一步”，Requirement Agent 生成真实 `requirement_specs` 并进入 `Designing`。
- 推进 Architect：点击“推进一步”，Architect Agent 生成真实 `technical_designs`；低风险自动进入 `Planning`，L2 及以上进入 `WaitingDesignApproval` 并展示审批。
- 恢复 Planning：通过 Design Review 或 Approval Panel 审批后，再次点击“推进一步”进入 `Planning`。
- 推进 Planner：点击“推进一步”，Planner Agent 生成真实 `development_plans` 并创建开发计划审查审批。
- 异常路径：缺少外部模型配置、非法状态或结构化输出失败时，控制台展示后端统一错误和 `trace_id`，不展示假结果。
- 外部模型瞬时请求或结构化响应错误会先执行有界重试；耗尽后 Task 暂停在原业务阶段，用户可修复配置或网络后恢复。

## M5 落地状态

- Tool Calls 面板展示 M5 新增字段：`audit_json`、`idempotency_key`、`duration_ms`、`result_summary`、`stdout_summary`、`stderr_summary`、`error_code` 和 `approval_id`。
- L3 工具调用通过 Platform API 写入 `approval_requests` 后，控制台可在 Approval Panel 中看到真实待审批记录；审批通过不自动执行远端动作。
- 无 ToolCall 记录时保持真实空态，不构造假命令、假 diff 或假测试输出。
- 切换 Project 时立即清空旧 Task Detail；异步 Project/Task 请求只接受最后一次响应。
- 历史 Requirement/TechnicalDesign 显示“历史版本”，批准/要求修改按钮按最新版和 review 状态禁用。

## M6 落地状态

- Task Detail 新增“M6 Code · Test · Review · PR”本地开发控制区。只有最新一版 Development Plan 已审批、Task 状态和后端 `next_action` 允许、且没有运行中的 AgentRun 时，才启用“启动本地开发”或“推进下一步”。
- “启动本地开发”调用 `POST /api/tasks/{task_id}/local-development/start`；后续统一调用 `POST /api/tasks/{task_id}/local-development/run-next`，按照 `run_scaffold`、`run_coder`、`run_tester`、`run_reviewer`、`run_security`、`finalize_local_pull_request` 逐次推进。页面不接受任意 workspace、文件路径或命令输入，具体工具参数、幂等和风险门禁由 Platform API 与 Tool Gateway 决定。
- Development Evidence 读取真实 `local-development` 状态、Artifact 列表与详情以及 Pull Request Record，不在生产界面构造静态 diff、测试结果、Review 结论、安全发现项或 Git 信息。单个 Artifact 详情读取失败时保留其他已成功证据，并显示局部告警。
- 已形成 Pull Request Record 时，Diff、TestReport、ReviewReport 和 SecurityReport 优先使用该 Record 固化的四类 Artifact ID，避免重试后把不同轮次证据错误拼接；Record 尚未形成时才回退到闭环状态引用或同类型最新 Artifact。
- Diff Viewer 展示 changed files、diff stat 和 unified patch。源码只作为文本预览呈现，不解释为 HTML；服务端返回截断预览时明确显示 `bytes_returned`，长源码行只允许在 diff 容器内部横向滚动。
- Test Report 展示测试命令、exit code、通过/失败/跳过计数、stdout、stderr 和失败原因；Review Report 展示 Acceptance Criteria 映射、Review issues、证据引用和是否进入安全检查；Security Report 展示扫描器命令、findings、剩余风险以及是否阻断 PR。
- Pull Request Record 展示 provider、状态、base/head branch、commit、base commit、changed files 和 diff stat。M6 使用本地 Git 等价记录时，`provider=local` 且 `url=null` 必须显示“本地等价 PR 记录 · 无远端链接”，不得伪造远端 PR URL；未来存在远端 URL 时只允许打开通过 HTTP(S) 协议校验的链接。
- EventSource 显式监听 `LocalDevelopmentStarted`、`ScaffoldCompleted`、`CodePatchGenerated`、`TestRunStarted`、`TestRunPassed`、`TestRunFailed`、`ReviewCompleted`、`SecurityScanCompleted`、`SecurityScanBlocked`、`ArtifactCreated`、`BranchCreated`、`CommitCreated` 和 `PullRequestRecordCreated`。收到任一事件后自动刷新 Task Detail、左侧 Task Board 和 Development Evidence。
- M6 证据请求沿用“最后发起的请求才允许更新状态”的并发保护；SSE 高频刷新时保留当前已展示数据，避免整块内容闪烁，操作成功后也会主动刷新证据和任务状态。
- 响应式边界保持 Gemini 式浅色阅读流：`980px` 以下证据卡片改为单列；`680px` 以下压缩卡片间距、命令输出改为单列、diff 保持局部滚动；`430px` 以下操作按钮、指标和元数据改为移动端布局。1280、1024 和 375 像素目标视口均要求 document 不产生水平溢出。

## M7 规划交互边界

M7 控制台尚未实现；落地时必须严格展示服务端真实证据，并按以下顺序推进：

1. 展示最新版 PullRequestRecord、完整 commit、RepositoryBinding、Environment
   和 active RemoteTarget，用户发起 release candidate approval。
2. 第一道审批卡片必须展示 PR record、commit、candidate ref 与 request hash；
   审批前 UI 不得显示已 push 或已触发 CI。
3. 审批通过后展示受控 ref 校验和唯一 `workflow_dispatch` 对应的 CIRun、job、
   manifest、测试/安全结果与不可变 OCI digest。
4. Release / Deploy Agent 生成 ReleasePlan 后，第二道 deployment approval
   必须展示精确 digest、Environment、RemoteTarget、计划摘要和
   `release_plan_sha256`。
5. 第二道审批通过并显式推进后，展示 Deployment Controller 与 Remote Agent
   operation、Compose 步骤、digest 复核、健康检查和最终 DeploymentResult。
6. M7 Remote Ops 只展示服务 status、受时间/行数/字节限制且脱敏的直读 logs，
   以及固定只读 diagnostics；页面不提供 remote session、WebSocket terminal、
   restart、metrics 或集中日志检索入口。

Prometheus/Loki/Alertmanager、metrics、集中日志、告警和 runbook proposal 属于
M8；交互式远程接管属于 M8 之后的增强版。

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
9. 用户可以 Takeover；sandbox shell 用于本地开发接管，远程受控 shell 仅属于
   M8 之后的增强版。M7 远端只提供固定 diagnostics，不创建交互式会话。
10. 完成后展示：
   - 需求符合度。
   - PR 链接。
   - diff。
   - 测试结果。
   - 安全扫描结果。
   - Agent 总结。

---
