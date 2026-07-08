# 云舵 CloudHelm

CloudHelm 是面向毕业设计演示的多 Agent DevOps 系统。本仓库当前处于 **M1：Monorepo 骨架与最小工程** 阶段，目标是先形成可运行、可测试、可继续扩展的工程基线。

> 当前版本：`0.1.0`  
> 当前范围：最小 FastAPI `/health`、最小 React/TypeScript 控制台、共享契约起点和资料归档入口。

## 目录结构

```text
apps/
  control-console/        # React + TypeScript 控制台骨架，后续接入 Tauri
modules/
  platform-api/           # FastAPI 平台 API，M1 提供真实 /health
packages/
  shared-contracts/       # OpenAPI、事件 schema、工具风险等级 schema
infra/                    # 后续 Docker Compose、CI 和部署配置
examples/                 # 后续演示仓库、演示 issue 和脚本
tests/                    # 后续跨模块集成测试和 E2E 测试
informations/             # 官方资料、命令来源和阶段性调研摘要
docs/                     # 设计文档与里程碑流程
```

## 后端：platform-api

```powershell
cd modules/platform-api
uv run pytest
uv run uvicorn cloudhelm_platform_api.main:app --host 127.0.0.1 --port 18080
```

启动后可验证：

```powershell
Invoke-RestMethod http://127.0.0.1:18080/health
```

## 前端：control-console

Windows PowerShell 如果拦截 `npm.ps1`，使用 `npm.cmd`：

```powershell
cd apps/control-console
npm.cmd install
$env:VITE_CLOUDHELM_API_BASE_URL='http://127.0.0.1:18080'
npm.cmd run dev
```

构建验证：

```powershell
cd apps/control-console
npm.cmd run build
```

## 共享契约

M1 已建立共享契约起点：

- `packages/shared-contracts/openapi/cloudhelm.openapi.yaml`
- `packages/shared-contracts/schemas/events/task-event.schema.json`
- `packages/shared-contracts/schemas/tools/tool-risk-level.schema.json`

后续 M2 开始实现 Project、Task、Requirement、Design、Event API 时，需要同步扩展这些契约。

## 环境变量

复制根目录 `.env.example` 后按本机环境调整。M1 使用的变量包括：

```env
CLOUDHELM_ENV=development
CLOUDHELM_VERSION=0.1.0
CLOUDHELM_API_HOST=127.0.0.1
CLOUDHELM_API_PORT=18080
VITE_CLOUDHELM_API_BASE_URL=http://127.0.0.1:18080
```

## informations 资料归档

`informations/` 只保存官方链接、检索日期、摘要、采用结论和少量必要摘录。禁止保存真实密钥、Token、Cookie、账号密码、真实服务器管理入口、许可证不明的大段代码或第三方文档全文。

M1 资料入口：

- `informations/README.md`
- `informations/m1-foundation/official-references.md`

## 当前未实现能力

M1 不实现 Task API、Agent 编排、Tool Gateway、数据库持久化、远端部署、监控告警或完整桌面端壳。上述能力将在 M2 及后续里程碑按 `PROJECT_PLAN.md` 和 `docs/14-roadmap/03-implementation-milestone-flow.md` 逐步实现。
