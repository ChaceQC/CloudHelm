# Git、工作区与受限构建开发

本文对应 [P1.2 实施说明](../implementation/p1-2-engineering.md)。工程入口、支持组合和验证范围以 [P1.2 证据索引](../acceptance/p1/p1-2.md) 为准。Hub 的身份、数据库和进程入口见 [Hub 开发说明](p1-hub.md)。

## 1. 当前基线与隔离范围

本机开发环境是 WSL `Ubuntu-24.04`，仓库路径 `/mnt/e/Project/CloudHelm`。Python `3.12.13`、uv `0.11.29` 和根 `uv.lock` 固定解释器与依赖；安装和运行在 WSL 内执行。

环境口径：s2413 是用户选定的临时同机组合，现有快照只证明采集时的系统事实；实际安装、配额生效和运行验证分别取证。WSL 结果不能替代这些证据，正式独立目标仍是 P1.4/P1 出口前置。具体方案见 [开发组合决定](../decisions/p0/s2413-development-envelope.md)，分类结果见 [支持矩阵](../acceptance/support-matrix.md)。

当前开发源码为 `0.4.0`，DBOS 工作流应用为 `cloudhelm-hub/0.4.0`，业务迁移 head 为 `0005_p1_3_resources`（从 `0004_p1_2_development` 线性前进）。旧版安装必须另行完成受控升级，`database.manage initialize` 会拒绝版本不匹配的现有安装。P1.2 历史固定候选仍按原版本与证据适用；本轮资源子系统与隔离范围见[共享资源说明](p1-resources.md)。

工作文件、受管 Git 元数据、候选、下载缓存、制品和执行临时目录具有独立位置与用途。受控运行数据放在 Linux 原生私有目录，不能放在 `/mnt/e` 的仓库工作树内；配置仅传受保护文件引用，不向命令参数、日志或公开输出写入密钥。

## 2. 工程授权

工程动作必须显式授予：工作区写入为 `workspace.write`，候选提交为 `candidate.submit`，构建请求为 `operation.request`。它们受既有 P0 角色上界约束，通过现有项目角色管理事务授予 developer 绑定。

既有 owner、角色和 Agent 委托不会因软件升级自动获得新动作。owner 如需执行工程动作，同样需要显式 developer 绑定；旧角色与委托保存的动作列表保持原意。每次推进及原结果回读都核对当前授权，撤权后不能依赖旧成功回执继续操作。

## 3. Runner 检查与历史方法

历史固定能力探针入口 `scripts.p1.probe_runner` 已移除。构建运行实际依赖的 Runner、工具链与隔离代码继续保留；其已取得的能力记录仍按原候选和固定环境适用。

