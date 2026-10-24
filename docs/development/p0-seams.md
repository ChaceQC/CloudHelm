# P0 历史接缝复现

P0 的数据库/DBOS、模型/Gateway、恢复、Compose 和远端协议实验已完成其准备阶段职责。当前分支已移除这些历史探针、专用接缝适配器和临时 Compose 夹具；日常保留的检查见[精简验证入口](checks.md)。当前 P0 决定契约检查仍见 [p0-decisions.md](p0-decisions.md)。

[组件基线](../decisions/p0/component-baseline.md)、[接缝结论](../acceptance/p0/seam-summary.md)、六张 SDK 卡及历史 InputSet/报告保留原字节。它们只证明绑定的候选、环境和方法，不随当前测试精简获得新的适用性。

## 取回历史方法

优先使用对应 InputSet 的 `source_commit`。如需查看精简前的完整开发工具集合，可在 WSL 建立独立检出：

```bash
git worktree add --detach /tmp/cloudhelm-historical-09cf13c 09cf13c978d90433d1b99165dfc9c033e0454d23
```

随后阅读该检出内原版本的 `docs/development/p0-seams.md`，按报告绑定的依赖、资产和环境复现。该命令只取回源码，不运行数据库、容器或收费请求；不要将历史脚本复制回当前开发目录。

## 证据和运行边界

历史文档中的相对源码链接按其候选提交解释；已删除路径应在独立检出查看。旧费用 journal、unknown 记录、原操作身份与恢复引用不能为了重跑而删除或重置。历史收费批次不自动获得再次执行授权。

s2413 同机准备与真实独立机器交付仍分别取证，见[开发组合决定](../decisions/p0/s2413-development-envelope.md)和[支持矩阵](../acceptance/support-matrix.md)。新产品代码或运行环境变化时，按实际风险建立新的定向方法和输入，不把历史通过记录当作当前功能验证。
