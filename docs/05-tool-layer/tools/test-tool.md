# Test Tool

> 来源：[M6 本地开发细化设计](../../15-detailed-design/08-m6-local-development-flow.md)

## 职责

Test Tool 在服务端绑定的 Task workspace 中执行真实 pytest，强制生成并解析
JUnit XML，把退出码、计数、stdout/stderr 和报告路径作为同一 ToolCall 结果。

## M6 函数

```text
test.run_pytest(
  cwd,
  pytest_args,
  junit_path,
  timeout_seconds,
  max_output_chars
)
```

`workspace_root` 由服务端绑定。`--rootdir`、`--confcutdir`、`--basetemp`、
`--junitxml` 和 `-c` 等平台管理参数会被拒绝。

## 风险等级

L1：启动本地测试进程并写入受控 JUnit 文件，默认允许但必须审计。

## 结果与失败

- pytest exit code、JUnit tests/failures/errors/skipped 和输出摘要必须一致。
- JUnit 文件缺失、为空、解析失败、命令缺失或超时返回稳定错误码。
- Tester Agent 只使用 `test.run_pytest`，不使用通用命令绕过测试 profile。
