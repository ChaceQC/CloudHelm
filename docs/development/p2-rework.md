# 验证与审查反馈返工

源码 `0.27.0` 复用原 Task/WorkItem、Session/Run、事件/outbox、工作区和固定候选，提供内部 `ReworkApplication`。没有新增数据库表、迁移、执行器或公开 HTTP 参数；当前只处理普通开发工作区候选，最终集成仍走[合并队列](p2-merge-queue.md)。

## 收件及开发继续

独立验证和只读审查的成功 Run 交接与返工收件在同一事务提交。受控调用方也可对已有交接或正式报告调用 `ReworkApplication.receive(actor, task_id, request, idempotency_key=...)`；[ReceiveReworkRequest](../../packages/contracts/p2/rework.py) 必须带当前 Task/控制/输入版本，并在 `source_run_id` 与 `verification_report_id` 中指定一个。调用方不能上传问题正文或自填结论。

服务端从原 Run 的持久交接或正式报告读取准确候选、SHA、原证据和所属工作项。每条审查问题保留位置、理由、严重性及自身证据；验证的 failed、missing、完整性错误和 unknown/not_run 分别记录原事实。完整通过且没有问题的来源不会创建返工。原 SHA 的历史结论不因收件而改写。

问题身份绑定原反馈来源及条目位置；同来源重投不重复建问题、重置工作项或推进版本。同一工作项的同类 check 或相同位置/标题问题有稳定指纹，后续反馈以 `previous_issue_ids` 关联之前问题，保留修复、复发和重复返工事实。

`rework.issue_received` 及 outbox 保存问题和 `owner_session_id`。阻塞问题清除原工作项的旧接受依据、推进工作项修订并置 ready，保留原会话和工作区；advisory 作为建议保存，不阻止完成。开发者从 Task 页按原会话显式继续，下一份 Context 带入未关闭或需要复核的 `rework` 通知。原活动 Run、未知写操作、可靠等待、写入权、预算和输入门禁继续有效；收件不启动新的物理操作。

开发沿现有读取、编辑、自测、候选提交和构建入口修复，再通过[固定候选](p2-candidates.md)、[独立正式验证](p2-verification.md)和[只读审查](p2-review.md)形成新证据。没有为返工另设一套构建或选择性验收工具；当前以固定参照的完整正式报告覆盖受影响检查，正式标准和资产不由被验收代码修改。

## 关闭及完成门禁

受控调用方使用 `ReworkApplication.resolve` 和 `ResolveReworkRequest`，提交当前三项版本、`issue_id`、新候选的 `verification_report_id`；审查来源还必须提供 `review_run_id`。

关闭必须同时具备：

- 同项目、Task、原工作项的新固定候选，候选 ID 与 SHA 均已改变；
- 当前适用且完整通过的独立正式报告，覆盖全部必需项与原问题受影响检查，没有失败、缺项或完整性错误；
- 对审查问题，同一新候选的独立只读 reviewer 交接，无阻塞问题、同指纹问题或未覆盖项。

`rework.issue_resolved` 保存新候选、构建、报告/证据和复查 Run 引用，不覆盖旧事实。`ReworkApplication.query` 提供有界问题及最新关闭依据；`open`、`resolved` 和 `needs_review` 是原事件与当前报告适用性的投影，不另存权威状态。单 Task 当前上限 128 条问题，达到上限时拒绝新增，不静默截断后宣称覆盖。

Task 完成在原短事务、Task 行锁和当前版本下重读这些依据；阻塞问题未关闭或报告失效时产生 `rework_unresolved`。完成与输入失效继续由原 Task 锁串行裁决，取消/关闭后不能新建返工推进。问题关闭不接受工作项、不替代最终集成、人工审查、人测真实结论或 Task 完成；原未知写操作收尾和人测政策继续参与完成门禁。

旧 Run 不在升级时自动补扫；受控调用方可按当前授权显式接收仍适用的历史来源。数据库 head `0019_p2_history_limit`、DBOS 应用 `cloudhelm-hub/0.7.0` 和现有 HTTP 契约保持原版本。定向结果及实际支持边界见 [P2.5-01 记录](../acceptance/p2/p2-5-01.md)。
