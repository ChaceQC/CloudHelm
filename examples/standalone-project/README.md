# 首条全栈参照：便签

本目录提供用于 CloudHelm 首条链路的可运行源码：React/TypeScript 前端、FastAPI 后端、PostgreSQL 及两条线性 Alembic 迁移。需求与验收资产独立保存在 [固定需求](../../docs/implementation/reference-requirements-r1.md) 和 [外部验收入口](../../docs/acceptance/reference/r1/README.md)，它们不进入构建上下文。

本参照只使用本机隔离合成数据：入口绑定 `127.0.0.1:58080`，数据库没有主机端口，内部连接使用 trust。该配置不提供认证或生产部署能力。服务启动不执行迁移；迁移必须显式运行。

在 WSL 的仓库根目录执行：

```bash
docker compose -f examples/standalone-project/compose.yaml build
docker compose -f examples/standalone-project/compose.yaml up -d postgres
docker compose -f examples/standalone-project/compose.yaml run --rm backend alembic upgrade head
docker compose -f examples/standalone-project/compose.yaml up -d --wait
python3 docs/acceptance/reference/r1/verify_http.py --base-url http://127.0.0.1:58080
```

浏览器打开 `http://127.0.0.1:58080`，可以创建、编辑和删除便签。`/health` 证明 API 存活；`/ready` 检查真实数据库与迁移 head。`docker compose ... restart backend` 不删除数据库卷，可用于独立资产的持久化核验。

结束隔离实验时用本文件对应的 `docker compose ... down --volumes` 定向移除服务和合成数据库，不清理其他项目。本目录的候选标签和 `0.0.0` 工程元数据不表示 CloudHelm 产品发布版本。来源、冻结输入与支持边界见 [参照链路规格](../../docs/implementation/reference-chain.md)。
