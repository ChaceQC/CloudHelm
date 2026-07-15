# remote_agent_replay_nonces

> 实现：`20260715_0007_create_m7_environment_remote_target.py`

## 业务含义

持久化已经通过 HMAC 校验的 nonce hash，由 PostgreSQL 唯一约束裁决顺序和并发
重放。原始 nonce 不入库。

## 关键字段与约束

- `credential_id`：级联关联 `remote_agent_credentials.id`。
- `nonce_hash`：原始 nonce 的 SHA-256 lowercase hex。
- `request_timestamp`：签名请求的 Unix 秒转换结果。
- `expires_at`：清理时间，必须晚于 `request_timestamp`。
- 唯一约束：
  `uq_remote_agent_replay_nonces_credential_hash(credential_id, nonce_hash)`。
- 清理索引：`ix_remote_agent_replay_nonces_expires`。

## 保留规则

过期时间取以下两者较晚值：

1. 服务端接收时间加 `remote_agent_nonce_ttl_seconds`。
2. 请求时间加 timestamp tolerance 再加 1 秒。

因此即使请求时间接近允许的未来偏差，nonce 也会保留到该签名窗口完全关闭。
