# P0 隔离接缝与决定契约

此处分别维护 P0.1 历史接缝草案和 P0.3 决定契约；二者均不是软件发布或已启用的产品协议。P0/P1 放行结果见 [统一出口评审](../../../docs/acceptance/p0/exit-review.md)，不能从 schema 存在推定支持。

## P0.3 决定契约

`p0-decisions-r1` 由以下有界模型组成，历史探针不自动切换到它：

|源码|职责与决定|
|---|---|
|`decision_common.py`、`engineering_contracts.py`|公共标量、工程引用、InputSet 与证据适用性|
|`core_contracts.py`|Runtime、accepted、等待及恢复/续接身份映射|
|`identity_contracts.py`|规范摘要、逐动作权限信封与幂等顺序；[身份决定](../../../docs/decisions/p0/identity-permissions-migrations.md)|
|`migration_contracts.py`|线性迁移、五类查询与未知结果；[迁移决定](../../../docs/decisions/p0/migration-contract.md)|
|`resource_contracts.py`|硬上限/占账、未知调整与磁盘分维释放；[资源决定](../../../docs/decisions/p0/resources-task-control.md)|
|`task_control_contracts.py`|完成/取消、唯一报告及普通推进关闭；[Task 决定](../../../docs/decisions/p0/task-control.md)|
|`permit_contracts.py`|PlanStep、时间映射、原许可及启动窗口；[许可决定](../../../docs/decisions/p0/time-preview-access.md)|
|`preview_contracts.py`|预览路线、公开兑换元数据与逐代理撤销；[预览决定](../../../docs/decisions/p0/preview-access.md)|
|`delivery_contracts.py`、`emergency_contracts.py`|Release/环境分层、应急禁用与维护交还；[核心边界](../../../docs/decisions/p0/core-boundaries.md)|

`decision_schema.py` 汇总模型并导出 [decisions-r1.schema.json](decisions-r1.schema.json)。聚合类只是结构集合，不构成产品 API。实际当前事实由可信适配层取得；源码内纯函数不会创建权限、写数据库、停止进程或原子兑换票据。JSON Schema 结构检查不能代替跨字段校验或外部事实取证。

在 WSL 仓库根目录使用 `uv run --locked --offline python -m scripts.p0.check_decisions` 运行当前七组精简检查；保留范围和历史候选复现见 [P0.3 使用说明](../../../docs/development/p0-decisions.md)。未释放物理占用、未知模型费用、未确认代理或人类结论不因检查通过而改变。

## P0.1 历史接缝草案

以下文件仍为各自历史固定输入，不因本轮新增决定改写字节或获得新的通过结论。

`runtime_contracts.py` 直接用 Pydantic 校验 D01 §8 的 RuntimeInput、TurnResult 和 D01 §5.2 的 accepted 回执。消息和结果只带固定版本及摘要的引用；不得把密钥、完整仓库或无界历史塞入工作流参数。固定批次上限仅用于本次隔离输入，生产界限待 P0.3/P2 决定。

`remote-plan.schema.json` 是 Compose/完整远端计划探测的 JSON Schema。其时间域、身份及资源字段属于历史实验；本轮新决定独立维护，不以改版本号追认语义兼容，实验中同机通信不构成实际受支持拓扑。

在 WSL、仓库根目录执行 `uv run --frozen python packages/contracts/p0/runtime_contracts.py` 可查看实际校验模型导出的 JSON Schema。契约源随隔离输入清单绑定 SHA-256；改动时建立新输入与新证据。业务接口、事件和数据库迁移在后续领域实施时单独维护。
