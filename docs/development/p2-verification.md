# 受控正式验收与消费者门禁

源码 `0.14.0` 提供固定参照 HTTP 验收的内部受信生产者入口，以及报告查询、证据选择和影响失效接口。新隔离库迁移 head 为 `0014_p2_verification`，线性承接 `0013_p2_usage_waits`；DBOS 应用继续为 `cloudhelm-hub/0.7.0`。旧安装不由 initialize 自动升级，受限维护副本仍固定在 `0011`。

## 执行与报告

1. 按[固定候选说明](p2-candidates.md)取得不可变候选。正式资产必须是平台受控 checkout 中已登记的固定参照修订，不能指定候选仓库中的入口或测试配置。
2. 由受控执行方准备隔离的本机实例，将准确候选、InputSet、验证环境和准备事实绑定为已登记证据。`seed` 后的实际进程重启、`not-ready` 的真实故障准备由执行方证明；HTTP 检查本身不能证明这些准备确已发生。
3. 受信生产者调用 `VerificationApplication.run_phase(actor, task_id, request, base_url=..., idempotency_key=...)`。`VerificationPhaseRequest` 携带当前三类修订、候选、`round_id`、生产者 `source_id`、阶段及 `setup_evidence_ref`；调用者必须匹配已启用的 integration/product 生产者，并具有当前 `fact.archive`、`resource.read` 及原构建的 `operation.query` 权限。
4. 按 `baseline → seed → 实际重启 → verify-persisted → 实际故障准备 → not-ready` 的顺序收集四份事实。`VerificationApplication.finalize(...)` 使用同一候选/轮次的 `phase_ids` 生成不可变报告；缺项也能归档，不能被选择为通过。

生产者入口是内部 Python API，不接受公开 HTTP 上传的报告、命令、执行入口或实例地址。现有 Runtime/Gateway 未增加新的自动验收调度工具。受控调用方应在现有执行边界内调用该入口；本包没有新增调度器或持久工作流。

准备证据由已登记的 product 生产者提供，须满足：

- `EvidenceRecord.result=passed`，subject 为准确固定候选，InputSet 为该候选原始完整输入，environment 与候选一致；
- `support_scope` 包含当前阶段，`fact_digest` 为 `delivery_digest({"base_url": origin, "phase": phase, "candidate_id": id, "input_set_digest": digest})`；
- 本机地址仅允许显式端口的 `http://127.0.0.1`、`localhost` 或 `::1`，不带用户信息、查询或片段。实际环境身份与重启/故障事实由受控准备方法负责，摘要本身不证明物理事实。

资产加载复用固定清单及摘要，脚本字节经只读读取后以 Python `-I -S` 执行，使用私有临时工作目录和最小环境。候选无法替换入口、断言、用例或跳过规则；不支持的修订直接拒绝，不自动降低要求。四阶段要求分别为 43、3、2、2 项，共 50 项，来自原独立清单；本包不修改原验收资产。

受信采集器核对实际检查 ID、数量、唯一性、方法/需求/阶段、通过与失败集合和退出码。缺项、跳过、额外检查或输出不完整即使退出码为 0 也不能通过。报告保存预期、实际通过/失败、缺失项、完整性错误、输出摘要及 UTC 观察时间；不保存响应正文、异常文字或实际秘密。

执行前先提交原身份意图，执行后另存事实。相同键重投只返回原事实；存在意图但没有结果时返回 `verification_phase_outcome_unknown`，先核对原执行，不自动再次写入测试实例。正常同输入重试使用明确的新轮次；输入变化重新固定候选。

## 查询与选择

- `GET /api/tasks/{task_id}/verifications/{report_id}` 返回原报告、证据引用、当前 `applicability` 和 `usable`。
- `POST /api/tasks/{task_id}/verification-selection` 携带 `Idempotency-Key`、`expected_version`、`expected_control_revision`、`expected_input_validity_revision` 和 `report_id`，要求当前 `task.command` 权限。只有当前适用的 passed 报告可以选择；选择、Task 版本、命令及事件同事务保存。

报告完整输入保留原固定候选的源码/构建/制品/环境引用，再加入准确最终源码 commit、固定候选和阶段准备证据；同 commit 的不同构建或环境不会混为同一输入。原始源 InputSet 仍独立保留，不覆盖旧记录。`EvidenceMetadata.check_ids` 声明该报告检查范围，实际执行结果以报告的通过、失败、缺失集合为准，未知或未执行不会因此变为通过。

Task 完成投影只读取显式选中的正式报告及其完整输入，工程元数据从所属领域固定事实投影，不要求把 Build/制品伪装成旧注册表对象。历史失败、unknown、not_run 报告均保留，不作为新的当前通过证据；选择也不把 WorkItem 改为 accepted，不生成 Task 完成或人工通过结论。审查和工作项接受仍按后续计划执行。

## 变化与消费

`POST /api/projects/{project_id}/verification-impacts` 携带幂等键及 `producer_ref`、`change_ref`、`reason`。前者是**被替代的准确旧引用**，后者是已登记的新变化；不能拿新修订的完整 key 查旧消费者。调用者须具备当前项目及受影响 Task 的 `fact.archive`、`resource.read` 权限。

唯一新增表 `verification_dependencies` 保存报告到准确生产者的依赖，并提供正向主键、反向 producer 与 Task 索引。变化在同一事务内把所有命中报告标为 needs_review，并推进适用的未终态 Task 输入修订；已完成 Task 的报告及业务结论保持原样，其报告的后续消费者仍受独立失效标记约束。传播有界且同步完成，没有异步分析未结束却仍允许旧通过的窗口；超出本次 128 条影响范围时整笔拒绝，不能据此宣布变更已生效，需后续受控维护方案处理该范围。

Task 完成、Release 形成、部署预检及每次新步骤许可均重新检查报告适用性。原 grant 的同身份查询及已启动步骤收束仍按原协议处理。Release 另要求准确运行配置的 `artifact_runtime` 证据，固定 HTTP 报告不能替代镜像运行检查；方法、环境及支持范围也须匹配。旧报告和旧 Release 不自动获得新的受控验收门禁通过。

当前只支持已固定的参照 HTTP 方法。新增正式资产、可跳过规则或其它技术栈需独立受控修订；不构成 UI、迁移、独立机器交付、容量或人工验收。开发验证及固定输入见 [P2.2-02 记录](../acceptance/p2/p2-2-02.md)。
