# CloudHelm · 审批收件箱

按已选方案 4 制作的独立 Windows Tauri 2 / React / TypeScript example。紫色顶部导航与审批收件箱，展示当前/目标差异、四个部署阶段、完整摘要与批准期限。勾选核对后才可本地批准；批准后执行仍未开始。

三套示例各自独立，不共享启动入口或运行时依赖，导航见 [独立桌面示例](../desktop-examples.md)。数据与操作仅保存在当前窗口内存中；重新打开或刷新后回到初始场景。没有连接 Hub、模型、数据库或远端执行器，也不接收真实设备会话或密钥。

## 在 Windows 启动

需要 Windows x64、Node.js/npm、Rust 的 `stable-x86_64-pc-windows-gnu` 工具链、PATH 中可用的 MinGW-w64 GCC/windres，以及 Microsoft Edge WebView2 Runtime。工程自己的 `src-tauri/rust-toolchain.toml` 选择 GNU 工具链，不修改机器默认工具链。首次准备可使用 `rustup toolchain install stable-x86_64-pc-windows-gnu`；MinGW-w64 和 WebView2 使用各自官方安装来源。

在本工程目录打开 PowerShell：

```powershell
npm.cmd ci
npm.cmd run desktop:dev
```

原生窗口使用本工程自己的 Vite 地址 `http://127.0.0.1:14204/`。只核对网页布局时可单独运行 `npm.cmd run dev`，使用 Windows Edge 查看该地址。

## 生成可直接运行的程序

```powershell
npm.cmd run desktop:build
```

程序输出到 `output/windows/cloudhelm-desktop-approvals.exe`，同目录保留 `WebView2Loader.dll`。双击 exe 可独立运行，不需要启动 Vite；移动时保留这两个文件。开发调试构建使用 `npm.cmd run desktop:build -- --debug`，同样输出可运行程序；本示例不生成安装器。

`npm.cmd run build` 执行 TypeScript 检查和前端构建。依赖锁定在各自的 `package-lock.json`、`src-tauri/Cargo.lock`；修改图标时运行 `npm.cmd run icons`，从 Phosphor 标准库图标生成 Windows 图标及 favicon。未使用文件系统、Shell、网络请求插件或业务 IPC。

## 状态与范围

初始日期与审批期限是固定演示输入，不应用于真实授权。Task、计划批准、执行接收、unknown 和物理停止分别展示：取消后继续保留停止待确认及资源占用；查询不会把未知改写为成功。秘密仅显示 `notes-db` 引用。

正式 P1.5、Hub 快照/SSE、设备凭据保护、worker 恢复、生产部署、安装升级和人工产品验收不属于此 example。视觉对照与本轮实际验证见 [design-qa.md](design-qa.md)；项目进度统一记录在 [PROJECT_PROGRESS.md](../../PROJECT_PROGRESS.md)。
