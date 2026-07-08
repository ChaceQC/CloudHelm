# 远端业务项目运维数据采集链路

> 来源：[设计书 5.4](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：定义日志、指标、探活、异常和事件转换路径。
## 统一事件

远端日志、指标、可用性探测、异常追踪和部署状态最终都应转换为平台事件，例如 `ProjectMetricUpdated`、`ProjectAlertFired`、`ProjectIncidentCreated`。

## 设计书摘录

### 5.4 远端业务项目运维数据采集链路

```text
远端业务项目
  ├── 应用日志 stdout / file log
  │     -> Grafana Alloy / Fluent Bit / Vector
  │     -> Loki
  │
  ├── 应用指标 /metrics
  │     -> Prometheus scrape
  │     -> Grafana dashboard / Alertmanager
  │
  ├── 主机指标
  │     -> node_exporter
  │     -> Prometheus
  │
  ├── 容器指标
  │     -> cAdvisor
  │     -> Prometheus
  │
  ├── 可用性探测
  │     -> blackbox_exporter / Uptime Kuma
  │     -> Alertmanager
  │
  └── 应用异常
        -> Sentry
        -> Incident Event
```

采集到的数据最终统一转换成平台事件：

```text
ProjectMetricUpdated
ProjectLogReceived
ProjectAlertFired
ProjectDeploymentUnhealthy
ProjectServiceRestarted
ProjectRollbackRequested
ProjectIncidentCreated
RequirementSpecCreated
TechnicalDesignProposed
DesignApprovalRequested
AcceptanceCriteriaVerified
```

---
