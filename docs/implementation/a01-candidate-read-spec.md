# A01 固定候选读取规格

本页对应架构细化方案 §3、§10.2，列出 A01b 解析固定读取规格所需的权威字段。Run 从服务端已分配的候选得到项目、Task 和源码身份。候选工具当前仍只读工作区冻结副本；最终集成源码经现有构建路径可读，候选工具接线与产品验证属于 A02。

## 两种源码来源

| 字段 | 工作区冻结候选 | 最终集成候选 |
| --- | --- | --- |
| 候选及生产依据 | 用 Project、Task 与 `candidate_id` 查 `workspace_candidates`，核对 `snapshot_json`、`snapshot_digest` 与登记列。用快照的 `freeze_operation_id` 查询原 `workspace.operation_accepted` 与 `workspace.operation_registered`；须是同一候选的 `CandidateFreezeReceipt`，Operation、请求摘要、快照和绑定一致。执行器回执以 `materialization_operation_id`、`runtime_scope_id` 及 `writer_scope_digest` 关联原物化和实际冻结证明。 | `integration.prepared` 事件保存准确的 `IntegrationAttempt`，可用快照的 `freeze_operation_id` 查原尝试；只有候选 ID 时，从同项目同候选的准备事件定位。以尝试的 `entry_id` 串联 `MergeQueueEntry`；两者的 Project、Task、条目 ID 相符，尝试须为 `prepared` 且含同一快照。`freeze_operation_id == attempt_id` 对应 Git 准备操作；当前读取还要求 `entry.attempt_id` 等于该次尝试。 |
| 归属和绑定 | `snapshot.binding` 来自冻结 Operation 与回执，含项目、Task、WorkItem、Workspace、所有者、`source_id`、`source_revision`、`base_commit`、`workspace_revision` 与 `write_generation`。读取冻结时的版本；当前 Task 的控制及输入门禁仍按原 Operation 和已分配候选核对，晚到且登记为 `applicable=false` 的回执不能支持本轮。 | `snapshot.binding == entry.candidate.binding`，沿用原开发候选的 Workspace、所有者、来源与冻结版本身份；`entry.control_revision`、`entry.input_validity_revision` 和 `entry.source_input_set_ref` 用于核对当前 Task。 |
| Git 与存储 | 以绑定的 Project、`source_id`、`source_revision` 对照 `project_git_sources` 的登记内容与 `source_digest`。受管 Git 以该来源打开冻结时发布的提交。`snapshot.storage_id` 对应受管工作区存储中的封存副本，现有读取器用原 Operation 打开并核对回执。 | `entry.source` 的完整记录须与项目已登记的 `source_json` 和 `source_digest` 相符，并与候选绑定中的来源 ID、修订一致。当前集成支持空 `source_prefix` 的受管 bare 仓库。按登记来源从受控 Git 存储打开准确对象；集成快照的 `storage_id` 是从尝试派生的身份，不指向 Workspace 冻结副本目录。 |
| 固定提交与差异基线 | 读 `snapshot.candidate_commit`；以 `snapshot.parent_commit` 比较，该值等于原冻结绑定的 `base_commit`。 | 读 `attempt.snapshot.candidate_commit`，即 Git 准备结果的 `integrated_commit`；`attempt.candidate_commit` 等于 `entry.candidate.candidate_commit`，是原开发提交。以 `attempt.base_commit` 比较，该值等于最终快照的 `parent_commit`，也是最终提交的第一父提交；它可以不同于继承的 `snapshot.binding.base_commit`。 |
| 内容摘要 | `snapshot.manifest_digest` 绑定冻结回执、规范清单与冻结提交的内容。 | `attempt.snapshot.manifest_digest` 绑定最终提交的内容，从该次准备产出的提交生成，不沿用开发候选的摘要。 |

[Workspace Operation](../../modules/workspaces/operations.py)、[回执登记](../../modules/workspaces/receipts.py)、[候选存储](../../modules/workspaces/candidate_store.py)和[当前候选读取](../../services/hub-worker/engineering_verification.py)保存工作区侧依据。[集成记录](../../modules/integration/merge_records.py)、[准备与快照登记](../../modules/integration/merge_execution.py)及[现有集成构建解析](../../modules/integration/merge_builds.py)保存集成侧依据。[项目 Git 登记](../../modules/projects/source_tables.py)保存来源身份；[Git 对象存储](../../modules/workspaces/git_objects.py)在[受管存储](../../services/dev-runner/engineering_registry.py)的 Git 根下按该身份定位仓库。两种来源的 `manifest_digest` 都是[规范清单](../../packages/contracts/p1/workspace_git.py)的 SHA-256，覆盖按路径排序的模式、字节数和文件内容摘要，与 Git 树 ID、快照记录摘要各自独立。

## 按记录串联 InputSet

