# FastAPI 便签后端参照

该目录是 P0.2 隔离参照，不是 CloudHelm 产品服务。Python 固定为 3.12.13；FastAPI、SQLAlchemy、Alembic、Pydantic 与 psycopg 使用根目录锁定版本作为参照候选，本目录单独维护 `uv.lock`。Dockerfile 的 Python 基础镜像标签仍是候选，由主会话统一冻结。

在 WSL Ubuntu-24.04 的该目录中安装锁定依赖：

```sh
uv sync --locked
```

设置运行环境变量 `DATABASE_URL`（驱动方案使用 `postgresql+psycopg://`）后，先显式运行迁移，再启动 API：

```sh
uv run alembic upgrade head
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

连接串仅从进程环境读取，不写入文件或日志。应用启动不会创建或升级数据库表；数据库不可用、未迁移到唯一 head 时，`/ready` 返回 503，而 `/health` 只报告 API 进程存活。

以本目录作为 Docker 构建上下文。运行镜像不包含数据库地址，部署时由运行环境提供 `DATABASE_URL`；迁移通过同一镜像显式执行 `alembic upgrade head`。示例无身份验证，只能用于隔离数据。
