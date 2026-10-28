# 固定候选与输入证据

源码 `0.14.0` 保留 P2.2-01 的固定候选接口，并接入[受控正式验收](p2-verification.md)。新库迁移 head 为 `0014_p2_verification`，工作流应用仍为 `cloudhelm-hub/0.7.0`。候选固定本身不生成正式验收结论。

## 使用顺序

1. 通过现有 Workspace 接口物化、修改并提交物理候选。采集在服务写锁中固定内容、commit 和实际写入者核对结果，之后恢复开发；构建读取独立候选目录。支持服务作为唯一写入者及已登记的只读 Runner，不支持未经停止/交接的可写 Runner 或任意宿主编辑。
2. 通过现有构建接口对该物理候选申请构建，等待原操作的受信执行观察和制品内容核对完成。`accepted`、内容存在或单独退出码 0 均不足以固定本轮候选。
3. 由受控生产者登记验证环境的不可变 `EngineeringRef`/`EnvironmentMetadata`。环境引用只保存安全描述、修订和支持范围；秘密使用独立版本引用，不把配置秘密放入元数据。
4. 调用 `POST /api/tasks/{task_id}/candidates`，携带 `Idempotency-Key` 及下列请求。成功返回 `201` 和 `candidate_id`；接口只登记输入与事实关联，不执行正式验收。

```json
{
  "expected_version": 12,
  "expected_control_revision": 0,
  "expected_input_validity_revision": 1,
  "build_operation_id": "build-operation-<原命令身份>",
  "environment_ref": {
    "kind": "environment",
    "object_id": "<已登记验证环境>",
    "revision": "<固定修订>",
    "authority": "integration",
    "digest": "sha256:<元数据摘要>",
    "digest_algorithm": "sha256"
  }
}
```

请求值从当前 Task、原构建和受控环境记录取得，示例数字与摘要不能直接提交。调用者需要当前 `candidate.submit`、`resource.read` 和原操作的 `operation.query` 权限；既有身份不会自动获得工程权限。结构在 HTTP 入口校验一次，内部继续使用类型化契约。

## 固定内容与适用范围

`modules/integration/candidates.py` 在同一短事务保存命令回执、固定记录及事件/Outbox。复用现有命令去重与事件存储，不建立第二份构建或执行状态机。同键同摘要先检查当前权限，再返回原结果；异摘要重用键拒绝。

不可变 InputSet 保留原需求、验收资产及方法、来源/策略、精确物理候选、完整构建定义，另加入精确 BuildRun、三个制品内容引用和本轮验证环境。相同 commit 的不同构建定义、参数、制品、资产或环境修订具有不同输入；再次开发不会修改原候选或原记录。新的受控资产进入新的来源输入及构建，不修改旧事实。

固定时检查原采集回执、构建执行和制品核对的适用性，以及 Task 当前输入、控制修订和推进资格。晚到归档的 `applicable=false` 回执不能作为本轮有效事实使用。接口不持有开发工作区写锁执行验证或构建。

`GET /api/tasks/{task_id}/candidates/{candidate_id}` 返回固定记录和三条 `EvidenceApplicability`，分别关联：

|范围|原始事实|能支持的结论|
|---|---|---|
|`source_snapshot`|已登记的 Workspace 采集回执|准确物理候选、源码 commit/快照和冻结输入|
|`build_execution`|原 BuildRun 的受信执行观察|该精确构建的执行及输出身份|
|`artifact_content`|原构建的制品内容核对回执|所列三种 OCI 内容与摘要|

引用摘要绑定原始回执，原始事实仍由 workspaces/delivery/artifacts 持有。这里的 `valid` 仅表示这些事实对该固定输入的关联当前适用，不表示源码测试、镜像运行检查或正式验收通过。已有回执没有完整实际方法/环境证据时，不补造 `EvidenceRecord(result=passed)`；本轮验证环境是后续验收的输入，不能冒充之前的构建执行环境。

查询按当前 Task 状态及输入/控制修订重新判断适用性，变化后返回 `needs_review`，保持原记录字节及历史事实。消费者必须核对准确的候选和 InputSet；不同环境的旧记录只适用于其原环境。正式验收执行、影响索引与消费者门禁见 [P2.2-02 说明](p2-verification.md)；固定候选接口本身不生成验收或完成结论。

开发验证及支持限制见 [P2.2-01 记录](../acceptance/p2/p2-2-01.md)。
