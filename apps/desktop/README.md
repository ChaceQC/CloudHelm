# CloudHelm 工程工作台

Windows Tauri 2 / React / TypeScript 客户端，使用真实 Hub API。启动、配置和支持边界见[Desktop 开发说明](../../docs/development/p1-desktop.md)。

在本目录的 Windows PowerShell 中运行：

```powershell
npm.cmd ci --no-audit --no-fund
npm.cmd run desktop:dev
```

生成不带安装器的调试程序：`npm.cmd run desktop:build -- --debug`。输出为 `src-tauri/target/debug/cloudhelm-desktop.exe`。浏览器只能展示未连接界面，无法调用原生凭据和连接桥；Linux、安装升级及人工验收分别处理。
