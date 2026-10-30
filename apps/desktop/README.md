# CloudHelm 工程工作台

Windows Tauri 2 / React / TypeScript 客户端，使用真实 Hub API。启动、配置和支持边界见[Desktop 开发说明](../../docs/development/p1-desktop.md)。

在本目录的 Windows PowerShell 中运行：

```powershell
npm.cmd ci --no-audit --no-fund
npm.cmd run desktop:dev
```

生成不带安装器的调试程序：`npm.cmd run desktop:build -- --debug`。输出为 `src-tauri/target/debug/cloudhelm-desktop.exe`。浏览器只能展示未连接界面，无法调用原生凭据和连接桥；Linux、安装升级及人工验收分别处理。

`0.29.0` 增加独立Windows预览容器。Task的人测轮次查询到ready且安装方已登记并验证 `tauri_windows_webview2` 时，可选择“打开隔离预览”；容器内自行认证，经管理页POST交付票据。主窗口只查询公开固定目标，不转交管理凭据或票据。窗口关闭后回收独立分区，原目录不复用；服务端撤销和客户端分区清理是不同事实。

正式路线默认关闭，当前本机证据不构成安装或人工验收放行。配置、受控入口与未满足门禁见[预览说明](../../docs/development/p2-previews.md)及[收尾记录](../../docs/acceptance/p2/p2-4-02-followup.md)。
