# P0 隔离接缝契约

此处为 P0.1 固定输入使用的契约草案 `p0-draft-r1`，不作为软件发布或正式执行协议版本，不表示 P0.3 已审查放行。

`runtime_contracts.py` 直接用 Pydantic 校验 D01 §8 的 RuntimeInput、TurnResult 和 D01 §5.2 的 accepted 回执。消息和结果只带固定版本及摘要的引用；不得把密钥、完整仓库或无界历史塞入工作流参数。固定批次上限仅用于本次隔离输入，生产界限待 P0.3/P2 决定。

`remote-plan.schema.json` 是 Compose/完整远端计划探测的 JSON Schema。时间域、可信误差、生产身份及权限、资源账本和步骤运行时长的正式决定依然属于 P0.3；实验中同机通信不构成实际受支持拓扑。

在 WSL、仓库根目录执行 `uv run --frozen python packages/contracts/p0/runtime_contracts.py` 可查看实际校验模型导出的 JSON Schema。契约源随隔离输入清单绑定 SHA-256；改动时建立新输入与新证据。业务接口、事件和数据库迁移在后续领域实施时单独维护。
