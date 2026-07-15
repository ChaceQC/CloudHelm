# apps/control-console

> 来源：[设计书 7.1-7.2](../../../云舵 CloudHelm 毕设设计书.md)  
> 层级：`apps/control-console`

## 职责

Windows/Linux Desktop，负责 Ops Hub server profile、登录、项目/任务、Agent
指导、方案审查、diff、日志、审批、远程状态和权限化交互。

## M3-M6 实现状态

当前 Web 控制台已经接入真实 Project、Task、Requirement、TechnicalDesign、
DevelopmentPlan、AgentRun、ToolCall、Approval、Timeline、Artifact 和
PullRequestRecord API。M6 页面可以启动/推进本地开发步骤，并展示真实 diff、
pytest/JUnit、Review、Bandit、pip-audit 与本地等价 PR record。

SSE 显式监听 M2-M6 事件并按 event id 去重；切换 Project/Task 使用最新请求门禁。
1280、1024 和 375 像素目标视口要求 document 无水平溢出，长 diff 只在局部容器
滚动。

当前不包含远端部署、监控、任意工具调试或交互终端。

当前目录没有 `src-tauri`，也没有 NSIS/MSI/AppImage/`.deb` 安装产物、运行时
server profile、Desktop SQLite、OS credential store、用户登录或 effective
permission UI，因此只能称为 Web 控制台，不能称为已交付桌面 App。

## 当前技术栈

React + TypeScript + Vite。Tauri、SQLite、OS credential store、
`modules/local-runtime`、Tailwind CSS、shadcn/ui、Monaco 和 xterm.js 是目标
技术组合，尚未全部进入当前工程。

## 目标技术栈

Tauri v2 + React + TypeScript + SQLite + OS credential store + Local Runtime
sidecar + Tailwind CSS + shadcn/ui + Monaco Editor + xterm.js。

## 上游依赖

Auth/User/Permission、Project/Task/Event/Sync/Approval/Remote Ops API。

## 主要输出

需求输入、审批动作、权限化 UI、server profile、离线缓存和事件订阅。

## MVP 实现要点

1. 先实现与全流程演示直接相关的最小能力。
2. 所有跨模块调用优先通过共享契约和 API，不直接耦合内部实现。
3. 状态变化、工具调用、审批、远程操作都必须写入事件或审计记录。
4. 与远端业务项目相关的操作必须绑定 `project_id + environment_id + deployment_id + service_id`。
5. Desktop 不直连 PostgreSQL、Redis 或 Remote Agent，不要求最终用户安装 Docker。
6. 页面和按钮按 effective permissions 渲染，但服务端 API 必须再次鉴权。
7. Windows 必须生成 setup `.exe`，Linux 必须生成 AppImage 和 `.deb`。

## 测试关注点

- 参数校验和错误处理。
- 与相邻模块的集成路径。
- 失败重试、暂停、审批和人工接管场景。
- 关键输出是否能被控制台展示和被审计追踪。
