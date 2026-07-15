# 安全边界

> 来源：[设计书 14.1](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：定义代码、Git、生产、密钥、数据库、部署、工具和成本的安全边界。
## 基线要求

- Agent 默认没有生产权限。
- 代码修改只允许发生在 sandbox worktree。
- 密钥不落日志，高风险数据库和部署动作必须审批。

## M5 本地工具边界

- Platform API 通过 `CLOUDHELM_TOOL_WORKSPACE_ROOTS` 配置允许根目录；未配置时默认拒绝 Repo、Sandbox、Git 工作区。Repo Tool 再使用 `Path.resolve()` 与 `relative_to()` 限制在对应 `workspace_root` 内，并拒绝 `.env`、私钥、证书、`.git`、依赖目录和构建产物。
- Sandbox Tool 使用命令数组和环境变量白名单，不允许 shell 字符串、高危命令、全局安装、网络扫描或后台常驻服务。
- Git Tool 只允许本地 `status`、`diff`、`switch -c`、显式路径 `commit`；不允许 push、force reset、clean、rebase、tag release。
- ToolCall 数据库参数只保存脱敏快照；文件正文只保留长度和 hash，Token、Cookie、密码、Bearer 凭据和私钥块不得进入参数、结果或输出摘要。
- Tool Gateway 审计主体由服务端生成并保存在 `audit_json`，调用方不能伪造参数 hash、风险、幂等键或终态。
- L3/L4 工具只创建审批请求，不执行远端副作用。

## M6 sample workspace 与证据门禁

- Platform API 只接受 `provider=local` 与受控 sample fixture；源 fixture 不被
  直接修改，实际副作用发生在由 `CLOUDHELM_M6_WORKSPACE_ROOT` 和 Task ID
  派生的独立 Git workspace。
- `CLOUDHELM_M6_SAMPLE_REPO_ROOT`、`CLOUDHELM_M6_RECIPE_ROOT`、
  `CLOUDHELM_M6_WORKSPACE_ROOT` 与 `CLOUDHELM_ARTIFACT_ROOT` 只由服务端
  配置读取，HTTP 请求和模型工具参数不能覆盖。
- Scaffold/Repo/Test/Security/Git 工具只接受正向 schema、命令数组、允许的
  相对路径、环境变量白名单、超时和输出上限；进程通过受控 runner 启动并在
  超时后清理。
- 本地 subprocess 仍不具备 Docker 的 CPU、内存、PID、只读挂载和内核级网络
  隔离。该剩余风险必须保留在 SecurityReport；远端部署前由 M7 再评估一次性
  Docker sandbox。
- Artifact 数据库仅保存相对 `storage_key`、SHA-256、大小和公开摘要。查询 API
  不返回内部 key 或绝对路径；详情在 hash 校验后最多预览 65536 bytes，并对
  metadata、摘要和文本中的常见本机绝对路径脱敏。
- `ReadyForPR` 与本地 commit 门禁要求 diff、通过测试、approved review 和
  non-blocking security 来自同一 `evidence_set_id`、同一已审批
  DevelopmentPlan 和同一 execution recipe hash。不同 cycle 的“拼接证据”
  不能创建 commit 或 PR record。
- `git.commit` 只接受经过 review 的显式文件列表；`provider=local` PR record
  强制 `url=null`，不伪造远端入口，也不执行 push。

## M7-1 RemoteTarget 与 machine identity

- RemoteTarget 只能由服务端 profile 派生 endpoint、TLS fingerprint、agent id
  和 credential metadata；HTTP 请求不能提交 host、endpoint、secret 或
  credential ref。
- Platform API 数据库只保存 secret fingerprint 和 ref。真实 HMAC secret 由
  运行配置注入；Remote Agent 只从绝对 credential file 读取。
- heartbeat 六个 header、原始 body hash、timestamp、nonce 和 target/agent/key
  必须同时校验。nonce hash 通过 PostgreSQL 唯一约束防顺序/并发 replay，并保留
  到 timestamp 窗口关闭。
- header 格式和 timestamp 窗口通过后，HMAC 不匹配统一返回
  `machine_auth_invalid`；target/credential lifecycle、scope、禁用和服务端配置
  状态只有在 HMAC 通过后才返回。
- 原始 heartbeat body 默认限制 16 KiB；validation detail 不回显 caller input。
- Remote Agent outbound client 强制 HTTPS，支持受控 CA，禁用环境代理和
  redirect，并限制 timeout、连接池和 ACK 大小。
- credential file 使用 no-follow、同一 fd 的类型/权限/大小检查与有界读取；完整
  key 轮换使用新 key id/ref，原地 secret 漂移由 fingerprint 阻断。
- Environment `base_url` 在 M7-1 不触发网络访问。后续健康检查必须改由服务端
  profile/allowlist 派生，避免形成任意 URL/SSRF 入口。

## 设计书摘录

### 14.1 安全边界

|领域|约束|
|---|---|
|代码修改|只能在 sandbox worktree 中修改|
|Git 操作|必须走 branch + commit + PR|
|生产环境|Agent 默认无生产 SSH 权限|
|密钥|通过 scoped temporary token 获取，禁止明文写入日志|
|数据库|destructive migration 必须人工审批|
|部署|Release / Deploy Agent 是部署编排入口；Git / CI 提供可追踪产物，Tool Gateway、审批和 Deployment Controller 控制实际远端变更|
|工具调用|全部记录 tool_calls 和 event_logs|
|权限|按 Agent 角色发放最小权限|
|成本|按 project / task / agent 设置 token 和资源预算|
