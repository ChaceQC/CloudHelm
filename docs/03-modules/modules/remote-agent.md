# modules/remote-agent

> 来源：[设计书 7.1-7.2](../../../云舵 CloudHelm 毕设设计书.md)  
> 层级：`modules/remote-agent`

## M7-1 实现状态

当前模块版本 `0.5.1`，已实现：

- `GET /health`
- `GET /version`
- `GET /capabilities`
- 从权限受控 credential file 读取 machine secret。
- 对固定 UTF-8 JSON bytes 计算五行 canonical HMAC-SHA256。
- 使用 HTTPS、可选受控 CA、显式 timeout/连接池上限、
  `trust_env=False`、`follow_redirects=False` 发送 heartbeat。
- 对 ACK 执行 16 KiB 上限、JSON schema 和 target/agent identity 校验。
- worker 单次失败后继续运行，并响应 SIGINT/SIGTERM 停止。

credential 读取使用同一文件描述符完成 `O_NOFOLLOW -> fstat -> 有界读取`，
拒绝 symlink、替换竞态、非普通文件、超过 4096 bytes 和 POSIX 宽松权限。

## 当前未实现

M7-1 不提供：

- deployment operation store
- Docker Compose config/pull/up/ps
- service status、受限日志或 diagnostics
- restart、rollback、自由命令、文件传输或交互终端
- 指标、集中日志或告警

这些能力必须在后续 M7/M8 切片完成 Controller、Tool Gateway、审批、幂等、
路径/Compose policy 和持久化后再开放。文档和答辩材料不得把规划能力写成当前
Remote Agent 已上线能力。

## 配置与依赖

- Python `>=3.12`
- FastAPI / Uvicorn
- Pydantic Settings
- `httpx2`
- systemd 安装与 Docker Compose integration 属于后续 M7 部署切片

machine secret 不进入 Settings，只保存 credential file 绝对路径。target id
必须为 UUID，Platform API origin 必须为 HTTPS。轮换使用新的
`key_id + credential file` 并重启 heartbeat worker；服务端在短期窗口内同时
保留新旧 key，不把“只替换 secret 文件”描述为完整 key-id 轮换。

## 上游/下游

- heartbeat 上游：Platform API `/api/remote-agents/heartbeat`
- 后续部署上游：Deployment Controller
- 共享契约：
  - `packages/shared-contracts/openapi/cloudhelm-remote-agent.openapi.yaml`
  - `packages/shared-contracts/schemas/remote/remote-agent-heartbeat.schema.json`

## 测试关注点

- UUID/identity/nonce 与跨服务 DTO 一致。
- HMAC canonical 与实际发送 bytes 一致。
- HTTPS、CA、timeout、redirect、proxy 和响应体积边界。
- credential 文件权限、symlink、替换竞态和大小上限。
- ACK 非法 JSON、身份漂移、服务端错误和 worker 恢复。
- 运行时 OpenAPI 与提交版契约精确一致。