日常检查见[精简验证入口](checks.md)。需要复现原 rootless BuildKit 能力或构建实验时，在[原提交独立检出](p0-seams.md#取回历史方法)中使用当时的完整方法；不以静态检查代替物理执行证据。

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
|可变开发环境申请、读取状态|`POST /api/workspaces/{workspace_id}/development-environments`；`GET /api/development-environments/{environment_id}`|
|环境操作与生命周期|`GET /api/development-environments/{environment_id}/operations/{operation_id}`；`POST /api/development-environments/{environment_id}/suspend`、`/resume`、`/reset-data`、`/dispose`|

固定参照 Task 的独立检查项由 [版本化目录](../acceptance/reference/README.md) 登记：加载器核验固定目录摘要、50 个唯一 ID、脚本/方法及 bundle 绑定，直接生成既有 AcceptanceMetadata，不再用运行时 AST 推导。当前公开资产修订为 `reference-public-assets-r2`，将既有 README 摘要变化显式登记；目录本身纳入新 bundle，创建新的工程引用与 Task InputSet，旧记录及通过结果不自动适用新输入。该入口只登记方法，实际执行结果仍须另行绑定；旧冻结 InputSet 与 `r1/` 文件保持原字节。

准确字段见 [HTTP 快照](../../packages/contracts/p1/hub-openapi.json)。修改入口接受至多 48KiB UTF-8 单文件内容，完整 JSON 请求仍受 64KiB 限制；请求包含 `request`（版本、路径、原内容与替换摘要）和 `content_utf8`，删除时内容为 null。内容在当前授权与版本预检后暂存到受控池，命令及 DBOS 只保留摘要与操作身份；正式接受时重新检查当前门禁。同键重投保留原请求，不用新键重放未知文件操作。

当前注册组合只支持固定便签参照和本机 UID 1000。`CLOUDHELM_ENGINEERING_REGISTRY_FILE` 指向 `0600` 的无秘密 UTF-8 JSON，包含实际维护创建的 `DevelopmentStorageRef` 及固定种子引用；API 的文件暂存与 worker 使用同一注册。公共请求不能选择宿主路径、Git 子命令或 Docker 参数。缺少注册、只读种子、当前挂载或实例修订不符时，执行入口明确拒绝。

开发存储采用专用、完整分配的 loop/ext4 文件系统，Git、工作文件、候选、缓存和归档共用一个有界实例及排他准入。用途目录保持独立，候选与工作区共用一致性锁。操作全程持有实际准入，停止进程不等于释放保留字节；卸载和删除只有核对后才能清理本实例。维护包装核验 Docker daemon 身份并进入其挂载命名空间创建本项目专用池；消费者保持同一视图，Docker 使用受管路径，目录 FD 全程保持打开并在容器内核对 dev/ino。

验证与收尾期间保持 WSL 发行版运行。发行版退出或挂载命名空间变化后，先按原实例注册、backing 身份和容器引用核对存储；目录仍在不代表专用文件系统仍挂载，不能直接另建操作覆盖原记录。

前后端构建固定配方、锁、Linux/amd64 工具链和已核验下载物；沙箱断网、使用私有可写缓存。BuildRun 保存 frontend/backend/postgres 三角色归档，内容核验与真实执行终结、加载身份分别登记。Docker 29 containerd 的实际 image ID 为 manifest digest，OCI config digest 单独保留。环境运行固定镜像，不将源码交给目标临时构建。

### 4.1 固定依赖种子准备

在启动工程 worker 前，由可信维护者以 WSL 本机 `cloudhelm` 用户（UID 1000）执行以下命令。入口只准备固定便签参照，不接受自定义下载源、工具命令或宿主目标目录；不经 HTTP 开放。它不读取供应商或应用配置，输出只包含无秘密的内容身份、摘要、数量、字节和复用状态。

```bash
cd /mnt/e/Project/CloudHelm
.venv/bin/python -B -m services.dev-runner.engineering_seed_maintenance prepare
.venv/bin/python -B -m services.dev-runner.engineering_seed_maintenance verify
```

`prepare` 可在没有任何历史探针目录的环境运行。npm 仅从固定锁指定的 `registry.npmjs.org` 匿名 HTTPS 下载，Python/uv 仅从固定的 `files.pythonhosted.org` wheel 地址下载；拒绝重定向，沿用既有大小、时限与摘要校验。完成后先校验只读暂存内容，再原子发布到固定身份；重复准备核验并复用，不重新下载。已存在的损坏内容拒绝，不自动覆盖或隐式修复；维护者须先核对引用，再另行安排处置。

|注册引用|固定定位及内容身份|边界|
|---|---|---|
|`reference-notes-npm-r1`|`/home/cloudhelm/.local/state/cloudhelm/engineering-seeds/npm/<npm_seed_id(NpmDownloadSpec)>`；spec 固定项目 `reference-notes`、信任域 `controlled-development`、锁、平台及 npm 安装选项|119 个 tarball、122 个文件；tarball 合计至多 256MiB，另含固定输入及至多 1MiB 清单|
|`reference-notes-python-r1`|`/home/cloudhelm/.local/state/cloudhelm/python-dependency-seeds/<PythonDependencyInput.cache_key>`；保留现有项目/信任域、Python/uv、基镜像及锁身份|至多 32 个依赖 wheel，单下载至多 64MiB，含 uv 的最终种子至多 256MiB；只允许 wheel|

上述为逻辑下载/内容上限，不是物理磁盘配额。原有开发存储准入仍负责构建副本的实际占用；种子准备不会清理旧缓存、运行记录或 backing。下载中断遗留的私有暂存也需按原引用核对，不能直接清空整个目录。

构建按固定身份直达种子，只读核验，不扫描 `npm-check-*`，不调用准备命令，不因缺失或损坏而联网。种子复制到已准入开发存储后再次验证；构建固定实际副本的清单摘要。npm 清单的准备时间可不同，但锁、逐包来源/内容及其余清单字段必须一致，旧副本保持原字节与原摘要。Python 的固定路径和内容身份沿用现有规则，既有开发环境/快照消费者继续使用同一登记。

`verify` 不创建目录或下载；npm 缺失返回 `engineering_npm_seed_unavailable`，存在但校验失败返回 `engineering_npm_seed_invalid`。Python 缺失返回 `python_dependency_seed_unavailable`，损坏返回既有内容/边界错误或 `python_dependency_seed_invalid`；错误不会变成成功回执。

已有历史 npm 种子的机器可选择一次性导入，维护者须显式提供已核对的目录 ID：

```bash
.venv/bin/python -B -m services.dev-runner.engineering_seed_maintenance import-legacy --npm-probe-id npm-check-<32位小写十六进制ID>
```

入口只接受该 ID 格式，从原受控根下读取一个 `cache`，核对历史固定 manifest `sha256:1763287887271b7713a4d0764739b73bf592d37b6cab85535546d0b3f15c98d0`、锁与全部 tarball，复制后重新核验。Python 已按内容键定位，只验证并复用；缺失时先执行 `prepare`。已准备的新 npm 内容若等价则保留新副本，不覆盖其准备时间。导入不联网、不扫描、不删除原目录，重复执行复用同一内容。该历史 ID 只用于显式迁移，不再作为构建配置。

### 4.2 固定 Python wheel 清单

受支持组合为 `linux/amd64`、CPython `3.12.13`、uv `0.11.29` 和固定 Python 基础镜像。依赖闭包与 wheel 兼容性由该版本 uv 实际离线解析、安装及安装后 distribution 清单复核；运行时不再维护依赖遍历、marker、ABI 或 manylinux 筛选规则。

`infra/p1/reference-build/python-wheels.linux-amd64.r1.json` 固定 20 个 wheel 的名称、版本、文件名、公开来源、SHA-256 与大小，并绑定原始项目/锁/Python pin 摘要、平台、解释器、uv、基础镜像及安装参数。`python_dependencies.wheel_plan()` 有界读取并校验源码固定的清单摘要与全部输入身份，保留原返回字段和排序；缺失、损坏或目标身份不符直接拒绝。准备、构建、安装核验与 Workspace 快照共同消费该清单，构建不临时生成清单或联网补齐。

固定 uv 的公开 `export --format requirements-txt` 可复核依赖声明与 marker，但导出包含 Windows 条件项，且不提供目标 wheel 文件选择；不能把它当作 wheel 选择结果。此处采用经实际安装复核的固定清单，不依赖私有工具输出。变更锁、平台或工具链时，维护者须重新用目标工具链解析并安装、核对 wheel 来源/摘要/大小与安装集合，再评审新清单修订及其源码摘要；不能只改固定摘要使旧证据继续生效。

原始 `uv.lock` 保持原字节。现有受限 Linux 派生项目与 wheelhouse 离线锁配方继续保留，由 uv 处理语义并核对实际安装集合；本次不更改安装参数或配方身份。清单逐项等价时，既有种子内容键、种子 manifest 字节及 Workspace 原锁/固定注释变体的快照键均保持兼容；旧缓存与持久引用按原规则保留。

## 5. 定向开发验证

### 5.1 验证入口

当前保留 Git 文件视图、OCI 内容边界、数据库基础及独立参照 HTTP 检查，具体命令与范围见[精简验证入口](checks.md)。运行时存储维护仍调用的 `probe_development_storage` 保留。

原 `engineering_storage_fixture`、工程链、可变环境全方法、Task 控制与后端缓存重验脚本及专用夹具已移除；真实 HTTP/worker/构建、容器恢复和故障场景不再由当前常驻测试覆盖。[P1.2 退出摘要](../acceptance/p1/p1-2.md)保留结果和支持限制，原始输入与运行 JSON 从 Git 查询，完整方法按候选绑定[独立检出](p0-seams.md#取回历史方法)。新行为变化仍需相应新证据，不能以旧通过结果替代。

### 5.2 可变环境语义

可变环境当前只开放 `notes-backend-dev-r1`，固定 Python/uv、离线依赖、只读动态 Workspace 源码、私有安装快照、固定 Uvicorn reload 与独立 PostgreSQL 测试数据。源码继续经文件命令修改；环境 resume 重新绑定当前修订并实际探活，锁变化使旧私有安装键失效。suspend 保留合成数据与依赖快照，reset-data 使用获准数据修订重建并递增 generation；dispose 停止并核对运行资源，保留内容的磁盘占账单独记录。未知结果按原操作查询。

`reset-data` 请求的 `expected_data_revision`／`expected_data_generation` 使用最新观测的当前值，`target_data_revision` 单独指定获准目标。成功后观测目标修订，数据代次仅递增一次；相同操作身份的重投先查询原结果，不能再次清空数据或重复递增。

对仍运行的环境执行 resume 时，先确认旧后端停止，再准备当前依赖并重新启动、探活；已核对身份的 PostgreSQL 可继续运行以保留数据。休眠后的 resume 按原 prepare 身份发现资源并重新取得执行锁。依赖准备或停止核对失败时不报告 ready，应按原操作查询原因和物理状态。

正常 worker 关闭会按已登记身份停止其持有的开发服务并写入物理收尾记录，不代替用户提交 Hub suspend/dispose 命令；数据库中的 ready 是上次带时间戳的观测，worker 退出后使用者应显式 resume 重新准入和核验。异常退出后先按原操作与容器身份核对，不能凭进程内对象不存在就重建。当前开发入口不包含完整预览票据、用户访问流程或前端开发服务器。

### 5.3 已知限制

以下低层 Git 与能力边界来自当前实现与固定输入范围。

当前低层 Git 仅支持经受控登记的 managed bare 与独立工作文件；外部认证、LFS、submodule、完整 Git 模式和来源迁移按明确限制拒绝。Git OID 与内容 SHA-256 分别保存，初始文件回执不能表示可变工作区当前状态。

工作区命令、固定候选、离线依赖与构建、BuildRun 内容及执行记录已提供源码；完整 worker 链路与制品运行的适用结论以固定输入证据为准。完整共享宿主资源协议、Release、远端部署、Desktop 和人工验收按后续工作包交付。
