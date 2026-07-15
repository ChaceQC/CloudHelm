# remote_targets

> 来源：[设计书 11.2](../../../云舵 CloudHelm 毕设设计书.md)
> 实现：`20260715_0007_create_m7_environment_remote_target.py`

## 业务含义

保存由服务端受控 profile 注册的 Linux Remote Agent 目标。M7 不支持调用方提交
任意 host、SSH 用户、Kubernetes context、namespace、endpoint 或 credential。

## SQL 结构

```sql
CREATE TABLE remote_targets (
    id UUID PRIMARY KEY,
    environment_id UUID NOT NULL
      REFERENCES environments(id) ON DELETE CASCADE,
    display_name TEXT NOT NULL,
    target_type TEXT NOT NULL DEFAULT 'linux_remote_agent',
    agent_id TEXT NOT NULL,
    agent_endpoint TEXT NOT NULL,
    credential_ref TEXT NOT NULL,
    tls_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'offline',
    agent_version TEXT,
    capabilities_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    last_heartbeat_at TIMESTAMPTZ,
    last_error_code TEXT,
    last_event_at TIMESTAMPTZ,
    last_status_changed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_remote_targets_type
      CHECK (target_type = 'linux_remote_agent'),
    CONSTRAINT ck_remote_targets_status
      CHECK (status IN ('offline', 'online', 'degraded', 'disabled')),
    CONSTRAINT ck_remote_targets_capabilities_array
      CHECK (jsonb_typeof(capabilities_json) = 'array'),
    CONSTRAINT ck_remote_targets_tls_fingerprint
      CHECK (tls_fingerprint ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT uq_remote_targets_environment_agent
      UNIQUE (environment_id, agent_id)
);
```

索引：

- `ix_remote_targets_environment_status_created`
- `ix_remote_targets_last_heartbeat`

## API 与事件边界

- 注册请求只接受 `profile_key` 和 `display_name`。
- 读取响应隐藏 `credential_ref`，并把完整 endpoint 转为
  `https://<redacted>:PORT`。
- 首次成功心跳写 `RemoteAgentOnline`；超时写 `RemoteAgentOffline`；恢复写
  `RemoteAgentRecovered`；普通 heartbeat 按间隔降频。
- M7-1 的离线收敛由 RemoteTarget 列表读取或下一次 heartbeat 触发，尚无周期
  worker；因此不描述为自主实时离线检测。
