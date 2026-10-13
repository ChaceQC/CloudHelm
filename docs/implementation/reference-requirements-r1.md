# 首条参照需求 r1

> 修订：reference-requirements-r1
> 日期：2026-10-13（Asia/Shanghai）
> 用途：P0.2 固定参照与独立验收资产建设；不是 CloudHelm 产品功能验收。
> 责任：开发代理建设参照，独立验收代理维护独立断言，项目所有者负责后续正式政策与人类结论。

本轮用户授权完成 P0.2。已有来源为历史 CloudHelm 的 `examples/sample-repo-python`，初始 commit 为 `3293a09c2501ee5bace398c6214dfcb7016c0824`，子树为 `b765b5f8ee988cd1d95f8a45dd6960597d047573`；原切片只具备 FastAPI 健康与指标接口，不能直接作为全栈参照。保留其健康检查语义，新增下列便签场景，作为有界、真实可运行的 React/FastAPI/PostgreSQL/线性 Alembic 示例。

|需求 ID|固定成功条件|
|---|---|
|REF-01|React 页面列出便签，能创建、编辑和删除；界面错误可理解，不将失败显示为成功|
|REF-02|FastAPI 提供 GET/POST `/api/notes`、GET/PATCH/DELETE `/api/notes/{id}`；创建 201，删除 204，不存在 404|
|REF-03|title 去除首尾空白后 1～120 字符；body 最多 4000 字符；超界或空标题返回 422；ID 为服务器生成的整数|
|REF-04|列表按 ID 升序；写入提交到 PostgreSQL，重建 API 进程后数据仍能读取；不以进程内列表模拟持久化|
|REF-05|Alembic 只有单一初始根和线性后继；初始化表含 title、body、UTC 创建/更新时间；应用启动不偷偷 create_all 替代迁移|
|REF-06|`/health` 只证明 API 进程存活；`/ready` 必须实际查询数据库并核验迁移 head，断开数据库或缺少迁移返回 503；响应与错误均无秘密|
|REF-07|前端与后端有实际依赖锁；Compose 含前端、后端、PostgreSQL 及健康检查，数据库不公开主机端口；运行参数与制品分离|
|REF-08|独立验收从仓库 `docs/acceptance/reference/r1/` 提供，仅通过外部 HTTP 和公开迁移工具观测；候选构建上下文不包含该目录，不能改入口、断言或跳过规则取得通过|

该参照只用于隔离测试数据；本修订不增加注册/登录、产品审批或生产部署能力。秘密由运行步骤读取，不出现在响应、诊断或源码；不把示例无认证接口公开用于真实数据。

JSON 响应契约固定如下：列表返回按 ID 升序排列的数组；创建、读取与更新返回单个便签对象，字段为 `id`（整数）、`title`、`body`、`created_at`、`updated_at`（后两项为带 UTC 时区的 ISO 8601 时间）。POST 必须提供 title，body 默认空字符串；PATCH 至少提供 title/body 中一个字段，不接受未知字段或 null。health/ready 以 HTTP 状态作为验收依据，诊断正文不包含连接串或异常详情。前端在同源路径调用上述接口。

固定验收至少覆盖：CRUD/排序与校验、跨前后端契约、数据库持久化、线性迁移、迁移缺失与数据库故障的 readiness 拒绝。单轮方法失败须保留结果；变更候选、需求、验收资产或环境均产生新 InputSet，不继承旧通过结论。验收政策的人类确认和真实独立机器交付留在相应阶段记录，代理不代填。
