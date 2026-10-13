# SDK-03 工具与流式回调

## 状态

隔离 SDK/Gateway 子路径已实测；SDK-03 整卡仍为 **未验证**。本卡没有真实供应商工具回调、自动重试或断线恢复证据，也不代表产品 Runtime/Gateway 已集成。真实供应商模型流证据由主会话另行交叉引用；模型文本流不能替代带副作用工具的供应商回调证据。

真实供应商文本流的交叉证据见 [SDK-02 C3](SDK-02.md)：同一获准服务和 gpt-6-luna/max 的 1 次 stream=true 请求，HTTP 200、text/event-stream、response.completed=1、供应商 usage 和响应/请求 ID 已落盘。本卡的副作用工具流、重复/中断行为仍只由受控 SDK 输入覆盖，不扩大为供应商整卡通过。

负责人：Runtime/Gateway 负责人，主会话集成；实名待项目负责人指定。复核期限：P0.1-07 统一接缝出口前；具体日期待主会话排定。

## 版本与固定输入

本次执行于 2026-10-13，工作树基线 c7da7fb，分支 dev，探测源文件尚未提交。运行环境为 WSL Ubuntu 24.04.4 LTS、Linux 6.18.33.2-microsoft-standard-WSL2、Python 3.12.13、uv 0.11.29、PydanticAI 2.55.0、DBOS 3.2.0、psycopg 3.3.6、PostgreSQL 16.13。第二次运行开始时间为 2026-10-13T04:52:29Z。本结果仅覆盖此 WSL 拓扑。

固定探测范围为 probe_id=sdk03-04-fixed-input-v1、Gateway schema p0_protocol、稳定业务身份 sdk04/durable-submit-v1、输入 {"counter_delta":1,"fixture":"p0-sdk03-04"}。摘要为 725ae99c450eb389513643a09e998bdebb300036dd99b01288a53591b52828b5，稳定 Operation ID 为 op_b099e2a0ecf632f7f43bef8219f039ae。该固定范围只存隔离探测计数器和操作回执。

探测使用 PydanticAI 2.55.0 的 FunctionModel.stream_function、Agent.run(event_stream_handler=...)、ExternalToolset 和延期工具类型；没有真实供应商请求，provider_requests=0，没有读取密钥或产生模型费用。

## 实际观测

受控流返回了 function_tool_call 和 deferred_tool_requests 事件。Gateway 在每次查询、提交、结果回调及等待时重新检查当前策略：过期策略与已撤销工具各拒绝一次，均未创建 Operation。带副作用的提交回调第一次创建了一条 Operation；对同一 DeferredToolRequests 工具调用重复执行 Gateway 回调均返回原接受回执，created=false。随后用新 PydanticAI tool-call ID 重放同一业务请求，也未创建新 Operation，业务 Operation ID 与摘要保持不变。

同一工具批次包含查询、长提交和等待时，接缝适配器在派发前明确拒绝；Operation 数量没有变化。完成的 Gateway/DBOS 探测结果为 operations=1、effects=1、counter=1；拒绝门禁次数为 2。DBOS 检查点后的进程退出与重启证据见 [SDK-04](SDK-04.md)。

上述回调重放是由受控 FunctionModel 事件和固定调用输入触发；没有中断真实供应商的网络流，也没有观测供应商 SDK 自动重试、回连或重复工具事件。因此不能据此开放这些供应商工具路径。

## 复现与证据

在 WSL 仓库根目录重复运行：

    /home/cloudhelm/.local/bin/uv run python scripts/p0/probe_protocol.py

该命令已连续成功运行两次。两次均得到一条 Operation、一条副作用记录、计数器值 1；每次运行先清理自己的固定 probe scope。脚本不触碰其他 probe_id 的业务数据；DBOS 工作流只通过 DBOS 公共 API 创建、恢复和删除。

源文件 SHA-256：

- gateway_probe.py: e58c5c6c8a924ca11aa603dcffe1d8d2ac1c1491d67ca8ae0697a4fce2dbdf0e
- probe_protocol.py: 4ae3be4230943196adc78f8082d7326ebbf14d78208b0f912a6add6b143e75e9

## 复用结论与阻塞入口

可直接复用的窄范围接口：PydanticAI 的流式模型事件、DeferredToolRequests/Results 与消息协议；每次副作用前重查门禁、稳定 Operation 身份及请求摘要的规则由 Gateway 薄适配实现。

尚未证明产品 modules/agent-runtime/、modules/tool-gateway/、integrations/ 的真实调用均经过此边界，也未证明供应商流中断、内部重试、回连和回调延迟行为。未补齐当前门禁和稳定身份去重证据前，这些工具及供应商流式入口应保持阻塞。P0.1-07 复核时由 Runtime/Gateway 负责人核对产品接线，并单独取得供应商路径证据。
