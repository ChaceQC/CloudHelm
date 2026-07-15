# CloudHelm Remote Agent

`cloudhelm-remote-agent` 是 CloudHelm M7 在 Linux staging/demo 主机上的远端
Agent 模块。当前版本为 `0.5.1`，本切片只交付以下真实能力：

- `GET /health`：返回 service、status、version、agent_id 和 capabilities。
- `GET /version`：返回模块版本与 Agent 身份。
- `GET /capabilities`：返回当前真实支持的 capability。
- heartbeat worker：周期性向 Platform API
  `POST /api/remote-agents/heartbeat` 提交 HMAC-SHA256 签名心跳。

当前尚未提供 deployment operation、Docker Compose 执行、服务日志、
diagnostics、restart、rollback、自由命令、文件传输或交互终端；这些能力必须
在后续 M7 切片完成策略、审批、幂等和持久化后再开放。

## 1. 安装

要求 Python `>=3.12` 和项目本地 `uv`：

```powershell
cd "D:\graduation project\modules\remote-agent"
uv sync --frozen
```

Linux 部署时同样在模块目录执行 `uv sync --frozen`，或从已验证的 wheel 创建
独立虚拟环境。不要全局安装依赖。

## 2. 环境变量

所有配置统一使用 `CLOUDHELM_REMOTE_AGENT_` 前缀：

|变量|必填|说明|
|---|---|---|
|`CLOUDHELM_REMOTE_AGENT_PLATFORM_API_BASE_URL`|是|Platform API 站点根地址；生产使用受控 CA 的 HTTPS|
|`CLOUDHELM_REMOTE_AGENT_TARGET_ID`|是|Platform API 已登记的 RemoteTarget ID|
|`CLOUDHELM_REMOTE_AGENT_AGENT_ID`|是|Remote Agent 稳定身份|
|`CLOUDHELM_REMOTE_AGENT_KEY_ID`|是|machine credential 轮换标识|
|`CLOUDHELM_REMOTE_AGENT_CREDENTIAL_FILE`|是|machine secret 绝对文件路径|
|`CLOUDHELM_REMOTE_AGENT_PLATFORM_CA_BUNDLE`|否|Platform API 自定义 CA bundle 绝对文件；为空使用系统信任库|
|`CLOUDHELM_REMOTE_AGENT_HEARTBEAT_SECONDS`|否|心跳尝试间隔，范围 `0.1..3600`，默认 `20`|
|`CLOUDHELM_REMOTE_AGENT_REQUEST_TIMEOUT`|否|HTTP 四类 timeout，范围 `0.1..120`，默认 `10`|
|`CLOUDHELM_REMOTE_AGENT_VERSION`|否|语义化版本，默认 `0.5.1`|
|`CLOUDHELM_REMOTE_AGENT_CAPABILITIES`|否|JSON 数组，默认当前四项运行信息能力|

PowerShell 本地联调示例只使用占位身份和临时凭据文件：

```powershell
$env:CLOUDHELM_REMOTE_AGENT_PLATFORM_API_BASE_URL = "https://platform.example.test"
$env:CLOUDHELM_REMOTE_AGENT_TARGET_ID = "00000000-0000-0000-0000-000000000201"
$env:CLOUDHELM_REMOTE_AGENT_AGENT_ID = "AGENT_ID"
$env:CLOUDHELM_REMOTE_AGENT_KEY_ID = "KEY_ID"
$env:CLOUDHELM_REMOTE_AGENT_CREDENTIAL_FILE = "C:\secure\cloudhelm\machine.secret"
$env:CLOUDHELM_REMOTE_AGENT_PLATFORM_CA_BUNDLE = "C:\secure\cloudhelm\platform-ca.pem"
$env:CLOUDHELM_REMOTE_AGENT_CAPABILITIES = '["capabilities","health","heartbeat","version"]'
```

machine secret 没有对应环境变量，也不会进入 Settings、API 响应或日志。

## 3. 凭据文件与 systemd

