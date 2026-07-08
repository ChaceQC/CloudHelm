# 本地与远程边界

> 来源：[设计书 6.2-6.3](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：明确本地开发区、控制平面、远程执行区和运维对象边界。
## 边界结论

- 本地 Docker sandbox 只用于开发和测试，不作为核心运维对象。
- 远端业务服务进程、容器、日志、指标、告警和发布版本才是核心运维对象。
- SRE Agent、Monitoring Collector、Remote Control Tool 的默认上下文必须绑定 `project_id + environment_id + deployment_id + service_id`。

## 设计书摘录

### 6.2 本地与远程边界

|区域|运行内容|说明|
|---|---|---|
|本地桌面端|Tauri 控制台、需求输入、方案审查、diff viewer、内嵌终端、任务面板|开发者主要操作入口，用于指导 Agents、审批方案、提出反馈和人工接管|
|本地 Agent 开发区|Git worktree、Docker sandbox、项目模板、测试执行、代码编辑|Agents 根据开发者目标进行需求分析、项目生成、代码实现、测试和 PR 的默认位置|
|规格与设计区|Requirement Spec、ADR、OpenAPI、数据库 schema、验收标准|保存开发者指导和 Agent 设计产物，作为后续实现、测试和审查的依据|
|控制平面|FastAPI、Orchestrator、Tool Gateway、数据库、队列|可以部署在本机，也可以部署在云端；负责调度、权限、审计|
|远程执行区|Remote Agent、部署脚本、业务项目进程、业务容器、K8s workload|运行被部署的业务项目，提供项目状态回传、日志流和远程控制|
|观测区|Prometheus、Grafana、Loki、Langfuse、Alertmanager|重点采集远端业务项目的指标、日志、告警和发布状态，同时也采集平台自身运行状态|

### 6.3 运维对象边界

本系统中的“运维”特指 **对远端已部署业务项目的运维**，不是对本地开发 sandbox 的运维，也不是仅对平台自身的运维。

|对象|是否属于核心运维对象|说明|
|---|---|---|
|远端业务服务进程 / 容器|是|例如用户项目的 Web API、Worker、前端服务、定时任务|
|远端业务项目日志|是|例如 access log、application log、error log、container log|
|远端业务项目指标|是|例如 QPS、错误率、延迟、CPU、内存、容器重启次数|
|远端业务项目告警|是|例如接口错误率升高、服务不可用、部署健康检查失败|
|远端业务项目发布版本|是|例如当前 commit、镜像 tag、release id、回滚目标|
|本地 Docker sandbox|否|只作为开发和测试环境，不作为运维目标|
|Agent 平台自身|次要|平台自身需要基础监控，但不是毕设重点运维对象|

因此 SRE Agent / Monitoring Collector / Remote Control Tool 的默认上下文都应该绑定到：

```text
project_id + environment_id + deployment_id + service_id
```

即：某个项目在某个远端环境中的某次部署及其服务实例。
