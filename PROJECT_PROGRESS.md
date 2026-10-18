# CloudHelm 项目进度

本文件记录实际开发、验证与交付状态。当前设计基线为总体设计 `v4.7`、索引 `v4.7.2`、D03/D06 `v4.7.1`、D01/D02/D04/D05 `v4.7.0`；设计版本与软件版本分别管理。

P0 已按用户选定的 s2413 同机准备范围结项，P1.1 保留既有交付；P1.2 退出结论已纠正为修正中。当前没有完整 P1 阶段、s2413 安装/配额、独立交付或原生/人工验收结论；本轮结果不扩大历史接缝或其它产品组合的支持范围。

任务级 [PROJECT_PLAN.md](PROJECT_PLAN.md) 修订 18 已重新开放 P1.2 的 C1～C7 修正；用户暂时全部使用 s2413 的选择保留，正式独立目标仍属 P1.4/P1 出口前置。以下按记录列出实际工作，较早条目的“下一步”和阻塞描述保留当时状态，以最新记录为准。

## 2026-10-18 · P1.2 缺口修正（进行中）

- 已完成：核对当前入口 `dev / c28a85a`，工作树原先干净；重新核对计划、D03、实施说明及退出记录。保留 P0 结项和旧候选／原字节报告，撤回 P1.2 已无剩余实现项的判断。
- 原因与行为边界：固定制品环境不能替代可变 Workspace 日常环境；Task 两来源操作合并缺合计／唯一性校验；后端 generation 换键尚非真实输入变化证据；合成 Task 写意图尚非真实 Workspace／Build 贯通。修正保持 128 上限、统一事务、当前授权、未知物理状态保守处理，不开放 P1.3/P2。
- 进行中：按计划 C2 先修边界；C3～C5 分步补环境契约／记录、增量执行、生命周期；C6～C7 固定新源码和方法后补缓存及四组 Task 证据。子任务固定 `gpt-6-luna / max`，小步轮换代理，主会话负责文档、集成与 Git。
- 阻塞与风险：上述实现和新候选验证尚缺；当前无外部输入阻塞。新增工作实际投入和剩余估算待估。
- 主要文件：`modules/collaboration/facts.py`、`modules/workspaces/`、`services/dev-runner/`、专属契约／迁移／`scripts/p1/` 及本轮计划、实施、使用和退出记录。
- 验证：本条仅完成状态与差异只读核对，业务测试和服务尚未执行；旧 r1/r2 通过结论不自动用于新实现。人工验收未执行。
- 下一项具体任务：完成 C2 的 128、129、跨来源重复 ID 定向验证，随后接入可变开发环境。

### 本轮小步交付

- C1：已纠正计划、进度、退出映射并固定实施说明，提交 `8e1f390` 已推送 dev；仅检查文档差异，没有由此产生功能结论。
- C2：完成／取消共用完整操作合并器；保留 128 上限，超量为 `task_fact_projection_scope_too_large`，重复为 `task_fact_projection_duplicate_operation`，没有截断。子代理在 WSL/Python 3.12.13 的纯投影方法核验 128、129、跨来源重复与来源错误归一化通过。主会话补了真实应用映射的独立方法，等待新候选下执行；该方法的注入来源仍仅为协议验证输入。
- 集成修正：真实工程操作原先只因未存在于 `task_operation_links` 而被 Task blocker 隐去 ID；现按 Workspace／Build 领域原意图核对所属项目与 Task，再执行当前 `operation.query` 鉴权，跨 Task 继续拒绝。实际 ID 可见性待 C6 四场景核验。
- C3／C4：可变环境契约／表和 Runner 依赖／服务切片正在交付；新增 backing 生命周期 pin 接缝，使长期服务固定存储身份而不长期独占短命令锁，回收还检查容器挂载。该接缝尚未运行验证，整池持续占账不变。
- 版本：新增开发环境能力按语义版本准备开发源码 `0.3.0`，工作流应用单独 `cloudhelm-hub/0.3.0`；SDK 未变。WSL `uv lock --check --offline` 通过，未升级依赖，未发布 tag 或 Release。
- C3 基础：独立环境／操作表、契约和迁移 `0004_p1_2_development` 已交付。子代理在 WSL 新隔离 PostgreSQL 实际初始化并反射核对全表、CHECK 名称、活动／未决唯一索引、API/worker 列权限，通过；契约 ready 正向、resume 固定 Spec、同修订 generation 重建及无任意路径／就绪请求字段通过。初次过长约束名在本次新迁移内缩短后重验通过，未改旧迁移。该检查为开发输入，最终新候选方法尚未运行。
- C6 方法：A→A→B 后端方法已移除人为 generation 失效场景，B 固定为已授权路由变体且独立求源码摘要；静态准备通过，没有运行真实 BuildKit。四组真实工程 Task 方法已交回，采用仅订阅 control/orchestration 的同版 Task worker 作为确定屏障，再由普通 worker 核对工程回执；尚未运行真实场景。两个已有提交的“仓库验证 / check”已成功，不能替代上述业务证据。
- C4 依赖切片：私有安装快照、固定原锁／注释变体字节校验和同键归档核验复用已实现；WSL 导入与内嵌 bootstrap 语法检查通过。由于存储 noexec，安装和运行在容器有界 exec tmpfs，持久池只保存已核验快照；尚未实际执行安装，不能记录命中／失效已通过。
- C5／C7 接线：生命周期与只读查询、当前 gate、live reader、worker 关闭收尾正在集成。query 只探测既有进程与数据，不通过重启／重装／重置得到成功；后台服务只能由已接受操作推进，关闭未知保留核对与占账。
- C3～C7 实现已交回：五种环境命令、受限运行／热更新、只读物理观察、数据修订、持久操作日志、候选 reader 和单 worker 接线均已落盘；主会话已完成全体公开 Python/JSON 的 UTF-8 解析，OpenAPI 已按新增入口重导出。运行验证尚未执行；首次快照一致性核对暴露响应 schema 漂移，已为每路由独立建立响应映射并重新生成，后续由实际契约检查裁决。
- 规模评估：已拆 source、probe、bootstrap、Docker、journal、Hub 命令／查询／回执；Runner runtime、Docker、依赖与生命周期控制器仍超过建议行数。包含集中安全边界及嵌入执行脚本，本轮在当前功能范围内集中验证，不以机械行数继续引入重构；大型模块的集成风险保留在当前候选检查范围。
- 下一项具体任务：冻结新实现与 InputSet，依次执行操作边界、后端 A→A→B、增量环境及四组真实工程 Task 方法；只有实际方法通过后才重裁退出。
- 集成前核对：OpenAPI 的多处漂移最终定位为主会话生成 JSON 时使用的模糊补丁定位，已通过 apply_patch 完整替换真实导出结果；WSL `scripts.p1.check_public_contracts` 通过，32 路径、34 操作、85 schema，旧路径未移除。两处新增文件的 EOF 空行已清除；首个实现提交的格式检查失败未阻止提交，后续提交纠正，不沿用该次通过结论。

## 2026-10-18 · P1.2 固定验证与交付收尾

