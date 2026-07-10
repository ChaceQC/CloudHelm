# infra

本目录保存 CloudHelm 本地开发、CI、远端演示部署和观测系统配置。

- `docker-compose.dev.yml`：当前本地开发 PostgreSQL，供 Platform API 迁移、测试和手工联调使用。
- M6 将评估并补充 Docker sandbox；当前 Sandbox Tool 仍是受控本地 `subprocess`。
- M7/M8 再加入远端演示 Compose、Prometheus、Grafana、Loki、Alertmanager 等真实部署与观测配置。
