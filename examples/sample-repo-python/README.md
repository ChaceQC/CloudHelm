# CloudHelm Python Sample Service

这是 CloudHelm M6 本地代码实现、测试与等价 PR 闭环使用的受控 FastAPI
fixture。基线能力只有：

- `GET /health`：返回服务健康状态。
- `GET /metrics`：返回 Prometheus text exposition format 指标。
- pytest：覆盖健康检查和指标起点。

`demo-issues/001-auth-profile.md` 中的注册、登录和个人资料能力尚未实现，必须由
M6 Coder 流程在受控工作区副本中产生真实代码 diff、测试和 Git 记录。

## 环境要求

- Python 3.12+
- uv 0.11+

## 本地启动

```powershell
uv sync
uv run uvicorn sample_service.main:app --host 127.0.0.1 --port 8000
```

启动后可访问：

- `http://127.0.0.1:8000/health`
- `http://127.0.0.1:8000/metrics`
- `http://127.0.0.1:8000/docs`

PowerShell 烟测：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-WebRequest http://127.0.0.1:8000/metrics | Select-Object -ExpandProperty Content
```

## 运行测试

```powershell
uv lock --check
uv run pytest -q
```

## Docker Compose

```powershell
docker compose up --build
docker compose down
```

Compose 只把端口绑定到本机 `127.0.0.1:8000`，并使用容器健康检查访问
`/health`。

## Fixture 约束

- 不在本目录初始化嵌套 `.git`。
- 不提交 `.venv`、缓存、测试报告、构建产物或凭据。
- CloudHelm Scaffold 复制本 fixture 时应排除上述内容，再在受控副本中建立
  baseline commit。