- 已完成：P1.2-01～02 的 Git 来源、独立工作区、受控文件修改、候选冻结、离线依赖/构建、BuildRun/三角色 OCI、受控存储与环境/数据重建，以及真实 HTTP/DBOS 单 worker 接线。契约、迁移、使用说明与 [退出映射](docs/acceptance/p1/p1-2.md)齐备。
- 已完成：[InputSet r2](docs/acceptance/p1/input-set-p1-2-r2.json)绑定源码 `118216079d2c0d7579443f4b297d67971b89c545` 的 290 文件；[完整结果 r2](docs/acceptance/p1/validation-p1-2-r2.json)于 `2026-10-17T20:13:53.211867Z`～`20:18:41.586038Z` 通过，前后输入完全匹配，`end_to_end_chain_complete=true`。该源码已推送 dev，[仓库验证 / check](https://github.com/ChaceQC/CloudHelm/actions/runs/39065652760)成功。
- 自动验证：真实导入/Task/物化/文件写入/候选/继续开发/构建链贯通；候选保持不变，BuildRun `build-5620ffeff3294eeda798be0e689037b4` 为 succeeded，frontend/backend/postgres 三份制品核验并加载。独立 HTTP 136 个断言全部通过，覆盖重启持久性、数据库不可用、暂停恢复及数据 generation 1→2；这是重复分段断言数，不是产品覆盖率。
- 回收：API、worker、观察器、隔离数据库、应用容器和父组均停止；本次 8GiB 池卸载、loop 脱离、backing/目录删除，实测回收 8,589,934,592 字节，剩余占账 0。早期 4GiB 的即时未知回收已由补充 ext4 核对解除；历史失败和收尾收据均保留。
- 镜像清理：按标签和完整镜像 ID 核对无容器引用后，仅删除旧 `cloudhelm-reference-backend:p0.2-r1` 与 `cloudhelm-reference-frontend:p0.2-r1`，使用 `image rm --no-prune`；[清理记录](docs/acceptance/p1/development-image-cleanup-r1.json)保留结果。当前验证镜像、固定公共工具链/数据库镜像和内容证据保留，没有全局 prune。
- 进行中：无 P1.2 实现或运行验证任务；本条及固定证据作为收尾文档提交。阻塞与风险：本轮退出无阻塞；支持限于固定受控 WSL 组合，实际人日与后续投入待估。
- 人工验收：未执行，保持 null；未发布 tag/Release，未合并 main，未进行 s2413 安装、独立交付或 Desktop 验收。
- 主要文件：`modules/projects/`、`modules/workspaces/`、`modules/delivery/`、`services/dev-runner/`、Hub API/worker、`packages/contracts/p1/`、`scripts/p1/`、`docs/acceptance/p1/`。下一项具体任务：P1.3-01 共享宿主资源准入，当前尚未启动。

## 2026-10-18 · P1.2 中断接续（实施过程）

- 已完成：读取用户引用会话，确认其因请求限流中断；当前入口 `dev / 3b42d20`，保留已有来源回执、受控文件操作、离线依赖/前端构建及开发存储未提交实现。当前任务继续授权 P1.2，子代理明确使用 `gpt-6.1-sol / max`，新切片轮换新代理。
- 已完成：计划修订 16 将剩余工作分为候选、工作区应用、后端构建、前端收尾、开发存储、构建记录六项，后续依赖稳定后接 API/worker 与环境/数据。
- 进行中：逐项接续现有实现并整合；主会话负责最终文档、输入与证据绑定、Git。涉及现有模块拆分仅为接通上述职责，保留授权、Task、幂等和物理事实边界。
- 阻塞与风险：最终候选、Hub/worker 接线、完整制品和环境退出项尚缺证据；旧通过结果不自动适用于当前未提交字节。无新增外部输入阻塞，实际投入与剩余工作量待估。
- 验证：只读核对 WSL Ubuntu-24.04、内核 `6.18.33.2-microsoft-standard-WSL2`、uv `0.11.29`、Docker `29.1.3`，名称匹配 cloudhelm 的容器为空；本轮业务验证尚未执行，等待具体切片交付。
- 主要文件：计划 R1～R8 所列模块及 `docs/acceptance/p1/`；下一步为收齐六项接口与定向证据，再接通最终受控开发链路。

### 本轮已交回的小步

- R1：候选冻结、只读内容、稳定操作核对及私有 Git refs 已实现；WSL `check_workspace_candidates` 于 `2026-10-17T19:05:21.888720Z` 通过 27 个检查标签。正常采集使用真实 Docker 库存，相关拒绝部分为隔离 fixture；不提供任意宿主编辑器冻结。
- R2：工作区命令/查询/可信回执、当前版本与权限及 Task 完成/取消 pending 已接入；`check_workspace_application --development --port 55439` 于 `2026-10-17T19:09:04.391355+00:00`～`19:09:21.501612+00:00` 通过并清理。初次文件回执原字节保留，当前 binding 独立递增；尚不由此证明 worker/资源执行链。
- R3：后端断网构建于 `2026-10-17T19:00:47.093205+00:00`～`19:01:35.735652+00:00` 通过；20 项锁定依赖安装、入口及迁移 head、缓存命中/失效、OCI 和停止事实已核验。[原字节报告](docs/acceptance/p1/validation-development-backend-build-r1.json) SHA-256 为 `df122d1507eadf848b883d2789da0b1b0e3372406ed231b50c2b2ce2796e7f2d`。此前两次发现 native 快照空间不足及检查方法不兼容 FastAPI 惰性路由，修正配方/方法后通过，没有扩大限额。
- R4：主会话复用并重新核验 npm seed，运行前端方法；`2026-10-17T19:02:38.878904+00:00`～`19:04:28.244261+00:00` 通过断网编译、OCI 各层及最终 dist、缓存拒绝和停止确认。[原字节报告](docs/acceptance/p1/validation-development-frontend-build-r2.json) SHA-256 为 `ed62ac5f1ad54349ea92878977feb99f2ed4a92ac002ef1ac35928c942c74718`，内存峰值 3,111,583,744 字节，121 个跟踪进程全部退出；不包含镜像加载或 HTTP。
- R5：可配置专用存储提供者 r2 已实现；`verify-pool` 于 `2026-10-17T18:56:25.004726+00:00`～`18:56:27.770514+00:00` 实际验证 64MiB 池的 ENOSPC、停止保留、remount、文件及 backing 回收。[原字节报告](docs/acceptance/p1/validation-development-storage-r2.json) SHA-256 为 `b3ea6d1b1eb5fe7e69403c4d735b984debc263b13eee3761ca0d9ad8c64907ad`；实例已移除，应用写入路径待集成，不扩大到任意容量/主机。
- R6：BuildRun、三角色内容与执行观察、pending 及线性迁移 `0003_p1_2_builds` 已实现；`check_build_records --port 55438` 于 `2026-10-17T19:07:40.694562+00:00`～`19:07:50.671935+00:00` 通过并清理。覆盖真实数据库约束/权限/UoW与合成执行协议，未以合成成功代替 Runner。
- 主会话已接 HTTP 工程申请/查询与 DBOS 同事务交接；API factory/OpenAPI 可在无数据库 lifespan 下导出。R7 正接真实 worker、完整制品运行及新 InputSet 方法，完整 P1.2 退出尚未判定。
- 主会话定向回归 `check_foundation --development --group tasks` 于 `2026-10-17T19:37:55.131742+00:00`～`19:38:36.454195+00:00` 通过 32 个 Task 结果键，覆盖新增 pending 汇总后的完成/取消/竞态和真实 worker 控制；夹具 `cloudhelm-p1-0eae1a15ed98` 已清理，非完整 P1.1 重验。当前 OpenAPI 快照核对为 25 路径、27 操作、71 schema；123 个变更公开文本的 UTF-8、103 个 Python AST、9 个 JSON 和 69 个 Markdown 本地链接检查无失败。
- R7 开发接线：真实 HTTP/同事务入队/单 worker 已跑通来源、Task、文件修改、候选和恢复开发，候选保持不变；[前半链记录](docs/acceptance/p1/validation-development-engineering-candidate-r2.json)及[定向清理记录](docs/acceptance/p1/validation-development-engineering-candidate-cleanup-r1.json)分别保留运行与回收事实。该次存在并行无关构建文件漂移，只作为开发接线证据。
- R7 制品环境：复用已生成的前后端归档并核验 PostgreSQL 依赖，真实完成三角色加载、迁移/就绪、独立 HTTP、重启持久性、数据库不可用、暂停恢复及数据重建；[原字节报告](docs/acceptance/p1/validation-development-artifact-environment-r1.json)记录全部容器/父组停止删除、池卸载、loop 脱离与 backing 删除，但当次宿主空间增量不足，仍保守占账 4GiB 待核对。此前失败定位并修复了 Docker 29 manifest/config 身份差别、挂载命名空间、PostgreSQL shm、固定镜像的文件权限与内部网络入口；没有将失败写成成功或删除写成额度释放。
- 当前固定运行组合：数据库 UID1000、64MiB shm；后端沿镜像 UID0 且 drop ALL；Nginx master UID0，仅保留 SETUID/SETGID/CHOWN，三服务均只读 root。三服务与迁移处于 896MiB/1.5CPU/256PID 父组，平台控制进程另计；独立验收使用只连当前前端的有界 loopback 入口，不构成 P2 预览或整机容量验收。下一步固定实现提交与新 InputSet，运行完整工程链。
- 实现提交 `ff8056744a95db3fbf1fc2421afcdbc51eb47e15` 已推送 dev，对应[仓库验证 / check](https://github.com/ChaceQC/CloudHelm/actions/runs/39065135382)成功。InputSet r1 固定 290 文件；首次完整方法的前后输入均匹配，但在 Build 申请前暴露固定前端来源 12 文件与离线配方 10 文件的成员接缝，尚未启动 Builder；[失败原记录](docs/acceptance/p1/validation-p1-2-r1.json)及[8GiB 池清理收据](docs/acceptance/p1/validation-p1-2-r1-cleanup.json)保留。修复仅核验原 Dockerfile/.dockerignore 的固定摘要后选择离线配方输入，未知文件和字节变化继续拒绝；该改动将由新输入重新绑定。
- 早期环境验证的 4GiB 保守占账已通过[补充只读核对 r2](docs/acceptance/p1/storage-reconciliation-development-r2.json)解除：绑定原报告 SHA-256、原 backing 设备/inode，确认实例与 loop 均消失，ext4 inode 已在原删除之后重新分配且当前 bitmap 空闲、blockcount 为 0；原文件已无分配块。r1 无法排除 inode 复用的核对记录保留，不改写原未知结论。该核对仅说明 WSL ext4 可复用空间，不声称 Windows VHD 文件已缩小。

## 2026-10-17 · school-docs 本地目录忽略

- 已完成：根目录 `.gitignore` 新增 `/school-docs/`，忽略该目录及其内容；修改前确认目录尚未被 Git 跟踪。
- 进行中：无；阻塞与风险：无。
- 主要文件：`.gitignore`、`PROJECT_PROGRESS.md`。
- 验证：`git check-ignore -v -- school-docs/ school-docs/ignore-rule-probe.txt` 均命中新增规则，`git status` 不再列出该未跟踪目录，`git diff --check -- .gitignore` 通过。仅核对 Git 忽略规则，未运行业务测试。
- 下一步：等待用户后续任务。

## 2026-10-15 · P1.2 接续实施（进行中）

### 已完成

- 核对接续入口 `dev / 8dc47f5`；工作树已有数据库权限/表修改，以及 Git 文件视图、工作区结构、Runner 契约与探针未提交文件。本轮保留并接续这些 P1.2 草稿，不回退既有工作。
- 根据用户最新要求，将接续代理指定为 `gpt-6.1-sol / max`。计划修订 14 保留既有细分，先核验三个已有实现小步，再依次接工程授权/输入、候选、增量环境、构建及最终集成。
- 主会话核对当前远端 dev 与本地一致；于 `2026-10-15T07:58:41Z` 核对 WSL 内核 `6.18.33.2-microsoft-standard-WSL2`、`uv 0.11.29`、Docker `29.1.3`。新增 [P1.2 证据索引](docs/acceptance/p1/p1-2.md)，按退出项保留缺口和支持边界。
- Hub 结构代理完成 01c：来源唯一性、工作区/候选复合归属、线性迁移和数据库权限验证通过；主会话将既有数据库验证入口改为 `load_business_metadata()`，避免遗漏新增表。当前仅支持新隔离库，旧版本识别继续拒绝，未建立旧库升级器。
- Git 安全文件视图已交付；工程授权代理交付三项显式动作，并固定原 owner/角色/委托动作语义；Hub 代理交付首次工程 InputSet 绑定，内部方法复用调用方 UoW，不生成候选、人测或验收事实。
- OCI 内容层完成单架构归档核验、内容寻址、原子只读保存及同一已核验 fd 的读取；它不管理 BuildRun，不将内容校验写成实际镜像启动。Runner 最终能力报告和八引用 InputSet 已原字节归档到 `docs/acceptance/p1/`。
- 开发源码版本更新为 `0.2.0`，工作流应用独立更新为 `cloudhelm-hub/0.2.0`；业务迁移为 `0002_p1_2`，SDK 仍为 `3.2.0`。同步根锁文件和当前 OpenAPI 增量，未创建 tag 或 Release。
- 固定参照导入已交付：从原固定 commit 的子树生成新的受管 bare 初始提交，仅包含 32 个源码文件；原历史、remote、hooks 和独立需求/验收资产不进入新仓库。来源导入意图、当前权限 resolver 和查询已持久化，尚未开放物理 worker 入口或声明已经入队。
- 固定 Python 基础镜像已通过断网 rootless BuildKit 的实际版本命令、OCI 导出及可信内容存储核对；报告原字节归档为 [离线镜像开发证据](docs/acceptance/p1/validation-development-offline-image-r1.json)。显式执行 tmpfs 合计 1,108,344,832 字节，组内内存峰值 902,615,040 字节；停止后进程/cgroup/容器均确认退出，保留内容另记 136,325,763 字节，不声称宿主归档已获物理磁盘配额。
- 已验证的工程基础以 `90d35d1` 提交并成功推送 `origin/dev`；这是 P1.2 中间小步，完整退出条件仍未满足。

### 进行中

- 按用户最新要求，允许最多六个同时执行的子代理，且每个新切片使用新代理；已开始的 Git 受控文件操作和 Hub 来源回执先交回，Python 离线依赖由新代理执行。真实重执行仍串行准入。本任务继续按显式要求使用 `gpt-6.1-sol / max`；候选、npm、环境/缓存和完整构建按新细分依次推进。
- 必要接缝调整仍以真实身份、统一事务、Task 当前控制、稳定操作和真实物理事实为边界；不改变 P1.1 既有授权列表或补写验收结论。

### 阻塞与风险

- Runner 首轮十项固定离线能力探针已通过，真实应用构建所需更大限额、依赖获取和最终制品仍待证据；这些前置不成立时拒绝对应执行。完整 P1.3 资源协议与 P1.4 部署未开放。
- 实际投入与剩余工作量待估；已有草稿尚未完成集成，不属于已验证交付。

### 下一步

- 完成受控单文件操作、真实来源回执登记与 Python 离线安装；随后接候选、npm 与实际环境。业务执行入口开放前补齐真实存储准入及 DBOS 原子交接，最终形成 P1.2 新 InputSet 与完整集成证据。

### 主要文件或模块

- `modules/workspaces/`、`modules/projects/source_tables.py`、`database/`、`services/dev-runner/`、`packages/contracts/p1/`、`scripts/p1/`；文件分工按实施说明执行。

### 验证

- `2026-10-15T08:05:07.675355+00:00`～`2026-10-15T08:05:17.107811+00:00` 在 WSL 运行 `uv run --locked --offline --no-sync python -B -m scripts.p1.check_workspace_records`：元数据/迁移一致、5 个契约拒绝、8 个数据库约束拒绝、74 项权限核对通过；旧基线标识拒绝且不被改写，夹具已清理。该结果为 development_worktree，未验证应用流程、旧库升级或完整 P1.2。
- Git 方法于 `2026-10-15T08:07:20.332638Z`～`2026-10-15T08:07:21.229917Z` 完成 SHA-1/SHA-256 双格式 59 条定向检查；最终 Runner 方法于 `2026-10-15T08:07:57.448737Z`～`2026-10-15T08:08:02.279580Z` 十项通过，随后严格回读和六项拒绝检查通过，所属容器余量为零。报告 SHA-256 为 `9c7a832e8af25887780471455d0288f4bdb4ee18856f2d4d49eb3251f144fa14`，只适用固定离线 tmpfs 探针。
- 工程授权方法于 `2026-10-15T08:10:06.269488+00:00`～`2026-10-15T08:10:15.255658+00:00` 通过九项真实数据库检查，夹具已清理。首次输入绑定方法最终于 `2026-10-15T08:17:37.226570+00:00`～`2026-10-15T08:17:47.579824+00:00` 通过九组检查；首轮仅检查方法误传既有请求字段而失败，修正方法后通过。该绑定证据使用 `protocol_validation` 测试资料，尚未证明真实源码链。
- OCI 内容方法最终于 `2026-10-15T08:17:32.658787+00:00`～`2026-10-15T08:17:32.745116+00:00` 通过普通/gzip 正向及 25 项内容拒绝、9 项存储拒绝；首轮一个合成篡改用例预期不准确，修正用例后通过。尚未验证真实构建产物或 Docker load。
- 主会话核对当前锁文件（49 个包）及 OpenAPI 快照一致性（13 路径、15 操作、33 schema）通过；没有运行无关全量测试。上述结果仍为开发字节证据，最终固定候选另行绑定验证。
- 固定来源导入于 `2026-10-15T08:30:47.298084Z`～`2026-10-15T08:30:53.469175Z` 通过 16 项检查，新 commit 为 `7ec1ab83bdc963b4d6521d832f7f53f7a874dc11`，32 文件/139037 字节，清单 SHA-256 为 `31a82fa9e1e04c27a8df2f6a35b04c7a482ab0aecdccee174b958d1d71ea3974`。首次发现无执行能力的 `-diff/-merge` 属性未获允许，明确扩展这两项后相关 Git 59 项检查通过；临时目录清理完成。
- 来源意图方法于 `2026-10-15T08:33:23.586613+00:00`～`2026-10-15T08:33:33.384316+00:00` 一次通过 11 组检查，覆盖版本、当前权限、重投、注销/撤权、唯一预留和事务回滚，夹具已清理。该结果未证明 Git 物理执行、来源回执登记或 worker 调度。
- 离线基础镜像方法最终于 `2026-10-15T08:33:16.446941+00:00`～`2026-10-15T08:33:48.823592+00:00` 全程通过，归档 45,448,192 字节，SHA-256 为 `2abb95b1030f66fabf1b9494706a479c8591503e37478ea380ad58db92939267`。当前 Docker 的 `cp` 不能采集 tmpfs 输出，改为有 `RLIMIT_FSIZE` 的固定二进制流采集并双端核对摘要；两个失败调试目录的重复 layout 共 90,858,758 字节定向清理，失败报告/输入保留。尚未执行项目依赖安装、缓存、实际应用构建或 Docker load。
- 主会话完成当前改动的 UTF-8（66 个文本）、Python AST（49 文件）、JSON（4 文件）、本地文档链接（88 个）及差异格式核对。CI 只新增已交付的 Git 文件视图和合成 OCI 内容窄检查，规范与协作说明同步其覆盖范围；真实数据库、Runner 和应用构建继续单独取证。

## 2026-10-15 · P1.2 Git、工作区与受限构建（进行中）

### 已完成

- 核对入口 `dev / f2849b7ac7aa84f613f02d1ad790b3585c2c4920` 及干净工作树；`git fetch origin dev` 后本地与远端一致。读取当前规范、P1.2 计划/进度、总体设计、D03 相关边界、P0 参照适用决定及 P1.1 基础，不复用旧同名仓库的实现状态。
- 用户明确要求完成 P1.2，子代理指定 `gpt-6-astra / max`；先将两项工作细分为接口、Git、Hub 记录、沙箱、候选、缓存、构建和集成验证小步，代理负责文件互不重叠。
- 于 `2026-10-15T02:46:50Z` 核对本机 WSL `Ubuntu-24.04`、内核 `6.18.33.2-microsoft-standard-WSL2`、仓库 `/mnt/e/Project/CloudHelm`、`uv 0.11.29`、Git `2.43.0`、Docker server `29.1.3`、cgroup v2/overlayfs；当前没有运行名称匹配 cloudhelm 的容器。本轮没有读取或输出配置密钥。
- 三个代理完成 01a，只读识别工程动作未开放、真实 Task 输入缺初次绑定、worker 白名单待扩展和旧库无升级器四处接缝；主会话在 [P1.2 实施说明](docs/implementation/p1-2-engineering.md) 固定领域所有权、文件归属及分步接口。BuildRun 仍归 delivery，制品存储不复制业务状态，物理候选不伪装成最终集成/完成证据。
- 主会话新增 `scripts/p1/engineering_manifest.py`，分别提供未提交开发字节指纹和已提交候选的冻结/验证，固定范围包含 Runner、Git/Hub、锁定参照与独立验收方法；清单不含私有运行数据，当前尚未生成最终 InputSet。

### 进行中

- 接续三个首个实现小步：Git 安全文件视图、Hub 来源/工作区结构和 Runner 固定能力探针。现有身份/Task/worker 接缝后续分别调整，原因是新工程动作与真实输入/域内推进需要当前授权和统一事务；预期保留 P1.1 外部控制语义及旧授权动作列表，不自动扩权。

### 阻塞与风险

- 当前待核实 rootless BuildKit 在实际 WSL Docker 环境的内核、cgroup、存储及网络支持；未取得证据前不承诺可用，不使用宿主 socket 或特权旁路替代沙箱边界。
- 构建代理 01a 因 gpt-6-astra token rate limit 非正常终止一次，已按同模型/max 接续并交付只读报告；没有改模型或代写其工作。当前未装 rootless 工具链，本机 /mnt/e 是 9p，运行数据将使用 Linux 原生私有目录；现有 ext4 没有已证实的硬配额，先核验有界 tmpfs 范围。
- 完整共享宿主资源协议、s2413 安装/部署、P1.3～P1.5 和 P2 正式产品验收不属于本轮授权；P1.2 的运行入口必须有实际受控开发限额，缺少前置时明确拒绝。实际人日与新增工作量待估。

### 下一步

- 完成三个首个实现小步的窄范围退出检查；随后单独接工程动作/真实输入、候选冻结和依赖获取，不把这些合并成过大的代理任务。

### 主要文件或模块

- 主会话负责计划、进度、`docs/implementation/p1-2-engineering.md` 和 `scripts/p1/engineering_manifest.py`；代理源码落点及负责范围见实施说明第 2 节。

### 验证

- 已执行 Git 状态及 WSL 工具链只读核验；三份本轮文档的 UTF-8/47 个本地链接、输入方法 AST 和开发字节指纹检查通过，工作树指定范围差异格式通过。业务、数据库、沙箱与构建验证未执行，原因是本轮实现和输入尚未建立；未运行无关测试。

## 2026-10-15 · P1.1 身份、命令与 Task 基础（实现与 WSL 开发验证已完成）

### 已完成

- 核对当前 `dev / 8c81ea7` 与干净工作树；`git fetch origin dev` 后本地与远端一致。读取当前计划、进度、D01/D02/D05/D06、P0 身份/Task/迁移决定和 SDK 接缝，未套用旧同名仓库实现。
- 用户明确授权完成 P1.1，子代理采用 `gpt-6-astra / max`；主会话先形成计划修订 11，三个方向先核对共享接口，再以小任务接续实现，避免重叠文件。
- 实际确认 WSL `Ubuntu-24.04`、内核 `6.18.33.2-microsoft-standard-WSL2`、仓库 `/mnt/e/Project/CloudHelm`、`uv 0.11.29` 与 Docker server `29.1.3` 可用；当前未运行本项目 P0 数据库容器。
- 三个指定模型代理完成 01a 的接口核对，主会话在 [P1.1 实施说明](docs/implementation/p1-1-foundation.md) 固定同库事务、去重/完成顺序、受控身份引导、锁序、已接受命令的授权延续及初始连接预算。数据库代理已核验已安装 DBOS 3.2.0 的公开迁移/事务入队/启动接口，SDK 锁超时和额外监听连接限制单独处理。
- 共享基础首个小步交付 11 个文件：唯一 metadata/UoW、命令及审计引用、受保护配置与分离连接池、事件/Outbox、workflow 绑定及公开同事务入队。数据库代理在 WSL 完成 11 文件 UTF-8/AST、导入/配置脱敏/池分离/有界结果/拒绝未知 workflow 和 PostgreSQL DDL 编译检查；未连接数据库，该结果不表示原子性运行证据。
- 身份核心首个小步交付 11 个源文件和 7 张表，包含真实 DeviceSession 认证、当前角色/委托、原命令与审计恢复、锁序及有界项目查询。WSL 在 `2026-10-14T18:48:52.972250+00:00` 完成 10 模块导入、7 表 DDL 编译及 13 项纯拒绝；`2026-10-14T18:54:41.576228+00:00` 对最终 Task 外键和分页/资源绑定补充 6 项纯拒绝核验。尚未连接数据库，不将这些结果计为真实授权/撤销运行证据。
- 身份维护 CLI 与既有项目管理命令已交付；WSL 在 `2026-10-14T19:13:38.707127+00:00` 完成新增 10 模块导入和 15 项纯边界，在 `2026-10-14T19:16:22.787849+00:00` 核对 4 类 CLI 参数错误在读取配置前安全拒绝。尚未实际签发会话或运行 HTTP。
- 数据库代理在 `2026-10-14T19:19:19.234743+00:00～19:19:28.069339+00:00` 完成新 P1 隔离数据库窄验证：24 表、业务 head `0001_p1_1`、SDK `3.2.0`、工作流应用 `0.1.0`；重复初始化、维护锁拒绝和 UoW 回滚通过，API/worker 运行角色各 11 项越权写入以 PostgreSQL `42501` 拒绝。公开 DBOS 查询仅检查空列表，不读取 inputs/outputs，精确系统 schema 版本仍为 null。fixture `cloudhelm-p1-1952d93c5838` 的 55433 端口、唯一 Compose 项目和私有目录已清理。
- 该数据库验证前的三次启动尝试均在容器启动前因 `local` 日志驱动的 `max-file=1` 与默认压缩冲突而拒绝；配置改为 `max-file=2` 后才进入上述成功窗口。没有修改旧数据库、P0 或 s2413；不把失败尝试记为初始化成功。
- worker 运行基础与根依赖已交付：源码项目 `cloudhelm-hub/0.1.0`，新增参照已锁的 `uvicorn==0.54.0`，原 SDK 版本不变。WSL 完成离线 lock/sync/lock check、入口帮助与真实双进程锁核验；第二进程拒绝，首进程实际退出后可再取得锁，测试锁已清理。尚未运行真实业务 workflow 消费。
- API 自有入口与 HTTP 快照已交付；`2026-10-14T19:42:55.701148+00:00` 的静态/HTTP 边界核验覆盖无配置/连接/DBOSClient 的 factory、13 路径/15 操作/33 schema 及 15 项原始 JSON/安全错误拒绝。此时 TaskApplication 尚在接续实现，未把无 lifespan 的边界检查当作实际服务/数据库通过；最终快照以集成版本为准。
- Task 03a/03b 源码已交付：12 张领域/消费事实表、受控字节/摘要登记、完整事实合取、创建/启动/完成/取消/核对/查询、输入失效与原意图关联、两个业务 workflow/step 和持久内部 invocation 去重。WSL 的导入、无 I/O 构造/注册及纯条件检查通过；运行层面已在上述身份组使用真实 Task 创建，其余完成/并发/worker 消费等待本组方法。
- 主会话新增固定输入、HTTP 快照与分组集成验证入口，维护开发/契约说明；AGENTS.md 和 GitHub 协作说明同步真实 Hub 源码/版本与 CI 覆盖。CI 仍只承担已列结构/源码/契约/参照构建检查，实际 P1 数据库/流程证据单独记录。
- 两个指定模型代理完成小范围只读交叉审查：身份/项目/API 的当前权、重投和秘密边界，以及共享事务、worker 版本/进程锁/连接预算均未发现具体阻断；没有代替实际运行验证或扩大到完整安全验收。
- 主会话于 `2026-10-14T20:29:20.704567+00:00～20:30:18.682270+00:00` 执行 `scripts.p1.check_foundation --development --group runtime`，7 项运行入口检查通过：双 API 存活且没有 worker 连接/版本写入、单 worker/重复实例拒绝/SIGTERM 后实际重启、连接预算采样、恢复与版本门禁及基线恢复。[开发运行结果](docs/acceptance/p1/validation-development-runtime-r1.json) 明确 `complete_scope=false`、未冻结工作树；不是最终候选全组结论。fixture `cloudhelm-p1-85f2161c6b06` 已清理。
- 主会话于 `2026-10-14T20:33:49.644281+00:00～20:34:53.022186+00:00` 执行 `scripts.p1.check_foundation --development --group identity`，18 项真实维护/身份/HTTP 检查通过，使用真正 developer Task 创建命令验证当前权先于原结果、角色/用户撤销与原主体恢复；未伪造成功命令。[开发身份结果](docs/acceptance/p1/validation-development-identity-r1.json) 同样是未冻结工作树的部分覆盖，fixture `cloudhelm-p1-4ba64c2acbc3` 已清理。
- 主会话于 `2026-10-14T21:13:22.104213+00:00～21:14:00.545837+00:00` 执行 `scripts.p1.check_foundation --development --group tasks`，32 项 Task 检查通过：五处真实写入/公开 SDK 后故障整体回滚、完成来源/固定报告、七场双控制池竞争、unknown/合成封闭、真实 initial/control 消费及业务 step 重投。没有伪造成功命令、HTTP 或 worker；合成事实仅证明控制协议。[开发 Task 结果](docs/acceptance/p1/validation-development-tasks-r1.json) 的 fixture `cloudhelm-p1-45f4ed06f6bd` 已清理，尚不替代最终固定候选全组结果。
- 主会话核对 99 个本轮工程文件，其中 94 个 Python 语法及 1 个 JSON 通过；工作树差异格式通过。再次 fetch 后 `dev` 与 `origin/dev` 仍同为入口 `8c81ea74686a738b0ba1ec5ca26352304ff88d36`，GitHub 仍为公开 `ChaceQC/CloudHelm`、默认分支 main。
- 暂存审查限定本任务 113 个文件，UTF-8、入库范围和凭据形态检查通过；清除首迁移末尾一个多余空行后，暂存差异检查通过。该格式修正不改变迁移语句或运行行为。
- 实现与方法提交 `43a04f7abe36faf49233ccc4267b657ff7ba99a0` 已正常推送 origin/dev；对应[仓库验证 / check](https://github.com/ChaceQC/CloudHelm/actions/runs/38640037561) 为 completed/success，全部工作流步骤成功。该 CI 只覆盖既定结构/源码/契约/参照构建范围。
- [P1.1 InputSet r1](docs/acceptance/p1/input-set-p1-1-r1.json) 于 `2026-10-14T21:25:46+00:00` 固定上述源码的 125 个公开输入，清单 SHA-256 为 `ab48769593b9ccf86d2371e14c93af10a10e53723c9670eadab4c658fbbab691`。没有改写旧 P0 InputSet。
- [最终四组结果](docs/acceptance/p1/validation-p1-1-r1.json) 于 `2026-10-14T21:27:40.091129+00:00～21:30:19.409940+00:00` 完成：database 4、identity 18、tasks 32、runtime 7，共 61 个有限检查结果键全部 true；`complete_scope=true`，运行前后 125 个输入与源码/清单匹配，`cleanup=complete`。这些键包含组合断言，不当作独立用户验收场景数或覆盖率。
- [P1.1 记录](docs/acceptance/p1/p1-1.md) 已逐项映射 P1.1-01～03 的实现、契约、使用说明和固定候选证据；计划修订 12、支持矩阵 r4 已同步。本轮工作包无未完成实现或开发验证项，下一待启动为 P1.2-01；实际人日和剩余总量待估，不按代理墙钟折算。

### 进行中

- 无 P1.1 实现或运行验证任务。本条、最终 InputSet/结果和收尾文档作为源码之后的独立证据提交，不预写该文档提交自身的哈希或未来 CI 结果。

### 阻塞与风险

- 本轮 P1.1 退出阻塞：无。完成/封闭正向域事实是受控合成输入，实际 SQL/HTTP/worker 和控制协议通过不代表真实工程开发、执行器物理停止或人类验收；支持范围以 P1.1 记录为准。
- 数据库代理接续 worker 小步时曾因模型服务 `400 / invalid_encrypted_content` 非正常终止；已按原 `gpt-6-astra / max` 恢复并完成该小步，未切换模型或由主会话代写其负责实现。
- 本轮范围不包括 s2413 安装/部署/资源分配、收费模型调用、P1.2～P1.5 或人类验收；WSL 结果只覆盖本轮开发方法与固定环境。

### 下一步

- 下一待启动为 P1.2-01：接入唯一权威 Git 来源与受限独立工作区；P1.3 资源/执行器按依赖另行安排。当前任务没有自动启动下一工作包。

### 主要文件或模块

- 实际新增 `database/`、`modules/identity/`、`modules/projects/`、`modules/collaboration/`、`modules/workflow/`、`modules/sync/`、Hub API/worker、P1 契约、`infra/p1/`、`scripts/p1/` 及实施/使用/验收记录；同步根依赖、CI、AGENTS、README、计划、进度与支持矩阵。
- 规模口径排除生成 OpenAPI、迁移与文档；普通业务/服务模块按职责拆分，集中契约字段与顺序验证资产按自然结构维护。`check_identity.py` 的 332 行用于同一受控身份场景的连续安排，作为验证资产单列，不机械搬迁已验证的断言。

### 验证

- 已执行分组开发核验及固定候选完整四组，最终 61 项结果全部通过；实际命令为 `uv run --locked --offline --no-sync python -B -m scripts.p1.check_foundation --input-set docs/acceptance/p1/input-set-p1-1-r1.json`。同一新夹具依次覆盖四组，输入前后匹配；通过后不重复运行未变化的数据库或业务方法。
- 主会话的 WSL 文档检查覆盖 10 份 UTF-8 文档与 70 个本地链接，均通过；当前差异格式检查通过。没有收费模型、s2413 操作、独立部署或原生/人工验收，未显形读取或输出配置密钥。
- 最终 fixture `cloudhelm-p1-069c083c4ec5` 的 API/worker 实际退出、安装锁、数据库/网络和私有运行目录按本项目定向清理。未构建新的 Hub 镜像，没有因此替代旧参照/P0 镜像；保留本版复现所需的固定 PostgreSQL 基础镜像。
- 最终写回后只做文档/证据核对：4 份文档的 63 个本地链接、InputSet/结果 JSON 关联、61 个 true 结果及 125 个当前源码摘要均通过，差异格式通过；没有再次运行已通过的数据库或业务场景。

## 2026-10-15 · 接续 P0 同机收尾（已完成）

### 已完成

- 读取用户引用的聊天“根据文档，补全P0剩余部分，subagent使用 6 astra max”，确认上次因服务端 token rate limit 中断；沿用用户“暂时都使用 s2413”的选择，不重复要求另配机器。
- 当前入口为 `dev / 6b2f308`；保留并审查接续上次尚未提交的 `scripts/p0/topology_snapshot.py`。远端与基线检查已按下项核对，本轮验证另行记录。
- 按计划修订 9 的 G01a、G01b、G02a、G03a、G03b 接续。子代理继续使用用户指定的 `gpt-6-astra / max`；主会话负责计划、进度、最终证据与开发分支交付。
- `git fetch origin dev` 后确认双方均为 `6b2f308da162599729f16f7722e2862f630b24ec`，其[仓库验证 / check](https://github.com/ChaceQC/CloudHelm/actions/runs/38568709752) 为 completed/success；该结论仅适用于入口提交。
- G01a [采集器和实际快照](docs/acceptance/p0/topology-s2413-r2.md) 已交付。最终窗口为 `2026-10-14T17:18:20.824859Z～17:18:26.374945Z`，8 项定向安全核验通过。s2413 为 6 CPU、约 15.51 GiB RAM、179 个容器（17 个运行）；四个候选目录均不存在，项目预算和未知占用上界仍未知。保留私有原始白名单 JSON，未加入公开输入。
- G01b [受控环境决定](docs/decisions/p0/s2413-development-envelope.md) 已交付：固定大小预分配 ext4、独立组后端/全部写入者、单宿主硬限与零新准入、三身份 mTLS、内网 DNS/独立预览、首次制品/数据库/许可前置均有明确方案；没有配置生效或产品验收结论。
- G02a [适用性方法及决定](docs/decisions/p0/reference-applicability.md) 已交付。`2026-10-14T17:16:42Z～17:16:45Z` 的 WSL 开发核验确认 36 个参照文件及 14 个历史来源文件；52 个映射字段分为 15 个复用、36 个受控编译和 1 个拒绝。旧解析器实际拒绝原文件的 `services.postgres.mem_limit`；保留资源、认证、网络、tmpfs 和迁移前置，产品部署仍不支持。
- 主会话核对两个方法和私有快照的当前 SHA-256 与报告相符，同步拓扑索引、支持矩阵 r3、参照规格 r2 和只读使用说明；新增 `closure_manifest.py`，准备独立收尾清单及历史来源核对，不修改旧 InputSet。
- G03a [最终覆盖复核](docs/acceptance/p0/remaining-scope-review-r1.md) 已完成：15 个工作包与 5 条出口均接入 G01/G02，未发现剩余 P0 准备方案缺口或新增权威冲突。该审查不代填最终来源绑定、CI 或统一裁决。
- 源码与决定提交 `2a371501cf93b7ef7547bbd0581830719fa97138` 已正常推送 origin/dev；其[仓库验证 / check](https://github.com/ChaceQC/CloudHelm/actions/runs/38611170547) 为 completed/success。该 CI 覆盖既有结构/UTF-8/锁/语法/契约/OpenAPI/前端构建，不代替环境/部署或人工验收。
- [收尾 InputSet](docs/acceptance/p0/input-set-closure-r1.json) 于 `2026-10-14T17:59:17+00:00` 固定该源码的 75 个公开输入；[最终结果](docs/acceptance/p0/validation-closure-r1.json) 于 `2026-10-14T18:00:44+00:00` 完成来源绑定。当前字节均匹配，四份历史清单的 20/25/36/62 条记录与各自源码一致；原 r1 的 17 条摘要因未记录 source_commit 保留该限制，不补造来源。
- 冻结后 `2026-10-14T18:00:39Z～18:00:42Z` 的参照核验仍为 36 个固定文件、14 文件历史来源和 52 个映射字段，原解析器实际拒绝 mem_limit，产品部署支持仍为 false。采集器、私有白名单 JSON、G01b 决定和独立审查的摘要与记录一致；没有重采拓扑或重跑历史接缝。
- [出口评审 r2](docs/acceptance/p0/exit-review.md) 完成 5 条当前准备出口裁决，P0 当前范围无剩余工作包。计划修订 10 指向下一待启动的 P1.1-01；累计实际人日及后续产品实施/取证量仍待估，不将代理墙钟或 P0 方案决定当作已完成的产品工作。

### 进行中

- 无 P0 准备开发或验证任务；P1 尚未启动。本记录与 InputSet/结果作为独立证据提交，沿用正常 dev 交付和既有 CI，不预写自身提交哈希或检查结果。

### 阻塞与风险

- 本轮 P0 准备工作无剩余阻塞。G03a 最终更新曾因指定模型服务端 token rate limit 中断，已由原 `gpt-6-astra / max` 代理恢复完成；未切换模型或由主会话代填审查。
- 旧 InputSet、供应商批次和 unknown 账本保留。只读事实、实施决定和产品生效分开记录；同机结果不能替代 P1.4 独立目标、物理配额、许可时间、预览或原生验收。

### 下一步

- 下一实施任务为 P1.1-01：在明确任务范围内细分真实 Hub API/单 worker、业务 schema/系统迁移、项目身份/权限和查询入口。当前控制方案不授予安装/部署或预算；实际资源、许可、数据库初始化与独立目标按所属门禁取证。

### 主要文件或模块

- `scripts/p0/topology_snapshot.py`、`reference_applicability.py`、`closure_manifest.py`；G01/G02 决定与验收记录、拓扑、支持矩阵、参照规格、P0 使用说明；本轮 InputSet/最终结果、出口评审、PROJECT_PLAN.md 与本进度。

### 验证

- 开发方法核验由各报告记录：采集器 8 项安全边界及两端真实快照；参照源码/历史 blob/字段分类及旧解析器实际拒绝。三个子代理交付均使用 `gpt-6-astra / max`，文档完成 UTF-8/本地链接/差异检查。
- 主会话在 WSL 用 `python3 -B -` 对本次 3 个方法及自己维护的文档检查：12 个 UTF-8 文件、3 个 AST、119 个本地链接通过，无行尾空格；`git diff --check` 通过。该步骤不运行模型、数据库、容器或旧接缝。
- 最终命令在 WSL 通过已锁定环境运行：`uv run --locked --offline --no-sync python -B -m scripts.p0.closure_manifest --verify docs/acceptance/p0/input-set-closure-r1.json`，以及同环境的 `scripts.p0.reference_applicability --historical-repository '/mnt/d/graduation project'`；另外以只读 SHA-256 核对记录的拓扑/审查证据及 Git 忽略状态。实际结果见上述 JSON，不把数据摘要核对写成重跑所有历史测试。
- 证据与出口写回后，WSL 窄检查确认 4 份最终文档的 85 个本地链接、2 份 JSON、结果/输入关联均有效，75 个冻结文件保持原摘要；差异格式检查通过。只复核本次写回，不再执行已通过的方法。
- 本地未重跑旧收费批次、数据库/容器接缝、前端构建或无关全量测试；CI 按既有必需工作流核对源码。s2413 未安装、部署、分配预算、变更配额/网络或清理镜像；WSL 没有构建新镜像，既有镜像不因本轮只读方法而视为已替代。没有 main 合并、tag 或 Release。

## 2026-10-14 · P0 剩余工作与同机开发组合收尾（进行中）

### 已完成

- 入口核对为干净的 `dev / 735ce66c79c25b8108d5ba3d4d4f7e1b5902b973`，逐项读取当前计划、P0.3 出口、六卡汇总和参照拓扑；未采用历史同名仓库的实现状态。
- 用户授权根据文档补全 P0，并指定子代理 `gpt-6-astra / max`；对独立目标的补充答复为“暂时都使用 s2413”。已先同步计划修订 9、D06 v4.7.1、索引 v4.7.2 及规范中的版本索引。P1 独立交付验收要求保留，本轮按一个共享宿主冻结开发组合。
- 收尾拆分为 G01a 环境只读快照、G01b 受控环境决定、G02a 首链字段/制品/计划适用性、G03a 独立出口覆盖复核和 G03b 主会话集成；负责文件与依赖见计划。
- `git fetch origin dev` 后确认本地与远端同为入口提交；入口提交的[仓库验证](https://github.com/ChaceQC/CloudHelm/actions/runs/38561710325) 为 completed/success。该历史检查只覆盖原候选。

### 进行中

- 按上述小任务补齐环境事实、具体控制方案及接缝适用性；不提前填写 P0 完成或产品可用。
- 指定模型的首次三个子任务遇到服务端 token rate limit，保留 `gpt-6-astra / max` 错峰接续；环境和参照代理已重新运行，出口审查随后接续。

### 阻塞与风险

- 暂无已确认的本轮实施阻塞；s2413 的具体路径/配额/已有占用/网络以本轮实际观测为准。正式独立目标按用户临时安排留在 P1.4 前置，不能用同机或 WSL 结果代替。
- 既有模型 unknown 账本、历史 InputSet 和旧 SDK 结果保留；新文档/方法产生新证据，不重跑收费批次。真实产品服务、配额生效、可信时间、预览与原生验收仍按所属阶段门禁执行。

### 下一步

- 完成三项并行小任务；由环境代理接续 G01b，然后依据最终集成版本进行窄验证、冻结公开输入并更新出口裁决。

### 主要文件或模块

- `PROJECT_PLAN.md`、本进度、D06/设计索引、`AGENTS.md`；后续产物路径见计划 G01～G03。

### 验证

- 已进行 Git 状态与公开文档只读核对，本轮六份范围/版本/计划文档的 `git diff --check` 通过；环境/接缝验证未执行，等待相应方法产出。文档变更不运行无关业务测试。没有远端系统修改、产品部署、P1 实施或人工验收结论。

## 2026-10-14 · P0.3 关键契约与出口评审（已交付；P0 统一出口未放行）

### 已完成

- 核对当前分支 `dev`、基线 `11aaca08b95a7cc3c70cb3dd020f94836383bfe0`；接续工作区已有的计划修订 7、进度草稿与 `decision_common.py`，不覆盖这些未提交改动。按当前仓库设计、计划和 A02/参照证据确定范围，不套用历史同名项目的实现状态。
- 计划修订 7 开放 P0.3-01～04，先拆为身份权限、迁移、资源、Task 控制、时间许可和预览六项不重叠任务；本轮子代理按用户指定使用 `gpt-6-astra / max`。
- `2026-10-14T10:56:23Z` 再次核对 WSL Ubuntu-24.04、内核 `6.18.33.2-microsoft-standard-WSL2`、仓库映射 `/mnt/e/Project/CloudHelm` 与 `uv 0.11.29` 可用。未读取或输出任何配置密钥。
- 第一批身份权限、资源占账、许可时间已由 `gpt-6-astra / max` 小任务交付。身份包括 20 项动作与当前授权先于去重；资源包括独立调整/未知占账和分维释放；许可采用 Hub 单调授权时间、固定旧 grant/首次接受窗口及失信封闭。主会话完成统一工程引用、Runtime/恢复续接、Release/环境和应急禁用契约；身份子代理已按统一 EngineeringRef 做一次集成对齐。
- 第一批提交 `e493db2a40e3f5833ecd0a4350d965484af0d6af` 已正常推送 dev，[仓库验证](https://github.com/ChaceQC/CloudHelm/actions/runs/38556156274) completed/success。它只对应该提交和当时 CI 覆盖范围；后续集成输入另行固定。
- 用户补充 Hub 与开发 Runner 也使用 `s2413`。已在拓扑/参照规格/支持矩阵明确记录同机组合与单宿主计量，现有交付候选不再被当作相对 Hub 的独立机器；另台正式交付目标与真实配额/网络/注册证据仍待后续安排。未执行 s2413 安装、部署或配置变更。
- 第二批迁移查询、Task 完成取消、预览访问已分别交付；主会话核对跨域字段，补上计划/配置修订/许可起始状态的一致性检查，导出包含 76 个定义的 JSON Schema。已准备只读 InputSet 冻结与统一窄检查入口，并将该入口接入既有“仓库验证 / check”；工作流范围说明同步更新，业务/原生/部署验收范围不扩大。
- 最终源码 `c8b5dfbc4aa554b943934548f192603739984636` 已正常推送 dev，其 [仓库验证](https://github.com/ChaceQC/CloudHelm/actions/runs/38558633071) completed/success。[本轮 InputSet](docs/acceptance/p0/input-set-decisions-r1.json) 于 `2026-10-14T11:44:39+00:00` 固定 62 个公开输入，再于 `2026-10-14T11:45:50+00:00` 取得 [最终结果](docs/acceptance/p0/validation-decisions-r1.json)：7 个模块、83 项固定检查全部通过，源码/清单/当前字节一致。
- [统一出口评审](docs/acceptance/p0/exit-review.md) 已逐项覆盖 P0.3、三组接缝/六卡、计划出口和 R21～R27，并记录第一次重估。P0.3 本轮决定/契约工作无剩余；人工人日未统计，可核验环境/验证窗口为 `2026-10-14T10:56:23Z～11:45:50Z`，不将代理墙钟折算人日。原 P0 5～8 人日的直接复用/现成资产/拓扑前提不全部成立，新总量及统一出口剩余保持待估。

### 进行中

- 无 P0.3 实现或验证工作进行中。六个指定模型的小任务和主会话集成已交付，输入/结果与本条记录一并归档到 dev；后续阶段没有自动启动。

### 阻塞与风险

- 本轮 P0.3 决定/契约范围无阻塞。统一出口已评审为未放行：Hub/Runner 的机器选择明确为 s2413，但受控路径与硬配额、安装注册/身份通道、网络/DNS/TLS、首链接缝适用性和另一台独立交付目标仍有缺项；可信时间/原生等实际证据依后续所属入口取证。责任及复核点见 P0-G01/G02 与出口表，不能由契约校验替代。
- 原生 Desktop、预览六组隔离、真实独立目标部署和人类验收没有本轮证据；旧模型 unknown 记录继续保留，不重跑历史收费批次。

### 下一步

- 按后续任务授权补充 P0-G01 的 s2413 受控资源/身份/网络及独立目标输入，并完成 P0-G02 的首链适用性复核，再更新统一出口。保留当前已选拓扑，不重复询问已确认的 Hub/Runner 机器选择。

### 主要文件或模块

- PROJECT_PLAN.md、PROJECT_PROGRESS.md、packages/contracts/p0/、docs/decisions/p0/、docs/acceptance/p0/exit-review.md、支持矩阵及接缝使用说明。

### 验证

- 开发检查均在上述 WSL 的锁定离线 Python 环境：`check_decision_core` 16 项通过；identity 初次 7 组通过，统一工程引用后于 `2026-10-14T11:15:15Z` 重查 8 组通过；permits 于 `11:11:06Z～11:11:15Z` 检查 7 组通过；resources 于 `11:11:38Z～11:11:44Z` 检查 16 项通过（日期均为 2026-10-14）。命令为 `uv run --locked --offline python` 配合对应脚本/模块，均退出 0。
- 以上是各自开发候选的类型、合成输入和纯函数检查，当时尚未固定最终集成 InputSet；后续以本节末的统一检查取得最终证据。未执行模型、数据库/容器、真实远端、浏览器或原生验收。
- 第二批开发检查：migrations 8 组、task 18 项、preview 9 组均以相同 WSL 锁定离线入口退出 0；迁移复核时间为 `2026-10-14T11:25:39Z`，预览最终复核为 `2026-10-14T11:34:26Z`。Task 在收紧未知 usage 的投影后仅重跑本模块；主会话在补充跨契约绑定后重跑 core，17 项全部通过。尚不把这些独立结果记为最终输入的通过。
- 固定前预检：62 个明确公开输入均为 UTF-8，21 个 Python 文件 AST、76 个 schema 定义与 7 个检查入口导入一致；18 份本轮 Markdown 的 168 个本地链接已核对，仅新 InputSet/最终结果两个文件按顺序待创建。未运行无关全量测试。Task 契约 370 行中前约 235 行为集中声明/关联校验，裁决函数均小于 60 行，按单一领域保留同文件；生成 schema 不计入普通源码规模。
- 最终命令为 WSL `PYTHONUTF8=1 uv run --locked --offline python -m scripts.p0.check_decisions --input-set docs/acceptance/p0/input-set-decisions-r1.json`，退出 0。Python 3.12.13、Pydantic 2.14.1、rfc8785 0.1.4；core 17、identity 8、migrations 8、resources 16、task 18、permits 7、preview 9。结构快照 SHA-256 为 `b2edad41ad6e57f22ff429617120803b49ea746ad0105a98f633315e1c6e6532`。范围仅为结构、固定合成输入和纯函数，不作为业务验收数量。
- 四份历史 InputSet 字节与入口基线完全相同，A01/A02/参照的 20/25/36 个输入按原 source_commit 用 `git show` 与 SHA-256 比较全部相符；旧 r1 无 source_commit，17 个摘要仅与本轮起始 `11aaca0` 的文件核对相符。没有重跑旧收费实验，没有操作原 unknown 账本。未构建新镜像，无本轮替代镜像清理；没有启动容器、执行迁移、部署 s2413、原生或人类验收。
- 最终文档收尾检查：19 份本轮 Markdown 的 188 个本地链接全部存在，62 个冻结输入保持原字节，结果记录与源 commit/schema 摘要一致，差异格式检查通过；此次仅核对文档/哈希，没有重复运行 83 项检查。输入、结果、计划修订 8 与出口结论随本条记录正常提交到 dev，文档提交的 CI 由同一工作流继续核对，不预填结论。

## 2026-10-14 · P0.1-A02 三项审查缺口修复（已完成所列范围）

### 已完成

- 核对基线为干净的 `dev / 009863bb268af106c453b0ef6443d8842ecd0923`，确认三项审查与实际代码一致。计划修订 6 明确 P0.1 完整出口未闭合，保留 P0.2 准备/冻结完成状态。
- 实施前记录原因和影响范围：旧恢复只重取完成结果，失败检查点未消费输入，断流通过条件过宽。预期保持当前业务身份、权限/费用不变量和历史证据，仅补齐新方法与组合证据。
- 五项方法已集成。WSL 锁定环境完成 25 个公开输入的 UTF-8/AST 和五个方法模块导入，无数据库或供应商出站；差异格式检查通过。SDK 结构化夹具按锁定版本的 `final_result` 工具输出修正，窄解析核对通过。
- 源码提交 `e7eded85a1ad24fbbcd1abc227cb667f94abda8f` 已推送 dev；新 [InputSet](docs/acceptance/p0/input-set-a02-r1.json) 于 `2026-10-14T04:09:51+00:00` 固定 25 个公开输入，再执行对应组合验证。完整结果见 [A02](docs/acceptance/p0/A02.md)。
- 四个 worker SIGKILL/同 executor 恢复场景通过：原 workflow/固定实验 Run 恢复、屏障 attempts=2；允许场景新 HTTP 1 次并取得 200/完整流/usage，取消、撤权、预算不足各 HTTP 0 次。旧 scope 修订不自动升级；合成 unknown 0.100 USD 保留。
- 消费合成 canary/25 MiB 后的异常安全验证、六组 SDK 二次请求门禁、14 个严格断流判定及 r2 真实流全部通过。r2 两场景各准确两请求、一 Operation/一 effect/counter=1；第二响应 200 后指定 ReadError、未完成流、缺失 usage 和 unknown 预留被严格核对。
- 实际新供应商 HTTP 合计 5 条；四条已知计算金额合计 0.0000817 USD，一条 unknown 保留 0.016768 USD，账单均为 null。旧 A01 四个原 ID 与一条 unknown 仍在；夹具和合成预算 hold 不混入供应商统计。
- `2026-10-14T04:18:54.600340+00:00` 只读快照及各方法脱敏 JSON 保留在被忽略的 `.thesis-work/runtime-data/a02-*.json`；原 SQLite journal 未删除。随后定向移除本轮 cloudhelm-p0 PostgreSQL 容器及网络，`2026-10-14T04:24:21Z` 后核对项目容器列表为空；未构建新镜像、未删除其他项目镜像或使用全局 prune。清理不表示 unknown 结算或释放。

### 进行中

- 无。所列实现、定向验证、证据冻结及 dev 交付已完成。五个 `gpt-6-luna / max` 小任务的边界和结果见计划及 A02。

### 阻塞与风险

- 三项修复的有限组合无实施阻塞；本轮 tmpfs 数据库已清理，后续不能凭快照补造在线对象。原本地模型 journal 与 unknown 占账不能删除或伪造为已结算，不重放已执行固定收费批次。
- P0.1 完整退出条件、P0.3 与 P1 尚未放行；独立机器、物理资源、原生 Desktop 和人工验收未执行。

### 下一步

- 下一待开放任务为 P0.3-01～03，消费 A02 新证据和 P0.2 冻结输入，逐项核对 P0.1 全包限制与 P0 统一出口；本轮不进入 P1。

### 主要文件或模块

- PROJECT_PLAN.md、scripts/p0/ 恢复/SDK/检查点/断流方法、integrations/seam_stream.py、对应决定/使用/验收文档。

### 验证

- 方法开发检查：锁定 WSL 环境严格断流的 12 个合成断言检查通过；Agent 默认 structured output 为 tool 模式，固定 function_call 夹具的校验修复/摘要解析核对通过。它们不是供应商或数据库组合通过证据。
- 固定候选后运行 `check_admitted_paths.py`（6/6）、`check_checkpoint.py`（消费后成功/失败安全）、`check_stream_assertions.py`（14/14）、`probe_admitted_recovery.py --live`（4/4，真实 HTTP 1）、`probe_admitted_stream.py --live --live-revision r2`（严格两场景通过，真实 HTTP 4）。命令均在 WSL 锁定环境用 `uv run --locked --offline python`；未重跑参照、生产、原生 Desktop 或无关业务全量测试。
- 最终新 InputSet 25 个文件与源码/当前字节一致；旧 A01 20 个输入与其历史源码 commit 一致（不要求已修改的当前文件匹配旧版本），参照 36 个和旧接缝 17 个当前输入保持原字节；45 个已改文档链接及精确费用汇总核对通过。方法版本/公共 API 修正后才取本轮证据，不追认旧失败路径。
- 源码 e7eded8 和输入/证据提交 `3d58688e4824bd602457d8686dfde1741d983f19` 均已正常推送 origin/dev；交付后工作树干净。源码的 [仓库验证](https://github.com/ChaceQC/CloudHelm/actions/runs/38509954309) completed/success；文档提交触发的检查异步运行，不预填结论。CI 仅覆盖结构、契约、锁和构建，不代替上述运行取证或产品验收。main 未合并，未创建 tag/Release。

## 2026-10-13 · P0.1-A01 与 P0.2 交付（已完成）

### 已完成

- 所选P0.1薄适配及P0.2-01～04的参照、独立方法、九检查点、拓扑与支持矩阵已按实际范围交付，详见下方实施结果、A01报告和参照validation-r1。
- 源码提交为 `6dd8b605a5cc4b7b641cc0f9b4f2633614c6e757`；A01的20个公开输入和参照的36个输入分别冻结到两个新InputSet。冻结工具逐字节比较工作树与该Git提交，既有r1历史输入不改写。
- 四条真实请求账本已导出到被忽略的 `.thesis-work/runtime-data/a01-ledger-snapshot-r1.json`，其中一条仍unknown；原SQLite request/usage journal也保留。临时数据库清理不被写成未知费用结算或释放。
- 2026-10-13T08:23:57Z 前完成本项目隔离P0数据库及参照三容器/网络/合成卷的定向移除；未清理其他项目。三份早期候选镜像ID在操作时已不可用，定向删除返回NoSuchImage，没有实际删除计数；最终backend c5aae384… / frontend 83523611…和digest固定基础镜像保留供当前候选复核，未使用全局prune。

### 进行中

- 无。本轮所选实施、输入冻结、开发分支交付及对应检查已完成。

### 阻塞与风险

- 本轮所选范围无实施阻塞；P0.3尚未开放，P0统一出口及P1仍阻断。实际Hub/Runner分配、s2413路径/配额/网络身份、DNS/TLS和许可误差有明确责任/门禁，见支持矩阵；未执行远端部署、原生Desktop或人类验收。

### 下一步

- 下一待开放任务为P0.3-01～03统一契约与阶段出口，消费已冻结输入和未决项；本轮不擅自跨入P1。

### 主要文件或模块

- PROJECT_PLAN.md；docs/acceptance/p0/A01.md与input-set-a01-r1.json；docs/acceptance/reference/、docs/implementation/reference-chain.md、docs/decisions/p0/topology.md、docs/acceptance/support-matrix.md；源码及方法由InputSet定位。

### 验证

- 定向运行结果：权限/计价/安全检查点/等待事务、真实流与实际Operation续接均通过；最终参照baseline43/43、seed3/3、API重启持久化2/2、停库拒绝2/2。只在代码、方法或环境变化后重取对应证据；原六卡不无故重跑。
- 初步检查通过144个UTF-8公开文本、源码AST/契约导入、OpenAPI一致性、入库排除规则与暂存差异格式；归档无修改。最终InputSet/文档链接及GitHub结论在开发分支交付后补记，不预填。
- 冻结后最终静态检查通过146个UTF-8文本、36个Python源、151个文档链接，两个InputSet的20/36个文件均匹配SHA-256且与源码commit逐字节一致；OpenAPI导出与实际app一致，docs/archive无改动。账本快照、截图、.venv/node_modules及构建输出被忽略。
- 源码6dd8b60与冻结记录a17aa5d已推送origin/dev；a17aa5de88f3808cda64e10a55a113b083fecd71对应[仓库验证](https://github.com/ChaceQC/CloudHelm/actions/runs/38371218951) completed/success，必需job/check为check。本次仅正常dev提交推送，main未合并，未创建tag/Release；该检查范围为结构/UTF-8/忽略、锁/语法/契约/OpenAPI和前端构建，不代替运行/产品/人类验收。本条后续文档提交仍由同一工作流核对，不预填其结论。

## 2026-10-13 · 接续中断任务（进行中）

### 已完成

- 读取引用会话“完成 P0.1 并实施 P0.2”，确认上游 502 中断；当前 dev/HEAD=011eaaf，承接未提交的官方计价、设计澄清与参照需求文件，保留已有修改。
- 复核当前计划开放范围仅为 P0.1-A01 和 P0.2；继承真实自定义模型探测及 s2413 只读拓扑核验授权，凭据不输出。

### 进行中

- 按独立文件分工：当前权限/金额预留、允许内容检查点、便签参照后端、便签参照前端、独立验收资产、s2413 只读拓扑核验。开发子代理使用 gpt-6-luna/max；主会话集成真实供应商流、冻结证据和提交推送。

### 阻塞与风险

- 前次结果尚未集成验证；旧卡、旧输入和前次进度不追认为本轮通过。
- 真实 DNS/TLS、原生 Desktop 及人类结论按实际证据登记；缺少时只阻断对应入口。

### 下一步

- 完成当前门禁与安全引用薄适配，执行有界供应商副作用流和 DBOS 恢复检查；构建参照并核验独立断言，冻结九检查点与支持矩阵。

### 主要文件或模块

- integrations/、scripts/p0/、examples/standalone-project/、docs/acceptance/reference/、docs/implementation/、docs/decisions/p0/。

### 验证

- 本轮运行验证未执行：已完成交接、工作树及输入只读核对，正在实施。本轮不重跑已保持不变的旧实验。

## 2026-10-13 · P0.1-A01 与 P0.2 实施结果（冻结收尾中）

### 已完成

- 承接中断会话留下的官方计价和文档，完成当前 Task/Run/权限/控制/有效输入门禁及逐次模型金额预登记；Gateway 门禁与业务副作用共享同一 PostgreSQL 事务。官方费用与供应商账单独立，未知仍占账。
- 完成引用检查点及公开 DBOS 薄适配；实际秘密 canary 与25MiB对象只在step内存消费，成功/安全失败/重取与保留检查通过。
- 自定义供应商 gpt-6-luna/max 新增4次真实流式请求；两场景均1 Operation/1 effect，重复回调及断流核对不重发。2026-10-13T07:16:39.118684Z～07:18:32.994413Z 的业务请求记录中3条取得完整usage，按官方价计算0.0000599 USD；第四条断流费用unknown、保留0.016768 USD占账，账单null。
- 同事务持久 wait、事件、WorkflowBinding、新Run和DBOS入队，取消/撤权/旧修订/异摘要/入队失败回滚通过；两个真实供应商Operation完成0新增请求的续接。应用层再次核对后newRun=succeeded/continue_required、Session=idle、Task保持active，authority与Run一致。
- 完成React/FastAPI/PostgreSQL/Alembic全栈便签参照、独立需求与HTTP方法、实际OpenAPI、依赖锁及digest固定的构建；正式断言不进入候选构建上下文。历史来源commit/子树重新读取核实。
- 最终参照候选 baseline43/43，seed3/3，API重启后持久化2/2，数据库停止拒绝2/2；线性两迁移单根/head。缺迁移拒绝在r1.0方法下2/2；最终浏览器CRUD、HTTP503错误和表单保留取得观测。
- 定向修复实际发现的Vite公告（6.3.5→6.4.4，audit0项）与数据库/DNS等待过长；旧候选和错误方法顺序轮次保留，不追认为通过。
- s2413只读SSH核验成功，登记独立交付机器候选；WSL/实际机器、设计预算/实测容量、未核验配额/DNS/TLS分别记录。九检查点与支持矩阵已建立。

### 进行中

- 固定源码commit并生成两个新InputSet，收尾仓库检查、只针对本项目的镜像/容器清理及dev提交推送。

### 阻塞与风险

- P0.3仍未实施，P0统一出口与P1不放行。s2413项目路径/配额/网络身份、DNS/TLS、可信时间误差、真实交付、原生Desktop与人类结论待对应门禁；没有本轮独立部署授权。
- 默认未经裁剪的PydanticAI DBOS持久包装已决定不支持，采用公开workflow/step薄适配；不推定跨版本、多worker或容量支持。

### 下一步

- 完成不可变输入与开发分支交付；随后待开放任务为P0.3-01～03的关键契约、可信时间/预览及统一出口评审，不擅自启动P1。

### 主要文件或模块

- integrations/门禁/计价/安全引用/续接/Gateway/stream；scripts/p0/对应方法；examples/standalone-project/；docs/implementation/、docs/acceptance/reference/、docs/decisions/p0/及支持矩阵。
- 代码规模已评估：admission/continuation的长文件主要集中DDL、应用事务SQL、幂等和输入校验；本轮保持单一接缝职责。它们不是产品模块结构，进入P1时按领域所有权拆分，不为行数机械搬迁影响当前取证。普通源码和声明式SQL的口径分开，锁、生成OpenAPI、依赖和构建产物不计普通实现规模。

### 验证

- gpt-6-luna/max小任务代理完成各自窄验证，主会话消费实际Operation集成；完整命令、固定输入、失败及最终结果见A01与reference/validation-r1，不跑未改变的旧卡或无关全量测试。
- 首次live续接断言把包含should_enqueue的原/重投回执整体比较而失败，修正稳定身份比较后通过；后续补齐应用层ack再验证，0额外供应商请求。
- 集成只读复核后定向补齐供应商usage超请求预留上限时的事实保存/闭锁、带证据的迟到unknown核对及完整scope冲突。合成验证通过；没有改写实际第4条unknown或增加收费请求。参照SafeError/OpenAPI同步后重建最终镜像，baseline/seed/持久化/停库拒绝分别43/3/2/2全部通过。
- 最终输入哈希、入库范围、OpenAPI一致性、源码/文档检查与GitHub对应提交检查在冻结后记录，不预填。

## 2026-10-13 · P0.1 出口补齐与 P0.2（进行中）

### 已完成

- 已核对当前 dev、起始提交 011eaaf 和干净工作树；读取当前计划、进度、六卡汇总及权威设计入口。
- 用户授权完成 P0.1 权限/费用与检查点接线、供应商副作用工具流，并随后完成 P0.2；明确费用按官方模型价格计算。
- 已更新任务计划，拆分官方计价、当前门禁/安全持久边界、供应商副作用流与固定参照/拓扑切片；P0.3/P1 尚未开放。

### 进行中

- 费用规则澄清、接缝薄适配和已有参照资产核验。主会话负责计划、设计同步、集成验证和 Git；小任务由 gpt-6-luna/max 子代理执行。

### 阻塞与风险

- 现有探测代码尚未接通本轮所要求的完整门禁与检查点路径；不得提前标记出口通过。
- 独立正式验收责任人、真实独立交付机器及 DNS/TLS 输入须核验；缺失时只阻断依赖入口，不以 WSL 代替。

### 下一步

- 冻结官方价格及实际 usage 计价口径，完成薄适配，形成新固定供应商输入；核验已有参照源码和验收资产。

### 主要文件或模块

- PROJECT_PLAN.md、PROJECT_PROGRESS.md、scripts/p0/ 及本轮实际形成的费用/持久边界适配；P0.2 资料待核验后建立。

### 验证

- 本轮运行验证未执行：正在确定固定输入和改动范围。已只读确认工作树、历史证据和官方价格页面；未读取或输出配置密钥。

## 2026-10-13 · P0.1 隔离接缝实施

### 已完成

- 核对 v4.7/v4.7.0、P0.1-01～07、当前 dev 分支及干净工作树；实际基础提交为 c7da7fb。
- 核实 WSL Ubuntu-24.04（Ubuntu 24.04.4 LTS）、Linux 6.18.33.2-microsoft-standard-WSL2、仓库映射 /mnt/e/Project/CloudHelm、uv 0.11.29、Docker 29.1.3 和 Compose 2.40.3 的现有环境。
- 用户授权真实模型探测使用当前 Codex 自定义服务配置，模型 gpt-6-luna、reasoning max；凭据仅在请求步骤内解析，不进入输出、持久历史或 Git。
- 按用户要求更新 AGENTS.md：随版本推进定向删除已被替代且无运行/验证/回滚引用的早期开发镜像，记录清理范围和结果。此时尚无本项目早期开发镜像；不对其他项目执行全局清理。
- 已建立根目录 uv 隔离工程及实际锁文件、固定 digest 的 PostgreSQL 16.13 临时 Compose、只读脱敏诊断、公共输入哈希入口、Runtime 契约草案和使用说明；不存在空业务服务。
- SDK-01 已按当前设计复核并定向验证：四处同步异常、async run_sync 均整体回滚；成功丢回执重投返回原结果，异摘要拒绝；Task 版本 7→8、AgentRun 版本 3→4，status=succeeded 与 outcome=submitted 分开保存。运行身份和摘要见 docs/acceptance/p0/SDK-01.md。
- 完成 SDK-03/04 隔离 SDK/Gateway/DBOS 路径：完整延期结果与合法历史、混合批次拒绝、accepted 回执独立保存、原 Run 恢复/新等待 Run 续接、早到/重复结果均有观测；最终 1 Operation、1 effect、counter=1。供应商副作用工具流及产品接线仍未验证。
- 完成 SDK-05/06 固定恢复与控制实验：同 executor SIGKILL 后恢复原 workflow，write_count=1；公开 resume 安全收尾一条旧跨 executor 合成记录；逆序入队观察 priority 1 先于 9，模型队列占满时 control 1044.5ms、查询 5.3ms、取消 4.8ms。DBOS 默认参数/错误会被持久保存，未经裁剪的秘密/无界历史入口保持阻断。
- 完成 Compose 两环境参数映射及拒绝清单，完成 loopback 在线签名许可、SQLite 账本和真实 counter 子进程接缝；重投、失联、丢回执、停止核对、旧许可和时间边界有直接证据，详见 compose-remote.md。
- SDK-02 累计 18 次非流式及 1 次实际 stream=true 请求；C2 的 6 次和 C3 的 1 次均在发送前确认持久预登记。C3 返回 HTTP 200/text-event-stream，完整 SSE 完成，usage input=3543/output=11/total=3554；响应 ID 与 x-request-id 已落盘，原输入再次启动在出站前阻断。用户确认 s2a 请求记录可见，先前同步由 Agent.run 的非流式调用造成。
- 六张卡、逐能力复用矩阵、受阻入口/责任/复核期限和额外适配 P0.1-A01 已汇总；固定 17 个公开输入的 SHA-256 清单为 docs/acceptance/p0/input-set-r1.json。未代填人工验收，P0.1/P0 完整出口未放行。

### 进行中

- 本轮隔离实现、集成及 dev 分支交付已完成；P0.1 完整出口仍因下述受阻项未通过。主会话负责环境、契约、集成和 Git；五个 gpt-6-luna/max 子代理分别完成有限分工，文件不重叠。

### 阻塞与风险

- P0.2 尚未执行；首条参照输入、独立验收资产及独立机器/DNS/TLS 不作为本次已就绪输入。Compose/远端实验仅覆盖 WSL 隔离接缝，不构成独立交付验收。
- 未取得模型供应商 usage/金额时保存 unknown/null，不以本地估计补齐。正式费用策略、时间误差依据和阶段统一出口继续由 P0.3 决定。
- 模型旧候选 12 次不追认预登记，后续 C2/C3 分别有 6/1 次新候选实际证据；共 19 次是本轮探测计数，不是金额预算。真实价格/金额、产品级费用与权限门禁、官方 DBOS 请求/检查点组合仍待接入；未知费用保持 unknown/null。
- 供应商副作用工具流/断流及产品等待续接、默认检查点允许内容控制、真实物理资源/容量和可信时间仍有受阻项。六卡中有限切片成功不表示整卡、P0.1 完整出口或 P0 阶段已通过；责任和下一门禁见接缝汇总。

### 下一步

- 按后续授权先执行 P0.2-01，取得可核验参照、固定输入及独立验收资产；对照 P0.1-A01 与 P0.3 决定正式支持范围及受支持薄适配，不擅自启动 P1。

### 主要文件或模块

- pyproject.toml、.python-version、uv.lock、infra/p0/、scripts/p0/、packages/contracts/p0/、docs/decisions/p0/、docs/acceptance/p0/；仅为隔离接缝资产，不创建空业务服务。

### 验证

- 环境诊断于 2026-10-13T03:51:55Z 开始核验；2026-10-13T04:03:44.723695+00:00 的只读诊断确认数据库 16.13 可达、容器 healthy、268435456 bytes / 1 vCPU 上限；uv lock --check 成功。
- SDK-01 更新候选的 WSL 命令退出码 0；本卡复核记录截至 2026-10-13T04:31:30Z，固定 run_id=353e9a65811a，request_digest=sha256:15e76be9e1579e44a56e5e898cc74dc50a3e30620ae90ccf0629be8b4acdd54a。
- 最早的集成语法快照在 remote_probe.py 编写期间发现 finally 语法错误，负责代理已修复；2026-10-13T05:05:24Z 集成检查通过 91 份 UTF-8 文本、12 个 Python 源、115 个文档相对链接及 Runtime 契约导入，未检测到凭据形态字面量；归档无改动，运行 journal/.venv 被忽略。
- C3 真实流式出站预登记为 2026-10-13T05:08:48Z，usage/响应元数据完成为 2026-10-13T05:08:53Z。固定输入清单随后冻结；各历史卡仍只覆盖各自候选和方法，不把最终清单追认为早先版本全部通过。
- 最终复用仓库验证工作流中的结构/UTF-8/忽略规则与 P0 源码/契约检查，两段实际脚本均通过；17 个公共输入哈希与冻结清单完全匹配，暂存差异格式检查通过。代码规模按 P0 Python 探针源统计，排除锁文件/生成 schema；长脚本集中容纳实验 DDL、固定故障场景和执行夹具，已评估其卡片职责边界，正式 A01 接线按权限、持久化和协议职责拆入实际模块，不机械重排本轮取证方法。
- 取证窗口从 2026-10-13T03:51:55Z 起，实际单人投入不从并行代理时长推算；原 2～3 人日保持设计量级，新增适配及剩余人日待估。
- 实现提交 03cbc3163f9274fee5f3e6d349f78a0946dbd334（feat: 实现P0.1隔离接缝并记录SDK支持边界）已推送 origin/dev；[对应仓库验证](https://github.com/ChaceQC/CloudHelm/actions/runs/38350701970) completed/success。该检查覆盖结构、UTF-8、忽略、锁定依赖/语法和契约导入，不表示六卡整体验收通过。
- 本轮临时 PostgreSQL 容器及其项目网络已通过本项目 Compose down 定向移除，tmpfs 合成运行数据按实验结束清理；真实模型 request/usage journal 保留在被忽略的 .thesis-work/runtime-data，未删未知费用记录。没有本项目旧开发镜像需要删除，固定 PostgreSQL 基础镜像供同版本复现保留。
- 未执行无关业务测试、Desktop 原生验收、远程部署及人工验收；本次只开放 P0.1。

## 2026-10-13 · 建立执行计划与开发约定

### 已完成

- 依据当前 v4.7 总体设计、索引及 D01～D06 v4.7.0 建立 PROJECT_PLAN.md，保留 D06 的 P0～P6、31 个工作包编号和原估算，拆为 72 个唯一子任务，细化输入、前置依赖、行动、拟定产物/代码落点、必要验证和退出条件。
- 明确 P0 待启动及首个入口 P0.1-01；细化六张 SDK 卡、参照/正式验收资产/实际拓扑、许可时间与预览决定，列出责任角色及未决输入的具体阻断范围。
- 补齐 P1 集成顺序、P2 六组预览证据、P3.4 实验冻结、P4 应急/恢复门禁、P5 运维闭环、P6 双端/两档容量和最终交付；映射 R01～R27 及 D06 专项验收要求。
- 保留 125～203 人日及原缓冲量级为规划基线，子任务待估；适配、资产建设、机器/证书、支持组合和适配器扩展单列，要求 P0/P1 出口重估。
- 按用户要求补充 AGENTS.md：README 面向使用者，提供项目介绍、真实可用能力、安装/配置/使用说明及必要导航，项目日志、阶段/测试/提交流水进入进度或验收记录。
- 按用户补充要求明确本机开发使用 WSL，并同步 P0 的发行版/内核、仓库映射、工具链与 Docker/Compose 环境核验任务；WSL 开发证据与双端原生及真实远程交付验收分别记录。
- 同步规范中的计划存在状态、README 现状与执行计划导航；仓库验证必需文件清单加入 PROJECT_PLAN.md。

### 进行中

- 无业务实施任务正在执行；本次为计划和规范文档任务，P0 接缝与环境核验尚未启动。

### 阻塞与风险

- 本次计划编制无输入阻塞；具体组件补丁版本、可核验参照源码/初始 commit、需求/独立验收资产、实际机器/DNS/TLS 及客户端组合仍待 P0 核实，不能声明就绪或支持。
- 缺少某项输入只阻断依赖它的入口；候选组件与参照来源核验可独立准备。首条必需链路缺项时不能宣布 P0 完成或整体开放 P1。
- 所有拟定工程/证据路径均为后续落点，不表示已创建业务模块、完成 SDK 集成、获得人类批准或产品验收。

### 下一步

- 执行 PROJECT_PLAN.md 的 P0.1-01：核验候选组件、受支持接口、隔离验证环境和最小诊断方案，形成带来源的候选矩阵；可同时准备 P0.2-01 参照来源核验。
- P0 启动时指定实际负责人、输入/环境授权和下一检查点；随后按计划执行六卡与三组接缝，不从本次文档提交推断通过。

### 主要文件或模块

- PROJECT_PLAN.md、PROJECT_PROGRESS.md、AGENTS.md、README.md、.github/workflows/check.yml。
- 当前设计正文和 docs/archive 保持原设计基线；本次没有业务源码、依赖或运行环境变更。

### 验证

- 本地文档检查于 `2026-10-13T03:45:28Z` 汇总；使用 Windows PowerShell 的 UTF-8 输入/输出和本机 Python 3.12.9 只读核验文档，不锁定项目 Python 版本，也不作为 WSL 工程运行证据。
- 通过只读 Python 文档检查：5 个变更文件可严格按 UTF-8 解码、文档相对链接存在；31 个工作包及 72 个子任务编号唯一，六张 SDK 卡和 R01～R27 有落点；各包原估算与 D06 一致，合计 125～203 人日。
- 通过前置依赖核对：保留 D06 原工作包依赖，编号引用有效，无后向依赖或循环；人工核对 P0 草案/统一出口、P1 界面集成及 P2/P3/P4 的实际取证门槛。P1.5 的稳定 API 前置统一列在依赖字段中。
- 本地复用 `.github/workflows/check.yml` 的仓库检查脚本，通过必需文件、UTF-8 文本、入库范围及 `.thesis-work/` 忽略规则；工作区 `git diff --check -- . ':!docs/archive/**'` 通过，设计正文及归档无本次差异。
- 只暂存并审查本次 5 个文件，暂存差异格式检查通过；提交 `78fe801`（`docs: 建立完整执行计划并明确README与WSL开发约定`）已推送 `origin/dev`，该次推送后工作树干净、开发分支与远端一致。
- 提交 `78fe801` 的 [GitHub 仓库验证](https://github.com/ChaceQC/CloudHelm/actions/runs/38343308154) 已成功；该结论只覆盖结构、UTF-8、忽略/入库范围和提交格式，不表示 WSL 工程、SDK 接缝或系统功能通过。本条实际证据作为后续正常开发提交保存，后续提交的检查结论以对应运行记录为准。
- SDK 实验、业务测试、容器/构建、远程部署、研究及人工验收均未执行：本次仅建立执行计划、README 维护约定和 WSL 开发约定。

## 2026-10-13 · 仓库初始化与开发规范（此前记录）

### 已完成

- 只读核对当前总体设计、详细设计索引与 D06；确认已有阶段及工作包安排，任务级执行计划仍待建立。
- 核实本次 GitHub 仓库安排：用户已删除历史公开仓库，并明确授权建立新的公开 `ChaceQC/CloudHelm`。
- 确认 `.thesis-work/` 为本地工作目录，必须从 Git 与 GitHub 提交范围中排除。
- 已建立开发规范、README、忽略规则、文本属性、GitHub 协作说明和仓库验证工作流。
- 已在本地初始化 Git，当前开发分支为 `dev`；已创建公开 `ChaceQC/CloudHelm` 并将 `origin` 连接到 `https://github.com/ChaceQC/CloudHelm.git`。
- 已形成初始化提交 `abc75e5`（`chore: 初始化CloudHelm开发规范与Git仓库`），从同一提交建立并推送 `main`、`dev`；GitHub 默认分支为 `main`。
- 已启用并读取核对分支保护：`main` 要求 PR、严格必需检查 `check`（GitHub Actions，app ID 15368）、管理员同样受保护、禁止强推和删除；`dev` 禁止强推和删除，不要求 PR 或推送前状态检查。
- 已补全软件语义版本、中文提交、代码规模建议、UTF-8 文件操作、子代理分派和自定义位图提供方等开发约定。

### 进行中

- 无业务实施任务正在执行；本次开发规范与仓库初始化已经完成，P0 尚未启动。

### 阻塞与风险

- 当前尚无任务级 `PROJECT_PLAN.md`、首条链路可核验参照源码及独立验收资产，不能开始未经拆分和输入确认的业务实施。
- 本次仓库初始化无阻塞；公开可见性、默认分支、推送和保护配置均已核对。

### 下一步

- 下一项开发任务：建立 `PROJECT_PLAN.md`，把 D06 的 P0.1～P0.3 拆成可执行任务，明确输入、产物位置、前置依赖、代码落点、必要验证和阻塞决定；随后细化 P1 的任务与集成顺序。

### 主要文件或模块

- `AGENTS.md`、`README.md`、`PROJECT_PROGRESS.md`。
- `.gitignore`、`.gitattributes`、`.github/workflows/check.yml`。
- `docs/GitHub协作与合并流程.md`；原有总体设计、`docs/design/`、`docs/architecture/` 与设计历史 `docs/archive/`。

### 验证

- 已只读确认本地 Git 和 GitHub CLI 可用，GitHub 账号已登录；读取身份和仓库元数据时未输出实际密钥。
- 创建前已确认用户删除历史仓库后，`ChaceQC/CloudHelm` 不存在，可以建立新的公开仓库。
- 已实际创建公开仓库并连接 `origin`；已确认 `.thesis-work/`、`.env`、依赖和构建目录被忽略，依赖锁文件、设计归档及架构图没有被误排。
- 已确认历史设计目录的 Git 文本规范化关闭，避免改变归档字节与原 SHA-256 清单。
- 本次只运行与文档及仓库建立有关的内容、路径、忽略规则和 Git/Actions 检查；不运行无关业务测试。
- 已执行工作流中的仓库结构、UTF-8 和入库范围检查，通过；暂存文件共 64 个，未包含 `.thesis-work/` 或其他被忽略文件。
- 已核对 46 个设计归档文件的暂存字节与磁盘原文件，一致；当前提交差异格式检查通过。
- 初始化提交 `abc75e5` 的 GitHub Actions 均成功：[main 检查](https://github.com/ChaceQC/CloudHelm/actions/runs/38341193245)、[dev 检查](https://github.com/ChaceQC/CloudHelm/actions/runs/38341193563)，job 名称均为 `check`。
- 已通过 GitHub API 读取核对公开可见性、默认 `main`、两条分支保护，以及必需检查的严格模式与 GitHub Actions 来源。
- 本条收尾记录及规范补充通过正常开发分支提交与推送，后续提交由同一工作流重新检查；结论以其对应 commit 的实际运行记录为准，不预填未来检查结果。
