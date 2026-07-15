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
- 正式产品的控制平面固定部署为常在线 Linux Ops Hub；“本机或云端任选”的表述
  只适用于开发 profile，不再作为产品拓扑。
- Desktop 安装器不包含 Docker/PostgreSQL/Redis；本机 SQLite 仅保存非权威缓存、
  草稿、server profile 和事件 sequence。
- Agent 生成的项目必须使用独立数据、依赖和运行入口；CloudHelm 兼容性是可删除
  的 manifest/观测协议适配，不是运行时依赖。

## 设计书摘录

### 6.2 本地与远程边界

|区域|运行内容|说明|
|---|---|---|
|本地桌面端|Tauri 控制台、SQLite 非权威缓存、OS credential store、需求/审批/状态 UI|Windows/Linux 可安装客户端；退出不停止远端运维；不直连数据库、Redis 或 Remote Agent|
|本地 Agent 开发区|Local Runtime sidecar、Task 独立 workspace、受控 subprocess、项目模板、测试执行、代码编辑；后续升级 Docker sandbox|依赖本机 workspace 的步骤可在 Desktop/主机离线时暂停|
|规格与设计区|Requirement Spec、ADR、OpenAPI、数据库 schema、验收标准|保存开发者指导和 Agent 设计产物，作为后续实现、测试和审查的依据|
|常在线 Ops Hub|FastAPI、Orchestrator、Agent Runtime、Tool Gateway、Workflow Engine、PostgreSQL、Redis|部署在持续运行的 Linux 主机；负责两道审批、调度、权限、权威状态、幂等和审计|
|远程执行区|M7：Remote Agent、独立 Docker Compose 业务项目；增强版：K8s workload|Remote Agent 与项目生命周期分离；项目可脱离 CloudHelm 独立运行|
|观测区|Prometheus、Grafana、Loki、Langfuse、Alertmanager|重点采集远端业务项目的指标、日志、告警和发布状态，同时也采集平台自身运行状态|

### 6.2.1 M7 控制与执行边界

|主体|允许职责|禁止越界|
|---|---|---|
|Platform API / Orchestrator|创建两道审批、发布受控步骤、用固定 workflow id/ref/inputs 调用 `workflow_dispatch`、持久化状态与事件|在审批 HTTP 事务中直接部署，或接受任意 workflow、host、image、Compose 路径|
|CI Runner|检出精确 ref，运行测试、安全扫描和构建，发布 manifest、报告与不可变 OCI digest|SSH/SCP、远端 Compose、Remote Agent/部署 API 调用、服务重启|
|Deployment Controller|校验 ReleasePlan、target 与 digest，调用服务端登记的 Remote Agent endpoint|写 Platform 数据库、直接 SSH 部署、接受可变 tag|
|Remote Agent|按审批绑定请求执行 Compose policy、pull、digest 复核、up、状态和健康检查|任意 shell、任意 Compose/路径、交互终端、自动切换 SSH|
|SSH 诊断|目标显式启用且单独审批后执行固定只读 profile|部署、写入、自由 command、PTY 或转发|

### 6.2.2 App 离线边界

- 用户命令或审批在服务端事务提交后，由 Workflow Engine 继续推进。
- Desktop `run-next` 只作为调试、答辩逐步展示或故障恢复入口。
- Desktop 离线时不需要新人工决策的工作继续；高风险步骤持久等待审批。
- 重连通过 project snapshot、单调 event sequence 和 SSE high-watermark 补齐。
- 高风险离线 intent 不自动 replay，必须重新认证、检查版本并由用户确认。

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
|Ops Hub 平台自身|基础必需|虽不是业务运维展示重点，但必须具备健康、自动重启、worker heartbeat、队列/磁盘/备份检查|

因此 SRE Agent / Monitoring Collector / Remote Control Tool 的默认上下文都应该绑定到：

```text
project_id + environment_id + deployment_id + service_id
```

即：某个项目在某个远端环境中的某次部署及其服务实例。
