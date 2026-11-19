# 固定候选的只读审查

源码 `0.26.0` 在既有 Runtime 接通 `reviewer / agent-r2`。内部受控调用方在 `ContextPackage.review` 提供 `candidate_id`，以及可选的 `verification_report_id`，调用 `AgentRuntimeApplication.start`。候选来自[固定候选入口](p2-candidates.md)，验证报告来自[正式验收入口](p2-verification.md)；不开放公开启动参数、报告上传或新的执行器。

审查加载原需求、验收要求、准确候选/InputSet、构建执行与制品事实，以及所绑定验证报告的真实检查与当前适用性。没有提供验证报告时明确返回 missing；失败、缺项、unknown 或失效结果保留原样，不能按构建成功推断验收通过。报告必须属于准确候选、构建和源码提交；同一 Session 固定候选和报告绑定，需要变化时创建新 Session。

|工具|参数与行为|
|---|---|
|`candidate.list_directory` / `candidate.read_file`|相对路径及有界页或行范围；从 Run 分配的工作区冻结或最终集成候选读取固定清单和选定 blob|
|`candidate.diff`|`path` 默认空、`offset` 默认 0、`max_entries` 默认且最多 16；比较冻结候选的 parent commit 与 candidate commit，按 UTF-8 路径顺序分页。非空路径匹配指定文件或目录内变更|
|`review.evidence`|空参数；回查服务端绑定的构建状态、执行/制品事实、验证结果及可引用的 `evidence_refs`，模型不能指定另一份报告或自填事实|

候选页标明源码快照的 `candidate_id`、`candidate_commit`、`baseline_commit` 和 `manifest_digest`；`review.evidence` 中的候选 ID 属于构建后固定候选，通过同一构建 Operation 关联。最终集成候选的基线是该次尝试准备时的目标提交；差异只显示相对它新增、删除或修改的文件。差异页带文件模式和 Git 对象 ID，超过上限而无法读取的基线文件没有内容摘要。每个补丁最多 8 KiB，整页约 32 KiB。继续目录或差异查询时，将 `next_offset`、`next_cursor` 分别传回 `offset`、`cursor`；路径、页大小或候选变化后从第一页开始。

敏感路径会被排除，检测到秘密时会遮罩整个补丁。截断、二进制、遮罩或超过字节限制的内容按返回原因记入 `uncovered`。准备候选时，受管 Git 留存与快照摘要绑定的清单；缺清单、缺对象或摘要不符时读取失败。目录、文件和差异都不会回退到活动工作区或当前目标分支。读取前后检查当前 Run 和绑定，合入仍另查当前报告、批准和实际目标基线。

模型返回[ReviewHandoff](../../packages/contracts/p2/review_agent.py)：`feedback_ready`、`human_decision_required` 或 `continue_required`，包含摘要、下一步、`findings` 和 `uncovered`。每个问题必须有相对路径、行号、blocking/advisory、标题、理由和原事实证据引用；整体输出最多 8KiB。位置及理由属于审查建议，证据引用必须来自服务端返回的准确事实，不能伪造另一候选的通过结论。

服务端提交反馈前重查当前权限、控制/输入修订、固定候选与原报告，核对证据引用后把结构化反馈保存到原 Run。成功交接为 `submitted / agent_review_feedback_ready`，delivery 引用的 authority 为 `agent-runtime`、revision 为 `agent-review-r1`、object_id 为原 Run，digest 绑定交接正文。现有 Task Agent 查询可读回该反馈。源码 `0.27.0` 的 [P2.5-01 返工入口](p2-rework.md) 在同事务把问题关联原开发工作项并通知会话，关闭仍需新候选的独立验证和必要复查。

审查没有工作区写入、构建、检查执行或正式验证工具。无问题反馈仍是建议，不产生 `Review.approved`、证据选择、合入或 Task 完成。人类审查及正式批准继续走[合并队列策略](p2-merge-queue.md)。原模型请求、费用、Run 时限与工具准入保持生效。

早期工作区审查的开发证据及夹具边界见 [P2.5-04 记录](../acceptance/p2/p2-5-04.md)。
