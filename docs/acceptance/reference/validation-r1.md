# 参照候选本机验证 r1

日期：2026-10-13（Asia/Shanghai）。固定需求 reference-requirements-r1，最终独立方法 reference-http-r1.1；源码、需求和方法由 [InputSet](input-set-r1.json) 冻结。环境为 [实际拓扑](../../decisions/p0/topology.md) 的 WSL 开发机，不是独立目标交付或原生 Desktop 验收。

## 输入与执行

候选：React/TypeScript/Vite 6.4.4 前端、FastAPI/PostgreSQL/Alembic 后端。基础镜像及锁见 `examples/standalone-project/compose.yaml`。最终 Docker 候选身份：

- backend `sha256:c5aae3849a2921fcbfee5591eb90df8d335aff224fd3b90f2f498af0f9e87dba`。
- frontend `sha256:8352361124d8cfaa6015c90724f154278f9faa0fb7b07877be5aeddc8f3d0640`。

实际方法：WSL `docker compose -f examples/standalone-project/compose.yaml config --quiet/build/up -d --wait`；迁移独立运行 `run --rm --no-deps backend alembic upgrade head`，并通过公开 `alembic current/heads/history` 核对。验收入口从仓库 docs 独立运行，候选构建上下文只含 frontend/backend，各自 `.dockerignore` 排除依赖、秘密与生成物，不能访问独立断言。

|场景与实际准备|方法/结果|支持范围|
|---|---|---|
|未执行迁移的新数据库|method r1.0 not-ready 2/2 通过；health200/ready503|证明应用启动未替代正式迁移；随后显式 upgrade 两修订|
|线性迁移与 head|单根 0001_create_notes → 0002_add_updated_at_index；current=head，命令退出0|仅该固定 PostgreSQL 16.13 候选|
|最终候选正常运行|method r1.1 baseline 43/43 通过；最终轮窗口截至2026-10-13T08:07:42Z|CRUD、201/204/404/422、title/body边界、排序、UTC字段、同源HTML/JS；OpenAPI SafeError 与实际 detail 字符串一致|
|持久化|r1.1 seed 3/3；保留同一数据库卷并 `restart backend`；verify-persisted 2/2|数据库持久化而非进程列表；仅重启API，不宣称数据库灾难恢复|
|停止数据库|最终 backend DNS解析/建连/池等待有界；stop postgres 后 r1.1 not-ready 2/2，health200/ready503|固定开发网络与超时配置；不推定所有生产DNS故障上界|
|前端交互|内嵌浏览器实际新增、编辑、删除，均看到真实成功反馈；故障状态HTTP503显示中文错误且保留表单|浏览器结果，不代替Tauri/WebView原生；截图在被忽略的 .thesis-work/acceptance|
|依赖与构建|backend uv locked sync/导入、前端 npm ci/tsc/Vite、两个Docker镜像构建均通过；Vite 6.4.4 npm audit 为0项漏洞|固定锁与当前已知公告快照，不是持续安全认证|

## 失败轮次与修复边界

首次容器刚启动即运行 not-ready 时，连接尚未稳定，2项均失败；待服务存活后对同缺迁移场景取得2/2，不以启动返回作为通过。

method r1.0 baseline 41项中40过、1失败：脚本删除 CRUD core 后，末尾仍要求该 marker 存活。独立验收代理修正资产缺陷，保留全列表排序并增加倒序标题配对断言，递增到 r1.1；随后43/43。没有修改候选来绕过断言。

基线重跑清除了持久化 marker，因此一次 verify-persisted 只有清理项通过、存在项失败；该轮保留为方法顺序错误，不用于证明持久化。按 r1.1 重新 seed → API restart → verify-persisted 后2/2通过。

旧 backend 停止数据库时，ready 请求因建连/DNS等待超时，health通过、ready项失败；新增连接与池等待2秒、开发DNS timeout1/attempts1，重建 backend、新运行输入后得到2/2，未将旧候选追认为通过。前端最早 Vite 6.3.5 有一项 high 审计结果；升级到报告最小修复版本6.4.4并重新锁定/构建/审计，最终0项；旧输入不保留为支持候选。

## 结论

P0.2 参照资产已实际运行并取得所列本机证据；需求、独立方法与九检查点规格可复核。正式 P1 交付、远端迁移许可、物理资源/配额、DNS/TLS、用户批准和人类验收均未执行。旧六卡、早先参照与失败轮次保留其原支持范围；新 InputSet 不自动改变它们的结论。
