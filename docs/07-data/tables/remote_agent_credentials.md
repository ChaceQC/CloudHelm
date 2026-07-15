# remote_agent_credentials

> 实现：`20260715_0007_create_m7_environment_remote_target.py`

## 业务含义

保存 RemoteTarget machine credential 的可审计元数据。真实 HMAC secret 只存在于
Platform API 服务端 secret 映射和 Remote Agent credential file，不进入数据库。

## 关键字段与约束

- `target_id`：级联关联 `remote_targets.id`。
- `agent_id`、`key_id`：credential 身份；`(target_id, key_id)` 唯一。
- `credential_ref`：服务端 secret 引用，API/EventLog 不返回。
- `scopes_json`：JSON array，例如 `heartbeat`。
- `secret_fingerprint`：`sha256:<64 lowercase hex>`，用于检测 secret 原地漂移。
- `active_from`、`expires_at`、`revoked_at`：生效、过期和撤销时间。
- `expires_at` 为空或必须晚于 `active_from`。

索引：

- `ix_remote_agent_credentials_target_agent`
- `ix_remote_agent_credentials_expiry`

## 轮换语义

轮换通过新增不同 `key_id + credential_ref` 并保留短期重叠窗口完成。不得只在同一
`credential_ref` 原地替换 secret；Platform API 会比较登记 fingerprint 并阻断
漂移配置。
