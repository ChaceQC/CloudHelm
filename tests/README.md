# tests

本目录用于跨模块集成测试和 E2E 测试。M6 以前的白盒与 API 集成测试主要位于
各模块 `tests/`：

- `modules/platform-api/tests`：数据库、迁移、API、M4/M6 工作流和契约。
- `modules/agent-runtime/tests`：八类 Agent、Provider 和结构化输出。
- `modules/tool-gateway/tests`：工具、策略、审计与 M6 execution recipe 边界。
- `modules/orchestrator/tests`：M4/M6 纯状态机。
- `apps/control-console/tests`：操作策略、证据映射和 SSE 事件。

根目录 `tests/` 供 M7 远端部署及后续完整 E2E 使用，不能用静态假数据替代真实
API、数据库、Git、CI 或远端链路。
