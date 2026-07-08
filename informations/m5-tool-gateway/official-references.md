# M5 Tool Gateway 官方资料归档

检索日期：2026-07-08

## 采用资料

|主题|官方链接|采用结论|
|---|---|---|
|Pydantic / JSON Schema 参数校验|https://docs.pydantic.dev/latest/concepts/json_schema/|Tool Gateway 使用 Pydantic model 做运行时参数校验，并把 `model_json_schema()` 暴露为工具声明。|
|Python `pathlib` 路径解析|https://docs.python.org/3/library/pathlib.html|Repo / Sandbox / Git Tool 使用 `Path.resolve()` 和 `relative_to()` 约束 workspace 边界，阻止 `..`、绝对路径和 symlink 越界。|
|Python `subprocess` 超时|https://docs.python.org/3/library/subprocess.html|Sandbox Tool 使用命令数组、`capture_output`、UTF-8 解码和 `timeout`，不使用 shell 字符串拼接。|
|Git CLI 本地操作|https://git-scm.com/docs/git-status、https://git-scm.com/docs/git-diff、https://git-scm.com/docs/git-switch、https://git-scm.com/docs/git-commit|Git Tool 只实现 `status`、`diff`、`switch -c` 和显式文件列表 `commit`；不实现 push、rebase、tag、reset。|
|Docker sandbox 隔离实践|https://docs.docker.com/engine/security/、https://docs.docker.com/engine/containers/resource_constraints/|M5 暂不接 Docker，只记录本地受控目录 + subprocess 的临时边界；Docker 网络隔离和资源 quota 列为 M6 前置增强。|
|MCP Tool Server 工具契约|https://modelcontextprotocol.io/specification/2025-06-18/server/tools|工具声明需要名称、描述、参数 schema 和结构化结果；CloudHelm 当前通过本地 registry 暴露等价工具元数据。|
|pytest 临时目录|https://docs.pytest.org/en/stable/how-to/tmp_path.html|Repo、Sandbox、Git Tool 测试使用 `tmp_path` 创建隔离 workspace/repo，不污染真实项目目录。|

## 取舍说明

- M5 先实现本地工具底座和审计链路，不启动 Docker 容器、不执行远端 SSH/部署。
- 对执行类工具使用命令数组和环境变量白名单，避免 shell 拼接和系统全局污染。
- 对文件类工具统一走路径策略，敏感文件、依赖目录、构建产物和 `.git` 内部目录默认拒绝。
- L3/L4 工具在 M5 只创建 `ApprovalRequest`，不调用 handler，不产生远端副作用。
