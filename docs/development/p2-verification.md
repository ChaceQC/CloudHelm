# 受控正式验收与消费者门禁

源码 `0.15.0` 保留固定参照 HTTP 验收的内部受信生产者入口，以及报告查询、证据选择和影响失效接口。新隔离库迁移 head 为 `0015_p2_handoffs`，线性承接 `0014_p2_verification`；DBOS 应用继续为 `cloudhelm-hub/0.7.0`。旧安装不由 initialize 自动升级，受限维护副本仍固定在 `0011`。人工交还会推进输入修订并使本 Task 的正式报告消费待复核，见[写入权说明](p2-handoffs.md)。

## 执行与报告

### 独立验证角色

源码 `0.25.0` 通过既有 `AgentRuntimeApplication.start` 接入 `verifier / agent-r2`，参数见[验证契约](../../packages/contracts/p2/verification_agent.py)。受控调用方在 `ContextPackage.verification` 固定 `candidate_id`、`round_id`，并可提供当下已准备的唯一 `setup`（阶段、本机 origin 和已登记准备证据）。这些属于内部可信输入，不开放 HTTP 上传，也不由模型填写。仍须使用真实持久来源命令、当前授权和原预算；当前使用验收资产登记者的 product 事实来源，另一主体不能借该来源执行。

|工具|模型参数与实际行为|
|---|---|
|`candidate.list_directory` / `candidate.read_file`|仅相对路径、页/行范围；从原构建的准确冻结目录读取，沿用摘要、路径、秘密过滤及字节上限，不读取活动工作区|
|`verification.run_phase`|仅 `phase`；只执行当前受控准备的阶段，地址、证据和来源由服务端绑定，调用原 `run_phase`，保留检查 ID、失败、输出摘要和未知结果|
|`verification.finalize`|空参数；汇总同候选/轮次的原阶段与未完成意图，调用原 `finalize`，缺项、失败、unknown、not_run 均原样保留|
|`verification.result`|仅 `report_id`；按当前权限查询，核对准确候选/轮次并返回当前适用性及证据|

验证上下文加载原需求、固定候选/InputSet、受控资产、实际方法和环境；模型输出 `VerificationHandoff`。`report_ready` 只表示报告交接，服务端重新读取原报告并核对候选、轮次和适用性后，才把结构化结果与证据引用写入 Run。模型自述不生成 passed、审查批准或 Task 完成；失败或缺项报告也可按真实状态交接。现有 Task 查询可以读取该持久交接，不新增界面或公开启动参数。

四阶段顺序沿用下文。Gateway 要求前序阶段已有结果；实际重启与故障准备的证据时间必须晚于前序执行。每个 Run 只提供当下准备的一阶段，受控执行方在 seed 后实际重启、在 verify-persisted 后实际准备故障，再以新 Run 提供新证据。相同 Session 保持候选/轮次、模型/角色/工具策略和完整历史；需要不同候选/轮次时新建 Session。未准备阶段不执行，结果未知按原意图核对，不重放；关闭一轮后需重新验证时使用新轮次。同步检查的子进程超时取正式方法 300 秒上限与当前 Run 剩余时间的较小值，超时归档 unknown。

当前读取适配支持既有工作区冻结候选；项目合并候选读取尚未接入，明确拒绝，不回退到活动工作区。固定候选的运行实例、真实重启及故障准备仍由受控执行方提供；现有开发实例不能冒充正式环境。本包没有新增实例调度器、部署或常驻工作流。旧无验证绑定的角色/开发请求保留原行为；旧源码不自动理解新可选字段，使用验证工具须升级 Runtime/worker。开发证据及限制见 [P2.5-03 记录](../acceptance/p2/p2-5-03.md)。

### 既有受信执行入口

1. 按[固定候选说明](p2-candidates.md)取得不可变候选。正式资产必须是平台受控 checkout 中已登记的固定参照修订，不能指定候选仓库中的入口或测试配置。
2. 由受控执行方准备隔离的本机实例，将准确候选、InputSet、验证环境和准备事实绑定为已登记证据。`seed` 后的实际进程重启、`not-ready` 的真实故障准备由执行方证明；HTTP 检查本身不能证明这些准备确已发生。
3. 受信生产者调用 `VerificationApplication.run_phase(actor, task_id, request, base_url=..., idempotency_key=...)`。`VerificationPhaseRequest` 携带当前三类修订、候选、`round_id`、生产者 `source_id`、阶段及 `setup_evidence_ref`；调用者必须匹配已启用的 integration/product 生产者，并具有当前 `fact.archive`、`resource.read` 及原构建的 `operation.query` 权限。
4. 按 `baseline → seed → 实际重启 → verify-persisted → 实际故障准备 → not-ready` 的顺序收集四份事实。`VerificationApplication.finalize(...)` 使用同一候选/轮次的 `phase_ids` 生成不可变报告；缺项也能归档，不能被选择为通过。

生产者入口是内部 Python API，不接受公开 HTTP 上传的报告、命令、执行入口或实例地址。验证角色沿上述受控 Gateway 调用该入口；实例准备仍由受控调用方负责，没有新增调度器或持久工作流。

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
