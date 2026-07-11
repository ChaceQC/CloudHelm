# informations 资料归档说明

本目录用于保存 CloudHelm 实现前检索到的官方文档、开源项目资料、技术选型依据和命令来源摘要。

## 目录层级

建议按阶段和主题分层：

```text
informations/
├── m1-foundation/
│   └── official-references.md
├── m4-agent-context/
│   └── codex-responses-context.md
├── m5-tool-gateway/
│   └── official-references.md
└── m7-deployment/
    └── remote-deploy-references.md
```

## 每份资料建议包含

- 检索日期。
- 资料名称和官方链接。
- 适用阶段或子任务。
- 采用的工程实践、命令或接口形态。
- 不采用或延后采用的能力及原因。
- 与当前设计文档或 `PROJECT_PLAN.md` 的对应关系。

## 禁止保存

- 真实密钥、Token、Cookie、账号密码、证书私钥。
- 真实服务器管理入口、数据库连接串或敏感运维信息。
- 许可证不明的大段代码。
- 第三方文档、博客或书籍的全文复制。
