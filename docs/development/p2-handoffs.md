# Workspace 人工接管与交还

源码 `0.15.0` 提供 P2.3-01 的受控写入权交接。新隔离库迁移 head 为 `0015_p2_handoffs`，线性承接 `0014_p2_verification`；DBOS 应用保持 `cloudhelm-hub/0.7.0`，复用已有 Workspace 工作流及队列。旧安装不由 initialize 自动升级，0011 受限维护副本保持原限制。

## 使用接口

`POST /api/workspaces/{workspace_id}/handoffs` 要求当前人类设备会话、`workspace.write` 和 `Idempotency-Key`。请求携带当前 `expected_version`、`expected_control_revision`、`expected_input_validity_revision`、`input_set_ref`、`expected_workspace_revision`、`expected_write_generation`、实际 `expected_manifest_digest` 及 `reason`。

- `action=takeover` 时不传 `handoff_id`。返回 202 与稳定交接身份，状态为 `handoff_pending`。如果旧 Workspace 或开发环境操作还缺少终态回执，请求拒绝为 `workspace_operation_pending`，先查询原操作并完成核对，不取消或重放未知写入。
- 使用 `GET /api/workspaces/{workspace_id}/handoffs/{handoff_id}` 查询原交接。执行器在既有根目录写锁内盘点实际写入者并固定基线，Hub 验证原物理回执后才登记 `human_owned`，推进 Workspace 修订及写入代次。
- `human_owned` 后仅该人类可经已有 `POST /api/workspaces/{workspace_id}/files` 受控编辑。仍须提交准确文件/manifest、版本和代次；冲突拒绝覆盖，保留实际用户文件。记录了人类来源的编辑命令由 worker 执行；Runtime 借用旧人类命令身份不获得人工编辑资格。
- 显式交还使用同一个 POST，传 `action=return`、原 `handoff_id` 和编辑后的准确版本/manifest。状态先变为 `return_pending`，禁止新的人工写入；执行器固定另一不可变快照，再核对原回执并登记 `agent_owned`。接管与交还使用不同幂等键，重投使用各自原键和原请求。

关闭页面、断线、超时及 worker 恢复均不自动交还。查询可以在原身份下完成已存在 stage 的封存，但不会重新采集当前开发文件。物理采集已开始而结果未知时保留 pending；恢复查询同一操作，不能新建交接身份绕过。

## 差异与继续推进

查询记录保存基线与交还快照的准确 commit、manifest、原操作及修订/代次，`changes` 给出每个新增、删除、修改文件的前后元数据与内容摘要，无静默截断。两份内容均留在原 CandidateStore，后续开发不改变这轮差异。源文件内容不复制进工作流检查点或模型上下文；事件和检查点只传交接身份、记录摘要或差异数量。

交还同事务推进 Workspace 修订/代次、Task 输入有效性修订，将输入和本 Task 正式验收消费标为 `needs_review`，对应工作项回到 ready。历史报告与快照字节不被改写。普通推进须经既有输入复核后重新建立当前 Run，旧 Run 无权把晚到输出作为当前推进结果。后续有界 Run 的提示及 `task.read` 包含原交接、前后快照和差异查询引用；这些是修改事实，不是正式验收通过或 Task 完成结论。

交接未交还前参与 Task 工程阻断投影。只冻结该 Workspace 的冲突写入，其他工作区沿既有独立门禁推进；清理开发进程的 suspend/dispose 保留原入口。

## 支持范围

本包支持既有服务唯一写入者，以及经实际盘点确认的只读 Runner；人类通过服务端文件接口编辑，不开放宿主编辑器、任意可写容器或 Desktop 本地 Git。已有开发环境的读取登记必须与当前 Workspace binding 一致；版本变化后仍挂载旧 binding 的容器须先按原身份停止并核对，不能忽略未知写入者继续交权。

本包新增一张必要交接表，未新增服务、调度器、插件层、模型工具或合并队列。完整原生交互、P2.3-02 项目合并、预览/人测及人工产品验收按后续工作包安排。实际开发验证与固定输入见 [P2.3-01 记录](../acceptance/p2/p2-3-01.md)。