| 输入层级 | 权威引用与绑定 | A00b 中的事实 |
| --- | --- | --- |
| Task 来源 | Task 当前输入修订下的 `task_inputs.input_set_key` 指向已登记的 `source_input_set_ref`。工作区来源从原冻结 Operation 的 `result.input_set_ref` 取得；集成来源从 `entry.source_input_set_ref` 取得。 | 两轮共享同一个已登记的 Task 来源，D1 已冻结；换轮没有更换此引用。 |
| 构建 | [构建输入解析](../../modules/delivery/commands.py)生成 `BuildFixedInputs.input_set`：来源引用集合、以候选 ID 和准确 commit 为标识且带快照摘要的引用，以及构建定义引用。受理构建时随 `BuildRun` 登记，另有构建 Operation。 | 分别只读装配了 M1、M2 的 `build-inputs-*`，同一构建定义对应不同候选引用和集合摘要；未登记 `BuildRun`，没有物理构建。 |
| 构建后固定候选 | [`FixedCandidateRecord`](../../modules/integration/candidates.py)的 `input_set` 在构建输入基础上加入 BuildRun、执行方法、制品与环境；持有单独的 `fixed-candidate-*` ID、`build_operation_id` 与 `source_input_set_ref`。这是现有验证/审查 Run 所分配的候选记录。 | 未生成此记录及其 `candidate-inputs-*`。M1、M2 已有的是集成尝试的源码快照。 |
| 验证报告 | [验证报告](../../modules/integration/verification.py)通过 `candidate_id`、`build_operation_id`、`source_ref` 和 `source_input_set_ref` 串联固定候选、构建、源码提交与 Task 来源，保存本轮 `input_set`、证据输入引用以及方法、资产与环境。 | 未生成报告、`verification-inputs-*` 或人工批准。A00b 的独立读断言另行冻结，与 Task 引用的正式便签验收资产分开。 |

Task、构建、构建后固定候选和报告分别有自己的 InputSet。按记录中的 ID、修订、摘要和引用核对；相同的清单摘要不足以替换候选或证据身份。

## 当前读取、构建和采纳

- **当前读取：** 保留验证/审查角色、Run、Task 和原记录的读取授权。A01b 按已分配候选解析固定快照，核对归属、当前绑定与输入；集成候选缺准确尝试、绑定不一致或 Git 来源未登记时给出明确错误。读取判断不需要调用新构建准入，不要求重新申请构建权限或启动物理操作。物理存储仍须是已登记、可读的来源。已被换轮的尝试保留其原事实；本切片不开放历史查询入口。
- **新构建：** [构建准入](../../modules/delivery/commands.py)继续检查构建权限、Task 推进资格、当前控制/输入修订与集成尝试；新副作用仍须通过自己的执行门禁。构建从同一登记来源按固定提交取整树，核对清单及文件长度和摘要，不依赖候选工具的分页输出。A00b 只观察到 M2 成为当前尝试后，M1 的构建输入解析拒绝 `integration_attempt_not_current`。
- **结果采纳：** [集成证据检查](../../modules/integration/merge_validity.py)和[应用执行](../../modules/integration/merge_execution.py)另核对当前适用报告、对应尝试的批准及目标旧 SHA。目标移动不改变固定候选的文件或差异基线，旧结果不能批准新尝试或支持 Task 完成。

## 交给 A02

[A01b 的解析入口](../../modules/integration/candidate_read.py)是 `read_current_candidate_spec(connection, task, inputs)`。调用方在已授权的短事务中传入当前 Task 和从本 Run 的原构建取得的 `BuildFixedInputs`。返回的 `CandidateReadSpec` 包含 `snapshot`（含 Project/Task 绑定、候选、提交、基线、清单和存储身份）、`git_source`、`source_input_set_ref`、`build_input_set_id` 和 `build_input_set_digest`；只有集成来源附 `integration.entry_id` 和 `integration.attempt_id`。构建后的固定候选与报告仍由调用方核对，不作为源码解析的替代输入。

缺集成尝试返回 `candidate_read_integration_attempt_not_found`，绑定不符返回 `candidate_read_binding_mismatch`，缺可核对的 Git 登记返回 `candidate_read_git_source_unregistered`，尝试被替换返回 `integration_attempt_not_current`。解析只核对登记，不打开 Git。A02 打开尚未合入的候选时，不能沿用 `open_commit` 的目标可达性检查；目标引用也不能代替固定提交。

A02 在[验证](../../modules/agent_runtime/verification.py)和[审查](../../modules/agent_runtime/review.py)入口用短事务解析规格，事务外读页，响应前复核授权和 Run 绑定；模型只提供路径、范围、分页条件。Worker 用准确 Git 对象列目录、限长读文件及分页读差异；每页返回同一候选身份、提交、基线与清单摘要。丢失对象、摘要不符或内容不可安全展示时如实说明，不回落到分支头、原开发提交或可变工作区。沿用现有候选工具，无需新增公开路由。

按 [A00b 输入](../acceptance/a00b/README.md)与[独立断言](../acceptance/a00b/candidate-read-assertions.md)核对：M1 源码含 T1 独有文件而 D1 没有，T1 → M1 只显示排序修改；M2 使用 T2 作基线并纳入第二个目标文件。使用相同尝试的构建输入核对身份；覆盖目标移动后的旧结果拒绝，以及同项目另一 Task 越界读取。A00b 的 Git 对象和输入对照只证明固定来源事实；按现有 Gateway 执行完整产品读取还需合法的 Run/固定候选绑定。读取与采纳结果由 A02e 单独记录。
