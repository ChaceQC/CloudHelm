# P0.1 组件与隔离环境基线

> 记录日期：2026-10-13（Asia/Shanghai）
> 首次环境诊断：2026-10-13T04:03:44.723695+00:00
> 依据：总体 v4.7；D01～D06 v4.7.0；PROJECT_PLAN.md P0.1-01
> 状态：隔离探测候选已安装、已锁定；逐能力兼容结论以六张 SDK 卡及接缝汇总为准。

## 1. 实际环境

|项|实际观测|范围|
|---|---|---|
|WSL|Ubuntu-24.04，Ubuntu 24.04.4 LTS；WSL2 x86_64|本机隔离开发，不替代独立 Linux 机器|
|内核|6.18.33.2-microsoft-standard-WSL2，glibc 2.39|不推定 rootless 构建、休眠检测或可信时钟误差支持|
|仓库|Windows `E:\Project\CloudHelm`；WSL `/mnt/e/Project/CloudHelm`|当前 dev；起始提交 c7da7fb423cf37a76fa11006e0986e2a572b052d|
|资源|WSL 可见内存 7531MiB、Swap 2048MiB；E 盘初始可用约 163GiB|不是 D03/D06 的 4 核 8GiB 平台容量验收|
|Docker|WSL 内 `/usr/bin/docker`，本地 Linux daemon；client/server 29.1.3|overlayfs、cgroup v2；不读取 Docker 配置或其他容器环境|
|Compose/Buildx/BuildKit|Compose 2.40.3+ds1-0ubuntu1~24.04.1；Buildx 0.30.1；默认 docker driver 的 BuildKit v0.26.2|Compose 接缝另取证；默认 builder 可检查不证明 rootless BuildKit 可用|
|Git/uv|Git 2.43.0；uv 0.11.29|系统 Git、uv 管理解释器和依赖|
|JS/Rust|PATH 中的 npm 11.6.2 来自 `/mnt/d/node-v24.13.0-win-x64/npm`；Linux node、rustc、cargo 当前不可调用|Windows npm 互操作不作为 WSL 工具链证据；P0.1 无前端/Rust 工程，Desktop 和参照构建入口未支持，后续实际工程再安装取证|

验证期间以单独的 `wsl.exe -d Ubuntu-24.04 --exec /bin/sleep infinity` 保持发行版存活。首次命令返回后发生过 WSL 收束和数据库容器 Exited(0)，恢复实验必须先确认本项目 PostgreSQL healthy；不能把发行版关闭误记为 DBOS worker 故障。

## 2. 版本、来源和许可

所有 Python 候选已读取 PyPI 版本元数据并完成 `uv sync`；下表锁定的是隔离工程版本，安装/导入成功不自动表示六卡行为通过。`uv.lock` 记录包括间接依赖在内的实际解析结果和制品哈希。

