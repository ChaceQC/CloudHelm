# A00c 单 Agent 任务与操作账本固定输入

交给 D01/D02 和 G01 使用。依据用户指定的 `docs/architecture/2026-11-19-agent-architecture-detailed-design.md` §10.1、§10.5、§10.6（源稿 SHA-256 `7078d0c9c8548e2ebd8f76adf74d678df352280635022fe0746107287b283370`）。[独立断言](independent-assertions.md) `a00c-independent-assertions-r1` 的正负预期由独立验收负责人在取证前写定，交接 SHA-256 为 `85cd843f1331fe6a69553fc2d323881c944f7bfb26a4ebb70f6dd5335b5cfd54`。候选仓库不含该资产。

| 固定输入 | 来源、预期和负责人 |
|---|---|
| Task 草稿 | [A00a 隔离安装](../../development/a00-isolated-install.md)下的独立项目 `a00c-notes`，Task `f573e978047e415ea084e25c3de0d720`（`draft`，Task/控制/输入有效性修订 `2/0/1`）。创建命令 `ac4f4a989d384db88bf5f78e70d7fad6`，绑定命令 `9dac939c1c4b4f4c93603bc1748c068e`。开发负责人启动时登记 WorkItem、单开发 Session 和 Run；草稿没有这些运行身份。预算为 USD `0`，供无模型取证。G01 在合入后的版本用实际批准额度登记同一场景，记录新 Task 与本草稿的对应关系。 |
| 受管源码 | 导入操作 `source-import-5b1025904ff54f17943b7f4103e6906e`；来源 `source-5b1025904ff54f17943b7f4103e6906e` / 修订 `1`，基准 `refs/heads/main` → `7ec1ab83bdc963b4d6521d832f7f53f7a874dc11`，Git 树 `44fb9a050992e7e0e858f8eee535e0d8d151b628`。与 A00b 的 B0 内容相同，受管项目及登记独立。 |
| 草稿 InputSet | `reference-engineering-7a83fcd09ae3464ce7dbf2bab4571c0c22cbfc27c258bab50bd3dea542a7c388` / `p1-reference-task-input-r1`，引用摘要 `sha256:bca276d8eb40ad7638d1a256582622f8b8504d870f45f2c1bff486c982b0bf01`。包含 `reference-requirements-r1`、`reference-public-assets-r2`（登记 bundle `sha256:5142b355dcf055da498e8705864c789e82c15b656f1ffe3e4ca8c7afc5b0855f`）和禁用的人测策略；A00c 新断言单独冻结。独立验收负责人在 G01 另登记新增断言、实际方法、制品和环境，重新固定适用的 InputSet。 |
| 变更与交权 | `GET /api/notes` 增加选填 `q`，按标题的 ASCII 大小写不敏感字面子串筛选，保留原 ID 升序、依赖和数据库迁移。开发范围是列表接口及其契约快照。具有写入权的人类只把 `frontend/index.html` 的标题改为「便签交付 · A00c」；执行器固定交还差异和新代次，下一 Run 保留该改动，旧 Run 写入被拒绝。由交接负责人登记真实交权和交还。 |
| 失败与返工 | 独立方对第一轮区分大小写的对照候选使用固定三条标题，`q=AL` 若只得到第二条，保留该准确候选的真实失败或审查问题。修复后应按原 ID 顺序得到前两条，交还标题仍在，形成新候选和独立复验记录。既有[参照 HTTP 资产](../reference/README.md#新资产登记及历史边界)继续检验原有行为。人工交权不生成通过或跳过人测的记录。 |
| 实际可交付目标 | [已核对的独立 Debian 机器](../p1/archive-closeout.md#原身份与只读方法)，原 Remote 安装 `installation-3c8559b10db945dc8edb66507b0e1723` 用于定位该机器。UTC `2026-11-19T05:05:52.784697+00:00` 严格 SSH 核对为 Debian `13` / `x86_64`、内核 `6.12.107+deb13-amd64`、6 CPU、`16653266944` 字节内存、Docker CLI `26.1.5+dfsg1`、Compose `2.39.4`；原有界存储仍挂载。拟用新环境 `a00c-delivery` 消费本 Task 的固定三角色制品。交付负责人须先核对旧安装和资源隔离、登记本组合 Remote 身份/配额/时基与起始状态，再按已批准的准确 Release、配置和 DeploymentPlan 验证迁移、服务更新和连续健康。未创建新环境、绑定、部署或许可；只影响 G01f。 |

**账本输入。** 资源负责人使用两个真实构建操作的三个观察时点。以下事实分别绑定原 Task 与执行器，供核对或构造隔离回放输入；不得登记成 A00c 草稿或新构建的回执，也不得重启原操作。

| 事实 | 准确身份与独立判定依据 |
|---|---|
| 成功（S） | [E07d 真实构建](../p2/p2-4-02-e07d.md#成功构建与固定候选)：`build-operation-73a6eb09681a454ea17ca41ef20a6f0f`，Task `de0cc97f63884f2397887880adb0a111`，最终提交 `59e331eb19417ccf02f47d093e9ed99b36370f32`。请求摘要 `sha256:d1aead942e75c83c2a42217106486addfdd4f12f9927ca03beeafe5c1429eb82`、输入摘要 `sha256:fda52c281b72a3a234f8f93f0b2a4a70b341acf1c3136827942a3577a03a3559`。执行器 `controlled-dev-storage-fcbf8988af9a401e879cd70a2e5da578`，代次 `1`；UTC `2026-11-18T15:05:33.208492Z` 观察 `ended_reconciled`、退出码 `0`，三份 OCI 的归档摘要和实际加载身份见原记录。仅有成功受理、缺制品或摘要不符均不能判成功。 |
| 结果未知（U） | [E07c 前端超时](../p2/p2-4-02-closeout.md#构建超时与停止核对)：原 `build-operation-87850afe2e83473da74524b5f6b8562f`，Task `e3449b9137f644779da62a1130f547a7`，请求摘要 `sha256:660f379fc8e0722e0dd5c38260935863339412b05c6ff9d5d839b48619da1291`、输入摘要 `sha256:430c359bc9523cd2d13cfed93325e927f77453acabd6346880a458360be5cceb`。原观察 `engineering-build-87850afe2e83473da74524b5f6b8562f` / `unknown`，`engineering_frontend_build_unverified`，未取得后述 `seq=4` 停止事实。此时保留占账并阻止冲突执行，不能拿旧队列状态或 S 的制品解锁。 |
| 确认停止（X） | U 的原操作、原预留 `engineering-resource-1825085e63a92593bb171dfd786efbbd3746d79e`、进程绑定 `resource-a7b471431ff08c82bf59f943e1a132b3bce0eeca`。UTC `2026-11-01T05:29:57.663375Z` 追加 `engineering-build-stopped-87850afe2e83473da74524b5f6b8562f`，`seq=4 / stopped` 核实组删除及瞬态磁盘清理；构建 `failed`、`content_verified=false`。保留磁盘仍由原 owner 占账，U 的历史观察保持原值。停止请求本身不能释放资源。 |

S 的私有脱敏记录为 WSL `p1-fixtures/instance-cgn51uei/handoff.json`（相对 `~/.local/state/cloudhelm/`，SHA-256 `203dac41e648ea3371c4cfb72e1e9a7243214281e6e9cebf51069186be6b2a3e`）。U/X 的原方法结果为 `.thesis-work/p2-4-02-closeout/build-reconcile/result.json`，SHA-256 `ed7db5b5d4450640299521456172e15bf43cb9fc02e1a0dffbd94c9715de191b`。旧原始 `unknown` 观察 SHA-256 `2b02edd618027482befa20c09d2f1a7bccfa89fc2145f2bd2d540ede247a3f1d`，追加停止观察 SHA-256 `16d7973e4e24aa3109cd9d5e410bbaeb12076d05538f73587bb4290f1cf51f03`。两份私有历史记录只读，未重放或重新验证原物理构建。

| 准备时的版本 | 固定口径 |
|---|---|
| Hub / worker / SDK | A00a 源码 `b226022483fcc3c4c98f22c3a8faba1fb0b4c696` 加 `0020_p2_previews.py` 冷启动导入 blob `866cc2065ac991fdee55f75bdaf282a61f47f76b`，Hub `0.29.0`，DBOS 应用 `cloudhelm-hub/0.7.0`，迁移 `0020_p2_previews`。实际环境 Python `3.12.13`，DBOS `3.2.0`，PydanticAI 与 Pydantic Graph 均为 `2.55.0`。 |
| 构建配方 / 执行器 | 以上源码的本机 Runner，方法 `p1-fixed-reference-build-r3`、资源协议 `p1-resources-r2`；`linux/amd64` 使用 BuildKit `0.34.0`。固定[离线后端](../../../infra/p1/reference-build/backend.offline.Dockerfile) SHA-256 `dbe0cd0057c96f85853be1b7847fc23cd98f8187e5cd33c2b7584b26bd375fdf`、[离线前端](../../../infra/p1/reference-build/frontend.offline.Dockerfile) `137197cdcf2f624e9f5a0502e4e2b7f12f12c2e2de6557b9be4fe7086c29047f`。Remote 计划使用同一源码配对构建和 `reference-notes-archive-linux-amd64-r1` 固定归档配方；当前目标未运行新 Remote Agent。 |
| Desktop | 配对源码 `0.29.0`，锁定 Tauri `2.12.5`、`tauri-runtime-wry 2.12.3`。Windows 实机 Node `24.13.0`、npm `11.6.2`、Cargo `1.97.1`、WebView2 `154.0.4258.62`。尚未建立该轮原生客户端和 Runner 配对的运行证据。 |

**本机回执。** WSL `/home/cloudhelm/.local/state/cloudhelm/a00a/a00c/` 下 `task-r1.json` 的 SHA-256 为 `5a1458122bc7154542960df0086c1d7ac4a4c5881a57d32bd23428e36fa663b2`，`reference-base.bundle` 为 `a45a1ab7eaf16b90b144476705fa3d7f81c5d613ba8a27f55b1802a56ab166b2`。目标只读回执 `.thesis-work/a00c/target-facts.json` SHA-256 `4f49b912375b56ed8699881a08e83e680746430342210ca3e917b0681be371ef`。A00c 取证见[项目进度](../../../PROJECT_PROGRESS.md#2026-11-19a00c-固定单-agent-任务与操作账本样例)；G01 的实际交权、返工、构建、审查、原生验证与交付分别收证。
