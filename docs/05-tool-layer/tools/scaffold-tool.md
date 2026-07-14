# Scaffold Tool

> 来源：[设计书 9.4](../../../云舵 CloudHelm 毕设设计书.md)

## 职责

Scaffold Tool 通过 Tool Gateway 把只读 fixture 准备为 Task 独立 Git
workspace，并返回可验证的 baseline 身份。

## M6 函数

```text
scaffold.prepare_workspace(
  template_id,
  source_root,
  workspace_root,
  target_directory,
  baseline_branch,
  git_user_name,
  git_user_email
)
```

`source_root`、`workspace_root` 和 `target_directory` 是服务端绑定字段，不进入
模型可控参数。当前唯一模板为 `sample-repo-python`。

## 风险等级

L1：创建本地 workspace、初始化 Git 和 baseline commit，默认允许但必须审计。

## 幂等与失败

- Scaffold marker 保存 Task、模板、source hash、baseline branch 与 commit。
- 相同身份重放返回已有 workspace，不覆盖后续代码变更。
- marker、baseline 或目标目录冲突时返回结构化失败。
- 不执行远端 clone/push、CI 或部署。
