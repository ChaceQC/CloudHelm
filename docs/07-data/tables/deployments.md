# deployments

> 来源：[设计书 11.2](../../../云舵 CloudHelm 毕设设计书.md)、
> [M7 CI 与远端部署细化](../../15-detailed-design/09-m7-ci-remote-deployment-flow.md)

## 业务含义

`deployments` 保存业务项目一次受控远端部署的权威身份、第二道 L3 Approval、
不可变制品、Remote Agent operation、健康结果和失败摘要。

M7-2D 只建立数据底座，不新增审批、部署 HTTP API、WorkflowJob handler、
Deployment Controller 或 Remote Agent operation。

## 字段

|字段|类型|可空|说明|
|---|---|---|---|
|`id`|UUID|否|记录唯一标识。|
|`task_id` / `project_id`|UUID|否|所属 Task 与 Project。|
|`environment_id` / `remote_target_id`|UUID|否|staging/demo Environment 与 Linux RemoteTarget。|
|`ci_run_id`|UUID|否|通过 CI 的 CIRun。|
|`release_plan_artifact_id`|UUID|否|不可变 ReleasePlan Artifact。|
|`commit_sha`|TEXT|否|40/64 位小写 hex 完整 SHA。|
|`image_ref`|TEXT|否|可展示的镜像引用；部署身份仍以 digest 为准。|
|`image_digest`|TEXT|否|不可变 OCI digest。|
|`platform_manifest_digest`|TEXT|否|通用 renderer 输入 manifest digest。|
|`release_version`|TEXT|否|Environment 内唯一版本。|
|`request_hash`|TEXT|否|deployment canonical request SHA-256。|
|`approval_id`|UUID|是|第二道 L3 deployment Approval。|
|`remote_operation_id`|TEXT|是|Remote Agent 幂等 operation ID。|
|`status`|TEXT|否|部署生命周期状态。|
|`health_summary_json`|JSONB|是|有界、脱敏的结构化健康摘要。|
|`failure_code` / `failure_summary`|TEXT|是|稳定失败码和有界脱敏摘要。|
|`requested_by_actor`|TEXT|否|请求者兼容投影；M9 再绑定真实 user identity。|
|`approved_by_actor`|TEXT|是|审批者兼容投影。|
|`dispatched_by_agent_run_id`|UUID|是|执行部署调度的 AgentRun。|
|`idempotency_key`|TEXT|否|Task 内部署幂等键。|
|`started_at` / `finished_at`|TIMESTAMPTZ|是|实际 operation 起止时间。|
|`rollback_candidate_id`|UUID|是|健康失败后的历史 Deployment 候选。|
|`rollback_request_artifact_id`|UUID|是|只描述回滚请求的 Artifact。|
|`created_at` / `updated_at`|TIMESTAMPTZ|否|数据库时间。|

## 状态与证据

```text
planned
pending_approval
queued
deploying
verifying
healthy
unhealthy
failed
rollback_requested
cancelled
```

- `planned`：尚未绑定第二道 Approval。
- `pending_approval`：必须绑定 Approval；尚未写批准人或 operation。
- `queued`：必须有 Approval 和 `approved_by_actor`。
- `deploying/verifying`：必须有 Approval、批准人、operation 和 `started_at`。
- `healthy/unhealthy`：必须再有 `finished_at` 和 JSON object 健康摘要。
- `failed`：必须有 `finished_at` 和稳定 `failure_code`。
- `rollback_requested`：必须同时绑定另一条历史 Deployment 和 rollback request
  Artifact；不得自引用。
- `cancelled`：允许在远端 operation 前或后结束，但若已开始必须有
  `finished_at`。

M7 不包含 `restarting` 或 `rolled_back`；回滚请求不触发远端回滚。后续真正执行
回滚时创建新的 Deployment 和独立 Approval。

## 约束与索引

- commit 为 40/64 位小写 hex。
- `request_hash`、`image_digest`、`platform_manifest_digest` 固定为
  `sha256:<64 lowercase hex>`。
- `health_summary_json` 为空或 JSON object。
- `failure_code` 最长 160；`failure_summary` 最长 1024，且只保存脱敏摘要。
- `(task_id, idempotency_key)` 唯一。
- `(environment_id, release_version)` 唯一。
- `approval_id` 非空时唯一。
- `(remote_target_id, remote_operation_id)` 在 operation 非空时唯一。
- 查询索引：
  - `(task_id, created_at DESC, id DESC)`
  - `(project_id, created_at DESC, id DESC)`
  - `(environment_id, created_at DESC, id DESC)`

## Deployment Approval 组合

资源型 Approval 必须满足：

```text
action=approve_deployment
resource_type=deployment
risk_level=L3
requested_by_agent_run_id IS NOT NULL
```

其他 action 不能使用 `resource_type=deployment`。现有
`approve_release_candidate + release_candidate + L2` 组合继续有效。

## 外键与删除

- Task、Project 使用 `ON DELETE CASCADE`。
- Environment、RemoteTarget、CIRun、ReleasePlan Artifact、Approval、
  AgentRun 与 rollback Artifact/Deployment 使用 `ON DELETE NO ACTION`，
  防止破坏发布审计链。
- `service_instances.deployment_id` 使用 `ON DELETE CASCADE`，只在 Deployment
  聚合被合法清理时一并删除。
