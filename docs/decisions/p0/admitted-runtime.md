# P0.1 当前门禁、安全检查点与续接决定 r1

> 日期：2026-10-13（Asia/Shanghai）
> 工作包：P0.1-A01。
> 修订：文档 r1；薄适配证据见 A01。
> 权威依据：D01/D02/D05 v4.7.0、D03 v4.7.1。
> 性质：本文件只记录决定与边界，不代表已实现或已验收。

依据 D01/D02/D05 v4.7.0、D03 v4.7.1。实际证据见 [A01 报告](../../acceptance/p0/A01.md)。本决定选择隔离接缝的受支持薄适配，不发布 CloudHelm 产品或开放 P1。

当前业务资格在 PostgreSQL 应用 schema 中检查：Task active、未取消、当前 Session/Run、权限/控制/输入修订、有效输入与当前授权。模型 HTTP transport 在每次真实出站前先持久化固定请求身份及保守金额上界；SDK 自动重试、校验修复、压缩或恢复只要产生新 HTTP 请求，就经过相同边界。Gate 行锁、Gateway 业务写入和副作用共用 SQLAlchemy 外层事务与同一 psycopg 连接。历史成功不授权新的副作用。

费用使用版本化官方 GPT-6 Luna Standard 全球价格，输入、缓存读取、缓存写入和输出以 Decimal 计算。兼容服务的 `default` 显式映射到 Standard；其他服务档位不在本轮支持范围。只有用户函数工具，无收费的供应商托管工具，因此本轮其他收费项为 0；该条件不能套用到引入其他工具后的请求。未知 usage、未支持档位与账单分别保存，未知保留上界占账。实际计价依据 [官方模型资料](https://developers.openai.com/api/docs/models/gpt-6-luna) 和 [官方价格](https://developers.openai.com/api/docs/pricing)，这不是兼容服务账单金额证明。

供应商 usage 超过已预登记的输入/输出上限时，仍保存真实 usage 与计算金额，标记请求/Task 的 `reservation_bound_exceeded` 并阻断新的普通推进，不静默扩额。迟到 usage 只能经 `reconcile_result` 的当前完整 scope/权限修订与有界供应商证据引用核对；原 unknown 和摘要留在审计历史中，相同证据/usage 幂等，异证据冲突拒绝。该事实归档可在 Run 结束或 Task 取消后执行，不启动副作用；没有证据时仍 unknown。跨 Run、Session 或修订复用模型请求身份明确拒绝。

DBOS 仅接受有界引用和有界事实。ContextReferences 只含需求、InputSet、历史、制品、秘密资源引用，拒绝额外字段及无界文本；完整 SDK 消息与实际秘密仅在临时执行内存中消费。step 捕获异常时只返回固定错误类别或代码。引用在等待/恢复/去重仍需要时保留，终态确认后才可清理。

选择公开 `@workflow` / `@step` 与 DBOSClient 的 `enqueue_in_transaction` 接缝。PydanticAI 默认 DBOS 包装对原参数、原错误和完整历史没有本轮所需裁剪保证，因此该入口保持拒绝；这属于已决定的不支持范围，不能以 DBOS 默认包装替换所选薄适配。真实调用仍采用 PydanticAI 的 Responses 协议与 SDK，不新增持久执行引擎。

accepted 回执、Operation 的最终事实、WaitCondition、原 Run 和新续接 Run 分开保存。wait、事件、WorkflowBinding、新 Run 与 DBOS 入队在同一事务内交接；撤权、取消、失效和旧修订阻断新普通推进。原 Run 恢复复用原 workflow，等待后的续接产生稳定的新 Run。DBOS 成功仍须应用层核对当前门禁后收尾 Run，不代表 Task 完成。

支持范围仅为本轮固定版本、单 worker、隔离 PostgreSQL、Standard 文本与用户函数流。真实宿主资源调整/停止释放、跨版本或多 worker 恢复、TLS 许可误差和产品 Task 完成命令消费 P0.3/P1/P4 的相应门禁。P4 前本机应急入口关闭。

2026-10-14 以 [A02](../../acceptance/p0/A02.md) 补齐受控薄适配的恢复新请求、消费瞬态输入后的安全异常和严格断流证据。真实 SDK 的校验修复、500 自动重试、受控摘要压缩续接在固定 HTTP 夹具与同一 PostgreSQL 当前门禁下实测；供应商新请求在同 worker identity 的实际恢复后实测。该补充不追认默认 DBOS 包装、不改变权限/费用规则，不把夹具或结果重取写成供应商恢复证据，也不扩大产品、跨版本或物理容量支持。
