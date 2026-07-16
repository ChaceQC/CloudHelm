# ci_runs

> 来源：[设计书 11.2](../../../云舵 CloudHelm 毕设设计书.md)、
> [M7 CI 与远端部署细化](../../15-detailed-design/09-m7-ci-remote-deployment-flow.md)

## 业务含义

`ci_runs` 保存一次受控 `workflow_dispatch` 对应的 Gitea CI 权威身份、状态和
不可变制品证据。它绑定精确 ReleaseCandidate、PullRequestRecord、commit 与
候选 ref；CI 只执行 test/security/build/artifact，不执行远端部署。

M7-2D 只建立数据库、ORM、repository 和共享数据契约，不发布 candidate ref、
不触发 Gitea workflow，也不生产 CI 事件。

## 字段

|字段|类型|可空|说明|
|---|---|---|---|
|`id`|UUID|否|记录唯一标识。|
|`task_id`|UUID|否|所属 Task。|
|`project_id`|UUID|否|所属 Project。|
|`pull_request_record_id`|UUID|否|来源 PullRequestRecord。|
|`release_candidate_id`|UUID|否|唯一 ReleaseCandidate。|
|`provider`|TEXT|否|M7 固定为 `gitea`。|
|`repository_external_id`|TEXT|否|Gitea 仓库稳定外部 ID。|
|`external_run_id`|TEXT|是|provider run ID；dispatch 已接受但尚未关联 run 时可空。|
|`external_job_id`|TEXT|是|provider job ID。|
|`workflow_id`|TEXT|否|服务端受控 workflow 标识。|
|`workflow_revision`|TEXT|否|workflow 定义版本或内容摘要。|
|`source_ref`|TEXT|否|完整 `refs/heads/...` 候选 ref。|
|`commit_sha`|TEXT|否|40/64 位小写十六进制完整 SHA。|
|`status`|TEXT|否|`triggered/running/passed/failed/cancelled`。|
|`idempotency_key`|TEXT|否|Task 内 CI 创建幂等键。|
|`last_event_action`|TEXT|是|最后一次接受的 provider event action。|
|`last_event_status`|TEXT|是|最后一次接受的 provider event status。|
|`last_delivery_id`|TEXT|是|最后一次安全幂等 delivery 线索。|
|`provider_head_sha`|TEXT|是|provider 回报的 head SHA，非空时必须等于 commit。|
|`provider_updated_at`|TIMESTAMPTZ|是|provider 记录的更新时间。|
|`artifact_manifest_id`|UUID|是|通过 CI 的 manifest Artifact。|
|`image_index_digest`|TEXT|是|不可变 OCI image index digest。|
|`platform_manifest_digest`|TEXT|是|CloudHelm 平台 manifest digest。|
|`started_at`|TIMESTAMPTZ|是|CI 开始时间。|
|`finished_at`|TIMESTAMPTZ|是|CI 终态时间。|
|`created_at`|TIMESTAMPTZ|否|数据库创建时间。|
|`updated_at`|TIMESTAMPTZ|否|数据库更新时间。|

## 状态与证据

|状态|必须字段|禁止伪造|
|---|---|---|
|`triggered`|基础身份|不得写 passed 证据或完成时间。|
|`running`|`started_at`|不得写 passed 证据或完成时间。|
|`passed`|`started_at`、`finished_at`、`provider_head_sha`、manifest Artifact、两类 digest|所有不可变证据必须同时存在。|
|`failed` / `cancelled`|`finished_at`；`started_at` 可空|不得携带 manifest/digest passed 证据。|

`last_event_action`、`last_event_status`、`last_delivery_id` 和
`provider_updated_at` 必须全空或全有，避免保存不可比较的半组幂等线索。

## 约束与索引

- `provider = 'gitea'`。
- `source_ref` 必须是合法完整 `refs/heads/...`。
- SHA 只允许 40/64 位小写 hex；`provider_head_sha` 非空时等于 `commit_sha`。
- digest 固定为 `sha256:<64 lowercase hex>`。
- `release_candidate_id` 唯一。
- `(task_id, idempotency_key)` 唯一。
- `(provider, repository_external_id, external_run_id)` 在 run ID 非空时唯一。
- 查询索引：
  - `(task_id, created_at DESC, id DESC)`
  - `(project_id, created_at DESC, id DESC)`

## 外键与删除

- Task、Project 使用 `ON DELETE CASCADE`，与所属平台业务聚合一并清理。
- PullRequestRecord、ReleaseCandidate、Artifact 使用 `ON DELETE NO ACTION`，
  防止删除已进入发布证据链的历史事实。

## 安全边界

- 不保存 token、credential、clone URL、原始 CI 日志或 webhook 原文。
- delivery 字段只用于最后一次安全幂等比较；完整 delivery 审计由后续 EventLog
  纵切实现。
- 可变 tag、容器 image ID 和日志文本不能作为部署身份。
