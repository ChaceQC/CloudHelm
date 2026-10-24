# T-SIM-07：Task 局部读取复用与项目鉴权保留决定

本说明记录当前实现边界；实际验证输入、结果及未执行范围见 [T-SIM-07 进度](../../PROJECT_PROGRESS.md#2026-10-25源码简化专项-t-sim-07)。领域规则继续以 [D01](../design/01-domain-collaboration.md)、[D02](../design/02-execution-recovery.md) 和 [D05](../design/05-security-sync-operations.md) 为准。

## 07a：同一锁定事务内复用

`TaskApplication.query` 在同一 `UnitOfWork` 内调用 `lock_task_access`：按既有顺序锁定当前身份、会话、项目策略和 Task 行，并取得本次 `resource.read` 决定。`task_view` 随后读取声明和控制头，其间不写入 Task、声明或完成报告。

查询现在将这三个已读值传给事实投影函数：

|入口|复用内容|仍然实时读取的内容|
|---|---|---|
|`project_task_control_facts`|当前锁定的 Task 行、声明、控制头|输入、引用、验收、Operation、人测、等待和 Run 历史|
|`project_cancellation_facts`|当前锁定的 Task 行、控制头|Operation 物理收尾和 Run 历史；不增加完成输入要求|

这些入口仅供持有同一 Connection、Task 行锁及相同版本的内部调用方使用，传入值之间不能发生相关写入。复用变量只存在于本次查询的栈上；不建立 UoW 全局缓存、请求间缓存或持久工作流步骤缓存。

`load_task_control_facts` 和 `load_cancellation_facts` 保留原签名，命令调用仍自行重新锁行、读取所需值，再交给相同的投影实现。没有修改命令去重、当前版本检查、完成/取消转换、DBOS 步骤或持久返回值。

原查询顺序保留：读取声明及固定控制头 → 有界工作项及其已接受输入 → 当前控制 blocker → 可见性鉴权。`completed/cancelled` 不重新投影实时完成依据；完成报告仍以原报告为准。取消继续单独判定物理收尾，未知写入、重复 Operation、超量投影和跨对象可见性沿原分类处理。授权不参与上述复用，每次查询仍走完整当前门禁，Operation blocker 仍逐项检查 `operation.query`。

## 07b：保留两次项目鉴权

核对对象为 `ProjectApplication._execute`、`authorize_current`、当前 `policy.py`、`audit.py` 以及 `actor_for_command` 等审计消费者。

|当前主体/策略|`project.manage`|`resource.read`|
|---|---|---|
|有效人类项目所有者|隐式所有者动作允许|隐式所有者动作允许|
|非所有者 developer/reviewer|角色动作上限不含管理动作|仅在实际角色绑定授予时允许|
|Agent|委托动作上限不含管理动作|仍需有效角色、委托及范围|
|会话撤销、用户失效、策略版本不适用或记录范围不符|按当前门禁拒绝|按当前门禁拒绝|

当前管理命令的成功集合与“管理且可读”的交集相同，但这不足以合并两个授权决定。每个 `authorize_current` 都写入独立的 action、decision ID、当前权限/策略/资源修订及目标审计；管理命令保存并引用 `project.manage` 决定，返回的项目投影另有 `resource.read` 决定。`actor_for_command` 核对命令与原审计的 action/范围绑定，不能将读决定替换为管理决定。

因此按 07b 的条件出口保留两次完整鉴权及各自审计，也保留幂等重投前的当前权限核对。未为减少查询建立新的多 action 授权上下文或修改动作蕴含规则；在没有足够净收益证据时，收敛这条路径会增加策略、时效及审计契约的维护成本。

## 兼容与复核

本次不改变 HTTP 字段/状态码、角色动作集合、授权 envelope、数据库 schema、工作流步骤及固定参照资产；软件 `0.5.0`、工作流应用 `cloudhelm-hub/0.5.0` 和迁移 `0006_p1_3_resource_lifecycle` 保持原基线。设计及协议没有新规则，不递增设计版本，不追认旧候选证据。

必要复核使用同一真实 PostgreSQL 事务和锁定 Task 上的新旧查询比较，观测 SELECT 次数及完整投影/错误分类；项目命令检查当前允许集合、双 action 审计、原命令引用、策略变化与撤权后的重投。只覆盖这些局部边界，不替代 worker、完整工程链、Desktop、独立机器或人类验收。日常检查入口仍见 [checks.md](../development/checks.md)，没有新增常驻测试套件。
