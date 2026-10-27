# 日常定向检查

当前源码只保留持续开发需要的关键检查。已完成阶段的 SDK/远端接缝、完整工程链、故障注入和固定候选重验方法已移除，历史代码不搬到其它目录继续维护。

下表中的 Linux/后端命令在 WSL Ubuntu-24.04 的仓库根目录执行，使用已有锁定环境；Windows Desktop 命令单列于后文并直接在 Windows 执行。普通文档修改不重跑业务、数据库、模型或容器实验。

|入口|保留范围|执行条件|
|---|---|---|
|`python -B -m scripts.p0.check_decisions`|完整决定 schema 快照及七类关键纯函数边界|CI 或相应契约修改|
|`python -B -m scripts.p1.check_public_contracts`|Hub OpenAPI 快照，不进入数据库 lifespan|CI 或 HTTP 契约修改|
|`python -B -m scripts.p1.check_workspace_git`|真实 Git 文件视图、安全路径、链接及读取限额|CI 或文件/Git 边界修改|
|`python -B -m scripts.p1.check_artifact_content`|合成 OCI tar 的实际内容、摘要、成员与限额拒绝|CI 或制品内容边界修改|
|`python -B -m scripts.p1.check_database`|真实临时 PostgreSQL 初始化、角色、互斥与事务回滚|按需；会创建并定向清理隔离数据库|
|`python -B -m scripts.p1.check_sync`|快照、持久分发回滚/去重、流与权限重建及有限 HTTP SSE|仅同步变化时按需；只使用并清理自己的隔离数据库，不运行 worker/模型/远端链|
|`python -B -m services.dev-runner.development_storage_maintenance verify-pool`|原存储维护命令及其实际调用的 `scripts.p1.probe_development_storage`|按需；原受控 WSL 维护条件不变|
|`python -B docs/acceptance/reference/r1/verify_http.py --base-url http://127.0.0.1:58080`|独立参照 HTTP 资产，保持原字节与修订|已有隔离参照服务时按需执行|

前四项可用 `uv run --locked --offline --no-sync` 前缀运行。数据库与存储命令不属于日常静态检查，不为测试精简重复运行。独立 HTTP 入口和 manifest 被工程来源校验引用，本轮不修改或裁剪。

CI 仍保留仓库结构/编码/入库边界、锁定依赖、源码语法、契约与参照 OpenAPI、Git/OCI、参照锁与前端构建，工作流和必需检查名称保持“仓库验证 / check”。旧三套 Tauri example 已按用户要求退役，对应依赖缓存和构建步骤一并移除；HTML 原型不新增 npm 或 Rust 工具链要求。

## Windows 基础 Desktop

正式工程为 `apps/desktop/`。在 Windows 执行 `npm.cmd ci --no-audit --no-fund`、`npm.cmd run build` 和所需的 Tauri 构建，见[客户端说明](p1-desktop.md)。CI 构建正式前端；Rust/Tauri、WebView2 和原生人工验收单独记录，不转入 WSL 构建桌面端。

## HTML 界面原型

直接打开 `examples/p1-5-html/index.html`，从总览进入五套独立结构的方案。全部使用普通 HTML、CSS 和 JavaScript，不需要安装依赖；本地 HTTP 预览及覆盖说明见 [示例入口](../../examples/desktop-examples.md)。

视觉与主要交互按需要使用 Windows Edge Playwright 核对，只检查本次页面、链接、脚本语法与状态投影；不调用业务 API、模型、数据库或容器实验。HTML 浏览器结果不能作为 Tauri/WebView2、worker 恢复或人工产品验收证据。

## 历史方法与覆盖边界

完整 P0、P1.1、P1.2 和 P1.3-01 方法按历史候选独立检出。已删的 80 份历史 JSON 从提交 `b20a5e30fd0f3ddea50b7a7dc9b8e0fc3fbe1df1` 查询，再按输入和方法绑定复现，见 [历史记录入口](p0-seams.md#取回历史方法)。当前参照 InputSet 和独立验收资产继续保留；历史验收说明中的相对源码链接按绑定候选解释，已删路径在对应检出查看。

当前保留集合缩减了 SDK 组合、真实 HTTP/worker/工程构建、Task 并发/故障与资源物理执行的常驻自动回归。精简检查通过不等于这些完整流程重新通过；后续相关行为变化仍按实际风险建立新输入与必要定向证据，原阶段和人工验收状态不变。
