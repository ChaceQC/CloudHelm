# 权限策略示例

> 来源：[设计书 14.2](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：按 Agent 角色描述 allow、deny 和 require_approval。
## 策略实现

MVP 可先用自研 Policy Engine；规则稳定后可迁移到 OPA/Rego。

## M5 落地状态

- `modules/tool-gateway/policies.py` 已实现本地 Tool Policy：路径边界、敏感文件拒绝、命令 denylist、环境变量白名单、超时上限和 L3/L4 审批判定。
- Requirement / Architect / Planner 仍不直接调用工具；后续 Agent 接入时必须通过 Platform API 的 Tool Gateway service。
- Coder Agent、Release Agent 和远端部署权限尚未开放，`approval.request_remote_action` 只用于验证 L3 审批链路。

## 设计书摘录

### 14.2 权限策略示例

```text
Requirement Agent:
  allow:
    - requirement.parse
    - requirement.update_spec
    - repo.read_file
  deny:
    - repo.write_file
    - git.commit
    - deploy.*

Planner Agent:
  allow:
    - spec.read
    - repo.read_file
    - repo.search_code
    - ci.get_status
    - logs.search
  deny:
    - repo.write_file
    - git.commit
    - deploy.*

Architect Agent:
  allow:
    - spec.read
    - design.generate_api_design
    - design.generate_db_design
    - design.update_technical_plan
    - repo.read_file
  require_approval:
    - design.approve_high_risk
    - database.generate_migration
  deny:
    - deploy.*

Coder Agent:
  allow:
    - spec.read
    - repo.read_file
    - repo.write_file
    - sandbox.exec
    - git.diff
  require_approval:
    - git.commit
    - git.create_pr

Release Agent:
  allow:
    - ci.get_status
    - deploy.plan
    - deploy.render_manifest
    - deploy.health_check
  require_approval:
    - deploy.staging
    - deploy.rollback
    - deploy.production
```
