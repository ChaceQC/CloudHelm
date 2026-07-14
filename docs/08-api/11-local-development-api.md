# M6 本地开发与 Artifact API

> 实现位置：`modules/platform-api/src/cloudhelm_platform_api/api/`
> 适用范围：受控 sample repo 的本地代码、测试、审查、安全扫描和等价 PR
> record 闭环。

## 1. 调用方与提供方

- 调用方：Control Console。
- 提供方：Platform API。
- 编排执行：Platform API service 调用 Agent Runtime、Orchestrator 与应用级
  Tool Gateway。
- 认证：M6 本地演示阶段沿用当前本地 API 边界，尚未接入用户登录；`actor_id`
  只用于审计，不能替代后续身份认证。
- 权限：请求不能指定 workspace、命令、分支、文件路径或 Artifact 根目录。
  这些值均由服务端配置、Task、已审批计划和 execution recipe 绑定。

## 2. 状态查询

```http
GET /api/tasks/{task_id}/local-development
```

返回当前 `current_phase`、下一步 `next_action`、已审批
`development_plan_id`、active AgentRun、最新 Artifact 引用和最新本地 PR
record 引用。

典型响应：

```json
{
  "task_id": "11111111-1111-1111-1111-111111111111",
  "current_phase": "Testing",
  "next_action": "run_tester",
  "development_plan_id": "22222222-2222-2222-2222-222222222222",
  "active_agent_run_id": null,
  "latest_artifact_ids": {
    "diff_patch": "33333333-3333-3333-3333-333333333333"
  },
  "latest_pull_request_record_id": null
}
```

## 3. 启动与单步推进

```http
POST /api/tasks/{task_id}/local-development/start
POST /api/tasks/{task_id}/local-development/run-next
Content-Type: application/json
```

请求体可省略：

```json
{
  "actor_id": "control-console",
  "reason": "开始执行已审批计划"
}
```

`start` 只校验当前最新版 Requirement、TechnicalDesign 和 DevelopmentPlan
引用链及审批状态，并将 `Planning` 推进到 `Scaffolding`。`run-next` 每次只执行
一个动作：

|阶段|下一动作|成功目标|
|---|---|---|
|`Scaffolding`|`run_scaffold`|`Implementing`|
|`Implementing`|`run_coder`|`Testing`|
|`Testing`|`run_tester`|`Reviewing` 或回到 `Implementing`|
|`Reviewing`|`run_reviewer`|`SecurityScanning` 或回到 `Implementing`|
|`SecurityScanning`|`run_security`|`ReadyForPR` 或回到 `Implementing`|
|`ReadyForPR`|`finalize_local_pull_request`|`PullRequestCreated`|

响应包含更新后的 Task、当前动作、公开消息、AgentRun、按执行顺序排列的
ToolCall、当前步骤新建 Artifact、PR record 和 `gate_evidence`。普通角色始终
复用 Task root conversation；一次工具循环无论包含多少次 provider 请求和工具
调用，只提交一个逻辑 conversation turn。

## 4. Artifact 列表与详情

```http
GET /api/tasks/{task_id}/artifacts?artifact_type=diff_patch&status=available&limit=50&cursor=0
GET /api/artifacts/{artifact_id}
```

- 列表支持 `artifact_type`、`status`、`limit` 和严格十进制 `cursor`。
- `status` 可取 `available`、`invalidated`、`missing`。
- `uri` 使用 `artifact://<id>`，响应不返回内部 `storage_key` 或绝对路径。
- 详情读取文件前校验 SHA-256；文本、JSON、XML、YAML、CSV、Markdown 和 diff
  最多预览 65536 bytes。
- `preview.kind` 为 `text` 或 `json`，并返回 `truncated` 与
  `bytes_returned`；二进制或不允许预览的媒体类型返回 `preview=null`。
- 摘要、预览和 metadata 会移除内部路径字段并遮蔽常见本机绝对路径。

M6 主要 Artifact 类型：

- `workspace_manifest`
- `implementation_report`
- `diff_patch`
- `junit_xml`
- `test_report`
- `review_report`
- `security_report`
- `format_patch`

## 5. 本地等价 PR record

```http
GET /api/tasks/{task_id}/pull-request-records?status=open&limit=50&cursor=0
GET /api/pull-request-records/{record_id}
```

M6 没有远端 Git 服务时保存 `provider=local` 的可审计记录：

- `base_branch`、`head_branch`
- baseline commit 与最终 `commit_sha`
- 仓库相对 changed files 与 diff stat
- 同一 evidence set 的 diff、test、review、security Artifact 引用
- branch/commit ToolCall 引用
- `url=null`

`status` 可取 `open`、`superseded`、`closed`。相同 Task/commit 或相同幂等键
不会产生重复记录。

## 6. 错误、幂等、重试与超时

统一错误结构包含 `code`、`message`、`detail`、`trace_id`。典型错误：

|HTTP|错误码/场景|
|---|---|
|404|Task、Artifact 或 PR record 不存在|
|409|最新版计划未审批、Task 已暂停/取消/终止、当前阶段不允许、已有 active AgentRun|
|409|Artifact evidence set、recipe hash 或 DevelopmentPlan 引用不一致|
|422|UUID、cursor、status、actor/reason 长度或查询参数非法|

M6 ToolCall 的幂等键由 Task 范围、workflow step、attempt 和 provider call
组成；工具名、风险和规范化参数 hash 用于检测相同键/调用 ID 的冲突。
execution recipe 另以工具名、移除服务端绑定字段后的 Pydantic 规范化参数和允许
次数精确校验。工具副作用成功但数据库最终提交失败时，重试复用已有 ToolCall、
commit 和 Artifact，不重复写文件或创建 PR record。

工具调用已落库但步骤后续失败时，AgentRun 保存配对 call/output 和
`<failed_step_context>`；该失败 conversation turn 不会被展示为成功 Agent 输出。

Provider、CLI、文件系统或报告解析等基础设施错误会记录失败 AgentRun，并按当前
可恢复语义暂停 Task；测试失败、Review 要求修改或安全代码问题会保存真实报告并
回到 `Implementing`。

## 7. 事件与审计

控制台通过 `GET /api/tasks/{task_id}/events/stream` 获取 M6 事件。核心事件：

- `LocalDevelopmentStarted`
- `ScaffoldCompleted`
- `CodePatchGenerated`
- `TestRunStarted`、`TestRunPassed`、`TestRunFailed`
- `ReviewCompleted`
- `SecurityScanCompleted`、`SecurityScanBlocked`
- `ArtifactCreated`
- `BranchCreated`、`CommitCreated`
- `PullRequestRecordCreated`

事件和 ToolCall 只保存公开摘要、关联 ID、hash、状态与耗时，不保存凭据、源码
正文、workspace 绝对路径或内部 Artifact 存储键。

## 8. 版本兼容性

- 首次实现版本：CloudHelm `0.5.0`。
- M6 只生成本地等价 PR record；远端 push、真实 GitHub/Gitea PR、合并、部署
  和健康检查由 M7 另行定义。
