# Desktop 打包、安装与升级

> 目标：CloudHelm App 可在 Windows 和 Linux 桌面环境独立安装运行。
> 当前状态：规划已冻结，`apps/control-console` 仍是 Vite Web 工程，尚未创建
> Tauri 壳或安装产物。

## 1. 发行目标

M9 实现 Tauri/Desktop/Local Runtime/IAM 基础能力；M10 生成并验证真实发行包。

### Windows x86_64

必交付：

```text
CloudHelm_<version>_x64-setup.exe
CloudHelm.exe
SHA256SUMS
```

- setup `.exe` 使用 Tauri NSIS bundle。
- 安装器创建开始菜单入口和卸载项。
- 应用数据目录、日志、SQLite 和 credential store 位置必须记录。
- 卸载默认保留用户配置/草稿，提供显式“删除本地数据”选项。
- MSI 作为可选企业安装包。

### Linux x86_64

必交付：

```text
CloudHelm_<version>_amd64.AppImage
cloudhelm_<version>_amd64.deb
SHA256SUMS
```

- AppImage 用作直接运行的桌面可执行文件。
- `.deb` 用作 Ubuntu/Debian 安装包。
- `.rpm` 作为可选产物。
- 构建使用明确的最老支持 Linux 基线，并记录 WebKitGTK、GTK、libssl 等系统
  依赖。

## 2. 安装包内容

```text
CloudHelm Desktop
├── Tauri shell
├── React/Vite static assets
├── local-runtime sidecar
├── SQLite migration/resources
├── icons/license/version metadata
└── update public key/config
```

安装包不包含：

- PostgreSQL。
- Redis。
- Docker Desktop/Engine。
- Remote Agent。
- 远端 Ops Hub secret。
- 用户业务项目源码或数据。

## 3. 首次启动

首次启动向导：

1. 选择语言和本地数据目录。
2. 添加 Ops Hub URL，只允许 HTTPS；开发 profile 可显式启用 localhost HTTP。
3. 执行服务器 discovery/version/compatibility 检查。
4. 完成管理员登录或 device pairing。
5. 将 token/Ed25519 device private key 保存到 OS credential store。
6. 初始化 Desktop SQLite。
7. 选择允许 Local Runtime 访问的 workspace roots。
8. 拉取项目 snapshot 和事件 high-watermark。

不能把 API base URL 只编译进 `VITE_CLOUDHELM_API_BASE_URL`。安装后的 server
profile 必须可新增、切换、重命名和删除。

## 4. 运行模式

|模式|用途|Docker/PostgreSQL 要求|
|---|---|---|
|Desktop product|连接远端 Ops Hub|无|
|Desktop + Local Runtime|本机 Agent 开发|核心路径无；Docker sandbox 可选|
|Contributor development|开发 CloudHelm 仓库|可使用 Docker Compose PostgreSQL/Redis|
|Demo all-in-one|单台 Linux 部署 Ops Hub、Agent 和项目|远端 Linux 使用 Docker Compose|

## 5. 离线行为

Desktop 断网或退出：

- 展示最后缓存数据及缓存时间。
- 允许保存需求、评论等未提交草稿。
- 不把缓存状态显示为实时状态。
- 不静默重放审批、部署、取消、回滚或远端命令。
- Local Runtime 未配置后台服务时暂停本地开发步骤。
- Ops Hub 中已持久化的远端工作流继续运行。

恢复连接：

1. 刷新用户/device 凭据。
2. 拉取 snapshot 和缺失 event sequence。
3. 校验 aggregate version。
4. 更新待审批、部署、告警和任务状态。
5. 对离线草稿重新做 freshness 检查，由用户确认后提交。

## 6. 构建流水线

后续建立原生构建矩阵：

```text
windows-latest
  -> npm test / typecheck / build
  -> Rust test
  -> sidecar build
  -> tauri build --bundles nsis
  -> clean VM install smoke

linux baseline
  -> npm test / typecheck / build
  -> Rust test
  -> sidecar build
  -> tauri build --bundles appimage,deb
  -> clean VM/container install smoke
```

原则：

- Windows 安装包在 Windows runner 构建；Linux 包在 Linux runner 构建。
- sidecar 必须按目标 triple 命名和打包。
- 发行产物生成 SHA-256，并保存 SBOM/依赖扫描结果。
- 公开发行前启用代码签名；签名材料只来自 CI secret store。
- Tauri updater 只接受签名更新，不允许未签名自动升级。

## 7. 安装验收

### Windows

- 干净 Windows 11 VM 未安装 Docker/PostgreSQL/Redis。
- setup `.exe` 安装成功并生成 `CloudHelm.exe`。
- 首次启动可配置 Ops Hub 并登录。
- 重启系统后配置、SQLite 和 credential 可读。
- 升级后缓存/草稿保留，卸载项正常。

### Linux

- AppImage 添加执行权限后可启动。
- `.deb` 可安装、启动、升级和卸载。
- 无 Docker/PostgreSQL/Redis 时仍可作为 Ops Hub 客户端运行。
- 桌面图标、应用菜单、文件权限和 sidecar 启动正常。

### 跨平台

- 同一 Ops Hub profile 可分别由 Windows/Linux 客户端连接。
- 分别使用 Developer、Reviewer、Operator、Approver、Auditor、Viewer 登录，
  页面/按钮与 API 403 行为符合 effective permissions 和职责分离。
- App 关闭期间远端 WorkflowJob、Remote Agent heartbeat 和监控继续。
- 重连无事件丢失、重复执行或旧缓存覆盖新状态。
- credential 不出现在 SQLite、日志、crash report 或 UI 调试信息中。

## 8. 当前完成判定

本文件只表示目标契约已规划。以下证据全部存在后，才能把 Desktop 打包标记完成：

- `src-tauri`、Rust command 和 local-runtime sidecar 已实现。
- Windows setup `.exe` 与 Linux AppImage/`.deb` 已真实生成。
- 两个平台的干净环境安装/E2E 通过。
- Desktop 无 Docker/PostgreSQL/Redis 前置依赖。
- 运行时 server profile、认证、SQLite、离线/重连同步通过。
- 安装、升级、卸载、checksum、签名和回滚证据已归档。
