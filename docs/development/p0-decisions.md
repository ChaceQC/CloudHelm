# P0.3 决定契约的查看与校验

本目录入口面向需要实施或复核 P0 决定的开发者。`p0-decisions-r1` 提供不可变契约、结构快照与固定边界检查，没有产品 API 服务、数据库迁移或执行器。决定范围见 [核心边界](../decisions/p0/core-boundaries.md)，实际支持与剩余门禁见 [统一出口评审](../acceptance/p0/exit-review.md)。历史接缝的复现方法仍见 [p0-seams.md](p0-seams.md)。

## 环境与窄检查

依赖沿用仓库 `.python-version`、`pyproject.toml`、`uv.lock`，在 WSL Ubuntu-24.04 的 `/mnt/e/Project/CloudHelm` 执行。首次准备环境可运行 `uv sync --locked`；已有锁定环境无需重复安装。

```bash
cd /mnt/e/Project/CloudHelm
PYTHONUTF8=1 uv run --locked --offline python -m scripts.p0.check_decisions
```

该命令检查本轮 Python 源码语法、JSON Schema 与 Pydantic 源一致性，以及七个模块的固定正反例。它只使用公开合成值和给定事实，输出各组实际布尔结果、方法修订、依赖/内核与 UTC 时间；失败以非零退出码结束。不得通过 Python `-O` 关闭断言。命令不连接模型、数据库、Docker、目标主机或浏览器，不会获取票据或读取配置秘密。

## 查看契约

```bash
PYTHONUTF8=1 uv run --locked --offline python -m packages.contracts.p0.decision_schema
```

结构快照为 [decisions-r1.schema.json](../../packages/contracts/p0/decisions-r1.schema.json)，源码列表和职责见 [契约 README](../../packages/contracts/p0/README.md)。快照以 UTF-8 保存，由源码生成后通过 `apply_patch` 更新；不手工修改生成字段，也不通过终端重定向写文件。JSON Schema 不包含所有跨字段 Pydantic 验证，更不能验证当前授权和外部事实；实现端必须保留对应语义检查。

`P0DecisionContracts` / 各 `P0*Contracts` 是 schema 集合，不是用户提交的组合对象。不要将其中 `allowed`、`time_evidence_valid` 等可信事实投影作为客户端可自授权限的字段。它们只能由实际身份、领域事务或执行器在当前门禁下生成。

## 固定候选与结果

最终候选先提交源码及决定，再通过只读命令生成公开文件 InputSet：

```bash
PYTHONUTF8=1 uv run --locked --offline python -m scripts.p0.decision_manifest --revision r1
```

该命令只读显式清单中的契约、决定、方法、锁文件、权威设计和引用证据，并逐文件核对当前字节与真实 Git HEAD。输出需通过 `apply_patch` 保存到新的 `docs/acceptance/p0/input-set-decisions-r1.json`；不改写历史 InputSet。未提交文件、输入不同或缺失时拒绝冻结，不会自动提交、删除或写文件。

```bash
PYTHONUTF8=1 uv run --locked --offline python -m scripts.p0.check_decisions \
  --input-set docs/acceptance/p0/input-set-decisions-r1.json
```

带 InputSet 的检查还会核对清单、Git source_commit、工作树与逐文件哈希，再运行相同窄检查。结果保存为独立证据，由 [出口评审](../acceptance/p0/exit-review.md) 记录实际候选与范围。后续改变契约、决定、方法、依赖或验证环境时，建立新修订/新输入与新证据，不能覆盖旧清单或沿用不适用的通过结论。

通过只证明已绑定输入下的类型、纯函数边界及结构一致性。真实权限事务、唯一报告、共享宿主配额/停止、许可时间误差、网络/代理撤销、原生 Desktop 和人类验收仍依各自阶段与支持矩阵取得证据。
