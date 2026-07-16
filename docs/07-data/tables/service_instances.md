# service_instances

> 来源：[设计书 11.2](../../../云舵 CloudHelm 毕设设计书.md)、
> [M7 CI 与远端部署细化](../../15-detailed-design/09-m7-ci-remote-deployment-flow.md)

## 业务含义

`service_instances` 保存一次 Deployment 在指定 Environment/RemoteTarget 上发现的
Docker Compose 服务实例及最近健康证据。它不是通用容器 inventory，也不接受
Kubernetes、SSH 或任意 runtime。

## 字段

|字段|类型|可空|说明|
|---|---|---|---|
|`id`|UUID|否|记录唯一标识。|
|`deployment_id`|UUID|否|所属 Deployment。|
|`environment_id`|UUID|否|所属 staging/demo Environment。|
|`remote_target_id`|UUID|否|运行该服务的 Linux RemoteTarget。|
|`service_name`|TEXT|否|受控 Compose service slug。|
|`compose_project`|TEXT|否|受控 Compose project slug。|
|`runtime_type`|TEXT|否|M7 固定为 `docker_compose`。|
|`runtime_ref`|TEXT|是|Remote Agent 返回的容器/服务引用。|
|`image_digest`|TEXT|否|不可变 OCI digest。|
|`status`|TEXT|否|服务生命周期状态。|
|`health_url`|TEXT|是|经服务端 profile/allowlist 派生且不含 userinfo 的 HTTP(S) 健康 URL。|
|`health_result_json`|JSONB|是|最近一次结构化、脱敏健康结果。|
|`last_health_check_at`|TIMESTAMPTZ|是|最近健康检查时间。|
|`last_error_code`|TEXT|是|稳定、脱敏的最近错误码。|
|`created_at` / `updated_at`|TIMESTAMPTZ|否|数据库时间。|

## 状态与证据

```text
starting
running
healthy
unhealthy
stopped
failed
```

- `healthy/unhealthy` 必须同时具有 JSON object `health_result_json` 和
  `last_health_check_at`。
- `failed` 必须具有稳定 `last_error_code`。
- 其他状态不要求健康证据；如保存健康结果，结果与检查时间仍必须成对出现。
- M7 不提供 `unknown` 状态；缺少实时证据时保留最后已知状态并依靠时间字段判断
  freshness。

## 约束与索引

- `runtime_type = 'docker_compose'`。
- service 与 Compose project 使用小写字母、数字、短横线和下划线受控 slug。
- `image_digest` 固定为 `sha256:<64 lowercase hex>`。
- `health_result_json` 为空或 JSON object；对象最多 32 个小写受控 key，value
  只允许最长 512 字符的 string、number、boolean 或 null。禁止
  `token/secret/credential/password/cookie/authorization` 和
  `raw_logs/stdout/stderr/log` 等敏感或原始日志字段。
- `last_error_code` 最长 128。
- `(deployment_id, service_name)` 唯一。
- 查询索引：
  - `(environment_id, status, created_at DESC, id DESC)`
  - `(remote_target_id, status, created_at DESC, id DESC)`

## 跨表一致性

Environment、RemoteTarget 和 image digest 必须与父 Deployment 一致，但 PostgreSQL
CHECK 不能跨表读取。M7-2D repository 提供精确查询与锁入口；后续 deployment
service 在同一事务、Task/Deployment 行锁下重验，不在 repository 中实现状态机。

## 外键与删除

- Deployment 使用 `ON DELETE CASCADE`。
- Environment 与 RemoteTarget 使用 `ON DELETE NO ACTION`。
