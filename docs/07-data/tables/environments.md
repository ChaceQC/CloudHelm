# environments

> 来源：[设计书 11.2](../../../云舵 CloudHelm 毕设设计书.md)
> 实现：`20260715_0007_create_m7_environment_remote_target.py`

## 业务含义

保存 Project 下的 M7 staging/demo 环境。`production` 不在当前 MVP。

## SQL 结构

```sql
CREATE TABLE environments (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    environment_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    base_url TEXT NOT NULL,
    env_profile_ref TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_environments_type
      CHECK (environment_type IN ('staging', 'demo')),
    CONSTRAINT ck_environments_status
      CHECK (status IN ('active', 'disabled', 'degraded')),
    CONSTRAINT uq_environments_project_name UNIQUE (project_id, name)
);

CREATE INDEX ix_environments_project_status_created
  ON environments(project_id, status, created_at);
```

## API 与安全边界

- 创建请求只接受 `name`、`environment_type`、`base_url`。
- `env_profile_ref` 是内部部署配置引用，M7-1 不接受调用方提交，也不在响应中返回。
- `base_url` 必须为 HTTPS，且不能包含 userinfo、query 或 fragment。
- M7-1 只保存和展示 `base_url`，不据此发起网络请求；后续健康检查必须由服务端
  profile/allowlist 派生目标，不能把该字段直接作为任意 URL 请求入口。
- 删除 Project 时通过外键级联删除 Environment 及其 RemoteTarget 认证子记录。
