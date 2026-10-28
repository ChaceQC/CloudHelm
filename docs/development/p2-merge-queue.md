# 项目合并队列

源码 `0.16.0` 提供 P2.3-02。新隔离库迁移 head 为 `0016_p2_merge_queue`，承接 `0015_p2_handoffs`；DBOS 应用仍为 `cloudhelm-hub/0.7.0`，新增 integration 自有的 `integration.merge_queue.v1`，复用 engineering 队列。旧安装仍须显式升级，不由 initialize 自动迁移。

## 操作次序

所有写请求都使用当前 Task 的 `expected_version`、`expected_control_revision`、`expected_input_validity_revision` 和 `Idempotency-Key`。同键重投返回原回执，当前状态另行查询；202 只表示可靠接收。

1. 经现有 Workspace 接口固定真实物理候选后，调用 `POST /api/tasks/{task_id}/merge-queue`，提供 `candidate_id`。需要显式 `candidate.submit`。队列保存原候选、原 Task 输入及 Git 来源，不接受请求方提供任意 commit 或执行命令。
2. `GET /api/projects/{project_id}/merge-queue` 返回项目当前未收尾条目，按 FIFO 排列；`GET /api/merge-queue/{entry_id}` 返回当前尝试及审查。只有队首会进入真实准备，后续条目保持 queued；合入或撤回后，同事务入队下一项。
3. 准备步骤读取当前权威目标 tip，真实三方合并并固定不可变 `IntegrationAttempt`。冲突进入 conflict，返回冲突路径、明确的截断标记及原因；不改目标分支。成功进入 awaiting_evidence，查询中的 `attempt.snapshot.candidate_id` 是最终集成候选。
4. 使用该最终候选调用已有构建接口。worker 从固定最终 Git 对象读取文件和 manifest，仍经原资源门禁和构建器。之后沿既有固定候选、受控正式验收流程取得报告；原候选的构建或报告不能替代。构建、正式采集和 setup 的支持范围继续见[候选说明](p2-candidates.md)及[验收说明](p2-verification.md)。
5. 人类使用 `POST /api/merge-queue/{entry_id}/review`，提供 `attempt_id`、`verification_report_id`、`conclusion=approved|changes_requested` 和 `reason`。审查精确绑定最终提交及报告 InputSet，保存真实主体和授权决定。项目 owner 可审查；reviewer 必须经现有角色接口显式授予 `resource.read`、`review.submit`，旧 reviewer 不自动获得该动作。Agent 不代填人类审查。
6. 使用 `POST /api/merge-queue/{entry_id}/advance`，提供 `attempt_id`、`action=merge` 和同一 `verification_report_id`。执行前再次核对当前权限、Task/输入、队首、完整正式验证和 approved 审查，再用预期旧 SHA 条件更新目标。Task 完成、Release 形成及部署重验也核对该已合入事实，保留原制品与运行验证门槛。

## 竞争、返工与核对

外部提交使目标 SHA 变化时，条件更新拒绝覆盖，并将原条目重新排为新尝试。新的基线和最终提交形成新的构建/InputSet，旧验证和审查不再准入；历史事件和报告保持原值。项目串行化不替代 Git 的旧 SHA 条件更新，也不自动 rebase 其他长期工作。

`advance` 的 `retry` 在当前已知尝试上显式重新集成；`withdraw` 撤回尚未进行分支写入的条目。conflict 不被静默跳过，须返工后重新入队或撤回。构建每次新副作用检查当前尝试，已替换尝试不能继续开启新执行。

准备或合入回执未知时保留 preparing/applying，使用 `action=reconcile` 查询原 Git 操作。核对只读取原身份，不重新采集或创建提交。Git 保存准备、started 和合入引用；目标历史包含原精确提交才可确认已应用。合入后正常追加提交不抹除原合入事实，外部强制改写导致无法证明时保持 unknown。取消后的核对可确认原操作未启动并封闭条目；未知的分支写入继续参与 Task 停止/完成阻断。

## 数据与支持范围

新增一张项目 FIFO 表，尝试、审查及合入事实复用不可变事件。构建候选现在可由 Workspace 或 integration 产生，旧的单一 Workspace 候选外键移除；命令边界分别核对所属项目、Task、生产者记录和当前输入，BuildRun 的项目/Task 及输入修订外键继续保留。没有新增通用调度器、插件层或 shell 工具。

当前仅支持空 `source_prefix`、可写的受管 bare 仓库。外部 Git 托管、PR 重写提交、任意局部目录仓库及 Desktop 本地 Git 不在本包支持范围。完整物理构建/HTTP/worker 崩溃、独立交付、容量和原生/人工产品验收不能由本包定向方法推定通过。实际输入、方法及结果见 [P2.3-02 记录](../acceptance/p2/p2-3-02.md)。