|组件|锁定版本|许可及可核实来源|复用边界|
|---|---|---|---|
|CPython|3.12.13|[PSF](https://docs.python.org/3/license.html)；uv 可下载解释器清单|不是从其他项目继承的版本|
|PydanticAI slim|2.55.0|MIT；[PyPI](https://pypi.org/project/pydantic-ai-slim/2.55.0/)、[DBOS 接入](https://ai.pydantic.dev/durable_execution/dbos/)|仅安装 openai/dbos extras；工具、历史和检查点逐卡核验|
|DBOS Python / DBOSClient|3.2.0|MIT；[PyPI](https://pypi.org/project/dbos/3.2.0/)、[事务入队接口](https://docs.dbos.dev/python/reference/client#enqueue_in_transaction)|公有接口接受同一 SQLAlchemy Connection/Session；不直接写内部表补事务保证|
|Pydantic|2.14.1|MIT；[PyPI](https://pypi.org/project/pydantic/2.14.1/)|契约校验不代替业务授权|
|SQLAlchemy|2.1.4|MIT；[PyPI](https://pypi.org/project/SQLAlchemy/2.1.4/)|同库短事务；兼容证据绑定 SDK-01|
|psycopg / binary|3.3.6|LGPL-3.0-only；[PyPI](https://pypi.org/project/psycopg/3.3.6/)|WSL PostgreSQL 实际驱动；产品打包遵守其许可证|
|FastAPI / Alembic|0.143.0 / 1.20.0|MIT；[FastAPI](https://pypi.org/project/fastapi/0.143.0/)、[Alembic](https://pypi.org/project/alembic/1.20.0/)|版本已解析；未建立产品 API 或业务迁移链|
|OpenAI SDK / HTTPX|3.29.0 / 0.28.1|Apache-2.0 / BSD-3-Clause；[OpenAI](https://pypi.org/project/openai/3.29.0/)、[HTTPX](https://pypi.org/project/httpx/0.28.1/)|Responses 自定义服务能力以 SDK-02 实际观测为准|
|PyYAML / RFC8785|6.0.3 / 0.1.4|MIT / Apache-2.0；[PyYAML](https://pypi.org/project/PyYAML/6.0.3/)、[RFC8785 源码许可](https://github.com/trailofbits/rfc8785.py/blob/main/LICENSE)|安全解析与 JCS 摘要；标准解析不等于授权|
|PostgreSQL|16.13，Debian 16.13-1.pgdg13+1|[PostgreSQL License](https://www.postgresql.org/about/licence/)；[官方镜像](https://hub.docker.com/_/postgres)|同一隔离库，业务/系统 schema 分开|
|Docker / Compose / Buildx / BuildKit|29.1.3 / 2.40.3 / 0.30.1 / 0.26.2|Apache-2.0；[Moby](https://github.com/moby/moby)、[Compose](https://github.com/docker/compose)、[Buildx](https://github.com/docker/buildx)、[BuildKit](https://github.com/moby/buildkit)|只锁定实测配置；不声称 rootless、任意 Compose 或 Desktop 支持|
|Git / uv|2.43.0 / 0.11.29|GPL-2.0 / MIT 或 Apache-2.0；[Git](https://git-scm.com/about/free-and-open-source)、[uv](https://github.com/astral-sh/uv)|npm 管理实际 JS 工程、Cargo 管理实际 Rust 工程；本次无空工程|

数据库镜像绑定 `postgres:16.13@sha256:5d143123fdf80462d1778cd4f24b9f7ca13c87174bca19141fb194c5a1ebca59`。具体镜像 tag、digest、SQL 返回版本均已核对，不以设计 v4.7 或探测包版本代替数据库版本。

## 3. 隔离启动、诊断与数据边界

实际工程位于根目录 `pyproject.toml`，采用非打包的 uv 工程。`0.0.0` 仅满足本地探测项目元数据，不是 CloudHelm 软件发布；没有 tag、Release 或已发布软件版本。`.python-version` 固定解释器；`uv.lock` 固定依赖解析，二者解决不同问题。

`infra/p0/compose.yaml` 仅建立本项目的临时 PostgreSQL，host 端口限 `127.0.0.1:55432`，tmpfs 数据，硬内存 256MiB、CPU 1 vCPU。trust 只用于无秘密隔离探测，不用于 Hub/生产数据库；没有业务/生产数据、持久卷或真实数据库密码。各探测分别使用专属 schema，系统 schema 初始化和版本事实由实际 SDK 卡记录。停止并移除容器会丢弃本轮运行数据，证据以固定输入和脱敏卡片保留。

启动、诊断与关闭步骤见 [P0 接缝使用说明](../../development/p0-seams.md)。诊断只输出允许的版本、运行范围、可达性和有界计数；不读取 `.env`、Docker 配置、用户认证材料或其他项目数据库。

用户授权模型使用当前 Codex 自定义 Responses 服务，模型 `gpt-6-luna`、reasoning `max`。配置路径是环境输入，不复制配置或密钥进仓库；凭据只在获准请求步骤解析，费用证据缺失时保留 unknown/null。离线入口默认不发送真实模型请求，`--live` 仅用于明示授权的固定批次；SDK-02 记录实际请求上限与 usage。

## 4. 版本类别、限制与后续门禁

|类别|本次边界|
|---|---|
|设计|总体 v4.7 / D01～D06 v4.7.0，未修改权威规则|
|探测输入/协议|隔离输入 `p0.1-public-inputs-r1`、契约草案 `p0-draft-r1`；不是正式执行协议|
|DBOS SDK/系统 schema|SDK 3.2.0；SDK 公有 migration 创建专用实验 schema，实际修订与序列化方式由卡记录|
|工作流应用|仅隔离实验注册名/版本；不虚构产品 application_version 兼容窗口|
|业务迁移/软件|尚无产品 Alembic 修订、已发布软件或 Desktop 原生支持结论|

P0.1 不支持的真实模型、工具、检查点和恢复入口由对应卡明确阻断。P0.2 提供参照和实际拓扑，P0.3 决定生产身份/权限、可信时间误差、保留期限、步骤运行时长及阶段统一出口；本次不能据一次 WSL 实验开放 P1 或生产部署。基础设施负责人负责补齐实际机器及工具链，Runtime/数据库/执行器负责人在版本、输入、环境变化时复核相应卡；正式阶段出口由项目负责人确认。

版本推进后按 AGENTS.md 定向删除已替代且无运行/验证/回滚引用的旧开发镜像；本次只有固定基础镜像，没有本项目早期开发镜像。不得以全局 prune 影响其他项目。
