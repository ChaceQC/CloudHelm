# CloudHelm 工程工作台

Windows Tauri 2 / React / TypeScript 客户端，使用真实 Hub API。启动、配置和支持边界见[Desktop 开发说明](../../docs/development/p1-desktop.md)。

在本目录的 Windows PowerShell 中运行：

```powershell
npm.cmd ci --no-audit --no-fund
npm.cmd run desktop:dev
```

生成不带安装器的调试程序：`npm.cmd run desktop:build -- --debug`。输出为 `src-tauri/target/debug/cloudhelm-desktop.exe`。浏览器只能展示未连接界面，无法调用原生凭据和连接桥；Linux、安装升级及人工验收分别处理。

客户端连接 `p1-hub-api-r3` 的 Hub。任务的 Agent 面板先加载摘要，展开 Run 时查询该轮明细；工作区差异仍按工作项单独查询。命令回执由原生层持久保存后展示；断线后可[使用原身份核对](../../docs/development/p1-desktop.md#未确认命令)。

在工作台右上角可以切换深浅色主题，选择保存在本机。选中任务后，从「概览与控制」「Agent 推进」「人工测试」三个标签进入对应内容。

在“人工测试”页选择轮次，再点击“查询实际环境与撤销状态”。最新且仍可测试的轮次在环境就绪、安装方已验证 Windows 路线时提供“打开隔离预览”。原生层向 Hub 重查当前测试者资格，再为该环境打开独立窗口。历史轮次和终态轮次可查阅。切换轮次或项目、离开人测页、收到撤销或停止通知都会关闭旧窗。同轮从准备进入测试或记录活动时保留原窗。

原生层分别报告实际收窗和专用分区删除，主窗口按窗口标识保留两项事实，可逐条关闭提示。清理失败时，分区可能仍留在本机；原目录不会复用。服务端撤销已请求和相关代理已确认断开另按环境查询展示，缺少证据时保持待确认。

正式路线默认关闭，当前本机证据不构成安装或人工验收放行。配置、受控入口与未满足门禁见[预览说明](../../docs/development/p2-previews.md)及[收尾记录](../../docs/acceptance/p2/p2-4-02-followup.md)。
