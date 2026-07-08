# modules/platform-api

CloudHelm 平台 API 服务。M1 使用 FastAPI 提供真实 `/health`，用于验证后端模块、前端控制台和共享契约的最小闭环。

## 命令

```powershell
uv run pytest
uv run uvicorn cloudhelm_platform_api.main:app --host 127.0.0.1 --port 18080
```

启动后验证：

```powershell
Invoke-RestMethod http://127.0.0.1:18080/health
```

## 环境变量

- `CLOUDHELM_ENV`：运行环境，默认 `development`。
- `CLOUDHELM_VERSION`：服务版本，默认 `0.1.0`。

## 当前边界

M1 不连接数据库，不实现 Task API、Agent Run API、Tool Call API 或 Approval API。上述接口会在 M2 以后按共享契约和数据模型逐步实现。
