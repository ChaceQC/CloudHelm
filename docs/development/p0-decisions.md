# P0 决定契约的查看与校验

`p0-decisions-r1` 契约继续供 Hub 业务源码复用。决定范围见[核心边界](../decisions/p0/core-boundaries.md)，原阶段结论见[统一出口评审](../acceptance/p0/exit-review.md)。当前只维护结构快照和关键纯函数边界，完整历史实验见 [P0 历史复现](p0-seams.md)。

## 环境与窄检查

在 WSL Ubuntu-24.04 的仓库根目录使用已有锁定环境：

```bash
uv run --locked --offline --no-sync python -B -m scripts.p0.check_decisions
```

当前方法修订为 `p0-decisions-check-r2`，核对契约源码语法、完整 JSON Schema 深度快照，以及 core、identity、migrations、resources、task、permits、preview 七组保留场景。具体断言以当前检查源码为准；范围已精简，不再声称保留历史全部场景。

检查只消费公开合成事实，不连接供应商、数据库、容器或浏览器；不能据此证明当前授权、物理资源释放、执行停止或真实业务完成。查看结构可直接阅读 [decisions-r1.schema.json](../../packages/contracts/p0/decisions-r1.schema.json)，无需运行历史实验。

## 收尾输入与历史证据

当前结构快照继续维护，历史 InputSet 与运行报告已从当前树移除，原字节从 Git 查询。原 `decision_manifest`、`closure_manifest` 及 `check_decisions --input-set` 冻结/验重包装已从当前分支删除；当前命令只运行工作树中的精简检查，不创建或验证历史验收结论。

需要重现旧固定候选时，先从删除前提交查询相应 InputSet，再按候选绑定建立独立检出，具体方法见 [P0 历史复现](p0-seams.md)。方法或代码变化不沿用旧通过状态。其它常驻检查及其覆盖限制见[精简验证入口](checks.md)。
