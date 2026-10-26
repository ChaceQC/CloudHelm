# 三套独立 Windows Tauri 界面示例

按方案 1、4、8 分别制作，每套都有自己的 Tauri 应用、npm/Cargo 清单与锁文件。进入任一目录即可独立安装、开发或构建，不需要运行另外两套。

|方案|工程|界面与启动端口|
|---|---|---|
|1|[工程工作台](desktop-workspace/README.md)|蓝色侧栏、任务列表与详情，`14201`|
|4|[审批收件箱](desktop-approvals/README.md)|紫色顶部导航、差异审查与批准，`14204`|
|8|[任务手记](desktop-journal/README.md)|暖白文档、进度事实与证据索引，`14208`|

在 Windows PowerShell 中进入所选工程，执行 `npm.cmd ci`、`npm.cmd run desktop:dev`。生成可直接运行的程序使用 `npm.cmd run desktop:build`；构建脚本将 exe 和必需的 `WebView2Loader.dll` 一起放入该工程的 `output/windows/`。具体 Windows 工具前置和操作见各工程 README。

这些 example 只演示本地交互，数据在窗口内存中，不接真实 API、不保存凭据；关闭后重开会恢复初始场景。正式 Desktop 和 P1.5 的实现、恢复与人工验收仍遵循项目计划。
