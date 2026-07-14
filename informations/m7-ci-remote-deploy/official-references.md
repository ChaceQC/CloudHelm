# M7 CI/CD 与远端部署官方资料归档

检索日期：2026-07-14；复核日期：2026-07-15

适用阶段：M7 真实 CI、release candidate、Release / Deploy Agent、Deployment
Controller、Remote Agent、远端 staging 部署、受限诊断和跨服务契约

## 1. Gitea Actions、Runner、API 与 Webhook

### 官方链接

- [Gitea Actions Overview](https://docs.gitea.com/usage/actions/overview)
- [Quick Start](https://docs.gitea.com/usage/actions/quickstart)
- [Act Runner](https://docs.gitea.com/usage/actions/act-runner)
- [Comparison with GitHub Actions](https://docs.gitea.com/usage/actions/comparison)
- [Gitea API 1.26.4](https://docs.gitea.com/api/1.26/)
- [Repository Webhooks](https://docs.gitea.com/usage/repository/webhooks)

### 适用子任务

- `7.2` 建立真实 CI 与 release candidate 来源。
- `7.7` 实现 `ci.trigger_workflow`、run/job/log/artifact 查询和失败 job 重跑。
- `7.10` 接收、验证并幂等处理 CI Webhook。

### 摘要

- Gitea Actions 从仓库 `.gitea/workflows/` 读取 workflow；`act_runner` 通过实例、
  组织或仓库级 registration token 注册。registration token 可重复注册多个 runner，
  直到被重置或撤销，因此属于高敏长期注册凭据，不是一次性 token。
- 当前 Gitea API 提供 workflow dispatch，以及 workflow run、job、log、artifact
  的查询接口；API 响应中的 run/job/artifact 标识应作为远端事实保存。
- Webhook 使用原始请求体和 secret 计算 HMAC-SHA256；`X-Gitea-Delivery` 是一次
  delivery attempt 的 UUID，`X-Gitea-Signature` 是不带前缀的十六进制摘要。
  workflow 状态事件使用 `workflow_run` / `workflow_job`，delivery id 本身不能
  代替 run/job 级业务幂等身份。

### 采用结论

- CI workflow 由仓库版本化管理；CloudHelm 只通过受控 workflow id、精确 ref
  和结构化 inputs 触发，不允许调用方提交任意 workflow 文件或 runner label。
- Runner 在 CI 专用主机或隔离 Compose 网络注册，与 Remote Agent、registry 和
  部署目标隔离；固定 Gitea/act_runner patch 版本或镜像 digest，不使用
  `latest`/`nightly`。registration token 只用于人工初始化，注册完成后立即
  轮换或撤销，不写入仓库、数据库、Artifact、日志或 API 响应。
- Platform API 保存 Gitea run id、job id、artifact id、repository、branch、
  commit SHA 和状态，并要求成功 run 的 commit 与待发布 commit 精确一致。
- Webhook 在解析 JSON 前验证原始请求体签名，使用常量时间比较并拒绝空 secret/
  空签名；保存 `X-Gitea-Delivery` 以审计 delivery attempt，同时以 repository、
  workflow run/job id、event action/status、head SHA 和 provider updated time
  建立状态幂等，重复事件返回已有处理结果。
- Release candidate 只接受已完成 run 的服务端报告和 artifact manifest；HTTP
  请求成功不等价于 CI 成功。
- host 模式 runner 和挂载 Docker socket 都不提供隔离，且 Docker socket 具备
  root 级主机能力；M7 不把 runner 与远端部署执行器部署在同一权限边界。

### 排除结论

- 不把 webhook payload、分支名、tag 或可变 artifact 名单独视为可信发布证据。
- 不把 runner registration token、Gitea Token 或 webhook secret 下发给 Agent、
  Tool Gateway、控制台或部署请求。
- 不在 M7 自研 CI runner、workflow engine 或通用 Gitea Actions 兼容层。

## 2. Git 远端、精确 ref 推送与 commit 校验

### 官方链接

- [`git remote`](https://git-scm.com/docs/git-remote)
- [`git push`](https://git-scm.com/docs/git-push)
- [`git ls-remote`](https://git-scm.com/docs/git-ls-remote)
- [`git rev-parse`](https://git-scm.com/docs/git-rev-parse)

### 适用子任务

- `7.2` 将 M6 本地 commit 推送为真实 CI 输入。
- `7.8` 生成绑定精确 commit 的 ReleasePlan。
- `7.10` 校验远端 CI run 与本地提交的一致性。

### 摘要

- Git remote 保存远端名称和 fetch/push URL；`git push` 的 refspec 明确指定源
  object/ref 与目标 ref，默认拒绝非 fast-forward 更新。
- `git ls-remote` 从远端读取 ref 与 object id，可用于推送后的远端 commit
  校验；`git rev-parse` 可将本地 ref 解析为完整 object id。

### 采用结论

- Git 工具只使用服务端配置的 remote；推送前解析完整 commit SHA，使用显式
  `<commit>:refs/heads/<controlled-branch>` refspec，且不启用 force。
- 推送后通过 `git ls-remote --refs` 读取目标 ref，并要求返回 object id 与
  本地完整 commit SHA 完全相等后才能触发 CI。
- ReleasePlan、审批 request hash、CI run 和 Deployment 全部保存同一完整
  commit SHA；短 SHA 只用于界面显示。

### 排除结论

- 不使用 `--force`、`--force-with-lease`、`--mirror`、`--all` 或隐式推送默认
  分支。
- 不允许 API、Agent 或控制台传入 remote URL、任意 refspec 或目标默认分支。
- 不通过本地 branch 名或“push 命令退出码为 0”替代远端 ref 校验。

## 3. Docker Buildx、OCI digest、SBOM、provenance 与 Registry

### 官方链接

- [`docker buildx build`](https://docs.docker.com/reference/cli/docker/buildx/build/)
- [Build attestations](https://docs.docker.com/build/metadata/attestations/)
- [SBOM attestations](https://docs.docker.com/build/metadata/attestations/sbom/)
- [Provenance attestations](https://docs.docker.com/build/metadata/attestations/slsa-provenance/)
- [`docker buildx imagetools inspect`](https://docs.docker.com/reference/cli/docker/buildx/imagetools/inspect/)
- [`docker image push`](https://docs.docker.com/reference/cli/docker/image/push/)
- [`docker image pull`](https://docs.docker.com/reference/cli/docker/image/pull/)

### 适用子任务

- `7.2` 构建并推送真实 release image、测试报告和 CI artifact manifest。
- `7.3`、`7.8` 定义并验证 image ref、digest、SBOM/provenance 证据。
- `7.5`、`7.6` 远端拉取并按 digest 部署镜像。

### 摘要

- Buildx 支持 `--push`、`--metadata-file`、`--sbom` 和 `--provenance`；SBOM 与
  provenance 作为 OCI attestation 与镜像结果关联。
- Registry tag 是可变引用；OCI index digest、平台 manifest digest 和 image
  config digest 分别标识多平台索引、单平台 manifest 与镜像配置，不能互换。
  `imagetools inspect` 可读取 registry 中 index/manifest 的名称、media type、
  digest 和平台清单；本地 image id 或容器 `.Image` 字段不等同于 registry digest。
- `docker image pull` 和 Compose 可使用 `name@sha256:<digest>` 拉取固定内容。

### 采用结论

- CI 使用 Buildx 构建并直接 push 到受控 registry，同时生成 SBOM、provenance
  和 metadata；CI artifact manifest 分别保存 image repository、index digest、
  目标平台 manifest digest、platform、报告 hash 和源 commit。
- Release candidate 与审批使用 `repository@sha256:<digest>`；部署前由 CI
  provider 和 Deployment Controller 分别校验 manifest digest。
- Remote Agent 只拉取 ReleasePlan 中已审批的 digest；部署前后通过 registry
  manifest、`RepoDigests` 和目标平台信息复核实际内容，不使用容器 image id、
  config digest 或日志文本替代审批绑定的 registry digest。

### 排除结论

- 不以 tag、构建日志中的文本或本地 image id 作为审批和部署身份。
- 不在远端 staging 主机构建镜像，不允许 Compose 模板包含 `build:`。
- M7 不自建 registry、签名系统或通用制品仓库；现阶段保存并核验 digest、
  SBOM、provenance 和报告证据，不把“已生成 provenance”等同于供应链签名。

## 4. Docker Compose 验证、拉取、启动、健康与安全配置

### 官方链接

- [`docker compose config`](https://docs.docker.com/reference/cli/docker/compose/config/)
- [`docker compose pull`](https://docs.docker.com/reference/cli/docker/compose/pull/)
- [`docker compose up`](https://docs.docker.com/reference/cli/docker/compose/up/)
- [Compose project name and top-level `name`](https://docs.docker.com/reference/compose-file/version-and-name/)
- [Compose services](https://docs.docker.com/reference/compose-file/services/)

### 适用子任务

- `7.5` Remote Agent Compose 执行与安全校验。
- `7.6` Deployment Controller 渲染固定 digest 的 manifest。
- `7.11` staging Compose 模板、release 目录和部署 E2E。

### 摘要

- `docker compose config` 负责解析、合并、变量展开和规范化 Compose 模型；
  `pull` 拉取服务镜像；`up -d` 创建或重建并后台启动服务。
- Compose project name 隔离同一主机上的项目资源；service 定义支持
  `healthcheck`、`read_only`、`cap_drop`、`security_opt`、资源限制、网络、
  volume、PID/IPC 和 device 等配置。

### 采用结论

- 每次部署先对渲染结果执行 `docker compose -p <controlled-name> config`，
  再对规范化模型执行 CloudHelm policy 校验，之后依次 `pull`、`up -d`、
  `ps` 和 HTTP `/health`。
- 固定目标机 Compose patch 版本；可使用 `up -d --wait --wait-timeout` 等待
  Compose health，但仍执行独立 HTTP `/health`。对 CPU、memory、pids 等限制在
  部署后通过容器 inspect 验证，不只相信可能被运行时忽略的 Compose 字段。
- Compose project name 由服务端根据 project/environment 生成并持久化；不接受
  请求方覆盖。
- 模板使用固定 digest、健康检查、最小 capability、只读文件系统和资源上限；
  只允许受控 named volume 与受控 release 目录。

### 排除结论

- 拒绝 `privileged`、host network、host PID/IPC、Docker socket、任意 device、
  危险 capability 和受控根目录外 host bind mount。
- 不接受调用方上传任意 Compose、project name、env 文件路径或命令参数。
- 健康失败时保存诊断和 rollback candidate，不在 M7 自动回滚或删除命名卷。

## 5. FastAPI 认证、流式响应、请求大小与长操作边界

### 官方链接

- [FastAPI Dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/)
- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)
- [FastAPI Background Tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/)
- [Starlette Requests](https://www.starlette.io/requests/)
- [Starlette Responses](https://www.starlette.io/responses/)

### 适用子任务

- `7.5` Remote Agent 认证、部署 API、日志与 operation 查询。
- `7.10` Platform API 心跳、Webhook 和远端发布工作流。
- `7.12` 控制台 SSE、远端日志和状态展示。

### 摘要

- FastAPI dependency 可集中执行认证、权限和请求上下文校验；Starlette Request
  支持按流读取 body，`StreamingResponse` 支持迭代式响应。
- FastAPI `BackgroundTasks` 适合请求完成后的较小进程内任务；官方文档建议重型、
  跨进程任务使用独立执行机制。
- FastAPI/Starlette 文档没有提供一个覆盖所有部署方式的声明式全局 body size
  配置，应用边界仍需结合请求头、流式读取上限和入口代理限制。

### 采用结论

- Remote Agent 和 Platform API 使用 dependency 统一完成认证、时间戳/重放、
  target capability 与 audit context 校验，路由不自行复制认证逻辑。
- 对 Webhook、manifest 和部署请求同时检查 `Content-Length` 与实际流式读取字节
  数，超过上限立即终止；日志按行数、时间范围和总字节上限流式返回。
- 部署是持久化 operation：API 快速返回 operation id，调用方查询状态；不把
  Compose/HTTP health 长操作隐藏为无持久化的 `BackgroundTasks`。

### 排除结论

- 不把认证信息放入 query string、事件正文、SSE payload 或日志。
- 不提供任意大请求、无限日志流、任意文件下载或交互式远端终端。
- 不使用单进程内 BackgroundTasks 充当可恢复部署队列。

## 6. HTTPX TLS、连接池、超时与流式下载

### 官方链接

- [SSL](https://www.python-httpx.org/advanced/ssl/)
- [Timeouts](https://www.python-httpx.org/advanced/timeouts/)
- [Resource Limits](https://www.python-httpx.org/advanced/resource-limits/)
- [Streaming Responses](https://www.python-httpx.org/quickstart/#streaming-responses)
- [Async Support](https://www.python-httpx.org/async/)

### 适用子任务

- `7.6` Deployment Controller 调用 Remote Agent。
- `7.10` Platform API 调用 Gitea、CI artifact 和远端 operation API。
- `7.7` Tool Gateway 查询 CI 日志和 artifact manifest。

### 摘要

- HTTPX 默认校验证书，可用受控 `SSLContext` 配置 CA；timeout 分为 connect、
  read、write、pool，连接池通过 limits 限制连接数和 keep-alive。
- 流式接口允许逐块消费响应，避免把未知大小内容一次性载入内存；调用方负责关闭
  streaming response。

### 采用结论

- 每个外部 provider 复用有界 `Client`/`AsyncClient`，配置明确的四类 timeout、
  连接数、keep-alive、`trust_env=False` 和受控 CA；默认保持 TLS hostname/
  证书验证并禁止 redirect。确需 redirect 时只允许同源或服务端 allowlist 目标，
  每一跳重新执行 scheme/host/port 校验。
- artifact、日志和诊断使用 streaming，累计字节达到上限即停止并返回结构化
  size-limit 错误；响应关闭由 context manager 保证。
- 网络超时后使用同一 idempotency key 查询现有 CI/Remote Agent operation，
  不直接重发部署副作用。

### 排除结论

- 不设置 `verify=False`，不读取进程代理/CA 环境变量，不信任调用方传入 CA 路径、
  proxy、URL 或 redirect 目标。
- 不使用无限 timeout、无限连接池、无限响应缓冲或自动无限重试。
- 不在请求/响应日志中记录 Authorization、Cookie、签名、env profile 内容或
  registry 凭据。

## 7. SQLAlchemy 2.x 行锁、短事务与并发幂等

### 官方链接

- [`Select.with_for_update()`](https://docs.sqlalchemy.org/en/20/core/selectable.html#sqlalchemy.sql.expression.Select.with_for_update)
- [Transactions and Connection Management](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html)
- [Session Basics](https://docs.sqlalchemy.org/en/20/orm/session_basics.html)

### 适用子任务

- `7.4` M7 数据模型、唯一约束与状态索引。
- `7.7` 审批恢复和 waiting ToolCall 原子抢占。
- `7.9`、`7.10` CI、ReleasePlan、Deployment 的并发状态推进。

### 摘要

- SQLAlchemy `with_for_update()` 生成数据库行锁语义；Session transaction
  管理 commit、rollback 和 savepoint 边界。
- 数据库事务只保护数据库状态；HTTP、Git、Docker、SSH 等外部副作用不会随
  数据库 rollback 自动撤销。

### 采用结论

- claim/resume 事务使用行锁、状态条件更新和唯一约束，提交 running/claimed
  状态后才调用外部系统。
- 外部调用结束后在新短事务中写结果、事件和证据；超时通过稳定 idempotency key
  查询已有 operation，不在持锁事务内盲目重试。
- `deployment_id + idempotency_key + request_hash`、CI delivery id、审批
  request hash 和活动状态索引共同阻止双执行与请求漂移。

### 排除结论

- 不在数据库事务或 `SELECT ... FOR UPDATE` 锁持有期间等待 CI、HTTP、Docker、
  SSH 或 LLM。
- 不依赖进程内锁作为多进程/多实例唯一并发控制。
- 不因网络异常删除已提交 Artifact、ReleasePlan、Deployment 或 operation
  证据。

## 8. Alembic 多表、约束、索引、downgrade 与 schema 检查

### 官方链接

- [Operation Reference](https://alembic.sqlalchemy.org/en/latest/ops.html)
- [Running the Second Migration and Downgrade](https://alembic.sqlalchemy.org/en/latest/tutorial.html#running-our-second-migration)
- [`alembic check`](https://alembic.sqlalchemy.org/en/latest/api/commands.html#alembic.command.check)
- [Autogeneration](https://alembic.sqlalchemy.org/en/latest/autogenerate.html)

### 适用子任务

- `7.4` 创建 M7 多表 migration、约束和索引。
- `10` 验证 downgrade、upgrade、head 和 metadata 一致性。

### 摘要

- Alembic operation API 支持表、外键、检查约束、唯一约束和索引；revision
  必须明确 upgrade/downgrade 顺序。
- `alembic check` 使用 autogenerate 比较数据库与 metadata，发现尚需生成的
  schema operation；autogenerate 结果仍需人工复核。

### 采用结论

- M7 migration 使用显式名称创建表、外键、检查约束、部分唯一索引和查询索引；
  downgrade 按依赖反序删除。
- 在真实 PostgreSQL 上执行 M6 head 到 M7 head 的 upgrade、M7 downgrade 回
  M6、再次 upgrade 和 `alembic check`。
- 对数据库无法表达的跨表归属、hash 绑定和状态语义继续在 service/policy 层
  校验。

### 排除结论

- 不把未经人工检查的 autogenerate 文件直接视为最终 migration。
- 不在 migration 中执行外部 HTTP、镜像拉取、真实部署或凭据迁移。
- 不为通过测试省略 downgrade、约束名、索引或真实 PostgreSQL 验证。

## 9. systemd 专用用户、权限与 service hardening

### 官方链接

- [systemd `systemd.exec` source](https://github.com/systemd/systemd/blob/main/man/systemd.exec.xml)
- [systemd `systemd.service` source](https://github.com/systemd/systemd/blob/main/man/systemd.service.xml)

### 适用子任务

- `7.11` Remote Agent 安装脚本、环境文件和 systemd unit。
- `7.5` operation store、release 目录和日志运行边界。

### 摘要

- `systemd.exec` 提供 `User`、`Group`、`UMask`、`EnvironmentFile`、
  `ProtectSystem`、`PrivateTmp`、`NoNewPrivileges`、`ReadWritePaths`、
  `StateDirectory` 等执行与 sandbox 配置。
- `systemd.service` 提供启动类型、超时、退出行为、`Restart` 与
  `RestartSec`；重启策略不能替代应用幂等和持久化 operation。

### 采用结论

- Remote Agent 使用专用 staging 用户和组。secret 优先通过 systemd
  `LoadCredential=` / `LoadCredentialEncrypted=` 或应用 `_FILE` 配置读取；
  普通 `Environment=` / `EnvironmentFile=` 仅保存非敏感配置，不传递密码、
  Token 或私钥。
- 设置 `UMask=0077`、`PrivateTmp=true`、`NoNewPrivileges=true`、
  `ProtectSystem=strict` 和精确 `ReadWritePaths`；只开放 operation store、
  受控 release/project 根和必要运行目录，并通过 `systemd-analyze verify`
  验证 unit。
- 使用有界启动/停止超时和失败重启间隔；进程重启后从 SQLite operation store
  恢复查询语义。

### 排除结论

- 不以 root 运行 Remote Agent，不在 unit、命令行、journal 或 README 写入
  secret。
- 不给予受控目录之外的通用写权限，不启用交互 shell、TTY 或任意命令入口。
- Docker socket 边界会显著削弱 systemd sandbox；文档必须明确该限制，不能用
  hardening 选项宣称获得完整隔离。

## 10. Linux Docker socket 权限与 staging allowlist

### 官方链接

- [Linux post-installation steps for Docker Engine](https://docs.docker.com/engine/install/linux-postinstall/)
- [Docker Engine security](https://docs.docker.com/engine/security/)
- [Protect the Docker daemon socket](https://docs.docker.com/engine/security/protect-access/)

### 适用子任务

- `7.5` Remote Agent Compose adapter 和命令 allowlist。
- `7.11` staging 用户、Docker 权限、安装与安全说明。

### 摘要

- Docker 官方文档明确指出 `docker` group 提供 root-level privileges；能够访问
  daemon socket 的进程可创建高权限容器并操作主机资源。
- Docker daemon 远程访问需要 TLS 或 SSH 等保护；未经保护的 TCP socket 会把
  主机控制能力暴露给网络调用方。

### 采用结论

- M7 Remote Agent 仅部署于 staging/demo 专用主机和专用用户；将 Docker socket
  视为 L3/L4 高权限边界并写入部署、安全和答辩文档。
- Remote Agent 只暴露固定 Compose profile、service status、受限日志和只读
  diagnostics；所有 subprocess 使用参数数组、超时、输出上限和审计。
- Compose policy 在调用 daemon 前拒绝高权限配置；Platform API、控制台和
  Release / Deploy Agent 均不能传自由命令。

### 排除结论

- 不把 Docker socket 挂入被部署服务，不开放未保护 daemon TCP API。
- 不把 Remote Agent 扩展为通用 Docker 管理面、任意 shell、交互终端或生产
  主机 Agent。
- 不把“专用用户”描述为消除了 Docker socket 的 root-level 风险。

## 11. OpenAPI / JSON Schema 跨服务契约与兼容演进

### 官方链接

- [OpenAPI Specification 3.1.2](https://spec.openapis.org/oas/v3.1.2.html)
- [Latest OpenAPI Specification](https://spec.openapis.org/oas/latest.html)
- [JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12)
- [JSON Schema Core](https://json-schema.org/draft/2020-12/json-schema-core.html)
- [JSON Schema Validation](https://json-schema.org/draft/2020-12/json-schema-validation.html)

### 适用子任务

- `7.3` 扩展 Agent、CI、部署和远端共享契约。
- `7.5`、`7.6` Remote Agent 与 Deployment Controller DTO。
- `7.10`、`7.13` OpenAPI、JSON Schema、README 和版本同步。

### 摘要

- OpenAPI 3.1 的 Schema Object 基于 JSON Schema Draft 2020-12 vocabularies；
  OpenAPI 文档中的 operation、security、request/response 和 component 引用共同
  描述 HTTP 契约。
- 截至检索日，OpenAPI 最新发布线已进入 3.2；CloudHelm 当前 FastAPI/OpenAPI
  生成链仍以 3.1.x 语义和 Draft 2020-12 JSON Schema 为兼容基线。

### 采用结论

- 所有跨服务请求、响应、事件和工具输出先定义 Pydantic/typed contract，再生成
  OpenAPI/JSON Schema；仓库中的共享 schema 与运行时 DTO 做精确一致测试。
- 新增字段优先保持可选或提供默认值；枚举、required、状态含义、hash 算法和
  idempotency 语义变化必须记录兼容性与项目版本影响。
- Platform API 与 Remote Agent 分别导出 OpenAPI，并对 Deployment Controller
  使用的 schema 做 contract test。

### 排除结论

- M7 不为追逐最新规范单独升级到 OpenAPI 3.2；只有生成器、前端类型链和全部
  contract test 验证后才另行升级。
- 不维护与运行时模型分离的手写重复 schema，不允许控制台自行猜测状态字段。
- 不把 JSON Schema meta-valid 等同于跨服务行为兼容；还需验证示例、错误、
  required 集合、枚举和状态流转。

## 12. SSH host key、密钥权限与只读诊断

### 官方链接

- [`ssh_config(5)`](https://man.openbsd.org/ssh_config)
- [`ssh(1)`](https://man.openbsd.org/ssh.1)
- [`sshd(8)`](https://man.openbsd.org/sshd.8)

### 适用子任务

- `7.7` `remote.ssh_exec_readonly`。
- `7.11` 远端主机预检、SSH 配置和诊断说明。

### 摘要

- OpenSSH client 通过 `StrictHostKeyChecking` 和 `UserKnownHostsFile` 控制主机
  身份校验；`IdentityFile`、`IdentitiesOnly` 与 `BatchMode` 控制客户端身份和
  非交互行为。
- OpenSSH 会拒绝其他用户可访问的私钥文件；host key 变化必须作为身份异常处理，
  不能静默接受。

### 采用结论

- M7 只接受服务端 RemoteTarget 中配置的 host、port、user、known-hosts 记录和
  identity path；使用 `StrictHostKeyChecking=yes`、专用
  `UserKnownHostsFile`、`IdentitiesOnly=yes`、`BatchMode=yes`、`-T` 与
  `ClearAllForwardings=yes`。
- 私钥和 known-hosts 文件由运维预置，私钥权限为 `0600`；API、Agent、控制台和
  数据库只保存引用或 fingerprint，不返回密钥内容。
- SSH 仅执行 `docker_ps`、`compose_ps`、`disk_usage`、`systemd_status` 等服务端
  固定 diagnostic profile，并记录 profile、target、exit code、输出摘要和审计
  id。
- 远端 `authorized_keys` 使用 `restrict`、forced `command=` wrapper，显式关闭
  PTY、agent/X11/TCP forwarding 和 user rc；需要特权的 Docker/systemd 诊断由
  root-owned 固定 wrapper 与精确 sudoers 提供。加入 docker group 的账号仍是
  root 级权限边界，不能仅因命令名受限而描述为只读账号。

### 排除结论

- 不使用 `StrictHostKeyChecking=no`、自动接受新 host key 或调用方提供
  known-hosts/identity 路径。
- 不开放自由 command、shell 字符串、交互会话、端口转发、SCP/SFTP 或写操作。
- 正常部署只走 Remote Agent；SSH 仅为按策略启用的只读诊断补充链路。

## 13. Celery + Redis 投递、ack、worker 与业务幂等

### 官方链接

- [Celery Tasks](https://docs.celeryq.dev/en/stable/userguide/tasks.html)
- [Celery Optimizing](https://docs.celeryq.dev/en/stable/userguide/optimizing.html)
- [Celery Workers](https://docs.celeryq.dev/en/stable/userguide/workers.html)
- [Celery Redis broker/backend](https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html)
- [Redis security](https://redis.io/docs/latest/operate/oss_and_stack/management/security/)

### 适用子任务

- `7.0` M7 长任务执行器与 stale reclaim。
- `7.4` `workflow_jobs`、lease、heartbeat 和重试字段。
- `7.9` CI、远端部署和健康检查的异步状态推进。

### 摘要

- Celery 支持 late acknowledgement、worker prefetch、task time limit、retry 和
  worker shutdown；broker delivery 可能重复，task 必须按幂等方式设计。
- Redis 负责消息投递和短期队列状态，不替代 PostgreSQL 业务事实；Redis 网络、
  ACL、认证和持久化必须按受控环境配置。

### 采用结论

- `modules/workflow-engine` 使用 Celery + Redis；task payload 只携带
  `workflow_job_id`，业务请求、request hash、attempt、lease 和结果保存在
  PostgreSQL。
- worker 使用 `acks_late`、有界 prefetch、显式软/硬超时；开始外部副作用前先
  以短事务 claim job，网络调用完成后使用新事务写终态。
- retry 前先查询 Gitea workflow run 或 Remote Agent operation；未知远端状态
  进入 `recovery_required`，不盲目重复 push、build 或 deploy。

### 排除结论

- 不把 Celery task id、Redis message 或进程内锁当成业务幂等身份。
- 不把 secret、任意 URL、Compose 内容、SSH 命令或 registry credential 放入
  broker payload。
- 不实现自研队列、无限自动重试或在数据库行锁事务中等待 Celery/HTTP/Docker。
