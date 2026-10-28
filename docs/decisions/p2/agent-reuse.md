# P2.1-A02 成熟方案复用决定

> 修订：r1；日期：2026-10-28（Asia/Shanghai）。
> 本文件只记录决定与边界，不代表已实现或已验收。
> CloudHelm 核对基线：`dev / 1410787`，软件 `0.16.0`。

## 1. 决定

**保留现有 PydanticAI 协议 Runtime、Gateway 和 DBOS 持久执行；OpenHands SDK 本轮仅作工程结构参考，不作为产品依赖或第二套循环/历史引擎。**

固定 SDK 源码存在自定义工具、请求重试和会话恢复机制，但这些机制不能直接等同于 CloudHelm 的逐次业务准入、原 Operation 核对和事务等待。尤其是未配对观察的动作会进入重新执行路径；将它接入现有 Gateway 还需要显式身份映射和未知结果核对。当前领域能力已经存在，为整体接入维护这些跨引擎适配没有足够收益。本决定不声称 OpenHands 无法改造；本轮停止继续扩展集成实验，不维护框架分叉。

该选择沿用 [D01](../../design/01-domain-collaboration.md) 的 Runtime/历史/等待所有权及 [D02](../../design/02-execution-recovery.md) 的 DBOS 唯一持久执行，不改变权威设计、模型配置、软件版本、数据库或工作流应用版本。

## 2. 固定来源与许可

