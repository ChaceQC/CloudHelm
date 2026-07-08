# M3 控制台任务主流程官方资料归档

检索日期：2026-07-08
适用阶段：M3 控制台任务主流程

## 1. React state / effect / form

- 来源：
  - [React: Managing State](https://react.dev/learn/managing-state)
  - [React: Synchronizing with Effects](https://react.dev/learn/synchronizing-with-effects)
  - [React: You Might Not Need an Effect](https://react.dev/learn/you-might-not-need-an-effect)
- 摘要：React 推荐把可由 props/state 直接推导的值留在渲染阶段计算；Effect 只用于和外部系统同步；表单交互应使用受控输入和事件处理函数。
- M3 采用结论：
  - Project、Task、Detail 数据读取放入 `useProjects`、`useTasks`、`useTaskDetail`。
  - 表单使用受控输入，提交后只以真实 API 响应刷新状态。
  - Task Detail 通过 `refreshKey` 与外部 Task 操作同步，避免把 API 副作用堆在 `App.tsx`。

## 2. TypeScript 类型建模

- 来源：[TypeScript Handbook](https://www.typescriptlang.org/docs/handbook/intro.html)
- 摘要：TypeScript 通过静态类型描述对象、联合类型和函数边界，适合把 OpenAPI DTO 映射为前端可检查类型。
- M3 采用结论：
  - `apps/control-console/src/shared/types/api.ts` 用联合类型约束 `TaskStatus`、`RiskLevel`、`ReviewStatus` 等后端枚举。
  - API 请求与响应类型集中在 shared types，不在组件内临时猜字段。

## 3. Vite 环境变量

- 来源：[Vite: Env Variables and Modes](https://vite.dev/guide/env-and-mode)
- 摘要：Vite 只向客户端暴露带 `VITE_` 前缀的环境变量。
- M3 采用结论：
  - API base URL 继续使用 `VITE_CLOUDHELM_API_BASE_URL`。
  - `apiClient.ts` 统一拼接 URL，组件不硬编码本机端口或演示环境地址。

## 4. EventSource / SSE

- 来源：
  - [MDN: EventSource](https://developer.mozilla.org/en-US/docs/Web/API/EventSource)
  - [MDN: Using server-sent events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events)
- 摘要：`EventSource` 用于接收 `text/event-stream`，服务端可通过具名事件和 `data` 字段推送消息。
- M3 采用结论：
  - `openTaskEventStream` 优先使用浏览器 `EventSource` 监听 M2 已落库事件类型。
  - 由于 M2 SSE 只回放已有事件并追加 heartbeat，控制台明确标注为“轮询/重连式事件流边界”，并在事件或操作后重新读取 Timeline。

## 5. 前端验证

- 来源：
  - [Vitest Guide](https://vitest.dev/guide/)
  - [Testing Library React](https://testing-library.com/docs/react-testing-library/intro/)
- 摘要：Vitest 可用于 Vite 项目单元测试；Testing Library 推荐从用户可见行为验证 React 组件。
- M3 采用结论：
  - 本阶段未新增测试依赖，避免扩大 M3 依赖面。
  - 使用 `npm.cmd run build` 覆盖 TypeScript/Vite 构建验证。
  - 使用浏览器执行手工 E2E：创建项目 -> 创建任务 -> Pause/Resume/Cancel -> 详情与 Timeline 刷新。
