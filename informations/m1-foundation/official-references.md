# M1 官方参考资料

> 检索日期：2026-07-08  
> 适用阶段：M1 Monorepo 骨架与最小工程  
> 用途：为 `PROJECT_PLAN.md` 中 FastAPI、uv、Vite、Tauri、OpenAPI、JSON Schema 的最小工程命令和目录取舍提供依据。

## 1. 后端 API 与测试

### FastAPI

- 官方文档：
  - <https://fastapi.tiangolo.com/tutorial/first-steps/>
  - <https://fastapi.tiangolo.com/tutorial/testing/>
  - <https://fastapi.tiangolo.com/reference/apirouter/>
- 适用子任务：`modules/platform-api` 最小 FastAPI 工程、`/health` 路由、pytest 验证。
- 采用结论：
  - 使用 `FastAPI()` 创建应用。
  - 使用 `APIRouter` 拆分 `api/health.py`，避免把路由全部堆在 `main.py`。
  - 使用 `fastapi.testclient.TestClient` 和 pytest 验证 `/health`。

### uv

- 官方文档：
  - <https://docs.astral.sh/uv/concepts/projects/config/>
  - <https://docs.astral.sh/uv/concepts/projects/sync/>
  - <https://docs.astral.sh/uv/guides/tools/>
- 适用子任务：`modules/platform-api/pyproject.toml`、模块内依赖、`uv run pytest`。
- 采用结论：
  - 后端模块优先使用 `uv init --package` 形成可安装的 `src` 布局。
  - 运行项目内工具优先使用 `uv run`，避免污染系统全局 Python 环境。
  - 缺少 `uv` 时先记录阻塞或选择项目内 `.venv` 方案，不直接依赖全局包。

## 2. 前端与桌面端

### Vite

- 官方文档：
  - <https://vite.dev/guide/>
- 适用子任务：`apps/control-console` React + TypeScript 骨架。
- 采用结论：
  - 使用 `npm create vite@latest apps/control-console -- --template react-ts` 初始化。
  - 使用 `npm run build` 作为 M1 前端最小验证。
  - API 地址通过 `VITE_CLOUDHELM_API_BASE_URL` 读取，不在组件中硬编码。

### Tauri

- 官方文档：
  - <https://v2.tauri.app/start/create-project/>
  - <https://v2.tauri.app/start/frontend/>
- 适用子任务：控制台桌面端预留或后续接入。
- 采用结论：
  - M1 可先完成 React/TypeScript 骨架；如本机 Rust/Tauri 条件齐全，再初始化 `src-tauri`。
  - 如果 Tauri 条件不足，需要在 `PROJECT_PROGRESS.md` 记录延后原因，不能把未验证桌面端标记为完成。

## 3. 共享契约

### OpenAPI

- 官方规范：
  - <https://spec.openapis.org/oas/latest.html>
- 适用子任务：`packages/shared-contracts/openapi/cloudhelm.openapi.yaml`。
- 采用结论：
  - M1 只定义 API 基本信息和 `/health` 路径。
  - Task、Agent Run、Tool Call、Approval 等业务接口留到 M2 以后同步实现。

### JSON Schema

- 官方文档：
  - <https://json-schema.org/learn/getting-started-step-by-step>
- 适用子任务：事件 schema、工具风险等级 schema。
- 采用结论：
  - schema 文件必须包含 `$schema`、`title`、`type`、`required`、`properties`。
  - M1 只定义可被后续模块引用的基础结构，不提前实现完整业务状态机。

## 4. 本阶段取舍

- 不直接复制官方模板生成的大量无关文件；以 M1 最小可运行、可测试、可继续扩展为准。
- 不保存第三方文档全文，只保存链接、检索日期、摘要和采用结论。
- 不引入全局依赖；Python、Node 工具优先落在对应模块或通过项目内工具链运行。

## 5. M1 本机工具与实际命令记录

- 检查日期：2026-07-08。
- 本机工具：
  - `node --version`：`v24.13.0`
  - `npm.cmd --version`：`11.6.2`
  - `python --version`：`Python 3.12.10`
  - `uv --version`：`uv 0.11.7`
  - `git --version`：`git version 2.45.1.windows.1`
- Windows PowerShell 当前会拦截 `npm.ps1`，因此前端命令采用 `npm.cmd install` 和 `npm.cmd run build`。
- 后端采用模块内 `uv` 环境，执行 `uv run pytest` 会在 `modules/platform-api/.venv` 安装依赖并生成 `uv.lock`。
- 前端采用项目内依赖，执行 `npm.cmd install` 会在 `apps/control-console` 生成 `package-lock.json`。
- Tauri/Rust：
  - `rustc --version`：`rustc 1.92.0`
  - `cargo --version`：`cargo 1.92.0`
  - M1 按计划只落地 React/TypeScript 骨架；`src-tauri` 留到控制台主流程阶段接入，避免在最小工程阶段提前扩大桌面端验证范围。
