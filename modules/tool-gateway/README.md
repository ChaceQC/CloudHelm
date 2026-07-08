# modules/tool-gateway

CloudHelm M5 Tool Gateway 本地工具层。该模块提供工具注册、参数校验、
风险等级、审批拦截、路径边界、命令超时和审计摘要，不直接依赖 FastAPI
路由或数据库。

## 当前能力

- `requirement.normalize`、`design.render_markdown`：结构化需求/设计辅助工具。
- `repo.read_file`、`repo.search_text`、`repo.list_files`、`repo.write_file`：只作用于受控 `workspace_root`。
- `sandbox.run_command`、`sandbox.collect_artifact`：M5 使用本地受控目录 + `subprocess` 超时，暂未接 Docker。
- `git.status`、`git.diff`、`git.create_branch`、`git.commit`：只操作受控 Git 仓库根目录，不 push、不 rebase、不 tag。

## M5 隔离边界

Sandbox Tool 暂不创建 Docker 容器，只提供本地目录边界、命令 allow/deny
策略、环境变量白名单、超时和输出截断。Docker sandbox、网络隔离和资源
quota 留到 M6 前置增强。

## 命令

```powershell
uv run pytest
```
