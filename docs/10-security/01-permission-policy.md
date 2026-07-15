# 权限策略示例

> 来源：[设计书 14.2](../../云舵 CloudHelm 毕设设计书.md)  
> 目的：按 Agent 角色描述 allow、deny 和 require_approval。
## 策略实现

MVP 可先用自研 Policy Engine；规则稳定后可迁移到 OPA/Rego。

## M5/M6 落地状态

- `modules/tool-gateway/policies.py` 已实现本地 Tool Policy：路径边界、敏感文件拒绝、命令 denylist、环境变量白名单、超时上限和 L3/L4 审批判定。
- Requirement / Architect / Planner 不执行本地副作用；Scaffold、Coder、
  Tester、Reviewer、Security 由 Platform API 执行稳定工具循环，所有调用仍
  经过角色 allowlist、Tool Gateway schema 与 Policy。
- Coder 只允许受控 workspace 内显式路径读写与 diff；Tester 只允许 recipe
  固定 pytest；Security 只允许配置的本地扫描器；Git 收尾只提交已审查的显式
  changed files，不允许 push。
- Release Agent 和远端部署权限尚未开放，
  `approval.request_remote_action` 仍只用于验证 L3 审批链路。

## M9 用户授权策略目标（规划）

用户策略输入：

```text
authenticated_user_id
device_id
session_id
permission
scope_type / scope_id
resource_type / resource_id / resource_version
resource provenance
requested action
```

决策顺序：

1. 验证 user/device/session lifecycle 与 token version。
2. 解析 active、未过期 role binding 和 effective permissions。
3. 按 `(role_key, binding_scope_type)` 解析 permission，并校验
   system/project/environment scope；Environment 响应中的父 Project/关联
   Task/CI 只允许最小嵌入摘要。
4. 校验资源状态、版本和服务端 provenance。
5. 应用 design/release/deployment/diagnostics 职责分离；设计审批重验当前
   version/content hash 和最后修改者/AgentRun 发起者。
6. 返回 allow/deny、稳定 reason code 和安全审计；Desktop 只消费结果。

当前 MVP 不提供用户可配置 negative grant；文档中的 deny 表示 scope、resource
policy 或 domain guard 优先于 role allow。API 与 Tool Gateway 都不得只按 role
名称或前端按钮状态放行。

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
