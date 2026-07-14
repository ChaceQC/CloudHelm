# 本地与远程边界

> 来源：[设计书 6.2-6.3](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：明确本地开发区、控制平面、远程执行区和运维对象边界。
## 边界结论

- 本地隔离执行区只用于开发和测试，不作为核心运维对象。M6 采用 Task 独立
  workspace + 受控 `subprocess`；Docker sandbox 是后续隔离目标。
- 远端业务服务进程、容器、日志、指标、告警和发布版本才是核心运维对象。
- M7 的远端副作用只允许在 deployment approval 后沿 Tool Gateway ->
  Deployment Controller -> Remote Agent 执行；CI 仅由 release candidate
  approval 后的固定 `workflow_dispatch` 触发并产出不可变 OCI 制品。
- M7 远端范围固定为 Linux staging / demo + Docker Compose。SSH 只执行单独审批
  的固定只读诊断；production、Kubernetes 和交互式远程终端属于后续扩展。
- SRE Agent、Monitoring Collector、Remote Control Tool 的默认上下文必须绑定 `project_id + environment_id + deployment_id + service_id`。

## 设计书摘录

### 6.2 本地与远程边界

|区域|运行内容|说明|
|---|---|---|
|本地桌面端|Tauri 控制台、需求输入、方案审查、diff viewer、本地内嵌终端、任务面板|开发者主要操作入口，用于指导 Agents、完成两道审批、提出反馈和本地人工接管；M7 不提供交互式远程终端|
|本地 Agent 开发区|Task 独立 workspace、受控 subprocess、项目模板、测试执行、代码编辑；后续升级 Docker sandbox|Agents 根据开发者目标进行需求分析、项目生成、代码实现、测试和 PR 的默认位置|
|规格与设计区|Requirement Spec、ADR、OpenAPI、数据库 schema、验收标准|保存开发者指导和 Agent 设计产物，作为后续实现、测试和审查的依据|
|控制平面|FastAPI、Orchestrator、Tool Gateway、PostgreSQL、Redis + Celery worker|可以部署在本机，也可以部署在云端；负责两道审批、调度、权限、业务状态、幂等和审计|
|远程执行区|M7：Remote Agent、Docker Compose、业务项目进程与容器；增强版：K8s workload|M7 只运行 Linux staging / demo 业务项目，提供状态回传、受限日志和固定 diagnostics|
|观测区|Prometheus、Grafana、Loki、Langfuse、Alertmanager|重点采集远端业务项目的指标、日志、告警和发布状态，同时也采集平台自身运行状态|

### 6.2.1 M7 控制与执行边界

|主体|允许职责|禁止越界|
|---|---|---|
|Platform API / Orchestrator|创建两道审批、发布受控步骤、用固定 workflow id/ref/inputs 调用 `workflow_dispatch`、持久化状态与事件|在审批 HTTP 事务中直接部署，或接受任意 workflow、host、image、Compose 路径|
|CI Runner|检出精确 ref，运行测试、安全扫描和构建，发布 manifest、报告与不可变 OCI digest|SSH/SCP、远端 Compose、Remote Agent/部署 API 调用、服务重启|
|Deployment Controller|校验 ReleasePlan、target 与 digest，调用服务端登记的 Remote Agent endpoint|写 Platform 数据库、直接 SSH 部署、接受可变 tag|
|Remote Agent|按审批绑定请求执行 Compose policy、pull、digest 复核、up、状态和健康检查|任意 shell、任意 Compose/路径、交互终端、自动切换 SSH|
|SSH 诊断|目标显式启用且单独审批后执行固定只读 profile|部署、写入、自由 command、PTY 或转发|

### 6.3 运维对象边界

本系统中的“运维”特指 **对远端已部署业务项目的运维**，不是对本地开发
workspace/sandbox 的运维，也不是仅对平台自身的运维。

|对象|是否属于核心运维对象|说明|
|---|---|---|
|远端业务服务进程 / 容器|是|例如用户项目的 Web API、Worker、前端服务、定时任务|
|远端业务项目日志|是|例如 access log、application log、error log、container log|
|远端业务项目指标|是|例如 QPS、错误率、延迟、CPU、内存、容器重启次数|
|远端业务项目告警|是|例如接口错误率升高、服务不可用、部署健康检查失败|
|远端业务项目发布版本|是|例如完整 commit、OCI digest、release id、rollback candidate|
|本地 workspace / 后续 Docker sandbox|否|只作为开发和测试环境，不作为运维目标；M6 尚未启用 Docker 隔离|
|Agent 平台自身|次要|平台自身需要基础监控，但不是毕设重点运维对象|

因此 SRE Agent / Monitoring Collector / Remote Control Tool 的默认上下文都应该绑定到：

```text
project_id + environment_id + deployment_id + service_id
```

即：某个项目在某个远端环境中的某次部署及其服务实例。
