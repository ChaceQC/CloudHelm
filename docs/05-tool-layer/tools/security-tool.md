# Security Tool

> 来源：[设计书 9.4](../../../云舵 CloudHelm 毕设设计书.md)

## 职责

Security Tool 通过受控命令 profile 执行真实 Python 代码与依赖安全扫描，返回
结构化 findings、stdout/stderr 摘要、退出码和稳定错误码。

## M6 函数

```text
security.run_bandit(cwd, path, timeout_seconds, max_output_chars)
security.run_pip_audit(cwd, timeout_seconds, max_output_chars)
```

`workspace_root` 由服务端绑定。Security Agent 只使用上述两个安全工具与必要的
Repo/Git 只读工具，不回退到通用命令执行。

## 风险等级

两项工具均为 L1：会在本地启动受控扫描进程，默认允许但必须写入 ToolCall 和
EventLog。

## 结果与失败

- Bandit 返回结构化代码 findings。
- pip-audit 返回依赖漏洞，并明确记录被跳过的本地包。
- 命令缺失、超时、非预期退出或报告解析失败使用稳定错误码，属于可恢复基础设施
  失败。
- 扫描工具不修改源码、不关闭规则、不执行远端镜像扫描；Trivy 镜像扫描属于 M7
  CI 制品门禁。
