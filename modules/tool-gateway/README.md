# modules/tool-gateway

CloudHelm M5 Tool Gateway 本地工具层。该模块提供工具注册、参数校验、
风险等级、审批拦截、路径边界、命令超时和审计摘要，不直接依赖 FastAPI
路由或数据库。

## 当前能力

- `requirement.normalize`、`design.render_markdown`：结构化需求/设计辅助工具。
- `repo.read_file`、`repo.search_text`、`repo.list_files`、`repo.write_file`：只作用于受控 `workspace_root`。
- `sandbox.run_command`、`sandbox.collect_artifact`：M5 使用本地受控目录 + `subprocess` 超时，暂未接 Docker。
- `git.status`、`git.diff`、`git.create_branch`、`git.commit`：只操作受控 Git 仓库根目录，不 push、不 rebase、不 tag。
- Agent 上下文要求 `agent_run_id` 与 `agent_type` 成对出现；Platform API 继续校验 AgentRun 归属和 `running` 状态。
- Repo、Sandbox 和 Git 的 `workspace_root` 必须等于或位于 Platform API 配置的 `CLOUDHELM_TOOL_WORKSPACE_ROOTS`；未配置时默认拒绝。
- `git.commit` 只接受显式文件路径，拒绝仓库根目录、目录 pathspec 和不存在的非 tracked 文件。
- 参数落库前递归脱敏，文件 `content` 只保留长度与 SHA-256；stdout、stderr 和结果 JSON 会移除常见 Token、Bearer 凭据和私钥块。
- 工具声明同时暴露参数 schema 与统一 `ToolCallResult` schema；Gateway 为成功、审批和失败路径生成一致的审计主体。
- 进程内滑动窗口限流：默认按 `task_id` 或 `agent_run_id` 每 60 秒最多 60 次调用，超额返回 `rate_limit_exceeded`。

## M5 隔离边界

Sandbox Tool 暂不创建 Docker 容器，只提供本地目录边界、命令 allow/deny
策略、环境变量白名单、超时和输出截断。Docker sandbox、网络隔离和资源
quota 留到 M6 前置增强。当前调用频率限流为单实例内存实现；多 worker
或远端部署时必须切换为 Redis 等共享存储，不能把单进程配额误当成分布式限流。

## 命令

```powershell
uv run pytest
```
