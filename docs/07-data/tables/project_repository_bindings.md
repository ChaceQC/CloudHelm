# project_repository_bindings

> 来源：[数据库关键表总览](../01-database-schema.md)
> M7-2 migration：`20260716_0008_create_m7_release_jobs.py`

## 业务含义

把一个 CloudHelm Project 绑定到服务端配置的 Gitea repository profile。普通 API
只提交 `profile_key`；repository identity、clone URL、credential ref、workflow
和 release ref 前缀全部由服务端 profile 解析。

## 字段

|字段|约束|说明|
|---|---|---|
|`id`|UUID PK|Binding 唯一标识。|
|`project_id`|唯一 FK `projects.id`, `ON DELETE CASCADE`|每 Project 一条 binding。|
|`provider`|固定 `gitea`|M7 provider。|
|`profile_key`|受控 key|只允许字母、数字、点、下划线和短横线。|
|`repository_external_id`|非空|Gitea repository 稳定 ID。|
|`repository_owner/repository_name`|非空|大小写不敏感的 repository identity。|
|`clone_url`|HTTPS、无 userinfo|内部 Git 访问地址；不进入普通响应。|
|`default_branch`|非空|默认分支。|
|`credential_ref`|非空|服务端 credential 映射引用；不进入响应、事件或日志。|
|`workflow_id`|非空|固定 Gitea workflow identity。|
|`release_ref_prefix`|完整 `refs/heads/...`|无尾斜杠的 candidate ref 前缀。|
|`status`|active/disabled|Binding 状态。|
|`created_at/updated_at`|UTC，`updated_at>=created_at`|审计时间。|

## 唯一性与删除规则

- `project_id` 唯一。
- `(provider, repository_external_id)` 唯一。
- `(provider, lower(repository_owner), lower(repository_name))` 唯一。
- 删除 Project 级联删除 binding；被 ReleaseCandidate 引用时不得单独删除。

## Profile 与 ref 门禁

- `PUT /api/projects/{project_id}/repository-binding` 请求体只允许：

  ```json
  {"profile_key": "demo-gitea-repository"}
  ```

- URL、token、credential ref、workflow path、remote name 和 refspec 作为额外字段
  提交时返回 422。
- `release_ref_prefix` 必须是无尾斜杠的完整 `refs/heads/...`，服务层使用等价
  `git check-ref-format` 规则校验；数据库 CHECK 再拒绝空白、`..`、`//`、`@{`、
  `.lock`、反斜杠和 Git 禁止字符。
- PUT 先按当前 binding 与新 profile 分别计算 internal snapshot hash。相同
  profile key、相同物化字段且状态仍为 active 时返回原 binding，不改
  `updated_at`、不写事件，也不失效 Candidate。
- 只有 internal snapshot hash 变化，或 binding 从 active 变为 disabled
  时，才更新 binding，并把旧 `pending_approval|approved` Candidate 标记为
  stale、把其 pending Approval 标记为 expired，同时写
  `decided_by=system:release_candidate_freshness` 与数据库决策时间。
- 已经 published 的历史事实不改写。

## PUT / Candidate POST 并发

- Candidate POST 按 `Task -> Binding -> PullRequestRecord -> existing Candidate`
  加锁，并从生成 snapshot 到插入 Candidate 的整个短事务持有 Binding
  `FOR UPDATE`。
- Binding PUT 先取得 RepositoryBinding 配置 namespace 的 transaction-level
  advisory lock，再锁 Binding，并按 Candidate/Approval UUID 升序锁定并失效旧
  资源；该事务不反向获取 Task。advisory lock 用于避免跨 Project identity
  swap 死锁。
- PUT 先提交时 POST 使用新 snapshot；POST 先提交时 PUT 必须看到并失效刚插入的旧
  snapshot Candidate。

## Candidate snapshot

Candidate 不只引用可变 binding 行。创建时必须保存安全 snapshot JSON，并对包含
`profile_key`、`clone_url`、`credential_ref` 的内部 snapshot 计算稳定 hash。
内部配置只参与 hash，不进入 Candidate API、EventLog 或日志。

完整 CHECK、索引和 SQL 以
[01-database-schema.md](../01-database-schema.md) 为权威来源。