|对象|固定输入与来源|复用方式|
|---|---|---|
|OpenHands SDK|[`v1.58.2`](https://github.com/OpenHands/software-agent-sdk/tree/d2ee0cdea60825608c2f8906eb54e1d4d264fb42)，commit `d2ee0cdea60825608c2f8906eb54e1d4d264fb42`；[PyPI 1.58.2](https://pypi.org/project/openhands-sdk/1.58.2/)|仅参考工程循环、动作/观察、上下文和工作区分层；不复制源码、不安装到产品环境|
|候选许可|固定提交的 [LICENSE](https://github.com/OpenHands/software-agent-sdk/blob/d2ee0cdea60825608c2f8906eb54e1d4d264fb42/LICENSE) 为 MIT，版权行是 `Copyright (c) 2026 OpenHands contributors`|未来复制实质代码须保留版权及许可文本；本轮无代码再分发。PyPI 未声明许可字段，不从空字段推定许可|
|现有协议与持久执行|根目录 [pyproject.toml](../../../pyproject.toml) / [uv.lock](../../../uv.lock)：`pydantic-ai-slim[openai,dbos]==2.55.0`、`dbos==3.2.0`；既有 [组件基线](../p0/component-baseline.md) 均记录 MIT|继续直接使用现有锁定依赖；不新增安装或重做历史兼容结论|
|现有领域与执行工具|Gateway、Workspace、Runner、候选/构建及正式验证的当前应用入口|A03～A09 按 [实施映射](../../implementation/p2-agent.md) 增加必要薄适配，复用领域命令，不重写执行器|

版本身份通过 `git ls-remote`、固定 tag 的独立只读检出和 PyPI 固定版本元数据交叉核对。PyPI 源码包 `openhands_sdk-1.58.2.tar.gz` 的发布摘要为 `sha256:43227ed68c4d5684aac6e56b3b83ea56018ce9441b9b4b0433a2f06077bc986b`；本轮阅读 Git 提交，没有下载/运行该源码包，不把其摘要当作两份内容相同的证明。

固定提交的 [SDK 清单](https://github.com/OpenHands/software-agent-sdk/blob/d2ee0cdea60825608c2f8906eb54e1d4d264fb42/openhands-sdk/pyproject.toml#L2-L32) 要求 Python `>=3.12`，与本仓库 `3.12.*` 无直接版本门槛冲突；同时引入 LiteLLM、FastMCP、lmnr 等当前未采用的运行依赖。未安装或解析整组候选依赖，不能声明整体依赖兼容。

计划中 Claude Agent SDK、OpenCode、Codex App Server、Aider、Deep Agents 与 HolmesGPT 继续保留原有的设计参考/P5 候选范围，本轮未对它们实施引擎接缝评估、复制代码或采用依赖。它们的调查链接不作为版本级兼容证据；若后续确需采用组件，届时固定对应版本/commit 和许可。本次没有同时评估或引入多个候选引擎，Pydantic AI Coder 仍排除。

## 3. 三项决定性接缝

以下均为固定真实源码的静态调用核对，区别于 SDK 文档/示例阅读；**未执行 SDK 集成运行，三项运行兼容性均未验证**。静态证据足以决定本轮不整体采用，无需为该决定增加模型、故障注入或完整引擎测试。

|接缝|固定源码证据与现有边界|裁决|
|---|---|---|
|每次实际模型出站、请求身份及费用|[llm.py](https://github.com/OpenHands/software-agent-sdk/blob/d2ee0cdea60825608c2f8906eb54e1d4d264fb42/openhands-sdk/openhands/sdk/llm/llm.py#L1816-L1837) 将校验和传输放在重试内部；Chat 同步/异步分别经 `_transport_call/_atransport_call`（2521/2547 行），Responses 同步/异步直接调用 LiteLLM（2086/2259 行）。[retry_mixin.py](https://github.com/OpenHands/software-agent-sdk/blob/d2ee0cdea60825608c2f8906eb54e1d4d264fb42/openhands-sdk/openhands/sdk/llm/utils/retry_mixin.py#L29-L46) 的 listener 在重试睡眠前调用，不覆盖首次出站；[摘要器](https://github.com/OpenHands/software-agent-sdk/blob/d2ee0cdea60825608c2f8906eb54e1d4d264fb42/openhands-sdk/openhands/sdk/context/condenser/llm_summarizing_condenser.py#L54-L64) 使用独立 LLM，262 行另发摘要请求。现有 [sdk.py](../../../modules/agent_runtime/sdk.py) 在 HTTP transport 边界预登记每次请求，并交 `RuntimeBilling` 结算|有可适配调用点，但只包外层循环、重试 listener 或 Chat transport 不能证明覆盖所有真实出站。需要逐传输路径和摘要器统一准入、稳定请求映射及费用落账；本轮未验证，不接管现有传输|
|Gateway/Runner 工具及长操作|[ToolExecutor](https://github.com/OpenHands/software-agent-sdk/blob/d2ee0cdea60825608c2f8906eb54e1d4d264fb42/openhands-sdk/openhands/sdk/tool/tool.py#L283-L289) 支持自定义执行器；[动作执行](https://github.com/OpenHands/software-agent-sdk/blob/d2ee0cdea60825608c2f8906eb54e1d4d264fb42/openhands-sdk/openhands/sdk/agent/agent.py#L1466-L1557) 区分 ActionEvent 和 ObservationEvent，但 executor 调用没有直接传入整个 ActionEvent 的 `tool_call_id`。现有 [Gateway](../../../modules/tool_gateway/gateway.py) 在每次调用准入后向路由传原 tool-call ID，长操作由 [operations.py](../../../modules/agent_runtime/operations.py) 交给领域事务|可以定义受限工具并委托现有能力，但身份、权限与可靠等待需另作业务适配；SDK 自定义工具接口本身不授予文件/终端权限。未验证 accepted 与最终结果等待的完整组合，不开放内置宿主工具|
|中断、未知结果及原身份恢复|[agent.py](https://github.com/OpenHands/software-agent-sdk/blob/d2ee0cdea60825608c2f8906eb54e1d4d264fb42/openhands-sdk/openhands/sdk/agent/agent.py#L710-L718) 会对未匹配 ObservationEvent 的动作再次 `_execute_actions`；同文件 1495～1557 行先调用 executor 再构造观察。执行成功但观察尚未持久化的间隙，不能从缺少观察推断未执行。CloudHelm 的 [workflows.py](../../../modules/agent_runtime/workflows.py) 只持久传递 `run_id`；业务请求、Operation、历史和等待各沿原身份核对|确认存在需要适配的恢复语义差异；不能直接启用 SDK 的恢复循环。没有集成 DBOS 或执行崩溃实验，不声明组合恢复通过；保留现有 Runtime 的核对及续接路径|

SDK 的 telemetry 在每次外层尝试记录请求上下文/响应与指标，但不等同于 CloudHelm 的持久准入及精确费用账本，见固定 [telemetry.py 190～235 行](https://github.com/OpenHands/software-agent-sdk/blob/d2ee0cdea60825608c2f8906eb54e1d4d264fb42/openhands-sdk/openhands/sdk/llm/utils/telemetry.py#L190-L235)。这并非认定 SDK 没有扩展能力，而是本轮没有获得可以直接复用现有门禁和恢复不变量的组合证据。

工具与恢复还须区分三点：

- [ClientTool 152～172 行](https://github.com/OpenHands/software-agent-sdk/blob/d2ee0cdea60825608c2f8906eb54e1d4d264fb42/openhands-sdk/openhands/sdk/tool/client_tool.py#L152-L172) 立即返回 ACK 让循环继续，不提供 CloudHelm 的事务等待及结果续接。
- SDK 核心只默认加入 Finish/Think；[标准工程预设](https://github.com/OpenHands/software-agent-sdk/blob/d2ee0cdea60825608c2f8906eb54e1d4d264fb42/openhands-tools/openhands/tools/preset/default.py#L37-L63) 另加入本地 Terminal/FileEditor 和可选 Browser，不能当作已经通过本项目 Gateway 的工程工具。
- [会话状态 430～451 行](https://github.com/OpenHands/software-agent-sdk/blob/d2ee0cdea60825608c2f8906eb54e1d4d264fb42/openhands-sdk/openhands/sdk/conversation/state.py#L430-L451) 由 FileStore 保存，历史 EventLog 与 base 状态不等于现有 DBOS 检查点和业务历史；本轮不引入另一套持久化，也未验证历史格式迁移。

## 4. 后续实施落点

后续只沿 [A01 实施映射](../../implementation/p2-agent.md) 推进：A03 装配角色指令与有界工程内容；A04/A05 接通现有工作区读写和差异；A06～A08 接通已有环境、固定构建及必要检查；A09 沿现有 Session/Run/Operation/WaitCondition 组织循环。动作/观察仅用于明确工具输入及真实结果，不另存一套权威业务状态；不预建通用插件、符号地图或第二套调度器。

本决定不新增引擎迁移工作包。各能力仍逐项实现和估算，剩余总投入资料不足，保持待估；不把“不换引擎”换算成虚构的工时节省。下一项为待安排的 **P2.1-A03**，本次不启动。
