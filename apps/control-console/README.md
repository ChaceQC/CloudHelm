# apps/control-console

CloudHelm 控制台前端骨架，使用 React + TypeScript + Vite。M1 只实现平台 API `/health` 的真实调用和错误展示，不提供静态假任务、假 Agent 或假部署数据。

## 命令

```powershell
npm.cmd install
$env:VITE_CLOUDHELM_API_BASE_URL='http://127.0.0.1:18080'
npm.cmd run dev
npm.cmd run build
```

## 配置

- `VITE_CLOUDHELM_API_BASE_URL`：平台 API 地址，例如 `http://127.0.0.1:18080`。

## Tauri 说明

M1 保留 React/TypeScript 工程边界，未初始化 `src-tauri`。Tauri 桌面壳会在控制台功能进入可交互主流程后再接入，避免在最小工程阶段提前扩大依赖和验证范围。
