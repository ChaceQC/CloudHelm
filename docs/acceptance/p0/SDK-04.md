# SDK-04 历史、批次与续接

## 状态

隔离协议/DBOS 子路径已实测；SDK-04 整卡仍为 **未验证**。证据不表示业务 Runtime、UnitOfWork、WaitCondition 或产品工作流已集成。

负责人：Runtime/Workflow 负责人，主会话集成；实名待项目负责人指定。复核期限：P0.1-07 统一接缝出口前；具体日期待主会话排定。

## 版本与固定输入

执行环境、探测固定输入、代码基线和 SHA-256 见 [SDK-03](SDK-03.md)。本卡在相同隔离 PostgreSQL 上创建 Gateway 业务 schema p0_protocol；DBOS 使用独立 system schema p0_sdk04_dbos，只经 DBOS 3.2.0 公共 API 操作，不查询或写入 DBOS 内部表。没有模型供应商请求。

本卡与 SDK-01 的同库事务、SDK-05 的允许内容/保留限制、SDK-06 的同身份重启完成本次集成复核，结果见 [接缝汇总](seam-summary.md)。这些有限切片不能替代仍缺失的产品等待/当前资格接线；复核期限为 P0.3 统一出口前，源码、依赖、输入或环境变化时立即重建适用证据。

探测历史由 PydanticAI 2.55.0 的 ModelMessagesTypeAdapter 校验及序列化；延期批次用真实 DeferredToolRequests.build_results()、remaining() 和 DeferredToolResults.to_tool_call_results() 操作。固定 submit 调用 ID 为 call-submit-original，等待调用 ID 为 call-await-original；最终结果 ID 为 sdk04/result-v1。

## 实际观测

由 query_counter、submit_operation、await_operation 组成的混合批次在派发前被拒绝，未产生 Operation。两个查询调用中只提供一个结果时，SDK 仍报告 call-query-2 未完成，续接次数保持为 0；提供完整结果后才执行受控续接。

Submit 回执绑定 call-submit-original，其内容为稳定 Operation ID、请求摘要及 accepted 状态。Operation 完成后，最终结果只绑定 call-await-original；校验后的消息历史中原 submit 接受回执仍保持原值。

DBOS 探测在 Gateway 操作步骤返回并形成检查点后注入 os._exit(75)。新进程以 DBOS 查询和恢复接口接回原工作流，原 workflow ID 保持 3ce794e0-95fe-4c3d-bfa5-842a67458c1f，原 AgentRun ID 保持 agent-run-sdk04-submit。恢复后的新等待续接使用另一个 workflow ID c1d2e739-ec9e-497c-a9b3-7711cddcfc09 和 AgentRun ID agent-run-sdk04-after-wait。结果在新续接开始前已到达；续接读取到完整结果。相同结果回调再次提交后，Gateway 返回既有结果且 duplicate_result_effect_applied=false。

本次输出还记录：DBOS 重启区间内 Gateway 检查增量为 6（包含预期的提交、完成、等待、重复结果与证据查询检查），隔离账本为 operations=1、effects=1、counter=1。第二次成功运行使用新的 DBOS workflow ID，但得到相同计数和协议结论。

## 复现与证据

在 WSL 仓库根目录重复运行：

    /home/cloudhelm/.local/bin/uv run python scripts/p0/probe_protocol.py

两次运行均通过脚本内固定断言。每次成功运行后，探测使用 DBOS 公共 delete_workflows API 定向删除本次两条已完成工作流；隔离 DBOS schema 保留供后续重复运行。未执行全量测试、供应商请求、产品数据库事务或 Desktop/远程部署验收。

第二次运行输入摘要为 725ae99c450eb389513643a09e998bdebb300036dd99b01288a53591b52828b5；第二次 workflow ID 分别为原流程 3ce794e0-95fe-4c3d-bfa5-842a67458c1f 和等待后新流程 c1d2e739-ec9e-497c-a9b3-7711cddcfc09。这些 ID 仅用于该次隔离运行，不是产品身份或版本。

## 复用结论与阻塞入口

可直接复用的窄范围接口：候选版本的 PydanticAI 合法 ModelMessages 编解码、DeferredToolRequests/Results 批次解析；DBOS 公共 API 支持本次所用的步骤检查点、原 workflow 查询恢复及新 workflow 启动。

本探测没有验证业务命令事务、生产 WorkflowBinding、持久 WaitCondition/Outbox、Task 当前资格与取消门禁、未知结果处理或代码版本不兼容时的恢复规则。产品 modules/agent-runtime/、modules/workflow/ 与 packages/contracts/ 的历史导入和新 Run 续接在这些边界取得实证前仍应阻塞。P0.1-07 由 Runtime/Workflow 负责人把本探测与 SDK-01、SDK-05/06 证据交叉复核。
