# P0 历史接缝复现

P0 的数据库/DBOS、模型/Gateway、恢复、Compose 和远端协议实验已完成其准备阶段职责。当前分支已移除这些历史探针、专用接缝适配器和临时 Compose 夹具；日常保留的检查见[精简验证入口](checks.md)。当前 P0 决定契约检查仍见 [p0-decisions.md](p0-decisions.md)。

[组件基线](../decisions/p0/component-baseline.md)、[接缝结论](../acceptance/p0/seam-summary.md)与六张 SDK 卡保留阶段摘要。80 份历史运行/清理报告、InputSet 与跨轮适用性 JSON 已按用户授权于 2026-10-24 从当前树移除，原字节从删除前 Git 提交查询。它们只证明绑定的候选、环境和方法。

## 取回历史方法

先从删除前提交 `b20a5e30fd0f3ddea50b7a7dc9b8e0fc3fbe1df1` 查看原始记录。例如在 WSL 查询 P1.2 的最终 InputSet：

```bash
git show b20a5e30fd0f3ddea50b7a7dc9b8e0fc3fbe1df1:docs/acceptance/p1/input-set-p1-2-r12.json
```

再按其中的 `source_commit` 和方法版本取回对应源码；仅有 `base_commit` 或工作树候选身份时，须同时核对记录中的文件摘要，不能把基础提交当作完整候选。缺少历史字段时不补造。

如需查看测试精简前的完整开发工具集合，可在 WSL 建立独立检出：

```bash
git worktree add --detach /tmp/cloudhelm-historical-09cf13c 09cf13c978d90433d1b99165dfc9c033e0454d23
```

随后阅读该检出内原版本的 `docs/development/p0-seams.md`，按报告绑定的依赖、资产和环境复现。这些命令只查看或取回历史文件，不运行数据库、容器或收费请求；不要将历史脚本复制回当前开发目录。

## 证据和运行边界

历史文档中的相对源码链接按其候选提交解释；已删除路径应在独立检出查看。旧费用 journal、unknown 记录、原操作身份与恢复引用不能为了重跑而删除或重置。历史收费批次不自动获得再次执行授权。

s2413 同机准备与真实独立机器交付仍分别取证，见[开发组合决定](../decisions/p0/s2413-development-envelope.md)和[支持矩阵](../acceptance/support-matrix.md)。新产品代码或运行环境变化时，按实际风险建立新的定向方法和输入，不把历史通过记录当作当前功能验证。