heartbeat 每次发送前重新读取 `credential_file`。读取使用同一文件描述符执行
`O_NOFOLLOW`、`fstat` 和最多 4097 bytes 的有界读取；文件为空、不是普通文件、
是 symlink、在检查/打开之间被替换、超过大小限制或在 POSIX 上具有 group/other
权限时，worker 使用稳定错误码拒绝发送。

完整 key 轮换需要同时更新 `key_id` 与 credential file，并重启 heartbeat worker；
Platform API 在短期窗口内保留新旧 key。只原子替换同一 key id 的 secret 文件不
等于完整轮换，服务端 fingerprint 也会阻断同一 credential ref 的原地漂移。

Linux 推荐使用 systemd `LoadCredential=` / `LoadCredentialEncrypted=`，把
`CREDENTIALS_DIRECTORY` 下的文件路径配置到
`CLOUDHELM_REMOTE_AGENT_CREDENTIAL_FILE`。unit 至少应使用专用用户、
`UMask=0077`、`NoNewPrivileges=true`、`PrivateTmp=true` 和精确的
`ReadOnlyPaths`/`ReadWritePaths`。Windows 本地联调应给凭据文件设置专用账号
ACL；Windows 不使用 POSIX mode 位代替 ACL 判断。

## 4. 启动

启动只读 HTTP 接口：

```powershell
uv run cloudhelm-remote-agent serve --host 127.0.0.1 --port 9443
```

启动独立 heartbeat worker：

```powershell
uv run cloudhelm-remote-heartbeat
```

也可以使用模块入口：

```powershell
uv run python -m cloudhelm_remote_agent serve
uv run python -m cloudhelm_remote_agent heartbeat
```

heartbeat worker 响应 `SIGINT`/`SIGTERM`，停止时退出循环并关闭 HTTP 连接池。
单次失败只记录脱敏错误码，等待有界间隔后继续尝试。

## 5. Heartbeat 与 HMAC 契约

JSON body 使用 UTF-8、紧凑分隔符和稳定 key 排序，字段固定为：

```json
{
  "target_id": "00000000-0000-0000-0000-000000000201",
  "agent_id": "AGENT_ID",
  "agent_version": "0.5.1",
  "capabilities": ["health", "heartbeat"],
  "reported_at": "2026-07-15T00:00:00Z"
}
```

实际发送使用 `content=body_bytes`，签名后不会再由 HTTP client 重新序列化。
canonical string 无末尾换行：

```text
METHOD
PATH
TIMESTAMP
NONCE
BODY_SHA256
```

签名为 `HMAC-SHA256(secret, canonical UTF-8)` 的 lowercase hex。请求只增加
以下六个 CloudHelm authentication headers：

- `X-CloudHelm-Target-Id`
- `X-CloudHelm-Agent-Id`
- `X-CloudHelm-Key-Id`
- `X-CloudHelm-Timestamp`
- `X-CloudHelm-Nonce`
- `X-CloudHelm-Signature`

HTTP client 强制 HTTPS，支持受控 CA bundle，显式设置 connect/read/write/pool
timeout、连接池上限、`trust_env=False` 和 `follow_redirects=False`。成功响应
正文最多 16 KiB，必须为合法 ACK JSON，且 `target_id`、`agent_id` 与请求一致。
成功时使用服务端建议间隔与本地配置中的较小值；失败时使用本地有界间隔。

## 6. 验证

```powershell
uv sync --frozen
uv run pytest
git diff --check -- modules/remote-agent modules/README.md packages/shared-contracts
```

测试使用 `httpx2.MockTransport` 和 ASGI transport，只存在于测试路径；生产
heartbeat client 使用真实 `httpx2.AsyncClient`。

提交版 Remote Agent OpenAPI 位于
`packages/shared-contracts/openapi/cloudhelm-remote-agent.openapi.yaml`，测试会
与运行时 `/openapi.json` 精确比较；heartbeat 请求/响应 schema 位于
`packages/shared-contracts/schemas/remote/remote-agent-heartbeat.schema.json`。
