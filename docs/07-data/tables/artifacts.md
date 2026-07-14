# artifacts

## 业务含义

保存 M6 workspace manifest、implementation report、diff、JUnit、测试、审查、
安全与 format patch 的元数据。文件内容位于配置的 Artifact root，数据库只保存
安全相对 `storage_key`、hash、大小和摘要。

## 关键字段

- `task_id`
- `agent_run_id` / `tool_call_id`
- `producer_type`: `agent` / `tool` / `system`
- `artifact_type`
- `status`: `available` / `invalidated` / `missing`
- `display_name`、`media_type`
- `storage_key`
- `sha256`、`size_bytes`
- `summary`、`metadata_json`
- `idempotency_key`
- `created_at`、`updated_at`

## 约束与安全

- producer 为 agent/tool/system 时，只允许对应审计引用存在。
- `(task_id, idempotency_key)` 与 `storage_key` 唯一。
- `sha256` 必须使用 `sha256:<64 hex>`，`size_bytes>=0`。
- API 返回 `artifact://<id>`，不返回 `storage_key` 或本机绝对路径。
- 详情读取先校验文件大小与 hash，再按媒体类型返回最多 65536 bytes 的安全预览。
