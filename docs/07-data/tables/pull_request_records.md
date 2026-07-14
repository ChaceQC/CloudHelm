# pull_request_records

## 业务含义

保存 M6 本地 branch、commit、changed files、diff stat 和四类质量门禁 Artifact
组成的等价 PR 记录。它不是远端 Git PR，也不是 Task 终态。

## 关键字段

- `task_id`、`project_id`、`development_plan_id`
- `created_by_agent_run_id`
- `branch_tool_call_id`、`commit_tool_call_id`
- `provider`: `local` / `github` / `gitea`
- `status`: `open` / `superseded` / `closed`
- `title`、`summary`
- `base_branch`、`head_branch`
- `base_commit_sha`、`commit_sha`
- `changed_files_json`、`diff_stat_json`
- `diff_artifact_id`、`test_artifact_id`、`review_artifact_id`、
  `security_artifact_id`
- `url`
- `idempotency_key`
- `created_at`、`updated_at`

## 约束

- base/head branch 必须不同；commit SHA 为 40 或 64 位小写十六进制。
- local provider 必须 `url IS NULL`。
- `(task_id, commit_sha)` 与 `(task_id, idempotency_key)` 唯一。
- 四类 Artifact 必须属于同一 Task、DevelopmentPlan、recipe hash 和 evidence
  set，并分别满足 diff、通过测试、approved review、non-blocking security 门禁。
