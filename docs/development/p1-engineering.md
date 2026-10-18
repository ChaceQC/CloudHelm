# Git、工作区与受限构建开发

本文对应 [P1.2 实施说明](../implementation/p1-2-engineering.md)。本轮工程链路正在接续实施，实际可用范围以 [P1.2 证据索引](../acceptance/p1/p1-2.md) 为准。Hub 的身份、数据库和进程入口见 [Hub 开发说明](p1-hub.md)。

## 1. 当前基线与隔离范围

本机开发环境是 WSL `Ubuntu-24.04`，仓库路径 `/mnt/e/Project/CloudHelm`。Python `3.12.13`、uv `0.11.29` 和根 `uv.lock` 固定解释器与依赖；安装和运行在 WSL 内执行。

当前增量环境修正的开发源码为 `0.3.0`，DBOS 工作流应用为 `cloudhelm-hub/0.3.0`，新增业务迁移从 `0003_p1_2_builds` 线性前进。仅为本轮准备新隔离开发库；旧版安装必须另行完成受控升级，`database.manage initialize` 会拒绝版本不匹配的现有安装。

工作文件、受管 Git 元数据、候选、下载缓存、制品和执行临时目录具有独立位置与用途。受控运行数据放在 Linux 原生私有目录，不能放在 `/mnt/e` 的仓库工作树内；配置仅传受保护文件引用，不向命令参数、日志或公开输出写入密钥。

## 2. 工程授权

工程动作必须显式授予：工作区写入为 `workspace.write`，候选提交为 `candidate.submit`，构建请求为 `operation.request`。它们受既有 P0 角色上界约束，通过现有项目角色管理事务授予 developer 绑定。

既有 owner、角色和 Agent 委托不会因软件升级自动获得新动作。owner 如需执行工程动作，同样需要显式 developer 绑定；旧角色与委托保存的动作列表保持原意。每次推进及原结果回读都核对当前授权，撤权后不能依赖旧成功回执继续操作。

## 3. 受控 Runner 能力检查

固定能力探针只接受维护操作 `probe_capabilities`，不接收 Task、项目、任意命令、任意挂载或自报授权。它使用受限 rootless BuildKit，保留 process sandbox，以实际执行和宿主进程证据判断能力。

```bash
cd /mnt/e/Project/CloudHelm
/home/cloudhelm/.local/bin/uv run --frozen --no-sync python -m scripts.p1.probe_runner
```

探针在私有运行目录保存原操作、InputSet 和报告；公开输出只含有界事实与固定错误类别。失败按原操作核对，不使用 privileged、关闭 process sandbox 或挂入宿主 Docker socket 绕过限制。探针仅覆盖其固定限额，真实构建与制品加载需要各自的容量证据。

## 4. 工程入口与本机注册

HTTP 工程命令由现有身份与 Task 门禁保护；API 只在业务事务中登记意图并向 DBOS 入队，单 worker 执行原操作。`engineering` 队列的 worker/global 并发均为 1。Git、文件和容器调用在事务提交后发生；查询原操作与重新执行分别处理，未知结果不盲目重建。

|用途|HTTP 入口|
|---|---|
|导入固定参照、查询来源|`POST /api/projects/{project_id}/source-imports`；`GET /api/projects/{project_id}/source-imports/{operation_id}`|
|绑定真实来源及独立资产建立 Task|`POST /api/projects/{project_id}/reference-tasks`|
|创建、读取独立工作区|`POST /api/tasks/{task_id}/workspaces`；`GET /api/workspaces/{workspace_id}`|
|物化、修改、固定候选|`POST /api/workspaces/{workspace_id}/materialize`、`/files`、`/candidates`|
|读取操作与物理候选|`GET /api/workspaces/{workspace_id}/operations/{operation_id}`、`/candidates/{candidate_id}`|
|构建申请、读取业务结果|`POST /api/tasks/{task_id}/builds`；`GET /api/tasks/{task_id}/builds/{operation_id}`|

准确字段见 [HTTP 快照](../../packages/contracts/p1/hub-openapi.json)。修改入口只接受至多 32KiB UTF-8 单文件内容；请求包含 `request`（版本、路径、原内容与替换摘要）和 `content_utf8`，删除时内容为 null。内容在当前授权与版本预检后暂存到受控池，命令及 DBOS 只保留摘要与操作身份；正式接受时重新检查当前门禁。同键重投保留原请求，不用新键重放未知文件操作。

当前注册组合只支持固定便签参照和本机 UID 1000。`CLOUDHELM_ENGINEERING_REGISTRY_FILE` 指向 `0600` 的无秘密 UTF-8 JSON，包含实际维护创建的 `DevelopmentStorageRef` 及固定种子引用；API 的文件暂存与 worker 使用同一注册。公共请求不能选择宿主路径、Git 子命令或 Docker 参数。缺少注册、只读种子、当前挂载或实例修订不符时，执行入口明确拒绝。

开发存储采用专用、完整分配的 loop/ext4 文件系统，Git、工作文件、候选、缓存和归档共用一个有界实例及排他准入。用途目录保持独立，候选与工作区共用一致性锁。操作全程持有实际准入，停止进程不等于释放保留字节；卸载和删除只有核对后才能清理本实例。维护包装核验 Docker daemon 身份并进入其挂载命名空间创建本项目专用池；消费者保持同一视图，Docker 使用受管路径，目录 FD 全程保持打开并在容器内核对 dev/ino。

前后端构建固定配方、锁、Linux/amd64 工具链和已核验下载物；沙箱断网、使用私有可写缓存。BuildRun 保存 frontend/backend/postgres 三角色归档，内容核验与真实执行终结、加载身份分别登记。Docker 29 containerd 的实际 image ID 为 manifest digest，OCI config digest 单独保留。环境运行固定镜像，不将源码交给目标临时构建。

## 5. 定向开发验证

完整工程方法使用新临时数据库、维护生成的短期身份、真实 HTTP 与单 worker，随后运行独立参照 HTTP 资产。存储维护包装只对本项目新实例操作；需要本机 root 维护权限以创建/回收专用文件系统和环境父 cgroup，应用与方法主体仍使用 UID 1000。

```powershell
wsl -d Ubuntu-24.04 -u root --cd /mnt/e/Project/CloudHelm -- .venv/bin/python -B -m scripts.p1.engineering_storage_fixture --development
```

`--development` 明确表示未固定工作树；`--through-candidate` 仅供有关 Git/HTTP/worker 问题的窄验证。正式固定候选使用 `--input-set docs/acceptance/p1/input-set-p1-2-r1.json`，代替 `--development`；方法核对运行前后的公共输入。失败或停止未知时保留原身份与阻断，不重启另一套物理操作覆盖原结果。实际记录见 [P1.2 证据索引](../acceptance/p1/p1-2.md)，不要把命令示例当作已通过结论。

## 6. 当前限制

当前低层 Git 仅支持经受控登记的 managed bare 与独立工作文件；外部认证、LFS、submodule、完整 Git 模式和来源迁移按明确限制拒绝。Git OID 与内容 SHA-256 分别保存，初始文件回执不能表示可变工作区当前状态。

工作区命令、固定候选、离线依赖与构建、BuildRun 内容及执行记录已提供源码；完整 worker 链路与制品运行的适用结论以固定输入证据为准。完整共享宿主资源协议、Release、远端部署、Desktop 和人工验收按后续工作包交付。
