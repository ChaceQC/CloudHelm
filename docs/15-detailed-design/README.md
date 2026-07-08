# 细化设计文档

本目录用于在原有分层文档基础上补充可实现级细节，重点回答“每个部分如何落地、模块之间如何交互、接口和数据如何约束、测试如何验收”。

## 文件

- [00-mvp-scope-and-cutline.md](00-mvp-scope-and-cutline.md)
- [01-module-contracts.md](01-module-contracts.md)
- [02-agent-tool-contract.md](02-agent-tool-contract.md)
- [03-api-detail.md](03-api-detail.md)
- [04-data-detail.md](04-data-detail.md)
- [05-workflow-state-events.md](05-workflow-state-events.md)
- [06-deployment-observability-detail.md](06-deployment-observability-detail.md)
- [07-testing-acceptance-matrix.md](07-testing-acceptance-matrix.md)

## 使用顺序

1. 先读 [00-mvp-scope-and-cutline.md](00-mvp-scope-and-cutline.md)，确定毕设 MVP 不做什么。
2. 再读 [01-module-contracts.md](01-module-contracts.md)，确定模块边界和输入输出。
3. 开发 Agent / Tool 时读 [02-agent-tool-contract.md](02-agent-tool-contract.md)。
4. 开发后端 API 时读 [03-api-detail.md](03-api-detail.md) 与 [04-data-detail.md](04-data-detail.md)。
5. 实现流程编排时读 [05-workflow-state-events.md](05-workflow-state-events.md)。
6. 部署、观测、答辩环境读 [06-deployment-observability-detail.md](06-deployment-observability-detail.md)。
7. 收尾验收读 [07-testing-acceptance-matrix.md](07-testing-acceptance-matrix.md)。

